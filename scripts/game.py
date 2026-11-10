#!/usr/bin/env python3
"""COMMIT//STRIKE: a turn-based, first-person ASCII shooter played through GitHub issues.

You walk inside the owner's real contribution graph (every active day is a wall block,
brighter = more commits) and shoot their public repos, which crawl around as creatures.
Everybody shares one striker. Each issue titled `strike|<action>` is one turn: the
striker acts, then every repo that can see (or smell) the striker crawls closer or
bites. Merge every repo, an exit portal opens, walk into it, next level.

    python3 scripts/game.py --init        # fresh game at level 1
    python3 scripts/game.py --play        # env ISSUE_TITLE, ISSUE_AUTHOR, RESULT_FILE
    python3 scripts/game.py --render      # re-render board + README from state
    python3 scripts/game.py --selftest    # plays a few hundred turns on a temp copy

Data: assets/stats.json ("weeks": contribution levels 0-4, from render.py) and
assets/extras.json ("repos": public repos, from extras.py). Without them the game
falls back to a procedural maze and generic bug enemies.

Standard library only. The board is an SVG shown inside <img> on GitHub, so all
motion is CSS keyframes; there is no JS anywhere.
"""
import argparse, hashlib, json, math, os, random, re, sys, tempfile
from collections import deque
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote, quote_plus

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
CW = 0.602  # monospace advance / font-size

# ── rules ────────────────────────────────────────────────────────────
PREFIX = "strike"
HP_MAX = 100
FIRE_RANGE = 8.0
POINT_BLANK = 1.6        # within this distance a shot does 2 damage
SENSE_LOS = 9.0          # repos that see you within this range chase you
SENSE_SMELL = 3          # repos this many steps away chase you even without sight
PTS_ACTION, PTS_KILL, PTS_CLEAR, PTS_DEATH = 1, 10, 30, -5

DIR8 = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]  # E SE S SW W NW N NE (y down)
FACING = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]
ACTIONS = ["fwd", "back", "left", "right", "strafe-left", "strafe-right", "fire"]
ALIASES = {"forward": "fwd", "f": "fwd", "w": "fwd", "up": "fwd", "move": "fwd",
           "b": "back", "s": "back", "down": "back", "backward": "back", "backwards": "back",
           "l": "left", "turn-left": "left", "turnleft": "left", "r": "right", "turn-right": "right", "turnright": "right",
           "strafe_left": "strafe-left", "strafeleft": "strafe-left", "sl": "strafe-left", "a": "strafe-left",
           "strafe_right": "strafe-right", "straferight": "strafe-right", "sr": "strafe-right", "d": "strafe-right",
           "shoot": "fire", "x": "fire", "pew": "fire"}
MOVE_OFF = {"fwd": 0, "back": 4, "strafe-left": -2, "strafe-right": 2}
LABEL_MD = {"fwd": "⬆ forward", "back": "⬇ back", "left": "↺ turn left", "right": "↻ turn right",
            "strafe-left": "⇠ strafe left", "strafe-right": "⇢ strafe right", "fire": "🔫 fire"}
LABEL_SVG = {"fwd": "fwd", "back": "back", "left": "turn L", "right": "turn R",
             "strafe-left": "strafe L", "strafe-right": "strafe R", "fire": "FIRE"}
BODY = 'Just press "Submit new issue". The bot moves the striker and updates the board in ~30s.'

# enemy colour by language: amber, cyan, magenta, red (read well against the green)
LANG_TONE = {"Python": "a", "Jupyter Notebook": "a", "TypeScript": "c", "JavaScript": "c", "Dart": "c",
             "HTML": "m", "CSS": "m", "SCSS": "m", "Vue": "m", "Svelte": "m"}
TONES = {"a": "#ffb84d", "c": "#4dd8ff", "m": "#ff5cd6", "r": "#ff4d6d"}


def h32(*parts):
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:8], 16)


class Paths:
    def __init__(self, root=ROOT, assets=None):
        self.root = root
        self.assets = assets or os.path.join(root, "assets")
        self.state = os.path.join(root, "game", "state.json")
        self.board = os.path.join(root, "game", "board.svg")
        self.readme = os.path.join(root, "README.md")


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── world ────────────────────────────────────────────────────────────
# map chars: "." floor · "#" border/maze wall · "1"-"4" contribution block of that level
def grid(state):
    return [[c != "." for c in row] for row in state["map"]]

def floor(G, x, y):
    return 0 <= y < len(G) and 0 <= x < len(G[0]) and not G[y][x]

def bfs(G, start):
    dist = {start: 0}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in DIR8[0::2]:
            n = (x + dx, y + dy)
            if n not in dist and floor(G, *n):
                dist[n] = dist[(x, y)] + 1
                q.append(n)
    return dist

def can_step(G, x, y, dx, dy):
    """Diagonal steps may not squeeze between two wall corners."""
    if not floor(G, x + dx, y + dy):
        return False
    return dx == 0 or dy == 0 or (floor(G, x + dx, y) and floor(G, x, y + dy))

def los(G, a, b):
    ax, ay = a[0] + .5, a[1] + .5
    bx, by = b[0] + .5, b[1] + .5
    n = max(2, int(math.hypot(bx - ax, by - ay) * 8))
    for i in range(1, n):
        t = i / n
        if G[int(ay + (by - ay) * t)][int(ax + (bx - ax) * t)]:
            return False
    return True

def calendar(weeks):
    """Contribution weeks → full 7-day columns (a short first week is padded at the top)."""
    cols = []
    for i, wk in enumerate(weeks):
        wk = [max(0, min(4, int(v))) for v in wk][:7]
        cols.append(([0] * (7 - len(wk)) + wk) if i == 0 else (wk + [0] * (7 - len(wk))))
    return cols

SPANS = [13, 20, 27, 34, 41, 48, 53]

