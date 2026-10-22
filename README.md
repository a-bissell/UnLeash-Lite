```
   ██╗   ██╗███╗   ██╗██╗     ███████╗ █████╗ ███████╗██╗  ██╗
   ██║   ██║████╗  ██║██║     ██╔════╝██╔══██╗██╔════╝██║  ██║
   ██║   ██║██╔██╗ ██║██║     █████╗  ███████║███████╗███████║
   ██║   ██║██║╚██╗██║██║     ██╔══╝  ██╔══██║╚════██║██╔══██║
   ╚██████╔╝██║ ╚████║███████╗███████╗██║  ██║███████║██║  ██║
    ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
```

<p align="center">
  <img src="https://img.shields.io/badge/Status-Working-brightgreen.svg" alt="Status">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Python-3.11+-yellow.svg" alt="Python">
  <img src="https://img.shields.io/badge/Hardware-Unitree_Go2-orange.svg" alt="Hardware">
</p>

<div align="center">

**Own your Unitree robot — enroll, manage, deploy.**

</div>

UnLeash takes a stock Unitree Go2 from factory-locked to fully managed in one command. It combines jailbreak enrollment with fleet management, MQTT brokering, and OTA package deployment in a single tool — built for labs, classrooms, and anyone who believes in the right to repair.

> **Upgrading from UnLeash-Lite?** `unleash jailbreak init-ssh` still works exactly as before. The `unleash enroll` command wraps it with persistence, MQTT redirect, and fleet setup — all automated.

## Install

```bash
pip install .
```

Requires Python 3.11+. Installs everything (enrollment, server, dashboard).

## Quick Start

### 1. Enroll a robot

```bash
unleash enroll 192.168.123.161
```

This single command:
1. Connects via WebRTC data channel
2. Deploys SSH access (sitecustomize.py injection, two-press trigger)
3. Waits for SSH to come up
4. Installs `ssh_guard.sh` persistence (survives reboots + OTA)
5. Redirects MQTT traffic to your UnLeash broker
6. Verifies enrollment and prints a summary

```
  UnLeash — enrolling robot at 192.168.123.161

  [1/6] Connecting via WebRTC...              ✓  connected
  [2/6] Deploying SSH access...               ✓  triggered (auto)
  [3/6] Waiting for SSH...                    ✓  sshd running
  [4/6] Installing persistence...             ✓  ssh_guard.sh active
  [5/6] Redirecting to UnLeash broker...      ✓  /etc/hosts updated
  [6/6] Verifying enrollment...               ✓  enrolled

  ┌───────────────────────────────────────────┐
  │  Serial:    GO2-XXXXXXXXXX                │
  │  SSH:       ssh root@192.168.123.161      │
  │  Password:  unleash                       │
  │  Dashboard: http://10.0.0.5:8080          │
  └───────────────────────────────────────────┘

  Run `unleash serve` to start the management dashboard.
```

For firmware >= 1.1.15, pass the per-device AES key:

```bash
unleash enroll 192.168.123.161 --aes-key <32-hex-chars>
```

Retrieve it with `unleash fetch-key --email you@example.com` or from the Cloud Intel tab in the dashboard.

### 2. Start the management server

```bash
unleash serve
```

