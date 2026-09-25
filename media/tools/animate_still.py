#!/usr/bin/env python3
"""Animate a keyframe procedurally: twinkling stars and a gentle breathing warp.

For scenes where only tiny, exact motions are wanted (space), this avoids a
video model entirely: nothing can appear that wasn't asked for, and the
output loops perfectly because every motion's period divides the loop length.

  animate_still.py space/keyframe.png space/anim_1.mp4 \
      --breath 720,450,60,2.5,0.43,-0.9 --breath-period 4

Stars: small bright points found with a white top-hat (outside --exclude
boxes). Each star's own light, not the sky behind it, is scaled by a slow
smooth pulse with a random phase and period (an integer fraction of the loop).

Breathing: a smooth Gaussian bump (cx, cy, sigma, amplitude px, direction
nx, ny) shifts pixels along the direction and back, once per
--breath-period seconds. Keep the bump on the torso, away from the face.

Output is loop_seconds*fps + 1 frames: the final frame equals frame 0, which
build_loop.py drops at the wrap. Encoded x264 CRF 10 as an intermediate.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


def find_stars(img, exclude, scales):
    """Label small bright points. scales: [(tophat_px, max_area, thresh), ...], small to large."""
    lum = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Never treat the moon (or any other big bright body) as stars.
    big = (cv2.GaussianBlur(lum, (0, 0), 5) > 185).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(big, 8)
    body = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > 5000])
    body = cv2.dilate(body.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    labels = np.zeros(lum.shape, np.int32)
    light = np.zeros(img.shape, np.float32)
    total = 0
    for px, max_area, thresh in scales:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (px, px))
        th = cv2.morphologyEx(lum, cv2.MORPH_TOPHAT, k)
        seeds = ((th > thresh) & ~body & (labels == 0)).astype(np.uint8)
        for x0, y0, x1, y1 in exclude:
            seeds[y0:y1, x0:x1] = 0
        n, lab, st, _ = cv2.connectedComponentsWithStats(seeds, 8)
        ok = np.zeros(n, bool)
        ok[1:] = st[1:, cv2.CC_STAT_AREA] <= max_area
        lab[~ok[lab]] = 0
        # Grow each star's label a little so its soft glow is included.
        grow = max(5, px // 4) | 1
        lab = cv2.dilate(lab.astype(np.float32), np.ones((grow, grow), np.uint8)).astype(np.int32)
        lab[labels > 0] = 0
        new = lab > 0
        labels[new] = lab[new] + labels.max()
        own = np.dstack([cv2.morphologyEx(img[..., c], cv2.MORPH_TOPHAT, k) for c in range(3)]).astype(np.float32)
        feather = cv2.GaussianBlur(new.astype(np.float32), (0, 0), 1.2)[..., None]
        light += own * feather * (light == 0)
        total += int(ok.sum())
    return labels, light, total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keyframe", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--loop-seconds", type=int, default=24)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--exclude", action="append", default=[],
                    help="x0,y0,x1,y1 box with no stars (repeatable), keyframe pixels")
    ap.add_argument("--star-scales", default="15:120:28,41:1200:75",
                    help="top-hat size:max area:threshold, small stars first then big sparkles")
    ap.add_argument("--twinkle-depth", type=float, default=0.7, help="0..1, how far stars dim at the trough")
    ap.add_argument("--twinkle-min-s", type=float, default=3.0, help="shortest twinkle period, seconds")
    ap.add_argument("--breath", help="cx,cy,sigma,amp_px,nx,ny (keyframe pixels)")
    ap.add_argument("--breath-period", type=float, default=4.0, help="seconds; must divide the loop length")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    if args.out.exists():
        sys.exit(f"{args.out} exists; not overwriting")

    img = cv2.imread(str(args.keyframe), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    base = img.astype(np.float32)
    L, fps = args.loop_seconds, args.fps
    nframes = L * fps
    rng = np.random.default_rng(args.seed)

    exclude = [tuple(int(v) for v in e.split(",")) for e in args.exclude]
    scales = [tuple(int(v) for v in sc.split(":")) for sc in args.star_scales.split(",")]
    labels, light, nstars = find_stars(img, exclude, scales)
    nl = labels.max() + 1
    max_cycles = max(1, int(L / args.twinkle_min_s))
    cycles = rng.integers(1, max_cycles + 1, nl)       # whole cycles per loop -> seamless
    phase = rng.uniform(0, 2 * np.pi, nl)
    depth = rng.uniform(0.4, 1.0, nl) * args.twinkle_depth
    print(f"stars: {nstars}  twinkle periods {L / max_cycles:.1f}-{L:.0f}s")

    if args.breath:
        cx, cy, sig, amp, nx, ny = (float(v) for v in args.breath.split(","))
        if abs(L / args.breath_period - round(L / args.breath_period)) > 1e-6:
            sys.exit("--breath-period must divide --loop-seconds")
        norm = np.hypot(nx, ny)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        bump = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sig * sig))
        bx, by = bump * nx / norm * amp, bump * ny / norm * amp

    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264",
                            "-crf", "10", "-preset", "slow", "-pix_fmt", "yuv420p", str(args.out)],
                           stdin=subprocess.PIPE)
    for f in range(nframes + 1):
        t = f / fps
        # Smooth pulse in [0, 1]: 1 = full brightness, 0 = deepest dim.
        pulse = 0.5 * (1 + np.cos(2 * np.pi * cycles * t / L + phase))
        factor = (1 - depth * (1 - pulse)).astype(np.float32)
        factor[0] = 1.0
        frame = base + (factor[labels] - 1.0)[..., None] * light
        if args.breath:
            s = 0.5 * (1 - np.cos(2 * np.pi * t / args.breath_period))   # 0 at loop start
            frame = cv2.remap(frame, (xx - bx * s).astype(np.float32), (yy - by * s).astype(np.float32),
                              cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REFLECT)
        enc.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("ffmpeg failed")
    print(f"saved {args.out}  {nframes + 1} frames ({L}s loop + closing frame)")


if __name__ == "__main__":
    main()
