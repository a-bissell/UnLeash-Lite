# UnLeash Dongle — REV B Power Section Correction

Corrections to the v1 design, verified against the official
**[Hardware design with RP2350](https://datasheets.raspberrypi.com/rp2350/hardware-design-with-rp2350.pdf)**
guide and the [RP2350 datasheet](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf).

> **Blocking:** v1 ties `DVDD` to `VCC_3V3` and has no core regulator. On RP2350,
> `DVDD` is the **1.1 V core rail**, supplied by the chip's internal **switching**
> regulator (not an LDO like RP2040). As drawn, v1 puts 3.3 V onto the 1.1 V core and
> destroys the chip on first plug-in. This document is the fix.

---

## 1. Core voltage regulator (NEW — was entirely missing)

The RP2350 core regulator is a 200 mA buck with **five** pins that need external parts:

| Pin        | Role                                                        |
|------------|-------------------------------------------------------------|
| VREG_VIN   | 3.3 V input                                                 |
| VREG_LX    | switch node → external inductor                             |
| VREG_FB    | output-voltage sense (tie to the regulator output node)     |
| VREG_PGND  | dedicated switching-current ground return                   |
| VREG_AVDD  | analogue supply for the regulator — noise-sensitive         |

```
      VCC_3V3 ──┬── C17 4.7uF ──┬── VREG_VIN
                │               │
               GND              │   (RP2350 internal buck)
                                │
         VREG_LX ───╥─── L1 3.3uH ───┬───────────────┬── 1V1_CORE
                    ║ (short, wide)  │               │
                                   C18 4.7uF      → DVDD pins
                                     │              (100nF each, on 1V1_CORE)
                                    GND
         VREG_FB  ── tie to 1V1_CORE (the C18 node)
         VREG_PGND── to GND, dedicated return right at the pin
         VREG_AVDD── R5 33R ──┬── C19 4.7uF ── and to 1V1_CORE
                              GND
```

### Exact components — RP says use these, do not substitute

| Ref | Value / Part                                   | Package      | Notes |
|-----|------------------------------------------------|--------------|-------|
| L1  | **Abracon AOTA-B201610S3R3-101-T** 3.3 µH 2.1 A | 0806 (2016)  | Polarity-marked on purpose. A "wrong way round" inductor couples into C18 and destabilizes the regulator. Orientation **matters** — follow RP's layout. |
| C17 | 4.7 µF 6.3 V X5R                                | 0402         | VREG_VIN input cap, close to pin |
| C18 | 4.7 µF 6.3 V X5R                                | 0402         | Core output cap, on the inductor / FB node |
| C19 | 4.7 µF 6.3 V X5R                                | 0402         | VREG_AVDD filter cap |
| R5  | 33 Ω                                            | 0402         | VREG_AVDD RC filter (AVDD draws ~200 µA) |

**Layout:** keep the VREG_VIN / VREG_LX / VREG_PGND loop short and wide. RP iterated
this many times — copy their regulator placement verbatim (see §5).

---

## 2. DVDD re-wiring (the blocking fix)

- Create a new net **`1V1_CORE`** = regulator output (C18 / VREG_FB node).
- Move **all DVDD pins** from `VCC_3V3` → `1V1_CORE`.
  - v1 DESIGN.md lists DVDD at **pins 23, 46, 50** — **verify against the datasheet
    pinout before trusting these numbers** (the DVDD→3V3 error shows the pin map has
    at least one bug; treat every pin number as unverified).
- Move the DVDD decoupling caps (v1 **C5, C8, C10**) onto `1V1_CORE`. Same 100 nF parts,
  different net. RP even shares one cap between two adjacent DVDD pins where space is tight.
- `VREG_VIN` stays on `VCC_3V3` (v1 had this right).
- IOVDD / USB_VDD / ADC_AVDD decoupling stays on `VCC_3V3`.

---

## 3. USB series termination (NEW — was missing)

RP2350 USB **requires 27 Ω series resistors on USB_DP and USB_DM, placed close to the chip.**
v1 had none.

| Ref     | Value | Package | Net                 |
|---------|-------|---------|---------------------|
| R6, R7  | 27 Ω  | 0402    | in-line on DP / DM  |

90 Ω differential on a 1 mm 2-layer board: RP uses **0.8 mm-wide** DP/DM tracks with a
**0.15 mm** gap and **solid ground directly underneath the entire run**. Route DP/DM over
nothing but ground.

---

## 4. Other notes

- **LDO:** AP2112K (v1) is a fine substitute for RP's NCP1117 — keep it. But add **≥1 µF on
  its input** (v1 only had 100 nF on VBUS). RP uses 10 µF in + 10 µF out.
- **Crystal:** v1's 15 pF load caps are correct for a 10 pF crystal. For guaranteed startup
  across temperature, RP strongly recommends the **Abracon ABM8-272-T3** 12 MHz part (Pico 2
  is tuned for it) plus its series/damping resistor. Not blocking.
- **Layers:** 2-layer / 1 mm is fine — it's exactly what RP's own Minimal board uses. Earlier
  advice to go 4-layer is **withdrawn**; 4-layer only eases QFN-60 escape routing, it isn't required.

---

## 5. Strongly recommended workflow

Download RP's official **RP2350A Minimal KiCad design** (ZIP, linked in the hardware guide)
and build your schematic from their power + USB + crystal sections verbatim, then restyle
into the 35 × 13 mm dongle outline. RP's words: *"if you choose not to use our example, you
do so at your own risk."* This gets the regulator correct-by-construction and sidesteps the
unverified pin map entirely.

### Reference component values (RP Minimal design numbering)
- C6, C7, C9 = 4.7 µF (0402) — regulator in / out / AVDD
- L1 = Abracon AOTA-B201610S3R3-101-T (0806)
- R3 = 33 Ω (0402) — AVDD filter
- R7, R8 = 27 Ω — USB series termination
- X1 = Abracon ABM8-272-T3 12 MHz crystal

*(Note: RP's refdes differ from this board's — see `bom-revB.csv` for this board's refs.)*

---

**Sources**
- Hardware design with RP2350 — https://datasheets.raspberrypi.com/rp2350/hardware-design-with-rp2350.pdf
- RP2350 datasheet — https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf
