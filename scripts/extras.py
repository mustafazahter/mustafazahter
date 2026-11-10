"""More CRT panels for the profile, same look as render.py.

    dist/htop.svg   live: GitHub activity as an htop screen (languages = CPU cores,
                    public repos = processes, contributions = load average)
    dist/stack.svg  static: `tree ~/stack` typed out

Standard library only. Private repositories are always filtered out.
"""
import json, os, random, sys, urllib.request
from datetime import datetime, timezone
from html import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import FONT, CW, ROOT, USER, typed, token  # noqa: E402

CACHE = os.path.join(ROOT, "assets", "extras.json")
SKIP_LANGS = {"HTML", "CSS", "SCSS", "Jupyter Notebook", "Makefile", "Dockerfile"}  # markup / notebooks skew the bars

LINKS = {
    "PyTorch": ("pytorch", "https://pytorch.org"), "TensorFlow": ("tensorflow", "https://www.tensorflow.org"),
    "OpenCV": ("opencv", "https://opencv.org"), "pandas": ("pandas", "https://pandas.pydata.org"),
    "MATLAB": ("mathworks", "https://www.mathworks.com"), "Python": ("python", "https://www.python.org"),
    "TypeScript": ("typescript", "https://www.typescriptlang.org"), "JavaScript": ("javascript", "https://developer.mozilla.org/docs/Web/JavaScript"),
    "C": ("c", "https://en.wikipedia.org/wiki/C_(programming_language)"), "C++": ("cplusplus", "https://isocpp.org"),
    "C#": ("dotnet", "https://learn.microsoft.com/dotnet/csharp"), "Java": ("openjdk", "https://www.java.com"),
    "Dart": ("dart", "https://dart.dev"), "Bash": ("gnubash", "https://www.gnu.org/software/bash"),
    "React": ("react", "https://react.dev"), "Next.js": ("nextdotjs", "https://nextjs.org"),
    "Node.js": ("nodedotjs", "https://nodejs.org"), "Django": ("django", "https://www.djangoproject.com"),
    "Flutter": ("flutter", "https://flutter.dev"), "Tailwind": ("tailwindcss", "https://tailwindcss.com"),
    "Komuta": ("rocket", "https://komuta.io"), "Docker": ("docker", "https://www.docker.com"),
    "Linux": ("linux", "https://www.linux.org"), "Git": ("git", "https://git-scm.com"),
    "Google Cloud": ("googlecloud", "https://cloud.google.com"), "Firebase": ("firebase", "https://firebase.google.com"),
    "PostgreSQL": ("postgresql", "https://www.postgresql.org"), "MySQL": ("mysql", "https://www.mysql.com"),
    "MongoDB": ("mongodb", "https://www.mongodb.com"), "SQLite": ("sqlite", "https://www.sqlite.org"),
    "Figma": ("figma", "https://www.figma.com"), "Unity": ("unity", "https://unity.com"),
    "Photoshop": ("adobephotoshop", "https://www.adobe.com/products/photoshop.html"), "Adobe XD": ("adobexd", "https://helpx.adobe.com/xd/get-started.html"),
}

STACK = [
    ("ai", ["PyTorch", "TensorFlow", "OpenCV", "pandas", "MATLAB"]),
    ("lang", ["Python", "TypeScript", "JavaScript", "C", "C++", "C#", "Java", "Dart", "Bash"]),
    ("web+mobile", ["React", "Next.js", "Node.js", "Django", "Flutter", "Tailwind"]),
    ("cloud+ops", ["Komuta", "Docker", "Linux", "Git", "Google Cloud", "Firebase"]),
    ("data", ["PostgreSQL", "MySQL", "MongoDB", "SQLite"]),
    ("design", ["Figma", "Unity", "Photoshop", "Adobe XD"]),
]

Q = """query($u:String!){user(login:$u){
 repositories(ownerAffiliations:OWNER,isFork:false,first:100,privacy:PUBLIC,orderBy:{field:PUSHED_AT,direction:DESC}){nodes{
   name isPrivate pushedAt diskUsage stargazerCount primaryLanguage{name}
   languages(first:10,orderBy:{field:SIZE,direction:DESC}){edges{size node{name}}}}}
 contributionsCollection{totalCommitContributions totalPullRequestContributions totalIssueContributions
   commitContributionsByRepository(maxRepositories:25){repository{name isPrivate} contributions{totalCount}}
   contributionCalendar{weeks{contributionDays{contributionCount date}}}}}}"""


