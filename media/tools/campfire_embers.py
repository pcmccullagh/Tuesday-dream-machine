#!/usr/bin/env python3
"""Replace the campfire's sparks with procedural embers that rise into the sky.

Wan's first=last-frame takes can't let a spark leave: everything has to be
back where it started by the last frame, so its sparks blink in place or bob
up and down. This tool:
  1. removes Wan's sparks inside a zone above the flames (small, bright orange
     specks only; flames, characters and green fireflies are untouched), and
  2. draws embers that spawn at the flame tips, rise with a little lift,
     curl sideways on the warm air, flicker, cool from yellow to orange to deep
     red, and fade. Embers pass behind Tuesday and Frog.

Every ember is timed modulo the loop length, so embers in the air at the loop
point carry straight through. Input is an open loop from
`build_loop.py --crossfade N --chain-only` (1280x720, 24 fps). Output adds a
closing copy of frame 0 (x264 CRF 10). Finish with:
  build_loop.py campfire campfire/chain_embers.mp4 --tail-search 1
"""
import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

W, H, FPS = 1280, 720, 24

# 1280x720 coordinates
REMOVE_ZONE = [(505, 0), (812, 0), (812, 232), (684, 232), (684, 495), (505, 495)]   # flames protected separately
OCCLUDERS = [  # embers pass behind these (Tuesday, Frog)
    [(684, 232), (900, 232), (900, 720), (684, 720)],
    [(330, 318), (505, 318), (505, 720), (330, 720)],
]
FIRE_X, FIRE_SPREAD, TIP_Y = 605.0, 20.0, 448.0


def read_frames(path):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(-1, H, W, 3)


TOPHAT = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))


