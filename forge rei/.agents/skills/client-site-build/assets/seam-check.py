#!/usr/bin/env python3
"""Measure scroll-world seam continuity.

Every chained clip's last frame must match the next clip's first frame, or the
seam pops. Usage:

    python3 seam-check.py leg1.mp4 leg2.mp4 leg3.mp4 ...

Reads as: under ~12 continuous, ~25 borderline, 50+ a visible pop.
Also checks each clip's first frame against a poster of the same basename in
--posters, because a poster must be the clip's FIRST frame, not its destination.
"""
import subprocess, sys, tempfile, os, argparse
from PIL import Image, ImageChops


def frame(path, where, out):
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if where == "last":
        cmd += ["-sseof", "-0.05", "-i", path, "-vframes", "1", out]
    else:
        cmd += ["-i", path, "-vf", "select=eq(n\\,0)", "-vframes", "1", out]
    subprocess.run(cmd, check=True)
    return out


def diff(a, b):
    ia = Image.open(a).convert("RGB")
    ib = Image.open(b).convert("RGB").resize(ia.size)
    d = ImageChops.difference(ia, ib).convert("L")
    return sum(i * c for i, c in enumerate(d.histogram())) / (ia.size[0] * ia.size[1])


def verdict(v):
    return "OK" if v < 12 else ("BORDERLINE" if v < 30 else "POP — re-render from the actual frame")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("clips", nargs="+")
    p.add_argument("--posters", help="directory of posters named <clip-basename>.png")
    a = p.parse_args()
    tmp = tempfile.mkdtemp()
    worst = 0.0

    print("SEAMS (last frame of N vs first frame of N+1)")
    for i in range(len(a.clips) - 1):
        x = frame(a.clips[i], "last", f"{tmp}/a{i}.png")
        y = frame(a.clips[i + 1], "first", f"{tmp}/b{i}.png")
        v = diff(x, y)
        worst = max(worst, v)
        print(f"  {os.path.basename(a.clips[i]):18s} -> {os.path.basename(a.clips[i+1]):18s} {v:6.1f}  {verdict(v)}")

    if a.posters:
        print("\nPOSTERS (must be the clip's FIRST frame, not its destination)")
        for c in a.clips:
            base = os.path.splitext(os.path.basename(c))[0]
            for ext in (".png", ".jpg", ".jpeg"):
                pth = os.path.join(a.posters, base + ext)
                if os.path.exists(pth):
                    v = diff(pth, frame(c, "first", f"{tmp}/p_{base}.png"))
                    print(f"  {base:18s} {v:6.1f}  {'OK' if v < 12 else 'WRONG FRAME — poster is not this clip start'}")
                    break

    sys.exit(1 if worst >= 30 else 0)


if __name__ == "__main__":
    main()
