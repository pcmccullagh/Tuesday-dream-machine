#!/usr/bin/env python3
"""Run media job specs against the Gemini API (Nano Banana images, Veo video).

Standard library only. Reads GEMINI_API_KEY from the environment, or from
~/.hermes/.env. Never prints the key.

  gemini_media.py image  media/jobs/01_ocean.json --ref character_sheet.png
  gemini_media.py video  media/jobs/01_ocean.json --keyframe ocean/keyframe.png
  gemini_media.py video  ... --dry-run          # print the request, no API call

Outputs go to $MEDIA_ROOT (default ~/TuesdayDreamMachine-media):
  image: <scene>/keyframe_<n>.png   (character sheet: character_sheet/v3/cand_<n>.png)
  video: <scene>/take_<n>.mp4
Each output gets a sidecar <file>.json (model, prompt, request params, sha256,
timestamp) and an entry appended to $MEDIA_ROOT/generation_log.jsonl.
Existing files are never overwritten; numbering continues after the last one.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta"
IMAGE_MODEL = "gemini-3-pro-image"          # Nano Banana Pro
VIDEO_MODEL = "veo-3.1-generate-preview"    # Veo 3.1 (supports lastFrame)
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", Path.home() / "TuesdayDreamMachine-media"))


def api_key():
    key = os.environ.get("GEMINI_API_KEY")
    env = Path.home() / ".hermes" / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("GEMINI_API_KEY not set (env or ~/.hermes/.env)")
    return key


def request(method, url, key, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {url.split('?')[0]}:\n{e.read().decode(errors='replace')[:4000]}")
    return payload if raw else json.loads(payload)


def inline_image(path):
    path = Path(path)
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return mime, base64.b64encode(path.read_bytes()).decode()


def next_path(folder, stem, ext):
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while (folder / f"{stem}_{n}{ext}").exists():
        n += 1
    return folder / f"{stem}_{n}{ext}"


def record(out, meta):
    meta = dict(meta, file=str(out.relative_to(MEDIA_ROOT)),
                sha256=hashlib.sha256(out.read_bytes()).hexdigest(),
                created=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    out.with_suffix(out.suffix + ".json").write_text(json.dumps(meta, indent=2) + "\n")
    with open(MEDIA_ROOT / "generation_log.jsonl", "a") as log:
        log.write(json.dumps(meta) + "\n")
    print(f"saved {out}  sha256={meta['sha256'][:12]}…")


def redact(body):
    """Copy of a request body with base64 image data shortened, for logs."""
    def walk(o):
        if isinstance(o, dict):
            return {k: (f"<{len(v)} b64 chars>" if k in ("data", "bytesBase64Encoded") else walk(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o
    return walk(body)


def cmd_image(args, job):
    spec = job["image"]
    model = args.model or IMAGE_MODEL
    prompt = spec["prompt"] if not args.fallback else spec["fallback_prompt"]
    if args.ref:
        prompt += (" The attached image is Tuesday's character reference sheet: match her face, hair,"
                   " age and proportions exactly, but do not copy its layout, pose, outfit or background.")
    parts = [{"text": prompt}]
    for ref in args.ref:
        mime, data = inline_image(ref)
        parts.append({"inline_data": {"mime_type": mime, "data": data}})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "imageConfig": {"aspectRatio": spec.get("aspect_ratio", "16:9")}}}
    if args.dry_run:
        print(json.dumps(redact(body), indent=2)); return
    key = api_key()
    folder, stem = ((MEDIA_ROOT / "character_sheet" / "v3", "cand") if job["id"] == "character_sheet"
                    else (MEDIA_ROOT / job["id"], "keyframe"))
    for i in range(args.n):
        resp = request("POST", f"{API}/models/{model}:generateContent", key, body)
        images = [p["inlineData"] for c in resp.get("candidates", [])
                  for p in c.get("content", {}).get("parts", []) if "inlineData" in p]
        if not images:
            print(f"candidate {i + 1}: no image returned:\n{json.dumps(resp)[:2000]}"); continue
        img = images[0]
        ext = ".png" if img.get("mimeType", "").endswith("png") else ".jpg"
        out = next_path(folder, stem, ext)
        out.write_bytes(base64.b64decode(img["data"]))
        record(out, {"job": job["id"], "stage": "image", "model": model, "prompt": parts[0]["text"],
                     "references": [str(r) for r in args.ref], "request": redact(body)})


def cmd_video(args, job):
    spec = job["video"]
    model = args.model or VIDEO_MODEL
    mime, data = inline_image(args.keyframe)
    # The docs' REST example uses {"inlineData": ...}, but the API rejects it ("`inlineData` isn't supported").
    frame = {"bytesBase64Encoded": data, "mimeType": mime}
    instance = {"prompt": args.prompt or spec["prompt"], "image": frame}
    if not args.no_last_frame:
        instance["lastFrame"] = frame          # first frame == last frame -> loopable take
    params = {"aspectRatio": spec.get("aspect_ratio", "16:9"),
              "durationSeconds": int(args.duration or spec.get("duration_s", 8)),
              "resolution": spec.get("resolution", "720p")}
    if args.person_generation:
        params["personGeneration"] = args.person_generation
    if spec.get("negative_prompt") and "lite" not in model:  # Lite rejects negativePrompt (HTTP 400)
        params["negativePrompt"] = spec["negative_prompt"]
    body = {"instances": [instance], "parameters": params}
    if args.dry_run:
        print(json.dumps(redact(body), indent=2)); return
    key = api_key()
    for i in range(args.n):
        op = request("POST", f"{API}/models/{model}:predictLongRunning", key, body)
        name = op["name"]
        print(f"take {i + 1}: started {name}")
        while not op.get("done"):
            time.sleep(10)
            op = request("GET", f"{API}/{name}", key)
        if "error" in op:
            print(f"take {i + 1}: failed: {json.dumps(op['error'])}"); continue
        resp = op.get("response", {})
        samples = resp.get("generateVideoResponse", {}).get("generatedSamples", [])
        if not samples:
            print(f"take {i + 1}: no video returned (possibly filtered):\n{json.dumps(resp)[:2000]}"); continue
        uri = samples[0]["video"]["uri"]
        out = next_path(MEDIA_ROOT / job["id"], "take", ".mp4")
        out.write_bytes(request("GET", uri, key, raw=True))
        record(out, {"job": job["id"], "stage": "video", "model": model, "prompt": spec["prompt"],
                     "keyframe": str(args.keyframe), "first_equals_last": not args.no_last_frame,
                     "request": redact(body)})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["image", "video"])
    ap.add_argument("job", type=Path, help="media/jobs/*.json")
    ap.add_argument("-n", type=int, default=None, help="how many (default: job's candidates/takes)")
    ap.add_argument("--model", help=f"override model (default image {IMAGE_MODEL}, video {VIDEO_MODEL})")
    ap.add_argument("--ref", action="append", default=[], help="reference image (image mode, repeatable)")
    ap.add_argument("--fallback", action="store_true", help="use the job's fallback_prompt (campfire)")
    ap.add_argument("--keyframe", type=Path, help="first (and last) frame for video mode")
    ap.add_argument("--duration", type=int, choices=[4, 6, 8], help="override clip length (video)")
    ap.add_argument("--person-generation", choices=["allow_all", "allow_adult", "dont_allow"],
                    help="Veo personGeneration parameter (omitted by default)")
    ap.add_argument("--prompt", help="override the job prompt (for diagnostics only)")
    ap.add_argument("--no-last-frame", action="store_true", help="don't pin the last frame (not loopable)")
    ap.add_argument("--dry-run", action="store_true", help="print the request body and exit")
    args = ap.parse_args()
    job = json.loads(args.job.read_text())
    if args.kind == "video" and not args.keyframe:
        ap.error("video needs --keyframe")
    if args.kind == "video" and "lite" in (args.model or VIDEO_MODEL) and not args.no_last_frame:
        ap.error("Veo Lite rejects lastFrame (HTTP 400 'use case not supported'); use standard or fast, or --no-last-frame")
    if args.n is None:
        args.n = job.get(args.kind, {}).get("candidates" if args.kind == "image" else "takes", 1)
    (cmd_image if args.kind == "image" else cmd_video)(args, job)


if __name__ == "__main__":
    main()
