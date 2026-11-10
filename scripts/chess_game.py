"""Issue-driven chess for the profile README: visitors play White, zahter.bot answers as Black.

    python3 scripts/chess_game.py --init        # fresh game, writes game/state.json + game/board.svg + README section
    python3 scripts/chess_game.py --play        # env ISSUE_TITLE, ISSUE_AUTHOR, RESULT_FILE
    python3 scripts/chess_game.py --selftest    # plays bot-vs-random games on a temp copy

Needs `chess` (python-chess) for the rules. Everything else is standard library.
Issue titles:  chess|move|e2e4   chess|move|Nf3   chess|new
"""
import argparse, json, os, random, re, shutil, sys, tempfile, time
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote

import chess

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REPO = os.environ.get("GITHUB_REPOSITORY", "mustafazahter/mustafazahter")
BOT = "zahter.bot"
PREFIX = "chess"
FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
GLYPH = {chess.KING: "♚", chess.QUEEN: "♛", chess.ROOK: "♜", chess.BISHOP: "♝", chess.KNIGHT: "♞", chess.PAWN: "♟"}
WHITE_GLYPH = {chess.KING: "♔", chess.QUEEN: "♕", chess.ROOK: "♖", chess.BISHOP: "♗", chess.KNIGHT: "♘", chess.PAWN: "♙"}
NAME = {chess.KING: "king", chess.QUEEN: "queen", chess.ROOK: "rook", chess.BISHOP: "bishop", chess.KNIGHT: "knight", chess.PAWN: "pawn"}


def paths(root=ROOT):
    return {"state": os.path.join(root, "game", "state.json"), "board": os.path.join(root, "game", "board.svg"),
            "readme": os.path.join(root, "README.md")}


# ── engine: small alpha-beta with piece-square tables ────────────────
VAL = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330, chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}
PST = {  # from White's point of view, a8..h1 order flipped below
    chess.PAWN: [0, 0, 0, 0, 0, 0, 0, 0, 50, 50, 50, 50, 50, 50, 50, 50, 10, 10, 20, 30, 30, 20, 10, 10, 5, 5, 10, 25, 25, 10, 5, 5,
                 0, 0, 0, 20, 20, 0, 0, 0, 5, -5, -10, 0, 0, -10, -5, 5, 5, 10, 10, -20, -20, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0],
    chess.KNIGHT: [-50, -40, -30, -30, -30, -30, -40, -50, -40, -20, 0, 0, 0, 0, -20, -40, -30, 0, 10, 15, 15, 10, 0, -30, -30, 5, 15, 20, 20, 15, 5, -30,
                   -30, 0, 15, 20, 20, 15, 0, -30, -30, 5, 10, 15, 15, 10, 5, -30, -40, -20, 0, 5, 5, 0, -20, -40, -50, -40, -30, -30, -30, -30, -40, -50],
    chess.BISHOP: [-20, -10, -10, -10, -10, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10, -10, 0, 5, 10, 10, 5, 0, -10, -10, 5, 5, 10, 10, 5, 5, -10,
                   -10, 0, 10, 10, 10, 10, 0, -10, -10, 10, 10, 10, 10, 10, 10, -10, -10, 5, 0, 0, 0, 0, 5, -10, -20, -10, -10, -10, -10, -10, -10, -20],
    chess.ROOK: [0, 0, 0, 0, 0, 0, 0, 0, 5, 10, 10, 10, 10, 10, 10, 5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5,
                 -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, 0, 0, 0, 5, 5, 0, 0, 0],
    chess.QUEEN: [-20, -10, -10, -5, -5, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10, -10, 0, 5, 5, 5, 5, 0, -10, -5, 0, 5, 5, 5, 5, 0, -5,
                  0, 0, 5, 5, 5, 5, 0, -5, -10, 5, 5, 5, 5, 5, 0, -10, -10, 0, 5, 0, 0, 0, 0, -10, -20, -10, -10, -5, -5, -10, -10, -20],
    chess.KING: [-30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30,
                 -20, -30, -30, -40, -40, -30, -30, -20, -10, -20, -20, -20, -20, -20, -20, -10, 20, 20, 0, 0, 0, 0, 20, 20, 20, 30, 10, 0, 0, 10, 30, 20],
}


