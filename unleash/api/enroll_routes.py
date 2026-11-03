"""Enrollment API routes — kick off browser-driven enrollment and stream
progress to the frontend via WebSocket."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..auth.dependencies import CurrentUser, require_role
from ..auth.jwt_handler import decode_token

logger = logging.getLogger("unleash.api.enroll")

router = APIRouter(prefix="/enroll", tags=["enrollment"])
ws_router = APIRouter()

_active_sessions: dict[str, "EnrollWsRelay"] = {}


class EnrollRequest(BaseModel):
    robot_ip: str
    aes_key: str | None = None
    password: str = "unleash"
    broker_ip: str | None = None
    manual_trigger: bool = False
    skip_redirect: bool = False
    skip_persist: bool = False


class EnrollWsRelay:
    """Bridges an EnrollmentSession's progress into a WebSocket."""

    def __init__(self):
        self.clients: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.clients.append(ws)

    async def remove(self, ws: WebSocket):
        async with self._lock:
            if ws in self.clients:
                self.clients.remove(ws)

    async def send(self, data: dict):
        async with self._lock:
            dead = []
            for ws in self.clients:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.clients.remove(ws)


async def _run_enrollment(relay: EnrollWsRelay, req: EnrollRequest):
    """Run EnrollmentSession in the background, streaming step events."""
    from ..enroll.enrollctl import EnrollmentSession, _check_ssh

    session = EnrollmentSession(
        req.robot_ip,
        aes_key=req.aes_key,
        password=req.password,
        broker_ip=req.broker_ip,
        skip_redirect=req.skip_redirect,
        skip_persist=req.skip_persist,
        manual_trigger=req.manual_trigger,
    )

    steps = [
        ("1/6", "Connecting via WebRTC"),
        ("2/6", "Deploying SSH access"),
        ("3/6", "Waiting for SSH"),
        ("4/6", "Installing persistence"),
        ("5/6", "Redirecting to broker"),
        ("6/6", "Verifying enrollment"),
    ]

    async def step_event(num, status, detail=""):
        await relay.send({"type": "step", "step": num, "status": status, "detail": detail})

    async def feed(message, badge="system", label="ENROLL"):
        await relay.send({"type": "feed", "badge": badge, "label": label, "message": message})

    try:
        ssh_already_up = _check_ssh(req.robot_ip)

        if ssh_already_up:
            for num, lbl in steps[:3]:
                await step_event(num, "skip" if num != "3/6" else "done",
                                 "SSH already up" if num != "3/6" else "already running")
        else:
            await step_event("1/6", "active")
            await feed("Connecting to robot via WebRTC...")
            ok = await session._step_connect()
            if not ok:
                await step_event("1/6", "fail", "WebRTC connection failed")
                await relay.send({"type": "error", "message": "WebRTC connection failed"})
                return

            await step_event("1/6", "done", "connected")
            await step_event("2/6", "active")
            await feed("Deploying SSH payload...")
            ok = await session._step_deploy_ssh()
            if not ok:
                await step_event("2/6", "fail", "SSH deploy failed")
                await relay.send({"type": "error", "message": "SSH deploy failed"})
                return

            await step_event("2/6", "done", "payload triggered")
            await step_event("3/6", "active")
            await feed("Waiting for SSH to come up...")
            ok = await session._step_wait_ssh()
            if not ok:
                await step_event("3/6", "fail", "SSH timed out (30s)")
                await relay.send({"type": "error", "message": "SSH did not come up within 30s"})
                return
            await step_event("3/6", "done", "sshd running")

        await step_event("4/6", "active")
        await feed("Installing persistence via SSH...")
        ok = await session._step_post_ssh()
        if not ok:
            await step_event("4/6", "fail", "SSH post-setup failed")
            await relay.send({"type": "error", "message": "Post-SSH setup failed"})
            return
        await step_event("4/6", "done", "ssh_guard active")

        if not req.skip_redirect:
            await step_event("5/6", "active")
            await feed("Redirecting MQTT to UnLeash broker...")
            ok = await session._step_redirect()
            if not ok:
                await step_event("5/6", "fail", "MQTT redirect failed")
                await relay.send({"type": "error", "message": "MQTT redirect failed"})
                return
            await step_event("5/6", "done", "/etc/hosts updated")
        else:
            await step_event("5/6", "skip", "skipped")

        await step_event("6/6", "active")
        await feed("Verifying enrollment...")
        verified = await session._step_verify()
        await step_event("6/6", "done" if verified else "fail",
                         "enrolled" if verified else "verification failed")

        await relay.send({
            "type": "complete",
            "result": {
                "serial": session._serial,
                "ssh": f"ssh root@{req.robot_ip}",
                "dashboard": f"http://{session.broker_ip}:8080" if session.broker_ip else "",
            },
        })
    except Exception as e:
        logger.exception("Enrollment failed")
        await relay.send({"type": "error", "message": str(e)})
    finally:
        await session._cleanup()
        _active_sessions.pop(req.robot_ip, None)


@router.post("/start")
async def start_enrollment(
    body: EnrollRequest,
    user: CurrentUser = Depends(require_role("operator")),
):
    if body.robot_ip in _active_sessions:
        raise HTTPException(status_code=409, detail="Enrollment already in progress for this robot")

    relay = EnrollWsRelay()
    _active_sessions[body.robot_ip] = relay
    asyncio.ensure_future(_run_enrollment(relay, body))
    return {"status": "started", "robot_ip": body.robot_ip}


@ws_router.websocket("/ws/enroll")
async def ws_enroll(ws: WebSocket):
    token = ws.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await ws.close(code=4401)
        return

    # Attach to whichever enrollment session is active (there's usually one).
    relay = next(iter(_active_sessions.values()), None)
    if relay is None:
        relay = EnrollWsRelay()

    await relay.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await relay.remove(ws)
