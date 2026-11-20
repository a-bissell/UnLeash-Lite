"""MQTT 3.1.1 packet encoding and decoding."""

import struct

CONNECT = 1
CONNACK = 2
PUBLISH = 3
PUBACK = 4
SUBSCRIBE = 8
SUBACK = 9
UNSUBSCRIBE = 10
UNSUBACK = 11
PINGREQ = 12
PINGRESP = 13
DISCONNECT = 14


def encode_remaining_length(n: int) -> bytes:
    out = []
    while True:
        byte = n % 128
        n //= 128
        if n > 0:
            byte |= 0x80
        out.append(byte)
        if n == 0:
            break
    return bytes(out)


def decode_remaining_length(data: bytes, offset: int) -> tuple[int, int]:
    mult, value = 1, 0
    while True:
        byte = data[offset]
        offset += 1
        value += (byte & 0x7F) * mult
        mult *= 128
        if not (byte & 0x80):
            break
    return value, offset


def read_utf8_string(data: bytes, offset: int) -> tuple[str, int]:
    length = struct.unpack("!H", data[offset:offset + 2])[0]
    offset += 2
    s = data[offset:offset + length].decode("utf-8", errors="replace")
    return s, offset + length


def make_connack(return_code: int, session_present: bool = False) -> bytes:
    flags = 0x01 if session_present else 0x00
    return bytes([CONNACK << 4, 2, flags, return_code])


def make_publish(topic: str, payload: bytes, qos: int = 0) -> bytes:
    topic_bytes = topic.encode()
    packet_body = struct.pack("!H", len(topic_bytes)) + topic_bytes
    if qos > 0:
        packet_body += struct.pack("!H", 1)
    packet_body += payload
    flags = (qos & 0x03) << 1
    header = bytes([(PUBLISH << 4) | flags]) + encode_remaining_length(len(packet_body))
    return header + packet_body


def make_suback(msg_id: int, granted_qos: list[int]) -> bytes:
    body = struct.pack("!H", msg_id) + bytes(granted_qos)
    return bytes([SUBACK << 4]) + encode_remaining_length(len(body)) + body


def make_unsuback(msg_id: int) -> bytes:
    return bytes([UNSUBACK << 4, 2]) + struct.pack("!H", msg_id)


def make_puback(msg_id: int) -> bytes:
    return bytes([PUBACK << 4, 2]) + struct.pack("!H", msg_id)
