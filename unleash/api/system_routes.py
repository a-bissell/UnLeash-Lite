"""System status and health check routes."""

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth.dependencies import CurrentUser, require_role

router = APIRouter(prefix="/system", tags=["system"])

_start_time = time.time()
_broker = None


def set_broker(broker):
    global _broker
    _broker = broker


class SystemStatus(BaseModel):
    status: str
    uptime_seconds: float
    connected_robots: int
    broker_events: int
    mqtt_tls: bool
    mqtt_port: int


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/status", response_model=SystemStatus)
async def system_status(_: CurrentUser = Depends(require_role("viewer"))):
    if not _broker:
        return SystemStatus(
            status="starting",
            uptime_seconds=time.time() - _start_time,
            connected_robots=0,
            broker_events=0,
            mqtt_tls=False,
            mqtt_port=0,
        )
    return SystemStatus(
        status="running",
        uptime_seconds=time.time() - _start_time,
        connected_robots=len(_broker.clients),
        broker_events=len(_broker.events),
        mqtt_tls=_broker.use_tls,
        mqtt_port=_broker.port,
    )
