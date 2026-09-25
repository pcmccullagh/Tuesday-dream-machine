# Media pipeline — scenes and audio

Generation runs on the **Dell**. The job specs in `media/jobs/` are the source of
truth for every prompt. Generated files live in `~/TuesdayDreamMachine-media/` on
the Dell (and later `/opt/sleepbox/content/` on the Pi). They are **never
committed** (see `.gitignore`).

## How generation runs
- The Dell is the Claude Code environment `hermes` (`env_016pcKYjyhq4rsVQHdootgom`,
  a bridge environment). The project session starts a Dell session per stage.
- **Generation calls the Gemini API directly** through
  `media/tools/gemini_media.py` (standard library only). The key is
  `GEMINI_API_KEY` in `~/.hermes/.env`, which the script reads itself.
  - Images: `gemini-3-pro-image` (Nano Banana Pro), with the character sheet as
    a reference image.
  - Video: `veo-3.1-generate-preview` (Veo 3.1), with `image` and `lastFrame`
    both set to the keyframe. 8 s, 16:9, 720p.
- Why not Antigravity: its CLI has no video tool, doesn't expose the model
  version or seeds, and writes to a new random folder every run. (Round 1 and 2
  character sheets were made with it before the API key was added.)
- Veo 3.1 always generates an audio track. `build_loop.py` discards it; scene
  audio comes from stage ME.
- Every output gets a sidecar `<file>.json` (model, exact prompt, request
  parameters, sha256, time) and a line in `generation_log.jsonl`. Nothing is
  ever overwritten.

## Stages

| Stage | Command (on the Dell, repo root) | Output | Gate |
|---|---|---|---|
| MA | done (Antigravity, rounds 1–2); re-run: `gemini_media.py image media/jobs/00_character_sheet.json` | `character_sheet/…` | Peter picks one → copy to `character_sheet.png` |
| MB | `gemini_media.py image media/jobs/0N_<scene>.json --ref ~/TuesdayDreamMachine-media/character_sheet.png` | `<scene>/keyframe_{n}.png` | Peter picks one → copy to `<scene>/keyframe.png` |
| MC | `gemini_media.py video media/jobs/0N_<scene>.json --keyframe ~/TuesdayDreamMachine-media/<scene>/keyframe.png` | `<scene>/take_{n}.mp4` (3 takes) | Discard takes with morphing faces or camera moves |
| MD | `build_loop.py <scene> take_a.mp4 take_b.mp4 …` | `content/<scene>.mp4`, `master_<scene>.mp4`, `<scene>.jpg` | Seam check passes; Peter watches 3+ min |
| ME | `make_audio_loop.sh …` | `content/audio_<scene>.flac` | Loudness-matched, no audible wrap |

Rules:
- Use the prompt text exactly as written in the job file. If a model rejects a
  prompt, report it verbatim rather than rewording it. Campfire has an approved
  `fallback_prompt` (`--fallback`).
- **No photo of Tuesday is used anywhere.** Her likeness comes from the text
  description plus the generated character sheet.
- Record every **chosen** output in `media/manifest.json` (file, model, sha256,
  date). The manifest is committed; the files are not.
- Try `--dry-run` first to see the exact request without spending anything.

## Why first frame = last frame
Veo can't guarantee a seamless loop from a single start image. Pinning both ends
of every take to the same keyframe means each take starts and ends on the same
image. Chaining 2–3 different takes gives a 16–24 s loop with visible variety,
where every join (and the final wrap) lands on that identical keyframe. v2's
6-second single-take loops wrapped every 6 s and had to have their seams
repaired after the fact.

## MD — building a loop
```
python3 media/tools/build_loop.py ocean ~/TuesdayDreamMachine-media/ocean/take_1.mp4 ~/TuesdayDreamMachine-media/ocean/take_3.mp4 \
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