def fetch():
    tok = token()
    req = urllib.request.Request("https://api.github.com/graphql",
                                 data=json.dumps({"query": Q, "variables": {"u": USER}}).encode(),
                                 headers={"Authorization": f"bearer {tok}", "Content-Type": "application/json",
                                          "User-Agent": "profile-htop-card"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    if "errors" in d:
        raise RuntimeError(d["errors"])
    u = d["data"]["user"]
    cc = u["contributionsCollection"]
    repos = [r for r in u["repositories"]["nodes"] if not r["isPrivate"]]
    commits = {c["repository"]["name"]: c["contributions"]["totalCount"]
               for c in cc["commitContributionsByRepository"] if not c["repository"]["isPrivate"]}
    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    days = [x["contributionCount"] for w in cc["contributionCalendar"]["weeks"] for x in w["contributionDays"]]
    return {
        "repos": [{"name": r["name"], "pushed": r["pushedAt"], "disk": r["diskUsage"] or 0,
                   "stars": r["stargazerCount"], "lang": (r["primaryLanguage"] or {}).get("name") or "-",
                   "commits": commits.get(r["name"], 0)} for r in repos],
        "langs": langs, "days": days,
        "commits": cc["totalCommitContributions"], "prs": cc["totalPullRequestContributions"],
        "issues": cc["totalIssueContributions"],
    }


def data():
    try:
        d = fetch()
        json.dump(d, open(CACHE, "w"))
        return d
    except Exception as e:
        print("fetch failed, using cache:", e, file=sys.stderr)
        return json.load(open(CACHE))


BASE_CSS = (
    ".o{opacity:0;animation:on .01s forwards}@keyframes on{to{opacity:1}}"
    ".fade{opacity:0;animation:fd .5s forwards}@keyframes fd{to{opacity:1}}"
    ".cur{animation:bl 1.05s steps(1) infinite}@keyframes bl{50%{opacity:0}}"
    ".roll{animation:roll 7s linear infinite}@keyframes roll{from{transform:translateY(-90px)}to{transform:translateY(700px)}}"
    ".g{fill:#39ff7a}.d{fill:#1f9e4a}.k{fill:#7dffb0;font-weight:700}.m{fill:#155c2e}.w{fill:#e6fff0}"
    ".a{fill:#ffd166}.r{fill:#ff6b6b}.c{fill:#5ce1e6}.b{fill:#4d8dff;font-weight:700}"
    "@media (prefers-reduced-motion:reduce){*{animation-duration:0s!important;animation-delay:0s!important}}"
)


def frame(W, H, title, defs, body, css="", anim=()):
    defs = [
        '<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="#000" opacity=".28"/></pattern>',
        '<filter id="glow" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="1.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '<radialGradient id="vig" cx="50%" cy="50%" r="75%"><stop offset="62%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".7"/></radialGradient>',
        f'<clipPath id="card"><rect width="{W}" height="{H}" rx="14"/></clipPath>'] + defs
    head = [f'<rect width="{W}" height="{H}" rx="14" fill="#050a06"/>',
            f'<rect width="{W}" height="36" fill="#0c140e" clip-path="url(#card)"/>',
            '<circle cx="22" cy="18" r="6" fill="#ff5f57"/><circle cx="42" cy="18" r="6" fill="#febc2e"/><circle cx="62" cy="18" r="6" fill="#28c840"/>',
            f'<text x="{W / 2}" y="23" font-size="12" text-anchor="middle" class="d">{escape(title)}</text>',
            '<g filter="url(#glow)">']
    tail = ['</g>', *anim, f'<rect width="{W}" height="{H}" rx="14" fill="url(#scan)"/>',
            f'<rect width="{W}" height="{H}" rx="14" fill="url(#vig)"/>']
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">'
            f'<style>{BASE_CSS}{css}</style><defs>{"".join(defs)}</defs>{"".join(head + body + tail)}</svg>')


def ago(iso):
    d = datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))
    h = int(d.total_seconds() // 3600)
    return f"{h // 24}d{h % 24:02d}h" if h >= 24 else f"{h}h{int(d.total_seconds() // 60) % 60:02d}m"


def htop(d):
    W, H, fs = 940, 470, 12
    cw = fs * CW
    rnd = random.Random(7)
    defs, body, css = [], [], []
    d1, b1, t = typed(24, 62, "{{d|➜}} {{k|~}} htop --user=mustafazahter --sort=commits", 0.3, 13, "g")
    defs.append(d1); body.append(b1)
    t += 0.2

    # CPU meters = language share
    langs = sorted(((k, v) for k, v in d["langs"].items() if k not in SKIP_LANGS), key=lambda x: -x[1])[:6]
    tot = sum(v for _, v in langs) or 1
    bars = 30
    css.append(".bar{transform-box:fill-box;transform-origin:left;transform:scaleX(0);animation:grow 1s cubic-bezier(.2,.8,.2,1) forwards}"
               "@keyframes grow{to{transform:scaleX(1)}}"
               ".jit{animation:jit 2.6s ease-in-out infinite alternate}@keyframes jit{from{opacity:1}to{opacity:.55}}")
    for i, (name, v) in enumerate(langs):
        y = 92 + i * 18
        pct = v / tot
        n = max(1, round(pct * bars))
        col = "g" if pct < .35 else "a" if pct < .5 else "r"
        body.append(f'<text x="24" y="{y}" font-size="{fs}" class="o c" style="animation-delay:{t + i * .08:.2f}s" xml:space="preserve">{i + 1:>2}<tspan class="w">[</tspan></text>')
        body.append(f'<text x="{24 + 3 * cw:.1f}" y="{y}" font-size="{fs}" class="bar {col}" style="animation-delay:{t + i * .08:.2f}s" xml:space="preserve">'
                    f'{"|" * n}</text>')
        body.append(f'<text x="{24 + (3 + bars) * cw:.1f}" y="{y}" font-size="{fs}" class="o" style="animation-delay:{t + i * .08:.2f}s" xml:space="preserve">'
                    f'<tspan class="d">{escape(name[:10]):>10} {pct * 100:4.1f}%</tspan><tspan class="w">]</tspan></text>')

    # Mem / Swp + summary block
    commits, prs, issues = d["commits"], d["prs"], d["issues"]
    days = d["days"]
    la = [sum(days[-n * 7:]) / n for n in (4, 13, 52)]  # contributions per week
    rx = 520
    right = [
        f"{{{{c|Tasks:}}}} {{{{w|{len(d['repos'])}}}}}, {{{{w|{sum(1 for r in d['repos'] if r['commits'])}}}}} running",
        f"{{{{c|Load average:}}}} {{{{w|{la[0]:.2f}}}}} {{{{g|{la[1]:.2f}}}}} {{{{d|{la[2]:.2f}}}}}",
        f"{{{{c|Commits:}}}} {{{{w|{commits}}}}}  {{{{c|PRs:}}}} {{{{w|{prs}}}}}  {{{{c|Issues:}}}} {{{{w|{issues}}}}}",
        f"{{{{c|Load:}}}} {{{{d|contributions per week · 4w 13w 52w}}}}",
        "{{c|Employer:}} {{w|Sage Teknoloji A.Ş.}}",
        "{{c|Building:}} {{b|komuta.io}} {{d|(PaaS)}}",
    ]
    for i, line in enumerate(right):
        dd, bb, _ = typed(rx, 92 + i * 18, line, t + 0.3 + i * .15, fs, "g", cps=120)
        defs.append(dd); body.append(bb)

    # process table = public repos by commits this year, then by recency
    ty = 92 + 6 * 18 + 26
    body.append(f'<rect x="16" y="{ty - 13}" width="{W - 32}" height="18" fill="#1f9e4a" class="o" style="animation-delay:{t + .6:.2f}s"/>')
    body.append(f'<text x="24" y="{ty}" font-size="{fs}" fill="#050a06" font-weight="700" class="o" style="animation-delay:{t + .6:.2f}s" xml:space="preserve">'
                f'{"PID":>5} {"USER":<9} {"S":1} {"CPU%":>5} {"MEM%":>5} {"TIME+":>7}  {"LANG":<11}Command</text>')
    repos = sorted(d["repos"], key=lambda r: (r["commits"], r["pushed"]), reverse=True)[:12]
    tc = sum(r["commits"] for r in repos) or 1
    td = sum(r["disk"] for r in repos) or 1
    rows_y = []
    for i, r in enumerate(repos):
        y = ty + 20 + i * 17
        rows_y.append(y)
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(r["pushed"].replace("Z", "+00:00"))).total_seconds() / 3600
        st = "R" if age_h < 24 * 7 else "S" if age_h < 24 * 90 else "Z"
        stc = "a" if st == "R" else "g" if st == "S" else "m"
        pid = 1000 + (sum(map(ord, r["name"])) * 37) % 9000
        line = (f'<tspan class="d">{pid:>5}</tspan> <tspan class="g">{"mustafa":<9}</tspan> <tspan class="{stc}">{st}</tspan> '
                f'<tspan class="w">{r["commits"] / tc * 100:5.1f}</tspan> <tspan class="g">{r["disk"] / td * 100:5.1f}</tspan> '
                f'<tspan class="d">{ago(r["pushed"]):>7}</tspan>  <tspan class="c">{escape(r["lang"][:10]):<11}</tspan>'
                f'<tspan class="{"k" if st == "R" else "g"}">{escape(r["name"])}</tspan>')
        body.append(f'<text x="24" y="{y}" font-size="{fs}" class="o" style="animation-delay:{t + .7 + i * .06:.2f}s" xml:space="preserve">{line}</text>')
    # selection bar walking down the list like someone pressing ↓
    if rows_y:
        n = len(rows_y)
        vals = ";".join(f"{y - 13}" for y in rows_y + rows_y[-2:0:-1])
        sel = (f'<rect x="16" y="{rows_y[0] - 13}" width="{W - 32}" height="17" fill="#39ff7a" fill-opacity=".13" stroke="#39ff7a" stroke-opacity=".35" class="o" style="animation-delay:{t + 1.5:.2f}s">'
                                   f'<animate attributeName="y" values="{vals}" dur="{(2 * n - 2) * 0.9:.1f}s" begin="{t + 1.5:.2f}s" repeatCount="indefinite" calcMode="discrete"/></rect>')
    else:
        sel = ''
    fy = H - 18
    keys = [("F1", "Help"), ("F2", "Hire"), ("F3", "Search"), ("F5", "Tree"), ("F6", "SortBy"), ("F9", "Kill bug"), ("F10", "Quit")]
    x = 16
    for k, v in keys:
        body.append(f'<text x="{x}" y="{fy}" font-size="{fs}" xml:space="preserve"><tspan class="w">{k}</tspan><tspan class="d" style="font-weight:700">{v:<9}</tspan></text>')
        x += (len(k) + 9) * cw + 6
    return frame(W, H, "htop — mustafa@zahter", defs, body, "".join(css), [sel])


