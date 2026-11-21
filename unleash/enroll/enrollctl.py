"""
Guided enrollment flow: unleash enroll <robot-ip>

Takes a stock Unitree Go2 from factory state to fully managed in one
command, combining the jailbreak (init-ssh via sitecustomize.py injection)
with fleet setup (persistence, MQTT redirect, CA cert) that previously
required multiple manual steps.

Flow:
  [1/6] WebRTC connect + firmware auth detection
  [2/6] Upload init-ssh payload + two-press trigger
  [3/6] Wait for SSH to come up (poll port 22)
  [4/6] SSH in → clean sitecustomize.py → install ssh_guard.sh
  [5/6] Write /etc/hosts redirect → install CA cert → restart MQTT
  [6/6] Verify SSH + retrieve serial
"""

import asyncio
import logging
import socket

logger = logging.getLogger("unleash.enroll.enrollctl")

G = "\033[1;32m"
R = "\033[1;31m"
Y = "\033[1;33m"
C = "\033[1;36m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

SITECUSTOMIZE_PATHS = [
    "/usr/lib/python3.8/sitecustomize.py",
    "/usr/lib/python3.10/sitecustomize.py",
    "/usr/lib/python3.11/sitecustomize.py",
    "/usr/local/lib/python3.8/dist-packages/sitecustomize.py",
]


