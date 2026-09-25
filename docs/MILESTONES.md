# Milestones

Work on one milestone per session. Don't advance until every acceptance
criterion passes. Peter reviews between milestones. The media track (MA–ME)
runs in parallel with the software track.

## Software track

### M0 — Core on a laptop (mock mode)
- Repo skeleton, `sleepd/state.py` implementing every command in
  [CONTRACTS.md](CONTRACTS.md), with pytest coverage.
- `server.py`: `/ws`, static phone UI, `/healthz`, `/content`.
- Mock drivers (backlight → `/tmp/sleepbox/backlight`, scripted lux curve,
  softvol logging). `player.py` drives a windowed mpv.
- A basic phone UI (scenes, volume, timer, brightness chips).

**ACCEPT:** pytest green. `SLEEPBOX_MOCK=1 python -m sleepd` plays placeholder
loops in an mpv window. Two browser tabs stay in sync within 1 s. A scene switch
fades through black with an audio dip.

### M1 — Pi bring-up + thermal gate (go/no-go)
- Pi OS Lite 64-bit, `deploy/install.sh`, config.txt fragment, zram, systemd
  units for sleepd.
- mpv on DRM with `v4l2m2m-copy` playing a pre-rotated 720×1280 test loop.
- Heatsink + vented enclosure fitted (Peter).
- Measure the loop wrap: plain `loop-file` on a 16–24 s file vs. a
  pre-concatenated 10-minute file. Pick one and record why.

**ACCEPT:** cold boot → looping scene with audio in ≤ 30 s. Logs confirm
hardware decode. After 30 min: `get_throttled == 0x0`, temp < 65 °C,
`free -m` ≥ 150 MB available, and no visible hitch at the loop wrap.

### M2 — Real hardware + on-device UI
- Backlight sysfs, BH1750 auto-dim curve with slew limiting, ALSA softvol
  ceiling.
- `touch.py` (evdev, coordinate mapping, parent lock) and `overlay.py` (clock +
  control sheet via mpv `overlay-add`).

**ACCEPT:** covering the sensor dims toward 13 (slew temporarily shortened for
the test). Short taps never do anything. A 3 s hold opens the sheet, and every
button works. 20 s idle relocks. Max volume at the speaker is audibly capped.

### M3 — Matter bridge
- `matter-bridge/` (matter.js) as a WS client: Night Light, Sound, and four scene
  plugs. Commission into Apple Home and Google Home (multi-admin).

**ACCEPT:** "Hey Siri, turn on Rain" switches scene. The Google Home brightness
slider moves the backlight. All surfaces agree on state afterward. The bridge
stays ≤ 100 MB RSS.

### M4 — Nighttime behaviors + persistence
Bedtime schedule, sleep timer end-to-end (45 s fade, `timer_end`), and state
persistence.

**ACCEPT:** a pytest with a mocked clock fires 19:00 → 20:30 → 06:30 in order.
On-device, a 15-min timer ends with a smooth fade. Pulling power mid-scene
restores the same scene, volume and brightness mode.

### M5 — Hardening
overlayfs read-only root, hardware watchdog, `Restart=always`, HDMI/BT off.

**ACCEPT:** 10 hard power pulls boot clean and resume. Killing mpv or sleepd
recovers to a playing scene in < 15 s. A 24 h soak shows stable RSS and no OOM.

## Media track (see media/README.md)

- **MA — Character sheet:** a text-only character turnaround of Tuesday. Peter
  approves it before anything else is generated.
- **MB — Keyframes:** 4 candidates per scene, using the character sheet as the
  image reference. Peter picks one per scene.
- **MC — Veo takes:** 3 first=last-frame takes per scene, from the chosen
  keyframe.
- **MD — Build loops:** `build_loop.py` chains takes into 16–24 s loops, runs the
  seam check, and makes the master + device encodes. Peter watches each loop
  for 3+ minutes.
- **ME — Audio:** brown noise (synthesized); ocean, rain and fire from CC0
  recordings via `make_audio_loop.sh`. Loudness-matched, 60–90 s mono FLAC.