Opens the dashboard at [http://localhost:8080](http://localhost:8080) with:

- **Fleet** — Real-time robot status, live event feed, MQTT command console
- **Enroll** — Browser-based enrollment with live progress (alternative to CLI)
- **Packages** — Build UPK update packages from shell commands
- **Deployments** — Roll packages out to individual robots or the whole fleet
- **Audit** — Timestamped log of every action

The server includes a self-hosted MQTT broker that replaces Unitree's cloud. Enrolled robots connect automatically after the `/etc/hosts` redirect.

### 3. Deploy a package

Build and push an OTA package to your fleet:

```bash
unleash build spec.json        # create a .upk package
unleash deploy <pkg> <serial>  # push to a specific robot
```

Or use the Packages + Deployments pages in the dashboard.

## Firmware Support

| Firmware | Enrollment | AES Key? | Status |
|----------|-----------|----------|--------|
| <= 1.1.13 | `unleash enroll` (auto-trigger) | No | Confirmed |
| 1.1.14 | `unleash enroll` (two-press trigger) | No | Confirmed |
| >= 1.1.15 | `unleash enroll --aes-key KEY` | Yes | Confirmed |

If SSH is already up (e.g., from a previous session), `unleash enroll` skips the jailbreak and goes straight to fleet setup — persistence, MQTT redirect, and verification.

## CLI Reference

```
unleash                                   Show help + quickstart
unleash enroll <ip> [options]             Guided enrollment (the happy path)
unleash serve [--port 8080]               Start broker + API + dashboard
unleash fetch-key --email EMAIL           Retrieve AES key from Unitree cloud

# Power-user commands
unleash jailbreak <mode> [options]        Raw payload delivery
unleash probe [--robot-ip IP]             Diagnostic DDS dump
```

### Enroll options

```
unleash enroll <robot-ip>
  --aes-key KEY          Per-device AES-128 key (firmware >= 1.1.15)
  --password PASS        Root password to set (default: unleash)
  --broker-ip IP         UnLeash broker IP (default: auto-detect)
  --hotkey HOTKEY         Controller hotkey (default: L1+Y)
  --manual               Prompt for manual controller press instead of auto-trigger
  --skip-redirect        Skip MQTT /etc/hosts redirect
  --skip-persist         Skip ssh_guard.sh persistence install
  --debug                Enable debug logging
```

### Jailbreak modes (power users)

These are the raw payload modes, preserved for users who need fine-grained control.

| Mode | Firmware | Description |
|------|----------|-------------|
| `init-ssh` | >= 1.1.14 | SSH via `sitecustomize.py` injection (recommended) |
| `init-ssh-persist` | >= 1.1.14 | Install `ssh_guard.sh` via self-removing sitecustomize |
| `bypass-ssh` | >= 1.1.14 | SSH via cron job (requires crond) |
| `bypass-hosts` | >= 1.1.14 | Write MQTT redirect to `/etc/hosts` |
| `custom` | >= 1.1.14 | Arbitrary shell command via `np.savetxt` bypass |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `UNLEASH_SECRET_KEY` | (auto-generated) | JWT signing key |
| `UNLEASH_MQTT_PORT` | `17883` | MQTT broker port |
| `UNLEASH_ADVERTISE_HOST` | (auto-detect) | Host for OTA package downloads |
| `UNLEASH_DEFAULT_PASSWORD` | `admin` | Initial dashboard password |

## How It Works

The Go2's `webrtc_bridge` service sits inside the DDS security perimeter with valid credentials. It bridges between the WebRTC data channel and the internal DDS bus, forwarding messages without filtering.

UnLeash exploits this by:

1. Connecting to the HTTP signaling endpoint (port 9991) and establishing a WebRTC data channel
2. Uploading a Python payload to `programming_actuator` via the bridge
3. Triggering execution via a fake controller hotkey press (or manual press on physical controller)
4. The payload runs as root

The `init-ssh` technique specifically exploits the fact that `py_script_execute_env` calls `Py_Initialize()` before `seccomp_load()`. A `sitecustomize.py` written via `np.savetxt` runs with full root syscall access before the sandbox activates.

### Firmware Defenses

| Defense | Added in | How it's bypassed |
|---------|----------|-------------------|
| DDS Security (PKI-DH) | ~1.1.x | WebRTC bridge is inside the perimeter |
| Keyword blocklist | 1.1.14 | `str(bytes([...]))` encoding + `np.savetxt` for file I/O |
| seccomp sandbox | 1.1.14 | `sitecustomize.py` runs before `seccomp_load()` |
| UUID validation | 1.1.14 | `str(int(time.time()))` produces valid 10-digit UUIDs |
| Per-device AES auth | 1.1.15 | Key retrievable from Unitree cloud API |

## Project Structure

```
unleash/
├── core/           WebRTC data channel + signaling
├── enroll/         Jailbreak payloads + guided enrollment
├── broker/         Self-hosted MQTT broker
├── fleet/          Robot tracking + status
├── packages/       UPK package builder + OTA deployment
├── certs/          TLS certificate generation
├── auth/           JWT authentication
├── db/             SQLite database
├── audit/          Action logging
├── api/            FastAPI REST + WebSocket routes
└── app.py          Application factory

frontend/           React/Vite/Tailwind dashboard
├── src/pages/
│   ├── Dashboard   Fleet overview + live feed
│   ├── Enroll      Browser-based enrollment
│   ├── Packages    Package management
│   ├── Deployments OTA rollout tracking
│   ├── AuditLog    Action history
│   └── ...
```

## Acknowledgments

This tool builds on publicly disclosed security research by multiple independent teams.

**Olivier Laflamme (Boschko) and Ruikai Peng** discovered that `programming_actuator` executes arbitrary Python as root with no authentication ([CVE-2026-27509](https://nvd.nist.gov/vuln/detail/CVE-2026-27509)). Their writeup at [boschko.ca](https://boschko.ca/unitree-go2-rce/) documents the DDS attack chain.

**thiago** identified the `sitecustomize-ssh` technique: `py_script_execute_env` calls `Py_Initialize()` before `seccomp_load()`, meaning `sitecustomize.py` runs with full root syscall access on every Python init. Writing to it via the existing `np.savetxt` bypass gives persistent pre-sandbox code execution on firmware 1.1.14/15 where crond is not running.

**Andreas Makris (Bin4ry), Kevin Finisterre (h0stile), and Konstantin Severov (legion1581)** disclosed the broader Unitree security architecture weaknesses ([CVE-2025-35027](https://nvd.nist.gov/vuln/detail/CVE-2025-35027), [arXiv:2509.14139](https://arxiv.org/abs/2509.14139)). legion1581's [`unitree_webrtc_connect`](https://github.com/legion1581/unitree_webrtc_connect) was foundational for the WebRTC data channel implementation.

## Legal

This software is provided for **security research, education, and right-to-repair purposes only**. By using it, you agree that:

- You own the robot you are targeting, or have explicit written authorization from its owner.
- You are solely responsible for complying with all applicable local, state, national, and international laws.
- The authors and contributors accept no liability for damages, legal consequences, or misuse arising from this software.

## License

MIT
