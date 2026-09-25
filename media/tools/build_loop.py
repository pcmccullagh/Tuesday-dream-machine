#!/usr/bin/env python3
"""Chain Veo first=last-frame takes into one seamless loop and encode it.

Each take starts and ends on the same keyframe, so takes can be chained
end-to-end: drop each take's final frame (it duplicates the next take's first
frame) and concatenate. Veo often reaches the keyframe a few frames early and
drifts past it, so with --tail-search N the cut point is instead whichever of
the last N frames best matches the next take's first frame. The wrap from the last take back to the first lands on
that same keyframe.

Outputs (in --out-dir):
  master_<scene>.mp4   landscape 1280x720, archive + phone preview
  <scene>.mp4          device encode, pre-rotated to 720x1280 portrait
  <scene>.jpg          landscape preview still (frame 0)
  <scene>_long.mp4     optional, device encode repeated to --repeat-minutes

Encode spec: H.264 High, yuv420p, 24 fps, keyint 48 (no scene-cut keyframes),
CRF 20 capped at 2.5 Mbps, no audio track, +faststart.

Only needs python3 + ffmpeg/ffprobe on PATH.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

W, H, FPS = 1280, 720, 24
ENCODE = [
    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
    "-r", str(FPS), "-g", "48", "-keyint_min", "48", "-sc_threshold", "0",
    "-crf", "20", "-maxrate", "2500k", "-bufsize", "5000k",
    "-an", "-movflags", "+faststart",
]
TRANSPOSE = {"cw": "transpose=1", "ccw": "transpose=2"}


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{p.stderr[-2000:]}")
    return p


def frame_count(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
               "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)]).stdout
    return int(json.loads(out)["streams"][0]["nb_read_frames"])


def ssim(a, a_frame, b, b_frame):
    """SSIM between frame a_frame of file a and frame b_frame of file b."""
    graph = (f"[0:v]select=eq(n\\,{a_frame}),setpts=PTS-STARTPTS[a];"
             f"[1:v]select=eq(n\\,{b_frame}),setpts=PTS-STARTPTS[b];[a][b]ssim")
    err = run(["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b),
               "-lavfi", graph, "-frames:v", "1", "-f", "null", "-"]).stderr
    m = re.search(r"All:([0-9.]+)", err)
    if not m:
        sys.exit(f"could not measure SSIM between {a} and {b}")
    return float(m.group(1))


def normalize(src, dst):
    """Conform a take to 1280x720 @ 24 fps (cover-crop), near-lossless intermediate."""
    vf = (f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},setsar=1")
    run(["ffmpeg", "-hide_banner", "-y", "-i", str(src), "-vf", vf, "-an",
         "-c:v", "libx264", "-crf", "10", "-preset", "fast", "-pix_fmt", "yuv420p", str(dst)])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", help="scene id: ocean | rain | space | campfire")
    ap.add_argument("takes", nargs="+", type=Path, help="Veo takes in play order")
    ap.add_argument("--out-dir", type=Path, default=Path("content"))
    ap.add_argument("--rotate", choices=["cw", "ccw", "none"], default="cw",
                    help="device encode rotation to match how the panel is mounted (verify in M1)")
    ap.add_argument("--vignette", default="PI/5", help="ffmpeg vignette angle, or 'none'")
    ap.add_argument("--repeat-minutes", type=float, default=0,
                    help="also write <scene>_long.mp4 repeated to about this length")
    ap.add_argument("--seam-threshold", type=float, default=0.97,
                    help="minimum SSIM at every join and at the wrap")
    ap.add_argument("--tail-search", type=int, default=12,
                    help="cut each take at the best-matching of its last N frames (1 = always the final frame)")
    ap.add_argument("--force", action="store_true", help="encode even if a seam fails")
    ap.add_argument("--chain-only", type=Path, metavar="OUT",
                    help="write the chained takes (no vignette, CRF 10, plus a closing copy of frame 0) "
                         "for post-processing, then stop. Feed the result back in as a single take "
                         "with --tail-search 1.")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        norm, counts = [], []
        for i, take in enumerate(args.takes):
            dst = tmp / f"take{i}.mp4"
            normalize(take, dst)
            norm.append(dst)
            counts.append(frame_count(dst))
            print(f"take {i}: {take.name}  {counts[-1]} frames")

        # Seam check: the dropped cut frame of take i should match the first
        # frame of the next take (the last take wraps to take 0). The cut frame
        # is the best match among the last --tail-search frames.
        failed = False
        cuts = []
        for i in range(len(norm)):
            j = (i + 1) % len(norm)
            tail = range(counts[i] - 1, max(counts[i] - 1 - max(args.tail_search, 1), 0), -1)
            s, cut = max((ssim(norm[i], f, norm[j], 0), f) for f in tail)
            cuts.append(cut)
            label = "wrap" if j == 0 else "join"
            ok = s >= args.seam_threshold
            failed |= not ok
            print(f"{label} take{i} -> take{j}: SSIM {s:.4f} at frame {cut}/{counts[i] - 1} "
                  f"{'ok' if ok else 'FAIL'}")
        if failed and not args.force:
            sys.exit("seam check failed: regenerate the offending take, or pass --force")

        # Chain: cut each take before its cut frame, concatenate, bake vignette.
        inputs, parts = [], []
        for i, (path, cut) in enumerate(zip(norm, cuts)):
            inputs += ["-i", str(path)]
            parts.append(f"[{i}:v]trim=end_frame={cut},setpts=PTS-STARTPTS[v{i}]")
        chain = "".join(f"[v{i}]" for i in range(len(norm)))
        if args.chain_only:
            # Closing frame = take 0's first frame, so the chain is a closed loop
            # that a second build_loop pass (--tail-search 1) cuts exactly.
            inputs += ["-i", str(norm[0])]
            parts.append(f"[{len(norm)}:v]trim=end_frame=1,setpts=PTS-STARTPTS[close]")
            graph = ";".join(parts) + f";{chain}[close]concat=n={len(norm) + 1}:v=1:a=0[out]"
            run(["ffmpeg", "-hide_banner", "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
                 "-c:v", "libx264", "-crf", "10", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", str(FPS),
                 str(args.chain_only)])
            print(f"chain: {args.chain_only}  {sum(cuts) + 1} frames ({sum(cuts)} + closing frame)")
            return
        graph = ";".join(parts) + f";{chain}concat=n={len(norm)}:v=1:a=0"
        if args.vignette != "none":
            graph += f",vignette={args.vignette}"
        graph += "[out]"
        master = args.out_dir / f"master_{args.scene}.mp4"
        run(["ffmpeg", "-hide_banner", "-y", *inputs, "-filter_complex", graph,
             "-map", "[out]", *ENCODE, str(master)])
        total = sum(cuts)
        print(f"master: {master}  {total} frames = {total / FPS:.1f}s")

    device = args.out_dir / f"{args.scene}.mp4"
    if args.rotate == "none":
        run(["ffmpeg", "-hide_banner", "-y", "-i", str(master), "-c", "copy",
             "-movflags", "+faststart", str(device)])
    else:
        run(["ffmpeg", "-hide_banner", "-y", "-i", str(master), "-vf", TRANSPOSE[args.rotate],
             *ENCODE, str(device)])
    print(f"device: {device}  (rotate={args.rotate})")

    preview = args.out_dir / f"{args.scene}.jpg"
    run(["ffmpeg", "-hide_banner", "-y", "-i", str(master), "-frames:v", "1", "-q:v", "3", str(preview)])
    print(f"preview: {preview}")

    if args.repeat_minutes > 0:
        loops = max(1, round(args.repeat_minutes * 60 * FPS / total))
        long = args.out_dir / f"{args.scene}_long.mp4"
        run(["ffmpeg", "-hide_banner", "-y", "-stream_loop", str(loops - 1), "-i", str(device),
             "-c", "copy", "-movflags", "+faststart", str(long)])
        print(f"long: {long}  {loops} loops = {loops * total / FPS / 60:.1f} min")


if __name__ == "__main__":
    main()
