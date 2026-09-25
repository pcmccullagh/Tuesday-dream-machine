# Tuesday Dream Machine — Architecture (v3)

A bedside ambient sound machine + night light for Tuesday's room. It plays four
looping animated scenes on a small landscape screen with matching ambient
audio, dims itself with the room, and is controlled from Apple Home / Siri,
Google Home, a phone web page, and a parent-locked touchscreen.

v3 is a from-scratch rebuild. Hardware is unchanged from v2 (see
[HARDWARE.md](HARDWARE.md)). The software is redesigned around the lessons of v2.

## What v2 taught us

| v2 problem | Root cause | v3 answer |
|---|---|---|
| Sluggish UI, crossfades abandoned | A full WPE WebKit browser compositing a CSS-rotated stage on a 512 MB Pi 3A+ | No browser on the device. `mpv` plays video straight to the display; the on-device UI is a few overlay images |
| Video froze / stalled at the loop wrap | Browser GStreamer pipeline + stateful v4l2m2m decoder at EOS; 6 s clips with a single I-frame | mpv `loop-file`, keyint-48 encodes, 16–24 s loops, and optionally pre-concatenated 10-minute files so a wrap happens rarely |
| Soft thermal throttling at 60 °C | Heat trapped in the wooden box + heavy compositing | Much lighter software load, plus heatsink and vents designed in from day one (M1 gate) |
| Two smart-home bridges (HAP-python + matter.js) | Historical | One Matter bridge — Apple Home and Google Home both speak Matter |
| 6 s loops with visible repetition and a hand-repaired seam | Raw Veo output, seam fixed after the fact | Veo first-frame = last-frame generation, several takes chained into a 16–24 s loop with seams that match by construction |
| ~5 s audio loops lifted from Veo soundtracks | No dedicated audio source | Brown noise synthesized; ocean/rain/fire from CC0 field recordings cut into 60–90 s crossfaded loops, loudness-matched |

## System overview

```
                 ┌──────────────────────── Raspberry Pi 3A+ ────────────────────────┐
 Apple Home ─┐   │                                                                   │
 Google Home ┴─Matter─► matter-bridge (Node, matter.js) ──┐                          │
                 │                                         │ WebSocket (same protocol)│
 Phone browser ─HTTP/WS─────────────────────────────────► sleepd (Python asyncio)    │
                 │                                         │  single source of truth │
                 │      ┌──────────────────────────────────┼───────────────┐          │
                 │      │ JSON IPC                          │ sysfs / I²C   │ evdev    │
                 │      ▼                                   ▼               ▼          │
                 │  mpv (video) ─► DSI panel     backlight, BH1750    GT911 touch     │
                 │  mpv (audio) ─► ALSA softvol cap ─► I²S MAX98357A ─► speaker       │
                 └───────────────────────────────────────────────────────────────────┘
```

### sleepd — the only thing that owns state or touches hardware
Python 3.11+ asyncio. Dependencies: `aiohttp`, `smbus2`, `evdev`, `Pillow`.

- `state.py` — pure state machine (no I/O), fully pytest-covered.
- `player.py` — drives two mpv processes over JSON IPC (video and audio). Fades
  (scene switch, sleep-timer fade-out, power on/off) are done here by stepping
  mpv properties. No other part of the system does fades.
- `display.py` — backlight sysfs, auto-dim curve, slew limiting.
- `sensor.py` — BH1750 poller.
- `touch.py` — reads the GT911 directly via evdev, maps portrait panel
  coordinates to landscape, implements the parent lock and hit-testing.
- `overlay.py` — renders the on-device UI (clock, control sheet) with Pillow into
  BGRA images and shows them via mpv `overlay-add`. Rendered once per minute for
  the clock, and on demand when the control sheet is open.
- `schedule.py` — bedtime schedule + sleep timer.
- `server.py` — aiohttp: `/ws` state bus, static phone UI at `/`, `/healthz`.
- `persist.py` — debounced state save/restore.
- Every hardware driver has a mock; `SLEEPBOX_MOCK=1` runs the whole stack on a
  laptop, with mpv in a normal window.

### Video path
- `mpv --vo=gpu --gpu-context=drm --hwdec=v4l2m2m-copy --loop-file=inf`, idle
  on black at boot, controlled only by sleepd.
