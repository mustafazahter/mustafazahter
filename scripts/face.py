"""Tonal ASCII portrait: every cell gets a glyph (density) AND a shade level (colour)."""
from html import escape
import numpy as np
from PIL import Image, ImageFilter, ImageOps

RAMP = " ._:~;/<lj{y2ZPq&gQBM@N"

def _box(a, r, axis):
    c = np.cumsum(np.pad(a, [(r + 1, r) if k == axis else (0, 0) for k in range(2)], mode="edge"), axis=axis)
    hi = np.take(c, range(2 * r + 1, c.shape[axis]), axis=axis)
    lo = np.take(c, range(0, c.shape[axis] - 2 * r - 1), axis=axis)
    return (hi - lo) / (2 * r + 1)

def _blur(a, r):
    """~Gaussian blur: three separable box passes."""
    r = max(1, int(r / 1.7))
    for _ in range(3):
        a = _box(_box(a, r, 0), r, 1)
    return a

def tone_map(photo, mask, box, local=0.7, radius=22, gamma=0.9):
    """Local-contrast normalised luminance in 0..1 (CLAHE-like) + mask, at photo resolution."""
    img = ImageOps.autocontrast(Image.open(photo).convert("L").crop(box), cutoff=0.5)
    m = np.asarray(Image.open(mask).convert("L").crop(box), float) / 255
    g = np.asarray(img, float) / 255
    mean = _blur(g, radius)
    std = np.sqrt(np.maximum(_blur((g - mean) ** 2, radius), 1e-6))
    ln = np.clip(0.5 + 0.28 * (g - mean) / (std + 0.04), 0, 1)
    ins = m > 0.5
    eq = g.copy(); eq[ins] = np.argsort(np.argsort(g[ins])) / max(ins.sum() - 1, 1)
    v = np.clip(local * ln + (1 - local) * eq, 0, 1) ** gamma
    return v, m

def tonal(photo, mask, box, cols=72, aspect=0.55, levels=8, bg_cut=0.4, char_g=0.75, col_g=0.45, **kw):
    v, m = tone_map(photo, mask, box, **kw)
    h, w = v.shape
    rows = round(h / (w / cols) * aspect)
    vs = np.asarray(Image.fromarray(v.astype("float32"), "F").resize((cols, rows), Image.LANCZOS), float)
    vs = vs + 0.6 * (vs - _blur(vs, 2))
    mm = np.asarray(Image.fromarray((m * 255).astype("uint8")).resize((cols, rows), Image.LANCZOS), float) / 255
    vs = np.clip(vs, 0, 1) * np.clip((mm - bg_cut) / (1 - bg_cut), 0, 1) ** 0.35
    n = len(RAMP) - 1
    cells = []
    for i in range(rows):
        row = []
        for j in range(cols):
            if mm[i, j] < bg_cut:
                row.append((" ", 0)); continue
            x = vs[i, j]
            gch, gcol = x ** char_g, x ** col_g  # split brightness between glyph density and colour
            row.append((RAMP[max(1, min(n, int(gch * n + 0.5)))], max(1, min(levels - 1, int(gcol * (levels - 1) + 0.5)))))
        while row and row[-1][0] == " ": row.pop()
        cells.append(row)
    return cells

def text_rows(cells):
    return ["".join(c for c, _ in r) for r in cells]

def tspans(row, cls="t"):
    """Merge runs of equal shade into tspans (spaces join the current run)."""
    out, cur, buf = [], None, ""
    def flush():
        if buf: out.append(f'<tspan class="{cls}{cur}">{escape(buf, False)}</tspan>' if cur else escape(buf, False))
    for ch, lv in row:
        lv_ = cur if ch == " " else lv
        if lv_ != cur and buf:
            flush(); buf = ""
        cur = lv_; buf += ch
    flush()
    return "".join(out)


def dissolve(photo, mask, box, cols=84, aspect=0.55, levels=8, seed=11,
             dark_cut=0.14, char_g=0.85, col_g=0.6, fade_from=0.62, halo=0.05, edge_r=1.2, edge_w=0.45, streak=0.07,
             keep_off=0.08, keep_pow=1.2, jit=(0.7, 0.6), **kw):
    """Moodier portrait: shadows fall to empty space, edges + lower body
    break into scattered particles, a few stray glyphs drift outside the figure."""
    import random
    rnd = random.Random(seed)
    v, m = tone_map(photo, mask, box, **kw)
    h, w = v.shape
    rows = round(h / (w / cols) * aspect)
    vs = np.asarray(Image.fromarray(v.astype("float32"), "F").resize((cols, rows), Image.LANCZOS), float)
    mm = np.asarray(Image.fromarray((m * 255).astype("uint8")).resize((cols, rows), Image.LANCZOS), float) / 255
    soft = _blur(mm, 3)            # wide, soft version of the mask
    core = _blur(mm, edge_r)
    n = len(RAMP) - 1
    cells = []
    for i in range(rows):
        yf = i / (rows - 1)
        fade = 1.0 if yf < fade_from else max(0.0, 1 - (yf - fade_from) / (1 - fade_from)) ** 1.4
        row = []
        for j in range(cols):
            x = float(np.clip(vs[i, j], 0, 1))
            inside = core[i, j]
            keep = min(1.0, max(0.0, (inside - keep_off) / edge_w)) ** keep_pow * fade
            # jitter: a wobbly threshold so edges and the bottom crumble instead of ending on a line
            if inside > 0.12 and rnd.random() < keep and x > dark_cut * (jit[0] + jit[1] * rnd.random()):
                x = x * (0.55 + 0.45 * keep)          # dim towards the edges
                x = min(x, 0.88)                       # no pure white blocks
                row.append((RAMP[max(1, min(n, int((x ** char_g) * n + 0.5)))],
                            max(1, min(levels - 2, int((x ** col_g) * (levels - 1) + 0.5)))))
            elif soft[i, j] > 0.02 and rnd.random() < halo * soft[i, j] * 6 * (0.4 + fade):
                row.append((rnd.choice(".:'`,;~"), rnd.choice((1, 1, 2, 2, 3))))   # stray particles
            else:
                row.append((" ", 0))
        while row and row[-1][0] == " ":
            row.pop()
        # data smear: a few rows bleed sideways out of the silhouette
        if row and rnd.random() < streak and yf < fade_from + 0.15:
            ln = rnd.randint(4, 16)
            tail = "=-~-~..  .   ."
            for k in range(ln):
                ch = tail[min(len(tail) - 1, int(k / ln * len(tail)))]
                row.append((ch, max(1, 4 - k * 4 // ln)) if ch != " " else (" ", 0))
        cells.append(row)
    return cells
