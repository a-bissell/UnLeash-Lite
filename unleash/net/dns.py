"""Lightweight DNS redirector for MQTT-first enrollment.

Answers A queries for Unitree MQTT hostnames with the broker's IP.
All other queries get SERVFAIL so the client falls back to its
secondary resolver (if any) for normal internet access.

Usage during enrollment:
  1. Start this on the LAN (e.g. on the machine running UnleashBroker)
  2. Point the robot's DNS here (via DHCP, router config, or ARP)
  3. Robot resolves global-robot-mqtt.unitree.com → broker IP
  4. Robot connects to your broker instead of Unitree's cloud
"""

import asyncio
import logging
import struct

logger = logging.getLogger("unleash.net.dns")

REDIRECT_HOSTS = {
    "global-robot-mqtt.unitree.com",
    "robot-mqtt.unitree.com",
}

# DNS constants
_QR_RESPONSE = 0x8000
_AA_FLAG = 0x0400
_RCODE_OK = 0
_RCODE_SERVFAIL = 2
_TYPE_A = 1
_CLASS_IN = 1
_DEFAULT_TTL = 60


def _decode_name(data: bytes, offset: int) -> tuple[str, int]:
    """Decode a DNS domain name from wire format, handling compression."""
    labels = []
    jumped = False
    return_offset = offset
    seen = set()

    while offset < len(data):
        if offset in seen:
            break
        seen.add(offset)

        length = data[offset]

        if length & 0xC0 == 0xC0:
            if not jumped:
                return_offset = offset + 2
            pointer = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            offset = pointer
            jumped = True
            continue

        if length == 0:
            if not jumped:
                return_offset = offset + 1
            break

        offset += 1
        labels.append(data[offset:offset + length].decode("ascii", errors="replace"))
        offset += length

    return ".".join(labels).lower(), return_offset


def _encode_name(name: str) -> bytes:
    """Encode a domain name to DNS wire format."""
    parts = []
    for label in name.split("."):
        encoded = label.encode("ascii")
        parts.append(bytes([len(encoded)]) + encoded)
    parts.append(b"\x00")
    return b"".join(parts)


def _build_response(query: bytes, broker_ip: str, redirect_hosts: set[str]) -> bytes:
    """Build a DNS response for a query packet."""
    if len(query) < 12:
        return b""

    txn_id = query[:2]
    flags = struct.unpack("!H", query[2:4])[0]
    qdcount = struct.unpack("!H", query[4:6])[0]

    if qdcount == 0:
        return b""

    qname, offset = _decode_name(query, 12)
    if offset + 4 > len(query):
        return b""
    qtype = struct.unpack("!H", query[offset:offset + 2])[0]
    qclass = struct.unpack("!H", query[offset + 2:offset + 4])[0]

    if qname in redirect_hosts and qtype == _TYPE_A and qclass == _CLASS_IN:
        resp_flags = _QR_RESPONSE | _AA_FLAG | _RCODE_OK
        ip_bytes = bytes(int(o) for o in broker_ip.split("."))

        header = struct.pack("!HHHHHH",
            struct.unpack("!H", txn_id)[0],
            resp_flags,
            1,  # qdcount
            1,  # ancount
            0,  # nscount
            0,  # arcount
        )

        question = query[12:offset + 4]

        answer = (
            _encode_name(qname)
            + struct.pack("!HHiH", _TYPE_A, _CLASS_IN, _DEFAULT_TTL, 4)
            + ip_bytes
        )

        return header + question + answer

    resp_flags = _QR_RESPONSE | _RCODE_SERVFAIL
    header = struct.pack("!HHHHHH",
        struct.unpack("!H", txn_id)[0],
        resp_flags,
        qdcount,
        0, 0, 0,
    )
    return header + query[12:offset + 4]


class DNSRedirectProtocol(asyncio.DatagramProtocol):
    """asyncio UDP protocol that redirects DNS queries for target hostnames."""

    def __init__(self, broker_ip: str, redirect_hosts: set[str] | None = None):
        self.broker_ip = broker_ip
        self.redirect_hosts = redirect_hosts or REDIRECT_HOSTS
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        response = _build_response(data, self.broker_ip, self.redirect_hosts)
        if response and self.transport:
            self.transport.sendto(response, addr)

            if len(data) >= 12:
                qname, _ = _decode_name(data, 12)
                if qname in self.redirect_hosts:
                    logger.info("redirected %s → %s (from %s)", qname, self.broker_ip, addr[0])


class MQTTDNSRedirector:
    """Minimal DNS server that redirects Unitree MQTT hostnames to the broker.

    For queries matching the redirect set, responds with the broker IP.
    For everything else, returns SERVFAIL.
    """

    def __init__(
        self,
        broker_ip: str,
        listen: str = "0.0.0.0",
        port: int = 53,
        redirect_hosts: set[str] | None = None,
    ):
        self.broker_ip = broker_ip
        self.listen = listen
        self.port = port
        self.redirect_hosts = redirect_hosts or REDIRECT_HOSTS
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self):
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: DNSRedirectProtocol(self.broker_ip, self.redirect_hosts),
            local_addr=(self.listen, self.port),
        )
        logger.info(
            "DNS redirector listening on %s:%d — %s → %s",
            self.listen, self.port,
            ", ".join(sorted(self.redirect_hosts)),
            self.broker_ip,
        )

    async def stop(self):
        if self._transport:
            self._transport.close()
            self._transport = None
