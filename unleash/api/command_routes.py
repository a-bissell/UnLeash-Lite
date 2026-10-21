"""Command API routes for sending MQTT commands to robots."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import CurrentUser, require_role
from ..audit.logger import log_action
from ..db.engine import get_session

router = APIRouter(prefix="/command", tags=["commands"])

_broker = None


def set_broker(broker):
    global _broker
    _broker = broker


class CommandRequest(BaseModel):
    payload: dict | str


@router.post("/{serial}")
async def send_command(
    serial: str,
    body: CommandRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("operator")),
    session: AsyncSession = Depends(get_session),
):
    if not _broker:
        raise HTTPException(status_code=503, detail="Broker not available")
    if serial not in _broker.clients:
        raise HTTPException(status_code=404, detail="Robot not connected")

    payload = body.payload if isinstance(body.payload, str) else json.dumps(body.payload)
    success = await _broker.send_command(serial, payload)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send command")

    await log_action(
        session, user.username, "send_command",
        user_id=user.user_id,
        target_type="robot", target_id=serial,
        detail={"payload": body.payload},
        ip_address=request.client.host if request.client else None,
    )
    return {"status": "sent", "serial": serial}


@router.post("/broadcast")
async def broadcast(
    body: CommandRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    if not _broker:
        raise HTTPException(status_code=503, detail="Broker not available")

    payload = body.payload if isinstance(body.payload, str) else json.dumps(body.payload)
    sent = []
    for serial in list(_broker.clients.keys()):
        if await _broker.send_command(serial, payload):
            sent.append(serial)

    await log_action(
        session, user.username, "broadcast_command",
        user_id=user.user_id,
        detail={"payload": body.payload, "sent_to": sent},
        ip_address=request.client.host if request.client else None,
    )
    return {"status": "sent", "count": len(sent), "serials": sent}