- The panel is 720×1280 portrait mounted landscape. **Device encodes are
  pre-rotated to 720×1280** so there's no rotation at runtime. The landscape
  1280×720 masters are kept for phone previews and re-encodes.
- A scene switch is a fade through black: sleepd steps the mpv `brightness`
  property to −100 over ~0.4 s, runs `loadfile`, then fades back up. Only one
  decoder is ever live.
- The vignette is baked into the video at encode time (zero runtime cost).

### Audio path
- A second mpv instance (`--no-video --loop-file=inf`) plays the active scene's
  mono FLAC loop through ALSA.
- The ALSA softvol control `SleepboxVol` is a hard child-safe ceiling (80 %),
  set at install. Runtime volume is the mpv `volume` property, which only sleepd
  sets.
- Scene switch = volume dip (fade out → loadfile → fade in), matched to the
  video fade.
- All four loops are loudness-matched so switching scenes never jumps in volume.

### On-device UI (minimal)
- **Locked (default):** fullscreen scene plus a soft, dim clock. All touches are
  ignored.
- **3 s hold anywhere** opens the control sheet: four large scene buttons,
  volume − / +, sleep timer (cycles off → 15 → 30 → 45 → 60), and off.
- 20 s with no touch closes the sheet and relocks.
- No keyboard, dialogs, or text input on the device, ever.

### Phone UI
A static HTML/CSS/JS page served by sleepd at `http://sleepbox.local:8080`,
styled after the Dream prototype: scene buttons with previews, volume, sleep
timer, brightness chips (Auto · Full · Soft · Dim · Night), and schedule editor.
It's a pure WebSocket client — no framework, no build step, and no network fonts.

### Matter bridge
- A Node service using matter.js, set up as a Matter **bridge**
  (aggregator) with bridged endpoints:
  - **Night Light** — dimmable light (on/off ↔ power, level ↔ manual brightness)
  - **Sound** — dimmable light (level ↔ volume). A fan endpoint is an option if
    both ecosystems render it well; verify in M3.
  - **Ocean / Rain / Space / Campfire** — four on/off plugs, mutually exclusive
    (turning one on switches scene; only the active one reports on).
- It's a plain WebSocket client of sleepd using the same protocol as the phone
  UI. The v2 TCP line protocol is gone.
- Commissioned into Apple Home and Google Home via Matter multi-admin. Needs a
  home hub for each (HomePod/Apple TV, Nest hub) and IPv6 on the LAN.

### RAM budget (512 MB)
mpv video ≤ 90 MB · mpv audio ≤ 30 MB · sleepd ≤ 50 MB · matter-bridge ≤ 100 MB.
That's ~270 MB, leaving ~200 MB headroom, versus v2 where the browser alone was
budgeted 240 MB. CMA is 128 MB, and zram is 256 MB.

### Reliability
- Read-only root (overlayfs), with `/opt/sleepbox/config` on a writable partition.
- systemd `Restart=always` for everything, and the bcm2835 hardware watchdog.
- Last state is persisted (debounced 5 s) and restored on boot: a 2 am power cut
  comes back playing the same scene at the same volume.
- HDMI and Bluetooth are disabled. Target boot-to-scene is ≤ 30 s.
- Heatsink on the SoC and a vented enclosure, verified with
  `vcgencmd get_throttled == 0x0` after 30 min of playback.

## Content pipeline (runs off-device)

```
text character spec ─► Nano Banana: character sheet ─┐
                                                     ▼
            per-scene prompt ─► Nano Banana: keyframe A (16:9)
                                                     ▼
          Veo image-to-video, first frame = A, last frame = A, ×3 takes
                                                     ▼
   build_loop.py: chain takes → 16–24 s loop, bake vignette, conform encode,
                  seam check, pre-rotate device encode, optional 10-min repeat
                                                     ▼
                      content/<scene>.mp4  (+ master_<scene>.mp4)

CC0 recordings / synthesized brown noise ─► make_audio_loop.sh ─► content/audio_<scene>.flac
```

Generation runs on the Dell through Hermes. Job specs live in `media/jobs/`, and
the pipeline is described in [media/README.md](../media/README.md). Generated
media never goes into git: that covers Tuesday's likeness and the
licensed-character Campfire scene, and the files are too large anyway.

## Explicitly out of scope
Alarms or wake-up features · cloud services or telemetry · a native phone app ·
a browser on the device · multi-room support · canvas-rendered scenes.