def evaluate(b):
    """Score from White's point of view, centipawns."""
    if b.is_checkmate():
        return -100000 if b.turn == chess.WHITE else 100000
    if b.is_stalemate() or b.is_insufficient_material():
        return 0
    s = 0
    for sq, p in b.piece_map().items():
        idx = (7 - chess.square_rank(sq)) * 8 + chess.square_file(sq) if p.color == chess.WHITE else chess.square_rank(sq) * 8 + chess.square_file(sq)
        v = VAL[p.piece_type] + PST[p.piece_type][idx]
        s += v if p.color == chess.WHITE else -v
    return s


def ordered(b):
    def key(m):
        k = 0
        if b.is_capture(m):
            victim = b.piece_at(m.to_square)
            k += 10 * (VAL[victim.piece_type] if victim else 100) - VAL[b.piece_at(m.from_square).piece_type] // 10
        if m.promotion:
            k += 800
        return -k
    return sorted(b.legal_moves, key=key)


def quiesce(b, alpha, beta, color, deadline, depth=0):
    stand = color * evaluate(b)
    if stand >= beta or depth > 4 or time.time() > deadline:
        return stand
    alpha = max(alpha, stand)
    for m in ordered(b):
        if not b.is_capture(m):
            continue
        b.push(m)
        sc = -quiesce(b, -beta, -alpha, -color, deadline, depth + 1)
        b.pop()
        if sc >= beta:
            return sc
        alpha = max(alpha, sc)
    return alpha


def negamax(b, depth, alpha, beta, color, deadline):
    if b.is_game_over():
        return color * evaluate(b) - (depth if b.is_checkmate() else 0)
    if depth == 0:
        return quiesce(b, alpha, beta, color, deadline)
    best = -10 ** 9
    for m in ordered(b):
        b.push(m)
        sc = -negamax(b, depth - 1, -beta, -alpha, -color, deadline)
        b.pop()
        best = max(best, sc)
        alpha = max(alpha, sc)
        if alpha >= beta or time.time() > deadline:
            break
    return best


def bot_move(b, seed, think=4.0, max_depth=3):
    """Iterative deepening; picks randomly among moves within 12 cp of the best, so games vary."""
    rnd = random.Random(seed)
    color = 1 if b.turn == chess.WHITE else -1
    deadline = time.time() + think
    scores = {}
    for depth in range(1, max_depth + 1):
        cur = {}
        for m in ordered(b):
            b.push(m)
            cur[m] = -negamax(b, depth - 1, -10 ** 9, 10 ** 9, -color, deadline)
            b.pop()
            if time.time() > deadline:
                break
        if len(cur) == b.legal_moves.count():
            scores = cur
        if time.time() > deadline:
            break
    if not scores:
        scores = {m: 0 for m in b.legal_moves}
    best = max(scores.values())
    pool = [m for m, s in scores.items() if s >= best - 12]
    m = rnd.choice(sorted(pool, key=lambda x: x.uci()))
    return m, color * best  # eval from White's view after the bot's best line


# ── state ─────────────────────────────────────────────────────────────
def new_state(prev=None):
    st = {"game": "chess", "version": 1, "fen": chess.STARTING_FEN, "plies": [], "game_no": 1,
          "players": {}, "results": [], "history": [], "last": None, "eval": 0, "turns": 0}
    if prev:
        for k in ("players", "results", "history", "turns"):
            st[k] = prev.get(k, st[k])
        st["game_no"] = prev.get("game_no", 0) + 1
    return st


def load(p):
    try:
        st = json.load(open(p["state"]))
        if st.get("game") == "chess":
            return st
    except (OSError, ValueError):
        pass
    return new_state()


def board_of(st):
    b = chess.Board()
    for u in st["plies"]:
        b.push_uci(u["uci"])
    return b


def outcome_text(b):
    if b.is_checkmate():
        return ("checkmate — White wins", "white") if b.turn == chess.BLACK else (f"checkmate — {BOT} wins", "black")
    if b.is_stalemate():
        return ("stalemate — draw", "draw")
    if b.is_insufficient_material():
        return ("insufficient material — draw", "draw")
    if b.can_claim_threefold_repetition():
        return ("threefold repetition — draw", "draw")
    if b.can_claim_fifty_moves():
        return ("fifty-move rule — draw", "draw")
    return None


def game_over(b):
    return outcome_text(b) is not None


