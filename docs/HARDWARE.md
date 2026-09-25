# Hardware (unchanged from v2)

## Parts (~$117)

| Component | Part | Est. cost |
|---|---|---|
| Microcomputer | Raspberry Pi 3A+ (512 MB) | $25 |
| Storage | Samsung 32 GB Endurance microSD | $10 |
| Power | 5 V 3 A micro-USB supply (2.5 A is marginal) | $12 |
| Display | Waveshare 5-DSI-TOUCH-B, 720×1280 IPS, GT911 touch | $37 |
| DAC/amp | Adafruit MAX98357A I²S | $6 |
| Speaker | Dayton Audio ND90-8 3.5" full range, 8 Ω | $12 |
| Light sensor | BH1750 | $4 |
| Enclosure | Dense wooden project / shadow box | $15 |
| Misc | Solid-core wire, female jumper leads | $6 |
| **New in v3** | Pi 3 heatsink (SoC) | ~$3 |

## Wiring — MAX98357A (I²S amp)

| MAX98357A | Pi GPIO | Physical pin |
|---|---|---|
| VIN | 5 V | 4 |
| GND | GND | 6 |
| BCLK | GPIO 18 (PCM_CLK) | 12 |
| LRCLK | GPIO 19 (PCM_FS) | 35 |
| DIN | GPIO 21 (PCM_DOUT) | 40 |
| GAIN | floating (9 dB) | — |

## Wiring — BH1750 (light sensor)
Mount it rear-facing on the back panel so the screen's glow doesn't feed back.

| BH1750 | Pi GPIO | Physical pin |
|---|---|---|
| VCC | 3.3 V | 1 |
| GND | GND | 9 |
| SDA | GPIO 2 (SDA1) | 3 |
| SCL | GPIO 3 (SCL1) | 5 |
| ADDR | floating (0x23) | — |

## Wiring — speaker
Run short solid-core leads from the MAX98357A +/− pads to the ND90-8 terminals.

## Wiring — DSI display
- Connect the DSI ribbon (12 cm) to the Pi's 15-pin DSI connector, contacts
  down. Leave a gentle loop.
- Display power goes to GPIO pin 2 (5 V) and pin 6 (GND). This is required in
  addition to the ribbon.
- GT911 touch is on the same I²C bus as the BH1750, at a different address.

## /boot/firmware/config.txt fragment
```
dtparam=i2c_arm=on
dtoverlay=vc4-kms-v3d,cma-128
dtoverlay=vc4-kms-dsi-waveshare-panel-v2,5_0_inch_a
dtoverlay=hifiberry-dac
dtoverlay=disable-bt
temp_soft_limit=70
```
Don't set any kernel rotation. The device video encodes are pre-rotated.

## Enclosure
- Display opening ~120×73 mm; speaker opening 89 mm (ND90-8 fits flush).
- Pi on 5 mm nylon standoffs, amp near the GPIO header, BH1750 rear-facing.
- **Ventilation (new, required):** intake holes low on the back or bottom and
  exhaust holes high, with the heatsinked SoC in that airflow path. v2 throttled
  at 60 °C inside the closed box.
- Put a partition between the speaker cavity and the electronics.
- Power enters via a rear micro-USB cutout.