def _check_ssh(ip, port=22, timeout=2.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _get_local_ip():
    for target in ("192.168.123.161", "8.8.8.8"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            continue
    return None


class EnrollmentSession:
    """Guided single-command enrollment for a Unitree Go2.

    Orchestrates: WebRTC connect -> init-ssh payload -> two-press trigger ->
    SSH wait -> ssh_guard persistence -> /etc/hosts redirect -> CA cert ->
    MQTT restart -> verification.
    """

    def __init__(self, robot_ip, *, aes_key=None, password="unleash",
                 hotkey="L1+Y", broker_ip=None, port=9991,
                 skip_redirect=False, skip_persist=False,
                 manual_trigger=False):
        self.robot_ip = robot_ip
        self.aes_key = aes_key
        self.password = password
        self.hotkey = hotkey
        self.broker_ip = broker_ip or _get_local_ip()
        self.port = port
        self.skip_redirect = skip_redirect
        self.skip_persist = skip_persist
        self.manual_trigger = manual_trigger
        self._dc = None
        self._ssh = None
        self._serial = "unknown"

    async def run(self):
        """Execute the full enrollment flow. Returns True on success."""
        print()
        print(f"  {C}{'=' * 62}{RESET}")
        print(f"  {C}{BOLD}  UnLeash — enrolling robot at {self.robot_ip}{RESET}")
        print(f"  {C}{'=' * 62}{RESET}")
        print()

        try:
            ssh_already_up = _check_ssh(self.robot_ip)

            if ssh_already_up:
                print(f"  {G}[1/6]{RESET} Connecting via WebRTC       "
                      f"{DIM}skipped — SSH already up{RESET}")
                print(f"  {G}[2/6]{RESET} Deploying SSH access        "
                      f"{DIM}skipped — SSH already up{RESET}")
                print(f"  {G}[3/6]{RESET} Waiting for SSH             "
                      f"{G}✓{RESET}  already running")
            else:
                if not await self._step_connect():
                    return False
                if not await self._step_deploy_ssh():
                    return False
                if not await self._step_wait_ssh():
                    return False

            if not await self._step_post_ssh():
                return False

            if not self.skip_redirect:
                if not await self._step_redirect():
                    return False
            else:
                print(f"  {DIM}[5/6] MQTT redirect              skipped{RESET}")

            verified = await self._step_verify()
            self._print_summary(verified)
            return True

        except KeyboardInterrupt:
            print(f"\n  {Y}Enrollment cancelled.{RESET}")
            return False
        finally:
            await self._cleanup()

    async def _step_connect(self):
        """[1/6] Connect via WebRTC data channel."""
        from ..core.webrtc import Go2DataChannel, handshake

        print(f"  {G}[1/6]{RESET} Connecting via WebRTC...", end="", flush=True)

        try:
            handshake(self.robot_ip, self.port, self.aes_key)
        except ConnectionError as e:
            if "data2=3" in str(e) and not self.aes_key:
                print(f"       {Y}needs AES key{RESET}")
                print()
                print(f"  {C}  Firmware ≥1.1.15 detected — per-device AES key required.{RESET}")
                print(f"  {C}  Retrieve it: unleash fetch-key --email <your-unitree-email>{RESET}")
                print(f"  {C}  Then re-run: unleash enroll {self.robot_ip} --aes-key <key>{RESET}")
                return False
            print(f"       {R}✗{RESET}")
            print(f"  {R}  {e}{RESET}")
            return False

        try:
            self._dc = Go2DataChannel(
                self.robot_ip, self.port, aes_128_key=self.aes_key)
            await self._dc.connect(timeout=15)
            print(f"       {G}✓{RESET}  connected")
            return True
        except Exception as e:
            print(f"       {R}✗{RESET}")
            print(f"  {R}  WebRTC failed: {e}{RESET}")
            return False

    async def _step_deploy_ssh(self):
        """[2/6] Upload init-ssh payload and trigger twice."""
        from .payloads import payload_sitecustomize_ssh

        print(f"  {G}[2/6]{RESET} Deploying SSH access...", end="", flush=True)

        payload = payload_sitecustomize_ssh(
            password=self.password, hotkey=self.hotkey)

        status, _ = await self._dc.upload_program(
            payload.python_code, payload.program_uuid, self.hotkey)

        if status != 0:
            print(f"        {R}✗{RESET}  upload rejected (status {status})")
            return False

        if self.manual_trigger:
            print()
            print(f"  {Y}        ⚠  Press {self.hotkey} on controller TWICE:{RESET}")
            print(f"  {Y}           1st press: writes sitecustomize.py{RESET}")
            print(f"  {Y}           2nd press: activates SSH{RESET}")
            input(f"  {Y}           Press Enter after both presses... {RESET}")
            print(f"\r  {G}[2/6]{RESET} Deploying SSH access...     "
                  f"   {G}✓{RESET}  triggered (manual)")
        else:
            try:
                await self._dc.trigger_hotkey(self.hotkey)
                await asyncio.sleep(3.0)
                await self._dc.trigger_hotkey(self.hotkey)
                print(f"        {G}✓{RESET}  triggered (auto)")
            except Exception:
                print()
                print(f"  {Y}        ⚠  Auto-trigger failed.{RESET}")
                print(f"  {Y}           Press {self.hotkey} on controller TWICE, "
                      f"then press Enter.{RESET}")
                input(f"  {Y}           > {RESET}")
                print(f"\r  {G}[2/6]{RESET} Deploying SSH access...     "
                      f"   {G}✓{RESET}  triggered (manual)")

        return True

    async def _step_wait_ssh(self):
        """[3/6] Wait for SSH to come up."""
        print(f"  {G}[3/6]{RESET} Waiting for SSH...", end="", flush=True)

        for i in range(30):
            if _check_ssh(self.robot_ip):
                print(f"             {G}✓{RESET}  sshd running")
                await self._close_webrtc()
                return True
            await asyncio.sleep(1.0)

        print(f"             {R}✗{RESET}  timed out (30s)")
        print()
        print(f"  {Y}  SSH did not come up. Possible causes:{RESET}")
        print(f"  {Y}    - Auto-trigger didn't fire → try --manual{RESET}")
        print(f"  {Y}    - Only one press registered → press {self.hotkey} again{RESET}")
        print(f"  {Y}    - Firmware too old for sitecustomize technique{RESET}")
        print(f"  {Y}      → try: unleash jailbreak bypass-ssh{RESET}")
        return False

    async def _step_post_ssh(self):
        """[4/6] SSH in, clean up sitecustomize, install persistence."""
        print(f"  {G}[4/6]{RESET} Installing persistence...", end="", flush=True)

        try:
            import paramiko
        except ImportError:
            print(f"       {R}✗{RESET}")
            print(f"  {R}  paramiko is required for post-SSH setup.{RESET}")
            print(f"  {R}  Install it: pip install paramiko{RESET}")
            return False

        try:
            self._ssh = paramiko.SSHClient()
            self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._ssh.connect(
                self.robot_ip, username="root", password=self.password,
                timeout=10, look_for_keys=False, allow_agent=False)
        except Exception as e:
            print(f"       {R}✗{RESET}")
            print(f"  {R}  SSH login failed: {e}{RESET}")
            return False

        # Clean up sitecustomize.py — CRITICAL to prevent Python crash loops
        self._ssh_exec("rm -f " + " ".join(SITECUSTOMIZE_PATHS))

        if not self.skip_persist:
            from .payloads import SSH_GUARD_SCRIPT
            sftp = self._ssh.open_sftp()
            try:
                with sftp.file("/usr/local/bin/ssh_guard.sh", "w") as f:
                    f.write(SSH_GUARD_SCRIPT)
                sftp.chmod("/usr/local/bin/ssh_guard.sh", 0o755)
            finally:
                sftp.close()
            self._ssh_exec("/usr/local/bin/ssh_guard.sh install")

        print(f"       {G}✓{RESET}  ssh_guard.sh active")
        return True

    async def _step_redirect(self):
        """[5/6] Redirect MQTT traffic to UnLeash broker."""
        print(f"  {G}[5/6]{RESET} Redirecting to UnLeash broker...", end="", flush=True)

        if not self.broker_ip:
            print(f"  {Y}⚠{RESET}  cannot detect broker IP — pass --broker-ip")
            return True

        hosts_content = (
            "127.0.0.1 localhost\n"
            f"{self.broker_ip} global-robot-mqtt.unitree.com\n"
            f"{self.broker_ip} robot-mqtt.unitree.com\n"
        )

        sftp = self._ssh.open_sftp()
        try:
            with sftp.file("/etc/hosts", "w") as f:
                f.write(hosts_content)
        finally:
            sftp.close()

        self._install_ca_cert()

        self._ssh_exec(
            "systemctl restart unitree_mqtt_client 2>/dev/null; "
            "systemctl restart mqtt_client 2>/dev/null; true"
        )

        print(f" {G}✓{RESET}  /etc/hosts updated")
        return True

    def _install_ca_cert(self):
        """Copy our CA cert to the robot's trust store."""
        from ..certs.generator import generate_self_signed, DEFAULT_CERT_DIR

        ca_cert = DEFAULT_CERT_DIR / "ca.pem"
        if not ca_cert.exists():
            try:
                generate_self_signed()
            except Exception as e:
                logger.debug("CA cert generation failed: %s", e)
                return

        if not ca_cert.exists():
            return

        try:
            sftp = self._ssh.open_sftp()
            try:
                sftp.put(str(ca_cert),
                         "/usr/local/share/ca-certificates/unleash-ca.crt")
            finally:
                sftp.close()
            self._ssh_exec("update-ca-certificates 2>/dev/null || true")
        except Exception as e:
            logger.debug("CA cert install failed: %s", e)

    async def _step_verify(self):
        """[6/6] Verify the enrollment succeeded."""
        print(f"  {G}[6/6]{RESET} Verifying enrollment...", end="", flush=True)

        if not _check_ssh(self.robot_ip):
            print(f"          {Y}⚠{RESET}  SSH check failed")
            return False

        self._serial = self._ssh_exec(
            "cat /etc/serial_number 2>/dev/null || "
            "cat /unitree/etc/serial_number 2>/dev/null || "
            "echo unknown"
        ).strip() or "unknown"

        guard_ok = True
        if not self.skip_persist:
            guard_status = self._ssh_exec(
                "systemctl is-active ssh-guard.service 2>/dev/null"
            ).strip()
            guard_ok = guard_status in ("active", "activating")

        if guard_ok:
            print(f"          {G}✓{RESET}  enrolled")
        else:
            print(f"          {G}✓{RESET}  enrolled "
                  f"{DIM}(ssh_guard pending){RESET}")

        return True

    def _print_summary(self, verified):
        serial = self._serial
        ip = self.robot_ip
        pw = self.password

        ssh_str = f"ssh root@{ip}"
        dashboard_str = f"http://{self.broker_ip}:8080" if self.broker_ip else ""

        w = 43
        print()
        print(f"  {G}┌{'─' * w}┐{RESET}")
        print(f"  {G}│{RESET}  Serial:    {serial:<{w - 14}}{G}│{RESET}")
        print(f"  {G}│{RESET}  SSH:       {ssh_str:<{w - 14}}{G}│{RESET}")
        print(f"  {G}│{RESET}  Password:  {pw:<{w - 14}}{G}│{RESET}")
        if dashboard_str and not self.skip_redirect:
            print(f"  {G}│{RESET}  Dashboard: {dashboard_str:<{w - 14}}{G}│{RESET}")
        print(f"  {G}└{'─' * w}┘{RESET}")
        print()
        if not self.skip_redirect:
            print(f"  Run {C}unleash serve{RESET} to start the management dashboard.")
        print()

    def _ssh_exec(self, cmd):
        if not self._ssh:
            return ""
        try:
            _, stdout, _ = self._ssh.exec_command(cmd, timeout=15)
            return stdout.read().decode(errors="replace")
        except Exception as e:
            logger.debug("SSH exec failed (%s): %s", cmd[:60], e)
            return ""

    async def _close_webrtc(self):
        if self._dc:
            await self._dc.close()
            self._dc = None

    async def _cleanup(self):
        await self._close_webrtc()
        if self._ssh:
            self._ssh.close()
            self._ssh = None
