"""One-off, run locally: bake the ASCII portrait and the spinning 3D "MZ" into JSON.

    swiftc -O scripts/segment.swift -o /tmp/segment -framework Vision -framework AppKit -framework CoreImage
    /tmp/segment assets/avatar.png assets/mask.png        # macOS person segmentation
    python3 scripts/build_assets.py                        # needs Pillow + numpy

The GitHub Action never runs this; it only reads the baked JSON.
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from face import dissolve

ROOT = os.path.join(os.path.dirname(__file__), "..")
A = lambda *p: os.path.join(ROOT, "assets", *p)

BOX = (130, 50, 420, 400)   # head + shoulders crop of the avatar (x0, y0, x1, y1)
COLS = 84

# the "first scattered" look: crumbling edges, dark areas fall to empty space
FIRST = dict(local=0.5, keep_off=0.15, edge_w=0.55, keep_pow=1.3, jit=(0.6, 0.8),
             char_g=0.9, col_g=0.7, fade_from=0.55, halo=0.05, streak=0.05)
VARIANTS = [dict(dark_cut=0.22, seed=11), dict(dark_cut=0.28, seed=23), dict(dark_cut=0.18, seed=37)]
SCATTER = dict(dark_cut=0.34, seed=5, halo=0.16, fade_from=0.3, keep_pow=2.4, streak=0.18)

def pack(cells):
    return [{"t": "".join(c for c, _ in r), "l": "".join(str(l) for _, l in r)} for r in cells]

def portrait():
    frames = [pack(dissolve(A("avatar.png"), A("mask.png"), BOX, cols=COLS, **{**FIRST, **v})) for v in VARIANTS]
    scatter = pack(dissolve(A("avatar.png"), A("mask.png"), BOX, cols=COLS, **{**FIRST, **SCATTER}))
    rows = max(len(f) for f in frames + [scatter])
    return frames, scatter, rows

def voxel_frames(text="MZ", n=36, cols=52, rows=17, depth=3.2, tilt=0.30,
                 font="/System/Library/Fonts/Supplemental/Arial Black.ttf"):
    f = ImageFont.truetype(font, 160)
    bb = f.getbbox(text)
    im = Image.new("L", (bb[2] - bb[0] + 10, bb[3] - bb[1] + 10), 0)
    ImageDraw.Draw(im).text((5 - bb[0], 5 - bb[1]), text, font=f, fill=255)
    im = im.crop(im.getbbox())
    gw = 40; gh = round(im.height / im.width * gw)
    g = np.asarray(im.resize((gw, gh), Image.LANCZOS)) > 100
    pts, sub = [], 3
    for j in range(gh):
        for i in range(gw):
            if not g[j, i]:
                continue
            for a in range(sub):
                for b in range(sub):
                    x = i + a / sub - gw / 2; y = j + b / sub - gh / 2
                    pts += [(x, y, depth, 0, 0, 1), (x, y, -depth, 0, 0, -1)]
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if 0 <= ni < gw and 0 <= nj < gh and g[nj, ni]:
                    continue
                for a in range(sub):
                    for zz in np.linspace(-depth, depth, int(depth * 2 * sub) + 1):
                        if di:
                            x = i + (1 if di > 0 else 0) - gw / 2; y = j + a / sub - gh / 2
                        else:
                            x = i + a / sub - gw / 2; y = j + (1 if dj > 0 else 0) - gh / 2
                        pts.append((x, y, zz, di, dj, 0))
    P = np.array(pts, float)
    ramp = ".,-~:;=!*#$@"
    L = np.array([-0.35, -0.5, 0.8]); L /= np.linalg.norm(L)
    frames = []
    for k in range(n):
        th = 2 * math.pi * k / n
        cy, sy, cx, sx = math.cos(th), math.sin(th), math.cos(tilt), math.sin(tilt)
        def rot(v):
            x, y, z = v[:, 0], v[:, 1], v[:, 2]
            x2 = x * cy + z * sy; z2 = -x * sy + z * cy
            return np.stack([x2, y * cx - z2 * sx, y * sx + z2 * cx], 1)
        p, nrm = rot(P[:, :3]), rot(P[:, 3:])
        ooz = 1 / (55.0 - p[:, 2])
        X = (cols / 2 + p[:, 0] * ooz * cols * 1.3).astype(int)
        Y = (rows / 2 + p[:, 1] * ooz * cols * 1.3 * 0.5).astype(int)
        lum = nrm @ L
        zb = np.full((rows, cols), -1e9); out = [[" "] * cols for _ in range(rows)]
        for xi, yi, z, l in zip(X, Y, ooz, lum):
            if 0 <= xi < cols and 0 <= yi < rows and z > zb[yi, xi]:
                zb[yi, xi] = z
                out[yi][xi] = ramp[max(0, min(11, int((l + 0.2) / 1.2 * 11)))]
        frames.append(["".join(r).rstrip() for r in out])
    return frames

if __name__ == "__main__":
    frames, scatter, rows = portrait()
    json.dump({"box": BOX, "cols": COLS, "rows": frames[0], "frames": frames, "scatter": scatter},
              open(A("portrait.json"), "w"), ensure_ascii=False)
    if "--mz" in sys.argv:
        json.dump(voxel_frames(), open(A("mz.json"), "w"), ensure_ascii=False)
    print("baked", A("portrait.json"), A("mz.json"))