def stack():
    W, fs = 940, 13
    lines = ["{{k|~/stack}}"]
    for i, (dname, items) in enumerate(STACK):
        br = "└──" if i == len(STACK) - 1 else "├──"
        lines.append(f"{{{{m|{br}}}}} {{{{c|{dname + '/':<12}}}}}" + "  ".join(f"{{{{{'b' if x == 'Komuta' else 'g'}|{x}}}}}" for x in items))
    lines.append("")
    lines.append(f"{{{{d|{len(STACK)} directories, {sum(len(x) for _, x in STACK)} tools}}}}")
    H = 70 + len(lines) * 22 + 20
    defs, body = [], []
    d1, b1, t = typed(24, 62, "{{d|➜}} {{k|~}} tree ~/stack -L 1 --noreport", 0.2, fs, "g")
    defs.append(d1); body.append(b1)
    for i, l in enumerate(lines):
        if not l:
            continue
        dd, bb, t = typed(24, 92 + i * 22, l, t + .05, fs, "g", cps=140)
        defs.append(dd); body.append(bb)
    cur = f'<rect x="24" y="{92 + len(lines) * 22 - 8}" width="8" height="2" class="g cur"/>'
    return frame(W, H, "zsh — ~/stack", defs, body, anim=[cur])


BUTTONS = [  # (file, label, accent)
    ("komuta", "komuta.io", "#4d8dff"),
    ("linkedin", "linkedin", "#3a9ae8"),
    ("mail", "mail", "#ea4335"),
    ("instagram", "instagram", "ig"),        # brand gradient
]


