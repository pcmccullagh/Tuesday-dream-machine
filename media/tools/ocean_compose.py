#!/usr/bin/env python3
"""Build the ocean loop from layers, so every motion is constant and loops exactly.

Layers (all in keyframe pixels, output scaled to 1280x720 at the end):
  1. static plate: the keyframe with the beam and mermaid removed
  2. sea: a free-running water clip (no last-frame pin, so the waves never
     settle) inside sea_mask, aligned to the plate, looped with a crossfade
  3. Tuesday's hair: a wind warp from several gusts, each a whole number of
     cycles per loop (irregular, but seamless)
  4. mermaid cut-out (static) and a small painterly splash at her rock
  5. two soft lighthouse beams at a constant angular speed, a whole number of
     turns per loop (lighthouse_beam.Beam)

  ocean_compose.py ocean/water_1.mp4 -o ocean/compose_1.mp4

Output: --seconds*24 frames plus a closing copy of frame 0, x264 CRF 10, for
  build_loop.py ocean ocean/compose_1.mp4 --tail-search 1
"""
import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from lighthouse_beam import Beam  # noqa: E402

FPS = 24
OUT_W, OUT_H = 1280, 720


def read_frames(path, w, h, fps=FPS):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h}",
                        "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(-1, h, w, 3)


