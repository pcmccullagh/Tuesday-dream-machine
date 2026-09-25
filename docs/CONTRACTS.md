# Contracts (pinned)

These are the interfaces every component codes against. Don't extend them
without asking Peter.

## State object
sleepd broadcasts this to every client on connect and after every change:

```json
{
  "power": true,
  "scene": "rain",
  "volume": 40,
  "brightness": 180,
  "brightness_mode": "auto",
  "audio_only": false,
  "sleep_timer_ends_at": null,
  "schedule": {
    "enabled": true,
    "on_time": "19:00",
    "scene": "rain",
    "screen_off_time": "20:30",
    "off_time": "06:30"
  },
  "lux": 12.4,
  "scenes": [
    {
      "id": "rain",
      "name": "Rainy Forest",
      "video": "/content/rain.mp4",
      "preview": "/content/rain.jpg",
      "audio": "/content/audio_rain.flac",
      "accent": "rgba(150,190,235,0.55)"
    }
  ]
}
```

- `volume` is 0–100 (maps to mpv `volume`; the ALSA ceiling is applied beneath it).
- `brightness` is 0–255 (the backlight value currently targeted).
- `brightness_mode` is `"auto" | "full" | "soft" | "dim" | "night" | "manual"`.
  The presets map to fixed values (full 220, soft 140, dim 60, night 13 + video
  darkening). `manual` means the value was set directly (Matter slider).
- `sleep_timer_ends_at` is an ISO-8601 UTC timestamp or `null`.
- Scene ids: `ocean`, `rain`, `space`, `campfire`.

## WebSocket protocol
Endpoint: `ws://sleepbox.local:8080/ws`

Server → client: `{"type":"state","data":{…state…}}`

Client → server:
```json
{"type":"cmd","action":"set_power","value":true}
{"type":"cmd","action":"set_scene","value":"ocean"}
{"type":"cmd","action":"set_volume","value":55}
{"type":"cmd","action":"set_brightness","value":120}
{"type":"cmd","action":"set_brightness_mode","value":"auto"}
{"type":"cmd","action":"set_audio_only","value":true}
{"type":"cmd","action":"set_sleep_timer","value":30}
{"type":"cmd","action":"set_schedule","value":{…schedule…}}
```

- `set_brightness` sets `brightness_mode` to `"manual"`.
- `set_sleep_timer` takes minutes; `0` cancels.
- `set_scene` while `power=false` also powers on.
- An invalid command gets `{"type":"error","message":"…"}` back to that client
  only; state is unchanged.
- Clients never mutate state locally. They send a command and render the
  broadcast that follows.

## Behavior semantics

| State | Audio | Video | Backlight |
|---|---|---|---|
| `power=false` | stopped | black | 0 |
| `power=true, audio_only=true` | playing | black | 0 |
| `power=true, audio_only=false` | playing | scene looping | per `brightness_mode` |

- **Auto-dim:** lux ≥ 50 → 220; 10–50 lux → linear 60→220; < 10 lux → 13 (the
  5 % night-light floor, never fully dark). BH1750 is polled every 5 s, using
  the median of the last 6 readings. The slew is limited so a full-range
  traverse takes 15 min.
- **Scene switch:** ~0.4 s fade to black (video brightness + audio volume),
  load, then ~0.4 s fade in. Only one video decoder and one audio stream are
  ever live.
- **Sleep timer:** sleepd fades the audio over the final 45 s, ramps the
  backlight down, then applies `timer_end` (config; default `power=false`,
  alternative `audio_only`).
- **Bedtime schedule** (checked every 30 s): `on_time` → power on with
  `schedule.scene`; `screen_off_time` → `audio_only=true`; `off_time` →
  `power=false`.
- **All-night loop** is the default whenever no timer or schedule is due.
- **Parent lock (device touchscreen):** touches are ignored by default. A 3 s
  hold opens the control sheet, and 20 s idle closes it and relocks.
- **Persistence:** state is written to `/opt/sleepbox/config/state.json`
  (debounced 5 s) and restored on boot.
