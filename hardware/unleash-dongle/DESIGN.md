# UnLeash Key — Hardware Design Specification

## Overview

USB-C developer access key powered by RP2350A. Plug into Go2 USB-C port,
enables root SSH. Form factor: ~35mm x 13mm, male USB-C plug, no cable needed.

## Block Diagram

```
USB-C Male ──┬── VBUS (5V) ── AP2112K LDO ── 3.3V rail
Plug         │                                  │
             ├── D+/D- ───── RP2350A ──── QSPI Flash (W25Q32JV)
             │                  │
             └── GND            ├──── 12MHz Crystal
                                ├──── BOOTSEL Button
                                ├──── Status LED (WS2812B-2020)
                                └──── SWD Test Points
```

## Schematic — Net Connections

### Power (5V → 3.3V)

| Net      | Source              | Destination                              |
|----------|---------------------|------------------------------------------|
| VBUS     | USB-C VBUS (A4,B4)  | AP2112K VIN (pin 1), C1 100nF            |
| VCC_3V3  | AP2112K VOUT (pin 5)| RP2350A all IOVDD, DVDD, USB_VDD, VREG_VIN |
| VCC_3V3  | AP2112K VOUT        | W25Q32JV VCC, C_bulk 10uF, C2-C8 100nF  |
| GND      | USB-C GND           | All component GND, AP2112K GND (pin 2,3) |
| ADC_AVDD | VCC_3V3 via 100R    | RP2350A ADC_AVDD (pin 43)                |

AP2112K-3.3 connections:
- Pin 1 (VIN): VBUS + C1 (100nF to GND)
- Pin 2 (GND): GND
- Pin 3 (GND): GND
- Pin 4 (EN): VBUS (always enabled)
- Pin 5 (VOUT): VCC_3V3 + C_bulk (10uF to GND)

### RP2350A (QFN-60) Power Pins

| Pin | Function  | Net      | Decoupling |
|-----|-----------|----------|------------|
| 1   | IOVDD     | VCC_3V3  | C2 100nF   |
| 10  | IOVDD     | VCC_3V3  | C3 100nF   |
| 22  | IOVDD     | VCC_3V3  | C4 100nF   |
| 23  | DVDD      | VCC_3V3  | C5 100nF   |
| 33  | IOVDD     | VCC_3V3  | C6 100nF   |
| 43  | ADC_AVDD  | ADC_AVDD | C7 100nF   |
| 46  | DVDD      | VCC_3V3  | C8 100nF   |
| 49  | IOVDD     | VCC_3V3  | C9 100nF   |
| 50  | DVDD      | VCC_3V3  | C10 100nF  |
| 59  | USB_VDD   | VCC_3V3  | C11 100nF  |
| 60  | VREG_VIN  | VCC_3V3  | C12 100nF  |
| GND | (EP + pins)| GND    |            |

### USB

| RP2350A Pin | Function | Net    | USB-C Pin |
|-------------|----------|--------|-----------|
| 47          | USB_DP   | USB_DP | A6, B6    |
| 48          | USB_DM   | USB_DM | A7, B7    |

USB-C CC pins (A5, B5): each pulled down to GND via 5.1k resistor
(identifies as UFP / device).

No ESD protection diodes in v1 (internal RP2350 protection sufficient
for a dongle that's plugged in once).

### QSPI Flash (W25Q32JVSSIQ — 32Mbit / 4MB)

| W25Q32 Pin | Function | Net        | RP2350A Pin |
|------------|----------|------------|-------------|
| 1          | /CS      | QSPI_SS   | 56          |
| 2          | DO (IO1) | QSPI_SD1  | 53          |
| 3          | /WP (IO2)| QSPI_SD2  | 52          |
| 4          | GND      | GND        | —           |
| 5          | DI (IO0) | QSPI_SD0  | 54          |
| 6          | CLK      | QSPI_SCLK | 55          |
| 7          | /HOLD(IO3)| QSPI_SD3 | 51          |
| 8          | VCC      | VCC_3V3   | —           |

C13 100nF on VCC close to flash.

### Crystal (12MHz, 3.2x2.5mm)

| Crystal Pin | Net  | RP2350A Pin |
|-------------|------|-------------|
| 1           | XIN  | 57          |
| 2           | XOUT | 58          |

Load capacitors: C14, C15 = 15pF each (XIN to GND, XOUT to GND).
Exact values depend on crystal spec — 15pF is typical for 12MHz/10pF.

### BOOTSEL Button

QSPI_SS (pin 56) has an internal pull-up. BOOTSEL grounds it during
power-on to enter UF2 mass storage bootloader.

| Component     | Pin 1   | Pin 2 |
|---------------|---------|-------|
| SW1 (tactile) | QSPI_SS | GND   |

### Status LED (WS2812B-2020 — addressable RGB)

| WS2812B Pin | Function | Net/Connection  |
|-------------|----------|-----------------|
| VDD         | Power    | VCC_3V3         |
| VSS         | Ground   | GND             |
| DIN         | Data in  | GPIO0 (pin 2)   |
| DOUT        | Data out | NC              |

C16 100nF on VDD. Single-wire protocol, one GPIO.

### TESTEN Pin

| RP2350A Pin | Function | Connection     |
|-------------|----------|----------------|
| 45          | TESTEN   | GND via 1k     |

Must be held low for normal operation.

### SWD Debug (Test Points)

| RP2350A Pin | Function | TP  |
|-------------|----------|-----|
| 42          | SWCLK    | TP1 |
| 44          | SWDIO    | TP2 |
| —           | GND      | TP3 |

Exposed pads on PCB bottom — can probe with pogo pins.

### Unused GPIO

All unused GPIO left floating (internal pull-downs available via
software if needed). No external pull resistors.

## PCB Constraints

| Parameter     | Value                |
|---------------|----------------------|
| Dimensions    | 35mm x 13mm          |
| Layers        | 2 (or 4 for tighter) |
| Thickness     | 1.0mm                |
| Min trace     | 0.15mm / 6mil        |
| Min space     | 0.15mm / 6mil        |
| USB diff pair | 90Ω impedance        |
| Via size      | 0.3mm drill / 0.6mm  |
| Copper weight | 1oz                  |
| Surface finish| HASL or ENIG         |
| Solder mask   | Matte black          |

### Component Placement (top-down, USB-C plug at top)

```
┌─────────────────────────────┐
│         USB-C MALE          │  ← 12mm
│         PLUG HERE           │
├─────────────────────────────┤
│  [C1]  [LDO]  [C_bulk]     │
│                             │
│     ┌─────────────┐        │
│     │             │  [XTAL] │
│     │   RP2350A   │  [C14]  │
│     │   QFN-60    │  [C15]  │
│     │             │         │
│     └─────────────┘        │
│  [FLASH]            [LED]   │
│  [C13]              [SW1]   │
│                             │
│  (TP1) (TP2) (TP3)         │  ← bottom side TPs
└─────────────────────────────┘
     13mm wide x 35mm long
```

## Firmware Notes

Same UF2 build as `unleash-key-prod.uf2`. The RP2350A runs TinyUSB
presenting 30 USB interfaces (UVC + Mass Storage). Flash via BOOTSEL:
hold SW1, plug into laptop USB, drag-drop UF2.

The 4MB flash is overkill for the current 50KB firmware but leaves
room for future mass storage image expansion (full installer payload).

## Manufacturing

Target: JLCPCB turnkey assembly.
All parts chosen for JLCPCB basic/preferred stock where possible.
See bom.csv for LCSC part numbers.
