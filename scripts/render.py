"""Render the animated terminal card (dist/terminal.svg) from live GitHub data.

Standard library only, so the GitHub Action needs no pip install.
GitHub strips <script> from READMEs but plays CSS + SMIL inside an <img> SVG,
so every bit of motion here is CSS keyframes or <animate>.

    GITHUB_TOKEN=... python3 scripts/render.py            # writes dist/terminal.svg
"""
import json, os, random, subprocess, sys, urllib.request
from datetime import datetime, timezone
from html import escape

USER = os.environ.get("PROFILE_USER", "mustafazahter")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "dist", "terminal.svg")
CACHE = os.path.join(ROOT, "assets", "stats.json")

# ── who I am (edit freely) ───────────────────────────────────────────
HANDLE = ("mustafa", "zahter")
INFO = [
    ("OS", "Computer Engineering · Year 3"),
    ("Host", "Sage Teknoloji A.Ş. · Content Developer"),
    ("Build", "komuta.io · PaaS platform, code → production"),
    ("Kernel", "Deep Learning · Generative AI · Robotics"),
    ("Shell", "zsh · Docker · Linux · AI agents"),
    ("Langs", "Python · TypeScript · C/C++ · C# · Dart"),
    ("Uptime", "{uptime}"),
    ("Stats", "{repos} public repos · {followers} followers{stars}"),
]

# ── palette ──────────────────────────────────────────────────────────
SHADES = ["#000", "#0f3d20", "#17652f", "#21903f", "#33c45c", "#62f08c", "#aaffc8", "#efffF4"]
HEAT = ["#10301c", "#1d6b3a", "#28a352", "#39d96c", "#b4ffd2"]

FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
CW = 0.602  # monospace advance / font-size


# ── data ─────────────────────────────────────────────────────────────
def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None

QUERY = """query($u:String!){user(login:$u){createdAt followers{totalCount}
 repositories(ownerAffiliations:OWNER,isFork:false,first:100,privacy:PUBLIC){totalCount nodes{stargazerCount}}
 contributionsCollection{contributionCalendar{totalContributions weeks{contributionDays{contributionCount contributionLevel}}}}}}"""

