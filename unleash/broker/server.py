"""MQTT broker for Unitree robot fleet management.

Implements MQTT 3.1.1 as a drop-in replacement for global-robot-mqtt.unitree.com:17883.
Robots connect, authenticate with their serial-based credentials, subscribe to
cmd/<serial>, and the platform can publish commands to that topic.
"""

import asyncio
import logging
import ssl
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .auth import AuthProvider, UnitreeAuthProvider, NoAuthProvider
from .protocol import (
    CONNECT, CONNACK, PUBLISH, PUBACK, SUBSCRIBE, SUBACK,
    UNSUBSCRIBE, UNSUBACK, PINGREQ, PINGRESP, DISCONNECT,
    encode_remaining_length, read_utf8_string,
    make_connack, make_publish, make_suback, make_unsuback, make_puback,
)

logger = logging.getLogger("unleash.broker")


@dataclass
class MQTTClient:
    writer: asyncio.StreamWriter
    serial: str = ""
    client_id: str = ""
    subscriptions: list[str] = field(default_factory=list)
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    ip_address: str = ""


@dataclass
class BrokerEvent:
    timestamp: float
    event_type: str
    serial: str
    detail: str = ""


class UnleashBroker:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 17883,
        cert_path: Path | None = None,
        key_path: Path | None = None,
        auth_provider: AuthProvider | None = None,
        require_auth: bool = True,
        use_tls: bool = True,
        allowed_serials: list[str] | None = None,
    ):
        self.host = host
        self.port = port
        self.cert_path = cert_path
        self.key_path = key_path
        self.require_auth = require_auth
        self.use_tls = use_tls
        self.allowed_serials = allowed_serials
        self.auth_provider: AuthProvider = auth_provider or (
            UnitreeAuthProvider() if require_auth else NoAuthProvider()
        )
        self.clients: dict[str, MQTTClient] = {}
        self.events: list[BrokerEvent] = []
        self._server: asyncio.Server | None = None
        self._on_message_callbacks: list[Callable] = []
        self._on_connect_callbacks: list[Callable] = []
        self._on_disconnect_callbacks: list[Callable] = []
        self._max_events = 10000

    def on_message(self, callback: Callable):
        self._on_message_callbacks.append(callback)

    def on_connect(self, callback: Callable):
        self._on_connect_callbacks.append(callback)

    def on_disconnect(self, callback: Callable):
        self._on_disconnect_callbacks.append(callback)

    def _log_event(self, event_type: str, serial: str, detail: str = ""):
        ev = BrokerEvent(time.time(), event_type, serial, detail)
        self.events.append(ev)
        if len(self.events) > self._max_events:
            self.events = self.events[-self._max_events // 2:]

    async def start(self):
        ssl_ctx = None
        if self.use_tls:
            if self.cert_path and self.key_path:
                ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_ctx.load_cert_chain(str(self.cert_path), str(self.key_path))
            else:
                from ..certs.generator import generate_self_signed
                cert_path, key_path = generate_self_signed()
                ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_ctx.load_cert_chain(str(cert_path), str(key_path))
                self.cert_path = cert_path
                self.key_path = key_path

        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port, ssl=ssl_ctx,
            reuse_address=True, reuse_port=True,
        )
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        tls_status = "TLS" if ssl_ctx else "plaintext"
        logger.info(f"MQTT broker listening on {addrs} ({tls_status})")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for client in list(self.clients.values()):
            try:
                client.writer.close()
            except Exception:
                pass

    async def publish_to_robot(self, serial: str, topic: str, payload: str | bytes, qos: int = 0) -> bool:
        client = self.clients.get(serial)
        if not client:
            return False
        if isinstance(payload, str):
            payload = payload.encode()
        try:
            client.writer.write(make_publish(topic, payload, qos))
            await client.writer.drain()
            self._log_event("command", serial, f"topic={topic} len={len(payload)}")
            return True
        except Exception as e:
            logger.error(f"Failed to publish to {serial}: {e}")
            return False

    async def send_command(self, serial: str, payload: str | bytes) -> bool:
        return await self.publish_to_robot(serial, f"cmd/{serial}", payload)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        client = MQTTClient(writer=writer, ip_address=str(addr[0]) if addr else "")

        try:
            header_byte = await asyncio.wait_for(reader.readexactly(1), timeout=30)
            ptype = header_byte[0] >> 4
            if ptype != CONNECT:
                writer.close()
                return

            _, body = await self._read_remaining(reader)
            accepted, serial = self._process_connect(body, client)
            writer.write(make_connack(0 if accepted else 4))
            await writer.drain()

            if not accepted:
                logger.info(f"Auth rejected from {addr}: {client.client_id}")
                writer.close()
                return

            self.clients[serial] = client
            self._log_event("connect", serial, f"from {addr}")
            for cb in self._on_connect_callbacks:
                try:
                    cb(serial, client)
                except Exception:
                    pass
            logger.info(f"Robot connected: {serial} from {addr}")

            await self._client_loop(reader, client)

        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError, OSError):
            pass
        finally:
            if client.serial and client.serial in self.clients:
                del self.clients[client.serial]
                self._log_event("disconnect", client.serial)
                for cb in self._on_disconnect_callbacks:
                    try:
                        cb(client.serial)
                    except Exception:
                        pass
                logger.info(f"Robot disconnected: {client.serial}")
            try:
                writer.close()
            except Exception:
                pass

    async def _client_loop(self, reader: asyncio.StreamReader, client: MQTTClient):
        while True:
            header_byte = await asyncio.wait_for(reader.readexactly(1), timeout=90)
            ptype = header_byte[0] >> 4
            client.last_seen = time.time()

            if ptype == PINGREQ:
                await reader.readexactly(1)
                client.writer.write(bytes([PINGRESP << 4, 0]))
                await client.writer.drain()

            elif ptype == SUBSCRIBE:
                _, body = await self._read_remaining(reader)
                self._process_subscribe(body, client)

            elif ptype == PUBLISH:
                flags = header_byte[0] & 0x0F
                _, body = await self._read_remaining(reader)
                self._process_publish(body, flags, client)

            elif ptype == DISCONNECT:
                break

            elif ptype == UNSUBSCRIBE:
                _, body = await self._read_remaining(reader)
                self._process_unsubscribe(body, client)

            else:
                _, _ = await self._read_remaining(reader)

    async def _read_remaining(self, reader: asyncio.StreamReader) -> tuple[int, bytes]:
        remaining = 0
        mult = 1
        while True:
            b = (await reader.readexactly(1))[0]
            remaining += (b & 0x7F) * mult
            mult *= 128
            if not (b & 0x80):
                break
        body = await reader.readexactly(remaining) if remaining > 0 else b""
        return remaining, body

    def _process_connect(self, body: bytes, client: MQTTClient) -> tuple[bool, str]:
        offset = 0
        _, offset = read_utf8_string(body, offset)  # protocol name
        offset += 1  # protocol level
        flags = body[offset]
        offset += 1
        has_username = bool(flags & 0x80)
        has_password = bool(flags & 0x40)
        offset += 2  # keepalive

        client_id, offset = read_utf8_string(body, offset)
        client.client_id = client_id

        username = ""
        password = ""
        if has_username:
            username, offset = read_utf8_string(body, offset)
        if has_password:
            password, offset = read_utf8_string(body, offset)

        accepted, serial, reason = self.auth_provider.authenticate(username, password, client_id)
        if not accepted:
            logger.info(f"Auth failed: {reason} (user={username}, cid={client_id})")
            return False, ""

        if self.allowed_serials and serial not in self.allowed_serials:
            logger.info(f"Serial {serial} not in allowed list")
            return False, ""

        client.serial = serial or ""
        return True, client.serial

    def _process_subscribe(self, body: bytes, client: MQTTClient):
        offset = 0
        msg_id = struct.unpack("!H", body[offset:offset + 2])[0]
        offset += 2

        granted_qos = []
        while offset < len(body):
            topic, offset = read_utf8_string(body, offset)
            qos = body[offset]
            offset += 1
            client.subscriptions.append(topic)
            granted_qos.append(min(qos, 1))
            self._log_event("subscribe", client.serial, topic)
            logger.info(f"Robot {client.serial} subscribed to: {topic}")

        client.writer.write(make_suback(msg_id, granted_qos))

    def _process_publish(self, body: bytes, flags: int, client: MQTTClient):
        offset = 0
        topic, offset = read_utf8_string(body, offset)
        qos = (flags >> 1) & 0x03
        if qos > 0:
            msg_id = struct.unpack("!H", body[offset:offset + 2])[0]
            offset += 2
            client.writer.write(make_puback(msg_id))

        payload = body[offset:]
        self._log_event("publish", client.serial, f"topic={topic} len={len(payload)}")

        for cb in self._on_message_callbacks:
            try:
                cb(client.serial, topic, payload)
            except Exception:
                pass

    def _process_unsubscribe(self, body: bytes, client: MQTTClient):
        offset = 0
        msg_id = struct.unpack("!H", body[offset:offset + 2])[0]
        offset += 2
        while offset < len(body):
            topic, offset = read_utf8_string(body, offset)
            if topic in client.subscriptions:
                client.subscriptions.remove(topic)
        client.writer.write(make_unsuback(msg_id))