def ecc(template, image):
    g = lambda im: cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 2)
    warp = np.eye(2, 3, dtype=np.float32)
    cc, warp = cv2.findTransformECC(g(template), g(image), warp, cv2.MOTION_AFFINE,
                                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
    return cc, warp


def gust(t, L, parts):
    """Smooth, irregular signal in about [0, 1] that loops exactly over L seconds."""
    v = sum(a * np.sin(2 * np.pi * k * t / L + ph) for k, a, ph in parts)
    return 0.5 + 0.5 * v / sum(a for _, a, _ in parts)


class Splash:
    """Small bursts of spray and foam against the mermaid's rock."""

    def __init__(self, bursts, seed=7):
        rng = np.random.default_rng(seed)
        self.bursts = []
        for t0, (x, y), side in bursts:
            n = 22
            vx = side * rng.uniform(8, 60, n) + rng.normal(0, 8, n)
            vy = -rng.uniform(50, 135, n)
            r = rng.uniform(1.6, 3.6, n)
            life = rng.uniform(0.7, 1.5, n)
            dx = rng.normal(0, 6, n)
            self.bursts.append((t0, x, y, vx, vy, r, life, dx, side))

    def draw(self, t, w, h):
        """Return (alpha, x0, y0) for a small ROI, or None."""
        layers = []
        for t0, x, y, vx, vy, r, life, dx, side in self.bursts:
            a = t - t0
            if a < 0 or a > 1.8:
                continue
            roi = np.zeros((90, 140), np.float32)
            ox, oy = int(x) - 70, int(y) - 75
            # foam puff at the waterline
            k = a / 1.8
            cv2.ellipse(roi, (70, 75), (int(8 + 20 * k), int(3 + 6 * k)), 0, 0, 360, 0.55 * (1 - k) ** 1.5, -1)
            # soft mist rising off the rock
            mist = np.zeros_like(roi)
            cv2.circle(mist, (int(70 + side * 10 * k), int(70 - 30 * k)), int(6 + 16 * k),
                       float(0.35 * np.sin(np.pi * min(k * 1.4, 1))), -1)
            roi = np.maximum(roi, cv2.GaussianBlur(mist, (0, 0), 6))
            # spray droplets on ballistic arcs
            alive = a < life
            px = 70 + dx + vx * a
            py = 75 + vy * a + 0.5 * 260 * a * a
            fade = np.clip(1 - a / life, 0, 1) ** 1.2
            for xi, yi, ri, fi, al in zip(px, py, r, fade, alive):
                if al and 0 <= xi < 140 and 0 <= yi < 90:
                    cv2.circle(roi, (int(xi), int(yi)), max(1, int(round(ri))), float(0.6 * fi), -1, cv2.LINE_AA)
            layers.append((cv2.GaussianBlur(roi, (0, 0), 1.6), ox, oy))
        return layers


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("water", type=Path, help="free-running water clip")
    ap.add_argument("--dir", type=Path, default=Path.home() / "TuesdayDreamMachine-media" / "ocean",
                    help="folder with keyframe_nobeam.png, sea_mask.png, tower_mask.png, hair_mask.png, "
                         "mermaid_overlay.png")
    ap.add_argument("--seconds", type=int, default=24, help="loop length")
    ap.add_argument("--skip", type=float, default=1.5, help="seconds of water clip to skip at the start")
    ap.add_argument("--crossfade", type=float, default=2.0, help="water loop crossfade, seconds")
    ap.add_argument("--lamp", default="1122,130")
    ap.add_argument("--rotations", type=int, default=2, help="beam turns per loop (constant speed)")
    ap.add_argument("--wind", type=float, default=13.0, help="max hair displacement, keyframe px")
    ap.add_argument("--preview", type=Path, help="write 6 stills across the loop to this PNG and stop")
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()
    if not args.preview and (not args.out or args.out.exists()):
        sys.exit("need -o OUT that doesn't exist yet (or --preview)")

    d = args.dir
    plate = cv2.imread(str(d / "keyframe_nobeam.png"), cv2.IMREAD_COLOR)
    kh, kw = plate.shape[:2]
    platef = plate.astype(np.float32)
    sea = (cv2.imread(str(d / "sea_mask.png"), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255)[..., None]
    tower = cv2.GaussianBlur(cv2.imread(str(d / "tower_mask.png"), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255,
                             (0, 0), 1)
    merm = cv2.imread(str(d / "mermaid_overlay.png"), cv2.IMREAD_UNCHANGED).astype(np.float32)
    merm_a = merm[..., 3:] / 255
    hair = cv2.imread(str(d / "hair_mask.png"), cv2.IMREAD_GRAYSCALE)

    L, n = args.seconds, args.seconds * FPS
    C, S = int(args.crossfade * FPS), int(args.skip * FPS)

    # --- water: aligned to the plate, looped with a crossfade -------------
    water = read_frames(args.water, kw, kh)
    if len(water) < S + n + C:
        sys.exit(f"water clip too short: {len(water)} frames at {FPS} fps, need {S + n + C}")
    water = water[S:S + n + C]
    # Alignment can creep over a long clip: fit once a second and interpolate.
    keys = list(range(0, len(water), FPS)) + [len(water) - 1]
    warps = []
    for k in keys:
        cc, wp = ecc(plate, water[k])
        warps.append(wp)
    print(f"water: {len(water)} frames used; alignment ecc at start {ecc(plate, water[0])[0]:.4f}; "
          f"shift drift {np.hypot(*(warps[-1][:, 2] - warps[0][:, 2])):.2f} px over the clip")
    warps = np.array(warps)

    def water_frame(i):
        w = np.array([np.interp(i, keys, warps[:, r, c]) for r in range(2) for c in range(3)],
                     np.float32).reshape(2, 3)
        return cv2.warpAffine(water[i], w, (kw, kh), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_REPLICATE).astype(np.float32)

    def sea_at(i):
        if i < n - C:
            return water_frame(i + C)
        a = (i - (n - C) + 1) / (C + 1)                     # tail of the clip fades into its head
        return water_frame(i + C) * (1 - a) + water_frame(i - (n - C)) * a

    # --- hair wind field --------------------------------------------------
    yy, xx = np.mgrid[0:kh, 0:kw].astype(np.float32)
    zone = cv2.GaussianBlur(cv2.dilate(hair, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (37, 37)))
                            .astype(np.float32) / 255, (0, 0), 6)
    ramp_x = np.clip((xx - 890) / 60, 0, 1)                 # face and ear stay put; back of the bob moves
    ramp_y = np.clip((yy - 300) / 120, 0.25, 1)             # tips more than the crown
    field = zone * ramp_x * ramp_y
    field[yy > 438] *= 0                                    # never bend the horizon
    ys, xs = np.nonzero(field > 1e-3)
    hy0, hy1, hx0, hx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    fld = field[hy0:hy1, hx0:hx1]
    gx = [(2, 1.0, 0.3), (5, 0.6, 1.7), (9, 0.35, 4.1), (14, 0.2, 2.2)]
    gy = [(3, 1.0, 0.9), (11, 0.4, 3.3)]

    splash = Splash([(1.4, (240, 507), -1), (6.3, (368, 505), 1), (11.1, (246, 507), -1),
                     (15.7, (366, 505), 1), (20.2, (243, 507), -1)])
    lx, ly = (float(v) for v in args.lamp.split(","))
    beam = Beam(kw, kh, (lx, ly), tower, platef, scale=1.0)
    spray = np.array([248, 244, 236], np.float32)                     # BGR, slightly warm white

    def render(i):
        t = i / FPS
        f = platef * (1 - sea) + sea_at(i) * sea
        # hair: displaced by the wind (static sky behind it, so only hair visibly moves)
        dx = args.wind * (0.15 + 0.85 * gust(t, L, gx) ** 1.5)          # mostly gentle, now and then a gust
        dy = 1.2 * (2 * gust(t, L, gy) - 1)
        sub = cv2.remap(platef, (xx[hy0:hy1, hx0:hx1] - fld * dx).astype(np.float32),
                        (yy[hy0:hy1, hx0:hx1] - fld * dy).astype(np.float32),
                        cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        f[hy0:hy1, hx0:hx1] = np.where((fld > 1e-3)[..., None], sub, f[hy0:hy1, hx0:hx1])
        # mermaid (static) and splash
        f = f * (1 - merm_a) + merm[..., :3] * merm_a
        for roi, ox, oy in splash.draw(t, kw, kh):
            a = roi[..., None]
            f[oy:oy + roi.shape[0], ox:ox + roi.shape[1]] = (f[oy:oy + roi.shape[0], ox:ox + roi.shape[1]] * (1 - a)
                                                             + spray * a)
        out = beam.apply(f, 2 * np.pi * args.rotations * i / n)
        return cv2.resize(out, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)

    if args.preview:
        idx = [0, int(1.9 * FPS) % n, n // 3, n // 2, int(0.75 * n), n - C // 2]          # 1.9 s = mid-splash
        tiles = [cv2.resize(render(i), (OUT_W // 2, OUT_H // 2)) for i in idx]
        cv2.imwrite(str(args.preview), np.vstack([np.hstack(tiles[r * 2:r * 2 + 2]) for r in range(3)]))
        print(f"preview: {args.preview} (frames {idx})")
        return

    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{OUT_W}x{OUT_H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "10",
                            "-preset", "slow", "-pix_fmt", "yuv420p", str(args.out)], stdin=subprocess.PIPE)
    for i in range(n + 1):
        enc.stdin.write(render(i % n).tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("ffmpeg failed")
    print(f"saved {args.out}  {n + 1} frames ({L}s loop + closing frame)")


if __name__ == "__main__":
    main()
