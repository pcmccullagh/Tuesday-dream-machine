#!/usr/bin/env python3
"""Generate first=last-frame video takes through OpenRouter's video API.

Used for scenes Veo refuses (campfire: third-party characters). Same
conventions as gemini_media.py: the prompt comes from the job file, outputs
are never overwritten, and every take gets a sidecar <file>.json plus a line
in generation_log.jsonl. Standard library only. Reads OPENROUTER_API_KEY from
the environment or ~/.hermes/.env and never prints it.

  openrouter_video.py media/jobs/04_campfire.json --keyframe campfire/keyframe.png -n 1
  openrouter_video.py ... --model kwaivgi/kling-v3.0-std --provider-slug <slug>
  openrouter_video.py ... --dry-run

The keyframe is sent inline as a data: URL (JPEG q95), as both first_frame and
last_frame. Output: $MEDIA_ROOT/<scene>/take_<n>.mp4.
"""
import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", Path.home() / "TuesdayDreamMachine-media"))


def api_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    env = Path.home() / ".hermes" / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("OPENROUTER_API_KEY not set (env or ~/.hermes/.env)")
    return key


def request(method, url, key, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if url.startswith(API):
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {url.split('?')[0]}:\n{e.read().decode(errors='replace')[:4000]}")
    return payload if raw else json.loads(payload)


def data_url(path):
    """Keyframe as an inline JPEG data URL (keeps the request small)."""
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.open(path).convert("RGB").save(buf, "JPEG", quality=95)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        mime = "image/png" if Path(path).suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def redact(o):
    if isinstance(o, dict):
        return {k: redact(v) for k, v in o.items()}
    if isinstance(o, list):
        return [redact(v) for v in o]
    if isinstance(o, str) and o.startswith("data:"):
        return f"<{len(o)} char data URL>"
    return o


def next_path(folder, stem, ext):
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while (folder / f"{stem}_{n}{ext}").exists():
        n += 1
    return folder / f"{stem}_{n}{ext}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job", type=Path)
    ap.add_argument("--keyframe", type=Path, required=True)
    ap.add_argument("-n", type=int, default=1)
    ap.add_argument("--model", default="alibaba/wan-2.7")
    ap.add_argument("--provider-slug", default="atlas-cloud",
                    help="provider that receives the negative_prompt passthrough (Wan 2.7: atlas-cloud)")
    ap.add_argument("--no-negative", action="store_true", help="don't send the job's negative prompt")
    ap.add_argument("--duration", type=int, help="seconds (default: job's duration_s)")
    ap.add_argument("--resolution", help="default: job's resolution")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    job = json.loads(args.job.read_text())
    spec = job["video"]
    frame = data_url(args.keyframe)
    body = {
        "model": args.model,
        "prompt": spec["prompt"],
        "duration": args.duration or spec.get("duration_s", 8),
        "resolution": args.resolution or spec.get("resolution", "720p"),
        "aspect_ratio": spec.get("aspect_ratio", "16:9"),
        "generate_audio": False,
        "frame_images": [
            {"type": "image_url", "image_url": {"url": frame}, "frame_type": "first_frame"},
            {"type": "image_url", "image_url": {"url": frame}, "frame_type": "last_frame"},
        ],
    }
    if spec.get("negative_prompt") and not args.no_negative:
        body["provider"] = {"options": {args.provider_slug: {"parameters": {"negative_prompt": spec["negative_prompt"]}}}}
    if args.dry_run:
        print(json.dumps(redact(body), indent=2)); return

    key = api_key()
    for i in range(args.n):
        job_resp = request("POST", f"{API}/videos", key, body)
        print(f"take {i + 1}: submitted {job_resp.get('id')} status={job_resp.get('status')}")
        started = time.time()
        while job_resp.get("status") not in ("completed", "failed", "cancelled", "expired"):
            time.sleep(15)
            if time.time() - started > 1800:
                sys.exit(f"take {i + 1}: still {job_resp.get('status')} after 30 min; job {job_resp.get('id')}")
            poll = job_resp.get("polling_url") or f"{API}/videos/{job_resp['id']}"
            if poll.startswith("/"):
                poll = "https://openrouter.ai" + poll
            job_resp = request("GET", poll, key)
        if job_resp["status"] != "completed":
            print(f"take {i + 1}: {job_resp['status']}:\n{json.dumps(redact(job_resp))[:3000]}"); continue
        url = (job_resp.get("unsigned_urls") or [None])[0] or f"{API}/videos/{job_resp['id']}/content?index=0"
        out = next_path(MEDIA_ROOT / job["id"], "take", ".mp4")
        out.write_bytes(request("GET", url, key, raw=True))
        meta = {"job": job["id"], "stage": "video", "service": "openrouter", "model": args.model,
                "prompt": spec["prompt"], "keyframe": str(args.keyframe), "first_equals_last": True,
                "request": redact(body), "openrouter_job": job_resp.get("id"), "usage": job_resp.get("usage"),
                "file": str(out.relative_to(MEDIA_ROOT)), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
        out.with_suffix(".mp4.json").write_text(json.dumps(meta, indent=2) + "\n")
        with open(MEDIA_ROOT / "generation_log.jsonl", "a") as log:
            log.write(json.dumps(meta) + "\n")
        print(f"saved {out}  sha256={meta['sha256'][:12]}…  usage={job_resp.get('usage')}  "
              f"({time.time() - started:.0f}s)")


if __name__ == "__main__":
    main()