def fetch():
    tok = token()
    if not tok:
        raise RuntimeError("no token")
    req = urllib.request.Request("https://api.github.com/graphql",
                                 data=json.dumps({"query": QUERY, "variables": {"u": USER}}).encode(),
                                 headers={"Authorization": f"bearer {tok}", "Content-Type": "application/json",
                                          "User-Agent": "profile-terminal-card"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    if "errors" in d:
        raise RuntimeError(d["errors"])
    u = d["data"]["user"]
    lv = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
    cal = u["contributionsCollection"]["contributionCalendar"]
    weeks = [[lv[x["contributionLevel"]] for x in w["contributionDays"]] for w in cal["weeks"]]
    weekly = [sum(x["contributionCount"] for x in w["contributionDays"]) for w in cal["weeks"]]
    return {
        "created": u["createdAt"], "followers": u["followers"]["totalCount"],
        "repos": u["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in u["repositories"]["nodes"]),
        "contrib": cal["totalContributions"], "weeks": weeks, "weekly": weekly,
    }

def stats():
    try:
        s = fetch()
        json.dump(s, open(CACHE, "w"))
        return s
    except Exception as e:  # keep the card alive on API hiccups
        print("fetch failed, using cache:", e, file=sys.stderr)
        return json.load(open(CACHE))

def uptime(created):
    c = datetime.fromisoformat(created.replace("Z", "+00:00"))
    n = datetime.now(timezone.utc)
    months = (n.year - c.year) * 12 + n.month - c.month - (n.day < c.day)
    y, m = divmod(months, 12)
    return f"{y} years, {m} month{'s' if m != 1 else ''} on GitHub"


# ── svg helpers ──────────────────────────────────────────────────────
_n = [0]
def uid():
    _n[0] += 1
    return f"c{_n[0]}"

def markup(text):
    """{{cls|text}} → coloured tspan."""
    out, i = "", 0
    while (j := text.find("{{", i)) >= 0:
        k = text.find("}}", j)
        cls, s = text[j + 2:k].split("|", 1)
        out += escape(text[i:j], False) + f'<tspan class="{cls}">{escape(s, False)}</tspan>'
        i = k + 2
    return out + escape(text[i:], False)

def plain(text):
    out, i = "", 0
    while (j := text.find("{{", i)) >= 0:
        k = text.find("}}", j)
        out += text[i:j] + text[j + 2:k].split("|", 1)[1]
        i = k + 2
    return out + text[i:]

def typed(x, y, text, t, fs, cls="", cps=70):
    """Text that types itself: a clip rect grows one glyph at a time."""
    n = len(plain(text))
    cid, dur = uid(), max(n / cps, 0.05)
    steps = ";".join(f"{k * fs * CW:.1f}" for k in range(n + 1))
    d = (f'<clipPath id="{cid}"><rect x="{x - 1}" y="{y - fs}" width="0" height="{fs * 1.5:.1f}">'
         f'<animate attributeName="width" values="{steps}" begin="{t:.2f}s" dur="{dur:.2f}s" fill="freeze" calcMode="discrete"/>'
         f'</rect></clipPath>')
    b = f'<text x="{x}" y="{y}" font-size="{fs}" class="{cls}" clip-path="url(#{cid})" xml:space="preserve">{markup(text)}</text>'
    return d, b, t + dur

def shade_spans(text, levels):
    out, cur, buf = [], None, ""
    def flush():
        if buf:
            out.append(f'<tspan class="t{cur}">{escape(buf, False)}</tspan>' if cur else escape(buf, False))
    for ch, lv in zip(text, levels):
        lv = cur if ch == " " else int(lv)
        if lv != cur and buf:
            flush(); buf = ""
        cur = lv; buf += ch
    flush()
    return "".join(out)



def morph_tracks(frames, yscale, radius=6.0):
    """Match glyphs between consecutive portrait variants (greedy nearest pairs)
    so each one can slide to a neighbouring spot instead of cross-fading."""
    def pts(rows):
        return [(i, j, ch, int(lv)) for i, r in enumerate(rows) for j, (ch, lv) in enumerate(zip(r["t"], r["l"])) if ch != " "]
    def match(src, dst):
        grid = {}
        for k, (i, j, *_) in enumerate(dst):
            grid.setdefault((i // 4, j // 4), []).append(k)
        pairs = []
        for a, (i, j) in enumerate(src):
            for gi in range(i // 4 - 2, i // 4 + 3):
                for gj in range(j // 4 - 2, j // 4 + 3):
                    for k in grid.get((gi, gj), ()):
                        d = ((dst[k][0] - i) * yscale) ** 2 + (dst[k][1] - j) ** 2
                        if d <= (radius * yscale) ** 2:
                            pairs.append((d, a, k))
        pairs.sort()
        used_a, used_k, m = set(), set(), {}
        for d, a, k in pairs:
            if a not in used_a and k not in used_k:
                used_a.add(a); used_k.add(k); m[a] = k
        return m
    def nearest(p, cands):
        return min(cands, key=lambda c: ((c[0] - p[0]) * yscale) ** 2 + (c[1] - p[1]) ** 2)
    F = [pts(f) for f in frames]
    tracks = [{"ch": c, "lv": l, "pos": [(i, j), None, None], "op": [1, 0, 0]} for i, j, c, l in F[0]]
    for f in (1, 2):
        live = [t for t in tracks if t["pos"][f - 1] is not None and t["op"][f - 1]]
        m = match([t["pos"][f - 1] for t in live], F[f])
        hit = set()
        for a, t in enumerate(live):
            if a in m:
                i, j, *_ = F[f][m[a]]; t["pos"][f] = (i, j); t["op"][f] = 1; hit.add(m[a])
        for k, (i, j, c, l) in enumerate(F[f]):   # newcomers fade in at their spot
            if k not in hit:
                pos = [None, None, None]; pos[f] = (i, j)
                op = [0, 0, 0]; op[f] = 1
                tracks.append({"ch": c, "lv": l, "pos": pos, "op": op})
    # fill gaps: an absent glyph waits (invisible) at the nearest visible spot of that frame
    for f in range(3):
        vis = [t["pos"][f] for t in tracks if t["op"][f]]
        for t in tracks:
            if t["pos"][f] is None:
                ref = next(p for p in (t["pos"][(f - 1) % 3], t["pos"][(f + 1) % 3], t["pos"][(f + 2) % 3]) if p)
                t["pos"][f] = nearest(ref, vis)
    return tracks

MOTION_GROUPS = 48
# Per-glyph drift looks great but makes browsers repaint the dense portrait every
# frame (profile page drops to ~20 fps). Off by default: the portrait stays still
# and the life comes from particles peeling off its edges (cheap).
GLYPH_DRIFT = os.environ.get("GLYPH_DRIFT") == "1"
PARTICLES = 34

def kmeans(vecs, items, k, rnd, iters=18):
    """Tiny k-means: returns [(centroid, [items])]."""
    k = min(k, len(vecs))
    cents = [list(v) for v in rnd.sample(vecs, k)]
    for _ in range(iters):
        buckets = [[] for _ in range(k)]
        for v, it in zip(vecs, items):
            c = min(range(k), key=lambda q: sum((a - b) ** 2 for a, b in zip(v, cents[q])))
            buckets[c].append((v, it))
        for q, bk in enumerate(buckets):
            if bk:
                cents[q] = [sum(v[d] for v, _ in bk) / len(bk) for d in range(len(vecs[0]))]
    return [(cents[q], [it for _, it in bk]) for q, bk in enumerate(buckets) if bk]

# ── card ─────────────────────────────────────────────────────────────
def render(s):
    pj = json.load(open(os.path.join(ROOT, "assets", "portrait.json")))
    portrait, variants, pcols = pj["frames"][0], pj["frames"], pj["cols"]
    mz = json.load(open(os.path.join(ROOT, "assets", "mz.json")))
    rnd = random.Random(42)
    W, H = 940, 640
    defs, body, anim = [], [], []

    css = [
        ".o{opacity:0;animation:on .01s forwards}@keyframes on{to{opacity:1}}",
        ".s{opacity:0;animation:blip .06s forwards}@keyframes blip{0%,99%{opacity:1}100%{opacity:0}}",
        ".fade{opacity:0;animation:fd .6s forwards}@keyframes fd{to{opacity:1}}",
        ".cur{animation:bl 1.05s steps(1) infinite}@keyframes bl{50%{opacity:0}}",
        ".roll{animation:roll 7s linear infinite}@keyframes roll{from{transform:translateY(-90px)}to{transform:translateY(700px)}}",
        ".g{fill:#39ff7a}.d{fill:#1f9e4a}.k{fill:#7dffb0;font-weight:700}.m{fill:#155c2e}.w{fill:#e6fff0}.big{fill:#c8ffe0;font-weight:700}",
        "".join(f".t{i}{{fill:{c}}}" for i, c in enumerate(SHADES)),
        "".join(f".h{i}{{fill:{c}}}" for i, c in enumerate(HEAT)),
        "@media (prefers-reduced-motion:reduce){*{animation-duration:0s!important;animation-delay:0s!important}}",
    ]
    defs += [
        '<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="#000" opacity=".28"/></pattern>',
        '<filter id="glow" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="1.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '<radialGradient id="vig" cx="50%" cy="50%" r="75%"><stop offset="62%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".72"/></radialGradient>',
        f'<clipPath id="card"><rect width="{W}" height="{H}" rx="14"/></clipPath>',
    ]

    body += [
        f'<rect width="{W}" height="{H}" rx="14" fill="#050a06"/>',
        f'<rect width="{W}" height="36" fill="#0c140e" clip-path="url(#card)"/>',
        '<circle cx="22" cy="18" r="6" fill="#ff5f57"/><circle cx="42" cy="18" r="6" fill="#febc2e"/><circle cx="62" cy="18" r="6" fill="#28c840"/>',
        f'<text x="{W / 2}" y="23" font-size="12" text-anchor="middle" class="d">{HANDLE[0]}@{HANDLE[1]}: ~/self</text>',
        '<g filter="url(#glow)">',
    ]

    # 1 · prompt
    d, b, t = typed(24, 66, "{{d|➜}} {{k|~}} neofetch --self --render=ascii --3d", 0.3, 13, "g")
    defs.append(d); body.append(b)
    t0 = t + 0.15

    # 2 · portrait on the right: every row scrambles, then locks into shaded glyphs
    pfs = 6.6; plh = pfs * 1.13
    pw = pcols * pfs * CW
    px, py = W - 24 - (pcols + 8) * pfs * CW, 62
    glyphs = "01<>/\\|#$%&*+=?"
    rows_svg = []
    S0 = t0 + len(portrait) * 0.028 + 2.5
    for i, r in enumerate(portrait):
        if not r["t"].strip():
            continue
        y = py + i * plh
        ti = t0 + i * 0.028
        for f in range(3):
            scr = "".join(" " if c == " " else rnd.choice(glyphs) for c in r["t"])
            body.append(f'<text x="{px:.1f}" y="{y:.1f}" font-size="{pfs}" class="s d" style="animation-delay:{ti + f * 0.06:.2f}s" xml:space="preserve">{escape(scr, False)}</text>')
        rows_svg.append((i, y, ti + 0.18, r))
    t_face = t0 + len(portrait) * 0.028 + 0.2

    # every glyph is its own element and slides, point to point, into its matched
    # spot in the next scattered variant (3 variants, 30 s loop, random phase per glyph). Glyphs with no
    # partner fade out where the next variant has nothing, or fade in where it gains one.
    cw_, lh_ = pfs * CW, plh
    tracks = morph_tracks(variants, lh_ / cw_)
    css.append(
        ".mv{animation:mv 30s linear infinite}"
        "@keyframes mv{"
        "0%{transform:translate(0,0);opacity:var(--o0)}"
        "16.67%{transform:translate(var(--ax),var(--ay));opacity:calc(.5*var(--o0) + .5*var(--o1))}"
        "33.33%{transform:translate(var(--x1),var(--y1));opacity:var(--o1)}"
        "50%{transform:translate(var(--bx),var(--by));opacity:calc(.5*var(--o1) + .5*var(--o2))}"
        "66.67%{transform:translate(var(--x2),var(--y2));opacity:var(--o2)}"
        "83.33%{transform:translate(var(--cx),var(--cy));opacity:calc(.5*var(--o2) + .5*var(--o0))}"
        "100%{transform:translate(0,0);opacity:var(--o0)}}")
    cx_mid = pcols * 0.5
    cy_mid = len(portrait) * 0.45

    def detour(a, b):
        """Midway point between two spots, blown outwards + random, so glyphs drift apart before settling."""
        (ia, ja), (ib, jb) = a, b
        mi, mj = (ia + ib) / 2, (ja + jb) / 2
        vj, vi = mj - cx_mid, (mi - cy_mid) * 1.8
        n = (vj * vj + vi * vi) ** 0.5 or 1
        push = rnd.uniform(1, 5)
        x = (mj - ja0) * cw_ + vj / n * push + rnd.uniform(-3, 3)
        y = (mi - ia0) * lh_ + vi / n * push * 0.6 + rnd.uniform(-2.5, 2.5)
        return x, y
    by_row, extra, still, moving = {}, [], {}, []
    for tr in tracks:
        (i0, j0), (i1, j1), (i2, j2) = tr["pos"]
        if not GLYPH_DRIFT:
            if tr["op"][0]:
                still.setdefault(i0, {})[j0] = (tr["ch"], tr["lv"])
            continue
        if tr["op"] == [1, 1, 1] and (i0, j0) == (i1, j1) == (i2, j2):
            still.setdefault(i0, {})[j0] = (tr["ch"], tr["lv"])
            continue
        ia0, ja0 = i0, j0
        ax, ay = detour((i0, j0), (i1, j1))
        bx, by = detour((i1, j1), (i2, j2))
        cx, cy = detour((i2, j2), (i0, j0))
        vec = (ax, ay, (j1 - j0) * cw_, (i1 - i0) * lh_, bx, by, (j2 - j0) * cw_, (i2 - i0) * lh_, cx, cy)
        moving.append({"i": i0, "j": j0, "ch": tr["ch"], "lv": tr["lv"], "op": tuple(tr["op"]), "v": vec})

    # Browsers pay per running animation, not per pixel moved, so glyphs whose paths
    # look alike share one animated group (k-means on the 10-D path). Neighbours land
    # in different groups, so the drift still reads as individual and organic.
    row_delay = {i: tshow for i, y, tshow, r in rows_svg}
    groups = []
    by_op = {}
    for g_ in moving:
        by_op.setdefault(g_["op"], []).append(g_)
    for op, items in by_op.items():
        k = max(1, round(MOTION_GROUPS * len(items) / max(1, len(moving))))
        for cent, members in kmeans([m["v"] for m in items], items, k, rnd):
            groups.append((op, cent, members))
    for op, c, members in groups:
        style = (f'--ax:{c[0]:.0f}px;--ay:{c[1]:.0f}px;--x1:{c[2]:.0f}px;--y1:{c[3]:.0f}px;--bx:{c[4]:.0f}px;--by:{c[5]:.0f}px;'
                 f'--x2:{c[6]:.0f}px;--y2:{c[7]:.0f}px;--cx:{c[8]:.0f}px;--cy:{c[9]:.0f}px;'
                 f'--o0:{op[0]};--o1:{op[1]};--o2:{op[2]};animation-delay:{-rnd.uniform(0, 30):.2f}s')
        els = "".join(f'<text x="{px + m["j"] * cw_:.1f}" y="{py + m["i"] * lh_:.1f}" class="o t{m["lv"]}" '
                      f'style="animation-delay:{(row_delay.get(m["i"], S0) if op[0] else S0):.2f}s">{escape(m["ch"], False)}</text>'
                      for m in members)
        extra.append(f'<g class="mv" style="{style}">{els}</g>')
    def still_row(i, y):
        cells = still.get(i)
        if not cells:
            return ""
        n = max(cells) + 1
        t_ = "".join(cells[j][0] if j in cells else " " for j in range(n))
        l_ = "".join(str(cells[j][1]) if j in cells else "0" for j in range(n))
        return f'<text x="{px:.1f}" y="{y:.1f}" xml:space="preserve">{shade_spans(t_, l_)}</text>'
    face = [f'<g class="o" style="animation-delay:{tshow:.2f}s">{still_row(i, y)}{"".join(by_row.get(i, []))}</g>' for i, y, tshow, r in rows_svg]
    face.append("".join(extra))
    # outside the glow filter: re-filtering 1.5k moving glyphs every frame makes browsers stutter/blur
    anim.append(f'<g id="face" font-size="{pfs}">{"".join(face)}</g>')
    # particles that peel off the figure and drift up/out forever
    css.append(".pt{opacity:0;animation:pt linear infinite}@keyframes pt{0%{opacity:0;transform:translate(0,0)}15%{opacity:.9}100%{opacity:0;transform:translate(var(--dx),-46px)}}")
    edges = []
    for i, r in enumerate(portrait):
        t_ = r["t"]
        if t_.strip():
            a, b_ = len(t_) - len(t_.lstrip()), len(t_.rstrip())
            edges += [(a, i, -1), (b_, i, 1)]
    for k in range(PARTICLES):
        c, i, side = rnd.choice(edges)
        dx = side * rnd.randint(8, 40)
        anim.append(f'<text x="{px + c * pfs * CW:.1f}" y="{py + i * plh:.1f}" font-size="{pfs + 1}" class="pt t{rnd.choice((3, 4, 5))}" '
                    f'style="--dx:{dx}px;animation-duration:{rnd.uniform(3, 7):.1f}s;animation-delay:{t_face + rnd.uniform(0, 6):.1f}s">{rnd.choice(".:·*+`")}</text>')
    cap_y = py + len(portrait) * plh + 14
    body.append(f'<text x="{px + pw:.1f}" y="{cap_y:.1f}" font-size="10" text-anchor="end" class="o m" style="animation-delay:{t_face:.2f}s">fig.1 — operator.ascii ({pcols}×{len(portrait)})</text>')

    # 3 · spinning 3D "MZ": all frames stacked in one strip that slides behind a
    # clip window with steps() — a single animation, so there is never a gap frame
    n, period = len(mz), 4.8
    mfs, mlh, mx, my = 9.0, 10.2, 24, 96
    rows_mz = max(len(fr) for fr in mz)
    FH = rows_mz * mlh + 8
    css.append(f".strip{{animation:strip {period}s steps({n}) infinite}}"
               f"@keyframes strip{{from{{transform:translateY(0)}}to{{transform:translateY(-{n * FH:.1f}px)}}}}")
    cid = uid()
    defs.append(f'<clipPath id="{cid}"><rect x="{mx - 4}" y="{my - mfs - 2:.1f}" width="{52 * mfs * CW + 8:.0f}" height="{FH:.1f}"/></clipPath>')
    lines = []
    for k, fr in enumerate(mz):
        lines += [f'<tspan x="{mx}" y="{my + k * FH + r * mlh:.1f}">{escape(l, False)}</tspan>' for r, l in enumerate(fr) if l]
    anim.append(f'<g class="fade" style="animation-delay:{t0:.2f}s" clip-path="url(#{cid})"><g class="strip">'
                f'<text font-size="{mfs}" class="g" xml:space="preserve">{"".join(lines)}</text></g></g>')

    # 4 · live numbers beside the logo
    sx = 24 + 52 * mfs * CW + 18
    body.append(f'<g class="fade" style="animation-delay:{t0 + 0.3:.2f}s">'
                f'<text x="{sx:.0f}" y="128" font-size="40" class="big">{s["contrib"]}</text>'
                f'<text x="{sx:.0f}" y="146" font-size="11" class="d">contributions · last 12 months</text>'
                f'<text x="{sx:.0f}" y="182" font-size="22" class="w">{s["repos"]}<tspan font-size="11" class="d"> repos   </tspan>{s["followers"]}<tspan font-size="11" class="d"> followers</tspan></text>'
                f'<text x="{sx:.0f}" y="212" font-size="11" class="g">● <tspan class="d">status:</tspan> shipping</text></g>')

    # 5 · neofetch block
    x0, y0 = 24, 288
    d, b, t = typed(x0, y0, f"{{{{k|{HANDLE[0]}}}}}{{{{d|@}}}}{{{{k|{HANDLE[1]}}}}}", t_face - 1.2, 15, "g", cps=30)
    defs.append(d); body.append(b)
    body.append(f'<text x="{x0}" y="{y0 + 16}" font-size="13" class="o m" style="animation-delay:{t:.2f}s">{"─" * 30}</text>')
    vals = {"uptime": uptime(s["created"]), "repos": s["repos"], "followers": s["followers"], "stars": f" · ★ {s['stars']}" if s["stars"] else ""}
    for i, (k, v) in enumerate(INFO):
        d, b, t = typed(x0, y0 + 40 + i * 22, f"{{{{k|{k:<7}}}}} {v.format(**vals)}", t + 0.04, 12.5, "g", cps=110)
        defs.append(d); body.append(b)
    sw_y = y0 + 40 + len(INFO) * 22 - 6
    body.append("".join(f'<rect x="{x0 + i * 30}" y="{sw_y}" width="26" height="12" fill="{c}" class="o" style="animation-delay:{t + 0.08 + i * 0.06:.2f}s"/>'
                        for i, c in enumerate(SHADES[1:])))

    # 6 · contribution heatmap in block glyphs
    hy = 548
    d, b, t = typed(24, hy, "{{d|➜}} {{k|~}} git log --since=1.year | heatmap", t + 0.4, 12, "g")
    defs.append(d); body.append(b)
    hfs = 9.0; hcw = hfs * CW; gy = hy + 18
    chars = ["·", "░", "▒", "▓", "█"]
    weeks = s["weeks"]
    rows = []
    for dday in range(7):
        line = ""
        for w, wk in enumerate(weeks):
            off = 7 - len(wk) if w == 0 else 0
            idx = dday - off
            line += (f'<tspan class="h{wk[idx]}">{chars[wk[idx]]}</tspan>' if 0 <= idx < len(wk) else " ") + " "
        rows.append(f'<text x="24" y="{gy + dday * 9.6:.1f}" font-size="{hfs}" xml:space="preserve">{line}</text>')
    hw = len(weeks) * 2 * hcw + 8
    cid = uid()
    defs.append(f'<clipPath id="{cid}"><rect x="20" y="{gy - 12}" width="0" height="80">'
                f'<animate attributeName="width" values="0;{hw:.0f}" begin="{t + 0.1:.2f}s" dur="1.6s" fill="freeze"/></rect></clipPath>')
    body.append(f'<g clip-path="url(#{cid})">{"".join(rows)}</g>')
    lx = 24 + hw + 16
    leg = "".join(f'<tspan class="h{i}">{c}</tspan> ' for i, c in enumerate(chars))
    body.append(f'<text x="{lx:.0f}" y="{gy + 20}" font-size="10" class="fade d" style="animation-delay:{t + 1.7:.2f}s" xml:space="preserve">less {leg}more</text>')
    body.append(f'<text x="{lx:.0f}" y="{gy + 40}" font-size="10" class="fade d" style="animation-delay:{t + 1.9:.2f}s">updated {datetime.now(timezone.utc):%Y-%m-%d} · auto</text>')
    anim.append(f'<rect x="{lx:.0f}" y="{gy + 50}" width="8" height="2" class="g cur"/>')
    body.append("</g>")
    body += anim

    # CRT overlay
    body += [f'<rect width="{W}" height="{H}" rx="14" fill="url(#scan)"/>',
             f'<rect width="{W}" height="{H}" rx="14" fill="url(#vig)"/>']

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="{FONT}" role="img" aria-label="{HANDLE[0]}@{HANDLE[1]} terminal profile card">'
            f'<style>{"".join(css)}</style><defs>{"".join(defs)}</defs>{"".join(body)}</svg>')


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    svg = render(stats())
    open(OUT, "w").write(svg)
    print(f"wrote {OUT} ({len(svg) // 1024} KB)")
