# Media pipeline — scenes and audio

Generation runs on the **Dell**, where Hermes and a Claude Code session live. The
job specs in `media/jobs/` are the source of truth for every prompt. Generated
files stay on the Dell (`media/out/`) and the Pi (`/opt/sleepbox/content/`), and
are **never committed** (see `.gitignore`).

## Connecting the Dell session
The Dell is available as the Claude Code environment `hermes`
(`env_016pcKYjyhq4rsVQHdootgom`, a bridge environment). The project session starts a
session there for each stage and gives it the job file contents.

**All Nano Banana and Veo generation goes through Hermes using Antigravity.** The Dell
session asks Hermes to run each job in Antigravity; nothing calls the Google APIs directly.

## Stages

| Stage | Input | Hermes → Antigravity call | Output (on the Dell) | Gate |
|---|---|---|---|---|
| MA | `00_character_sheet.json` | Nano Banana, 4 candidates | `media/out/character_sheet/cand_{1..4}.png` | Peter picks one → `character_sheet.png` |
| MB | `0N_<scene>.json` → `image` | Nano Banana, 4 candidates, reference = chosen character sheet | `media/out/<scene>/keyframe_{1..4}.png` | Peter picks one → `keyframe.png` |
| MC | `0N_<scene>.json` → `video` | Veo image-to-video, **first frame = last frame = keyframe.png**, 8 s, no audio, 3 takes | `media/out/<scene>/take_{1..3}.mp4` | Discard takes with morphing faces or camera moves |
| MD | good takes | — (local) | `content/<scene>.mp4`, `master_<scene>.mp4`, `<scene>.jpg` | Seam check passes; Peter watches 3+ min |
| ME | CC0 recordings / synthesized | — (local) | `content/audio_<scene>.flac` | Loudness-matched, no audible wrap |

Rules for Hermes calls:
- Use the prompt text exactly as written in the job file. If a model rejects a
  prompt, report back rather than rewording it silently. Campfire has an
  approved `fallback_prompt`.
- **No photo of Tuesday is used anywhere.** Her likeness comes from the text
  description plus the generated character sheet.
- Record every chosen output in `media/manifest.json`: file name, model and
  version, seed if available, date, and SHA-256. The manifest IS committed; the
  files are not.

## Why first frame = last frame
Veo can't guarantee a seamless loop from a single start image. Pinning both ends
of every take to the same keyframe means each take starts and ends on the same
image. Chaining 2–3 different takes gives a 16–24 s loop with visible variety,
where every join (and the final wrap) lands on that identical keyframe. v2's
6-second single-take loops wrapped every 6 s and had to have their seams
repaired after the fact.

## MD — building a loop
```
python3 media/tools/build_loop.py ocean media/out/ocean/take_1.mp4 media/out/ocean/take_3.mp4 \
    --out-dir content --rotate cw [--repeat-minutes 10]
```
- Normalizes each take to 1280×720 @ 24 fps and checks SSIM at every join and at
  the wrap (default threshold 0.97; it fails loudly if a take doesn't return to
  the keyframe).
- Drops each take's final frame (a duplicate of the next take's first frame),
  concatenates, and bakes the vignette in.
- Encodes the landscape master and the pre-rotated 720×1280 device file (H.264
  High, keyint 48, CRF 20 capped at 2.5 Mbps, no audio, faststart), plus a
  preview JPEG.
- `--rotate` must match how the panel is physically mounted; confirm in M1.
  `--repeat-minutes` writes a long pre-looped file if M1 shows a hitch at the
  wrap.

## ME — audio
```
media/tools/make_audio_loop.sh content/audio_space.flac brown 90 3
media/tools/make_audio_loop.sh content/audio_ocean.flac ~/sounds/waves.wav 12 90 3
```
- Space is brown noise, synthesized. Nothing needs licensing.
- Ocean, rain and campfire come from **CC0** field recordings (Freesound with
  the CC0 license filter). Put the source URL and author in the manifest.
  Pick 60–90 s stretches with no distinct events (no voices, gull screams, or
  thunder cracks) — anything memorable becomes an obvious repeat.
- The script pre-filters (40 Hz high-pass), normalizes every loop to −30 LUFS,
  and crossfades the tail into the head so the wrap is seamless. The output is
  FLAC, because Opus end padding caused an audible click at the wrap.
