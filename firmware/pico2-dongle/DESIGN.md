# Pico2 MSC Dongle — Design Notes

## Architecture

```
  ┌─────────────────────┐         ┌──────────────────────────────┐
  │    RP2350 (Pico 2)  │ USB-C   │       Go2 (RK3588S)         │
  │                     │────────►│                              │
  │  MSC: OracleCFS     │         │  1. udev sees MSC block dev  │
  │  disk image (16KB)  │         │     60-persistent-storage    │
  │                     │         │     triggers blkid probe     │
  │  LED: solid = ready │         │                              │
  └─────────────────────┘         │  2. blkid OCFS1 prober hits  │
                                  │     "OracleCFS" at +0x1B4    │
  ┌─────────────────────┐ eth     │     → overflow → overwrites  │
  │    Mac (unleash CLI) │───────►│     /proc/sys/kernel/         │
  │                     │         │     core_pattern with         │
  │  unleash crash:     │         │     |/bin/sh /root/go2_led.sh│
  │  HTTP signaling to  │         │                              │
  │  xfkTon :9991       │         │  3. Crash SDP → SIGSEGV in   │
  │  → crash SDP        │         │     unitreeWebRTCClientMaster│
  │  → WebRTC SIGSEGV   │         │                              │
  │                     │         │  4. core_pattern fires on    │
  └─────────────────────┘         │     crash → root shell exec  │
                                  └──────────────────────────────┘
```

## Why MSC-Only (Not CDC-ECM)

The Go2 kernel (5.10.176-rt86+) has **no USB Ethernet host drivers**:
- `CONFIG_USB_NET_CDCETHER is not set`
- `CONFIG_USB_NET_RNDIS_HOST is not set`
- `CONFIG_USB_NET_CDC_NCM is not set`
- `CONFIG_USB_ACM is not set`
- `CONFIG_PPP is not set`
- `CONFIG_SLIP is not set`

Available USB host drivers: USB_STORAGE=y, USB_HID=y, USB_SERIAL=y
(CH341/CP210X/FTDI/PL2303 modules), USB_VIDEO_CLASS=m.

Root login on tty1 requires a password, ruling out HID keyboard injection.

The crash trigger (SDP overflow) runs from the Mac's `unleash` CLI over
the existing ethernet connection (192.168.123.100 → 192.168.123.162).

## Comparison with pico-arm.uf2

Will's pico-arm.uf2 is a composite UVC + MSC device:
- **MSC**: Same OracleCFS disk image → core_pattern overwrite
- **UVC**: Malformed descriptors with De Bruijn patterns → crash trigger
  (the UVC descriptor overflow crashes a root process, firing core_pattern)

Our firmware is MSC-only because:
1. The SDP crash works reliably over ethernet (100% success rate)
2. Simpler firmware = easier to audit and modify
3. The `unleash` CLI already has ethernet access to the Go2

## Build

```bash
export PICO_SDK_PATH=/path/to/pico-sdk
mkdir build && cd build
cmake ..
make -j$(nproc)
# Output: pico2_dongle.uf2
```

## Resource Budget

| Resource     | Available | Used (est.) | Notes               |
|-------------|-----------|-------------|----------------------|
| Flash       | 4 MB      | ~35 KB      | Firmware + disk image|
| SRAM        | 520 KB    | ~10 KB      | USB buffers + stack  |
| CPU         | 150 MHz   | Low         | USB polling only     |

## Disk Image

Extracted from pico-arm.uf2 (Nov 4 2026 build). 32 sectors × 512 bytes
= 16,384 bytes. Sectors 0-15 contain exploit data; 16-31 are zeros.

Key byte offsets from disk start:
- `0x0024`: `FF FF` marker
- `0x01B4`: `OracleCFS` — OCFS1 filesystem signature
- `0x07EA`: `|/bin/sh /root/go2_led.sh` — core_pattern payload
- `0x0804`: De Bruijn pattern `Aa0Aa1Aa2...` — overflow offset finder

## LED Feedback

| Pattern              | Meaning                         |
|---------------------|---------------------------------|
| 1 blink (300ms)     | Boot complete                   |
| 3 rapid blinks      | MSC enumerated, core_pattern priming |
| Solid on            | Ready — run `unleash crash`     |

## Open Items

### Resolved
- [x] CDC-ECM support on Go2 → **Not possible** (no kernel drivers)
- [x] Extract OracleCFS disk image from pico-arm.uf2 → **Done** (disk_image.h)
- [x] DHCP server → **Not needed** (no USB networking)

### Remaining
- [ ] Verify device AES key is shared across Go2 Air boards
- [ ] Test firmware build with Pico SDK 2.x
- [ ] Add UART debug output for troubleshooting