def remove_sparks(frame, zone):
    """Inpaint small bright specks inside the zone, except blue stars and green fireflies.

    Wan's sparks are warm (hue <= ~30) or nearly white (low saturation); the
    painted stars are distinctly blue (hue ~100-115, saturation >= ~55) and the
    fireflies green (hue ~35-90).
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue, sat = hsv[..., 0].astype(int), hsv[..., 1].astype(int)
    th = cv2.morphologyEx(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.MORPH_TOPHAT, TOPHAT)
    keep = ((hue >= 90) & (hue <= 125) & (sat >= 50)) | ((hue > 32) & (hue < 90) & (sat >= 50))
    hot = ((th > 30) & ~keep).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(hot, 8)
    small = np.zeros(n, bool)
    small[1:] = st[1:, cv2.CC_STAT_AREA] <= 90
    # Protect the flames: anything touching a large warm body (a flame tongue) stays.
    flame = ((hue <= 32) & (sat >= 80) & (hsv[..., 2] >= 140)).astype(np.uint8)
    fn, flab, fst, _ = cv2.connectedComponentsWithStats(flame, 8)
    bigf = np.zeros(fn, bool)
    bigf[1:] = fst[1:, cv2.CC_STAT_AREA] >= 150
    flames = cv2.dilate(bigf[flab].astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    touching = np.unique(lab[flames & (lab > 0)])
    small[touching] = False
    specks = (small[lab] & (zone > 0)).astype(np.uint8)
    if not specks.any():
        return frame, 0
    specks = cv2.dilate(specks, np.ones((7, 7), np.uint8))
    x, y, w, h = cv2.boundingRect(specks)
    x0, y0, x1, y1 = max(x - 12, 0), max(y - 12, 0), min(x + w + 12, W), min(y + h + 12, H)
    out = frame.copy()
    out[y0:y1, x0:x1] = cv2.inpaint(frame[y0:y1, x0:x1], specks[y0:y1, x0:x1], 5, cv2.INPAINT_TELEA)
    return out, int(small[lab][zone > 0].any())


class Embers:
    def __init__(self, n_frames, rate, seed=3, pops=3):
        rng = np.random.default_rng(seed)
        L = n_frames / FPS
        self.L = L
        k = int(round(rate * L))
        t0 = list(rng.uniform(0, L, k))
        # a few pops: small clusters of sparks at once
        for tp in rng.uniform(0, L, pops):
            t0 += list(tp + rng.uniform(0, 0.15, 6))
        n = len(t0)
        self.t0 = np.array(t0) % L
        self.x0 = rng.normal(FIRE_X, FIRE_SPREAD, n)
        self.y0 = TIP_Y + rng.normal(0, 10, n)
        self.vy = rng.uniform(120, 210, n)                # px/s upward at the start
        self.decel = rng.uniform(0.12, 0.3, n)            # rise slows as it cools
        self.life = rng.uniform(2.2, 4.2, n)
        self.drift = rng.normal(0, 18, n)                 # steady sideways drift, px/s
        self.curl_a = rng.uniform(6, 18, n)               # curl amplitude, px
        self.curl_f = rng.uniform(0.4, 1.1, n)            # curl frequency, Hz
        self.curl_p = rng.uniform(0, 2 * np.pi, n)
        self.flick_f = rng.uniform(5, 11, n)
        self.flick_p = rng.uniform(0, 2 * np.pi, n)
        self.size = rng.uniform(0.7, 1.5, n)
        tops = self.y0 - self.vy * (self.life - 0.5 * self.decel * self.life ** 2)
        print(f"embers: {n} per {L:.2f} s loop (~{n * self.life.mean() / L:.1f} in the air at once); "
              f"highest point y {np.percentile(tops, 10):.0f}-{np.percentile(tops, 90):.0f} (sky is y<230)")

    def alive_ids(self, t):
        return np.nonzero((t - self.t0) % self.L < self.life)[0]

    def state(self, t, ids=None):
        i = self.alive_ids(t) if ids is None else ids
        a = (t - self.t0[i]) % self.L
        a = np.where(a > self.life[i], 0.0, a)            # just-born embers: no earlier position
        rise = self.vy[i] * (a - 0.5 * self.decel[i] * a * a / 1.0)
        x = self.x0[i] + self.drift[i] * a + self.curl_a[i] * np.sin(2 * np.pi * self.curl_f[i] * a + self.curl_p[i]) \
            * np.clip(a / 0.6, 0, 1)
        y = self.y0[i] - rise
        u = a / self.life[i]                              # 0 = just born, 1 = gone
        fade = np.clip(a / 0.12, 0, 1) * (1 - u) ** 0.8
        flick = 0.75 + 0.25 * np.sin(2 * np.pi * self.flick_f[i] * a + self.flick_p[i])
        return x, y, u, fade * flick, self.size[i]


def ember_color(u):
    """BGR (0..1) from yellow-white to orange to deep red as u goes 0 -> 1."""
    stops = np.array([[0.0, 0.62, 0.95, 1.00], [0.35, 0.25, 0.62, 1.00], [0.75, 0.10, 0.30, 0.90],
                      [1.0, 0.06, 0.16, 0.65]])
    return np.stack([np.interp(u, stops[:, 0], stops[:, c]) for c in (1, 2, 3)], -1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chain", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--rate", type=float, default=3.0, help="new embers per second")
    ap.add_argument("--brightness", type=float, default=1.0)
    ap.add_argument("--preview", type=Path, help="write a strip of stills and stop")
    args = ap.parse_args()
    if not args.preview and (not args.out or args.out.exists()):
        sys.exit("need -o OUT that doesn't exist yet (or --preview)")

    frames = read_frames(args.chain)
    n = len(frames)
    zone = np.zeros((H, W), np.uint8)
    cv2.fillPoly(zone, [np.array(REMOVE_ZONE, np.int32)], 1)
    occ = np.zeros((H, W), np.uint8)
    for poly in OCCLUDERS:
        cv2.fillPoly(occ, [np.array(poly, np.int32)], 1)
    vis = 1 - cv2.GaussianBlur(occ.astype(np.float32), (0, 0), 2)
    embers = Embers(n, args.rate)

    def render(i):
        f, _ = remove_sparks(frames[i], zone)
        f = f.astype(np.float32)
        t = i / FPS
        x, y, u, a, s = embers.state(t)
        # where each ember was ~1.5 frames ago -> a short motion streak
        xp, yp, *_ = embers.state(t - 1.5 / FPS, ids=embers.alive_ids(t))
        core = np.zeros((H, W, 3), np.float32)
        glow = np.zeros((H, W, 3), np.float32)
        col = ember_color(u)
        for xi, yi, x2, y2, ai, si, ci in zip(x, y, xp, yp, a, s, col):
            if not (0 <= xi < W and 0 <= yi < H):
                continue
            c = tuple(float(v) * ai for v in ci)
            p, q = (int(xi * 4), int(yi * 4)), (int(x2 * 4), int(y2 * 4))
            cv2.line(core, q, p, c, max(1, int(round(1.8 * si))), cv2.LINE_AA, shift=2)
            cv2.circle(core, p, int(4 * 1.4 * si), c, -1, cv2.LINE_AA, shift=2)
            cv2.circle(glow, p, int(4 * 3.0 * si), c, -1, cv2.LINE_AA, shift=2)
        light = (cv2.GaussianBlur(core, (0, 0), 0.6) * 340 + cv2.GaussianBlur(glow, (0, 0), 5.0) * 260)
        f += light * args.brightness * vis[..., None]
        return np.clip(f, 0, 255).astype(np.uint8)

    if args.preview:
        idx = [int(n * k / 6) for k in range(6)]
        tiles = [render(i)[0:560, 380:900] for i in idx]
        cv2.imwrite(str(args.preview), np.hstack(tiles))
        print(f"preview: {args.preview} (frames {idx})")
        return

    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "10", "-preset", "slow",
                            "-pix_fmt", "yuv420p", str(args.out)], stdin=subprocess.PIPE)
    for i in range(n + 1):
        enc.stdin.write(render(i % n).tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("ffmpeg failed")
    print(f"saved {args.out}  {n + 1} frames ({n} loop + closing frame)")


if __name__ == "__main__":
    main()
