#!/usr/bin/env python3
"""Composite a still RGBA cut-out back onto a video take.

Used when Veo refuses a keyframe because of a third-party character: generate
the takes from a keyframe with the character painted out, then put the
character back as a static layer.

  overlay_still.py take_1.mp4 keyframe_nomermaid.png mermaid_overlay.png -o take_1_comp.mp4

The plate is the exact image Veo was given, and the overlay is an RGBA image
at the same size as the plate. Veo stretches the keyframe to the video size
and can shift or squeeze it by about 1%, so the overlay is aligned to each
take's frame 0 (ECC affine fit of plate to frame 0), not placed by a fixed
scale. Output is a high-quality intermediate (x264 CRF 12, audio copied);
build_loop.py does the final encode.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("take", type=Path)
    ap.add_argument("plate", type=Path, help="the keyframe Veo was given")
    ap.add_argument("overlay", type=Path, help="RGBA cut-out, same size as the plate")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        sys.exit(f"{args.out} exists; not overwriting")

    with tempfile.TemporaryDirectory() as tmp:
        f0_path = Path(tmp) / "f0.png"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(args.take), "-frames:v", "1", str(f0_path)], check=True)
        f0 = cv2.imread(str(f0_path), cv2.IMREAD_GRAYSCALE).astype(np.float32)
        h, w = f0.shape
        plate = cv2.resize(cv2.imread(str(args.plate), cv2.IMREAD_GRAYSCALE), (w, h),
                           interpolation=cv2.INTER_AREA).astype(np.float32)
        warp = np.eye(2, 3, dtype=np.float32)
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-7)
        cc, warp = cv2.findTransformECC(cv2.GaussianBlur(plate, (0, 0), 2), cv2.GaussianBlur(f0, (0, 0), 2),
                                        warp, cv2.MOTION_AFFINE, crit, None, 5)
        print(f"alignment: ecc={cc:.4f} warp={np.round(warp, 4).tolist()}")
        if cc < 0.9:
            sys.exit("frame 0 doesn't match the plate well enough; wrong plate for this take?")

        ov = cv2.imread(str(args.overlay), cv2.IMREAD_UNCHANGED)
        if ov is None or ov.shape[2] != 4:
            sys.exit("overlay must be an RGBA image")
        ov = cv2.resize(ov, (w, h), interpolation=cv2.INTER_AREA)
        ov = cv2.warpAffine(ov, warp, (w, h), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
        ov_path = Path(tmp) / "ov.png"
        cv2.imwrite(str(ov_path), ov)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(args.take), "-i", str(ov_path),
                        "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p",
                        "-c:v", "libx264", "-crf", "12", "-preset", "slow", "-c:a", "copy",
                        str(args.out)], check=True)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