def button(label, accent, i):
    """Equal-size terminal key: `$ open <label>` with a blinking cursor."""
    W, H = 200, 44
    grad = ""
    if accent == "ig":
        grad = ('<linearGradient id="ig" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#feda75"/>'
                '<stop offset=".35" stop-color="#fa7e1e"/><stop offset=".6" stop-color="#d62976"/><stop offset="1" stop-color="#962fbf"/></linearGradient>')
        accent = "url(#ig)"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">'
            f'<style>.c{{animation:b 1.05s steps(1) infinite;animation-delay:{i * .26:.2f}s}}@keyframes b{{50%{{opacity:0}}}}'
            f'.r{{animation:p 3.2s ease-in-out infinite;animation-delay:{i * .4:.1f}s}}@keyframes p{{50%{{stroke-opacity:1}}}}</style>'
            f'<defs>{grad}<filter id="g"><feGaussianBlur stdDeviation="1.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
            f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="9" fill="#050a06"/>'
            f'<rect class="r" x="1" y="1" width="{W - 2}" height="{H - 2}" rx="9" fill="none" stroke="{accent}" stroke-opacity=".45" stroke-width="1.5"/>'
            f'<g filter="url(#g)"><text x="16" y="27" font-size="13"><tspan fill="#7d8590">$ open </tspan>'
            f'<tspan fill="{accent}" font-weight="700">{escape(label)}</tspan></text>'
            f'</g><rect class="c" x="{16 + (7 + len(label)) * 13 * CW + 3:.0f}" y="17" width="7" height="13" fill="{accent}" opacity=".85"/></svg>')