def window(level, cols):
    """Each level walks a different slice of the graph: spans grow, then cycle denser-first."""
    n = len(cols)
    span = min(SPANS[(level - 1) % len(SPANS)], n)
    cands = [(sum(1 for c in cols[s:s + span] for v in c if v), s) for s in range(n - span + 1)]
    cands.sort(key=lambda t: (-t[0], -t[1]))  # densest first, most recent on ties
    k = ((level - 1) // len(SPANS)) % len(cands)
    s = cands[k][1]
    return s, span

def arena_contrib(level, cols, rng):
    s, span = window(level, cols)
    part = cols[s:s + span]
    W, H = 3 * span + 3, 3 * 7 + 3
    M = [["#"] * W] + [["#"] + ["."] * (W - 2) + ["#"] for _ in range(H - 2)] + [["#"] * W]
    for i, col in enumerate(part):
        for d, v in enumerate(col):
            if v:
                for yy in (2 + 3 * d, 3 + 3 * d):
                    for xx in (2 + 3 * i, 3 + 3 * i):
                        M[yy][xx] = str(v)
    # join neighbouring active days into longer walls, but never cut the floor in two
    joins = []
    for i, col in enumerate(part):
        for d, v in enumerate(col):
            if v and i + 1 < span and part[i + 1][d]:
                joins.append([(4 + 3 * i, 2 + 3 * d), (4 + 3 * i, 3 + 3 * d), min(v, part[i + 1][d])])
            if v and d + 1 < 7 and col[d + 1]:
                joins.append([(2 + 3 * i, 4 + 3 * d), (3 + 3 * i, 4 + 3 * d), min(v, col[d + 1])])
    rng.shuffle(joins)
    total = sum(r.count(".") for r in M)
    for a, b, v in joins[:len(joins) * 2 // 3]:
        for x, y in (a, b):
            M[y][x] = str(v)
        G = [[c != "." for c in r] for r in M]
        if len(bfs(G, (1, 1))) != total - 2:
            for x, y in (a, b):
                M[y][x] = "."
        else:
            total -= 2
    first, last = s + 1, s + span
    label = f"weeks {first}–{last} of {len(cols)}"
    return ["".join(r) for r in M], label

def arena_maze(level, rng):
    cw, ch = min(8 + 2 * (level - 1), 14), min(6 + (level - 1), 10)
    W, H = 2 * cw + 1, 2 * ch + 1
    G = [[True] * W for _ in range(H)]
    G[1][1] = False
    stack, seen = [(0, 0)], {(0, 0)}
    while stack:
        x, y = stack[-1]
        nb = [(x + dx, y + dy, dx, dy) for dx, dy in DIR8[0::2]
              if 0 <= x + dx < cw and 0 <= y + dy < ch and (x + dx, y + dy) not in seen]
        if not nb:
            stack.pop()
            continue
        nx, ny, dx, dy = rng.choice(nb)
        G[2 * y + 1 + dy][2 * x + 1 + dx] = False
        G[2 * ny + 1][2 * nx + 1] = False
        seen.add((nx, ny))
        stack.append((nx, ny))
    walls = [(gx, gy) for gy in range(1, H - 1) for gx in range(1, W - 1) if G[gy][gx] and (gx % 2) != (gy % 2)]
    rng.shuffle(walls)
    for gx, gy in walls[:len(walls) // 9]:
        G[gy][gx] = False
    for _ in range(2 + level // 2):
        rw, rh = rng.choice([3, 5]), rng.choice([3, 3, 5])
        rx, ry = rng.randrange(1, W - rw, 2), rng.randrange(1, H - rh, 2)
        for yy in range(ry, ry + rh):
            for xx in range(rx, rx + rw):
                G[yy][xx] = False
    rows = ["".join(("#" if (x in (0, W - 1) or y in (0, H - 1)) else str(1 + h32(x, y, level) % 4)) if c else "."
                    for x, c in enumerate(row)) for y, row in enumerate(G)]
    return rows, "procedural maze"

def roster(level, repos):
    """4-7 repos per level, cycling through the list across levels."""
    n = min(3 + level, 7)
    if not repos:
        return [{"name": f"bug#{(level * 7 + i) % 256:02x}", "lang": "-", "hp": 2} for i in range(n)]
    start = sum(min(3 + l, 7) for l in range(1, level)) % len(repos)
    out = []
    for i in range(n):
        r = repos[(start + i) % len(repos)]
        out.append({"name": str(r.get("name", "repo"))[:60], "lang": str(r.get("lang") or "-")[:30],
                    "hp": max(1, min(4, 1 + int(r.get("commits") or 0) // 15))})
    return out

def gen_level(level, base_seed, assets):
    lseed = h32("strike", base_seed, level)
    rng = random.Random(lseed)
    stats = load_json(os.path.join(assets, "stats.json")) or {}
    extras = load_json(os.path.join(assets, "extras.json")) or {}
    cols = calendar(stats.get("weeks") or [])
    if len(cols) >= 13 and sum(1 for c in cols for v in c if v) >= 10:
        rows, label = arena_contrib(level, cols, rng)
        arena = "contributions"
    else:
        rows, label = arena_maze(level, rng)
        arena = "maze"
    G = [[c != "." for c in r] for r in rows]
    if arena == "contributions":  # middle of the left edge, looking into the graph
        mid = len(rows) // 2
        y = min((y for y in range(1, len(rows) - 1) if not G[y][2] and not G[y][3]), key=lambda y: abs(y - mid))
        start, facing = (1, y), 0
    else:
        start = (1, 1)
        facing = 0 if not G[1][2] else 2
    dist = bfs(G, start)
    far = max(dist.values())
    portal = rng.choice(sorted(p for p, d in dist.items() if d >= far - 1))
    cand = sorted(p for p, d in dist.items() if d >= 8 and p != portal)
    rng.shuffle(cand)
    repos = [r for r in (extras.get("repos") or []) if isinstance(r, dict) and r.get("name")]
    who = roster(level, repos)
    spots = []
    for spacing in (6, 4, 3, 2, 0):
        for p in cand:
            if len(spots) >= len(who):
                break
            if p not in spots and all(max(abs(p[0] - b[0]), abs(p[1] - b[1])) >= spacing for b in spots):
                spots.append(p)
    enemies = [dict(id=i, x=x, y=y, hp=w["hp"], max=w["hp"], name=w["name"], lang=w["lang"])
               for i, ((x, y), w) in enumerate(zip(spots, who))]
    return {"level_seed": lseed, "w": len(rows[0]), "h": len(rows), "map": rows, "arena": arena, "arena_label": label,
            "start": list(start), "start_facing": facing, "portal": list(portal), "enemies": enemies}

def enter_level(state, level, assets):
    lv = gen_level(level, state["seed"], assets)
    state.update(level=level, level_seed=lv["level_seed"], w=lv["w"], h=lv["h"], map=lv["map"],
                 arena=lv["arena"], arena_label=lv["arena_label"],
                 start=lv["start"], portal=lv["portal"], enemies=lv["enemies"], enemies_total=len(lv["enemies"]),
                 kills_level=0, turn=0,
                 player={"x": lv["start"][0], "y": lv["start"][1], "facing": lv["start_facing"], "hp": HP_MAX},
                 seen=["0" * lv["w"] for _ in range(lv["h"])])
    reveal(state)

def new_state(seed, assets):
    st = {"game": "commit-strike", "version": 1, "seed": seed, "moves": 0, "points": 0, "deaths": 0,
          "players": {}, "history": [], "cleared": [], "last": None}
    enter_level(st, 1, assets)
    return st


# ── raycasting ───────────────────────────────────────────────────────
FOV = math.radians(66)
TANH = math.tan(FOV / 2)

def camera(p):
    a = p["facing"] * math.pi / 4
    return (p["x"] + .5, p["y"] + .5), (math.cos(a), math.sin(a)), (-math.sin(a) * TANH, math.cos(a) * TANH)

def cast(G, px, py, rx, ry):
    """DDA. Returns (perp distance, side, wall x fraction, floor tiles passed, wall tile)."""
    mx, my = int(px), int(py)
    ddx = abs(1 / rx) if rx else 1e30
    ddy = abs(1 / ry) if ry else 1e30
    sx, sdx = (-1, (px - mx) * ddx) if rx < 0 else (1, (mx + 1 - px) * ddx)
    sy, sdy = (-1, (py - my) * ddy) if ry < 0 else (1, (my + 1 - py) * ddy)
    tiles = []
    for _ in range(512):
        if sdx < sdy:
            sdx += ddx; mx += sx; side = 0
        else:
            sdy += ddy; my += sy; side = 1
        if G[my][mx]:
            perp = (sdx - ddx) if side == 0 else (sdy - ddy)
            wx = (py + perp * ry) if side == 0 else (px + perp * rx)
            return max(perp, 1e-3), side, wx - math.floor(wx), tiles, (mx, my)
        tiles.append((mx, my))
    return 64.0, 0, 0.0, tiles, (mx, my)

def reveal(state):
    G = grid(state)
    p = state["player"]
    (px, py), (dx, dy), (qx, qy) = camera(p)
    seen = [list(r) for r in state["seen"]]
    for c in range(64):
        k = 2 * (c + .5) / 64 - 1
        _, _, _, tiles, wall = cast(G, px, py, dx + qx * k, dy + qy * k)
        for tx, ty in (tiles + [wall])[:40]:
            seen[ty][tx] = "1"
    for ddx in (-1, 0, 1):
        for ddy in (-1, 0, 1):
            x, y = p["x"] + ddx, p["y"] + ddy
            if 0 <= y < state["h"] and 0 <= x < state["w"]:
                seen[y][x] = "1"
    state["seen"] = ["".join(r) for r in seen]


# ── game logic ───────────────────────────────────────────────────────
def parse(title):
    parts = [s.strip().lower() for s in (title or "").split("|")]
    if len(parts) < 2 or parts[0] != PREFIX:
        return None
    a = parts[1].replace(" ", "-")
    a = ALIASES.get(a, a)
    return a if a in ACTIONS else None

def clean_user(u):
    u = re.sub(r"[^A-Za-z0-9-]", "", (u or "").replace("[bot]", ""))[:39]
    return u or "anonymous"

def enemy_at(state, x, y):
    return next((e for e in state["enemies"] if e["x"] == x and e["y"] == y), None)

def adjacent(G, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    return max(abs(dx), abs(dy)) == 1 and can_step(G, a[0], a[1], dx, dy)

def target(state, G):
    """Nearest repo near the crosshair, in range and in sight."""
    p = state["player"]
    (px, py), (dx, dy), _ = camera(p)
    best = None
    for e in state["enemies"]:
        rx, ry = e["x"] + .5 - px, e["y"] + .5 - py
        depth = rx * dx + ry * dy
        lat = rx * -dy + ry * dx
        if depth <= .2 or depth > FIRE_RANGE or abs(lat) > max(.55, depth * math.tan(math.radians(11))):
            continue
        if not los(G, (p["x"], p["y"]), (e["x"], e["y"])):
            continue
        d = math.hypot(rx, ry)
        if best is None or d < best[0]:
            best = (d, e)
    return best

def enemies_act(state, G, rng):
    p = state["player"]
    me = (p["x"], p["y"])
    dist = bfs(G, me)
    bites = []
    for e in sorted(state["enemies"], key=lambda e: e["id"]):
        pos = (e["x"], e["y"])
        if adjacent(G, pos, me):
            bites.append(rng.randint(6, 10))
            continue
        here = dist.get(pos, 999)
        sees = math.dist(pos, me) <= SENSE_LOS and los(G, pos, me)
        free = [(e["x"] + dx, e["y"] + dy) for dx, dy in DIR8[0::2]
                if floor(G, e["x"] + dx, e["y"] + dy) and (e["x"] + dx, e["y"] + dy) != me
                and not enemy_at(state, e["x"] + dx, e["y"] + dy)]
        if not free:
            continue
        if sees or here <= SENSE_SMELL:
            closer = [n for n in free if dist.get(n, 999) < here]
            if closer:
                closer.sort(key=lambda n: (dist.get(n, 999), math.dist(n, me)))
                e["x"], e["y"] = closer[0]
        elif rng.random() < .35:
            e["x"], e["y"] = rng.choice(free)
    return bites

def play(state, user, title, assets, now=None):
    """Apply one turn. Returns (ok, markdown message). Bad titles leave state untouched."""
    act = parse(title)
    user = clean_user(user)
    if act is None:
        return False, (f"🤔 Sorry @{user}, I couldn't read `{re.sub(r'[`@<>]', '', (title or '')[:80])}`.\n\n"
                       f"Valid titles: {', '.join(f'`{PREFIX}|{a}`' for a in ACTIONS)}. "
                       "Use the control pad on the profile README, it fills the title for you.")
    now = now or datetime.now(timezone.utc)
    G = grid(state)
    p = state["player"]
    rng = random.Random(h32(state["level_seed"], state["moves"], user))
    level = state["level"]
    last = {"user": user, "action": act, "valid": True, "bonk": False, "fired": False, "hit": None, "hit_name": None,
            "kill": None, "kill_name": None, "bitten": 0, "died": False, "cleared": None}
    notes, pts = [], 0

    if act in ("left", "right"):
        p["facing"] = (p["facing"] + (-1 if act == "left" else 1)) % 8
        notes.append(f"turned to face {FACING[p['facing']]}")
    elif act in MOVE_OFF:
        dx, dy = DIR8[(p["facing"] + MOVE_OFF[act]) % 8]
        blocker = enemy_at(state, p["x"] + dx, p["y"] + dy)
        if can_step(G, p["x"], p["y"], dx, dy) and not blocker:
            p["x"] += dx; p["y"] += dy
            notes.append("moved" if act in ("fwd", "back") else "strafed")
        else:
            last["valid"], last["bonk"] = False, True
            notes.append(f"{blocker['name']} blocks the way" if blocker else "bonk! that's a wall")
    else:  # fire
        last["fired"] = True
        t = target(state, G)
        if t is None:
            notes.append("missed, nothing in the crosshair")
        else:
            d, e = t
            e["hp"] -= 2 if d <= POINT_BLANK else 1
            if e["hp"] <= 0:
                state["enemies"].remove(e)
                state["kills_level"] += 1
                pts += PTS_KILL
                last["kill"], last["kill_name"] = [e["x"], e["y"]], e["name"]
                notes.append(f"💥 {e['name']} merged! +{PTS_KILL}")
                if not state["enemies"]:
                    notes.append("every repo merged, the exit portal is open")
            else:
                last["hit"], last["hit_name"] = [e["x"], e["y"]], e["name"]
                notes.append(f"hit {e['name']} ({e['hp']}/{e['max']} hp left)")
    if last["valid"]:
        pts += PTS_ACTION

    if not state["enemies"] and [p["x"], p["y"]] == state["portal"]:
        pts += PTS_CLEAR
        state["cleared"] = (state["cleared"] + [{"level": level, "user": user, "turns": state["turn"] + 1,
                                                 "time": now.strftime("%Y-%m-%dT%H:%M:%SZ")}])[-5:]
        notes.append(f"🌀 entered the portal, level {level} shipped")
        last["cleared"] = level
        enter_level(state, level + 1, assets)
    else:
        bites = enemies_act(state, G, rng)
        if bites:
            dmg = sum(bites)
            p["hp"] -= dmg
            last["bitten"] = dmg
            notes.append(f"bitten for {dmg} hp" + (f" by {len(bites)} repos" if len(bites) > 1 else ""))
        if p["hp"] <= 0:
            pts += PTS_DEATH
            state["deaths"] += 1
            last["died"] = True
            notes.append("💀 segfault (core dumped), level restarts")
            enter_level(state, level, assets)
        else:
            state["turn"] += 1
            reveal(state)

    state["moves"] += 1
    state["points"] += pts
    pl = state["players"].setdefault(user, {"score": 0, "actions": 0, "kills": 0, "clears": 0, "deaths": 0})
    pl["score"] += pts
    pl["actions"] += 1
    pl["kills"] += 1 if last["kill"] else 0
    pl["clears"] += 1 if last["cleared"] else 0
    pl["deaths"] += 1 if last["died"] else 0
    last["points"] = pts
    last["note"] = "; ".join(notes)
    state["last"] = last
    state["history"] = (state["history"] + [{
        "user": user, "action": act, "result": short_result(last), "points": pts, "level": level,
        "time": now.strftime("%Y-%m-%dT%H:%M:%SZ")}])[-8:]

    rank = 1 + sum(1 for v in state["players"].values() if v["score"] > pl["score"])
    icon = "🎯" if act == "fire" else "🧭" if act in ("left", "right") else "🏃"
    sign = f"+{pts}" if pts >= 0 else str(pts)
    p = state["player"]
    msg = (f"{icon} **{LABEL_MD[act]}**: {last['note']} · **{sign}** · your score **{pl['score']}** (#{rank})\n\n"
           f"`LVL {state['level']:02d}` · `HP {max(p['hp'], 0)}` · `repos left {len(state['enemies'])}`"
           + (" · `portal open`" if not state["enemies"] else ""))
    return True, msg

def short_result(last):
    if last["cleared"]:
        return f"level {last['cleared']} shipped 🌀"
    if last["died"]:
        return "segfault 💀"
    if last["kill"]:
        r = f"💥 {last['kill_name']} merged"
    elif last["hit"]:
        r = f"hit {last['hit_name']}"
    elif last["fired"]:
        r = "miss"
    elif last["bonk"]:
        r = "bonk"
    elif last["action"] in ("left", "right"):
        r = "turned"
    else:
        r = "moved" if last["action"] in ("fwd", "back") else "strafed"
    if last["bitten"]:
        r += f", bitten -{last['bitten']}"
    return r


# ── board.svg ────────────────────────────────────────────────────────
VW, VH = 100, 34          # viewport in characters
VX, VY = 24, 70           # viewport origin (px)
VPW = 892                 # viewport width (px)
FS = VPW / (VW * CW)      # font size so 100 glyphs fill the width
LH = 14.4                 # line height (px)
VPH = VH * LH
FOCAL = (VPW / 2) / TANH  # px
BG = "#030603"

WALL_GLYPH = ["█", "▓", "▒", "░", ":", "."]
WALL_BINS = [2.0, 4.0, 7.0, 11.0, 17.0, 999]
DIM = [1, .88, .76, .65, .55, .46, .38, .31]                 # brightness per distance step
WALL_BASE = {"#": "#1f7a42", "1": "#1d9e4a", "2": "#33d062", "3": "#62f08c", "4": "#c8ffe0"}  # contribution level → colour
PAL = {
    "f0": "#2bd062", "f1": "#21903f", "f2": "#17652f", "f3": "#114a24", "f4": "#0c3019",
    "c0": "#155c2e", "c1": "#0f3d20", "c2": "#0b2a16",
    "ee": "#fff6d6", "pt": "#e6fff0",
}

def mix(hex_, f):
    a = [int(BG[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))

for _k, _v in WALL_BASE.items():
    for _i, _f in enumerate(DIM):
        PAL[f"w{'b' if _k == '#' else _k}{_i}"] = mix(_v, _f)
for _k, _v in TONES.items():
    for _i, _f in enumerate((1, .78, .56)):
        PAL[f"e{_k}{_i}"] = mix(_v, _f)

# original sprites: a repo-creature is a little folder with eyes and teeth
REPO_L = [" ._____.        ",
          " |     \\______  ",
          " |  (o)    (o) |",
          " |    \\/\\/\\/   |",
          " |_____________|",
          "   /|        |\\ "]
REPO_M = [" ._.___ ",
          " |o  o| ",
          " |vvvv| ",
          " /----\\ "]
REPO_S = ["[oo]",
          "/vv\\"]
REPO_T = ["*"]
SPLAT_L = ["  .   '  *   . ",
           "   *  \\ | /  ' ",
           " --  MERGED  --",
           "   '  / | \\  * "]
SPLAT_S = ["*✓*"]
PORTAL_L = ["╔══════╗",
            "║ $_   ║",
            "║ EXIT ║",
            "║      ║",
            "╚══════╝"]
PORTAL_M = ["╔══╗", "║$_║", "╚══╝"]
PORTAL_S = ["[>]"]

GUN = ["           _||_           ",
       "          |_||_|          ",
       "      ____/ || \\____      ",
       "     / [PUSH --FORCE] \\   ",
       "    | ::  ======  :: |    ",
       "    |________________|    "]
FLASH = ["  \\  |  /  ",
         "--=  *  =--",
         "  /  |  \\  "]


def dist_step(d):
    return next(i for i, b in enumerate(WALL_BINS) if d < b)

def tone_of(lang):
    return LANG_TONE.get(lang, "r")

def view(state):
    """Rasterise the first-person view into a VH×VW char grid with colour classes."""
    G = grid(state)
    M = state["map"]
    p = state["player"]
    last = state.get("last") or {}
    (px, py), (dx, dy), (qx, qy) = camera(p)
    ch = [[" "] * VW for _ in range(VH)]
    cl = [[None] * VW for _ in range(VH)]
    zbuf = [0.0] * VW
    half = VH / 2
    for c in range(VW):
        k = 2 * (c + .5) / VW - 1
        rx, ry = dx + qx * k, dy + qy * k
        perp, side, wx, _, (tx, ty) = cast(G, px, py, rx, ry)
        zbuf[c] = perp
        hrows = FOCAL / perp / LH
        top, bot = half - hrows / 2, half + hrows / 2
        step = dist_step(perp)
        seam = perp < 5 and min(wx, 1 - wx) < (.03 if perp < 2 else .055)
        gi = min(step + side + seam, 5)
        ci = min(step + side + seam, 7)
        wc = M[ty][tx]
        cls = f"w{'b' if wc == '#' else wc}{ci}"
        for r in range(VH):
            a, b = max(r, top), min(r + 1, bot)
            cov = b - a
            if cov > .5 or (cov > .25 and gi == 0):
                g = WALL_GLYPH[gi]
                if gi == 0 and cov < .75:
                    g = "▄" if a > r else "▀"
                ch[r][c], cl[r][c] = g, cls
                continue
            off = (r + .5 - half) * LH
            dist = .5 * FOCAL / abs(off)
            fx, fy = px + rx * dist, py + ry * dist
            ex, ey = min(fx % 1, 1 - fx % 1), min(fy % 1, 1 - fy % 1)
            tol = .045 + .012 * dist
            if off > 0:  # floor: perspective grid of distance-graded dots
                if ex < tol or ey < tol:
                    fi = 0 if dist < 1.2 else 1 if dist < 2.2 else 2 if dist < 3.8 else 3 if dist < 6.5 else 4
                    ch[r][c] = ":" if dist < 1.6 else "·" if dist < 4 else "."
                    cl[r][c] = f"f{fi}"
                elif dist < 9 and (c + 2 * r) % (2 if dist < 1.6 else 3 if dist < 3.5 else 5) == 0:
                    ch[r][c] = "." if dist > 1.6 else "·"
                    cl[r][c] = "f3" if dist < 3.5 else "f4"
            else:        # ceiling: faint beams along one axis
                if dist < 7 and (ex if p["facing"] % 4 == 2 else ey) < tol * .8 and c % 2 == 0:
                    ch[r][c] = "-" if dist < 2 else "."
                    cl[r][c] = "c0" if dist < 2.5 else "c1" if dist < 4.5 else "c2"

    sprites = [("repo", e["x"], e["y"], e) for e in state["enemies"]]
    if last.get("kill") and not last.get("died") and not last.get("cleared"):
        sprites.append(("splat", last["kill"][0], last["kill"][1], {"name": last.get("kill_name")}))
    if not state["enemies"]:
        sprites.append(("portal", state["portal"][0], state["portal"][1], None))
    proj = []
    for kind, sx, sy, e in sprites:
        rx, ry = sx + .5 - px, sy + .5 - py
        depth = rx * dx + ry * dy
        lat = rx * -dy + ry * dx
        if .35 < depth < 16:
            proj.append((depth, lat, kind, sx, sy, e))
    placed = []
    for depth, lat, kind, sx, sy, e in sorted(proj, key=lambda t: -t[0]):
        ccol = VW / 2 * (1 + lat / depth / TANH)
        hit = False
        if kind == "repo":
            art = REPO_L if depth < 1.9 else REPO_M if depth < 3.6 else REPO_S if depth < 6.5 else REPO_T
            hit = last.get("hit") == [sx, sy] and last.get("hit_name") == e["name"]
            tone = "eh" if hit else f"e{tone_of(e['lang'])}{0 if depth < 2.5 else 1 if depth < 5 else 2}"
        elif kind == "splat":
            art, tone = (SPLAT_L if depth < 2.6 else SPLAT_S), "ek"
        else:
            art = PORTAL_L if depth < 2.6 else PORTAL_M if depth < 5.5 else PORTAL_S
            tone = "pt"
        hs, ws = len(art), len(art[0])
        contact = half + (.5 * FOCAL / depth) / LH
        bottom = min(contact, VH - 1) - .5 if kind == "portal" else min(contact, VH - 7 if depth < 1.9 else VH - 2)
        top = int(round(bottom - hs + 1))
        left = int(round(ccol - ws / 2))
        drawn = 0
        for i, line in enumerate(art):
            for j, g in enumerate(line):
                r, c = top + i, left + j
                if g == " " or not (0 <= r < VH and 0 <= c < VW) or depth >= zbuf[c]:
                    continue
                ch[r][c] = g
                cl[r][c] = "ee" if (kind == "repo" and g == "o" and not hit) else tone
                drawn += 1
        if drawn:
            placed.append({"kind": kind, "depth": depth, "e": e, "hit": hit,
                           "x": VX + (left + ws / 2) * VPW / VW, "y": VY + top * LH})
    return ch, cl, placed

def runs(chars, classes):
    out, cur, buf = [], None, ""
    def flush():
        if buf:
            out.append(f'<tspan class="{cur}">{escape(buf, False)}</tspan>' if cur else escape(buf, False))
    for g, c in zip(chars, classes):
        c = cur if g == " " else c
        if c != cur and buf:
            flush(); buf = ""
        cur = c; buf += g
    flush()
    return "".join(out)

def txt(x, y, s, size=12, cls="g", anchor=None, extra=""):
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" class="{cls}"{a}{extra} xml:space="preserve">{s}</text>'

def plain(s):
    """Drop emoji (colour glyphs break the phosphor look inside the SVG)."""
    return re.sub(r"[^\x20-\u2fff]", "", s).replace("  ", " ").strip()

def trunc(s, n):
    return s if len(s) <= n else s[:n - 1] + "…"

def render(state):
    W = 940
    HUD_Y = VY + VPH + 14
    PANEL_Y = HUD_Y + 46
    H = int(PANEL_Y + 128)
    p = state["player"]
    last = state.get("last") or {}
    ch, cl, placed = view(state)
    defs, body = [], []

    css = [
        ".g{fill:#39ff7a}.d{fill:#1f9e4a}.k{fill:#7dffb0;font-weight:700}.m{fill:#155c2e}.w{fill:#e6fff0}.r{fill:#ff4d6d}",
        "".join(f".{k}{{fill:{v}}}" for k, v in PAL.items()),
        "".join(f".t{k}{{fill:{v}}}" for k, v in TONES.items()),
        ".lb{paint-order:stroke;stroke:#030603;stroke-width:3px;font-weight:700}",
        ".eh{fill:#fff;animation:eh 1.6s steps(1) infinite}@keyframes eh{0%,12%,24%{fill:#fff}6%,18%,30%,100%{fill:#ff4d6d}}",
        ".ek{fill:#e6fff0;animation:ek 2.6s forwards}@keyframes ek{0%{opacity:1}70%{opacity:.85}100%{opacity:0}}",
        ".pt{animation:pt 1.4s ease-in-out infinite}@keyframes pt{50%{fill:#7dffb0;opacity:.75}}",
        ".cur{animation:bl 1.05s steps(1) infinite}@keyframes bl{50%{opacity:0}}",
        ".roll{animation:roll 7s linear infinite}@keyframes roll{from{transform:translateY(-90px)}to{transform:translateY(" + str(H + 60) + "px)}}",
        ".flick{animation:fl 5s infinite}@keyframes fl{0%,95%,100%{opacity:1}96%{opacity:.75}97%{opacity:1}98%{opacity:.85}}",
        ".bob{animation:bob 2.6s ease-in-out infinite alternate}@keyframes bob{from{transform:translate(0,0)}to{transform:translate(3px,4px)}}",
        ".recoil{animation:rc 3.2s infinite}@keyframes rc{0%{transform:translateY(0)}3%{transform:translateY(12px)}14%,100%{transform:translateY(0)}}",
        ".flash{opacity:0;animation:mf 3.2s infinite}@keyframes mf{0%,5%{opacity:1}7%,100%{opacity:0}}",
        ".hm{opacity:0;animation:hm 3.2s infinite}@keyframes hm{2%,22%{opacity:1}30%,100%{opacity:0}}",
        ".dmg{animation:dmg 2.2s ease-out infinite}@keyframes dmg{0%{opacity:1}55%,100%{opacity:.25}}",
        ".pop{animation:pop 2.6s ease-out forwards}@keyframes pop{0%{opacity:0;transform:translateY(6px)}15%{opacity:1}100%{opacity:0;transform:translateY(-26px)}}",
        ".ban{animation:ban 5s forwards}@keyframes ban{0%,75%{opacity:1}100%{opacity:0}}",
        "@media (prefers-reduced-motion:reduce){*{animation-duration:0s!important;animation-delay:0s!important}}",
    ]
    defs += [
        '<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="#000" opacity=".28"/></pattern>',
        '<filter id="glow" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="1.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '<radialGradient id="vig" cx="50%" cy="50%" r="75%"><stop offset="62%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".72"/></radialGradient>',
        '<radialGradient id="hurt" cx="50%" cy="50%" r="70%"><stop offset="55%" stop-color="#ff1f4b" stop-opacity="0"/><stop offset="100%" stop-color="#ff1f4b" stop-opacity=".42"/></radialGradient>',
        f'<clipPath id="card"><rect width="{W}" height="{H}" rx="14"/></clipPath>',
        f'<clipPath id="vp"><rect x="{VX}" y="{VY}" width="{VPW}" height="{VPH:.1f}"/></clipPath>',
    ]
    where = f'inside contributions · {state["arena_label"]}' if state["arena"] == "contributions" else state["arena_label"]
    body += [
        f'<rect width="{W}" height="{H}" rx="14" fill="#050a06"/>',
        f'<rect width="{W}" height="36" fill="#0c140e" clip-path="url(#card)"/>',
        '<circle cx="22" cy="18" r="6" fill="#ff5f57"/><circle cx="42" cy="18" r="6" fill="#febc2e"/><circle cx="62" cy="18" r="6" fill="#28c840"/>',
        f'<text x="{W / 2}" y="23" font-size="12" text-anchor="middle" class="d">commit//strike — level {state["level"]} · {escape(where)}</text>',
        '<g filter="url(#glow)" class="flick">',
        txt(24, 58, f'<tspan class="d">➜</tspan> <tspan class="k">~</tspan> git strike --level {state["level"]} --seed {state["seed"]:08x}'
                    f'<tspan class="m">   # shoot your repos inside your own contribution graph</tspan>', 12),
        txt(916, 58, f'<tspan class="m">pos</tspan> {p["x"]:03d},{p["y"]:02d} <tspan class="m">facing</tspan> {FACING[p["facing"]]:<2}', 12, "d", "end"),
    ]

    # 1 · first-person view
    body.append(f'<rect x="{VX - 1}" y="{VY - 1}" width="{VPW + 2}" height="{VPH + 2:.1f}" fill="{BG}" stroke="#155c2e" stroke-width="1"/>')
    rows = []
    for r in range(VH):
        y = VY + r * LH + LH * .78
        rows.append(f'<text x="{VX}" y="{y:.1f}" font-size="{FS:.2f}" textLength="{VPW}" lengthAdjust="spacing" xml:space="preserve">{runs(ch[r], cl[r])}</text>')
    vp = ["".join(rows)]

    # repo name tags float above each creature; "+10" over a fresh merge
    for s in sorted(placed, key=lambda s: -s["depth"]):
        if s["kind"] == "repo" and s["depth"] < 10:
            e = s["e"]
            size = 12.5 if s["depth"] < 2.5 else 11 if s["depth"] < 5 else 9.5
            pips = "■" * e["hp"] + "□" * (e["max"] - e["hp"])
            ty = max(VY + 14, s["y"] - 5)
            vp.append(txt(s["x"], ty, f'{escape(trunc(e["name"], 18))} <tspan class="w">{pips}</tspan>', size,
                          f't{tone_of(e["lang"])} lb', "middle"))
        elif s["kind"] == "splat":
            vp.append(txt(s["x"], s["y"] - 6, f'+{PTS_KILL} {escape(trunc(s["e"]["name"] or "", 18))} merged', 14, "k lb pop", "middle"))
        elif s["kind"] == "portal" and s["depth"] < 10:
            vp.append(txt(s["x"], max(VY + 14, s["y"] - 5), "exit portal", 11, "pt lb", "middle"))
    body.append(f'<g clip-path="url(#vp)">{"".join(vp)}</g>')

    cx, cy = VX + VPW / 2, VY + VPH / 2
    body.append(f'<g stroke="#7dffb0" stroke-width="1.4" opacity=".75"><line x1="{cx - 11}" y1="{cy}" x2="{cx - 4}" y2="{cy}"/><line x1="{cx + 4}" y1="{cy}" x2="{cx + 11}" y2="{cy}"/>'
                f'<line x1="{cx}" y1="{cy - 9}" x2="{cx}" y2="{cy - 3}"/><line x1="{cx}" y1="{cy + 3}" x2="{cx}" y2="{cy + 9}"/></g>')
    if last.get("fired") and (last.get("hit") or last.get("kill")):
        body.append('<g class="hm" stroke="#fff" stroke-width="2.2" stroke-linecap="round">'
                    + "".join(f'<line x1="{cx + sx * 7}" y1="{cy + sy * 7}" x2="{cx + sx * 15}" y2="{cy + sy * 15}"/>' for sx in (-1, 1) for sy in (-1, 1))
                    + "</g>")

    # 2 · the gun (own layer so it can bob / recoil over the floor)
    gcw = VPW / VW
    gw = len(GUN[0])
    gx = VX + (VW - gw) / 2 * gcw
    gy = VY + VPH - len(GUN) * LH
    gun = []
    for i, line in enumerate(GUN):
        a, b = len(line) - len(line.lstrip()), len(line.rstrip())
        gun.append(f'<rect x="{gx + a * gcw:.1f}" y="{gy + i * LH:.1f}" width="{(b - a) * gcw:.1f}" height="{LH + .5:.1f}" fill="{BG}"/>')
    for i, line in enumerate(GUN):
        s = escape(line, False).replace("PUSH --FORCE", '<tspan class="w">PUSH --FORCE</tspan>').replace("======", '<tspan class="k">======</tspan>')
        gun.append(f'<text x="{gx:.1f}" y="{gy + i * LH + LH * .78:.1f}" font-size="{FS:.2f}" textLength="{gw * gcw:.1f}" lengthAdjust="spacing" class="d" xml:space="preserve">{s}</text>')
    fired = last.get("fired")
    flash = ""
    if fired:
        fx = VX + (VW - len(FLASH[0])) / 2 * gcw
        flash = '<g class="flash">' + "".join(
            f'<text x="{fx:.1f}" y="{gy - (len(FLASH) - i) * LH + LH * .78:.1f}" font-size="{FS:.2f}" class="w" xml:space="preserve">{escape(l, False)}</text>'
            for i, l in enumerate(FLASH)) + f'<circle cx="{cx}" cy="{gy - LH * 1.6:.1f}" r="26" fill="#e6fff0" opacity=".18"/></g>'
    body.append(f'<g clip-path="url(#vp)"><g class="bob"><g class="{"recoil" if fired else ""}">{"".join(gun)}{flash}</g></g></g>')

    # 3 · minimap inset: the seen part of the graph, coloured by contribution level
    G = grid(state)
    M = state["map"]
    m = min(6.0, 300 / state["w"], 96 / state["h"])
    mw, mh = state["w"] * m, state["h"] * m
    mx, my = VX + VPW - 10 - mw, VY + 10
    mfill = {"#": "#155c2e", "1": "#1d6b3a", "2": "#28a352", "3": "#39d96c", "4": "#b4ffd2", ".": "#0c2414"}
    mm = [f'<rect x="{mx - 5:.1f}" y="{my - 5:.1f}" width="{mw + 10:.1f}" height="{mh + 19:.1f}" fill="#050a06" opacity=".9" stroke="#155c2e"/>']
    for y in range(state["h"]):
        x, row = 0, state["seen"][y]
        while x < state["w"]:
            if row[x] != "1":
                x += 1; continue
            kind, x2 = M[y][x], x
            while x2 < state["w"] and row[x2] == "1" and M[y][x2] == kind:
                x2 += 1
            mm.append(f'<rect x="{mx + x * m:.1f}" y="{my + y * m:.1f}" width="{(x2 - x) * m:.1f}" height="{m:.1f}" fill="{mfill[kind]}"/>')
            x = x2
    me = (p["x"], p["y"])
    if not state["enemies"] and state["seen"][state["portal"][1]][state["portal"][0]] == "1":
        mm.append(f'<rect x="{mx + state["portal"][0] * m - 1:.1f}" y="{my + state["portal"][1] * m - 1:.1f}" width="{m + 2:.1f}" height="{m + 2:.1f}" class="pt" fill="#e6fff0"/>')
    for e in state["enemies"]:
        if math.dist((e["x"], e["y"]), me) <= SENSE_LOS and los(G, (e["x"], e["y"]), me):
            mm.append(f'<circle cx="{mx + (e["x"] + .5) * m:.1f}" cy="{my + (e["y"] + .5) * m:.1f}" r="{max(m * .6, 2):.1f}" fill="{TONES[tone_of(e["lang"])]}"/>')
    pcx, pcy = mx + (p["x"] + .5) * m, my + (p["y"] + .5) * m
    cone, s_ = 7 * m, max(m, 3.2)
    mm.append(f'<g transform="translate({pcx:.1f},{pcy:.1f}) rotate({p["facing"] * 45})">'
              f'<path d="M0,0 L{cone:.1f},{-cone * TANH:.1f} L{cone:.1f},{cone * TANH:.1f}Z" fill="#7dffb0" opacity=".16"/>'
              f'<path d="M{s_ * .9:.1f},0 L{-s_ * .6:.1f},{-s_ * .6:.1f} L{-s_ * .25:.1f},0 L{-s_ * .6:.1f},{s_ * .6:.1f}Z" fill="#e6fff0"/></g>')
    seen_pct = sum(r.count("1") for r in state["seen"]) * 100 // (state["w"] * state["h"])
    mm.append(txt(mx, my + mh + 11, f'map · {seen_pct}% seen', 8.5, "m"))
    mm.append(txt(mx + mw, my + mh + 11, 'less <tspan fill="#1d6b3a">■</tspan><tspan fill="#28a352">■</tspan><tspan fill="#39d96c">■</tspan><tspan fill="#b4ffd2">■</tspan> more', 8.5, "m", "end"))
    body.append("".join(mm))

    # overlays: damage flash, level banners
    if last.get("bitten") and not last.get("died"):
        body.append(f'<rect x="{VX}" y="{VY}" width="{VPW}" height="{VPH:.1f}" fill="url(#hurt)" class="dmg"/>')
        body.append(txt(VX + 14, VY + 26, f'-{last["bitten"]} HP', 17, "r dmg lb"))
    if last.get("died") or last.get("cleared"):
        if last.get("died"):
            big, small, cls = "SEGMENTATION FAULT", f"(core dumped) · level {state['level']} restarts · -5 for @{last['user']}", "r"
        else:
            big, small, cls = f"LEVEL {last['cleared']:02d} SHIPPED", f"@{last['user']} took the portal · +30 · level {state['level']} loading", "k"
        bw = 540
        body.append(f'<g class="ban"><rect x="{cx - bw / 2}" y="{cy - 46}" width="{bw}" height="84" fill="#050a06" opacity=".92" stroke="{"#ff4d6d" if cls == "r" else "#39ff7a"}"/>'
                    + txt(cx, cy - 6, big, 28, cls, "middle") + txt(cx, cy + 22, escape(small), 12, "d", "middle") + "</g>")

    # 4 · HUD bar
    hp = max(p["hp"], 0)
    seg = 20
    filled = math.ceil(hp / HP_MAX * seg)
    hpc = "#39ff7a" if hp > 50 else "#ffd166" if hp > 25 else "#ff4d6d"
    hy = HUD_Y + 20
    body.append(f'<rect x="24" y="{HUD_Y}" width="892" height="32" fill="#0a120c" stroke="#155c2e"/>')
    body.append(txt(36, hy, "HP", 13, "k"))
    body.append("".join(f'<rect x="{62 + i * 7}" y="{hy - 11}" width="5" height="13" fill="{hpc if i < filled else "#10301c"}"/>' for i in range(seg)))
    body.append(txt(208, hy, f'<tspan fill="{hpc}">{hp:>3}</tspan>', 13, "w"))
    killed = state["enemies_total"] - len(state["enemies"])
    stats = [("MERGED", f'{killed}/{state["enemies_total"]}'), ("REPOS", f'{len(state["enemies"])}'), ("LVL", f'{state["level"]:02d}'), ("TURN", f'{state["turn"]}')]
    x = 248
    for k, v in stats:
        body.append(txt(x, hy, f'<tspan class="m">{k}</tspan> <tspan class="w">{v}</tspan>', 13, "g"))
        x += (len(k) + len(v) + 1) * 13 * CW + 18
    if not state["enemies"]:
        body.append(txt(x, hy, '<tspan class="pt">▣ PORTAL OPEN</tspan>', 13, "g"))
    if last:
        sign = f'+{last["points"]}' if last["points"] >= 0 else str(last["points"])
        body.append(txt(904, hy, f'<tspan class="m">&gt;</tspan> @{escape(trunc(last["user"], 13))} <tspan class="k">{LABEL_SVG[last["action"]]}</tspan>'
                                 f' <tspan class="d">{escape(trunc(plain(short_result(last)), 19))}</tspan> <tspan class="{"k" if last["points"] >= 0 else "r"}">{sign}</tspan>', 12, "g", "end"))
    else:
        body.append(txt(904, hy, '<tspan class="m">&gt;</tspan> awaiting first striker<tspan class="cur">_</tspan>', 12, "d", "end"))

    # 5 · panel: leaderboard · last moves · rules
    py0 = PANEL_Y
    body.append(txt(24, py0 + 12, "▌TOP 5 STRIKERS", 11, "k"))
    body.append(txt(320, py0 + 12, "▌LAST MOVES", 11, "k"))
    body.append(txt(712, py0 + 12, "▌HOW TO PLAY", 11, "k"))
    top = sorted(state["players"].items(), key=lambda kv: (-kv[1]["score"], -kv[1]["kills"], kv[0]))[:5]
    best = max([v["score"] for _, v in top] + [1])
    for i, (u, v) in enumerate(top):
        y = py0 + 34 + i * 17
        body.append(txt(24, y, f'<tspan class="m">{i + 1:02d}</tspan> <tspan class="{"w" if i == 0 else "g"}">@{escape(trunc(u, 15))}</tspan>', 11.5, "g"))
        bw = max(2, 80 * max(v["score"], 0) / best)
        body.append(f'<rect x="186" y="{y - 8}" width="{bw:.0f}" height="7" fill="{"#39ff7a" if i == 0 else "#1f9e4a"}" opacity=".8"/>')
        body.append(txt(304, y, f'{v["score"]}', 11.5, "w", "end"))
    if not top:
        body.append(txt(24, py0 + 34, "no strikers yet", 11.5, "d"))
        body.append(txt(24, py0 + 51, "be the first ↓", 11.5, "m"))
    hist = state["history"][-5:][::-1]
    for i, hh in enumerate(hist):
        y = py0 + 34 + i * 17
        t = hh["time"][5:16].replace("T", " ")
        sign = f'+{hh["points"]}' if hh["points"] >= 0 else str(hh["points"])
        res = plain(hh["result"])
        body.append(txt(320, y, t, 11.5, "m"))
        body.append(txt(403, y, f'@{escape(trunc(hh["user"], 12))}', 11.5, "g"))
        body.append(txt(500, y, LABEL_SVG[hh["action"]], 11.5, "k"))
        body.append(txt(562, y, escape(trunc(res, 15)), 11.5, "d"))
        body.append(txt(696, y, sign, 11.5, "w" if hh["points"] >= 0 else "r", "end"))
    if not hist:
        body.append(txt(320, py0 + 34, "the graph is quiet… for now", 11.5, "d"))
    rules = [("walls", "your contribution days"), ("enemies", "your public repos"), ("fire", "1 dmg · 2 point blank"),
             ("turn", "45° · move 1 tile"), ("score", "+1 act +10 merge +30 exit")]
    for i, (k, v) in enumerate(rules):
        body.append(txt(712, py0 + 34 + i * 17, f'<tspan class="g">{k:<7}</tspan> <tspan class="m">{v}</tspan>', 10, "g"))
    body.append("</g>")

    # CRT overlay
    body += [f'<rect width="{W}" height="{H}" rx="14" fill="url(#scan)"/>',
             f'<g clip-path="url(#card)"><rect class="roll" width="{W}" height="70" fill="#39ff7a" opacity=".035"/></g>',
             f'<rect width="{W}" height="{H}" rx="14" fill="url(#vig)"/>']
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="{FONT}" role="img" aria-label="commit//strike level {state["level"]}: first-person ASCII shooter inside a contribution graph">'
            f'<style>{"".join(css)}</style><defs>{"".join(defs)}</defs>{"".join(body)}</svg>')


# ── README section ───────────────────────────────────────────────────
def issue_url(repo, action):
    return f"https://github.com/{repo}/issues/new?title={quote(PREFIX + '|' + action, safe='')}&body={quote_plus(BODY)}"

def md_cell(s):
    return str(s).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")

def readme_section(state, repo):
    def key(action, label, tip):
        return f'<a href="{issue_url(repo, action)}" title="{tip}"><kbd>&nbsp;{label}&nbsp;</kbd></a>'
    pad = ("<table>\n"
           f'  <tr><td align="center">{key("left", "↺", "turn 45° left")}</td><td align="center">{key("fwd", "⬆", "step forward")}</td><td align="center">{key("right", "↻", "turn 45° right")}</td></tr>\n'
           f'  <tr><td align="center">{key("strafe-left", "⇠", "strafe left")}</td><td align="center">{key("back", "⬇", "step back")}</td><td align="center">{key("strafe-right", "⇢", "strafe right")}</td></tr>\n'
           f'  <tr><td align="center" colspan="3">{key("fire", "🔫 FIRE", "fire")}</td></tr>\n'
           "</table>")
    hist = state["history"][-5:][::-1]
    if hist:
        table = "| striker | action | result |\n|:--|:--|:--|\n" + "\n".join(
            f'| [@{h["user"]}](https://github.com/{h["user"]}) | {LABEL_MD[h["action"]]} | {md_cell(h["result"])} ({"+" if h["points"] >= 0 else ""}{h["points"]}) |'
            for h in hist)
    else:
        table = "_No moves yet. The repos are waiting for you._"
    return (f'<div align="center">\n\n<img src="game/board.svg?v={state["moves"]}" width="100%" alt="commit//strike">\n\n'
            f"{pad}\n\n"
            "<sub><b>How it works:</b> click a key → GitHub opens a pre-filled issue → press <b>Submit new issue</b>. "
            "A GitHub Action plays your turn inside my contribution graph, my repos crawl closer, the board updates and your issue is closed (~30 s). "
            "+1 per action · +10 per merged repo · +30 for the exit portal.</sub>\n\n"
            f"{table}\n\n</div>")

def update_readme(state, path, repo):
    if not os.path.exists(path):
        print(f"warning: {path} not found, README not updated", file=sys.stderr)
        return False
    text = open(path, encoding="utf-8").read()
    a, b = "<!-- GAME:START -->", "<!-- GAME:END -->"
    i, j = text.find(a), text.find(b)
    if i < 0 or j < i:
        print("warning: README has no <!-- GAME:START --> / <!-- GAME:END --> markers, skipped", file=sys.stderr)
        return False
    new = text[:i + len(a)] + "\n" + readme_section(state, repo) + "\n" + text[j:]
    if new != text:
        open(path, "w", encoding="utf-8").write(new)
    return True


# ── I/O ──────────────────────────────────────────────────────────────
def save(state, paths, repo):
    os.makedirs(os.path.dirname(paths.state), exist_ok=True)
    with open(paths.state, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, ensure_ascii=False)
        f.write("\n")
    svg = render(state)
    open(paths.board, "w", encoding="utf-8").write(svg)
    update_readme(state, paths.readme, repo)
    return svg

def load(paths):
    return json.load(open(paths.state, encoding="utf-8"))

def repo_name():
    return os.environ.get("GITHUB_REPOSITORY") or "mustafazahter/mustafazahter"


# ── selftest ─────────────────────────────────────────────────────────
def check(state):
    G = grid(state)
    p = state["player"]
    assert floor(G, p["x"], p["y"]), "striker inside a wall"
    assert 0 < p["hp"] <= HP_MAX, "hp out of range"
    seen = set()
    for e in state["enemies"]:
        assert floor(G, e["x"], e["y"]), "enemy inside a wall"
        assert (e["x"], e["y"]) != (p["x"], p["y"]), "enemy on the striker"
        assert (e["x"], e["y"]) not in seen, "two enemies on one tile"
        assert 0 < e["hp"] <= e["max"] <= 4
        seen.add((e["x"], e["y"]))
    assert floor(G, *state["portal"]), "portal inside a wall"
    assert len(bfs(G, tuple(state["start"]))) == sum(r.count(".") for r in state["map"]), "arena not connected"
    assert sum(v["score"] for v in state["players"].values()) == state["points"], "scores don't add up"
    assert sum(v["actions"] for v in state["players"].values()) == state["moves"], "action counts don't add up"
    assert len(state["history"]) <= 8

def autopilot(state):
    """A simple striker: shoot what's in the crosshair, else walk to the nearest repo (or the portal)."""
    G = grid(state)
    p = state["player"]
    if state["enemies"] and target(state, G):
        return "fire"
    me = (p["x"], p["y"])
    goals = {(e["x"], e["y"]) for e in state["enemies"]} or {tuple(state["portal"])}
    prev = {me: None}
    q = deque([me])
    goal = None
    while q:
        c = q.popleft()
        if c in goals:
            goal = c; break
        for dx, dy in DIR8[0::2]:
            n = (c[0] + dx, c[1] + dy)
            if n not in prev and floor(G, *n):
                prev[n] = c; q.append(n)
    if goal is None or goal == me:
        return "fire"
    step = goal
    while prev[step] != me:
        step = prev[step]
    diff = (DIR8.index((step[0] - me[0], step[1] - me[1])) - p["facing"]) % 8
    if diff == 0:
        return "fire" if enemy_at(state, *step) else "fwd"
    return "right" if diff <= 4 else "left"

def selftest_run(assets, label):
    import xml.dom.minidom
    with tempfile.TemporaryDirectory() as tmp:
        paths = Paths(tmp, assets)
        os.makedirs(os.path.join(tmp, "game"))
        open(paths.readme, "w").write("# hi\n<!-- GAME:START -->\nold\n<!-- GAME:END -->\nbye\n")
        st = new_state(1234, assets)
        save(st, paths, "someone/repo")
        check(st)
        rnd = random.Random(7)
        users = ["alice", "bob", "carol", "dave", "eve-1"]
        for i in range(400):                                   # 1) random play
            ok, msg = play(st, rnd.choice(users), f"{PREFIX}|" + rnd.choice(ACTIONS), assets)
            assert ok and msg
            check(st)
            if i % 50 == 0:
                xml.dom.minidom.parseString(render(st))
        snap = json.dumps(st, sort_keys=True)                  # 2) bad titles change nothing
        for bad in ["", "hello", f"{PREFIX}|jump", "robot|move|up", PREFIX, "bughunt|fire"]:
            ok, msg = play(st, "mallory", bad, assets)
            assert not ok and f"{PREFIX}|fire" in msg
        assert json.dumps(st, sort_keys=True) == snap, "bad title changed the state"
        start_level, steps = st["level"], 0                    # 3) a competent striker clears levels
        while st["level"] < start_level + 2 and steps < 8000:
            play(st, rnd.choice(users), f"{PREFIX}|" + autopilot(st), assets)
            check(st)
            if steps % 200 == 0:
                xml.dom.minidom.parseString(render(st))
            steps += 1
        assert st["level"] >= start_level + 2, f"levels did not advance ({st['level']} after {steps} turns)"
        assert st["cleared"], "no clear recorded"
        lvl, before = st["level"], st["points"]                # 4) death restarts the level, -5
        G = grid(st)
        p = st["player"]
        p["hp"] = 1
        nb = next((p["x"] + dx, p["y"] + dy) for dx, dy in DIR8[0::2] if floor(G, p["x"] + dx, p["y"] + dy))
        st["enemies"] = [e for e in st["enemies"] if (e["x"], e["y"]) != nb][:1] or [dict(id=99, x=0, y=0, hp=2, max=2, name="x", lang="-")]
        st["enemies"][0].update(x=nb[0], y=nb[1])
        p["facing"] = (DIR8.index((nb[0] - p["x"], nb[1] - p["y"])) + 4) % 8
        ok, msg = play(st, "zed", f"{PREFIX}|left", assets)
        assert ok and st["last"]["died"] and st["level"] == lvl and st["player"]["hp"] == HP_MAX
        assert st["points"] == before + PTS_ACTION + PTS_DEATH
        check(st)
        svg = save(st, paths, "someone/repo")                  # 5) files + README round-trip
        xml.dom.minidom.parseString(svg)
        assert len(svg) < 180_000, f"board too big: {len(svg)} bytes"
        text = open(paths.readme).read()
        assert f"{PREFIX}%7Cfire" in text and "old" not in text and text.endswith("bye\n")
        open(paths.readme, "w").write("no markers here\n")
        assert update_readme(st, paths.readme, "x/y") is False
        print(f"selftest ok [{label}]: {st['moves']} turns, level {st['level']}, {len(st['players'])} players, "
              f"{st['points']} points, {st['deaths']} deaths, board {len(svg) // 1024} KB")

def selftest():
    real = os.path.join(ROOT, "assets")
    if os.path.exists(os.path.join(real, "stats.json")):
        selftest_run(real, "contribution arena + repos")
    with tempfile.TemporaryDirectory() as empty:
        selftest_run(empty, "fallback maze + bugs")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--init", action="store_true")
    g.add_argument("--play", action="store_true")
    g.add_argument("--render", action="store_true")
    g.add_argument("--selftest", action="store_true")
    ap.add_argument("--seed", type=lambda s: int(s, 0))
    ap.add_argument("--root", default=ROOT, help="repo root (for testing on a scratch copy)")
    ap.add_argument("--assets", default=None, help="assets dir (default <root>/assets)")
    a = ap.parse_args()
    paths, repo = Paths(a.root, a.assets), repo_name()
    if a.selftest:
        selftest()
    elif a.init:
        st = new_state(a.seed if a.seed is not None else random.SystemRandom().randrange(1 << 32), paths.assets)
        svg = save(st, paths, repo)
        print(f"new game: seed {st['seed']:08x}, level 1 ({st['arena']}: {st['arena_label']}), "
              f"{len(st['enemies'])} enemies, board {len(svg) // 1024} KB")
    elif a.render:
        svg = save(load(paths), paths, repo)
        print(f"rendered board {len(svg) // 1024} KB")
    else:
        st = load(paths)
        ok, msg = play(st, os.environ.get("ISSUE_AUTHOR"), os.environ.get("ISSUE_TITLE"), paths.assets)
        if ok:
            save(st, paths, repo)
        out = os.environ.get("RESULT_FILE") or os.path.join(paths.root, "game", "last_result.md")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        open(out, "w", encoding="utf-8").write(msg + f"\n\n[↩ back to the board](https://github.com/{repo}#readme)\n")
        print(msg)


if __name__ == "__main__":
    main()
