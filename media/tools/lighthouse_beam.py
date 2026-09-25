#!/usr/bin/env python3
"""Replace the sky of a chained ocean loop and add a rotating lighthouse beam.

Veo draws a sweeping beam as a flat, hard-edged wedge. Instead, the sky is
held static from a beam-free plate, and a soft volumetric beam is rendered
analytically as a real rotating light: a cone from the lamp (orthographic
3D), foreshortened as it turns, flaring as it faces the viewer, and hidden
behind the tower as it faces away. Two opposed beams, like a real optic.

  lighthouse_beam.py ocean/chain_v1.mp4 ocean/keyframe_nobeam.png ocean/sky_mask.png \
      --tower-mask ocean/tower_mask.png --lamp 1122,130 -o ocean/chain_v1_beam.mp4

Input is a closed chain from `build_loop.py --chain-only` (the last frame is
a copy of frame 0). The beam completes --rotations turns over the chain, so
the closing frame matches frame 0 exactly. The plate and mask are in keyframe
pixels. They're aligned to the video by an ECC affine fit to frame 0.
Output is x264 CRF 10. Finish it with:
  build_loop.py ocean ocean/chain_v1_beam.mp4 --tail-search 1
"""
import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

W, H = 1280, 720


def read_frames(path):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(-1, H, W, 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chain", type=Path)
    ap.add_argument("plate", type=Path, help="beam-free sky plate, keyframe pixels")
    ap.add_argument("sky_mask", type=Path, help="8-bit mask, 255 = use the static plate")
    ap.add_argument("--lamp", required=True, help="x,y of the lamp centre, keyframe pixels")
    ap.add_argument("--tower-mask", type=Path, required=True,
                    help="8-bit lighthouse silhouette (keyframe px) that hides the beam facing away")
    ap.add_argument("--rotations", type=int, default=2, help="full turns per loop")
    ap.add_argument("--length", type=float, default=900, help="beam reach, keyframe px")
    ap.add_argument("--spread-deg", type=float, default=6.5, help="cone half-angle")
    ap.add_argument("--tilt", type=float, default=0.05, help="upward slope of the beam")
    ap.add_argument("--strength", type=float, default=0.55, help="beam opacity scale")
    ap.add_argument("--flare", type=float, default=0.9, help="extra glow when a beam faces the viewer")
    ap.add_argument("--color", default="255,232,190", help="R,G,B")
    ap.add_argument("--preview", type=Path, help="write stills at 8 beam angles to this PNG and stop")
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()
    if not args.preview and (not args.out or args.out.exists()):
        sys.exit("need -o OUT that doesn't exist yet (or --preview)")

    frames = read_frames(args.chain)
    n = len(frames) - 1                      # last frame closes the loop
    print(f"chain: {n} frames + closing frame")

    # Align plate (keyframe px) to video px.
    plate_k = cv2.imread(str(args.plate), cv2.IMREAD_COLOR)
    kh, kw = plate_k.shape[:2]
    sx, sy = W / kw, H / kh
    plate = cv2.resize(plate_k, (W, H), interpolation=cv2.INTER_AREA)
    f0 = cv2.GaussianBlur(cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 2)
    pg = cv2.GaussianBlur(cv2.cvtColor(plate, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 2)
    warp = np.eye(2, 3, dtype=np.float32)
    cc, warp = cv2.findTransformECC(pg, f0, warp, cv2.MOTION_AFFINE,
                                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-7), None, 5)
    print(f"alignment: ecc={cc:.4f}")
    wa = lambda im: cv2.warpAffine(im, warp, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    to_video = lambda x, y: (warp[0, 0] * x * sx + warp[0, 1] * y * sy + warp[0, 2],
                             warp[1, 0] * x * sx + warp[1, 1] * y * sy + warp[1, 2])
    plate = wa(plate).astype(np.float32)
    mask = cv2.resize(cv2.imread(str(args.sky_mask), cv2.IMREAD_GRAYSCALE), (W, H), interpolation=cv2.INTER_AREA)
    mask = (wa(mask).astype(np.float32) / 255)[..., None]

    tower = cv2.resize(cv2.imread(str(args.tower_mask), cv2.IMREAD_GRAYSCALE), (W, H), interpolation=cv2.INTER_AREA)
    tower = cv2.GaussianBlur(wa(tower).astype(np.float32) / 255, (0, 0), 1)

    lx, ly = to_video(*(float(v) for v in args.lamp.split(",")))
    scale = W / kw
    length, spread = args.length * scale, np.tan(np.radians(args.spread_deg))
    color = np.array([float(c) for c in args.color.split(",")][::-1], np.float32) / 255   # BGR

    # Beam lights the haze unevenly: static texture from the sky's own clouds.
    lum = cv2.cvtColor(plate.astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    tex = cv2.GaussianBlur(lum, (0, 0), 6)
    tex = 0.75 + 0.5 * (tex - tex.min()) / (np.ptp(tex) + 1e-6)

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    core = np.exp(-((xx - lx) ** 2 + (yy - ly) ** 2) / (2 * (5 * scale) ** 2))   # the lamp itself

    # The beam is built from soft splats along a 3D cone, at half resolution:
    # no hard edges at any angle, and foreshortening piles light up naturally.
    hw, hh = W // 2, H // 2
    step = 3.0 * scale                                                  # 3D spacing between splats
    svals = np.arange(0, length, step, dtype=np.float32)
    radii = 4 * scale + svals * spread
    amps = np.exp(-svals / (0.6 * length)) * np.clip(1 - svals / length, 0, 1) ** 1.5 / np.sqrt(radii / radii[0])
    amps *= step / (radii[0] * 2.5)

    def beam(phi):
        ax, az = np.cos(phi), np.sin(phi)                               # across screen, toward viewer
        acc = np.zeros((hh, hw), np.float32)
        for sv, r, amp in zip(svals, radii, amps):
            cx, cy = (lx + sv * ax) / 2, (ly - sv * args.tilt) / 2
            rh = r / 2
            x0, x1 = int(max(cx - 5 * rh, 0)), int(min(cx + 5 * rh + 1, hw))
            y0, y1 = int(max(cy - 5 * rh, 0)), int(min(cy + 5 * rh + 1, hh))
            if x0 >= x1 or y0 >= y1:
                continue
            gx = np.exp(-0.5 * ((np.arange(x0, x1, dtype=np.float32) - cx) / rh) ** 2)
            gy = np.exp(-0.5 * ((np.arange(y0, y1, dtype=np.float32) - cy) / rh) ** 2)
            acc[y0:y1, x0:x1] += amp * np.outer(gy, gx)
        d = cv2.resize(acc, (W, H), interpolation=cv2.INTER_LINEAR)
        if az < 0:                                                      # facing away: behind the tower
            d *= (1 - tower) * (0.6 + 0.4 * (1 + az))
        facing = max(az, 0.0) ** 4
        return d + facing * args.flare * np.exp(-((xx - lx) ** 2 + (yy - ly) ** 2) / (2 * (45 * scale) ** 2))

    def render(fr, theta):
        d = beam(theta) + beam(theta + np.pi)
        alpha = (0.85 * (1 - np.exp(-(args.strength * d * tex + 0.35 * core) / 0.85)))[..., None]   # soft roll-off
        base = fr.astype(np.float32) * (1 - mask) + plate * mask
        return np.clip(255 - (255 - base) * (1 - alpha * color), 0, 255).astype(np.uint8)   # screen blend

    if args.preview:
        tiles = [cv2.resize(render(frames[0], j * np.pi / 8), (W // 2, H // 2)) for j in range(8)]
        cv2.imwrite(str(args.preview), np.vstack([np.hstack(tiles[r * 2:r * 2 + 2]) for r in range(4)]))
        print(f"preview: {args.preview} (beam angle 0, 22.5, ... 157.5 deg)")
        return

    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                            "-r", "24", "-i", "-", "-c:v", "libx264", "-crf", "10", "-preset", "slow",
                            "-pix_fmt", "yuv420p", str(args.out)], stdin=subprocess.PIPE)
    for i, fr in enumerate(frames):
        enc.stdin.write(render(fr, 2 * np.pi * args.rotations * (i % n) / n).tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("ffmpeg failed")
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