def parse(title, b):
    parts = [x.strip() for x in (title or "").split("|")]
    if len(parts) < 2 or parts[0].lower() != PREFIX:
        return None, None
    if parts[1].lower() == "new":
        return "new", None
    if parts[1].lower() != "move" or len(parts) < 3:
        return None, None
    raw = parts[2].replace(" ", "")
    try:
        return "move", b.parse_uci(raw.lower())
    except ValueError:
        pass
    try:
        return "move", b.parse_san(raw)
    except ValueError:
        return "bad", None


def clean_user(u):
    return re.sub(r"[^A-Za-z0-9-]", "", (u or "").replace("[bot]", ""))[:39] or "anonymous"


def ply_record(b, m, who):
    cap = b.piece_at(m.to_square)
    ep = b.is_en_passant(m)
    rec = {"uci": m.uci(), "san": b.san(m), "by": who, "from": m.from_square, "to": m.to_square,
           "piece": b.piece_at(m.from_square).symbol(),
           "captured": (cap.symbol() if cap else ("p" if ep and b.turn == chess.WHITE else "P" if ep else None)),
           "cap_sq": (m.to_square + (-8 if b.turn == chess.WHITE else 8)) if ep else (m.to_square if cap else None),
           "castle": None}
    if b.is_castling(m):
        rank = chess.square_rank(m.from_square)
        if chess.square_file(m.to_square) == 6:
            rec["castle"] = [chess.square(7, rank), chess.square(5, rank)]
        else:
            rec["castle"] = [chess.square(0, rank), chess.square(3, rank)]
    return rec