def badge(name):
    from urllib.parse import quote
    logo, url = LINKS.get(name, ("", "#"))
    label = quote(name.replace("-", "--").replace("_", "__"))
    col = "4d8dff" if name == "Komuta" else "39ff7a"
    return (f'<a href="{url}"><img src="https://img.shields.io/badge/{label}-0c140e?style=for-the-badge'
            f'&logo={logo}&logoColor={col}&labelColor=0c140e" alt="{escape(name)}"></a>')


def readme_blocks(d):
    """Clickable companions to the SVG panels (an <img> can't hold links)."""
    stack = ["<details><summary><code>▸ ls ~/stack</code> — click a folder to open it</summary><br>", ""]
    for dname, items in STACK:
        stack.append(f"<details><summary><code>📁 {dname}/</code> <sub>{len(items)} tools</sub></summary><p>")
        stack.append(" ".join(badge(x) for x in items))
        stack.append("</p></details>")
    stack.append("</details>")
    procs = ["<details><summary><code>▸ ps aux</code> — open a process (public repos)</summary><br>", "",
             "| state | repo | lang | commits (12 mo) | last push |", "|:-:|---|---|--:|--:|"]
    for r in sorted(d["repos"], key=lambda r: (r["commits"], r["pushed"]), reverse=True):
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(r["pushed"].replace("Z", "+00:00"))).total_seconds() / 3600
        st = "🟢 R" if age_h < 24 * 7 else "🟡 S" if age_h < 24 * 90 else "⚫ Z"
        procs.append(f"| {st} | [`{r['name']}`](https://github.com/{USER}/{r['name']}) | {r['lang']} | {r['commits']} | {ago(r['pushed'])} ago |")
    procs += ["", "</details>"]
    return {"STACK": "\n".join(stack), "PROCS": "\n".join(procs)}


def patch_readme(blocks):
    import re
    p = os.path.join(ROOT, "README.md")
    txt = open(p).read()
    for k, v in blocks.items():
        txt, n = re.subn(rf"(<!-- {k}:START -->).*?(<!-- {k}:END -->)", lambda m: f"{m.group(1)}\n{v}\n{m.group(2)}", txt, flags=re.S)
        if not n:
            print(f"warning: README has no {k} markers", file=sys.stderr)
    open(p, "w").write(txt)


if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    dd = data()
    patch_readme(readme_blocks(dd))
    for i, (f, label, acc) in enumerate(BUTTONS):
        open(os.path.join(ROOT, "dist", f"btn-{f}.svg"), "w").write(button(label, acc, i))
    for name, svg in (("htop", htop(dd)), ("stack", stack())):
        p = os.path.join(ROOT, "dist", f"{name}.svg")
        open(p, "w").write(svg)
        print(f"wrote {p} ({len(svg) // 1024} KB)")
