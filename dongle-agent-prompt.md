# Unleash Dongle — Implementation Prompt

## Context

You are working on UnLeash, a jailbreak tool for the Unitree Go2 robot dog. The repo has been restructured (PR #9) from `unleash_lite/` to `unleash/` with subpackages: `core/` (WebRTC, cloud API), `enroll/` (jailbreak orchestrator, payloads), `fleet/`, `api/`, etc. The entry point is `unleash/__main__.py`.

We are adding a new jailbreak vector: a USB-C dongle based on a Raspberry Pi Pico2 (RP2350) that achieves root code execution on the Go2 without any credentials, WiFi, or BLE pairing. The dongle is completely self-contained — plug it into the Go2's USB-C port, wait for the LED to go green, SSH in.

## The exploit chain

The chain has two stages, both running on the Pico2:

1. **Prime `core_pattern`**: The Pico2 presents as a USB device that exploits a vulnerability in how the Go2 handles USB enumeration to write to `/proc/sys/kernel/core_pattern`. This points core_pattern at a short payload script on the filesystem (22-char path budget, e.g. `|/tmp/u.sh`). The same stage also writes that payload script to disk.

2. **Trigger crash**: The Pico2 reconfigures its USB device class (via TinyUSB runtime descriptor swap). The Go2 re-enumerates the new device, which triggers a crash in a root process (SIGABRT). The kernel executes the core_pattern handler as root, which runs our payload.

The payload enables SSH, sets the root password, installs persistence via `deb_update.sh`, and cleans up after itself.

**Important**: The USB exploit primitives (what device class primes core_pattern, what device class triggers the crash) come from Aleph/Praetorian's research. Their blog post and repo should be public by the time you read this. Reference their implementation for the specific USB descriptors and exploit mechanics. The existing file `firmware/pico2/` or Will's published repo will have the C code for the actual exploit — adapt it, don't reinvent it.

## What to build

### 1. Python package: `unleash/dongle/`

Create these modules inside the existing `unleash/` package:

**`unleash/dongle/__init__.py`**

**`unleash/dongle/payloads.py`**
- Generates the shell script that `core_pattern` executes on the Go2.
- Must fit the 22-char core_pattern path budget (use `|/tmp/u.sh` or similar).
- The script itself (written to `/tmp/u.sh` by the USB exploit) can be longer.
- Default payload: set root password ("unleash"), start sshd with PermitRootLogin=yes, install persistence via the `deb_update.sh` hook (see `unleash/enroll/payloads.py` `payload_sitecustomize_ssh` for the persistence pattern), clean up the core_pattern entry.
- Provide a `build_payload(password, persist=True, extra_commands=None)` function.
- The payload must be self-cleaning: after execution, it should restore `/proc/sys/kernel/core_pattern` to the default (`core`) and remove `/tmp/u.sh`.

**`unleash/dongle/uf2_builder.py`**
- Takes a compiled UF2 template and a payload string, patches the payload bytes into the UF2 at a known marker offset (e.g. `__PAYLOAD_MARKER__` in the firmware binary, padded to 4096 bytes).
- `patch_uf2(template_path, payload_str, output_path)` — reads the template UF2, finds the marker, replaces with the payload (null-terminated, zero-padded to the reserved region size), writes the output UF2.
- `bundle_default_uf2(output_path, password="unleash")` — generates the default payload via `payloads.py` and patches it into the bundled template.
- No Pico SDK or cross-compiler needed on the user's machine. The template UF2 is a pre-compiled binary shipped in `unleash/dongle/firmware/` (or downloaded on first use).

**`unleash/dongle/flash.py`**
- Detects a Pico2 in BOOTSEL mode (appears as a USB mass storage device named "RPI-RP2").
- On macOS: look for `/Volumes/RPI-RP2`. On Linux: check `/media/*/RPI-RP2` or `/run/media/*/RPI-RP2`.
- `detect_pico2()` — returns the mount path or None.
- `flash_uf2(uf2_path, mount_path=None)` — copies the UF2 to the Pico2. Auto-detects if mount_path is None. The Pico2 auto-reboots after the copy completes.
- Print clear status messages. If no Pico2 is detected, print instructions: "Hold BOOTSEL while plugging in the Pico2, then retry."

**`unleash/dongle/monitor.py`**
- Listens on USB CDC serial for status messages from the dongle firmware.
- The firmware emits single-line status messages: `STAGE:INIT`, `STAGE:PRIME`, `STAGE:RECONFIG`, `STAGE:CRASH_WAIT`, `STAGE:PWNED`, `STAGE:ERROR:<detail>`.
- On macOS: serial port appears as `/dev/cu.usbmodem*`. On Linux: `/dev/ttyACM*`.
- `monitor_dongle(callback=None, serial_port=None)` — auto-detects the serial port if not specified, reads lines, calls the callback with each status update, prints a formatted live feed.
- Use pyserial for cross-platform serial I/O (add to dependencies).

**`unleash/dongle/post_exploit.py`**
- After the dongle reports `STAGE:PWNED`, waits for SSH to come up on the robot.
- `wait_for_ssh(robot_ip, password, timeout=60)` — polls SSH connectivity.
- `post_exploit(robot_ip, password="unleash", enroll=False)` — SSHs in, verifies root access, cleans up any exploit artifacts (core_pattern restored, temp files removed). If `enroll=True`, hands off to the existing `unleash.enroll.enrollctl` enrollment flow for full fleet setup (MQTT redirect, certs, etc.).
- Use paramiko for SSH (already a dependency from the enroll flow).

**`unleash/dongle/cli.py`**
- Wire up the `unleash dongle` subcommand in `unleash/__main__.py`.
- Subcommands:
  - `unleash dongle flash` — detect Pico2, flash the default UF2. Options: `--password`, `--payload <script>` (custom shell script to bake in).
  - `unleash dongle build --payload <script> --output <path>` — build a custom UF2 without flashing.
  - `unleash dongle monitor` — watch the dongle work via USB serial. Options: `--then enroll` (auto-run enroll after success), `--robot-ip`, `--password`.
  - `unleash dongle status` — quick check: is a Pico2 in BOOTSEL mode attached? Is a dongle serial port active?

### 2. Firmware: `firmware/pico2/`

**Only if Aleph's firmware source is available.** If their repo has the Pico2 C source, adapt it into our firmware directory. If they only published the UF2 binary, use it as the template and skip writing firmware from scratch.

If writing/adapting firmware:

**`firmware/pico2/main.c`**
- Core 0: runs the exploit chain state machine (init → prime → wait → reconfig → crash_wait → done).
- Core 1: runs the LED state machine and CDC serial status output.
- The payload script is embedded at compile time via `payload_embed.h`.
- State transitions emit status lines over CDC serial.

**`firmware/pico2/usb_device.c`**
- TinyUSB device descriptors for both stages of the exploit.
- Stage 1: whatever device class Aleph's research uses for the core_pattern write.
- Stage 2: the crash-inducing device class.
- Runtime descriptor swap between stages.

**`firmware/pico2/led.c`**
- Simple state machine on Core 1.
- States: OFF → AMBER_BLINK (working) → GREEN_SOLID (success) → RED_BLINK (error).
- Uses the Pico2's onboard LED (GPIO 25 on most boards).

**`firmware/pico2/payload_embed.h`**
- Generated file. Contains the shell script as a C byte array.
- The `uf2_builder.py` on the Python side patches this region in the compiled UF2 so users don't need to recompile.
- Reserve 4096 bytes for the payload region, marked with `__PAYLOAD_MARKER__` (64 bytes of 0xAA sentinel) for easy binary patching.

**`firmware/pico2/CMakeLists.txt`**
- Standard Pico SDK CMake build.
- Target: `pico2-unleash`.
- Enable USB device (TinyUSB), CDC serial, multicore.
- Output: `pico2-unleash.uf2`.

### 3. Integration

- Add `unleash dongle` dispatch to `unleash/__main__.py` alongside the existing `r1`, `serve`, `fetch-key` subcommands.
- Add `pyserial` to the project dependencies in `pyproject.toml`.
- Bundle the pre-built default UF2 at `unleash/dongle/firmware/pico2-unleash.uf2` (or add a download helper if the binary is too large for the repo).
- Add the firmware source at `firmware/pico2/` (top-level, not inside the Python package — it's a separate build target).

### 4. README section

Add a "USB Dongle" section to README.md between the existing Go2 and R1 sections:

```
## USB Dongle (Pico2)

The fastest way to jailbreak a Go2 on any firmware. No credentials, no WiFi, no app.

### Requirements
- Raspberry Pi Pico2 (RP2350) — ~$5
- USB-C cable or adapter

### Quick start
1. Flash the dongle:
   ```bash
   unleash dongle flash
   ```
2. Plug the dongle into the Go2's USB-C port
3. Wait for the LED to turn solid green (~10-15 seconds)
4. SSH in:
   ```bash
   ssh root@192.168.123.161   # password: unleash
   ```

### How it works
The dongle exploits the Go2's USB enumeration to write a payload to
`core_pattern`, then triggers a root process crash. The crash handler
runs our payload as root, enabling SSH and installing persistence.
No network, no keys, no pairing — just USB.

Credit: USB exploit chain by Aleph (Praetorian). See [their blog post](LINK).
```

## Style notes

- Match the existing code style in `unleash/`. Look at `unleash/enroll/payloads.py` and `unleash/core/webrtc.py` for patterns.
- Use the same colored terminal output style (ANSI escape codes) as the existing jailbreak orchestrator in `unleash/enroll/orchestrator.py`.
- Docstrings: one-line module docstrings, brief function docstrings where non-obvious. No multi-paragraph blocks.
- No comments explaining what code does. Only comment on non-obvious "why".
- Tests go in `tests/test_dongle_*.py`. At minimum: test payload generation, test UF2 patching (with a mock template), test Pico2 detection logic.
