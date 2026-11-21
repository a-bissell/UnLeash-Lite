"""WebSocket hub for real-time fleet updates."""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth.jwt_handler import decode_token

logger = logging.getLogger("unleash.ws")

router = APIRouter()


async def _authenticate_ws(ws: WebSocket) -> bool:
    """Validate the access token passed as a ?token= query param.

    Browsers can't set Authorization headers on a WebSocket handshake, so the
    token rides in the query string. Closes the socket with 4401 on failure.
    """
    token = ws.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await ws.close(code=4401)
        return False
    return True


class WebSocketHub:
    def __init__(self):
        self._fleet_clients: list[WebSocket] = []
        self._event_clients: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect_fleet(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._fleet_clients.append(ws)

    async def disconnect_fleet(self, ws: WebSocket):
        async with self._lock:
            if ws in self._fleet_clients:
                self._fleet_clients.remove(ws)

    async def connect_events(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._event_clients.append(ws)

    async def disconnect_events(self, ws: WebSocket):
        async with self._lock:
            if ws in self._event_clients:
                self._event_clients.remove(ws)

    async def broadcast_fleet_update(self, data: dict):
        async with self._lock:
            dead = []
            for ws in self._fleet_clients:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._fleet_clients.remove(ws)

    async def broadcast_event(self, data: dict):
        async with self._lock:
            dead = []
            for ws in self._event_clients:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._event_clients.remove(ws)


hub = WebSocketHub()


def setup_broker_ws_hooks(broker):
    def on_connect(serial, client):
        asyncio.ensure_future(hub.broadcast_fleet_update({
            "type": "robot_connect",
            "serial": serial,
            "ip": client.ip_address,
            "timestamp": time.time(),
        }))
        asyncio.ensure_future(hub.broadcast_event({
            "type": "connect",
            "serial": serial,
            "timestamp": time.time(),
        }))

    def on_disconnect(serial):
        asyncio.ensure_future(hub.broadcast_fleet_update({
            "type": "robot_disconnect",
            "serial": serial,
            "timestamp": time.time(),
        }))
        asyncio.ensure_future(hub.broadcast_event({
            "type": "disconnect",
            "serial": serial,
            "timestamp": time.time(),
        }))

    def on_message(serial, topic, payload):
        try:
            data = json.loads(payload)
        except Exception:
            data = {"raw_length": len(payload)}
        asyncio.ensure_future(hub.broadcast_event({
            "type": "message",
            "serial": serial,
            "topic": topic,
            "data": data,
            "timestamp": time.time(),
        }))

    broker.on_connect(on_connect)
    broker.on_disconnect(on_disconnect)
    broker.on_message(on_message)


@router.websocket("/ws/fleet")
async def ws_fleet(ws: WebSocket):
    if not await _authenticate_ws(ws):
        return
    await hub.connect_fleet(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect_fleet(ws)


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    if not await _authenticate_ws(ws):
        return
    await hub.connect_events(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect_events(ws)
