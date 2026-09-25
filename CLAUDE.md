# Tuesday Dream Machine (Sleepbox v3)

An ambient sound machine + night light for a toddler's room, on a Raspberry Pi
3A+ (512 MB). Read `docs/ARCHITECTURE.md` and `docs/CONTRACTS.md` before any
work, and `docs/MILESTONES.md` for the current milestone.

## Hard rules
1. `sleepd` is the ONLY component that mutates state or touches hardware (mpv
   included). Everything else is a WebSocket client.
2. `docs/CONTRACTS.md` is pinned. Copy it exactly and never extend it without
   asking Peter.
3. No browser on the device. Video and audio are played by mpv, controlled by
   sleepd over JSON IPC.
4. Dependencies: Python — `aiohttp`, `smbus2`, `evdev`, `Pillow` only. Phone UI
   — plain HTML/CSS/JS, no framework, no bundler, no network fonts or assets at
   runtime. Node only inside `matter-bridge/`.
5. `sleepd/state.py` stays pure (no I/O) and pytest-covered. Hardware drivers
   are the only mockable seam, and `SLEEPBOX_MOCK=1` runs everything on a
   laptop.
6. RAM budget: mpv video ≤ 90 MB, mpv audio ≤ 30 MB, sleepd ≤ 50 MB,
   matter-bridge ≤ 100 MB. Measure on-device before calling a milestone done.
7. Never commit generated media (`content/`, `media/out/`). This covers Tuesday's
   likeness and the licensed-character Campfire scene. Commit prompts, job specs,
   tools and the manifest only.
8. Do NOT implement alarms, wake-up features, cloud calls, telemetry, or
   anything outside the current milestone.
9. Never store passwords or API keys in the repo.
10. If a requirement is ambiguous or two docs conflict, STOP and ask Peter.