def play(st, user, title, think=4.0):
    """Apply one issue. Returns (changed, markdown message)."""
    user = clean_user(user)
    b = board_of(st)
    kind, m = parse(title, b)
    nice = re.sub(r"[`@<>]", "", (title or "")[:60])
    if kind is None or kind == "bad":
        legal = ", ".join(f"`{b.san(x)}`" for x in list(b.legal_moves)[:12])
        return False, (f"🤔 Sorry @{user}, I couldn't read `{nice}` as a legal move.\n\n"
                       f"Use the move links under the board on the [profile](https://github.com/{REPO}). Some legal moves right now: {legal}")
    if kind == "new":
        if not game_over(b) and st["plies"]:
            return False, f"♟ @{user}, game #{st['game_no']} is still on — finish it first (or win it 😉)."
        prev = dict(st)
        st.clear(); st.update(new_state(prev))
        st["last"] = {"user": user, "event": "new"}
        st["turns"] += 1
        return True, f"♻ @{user} started game #{st['game_no']}. You play White — [make the first move](https://github.com/{REPO})."
    if game_over(b):
        return False, f"🏁 @{user}, game #{st['game_no']} is over ({outcome_text(b)[0]}). Start a new one with the ♻ link on the profile."
    if m not in b.legal_moves:
        return False, f"🚫 @{user}, `{nice}` is not legal here. Pick one of the links under the board."

    p = st["players"].setdefault(user, {"moves": 0, "captures": 0, "checks": 0, "wins": 0, "points": 0})
    rec = ply_record(b, m, user)
    b.push(m)
    st["plies"].append(rec)
    p["moves"] += 1; p["points"] += 1
    note = []
    if rec["captured"]:
        p["captures"] += 1; p["points"] += 3
        note.append(f"captured a {NAME[chess.Piece.from_symbol(rec['captured']).piece_type]}")
    if b.is_check():
        p["checks"] += 1; p["points"] += 2
        note.append("check!")
    reply = None
    if not game_over(b):
        bm, ev = bot_move(b, seed=f"{st['game_no']}-{len(st['plies'])}", think=think)
        brec = ply_record(b, bm, BOT)
        b.push(bm)
        st["plies"].append(brec)
        st["eval"] = ev
        reply = brec
    end = outcome_text(b)
    if end:
        if end[1] == "white":
            p["wins"] += 1; p["points"] += 20
        st["results"].append({"game": st["game_no"], "result": end[1], "text": end[0], "plies": len(st["plies"]),
                              "by": user, "at": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
    st["turns"] += 1
    st["last"] = {"user": user, "event": "move", "white": rec["san"], "black": reply["san"] if reply else None,
                  "end": end[0] if end else None}
    st["history"] = ([{"user": user, "white": rec["san"], "black": reply["san"] if reply else "—",
                       "n": (len(st["plies"]) + 1) // 2, "at": datetime.now(timezone.utc).strftime("%m-%d %H:%M")}]
                     + st["history"])[:8]
    st["fen"] = b.fen()
    msg = f"♟ **@{user}** played **{rec['san']}**" + (f" ({', '.join(note)})" if note else "")
    if reply:
        msg += f"\n\n🤖 **{BOT}** answered **{reply['san']}**" + (" — check!" if b.is_check() else "")
    if end:
        msg += f"\n\n🏁 **{end[0]}**" + (" — congratulations! +20" if end[1] == "white" else "") + \
               f"\n\nStart the next game with the ♻ link on the [profile](https://github.com/{REPO})."
    else:
        msg += f"\n\nYour score: **{p['points']}** · [back to the board](https://github.com/{REPO})"
    return True, msg


# ── board svg ─────────────────────────────────────────────────────────
def render(st):
    b = board_of(st)
    W, H = 940, 600
    S = 56                      # square size
    BX, BY = 52, 92             # board origin (a8 top-left)
    css = (
        ".d{fill:#1f9e4a}.g{fill:#39ff7a}.k{fill:#7dffb0;font-weight:700}.m{fill:#155c2e}.w{fill:#e6fff0}.a{fill:#ffb000}.r{fill:#ff5f57}"
        ".pw{fill:#eafff1}.pb{fill:#ffb000}"
        ".sl{animation:sl .75s cubic-bezier(.3,.7,.2,1) backwards}@keyframes sl{from{transform:translate(var(--dx),var(--dy))}}"
        ".gone{animation:gone .2s forwards}@keyframes gone{to{opacity:0}}"
        ".chk{animation:chk 1.4s ease-in-out infinite alternate}@keyframes chk{from{fill-opacity:.15}to{fill-opacity:.55}}"
        ".cur{animation:bl 1.05s steps(1) infinite}@keyframes bl{50%{opacity:0}}"
        "@media (prefers-reduced-motion:reduce){*{animation-duration:0s!important;animation-delay:0s!important}}"
    )
    defs = ('<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="#000" opacity=".25"/></pattern>'
            '<filter id="glow" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="1.3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
            '<radialGradient id="vig" cx="50%" cy="50%" r="75%"><stop offset="62%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".65"/></radialGradient>'
            f'<clipPath id="card"><rect width="{W}" height="{H}" rx="14"/></clipPath>')
    o = []
    o.append(f'<rect width="{W}" height="{H}" rx="14" fill="#050a06"/><rect width="{W}" height="36" fill="#0c140e" clip-path="url(#card)"/>'
             '<circle cx="22" cy="18" r="6" fill="#ff5f57"/><circle cx="42" cy="18" r="6" fill="#febc2e"/><circle cx="62" cy="18" r="6" fill="#28c840"/>'
             f'<text x="{W / 2}" y="23" font-size="12" text-anchor="middle" class="d">chess — you (white) vs {BOT} (black) · game #{st["game_no"]}</text>')
    o.append('<g filter="url(#glow)">')
    o.append(f'<text x="24" y="64" font-size="13" class="g" xml:space="preserve"><tspan class="d">➜</tspan> <tspan class="k">~</tspan> git chess --you=white --vs={BOT} '
             f'<tspan class="m"># every issue is one move</tspan></text>')

    # squares + coordinates
    last_w = st["plies"][-2] if len(st["plies"]) >= 2 and st["plies"][-1]["by"] == BOT else (st["plies"][-1] if st["plies"] else None)
    last_b = st["plies"][-1] if st["plies"] and st["plies"][-1]["by"] == BOT else None
    hi_w = {last_w["from"], last_w["to"]} if last_w else set()
    hi_b = {last_b["from"], last_b["to"]} if last_b else set()

    def xy(sq):
        return BX + chess.square_file(sq) * S, BY + (7 - chess.square_rank(sq)) * S

    for sq in chess.SQUARES:
        x, y = xy(sq)
        light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
        fill = "#13361f" if light else "#0a1e11"
        o.append(f'<rect x="{x}" y="{y}" width="{S}" height="{S}" fill="{fill}"/>')
        if sq in hi_b:
            o.append(f'<rect x="{x + 1}" y="{y + 1}" width="{S - 2}" height="{S - 2}" fill="#ffb000" fill-opacity=".14" stroke="#ffb000" stroke-opacity=".55"/>')
        elif sq in hi_w:
            o.append(f'<rect x="{x + 1}" y="{y + 1}" width="{S - 2}" height="{S - 2}" fill="#39ff7a" fill-opacity=".12" stroke="#39ff7a" stroke-opacity=".5"/>')
    o.append(f'<rect x="{BX - .5}" y="{BY - .5}" width="{8 * S + 1}" height="{8 * S + 1}" fill="none" stroke="#1f9e4a" stroke-opacity=".7"/>')
    for i in range(8):
        o.append(f'<text x="{BX + i * S + S / 2}" y="{BY + 8 * S + 17}" font-size="11" text-anchor="middle" class="m">{"abcdefgh"[i]}</text>')
        o.append(f'<text x="{BX - 14}" y="{BY + i * S + S / 2 + 4}" font-size="11" text-anchor="middle" class="m">{8 - i}</text>')
    o.append("</g>")

    # check glow under the king in check (one small infinite animation, outside the filter)
    if b.is_check():
        kx, ky = xy(b.king(b.turn))
        o.append(f'<rect class="chk" x="{kx + 2}" y="{ky + 2}" width="{S - 4}" height="{S - 4}" rx="6" fill="#ff3b30" stroke="#ff5f57"/>')

    # pieces; the last two moves slide in from where they came from
    t_w, t_b = 0.35, 1.35
    slides = {}
    for rec, t in ((last_w, t_w), (last_b, t_b)):
        if not rec:
            continue
        slides[rec["to"]] = (rec["from"], t)
        if rec.get("castle"):
            slides[rec["castle"][1]] = (rec["castle"][0], t)
    ghosts = []
    for rec, t in ((last_w, t_w), (last_b, t_b)):
        if rec and rec.get("captured") is not None and rec.get("cap_sq") is not None:
            ghosts.append((rec["cap_sq"], rec["captured"], t + .55))
    pieces = []
    for sq, pc in b.piece_map().items():
        x, y = xy(sq)
        cls = "pw" if pc.color == chess.WHITE else "pb"
        st_ = ""
        if sq in slides:
            fsq, t = slides[sq]
            fx, fy = xy(fsq)
            st_ = f' style="--dx:{fx - x}px;--dy:{fy - y}px;animation-delay:{t:.2f}s"'
            cls += " sl"
        pieces.append(f'<text x="{x + S / 2}" y="{y + S * .74:.1f}" font-size="{S * .74:.1f}" text-anchor="middle" class="{cls}"{st_}>{GLYPH[pc.piece_type]}</text>')
    for sq, sym, t in ghosts:
        x, y = xy(sq)
        p = chess.Piece.from_symbol(sym)
        cls = "pw" if p.color == chess.WHITE else "pb"
        pieces.insert(0, f'<text x="{x + S / 2}" y="{y + S * .74:.1f}" font-size="{S * .74:.1f}" text-anchor="middle" class="{cls} gone" style="animation-delay:{t:.2f}s">{GLYPH[p.piece_type]}</text>')
    o.append(f'<g>{"".join(pieces)}</g>')

    # side panel
    px = BX + 8 * S + 40
    end = outcome_text(b)
    o.append('<g filter="url(#glow)">')
    o.append(f'<text x="{px}" y="104" font-size="13" class="d">status</text>')
    if end:
        status, cls = end[0], ("k" if end[1] == "white" else "a" if end[1] == "black" else "w")
    elif b.is_check():
        status, cls = "CHECK — your move (White)", "r"
    else:
        status, cls = "your move — you play White", "k"
    o.append(f'<text x="{px}" y="128" font-size="19" class="{cls}">{escape(status)}</text>')
    # eval bar
    ev = max(-1000, min(1000, st.get("eval", 0)))
    bw = 380
    wx = bw * (0.5 + ev / 2000)
    o.append(f'<text x="{px}" y="162" font-size="11" class="d">{BOT} thinks · {"+" if ev >= 0 else ""}{ev / 100:.1f}</text>')
    o.append(f'<rect x="{px}" y="170" width="{bw}" height="8" fill="#ffb000" fill-opacity=".85"/><rect x="{px}" y="170" width="{wx:.0f}" height="8" fill="#eafff1"/>')
    # move list
    o.append(f'<text x="{px}" y="210" font-size="13" class="d">moves</text>')
    plies = st["plies"]
    rows = [(i // 2 + 1, plies[i]["san"], plies[i + 1]["san"] if i + 1 < len(plies) else "") for i in range(0, len(plies), 2)][-9:]
    if not rows:
        o.append(f'<text x="{px}" y="234" font-size="13" class="m">— board is fresh, open with 1. e4? —</text>')
    for r, (n, w_, b_) in enumerate(rows):
        y = 234 + r * 21
        o.append(f'<text x="{px}" y="{y}" font-size="13.5" xml:space="preserve"><tspan class="m">{n:>3}.</tspan> <tspan class="w">{escape(w_):<8}</tspan> <tspan class="a">{escape(b_)}</tspan></text>')
    # captured material
    start = {"P": 8, "N": 2, "B": 2, "R": 2, "Q": 1}
    have = {s: 0 for s in "PNBRQpnbrq"}
    for pc in b.piece_map().values():
        if pc.symbol() in have:
            have[pc.symbol()] += 1
    lost_b = "".join(GLYPH[chess.Piece.from_symbol(s.lower()).piece_type] * (start[s] - have[s.lower()]) for s in "QRBNP")
    lost_w = "".join(GLYPH[chess.Piece.from_symbol(s).piece_type] * (start[s] - have[s]) for s in "QRBNP")
    o.append(f'<text x="{px}" y="438" font-size="13" class="d">taken</text>')
    o.append(f'<text x="{px}" y="460" font-size="17" class="pb">{lost_b or "·"}</text>')
    o.append(f'<text x="{px}" y="482" font-size="17" class="pw">{lost_w or "·"}</text>')
    # leaderboard
    top = sorted(st["players"].items(), key=lambda kv: (-kv[1]["points"], kv[0]))[:3]
    o.append(f'<text x="{px}" y="516" font-size="13" class="d">top players</text>')
    if not top:
        o.append(f'<text x="{px}" y="538" font-size="12.5" class="m">no one yet — be the first</text>')
    for i, (u, v) in enumerate(top):
        o.append(f'<text x="{px}" y="{538 + i * 19}" font-size="12.5" xml:space="preserve"><tspan class="m">{i + 1:02d}</tspan> '
                 f'<tspan class="{"w" if i == 0 else "g"}">@{escape(u[:18]):<19}</tspan><tspan class="d">{v["points"]:>4} pts · {v["moves"]} mv</tspan></text>')
    played = len(st.get("results", []))
    wins = sum(1 for r in st.get("results", []) if r["result"] == "white")
    o.append(f'<text x="{BX - 28}" y="{H - 16}" font-size="11.5" class="d" xml:space="preserve">games played {played} · the internet won {wins} · last move: '
             + (escape(f'@{st["last"]["user"]} {st["last"].get("white") or "♻ new game"}' + (f' → {st["last"]["black"]}' if st["last"].get("black") else "")) if st.get("last") else "—")
             + '</text>')
    o.append("</g>")
    o.append(f'<rect x="{px}" y="{H - 25}" width="8" height="2" class="g cur" transform="translate(380,0)"/>')
    o.append(f'<rect width="{W}" height="{H}" rx="14" fill="url(#scan)"/><rect width="{W}" height="{H}" rx="14" fill="url(#vig)"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}" role="img" '
            f'aria-label="chess board, game {st["game_no"]}"><style>{css}</style><defs>{defs}</defs>{"".join(o)}</svg>')


# ── README section ────────────────────────────────────────────────────
def issue_link(title):
    body = "Just press \"Submit new issue\". The bot plays your move, answers as Black and updates the board in ~30s."
    return f"https://github.com/{REPO}/issues/new?title={quote(title, safe='')}&body={quote(body, safe='')}"


def readme_section(st):
    b = board_of(st)
    out = ['<div align="center">', "", f'<img src="game/board.svg?v={st["turns"]}" width="100%" alt="chess board">', ""]
    end = outcome_text(b)
    if end:
        out += [f"**🏁 {end[0]}** · [**♻ start game #{st['game_no'] + 1}**]({issue_link('chess|new')})", ""]
    else:
        out += ["<sub>You play <b>White</b> against <code>zahter.bot</code>. Click a move below, then press <b>Submit new issue</b>. "
                "The bot replies in about 30 seconds and the board updates for everyone.</sub>", ""]
    out += ["</div>", ""]
    if not end:
        order = [chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]
        groups = {}
        for m in b.legal_moves:
            groups.setdefault(m.from_square, []).append(m)
        rows = []
        for fsq in sorted(groups, key=lambda s: (order.index(b.piece_at(s).piece_type), chess.square_file(s), chess.square_rank(s))):
            pc = b.piece_at(fsq)
            links = []
            for m in sorted(groups[fsq], key=lambda x: (x.to_square, x.promotion or 0)):
                if m.promotion and m.promotion not in (chess.QUEEN, chess.KNIGHT):
                    continue
                links.append(f"[`{b.san(m)}`]({issue_link('chess|move|' + m.uci())})")
            rows.append(f"| {WHITE_GLYPH[pc.piece_type]} `{chess.square_name(fsq)}` | {' · '.join(links)} |")
        out += [f"<details open><summary><b>♙ your move — {b.legal_moves.count()} legal moves</b> (click one)</summary>", "",
                "| piece | moves |", "|:--|:--|"] + rows + ["", "</details>", ""]
    if st["history"]:
        out += ["<details><summary>last moves</summary>", "", "| # | player | White | zahter.bot |", "|--:|---|---|---|"]
        out += [f"| {h['n']} | [@{h['user']}](https://github.com/{h['user']}) | `{h['white']}` | `{h['black']}` |" for h in st["history"][:5]]
        out += ["", "</details>", ""]
    return "\n".join(out)


def patch_readme(p, st):
    try:
        txt = open(p["readme"]).read()
    except OSError:
        return
    new, n = re.subn(r"(<!-- GAME:START -->).*?(<!-- GAME:END -->)", lambda m: f"{m.group(1)}\n{readme_section(st)}\n{m.group(2)}", txt, flags=re.S)
    if not n:
        print("warning: README has no GAME markers, skipped", file=sys.stderr)
        return
    open(p["readme"], "w").write(new)


def save(p, st):
    os.makedirs(os.path.dirname(p["state"]), exist_ok=True)
    json.dump(st, open(p["state"], "w"), indent=1)
    open(p["board"], "w").write(render(st))
    patch_readme(p, st)


# ── self test ─────────────────────────────────────────────────────────
def selftest():
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "game"))
        shutil.copy(os.path.join(ROOT, "README.md"), os.path.join(tmp, "README.md"))
        p = paths(tmp)
        st = new_state(); save(p, st)
        rnd = random.Random(1)
        games = 0
        for turn in range(400):
            b = board_of(st)
            if game_over(b):
                ok, _ = play(st, "tester", "chess|new", think=0.15); assert ok; games += 1
                if games >= 3:
                    break
                continue
            if turn % 37 == 5:  # junk titles never change state
                before = json.dumps(st, sort_keys=True)
                for bad in ("chess|move|e9e4", "chess|move|zz", "chess|foo", "nope", "chess|move|`@x`"):
                    ok, msg = play(st, "tester", bad, think=0.15)
                    assert not ok and json.dumps(st, sort_keys=True) == before and "@x" not in msg.replace("@tester", "")
            m = rnd.choice(list(b.legal_moves))
            title = f"chess|move|{m.uci()}" if turn % 2 else f"chess|move|{b.san(m)}"
            ok, msg = play(st, f"user{turn % 5}", title, think=0.15)
            assert ok, (title, msg)
            b2 = board_of(st)
            assert b2.fen() == st["fen"], "fen drift"
            assert len(st["plies"]) % 2 == 0 or game_over(b2), "bot must answer unless the game ended"
            save(p, st)
            svg = open(p["board"]).read()
            assert svg.startswith("<svg") and len(svg) < 120_000
        assert sum(v["moves"] for v in st["players"].values()) > 0
        # bot finds mate in one
        b = chess.Board("r5k1/8/8/8/8/8/6PP/7K b - - 0 1")   # Black to move: Ra1#
        bm, _ = bot_move(b, "t", think=2)
        b.push(bm)
        assert b.is_checkmate(), f"bot missed mate in one: {bm}"
        print(f"selftest ok: {st['turns']} turns, {games} finished games, players {len(st['players'])}")
    finally:
        shutil.rmtree(tmp)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--init", action="store_true")
    g.add_argument("--play", action="store_true")
    g.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    p = paths()
    if a.selftest:
        return selftest()
    if a.init:
        st = new_state(); save(p, st); print("new game written"); return
    st = load(p)
    changed, msg = play(st, os.environ.get("ISSUE_AUTHOR"), os.environ.get("ISSUE_TITLE"))
    if changed:
        save(p, st)
    rf = os.environ.get("RESULT_FILE") or os.path.join(ROOT, "game", "last_result.md")
    open(rf, "w").write(msg + "\n")
    print(msg)


if __name__ == "__main__":
    main()
