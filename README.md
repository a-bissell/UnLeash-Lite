```
   ██╗   ██╗███╗   ██╗██╗     ███████╗ █████╗ ███████╗██╗  ██╗
   ██║   ██║████╗  ██║██║     ██╔════╝██╔══██╗██╔════╝██║  ██║
   ██║   ██║██╔██╗ ██║██║     █████╗  ███████║███████╗███████║
   ██║   ██║██║╚██╗██║██║     ██╔══╝  ██╔══██║╚════██║██╔══██║
   ╚██████╔╝██║ ╚████║███████╗███████╗██║  ██║███████║██║  ██║
    ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
                            l i t e
```

<p align="center">
  <img src="https://img.shields.io/badge/Status-Working-brightgreen.svg" alt="Status">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Python-3.10+-yellow.svg" alt="Python">
  <img src="https://img.shields.io/badge/Hardware-Unitree_Go2-orange.svg" alt="Hardware">
  <img src="https://img.shields.io/badge/Hardware-Unitree_R1_(Experimental)-red.svg" alt="Hardware R1">
</p>

<div align="center">

**Go2 Jailbreak for Firmware 1.1.7 – 1.1.15 | R1 Support (Experimental)**


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
- **Payloads** — All 10 jailbreak modes with firmware compatibility tags and parameter requirements
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

### Firmware 1.1.14/15

1. Connect to robot (with AES key if on 1.1.15)
2. Run init-ssh (CLI or web dashboard)
3. Press L1+Y on your physical controller, wait 2 seconds, press L1+Y again
4. ssh root@<robot-ip> (password: unleash)
   
Cleanup:
```bash
rm -f /usr/lib/python3.8/sitecustomize.py /usr/lib/python3.10/sitecustomize.py \
      /usr/lib/python3.11/sitecustomize.py \
      /usr/local/lib/python3.8/dist-packages/sitecustomize.py
```

### CLI

```bash
unleash-lite ssh                                        # firmware <= 1.1.13
unleash-lite init-ssh                                   # firmware 1.1.14
unleash-lite init-ssh --aes-key <32-hex-char-key>       # firmware 1.1.15+
```

## Firmware Support

| Firmware | Mode | AES Key? | Status |
|----------|------|----------|--------|
| <= 1.1.13 | `ssh` | No | Confirmed |
| 1.1.14 | `init-ssh` | No | Confirmed |
| >= 1.1.15 | `init-ssh --aes-key KEY` | Yes | Confirmed |

## R1 Support (Experimental)

The Unitree R1 humanoid ships with a hidden debug socket listener (`audio_detect.py`) that can be activated via a controller button combo. Once active, it provides unauthenticated root shell access over TCP port 8888.

### Quick Start

```bash
# 1. Press L1+L2+Start on the R1's controller (robot plays audio_detect.wav)

# 2. Confirm the listener is active:
unleash-lite r1 probe

# 3. Interactive root shell:
unleash-lite r1 shell

# 4. Or run a single command:
unleash-lite r1 custom --cmd 'id; hostname; cat /etc/os-release'
```

### R1 Modes

| Mode | Description |
|------|-------------|
| `probe` | Check if audio_detect listener is active on port 8888 |
| `shell` | Interactive root shell with output capture |
| `custom` | Run any shell command (`--cmd`) with stdout/stderr |
| `reverse-shell` | Bash reverse shell to specified IP |

> **Note:** The R1 does not ship with openssh-server pre-installed. To get SSH,
> use `shell` mode to wget/install the aarch64 .deb from a local HTTP server,
> then start sshd manually. See the Discord notes for the exact procedure.

### R1 Firmware Support

| Firmware | vui_service | Status |
|----------|-------------|--------|
| >= 1.4.x | >= 2.2.0 | Experimental (confirmed on 1.4.2.8) |

**Prerequisites:** Physical access to the controller. The FSM state machine requires pressing L1+L2+Start to cycle into audio detect mode, which spawns the Python socket listener on port 8888 as root.

---

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
| `init-ssh` | SSH via `sitecustomize.py` injection — recommended for fw 1.1.14/15 |
| `bypass-ssh` | SSH via cron job (fw 1.1.14+, requires crond running) |
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
unleash-lite <mode> [options]                           # Go2 jailbreak
unleash-lite r1 <mode> [--robot-ip IP]                  # R1 via audio_detect
unleash-lite serve [--port 8443] [--password SECRET]
unleash-lite fetch-key --email EMAIL [--sn SERIAL]
unleash-lite probe [--aes-key KEY] [--debug]
unleash-lite trigger [--robot-ip IP] [--via bridge|dds]
```

Common options:

```
--robot-ip IP         Robot IP (default: 192.168.123.161)
--aes-key KEY         Per-device AES-128 key for firmware >= 1.1.15
--trigger MODE        auto (bridge, experimental) or manual (press controller)
--hotkey HOTKEY        Controller hotkey binding (default: L1+Y)
--password PASS       Root password for ssh modes (default: unleash)
--debug               Enable debug logging
```

## Acknowledgments

This tool builds on publicly disclosed security research by multiple independent teams.

**Olivier Laflamme (Boschko) and Ruikai Peng** discovered that `programming_actuator` executes arbitrary Python as root with no authentication ([CVE-2026-27509](https://nvd.nist.gov/vuln/detail/CVE-2026-27509)). Their writeup at [boschko.ca](https://boschko.ca/unitree-go2-rce/) documents the DDS attack chain.

**thiago** identified the `sitecustomize-ssh` technique: `py_script_execute_env` calls `Py_Initialize()` before `seccomp_load()`, meaning `sitecustomize.py` runs with full root syscall access on every Python init. Writing to it via the existing `np.savetxt` bypass gives persistent pre-sandbox code execution on firmware 1.1.14/15 where crond is not running.

**Andreas Makris (Bin4ry), Kevin Finisterre (h0stile), and Konstantin Severov (legion1581)** disclosed the broader Unitree security architecture weaknesses ([CVE-2025-35027](https://nvd.nist.gov/vuln/detail/CVE-2025-35027), [arXiv:2509.14139](https://arxiv.org/abs/2509.14139)). legion1581's [`unitree_webrtc_connect`](https://github.com/legion1581/unitree_webrtc_connect) was foundational for the WebRTC data channel implementation.

**R1 RE Discord** — The R1 `audio_detect` shell method was discovered and confirmed by the R1 reverse engineering community. Special thanks to **thomas flayols** for confirming the FSM activation sequence (L1+L2+Start) and validating root shell access on firmware 1.4.2.8, **iso** for the Qwen-assisted binary analysis of the `vui_service` FSM state machine and deep Go2/GD32 hardware security knowledge, **Jim** for extensive hardware teardown and PCB tracing work on the R1 mainboard, and **alansrobotlab** for component identification. Their collaborative work made R1 support possible.

## Legal

This software is provided for **security research, education, and right-to-repair purposes only**. By using it, you agree that:

- You own the robot you are targeting, or have explicit written authorization from its owner.
- You are solely responsible for complying with all applicable local, state, national, and international laws.
- The authors and contributors accept no liability for damages, legal consequences, or misuse arising from this software.

## License

MIT
