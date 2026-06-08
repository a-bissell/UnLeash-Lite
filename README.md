<div align="center">

```
 _   _       _                    _
| | | |_ __ | |    ___  __ _ ___| |__
| | | | '_ \| |   / _ \/ _` / __| '_ \
| |_| | | | | |__|  __/ (_| \__ \ | | |
 \___/|_| |_|_____\___|\__,_|___/_| |_|
                  lite
```

**Root access for the Unitree Go2. Your robot, your rules.**

</div>

UnLeash Lite uploads Python payloads to the Go2 over its WebRTC data channel and executes them as root. No physical controller needed. The tool connects through the robot's HTTP signaling endpoint, uploads a payload via the WebRTC bridge, and triggers execution by sending a fake controller button press through the same bridge -- all from inside the DDS security perimeter.

## Quick Start

### Firmware <= 1.1.13

```bash
pip install .
python -m unleash_lite ssh
```

Wait for the callback confirmation, then:

```bash
ssh root@192.168.123.161
# password: unleash
```

### Firmware 1.1.14+

```bash
pip install .
python -m unleash_lite bypass-ssh
```

Wait up to 60 seconds for the cron job, then SSH in.

### Firmware 1.1.15+

Same as 1.1.14, but you need your robot's AES key:

```bash
pip install .
python -m unleash_lite fetch-key --email you@example.com
python -m unleash_lite bypass-ssh --aes-key <your-32-hex-char-key>
```

Wait up to 60 seconds, then SSH in.

> **Custom password:** Add `--password <your-password>` to any command above.

### What just happened?

1. Connected to the robot's HTTP signaling endpoint (port 9991) and established a WebRTC data channel
2. Uploaded a Python payload to `programming_actuator` via the bridge, bound to the L1+Y hotkey
3. Sent a fake L1+Y controller button press through the bridge to `rt/wirelesscontroller`
4. The bridge forwarded both the upload and the trigger to the internal DDS bus from inside the DDS security perimeter
5. `programming_actuator` executed the payload as root

No physical controller. No DDS multicast. No CycloneDDS dependency.

## Install

```bash
pip install .
```

That's it. The primary jailbreak path has no extra dependencies beyond the base package (aiortc, pycryptodome, cryptography, requests, curl_cffi).

## Firmware Support

| Firmware | Command | AES Key? | Status |
|----------|---------|----------|--------|
| <= 1.1.13 | `ssh` | No | Confirmed |
| 1.1.14 | `bypass-ssh` | No | Confirmed (benchtop) |
| >= 1.1.15 | `bypass-ssh --aes-key KEY` | Yes | Confirmed (benchtop) |

All firmware versions use the same attack chain: HTTP signaling into the WebRTC bridge, upload via `programming_actuator`, trigger via fake controller press. The bridge sits inside the DDS security perimeter and forwards both operations to the internal DDS bus.

> **Note on firmware 1.1.14+:** Unitree added a keyword blocklist and seccomp sandbox to `programming_actuator`. The `bypass-*` modes encode payloads as byte arrays and use `np.savetxt` for file I/O to evade the filter. `bypass-ssh` and `bypass-cron` escape the seccomp sandbox by staging commands as cron jobs that execute outside the sandbox.

## Modes

| Mode | Firmware | Description |
|------|----------|-------------|
| `ssh` | <= 1.1.13 | Enable SSH and set root password |
| `ssh-persist` | <= 1.1.13 | Persistent SSH with guard service (survives reboots + OTA) |
| `custom` | <= 1.1.13 | Run any shell command as root |
| `reverse-shell` | <= 1.1.13 | Reverse shell to a specified IP |
| `bypass-ssh` | all | Enable SSH via cron job (bypasses keyword blocklist) |
| `bypass-hosts` | all | Write MQTT DNS redirect to `/etc/hosts` |
| `bypass-file` | all | Write arbitrary file content |
| `bypass-cron` | all | Install a cron job for command execution |
| `bypass-escalate` | all | Two-press self-overwrite for unfiltered Python execution |

## Fetching the AES Key (firmware >= 1.1.15)

Firmware 1.1.15 added per-device AES-128 authentication to the HTTP signaling endpoint. You need the robot's key (32 hex characters) to connect.

```bash
# Print keys for all robots on your account
python -m unleash_lite fetch-key --email you@example.com

# Get key for a specific robot
python -m unleash_lite fetch-key --email you@example.com --sn B42D2000XXXXXXXX
```

If you already have SSH access, read it directly:

```bash
ssh root@192.168.123.161 'xxd -p /unitree/etc/key/aes_key.bin'
```

On firmware 1.1.14 and below, `--aes-key` is not needed.

## Standalone Trigger

The `trigger` subcommand sends a fake controller button press without uploading a payload. Use it to fire a previously staged hotkey binding:

```bash
# Via bridge (default, works on production robots)
python -m unleash_lite trigger --robot-ip 192.168.123.161

# Via DDS multicast (benchtop boards without DDS Security only)
python -m unleash_lite trigger --via dds --interface-ip 192.168.123.100
```

The bridge trigger connects via HTTP signaling and sends the button press through the WebRTC data channel. The jailbreak commands run this automatically after upload.

## CLI Reference

```bash
python -m unleash_lite <mode> [options]
```

```
--robot-ip IP         Robot IP address (default: 192.168.123.161)
--port PORT           WebRTC signaling port (default: 9991)
--aes-key KEY         Per-device AES-128 key for firmware >= 1.1.15 (32 hex chars)
--hotkey HOTKEY       Controller hotkey binding (default: L1+Y)
--password PASS       Root password for ssh modes (default: unleash)
--cmd CMD             Shell command for custom / bypass-cron mode
--attacker-ip IP      Target IP for reverse-shell / bypass-hosts
--file-path PATH      Target file path for bypass-file mode
--content TEXT        File content for bypass-file mode
--code CODE           Unfiltered Python code for bypass-escalate mode
--callback-ip IP      This machine's IP for verification (auto-detected)
--callback-port PORT  Callback listener port (default: 19999)
--no-callback         Skip callback verification
--timeout SECS        Callback wait timeout (default: 120s)
--debug               Enable debug logging
```

### Other subcommands

```bash
python -m unleash_lite fetch-key --email you@example.com [--sn SERIAL]
python -m unleash_lite probe [--aes-key KEY] [--debug]
python -m unleash_lite trigger [--robot-ip IP] [--via bridge|dds]
```

## How It Works

### The WebRTC Bridge Bypass

The Go2 runs DDS Security (PKI-DH authentication) on its internal DDS bus, which prevents external devices from directly publishing to DDS topics. This blocks the direct DDS attack documented in [CVE-2026-27509](https://nvd.nist.gov/vuln/detail/CVE-2026-27509).

However, the robot's `webrtc_bridge` service (`unitreeWebRTCClientMaster`) is an internal DDS participant with valid security credentials. It bridges between the WebRTC data channel and the DDS bus, forwarding messages in both directions. Any LAN-adjacent device that can reach the HTTP signaling endpoint (port 9991) can establish a WebRTC data channel and send messages that the bridge publishes to internal DDS topics from inside the security perimeter.

This bypasses DDS Security entirely. The bridge does not filter which topics it writes to or what message types it forwards. Confirmed working:

- **Upload:** `rt/api/programming_actuator/request` (api_id=1002) -- uploads Python code bound to a controller hotkey
- **Trigger:** `rt/wirelesscontroller` -- fake controller button press, received by `programming_actuator` which executes the bound script as root
- **Telemetry:** `rt/lf/lowstate` -- IMU and motor state readable via subscribe

The upload and trigger happen over the same WebRTC connection. No physical controller is involved at any point.

### Firmware Defenses

| Defense | Added in | What it does | How it's bypassed |
|---------|----------|-------------|-------------------|
| DDS Security (PKI-DH) | ~1.1.x | Blocks external DDS participants | WebRTC bridge is inside the perimeter |
| Keyword blocklist | 1.1.14 | Scans Python source for ~180 blocked keywords | `str(bytes([...]))` encoding + `np.savetxt` for file I/O |
| seccomp sandbox | 1.1.14 | Restricts syscalls in Python execution | Write to `/etc/cron.d/`, cron runs outside sandbox |
| UUID validation | 1.1.14 | Requires 10-digit numeric UUID | `str(int(time.time()))` produces valid UUIDs |
| Per-device AES auth | 1.1.15 | Per-device key on HTTP signaling | Key retrievable from Unitree cloud API |

### SDP Overflow (Research Finding)

UnLeash Lite also includes an SDP overflow exploit targeting a heap buffer overflow in `parseMediaAttributes()` in the AWS KVS WebRTC SDK (versions before v1.18.1). The overflow corrupts `sessionAttributesCount` via a 522-byte attribute name, causing an out-of-bounds read that injects a forged DTLS fingerprint into the PeerConnection.

This was discovered and responsibly disclosed to AWS through their Vulnerability Disclosure Program. AWS patched the issue in KVS WebRTC SDK v1.18.1.

On production Go2 robots, DDS Security blocks the multicast delivery of the overflow SDP, so the exploit only works on development/benchtop boards that lack DDS Security configuration. It remains available via the `sdp-jailbreak` subcommand for research purposes and is relevant to any other deployment of the KVS WebRTC SDK that accepts SDP from untrusted sources.

```bash
# Benchtop boards only (requires cyclonedds==0.10.2)
pip install 'unleash-lite[sdp]'
python -m unleash_lite sdp-jailbreak bypass-ssh --interface-ip 192.168.123.100
```

## Acknowledgments

This tool builds on publicly disclosed security research by multiple independent teams.

**Olivier Laflamme (Boschko) and Ruikai Peng** discovered that `programming_actuator` executes arbitrary Python as root with no authentication ([CVE-2026-27509](https://nvd.nist.gov/vuln/detail/CVE-2026-27509)). Their exploit reaches it by joining DDS domain 0 directly on the LAN. Their writeup at [boschko.ca](https://boschko.ca/unitree-go2-rce/) documents the DDS attack chain. Unitree's response was to add DDS Security, which blocks the direct DDS path but is bypassed by the WebRTC bridge (see above).

**Andreas Makris (Bin4ry), Kevin Finisterre (h0stile), and Konstantin Severov (legion1581)** disclosed the broader Unitree security architecture weaknesses ([CVE-2025-35027](https://nvd.nist.gov/vuln/detail/CVE-2025-35027), [arXiv:2509.14139](https://arxiv.org/abs/2509.14139)): hardcoded AES keys, the WebRTC signaling protocol, and fleet-wide shared cryptographic material. legion1581's [`unitree_webrtc_connect`](https://github.com/legion1581/unitree_webrtc_connect) was foundational for the WebRTC data channel implementation.

The SDP overflow was discovered and responsibly disclosed to AWS through their Vulnerability Disclosure Program. AWS patched the issue in KVS WebRTC SDK v1.18.1. Unitree was notified concurrently but has not responded.

## Legal

This software is provided for **security research, education, and right-to-repair purposes only**. By using it, you agree that:

- You own the robot you are targeting, or have explicit written authorization from its owner.
- You are solely responsible for complying with all applicable local, state, national, and international laws.
- The authors and contributors accept no liability for damages, legal consequences, or misuse arising from this software.

## License

MIT
