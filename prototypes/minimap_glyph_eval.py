r"""The game's minimap ability glyphs as a caster-naming channel, scored on the player's positioned labels.

    .\.venv\Scripts\python.exe prototypes\minimap_glyph_eval.py score      [--out DIR] [--states probe|all] [--answers on|off]
    .\.venv\Scripts\python.exe prototypes\minimap_glyph_eval.py misses     [--out DIR]
    .\.venv\Scripts\python.exe prototypes\minimap_glyph_eval.py separate   [--out DIR]
    .\.venv\Scripts\python.exe prototypes\minimap_glyph_eval.py inventory  [--out DIR]
    .\.venv\Scripts\python.exe prototypes\minimap_glyph_eval.py follow     [--out DIR] [--only sid,sid]
    .\.venv\Scripts\python.exe prototypes\minimap_glyph_eval.py heldout    [--out DIR]

`score` reads every positioned ability label (labels/ability, labels/ability_paint,
labels/tray_object marks) from the minimap crop cache (no decode), snaps it to the
nearest proposer disc within 8 px x scale, and names the labelled caster's kit
glyph by masked Pearson correlation of luma inside an r = 8.5 px disc
(x scale), centre +-3 px, glyph canvas 11-22 px, rotation 0-345 by 15 deg, never
binarised; templates are each ability's DisplayIcon plus the export's minimap
markers assigned to a kit ability by glyph correlation (never by file letter).
With `--answers on` (the default), the player's texture answers
(labels/minimap_glyph_questions/answers.jsonl) then add each answered stem's
variants as references of the answered ability, citing the answer's line, and
override the correlation's assignment of the same file; unsure answers stay
out (`apply_answers`; items.json meta `answer_log` lists every effect).
It writes items.json (per-item verdicts) and windows.npz (each item's luma and
colour window, so `separate` and `misses` read no cache).

Split: dev = d95cfad5693a, dae6f33f3f48 (Cypher, Killjoy); held-out = every
other session. Shape-class abilities (recon bolt, smokes, walls ...) are left
out, as the probe left them out. The probe this ports is
demo-abilities-gameicons-20261003 (store notes/predictions.jsonl).

`misses` itemises every held-out miss and draws a montage; `separate` runs the
separability methods (dev-trained or label-free, scored once on held-out);
`inventory` lists every minimap-related texture of the export with its proposed
ability and evidence. `follow` follows each labelled icon through the cached
frames of the next 3 s, from the nearest proposer disc within a growing reach,
skips a frame where a stored team_vision portrait covers it, the widget is not
drawn, or the disc is the baked map, and decides once from up to 8 clean
frames (follow.json, follow_misses.png). `prototypes/ask_minimap_glyphs.py`
asks the player what these cannot derive: unproven texture mappings, what an
ability draws on the minimap, and whether an icon rotates.

`heldout` scores the matcher once, every parameter as above (probe states,
answers on), on the held-out labelling pass
(`label_minimap_glyph_heldout.py`; last row per item wins). Each sure mark
named with a kit key is snapped, classified over the session agent's kit (no
other-agent path) and followed; the follow's verdict is the matcher's. The
headline is after_cast and control frames outside dev_session and
near_tuned_label; those two and the audit-only frames report apart. It also
counts the proposer's discs near the player's icon marks and away from every
mark, raw and after the follow's gates, and audits each excluded ability
against the self-view marks (heldout.json). Unsure, smoke, other-agent and
typed marks are listed, never scored.

Wire: no. It evaluates the game glyphs; wiring into reticle/ waits for an
owner of ability-disc tracking (ability-icon proposes, nothing follows) and a
held-out set the follow parameters were not chosen on (predictions.jsonl,
minimap-glyph-follow-20261004).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

cv2.setNumThreads(1)
try:
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
except Exception:  # noqa: BLE001
    pass

VERSION = "minimap-glyph-eval-0.2.0"
STORE = Path("C:/Users/grant/reticle-store")
BUILD = "release-13.06-shipping-18-5590001"
GX = STORE / "reference" / "game-files" / BUILD
CAT = STORE / "reference" / "abilities.json"
LABELS = STORE / "labels"
OUT = STORE / "analysis" / "minimap-glyphs-20261004"
DEV = {"d95cfad5693a", "dae6f33f3f48"}
SHAPES = {"recon bolt", "hunter's fury", "regrowth", "orbital strike", "toxic screen", "poison cloud",
          "viper's pit", "blaze", "smoke"}

# ------------------------------------------------------------------ glyph references


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _props(path: str) -> dict:
    for o in json.load(open(path, encoding="utf-8")):
        if "Properties" in o:
            return o["Properties"]
    return {}


def kit_table() -> tuple[dict, list[dict]]:
    """Agent display names and every ability's UIData (display name, DisplayIcon png) from the export."""
    g = str(GX) + "/"
    slot = {"4": "C", "Q": "Q", "E": "E", "X": "X", "C": "C"}
    icons_all = {**{os.path.basename(p)[:-4]: p for p in glob.glob(g + "minimap/**/*.png", recursive=True)},
                 **{os.path.basename(p)[:-4]: p for p in glob.glob(g + "killfeed-icons/**/*.png", recursive=True)}}
    agents = {}
    for p in glob.glob(g + "ability-data/**/*_UIData.json", recursive=True):
        code = os.path.basename(p)[:-len("_UIData.json")]
        dn = _props(p).get("DisplayName", {}).get("LocalizedString")
        if dn and "_" not in code:
            agents[code] = dn
    kit = []
    for p in glob.glob(g + "ability-data/**/UIData_*.json", recursive=True) + \
            glob.glob(g + "ability-data/**/AbilityUIData_*.json", recursive=True):
        b = os.path.basename(p)
        m = re.match(r"UIData_([A-Za-z]+)_(Q|E|X|4|C|Passive)(?:_.*)?\.json$", b)
        if m:
            code, tok = m.groups()
        else:
            m = re.match(r"AbilityUIData_([A-Za-z]+)_.*\.json$", b)
            f = re.search(r"/Ability_(Q|E|X|4|C)/", p.replace("\\", "/"))
            if not (m and f):
                continue
            code, tok = m.group(1), f.group(1)
        pr = _props(p)
        icon = re.sub(r"^Texture2D'|'$", "", (pr.get("DisplayIcon") or {}).get("ObjectName", ""))
        kit.append({"code": code, "agent": agents.get(code), "slot": slot.get(tok, tok),
                    "ability": pr.get("DisplayName", {}).get("LocalizedString"), "icon": icon,
                    "icon_png": icons_all.get(icon), "uidata": os.path.relpath(p, g).replace("\\", "/")})
    return agents, kit


def icon_glyph(f: str) -> np.ndarray:
    """A DisplayIcon as alpha x luma, 128 px (INTER_AREA to shrink)."""
    im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    a = im[..., 3].astype(np.float32) / 255.0 if im.shape[2] == 4 else np.ones(im.shape[:2], np.float32)
    g = a * cv2.cvtColor(im[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    if g.shape != (128, 128):
        g = cv2.resize(g, (128, 128), interpolation=cv2.INTER_AREA if g.shape[0] > 128 else cv2.INTER_LINEAR)
    return g


def load_glyphs() -> tuple[dict, list]:
    """(agent, catalogue slot) -> DisplayIcon glyph; the slot is the tray catalogue's, matched by display name."""
    cat = json.load(open(CAT, encoding="utf-8"))["agents"]
    _, kit = kit_table()
    out, unmatched = {}, []
    for k in kit:
        if not k["agent"] or not k["icon_png"] or k["slot"] == "Passive":
            continue
        abil = cat.get(k["agent"], {}).get("abilities", [])
        na = norm(k["ability"])
        hit = [a for a in abil if norm(a["name"]) == na] or \
              [a for a in abil if na and (norm(a["name"]) in na or na in norm(a["name"]))]
        if not hit:
            unmatched.append((k["agent"], k["ability"], k["slot"]))
            continue
        out[(k["agent"], hit[0]["key"])] = {"name": k["ability"], "glyph": icon_glyph(k["icon_png"]),
                                            "file": k["icon_png"], "uidata_slot": k["slot"], "uidata": k["uidata"]}
    return out, unmatched


GLYPHS, UNMATCHED = load_glyphs()


def kit(agent: str | None) -> dict:
    return {k: v for k, v in GLYPHS.items() if agent and k[0].lower() == agent.lower() and k[1] in "CQEX"}


def find(agent: str, ability: str):
    na = norm(ability)
    for k, v in kit(agent).items():
        nv = norm(v["name"])
        if nv == na or nv in na or na in nv:
            return k
    return None


CODENAME = {"Mage": "Harbor", "Nox": "Vyse", "Pine": "Veto", "Rift": "Astra", "Stealth": "Yoru", "Vampire": "Reyna",
            "Wraith": "Omen", "KAYO": "KAY/O", "Kayo": "KAY/O", "Cable": "Deadlock", "Aggrobot": "Gekko",
            "AggroBot": "Gekko", "BountyHunter": "Fade", "BountyHounter": "Fade", "Cashew": "Tejo", "Clay": "Raze",
            "Guide": "Skye", "Hunter": "Sova", "Iris": "Miks", "Sequoia": "Iso", "Gumshoe": "Cypher",
            "Deadeye": "Chamber", "Grenadier": "KAY/O", "Sarge": "Brimstone", "Smonk": "Clove", "Sprinter": "Neon",
            "Terra": "Waylay", "Thorne": "Sage", "Wushu": "Jett", "Pandemic": "Viper"}
INNER = 0.70
STATE_WORDS = ("inactive", "active", "selected", "default", "ally", "enemy", "detected", "hovered", "precast")
#: The probe kept these states only; `--states all` keeps every one (prediction M9).
PROBE_STATES = ("inactive", "default", "ally", "")


def marker_glyph(f: str) -> np.ndarray:
    """A disc marker's glyph: luma x alpha inside 0.70 of the disc, its median removed, clipped, 128 px."""
    im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
    a = im[..., 3].astype(np.float32) / 255.0
    lum = cv2.cvtColor(im[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0 * a
    n = im.shape[0]
    k = int(round(n / 2.0 * INNER))
    c = n // 2
    g = lum[c - k:c + k, c - k:c + k].copy()
    yy, xx = np.mgrid[-k:k, -k:k] + 0.5
    g[np.hypot(xx, yy) > k] = 0
    g = g - np.median(g[np.hypot(xx, yy) <= k])
    g = np.clip(g, 0, None)
    g /= max(g.max(), 1e-6)
    return cv2.resize(g, (128, 128), interpolation=cv2.INTER_AREA if g.shape[0] > 128 else cv2.INTER_LINEAR)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum() + 1e-9))


def _scaled(g: np.ndarray, m: int) -> np.ndarray:
    t = cv2.resize(g, (m, m), interpolation=cv2.INTER_AREA)
    o = np.zeros((128, 128), np.float32)
    p = (128 - m) // 2
    o[p:p + m, p:p + m] = t
    return o


def marker_files(states=PROBE_STATES) -> list[tuple]:
    fs = []
    for f in sorted(glob.glob(str(GX) + "/minimap/**/TX_UI_Minimap_*.png", recursive=True)):
        parts = os.path.basename(f)[:-4].split("_")[3:]
        code, rest = parts[0], parts[1:]
        state = rest[-1].lower() if rest and rest[-1].lower() in STATE_WORDS else ""
        if states is not None and state not in states:
            continue
        fs.append((f.replace("\\", "/"), CODENAME.get(code, code), "_".join(rest), state, "Possessables" not in f))
    return fs


def marker_map(states=PROBE_STATES) -> list[dict]:
    """Each export marker's correlation with every kit DisplayIcon of the agent its code names."""
    out = []
    for f, agent, rest, state, disc in marker_files(states):
        mg = marker_glyph(f) if disc else icon_glyph(f)
        best = []
        for key, v in kit(agent).items():
            s = max(_corr(mg, _scaled(v["glyph"], m)) for m in range(80, 132, 6))
            best.append((s, key))
        best.sort(reverse=True)
        out.append({"file": os.path.relpath(f, str(GX)).replace("\\", "/"), "agent": agent, "rest": rest,
                    "state": state, "disc": disc, "best": best[0] if best else None,
                    "second": best[1] if len(best) > 1 else None, "glyph": mg, "path": f})
    return out


EXTRA: dict = {}
#: What the player's texture answers did to the references in the last build_extra (written into items.json meta).
ANSWER_LOG: dict = {}
ANSWERS = LABELS / "minimap_glyph_questions" / "answers.jsonl"
#: The glyph `marker_map` rendered for each export marker it read (path -> glyph); an answer that re-labels such a
#: file keeps this rendering, so the answer changes the label and never the drawing.
DERIVED_GLYPH: dict = {}


def build_extra(states=PROBE_STATES, min_corr=0.5, min_gap=0.05, answers: bool = False) -> list[dict]:
    """Assign each export marker to the kit icon it correlates with best (corr >= 0.5, gap >= 0.05); with
    `answers`, the player's texture answers then override and extend that assignment (`apply_answers`)."""
    EXTRA.clear()
    ANSWER_LOG.clear()
    rows = marker_map(states)
    DERIVED_GLYPH.clear()
    DERIVED_GLYPH.update({r["path"]: r["glyph"] for r in rows})
    for r in rows:
        r["assigned"] = None
        if r["best"] is None:
            continue
        s, key = r["best"]
        gap = s - (r["second"][0] if r["second"] else -1)
        if s >= min_corr and gap >= min_gap:
            EXTRA.setdefault(key, []).append(
                (r["glyph"], f"1306:{os.path.basename(r['file'])} corr {s:.2f} gap {gap:.2f}"))
            r["assigned"] = f"{key[0]}:{key[1]}"
    if answers:
        apply_answers(states)
    return rows


def texture_answers() -> dict:
    """{stem: (line number, answer row)} for the texture questions; the last row for a key wins, as the asking
    tool reads them (`ask_minimap_glyphs.answered`)."""
    out = {}
    for i, ln in enumerate(ANSWERS.read_text(encoding="utf-8").splitlines(), 1):
        if ln.strip():
            r = json.loads(ln)
            if r.get("kind") == "texture":
                out[r["key"].split(":", 1)[1]] = (i, r)
    return out


def stem_of(name: str) -> str:
    """A texture's stem: its name less a trailing state word (the asking tool's grouping)."""
    return re.sub(r"_(" + "|".join(STATE_WORDS) + r")$", "", name, flags=re.I)


def answer_glyph(f: str) -> np.ndarray:
    """An answered texture's glyph: the rendering `marker_map` gave it, else `marker_glyph` for a disc texture
    (`is_disc`, which needs alpha), else `icon_glyph`."""
    if f in DERIVED_GLYPH:
        return DERIVED_GLYPH[f]
    im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
    return marker_glyph(f) if im.ndim == 3 and im.shape[2] == 4 and is_disc(im) else icon_glyph(f)


def apply_answers(states=PROBE_STATES) -> None:
    """The player's texture answers as references. A sure answer naming a kit key (agent:slot) adds each exported
    variant of the stem whose state `states` keeps, provenance `answers.jsonl#L<n>`; it moves a file the
    DisplayIcon correlation assigned elsewhere, never duplicating it. `agent_other` and `not_ability` remove the
    stem's files from the references. Unsure answers change nothing; ANSWER_LOG lists every answer's effect.

    The sure answers are domain facts, one per agent: [domain:abilities/minimap-textures-astra]
    [domain:abilities/minimap-textures-chamber] [domain:abilities/minimap-textures-cypher]
    [domain:abilities/minimap-textures-deadlock] [domain:abilities/minimap-textures-fade]
    [domain:abilities/minimap-textures-gekko] [domain:abilities/minimap-textures-harbor]
    [domain:abilities/minimap-textures-iso] [domain:abilities/minimap-textures-kayo]
    [domain:abilities/minimap-textures-killjoy] [domain:abilities/minimap-textures-miks]
    [domain:abilities/minimap-textures-neon] [domain:abilities/minimap-textures-omen]
    [domain:abilities/minimap-textures-phoenix] [domain:abilities/minimap-textures-raze]
    [domain:abilities/minimap-textures-reyna] [domain:abilities/minimap-textures-skye]
    [domain:abilities/minimap-textures-sova] [domain:abilities/minimap-textures-tejo]
    [domain:abilities/minimap-textures-veto] [domain:abilities/minimap-textures-vyse]
    [domain:abilities/minimap-textures-yoru]."""
    by_stem = defaultdict(list)
    for f in inv_files():
        by_stem[stem_of(os.path.basename(f)[:-4])].append(f)
    rel_answers = os.path.relpath(ANSWERS, STORE).replace("\\", "/")
    used, unsure, removed, out_of_states, moved = [], [], [], [], []
    for stem, (ln, a) in sorted(texture_answers().items()):
        if a.get("unsure") or not a.get("answer"):
            unsure.append({"stem": stem, "line": ln})
            continue
        files = by_stem.get(stem, [])
        names = {os.path.basename(f) for f in files}
        for key in list(EXTRA):                         # the answer decides these files; drop derived assignments
            keep = []
            for g, p in EXTRA[key]:
                f0 = p.split(" ")[0].split(":", 1)[-1]
                if f0 in names:
                    moved.append({"file": f0, "from": f"{key[0]}:{key[1]}", "to": a["answer"], "line": ln})
                else:
                    keep.append((g, p))
            EXTRA[key] = keep
            if not keep:
                del EXTRA[key]
        key = tuple(a["answer"].rsplit(":", 1)) if ":" in a["answer"] else None
        if key is None or key not in GLYPHS:
            removed.append({"stem": stem, "line": ln, "answer": a["answer"], "files": sorted(names)})
            continue
        for f in sorted(files):
            name = os.path.basename(f)[:-4]
            state = next((w for w in STATE_WORDS if name.lower().endswith("_" + w)), "")
            if states is not None and state not in states:
                out_of_states.append({"file": os.path.basename(f), "answer": a["answer"], "line": ln, "state": state})
                continue
            rel = os.path.relpath(f, str(GX)).replace("\\", "/")
            EXTRA.setdefault(key, []).append((answer_glyph(f), f"answer:{rel_answers}#L{ln}:{rel}"))
            used.append({"file": rel, "answer": a["answer"], "line": ln})
    ANSWER_LOG.update({"file": rel_answers, "used": used, "unsure": unsure, "no_kit_key": removed,
                       "state_filtered": out_of_states, "moved_from_derived": moved})


# ------------------------------------------------------------------ the probe's matcher (cv2, reproduced exactly)

CANVAS = np.arange(11, 23, 1.0)
MASK_R = 8.5
SHIFT = 3
ROTS = list(range(0, 360, 15))
_tcache: dict = {}


def sources(key) -> list[tuple[str, np.ndarray]]:
    return [("icon", GLYPHS[key]["glyph"])] + [(prov, g) for g, prov in EXTRA.get(key, [])]


def template(key, canvas: float, rot: int, si: int = 0) -> np.ndarray:
    k = (key, canvas, rot, si, len(EXTRA.get(key, [])))
    if k not in _tcache:
        g = sources(key)[si][1]
        n = int(round(canvas))
        t = cv2.resize(g, (n, n), interpolation=cv2.INTER_AREA)
        if rot:
            M = cv2.getRotationMatrix2D(((n - 1) / 2, (n - 1) / 2), rot, 1.0)
            t = cv2.warpAffine(t, M, (n, n), flags=cv2.INTER_LINEAR, borderValue=0)
        _tcache[k] = t
    return _tcache[k]


def luma(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)[..., 0].astype(np.float32)


def geom(scale: float) -> tuple[int, int, int, np.ndarray]:
    """(W, h, shift, disc mask) of the scoring window at a crop scale."""
    mr = MASK_R * scale
    W = int(np.ceil(mr)) * 2 + 1
    sh = int(round(SHIFT * scale)) if scale < 1 else SHIFT
    yy, xx = np.mgrid[-(W // 2):W // 2 + 1, -(W // 2):W // 2 + 1]
    return W, W // 2, sh, (np.hypot(xx, yy) <= mr).astype(np.float32)


def place(t: np.ndarray, W: int) -> np.ndarray:
    T = np.zeros((W, W), np.float32)
    n = t.shape[0]
    if n > W:
        o = (n - W) // 2
        T = t[o:o + W, o:o + W].copy()
    else:
        o = (W - n) // 2
        T[o:o + n, o:o + n] = t
    return T


def score_at(Y, cx, cy, keys, scale=1.0, rotate=True):
    """Best masked Pearson per candidate near (cx, cy): {key: (score, canvas, rot, dx, dy, source)}."""
    W, h, sh, mask = geom(scale)
    x0, y0 = int(round(cx)) - h - sh, int(round(cy)) - h - sh
    x1, y1 = x0 + W + 2 * sh, y0 + W + 2 * sh
    if x0 < 0 or y0 < 0 or x1 > Y.shape[1] or y1 > Y.shape[0]:
        return None
    win = Y[y0:y1, x0:x1]
    out = {}
    for key in keys:
        best = (-2.0, None, None, None, None, None)
        for si in range(len(sources(key))):
            for c in CANVAS * scale:
                for rot in (ROTS if rotate else [0]):
                    T = place(template(key, float(round(c)), rot, si), W)
                    if T[mask > 0].std() < 1e-3:
                        continue
                    r = cv2.matchTemplate(win, T, cv2.TM_CCOEFF_NORMED, mask=mask)
                    r = np.nan_to_num(r, nan=-2.0, posinf=-2.0, neginf=-2.0)
                    j = np.unravel_index(np.argmax(r), r.shape)
                    if r[j] > best[0]:
                        best = (float(r[j]), float(round(c)), rot, int(j[1]) - sh, int(j[0]) - sh,
                                sources(key)[si][0])
        out[key] = best
    return out


def classify(Y, cx, cy, keys, scale=1.0, rotate=True):
    s = score_at(Y, cx, cy, keys, scale, rotate)
    if not s:
        return None
    order = sorted(s, key=lambda k: -s[k][0])
    best = order[0]
    margin = s[best][0] - (s[order[1]][0] if len(order) > 1 else -1.0)
    return {"pred": best, "score": s[best][0], "margin": margin,
            "scores": {f"{k[0]}:{k[1]}": v[0] for k, v in s.items()}, "fit": s[best][1:],
            "fits": {f"{k[0]}:{k[1]}": list(v[1:]) for k, v in s.items()}}


# ------------------------------------------------------------------ items and crops


def load_items() -> list[dict]:
    """Every positioned ability label, as the probe read them (latest files, .bak skipped)."""
    items = []

    def add(sid, t, x, y, cat, src, roi, extra=None):
        items.append({"sid": sid, "t_ms": float(t), "x": x, "y": y, "cat": cat, "src": src, "roi": roi,
                      **(extra or {})})

    for f in sorted(glob.glob(str(LABELS / "ability" / "*.jsonl"))):
        if "bak" in f:
            continue
        for ln in open(f, encoding="utf-8"):
            if not ln.strip():
                continue
            r = json.loads(ln)
            cat = "NOT" if r.get("not_ability") else r.get("category_id")
            if cat is None or cat in ("radius_ring", "place_color"):
                continue
            add(r["session_id"], r["t_ms"], r["x"], r["y"], cat, "ability", r["roi"])
    for f in sorted(glob.glob(str(LABELS / "ability_paint" / "*.jsonl"))):
        for ln in open(f, encoding="utf-8"):
            if not ln.strip():
                continue
            r = json.loads(ln)
            for i in r.get("icons", []):
                if i.get("category_id") and not i["category_id"].startswith("world"):
                    add(r["session_id"], r["t_ms"], i["x"], i["y"], i["category_id"], "paint", r["roi"])
    for f in sorted(glob.glob(str(LABELS / "tray_object" / "*.jsonl"))):
        for ln in open(f, encoding="utf-8"):
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r["class"] != "object":
                continue
            for m in r["marks"]:
                add(r["session_id"], m["t_ms"], m["x"], m["y"], f"{r['agent'].lower()}:{r['ability'].lower()}",
                    "tray_object", None)
    sess_agent = {}
    for it in items:
        if it["cat"] not in ("NOT", "smoke"):
            sess_agent.setdefault(it["sid"], it["cat"].split(":")[0])
    for it in items:
        it["agent"] = it["cat"].split(":")[0] if it["cat"] not in ("NOT", "smoke") else sess_agent.get(it["sid"])
    return [it for it in items if not (":" in it["cat"] and it["cat"].split(":", 1)[1] in SHAPES)]


_caches: dict = {}


def crop_cache(sid: str):
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.store import Store
    if sid not in _caches:
        man = Store(str(STORE)).read_manifest(sid)
        c, why = RoiCache.load(STORE, man, get_profile(man["source_profile"]), "minimap")
        _caches[sid] = (c, why, man)
    return _caches[sid]


def frames(sid: str, times) -> dict:
    """{t_asked: (t_held, minimap crop)} from the crop cache, nearest held sample."""
    c, why, _ = crop_cache(sid)
    if c is None:
        raise RuntimeError(f"{sid}: {why}")
    h = np.asarray(c.holds())
    held = {t: float(h[np.argmin(np.abs(h - t))]) for t in times}
    x0, y0, x1, y1 = c.rect_of("minimap")
    got = {s.t_ms: s.frame for s in c.samples(sorted(set(held.values())), rois=["minimap"])}
    return {t: (th, got[th][y0:y1, x0:x1].copy()) for t, th in held.items() if th in got}


_terms: dict = {}


def icon_terms(sid: str, shape):
    from reticle import ability_icons, geometry, minimap
    if sid not in _terms:
        slab = minimap.slab_mask(geometry.reference_static(sid, str(STORE)))
        _terms[sid] = ability_icons.IconTerms(slab, geometry.map_scale_of(sid, str(STORE))) \
            if slab.shape[:2] == shape[:2] else None
    return _terms[sid]


WIN = 20  # stored window half-size (px) around the snapped centre


def cmd_score(args) -> None:
    from reticle import ability_icons
    from reticle.adjudication.gallery import classify_ability_glyph
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    states = None if args.states == "all" else PROBE_STATES
    rows = build_extra(states, answers=args.answers == "on")
    items = load_items()
    print(f"items {len(items)}; extra markers {sum(len(v) for v in EXTRA.values())}", flush=True)
    res, wins_Y, wins_C, wins_static = [], [], [], []
    t0 = time.time()
    by = defaultdict(list)
    for it in items:
        by[it["sid"]].append(it)
    for sid, its in sorted(by.items()):
        c, why, _ = crop_cache(sid)
        if c is None:
            res.extend({**it, "refused": why} for it in its)
            continue
        cr = c.rect_of("minimap")
        fr = frames(sid, sorted({it["t_ms"] for it in its}))
        static = None
        try:
            from reticle import geometry
            static = geometry.reference_static(sid, str(STORE))
        except SystemExit:
            static = None
        for it in its:
            if it["t_ms"] not in fr:
                res.append({**it, "refused": "no_frame"})
                continue
            th, crop = fr[it["t_ms"]]
            if abs(th - it["t_ms"]) > 70:
                res.append({**it, "refused": f"nearest_frame_{th - it['t_ms']:.0f}ms"})
                continue
            roi = it["roi"] or cr
            x = it["x"] + roi[0] - cr[0]
            y = it["y"] + roi[1] - cr[1]
            scale = crop.shape[1] / 465.0
            cat, agent = it["cat"], it["agent"]
            truth = find(agent, cat.split(":", 1)[1]) if cat not in ("NOT", "smoke") else None
            keys = sorted(kit(agent)) if agent else []
            Y = luma(crop)
            tm = icon_terms(sid, crop.shape)
            snap = None
            if tm is not None:
                near = [p for p in ability_icons.propose_icons(crop, tm)
                        if np.hypot(p["cx"] - x, p["cy"] - y) <= 8 * scale]
                if near:
                    snap = min(near, key=lambda p: np.hypot(p["cx"] - x, p["cy"] - y))
                    x, y = snap["cx"], snap["cy"]
            o = {**it, "truth": truth and f"{truth[0]}:{truth[1]}", "scale": scale, "t_held": th,
                 "split": "dev" if sid in DEV else "heldout", "cx": float(x), "cy": float(y),
                 "snap": snap and {k: float(snap[k]) for k in ("cx", "cy", "r", "score")}, "terms": tm is not None,
                 "kit": [f"{k[0]}:{k[1]}" for k in keys], "win_index": len(wins_Y)}
            for rot in (False, True):
                cl = classify(Y, x, y, keys, scale, rotate=rot) if keys else None
                tag = "rot" if rot else "norot"
                if cl:
                    o[f"{tag}_pred"] = f"{cl['pred'][0]}:{cl['pred'][1]}"
                    o[f"{tag}_score"], o[f"{tag}_margin"] = cl["score"], cl["margin"]
                    o[f"{tag}_scores"], o[f"{tag}_fit"], o[f"{tag}_fits"] = cl["scores"], cl["fit"], cl["fits"]
            h = int(round(16 * scale))
            p = crop[max(0, int(y) - h):int(y) + h, max(0, int(x) - h):int(x) + h]
            g = classify_ability_glyph(p) if p.size else None
            o["gallery_pred"] = g and g["ability_id"]
            # windows for the separability methods and the montage (NaN / 0 outside the crop)
            ix, iy = int(round(x)), int(round(y))
            wy = np.full((2 * WIN + 1, 2 * WIN + 1), np.nan, np.float32)
            wc = np.zeros((2 * WIN + 1, 2 * WIN + 1, 3), np.uint8)
            ws = np.full((2 * WIN + 1, 2 * WIN + 1, 3), 0, np.uint8)
            ya, yb, xa, xb = max(0, iy - WIN), min(crop.shape[0], iy + WIN + 1), max(0, ix - WIN), \
                min(crop.shape[1], ix + WIN + 1)
            wy[ya - iy + WIN:yb - iy + WIN, xa - ix + WIN:xb - ix + WIN] = Y[ya:yb, xa:xb]
            wc[ya - iy + WIN:yb - iy + WIN, xa - ix + WIN:xb - ix + WIN] = crop[ya:yb, xa:xb]
            if static is not None and static.shape[:2] == crop.shape[:2]:
                st = static if static.ndim == 3 else cv2.cvtColor(static, cv2.COLOR_GRAY2BGR)
                ws[ya - iy + WIN:yb - iy + WIN, xa - ix + WIN:xb - ix + WIN] = st[ya:yb, xa:xb]
                o["static"] = True
            wins_Y.append(wy)
            wins_C.append(wc)
            wins_static.append(ws)
            res.append(o)
        print(f"  {sid}: {len(its)} items, {time.time() - t0:.0f}s", flush=True)
    np.savez_compressed(out / "windows.npz", Y=np.array(wins_Y), C=np.array(wins_C), S=np.array(wins_static))
    meta = {"version": VERSION, "build": BUILD, "states": args.states, "n_items": len(res),
            "answers": args.answers == "on", "answer_log": dict(ANSWER_LOG),
            "extra": {f"{k[0]}:{k[1]}": [p for _, p in v] for k, v in EXTRA.items()},
            "markers": [{k: r[k] for k in ("file", "agent", "rest", "state", "disc", "assigned")} |
                        {"best": r["best"] and [round(r["best"][0], 3), f"{r['best'][1][0]}:{r['best'][1][1]}"],
                         "second": r["second"] and [round(r["second"][0], 3),
                                                    f"{r['second'][1][0]}:{r['second'][1][1]}"]} for r in rows],
            "wall_s": round(time.time() - t0, 1)}
    json.dump({"meta": meta, "items": res}, open(out / "items.json", "w"), indent=1, default=float)
    summarise(res)


def positives(res, split=None):
    return [r for r in res if not r.get("refused") and r["cat"] not in ("NOT", "smoke") and r.get("truth")
            and (split is None or r["split"] == split)]


def summarise(res) -> dict:
    s = {}
    for tag in ("norot", "rot"):
        for split in ("dev", "heldout"):
            P = positives(res, split)
            right = sum(r.get(f"{tag}_pred") == r["truth"] for r in P)
            s[f"{tag}_{split}"] = f"{right}/{len(P)}"
            per = defaultdict(lambda: [0, 0])
            for r in P:
                per[r["cat"]][1] += 1
                per[r["cat"]][0] += r.get(f"{tag}_pred") == r["truth"]
            s[f"{tag}_{split}_per"] = {k: f"{a}/{n}" for k, (a, n) in sorted(per.items())}
    for split in ("dev", "heldout"):
        P = positives(res, split)
        s[f"gallery_{split}"] = f"{sum(r.get('gallery_pred') == r['cat'] for r in P)}/{len(P)}"
    s["refused"] = dict(Counter(r["refused"] for r in res if r.get("refused")))
    print(json.dumps(s, indent=1))
    return s


def load_scores(out: Path, states: str = "probe"):
    d = json.load(open(out / "items.json", encoding="utf-8"))
    build_extra(None if d["meta"]["states"] == "all" else PROBE_STATES, answers=d["meta"].get("answers", False))
    z = np.load(out / "windows.npz")
    return d, z


def fit_template(key_s: str, fit: list, scale: float) -> np.ndarray:
    """The template a fit chose (canvas, rot, dx, dy, source), placed in the scoring window."""
    key = tuple(key_s.split(":"))
    canvas, rot, _, _, src = fit
    si = [s for s, _ in sources(key)].index(src)
    W, _, _, _ = geom(scale)
    return place(template(key, float(canvas), rot, si), W)


def _tile(img: np.ndarray, k: int, label: str | None = None) -> np.ndarray:
    """Nearest-neighbour enlargement, display only."""
    if img.ndim == 2:
        img = cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    t = cv2.resize(img, (img.shape[1] * k, img.shape[0] * k), interpolation=cv2.INTER_NEAREST)
    if label:
        cv2.putText(t, label, (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 255, 255), 1, cv2.LINE_AA)
    return t


def _pad(img: np.ndarray, h: int, w: int) -> np.ndarray:
    o = np.zeros((h, w, 3), np.uint8)
    o[:img.shape[0], :img.shape[1]] = img
    return o


def montage_row(r: dict, z, k: int = 5, tag: str = "rot") -> np.ndarray:
    """Native window, enlargements of the crop, the static map under it, the true and chosen glyph fits."""
    i = r["win_index"]
    C, S = z["C"][i], z["S"][i]
    W, h, sh, mask = geom(r["scale"])
    c = WIN
    cells = []
    nat = np.zeros((C.shape[0] * k, C.shape[1] + 4, 3), np.uint8)
    nat[:C.shape[0], 2:2 + C.shape[1]] = C                                 # native size
    cells.append(nat)
    big = _tile(C, k, "crop")
    for dx, dy in [(0, 0)]:
        cv2.circle(big, ((c + dx) * k + k // 2, (c + dy) * k + k // 2), int(MASK_R * r["scale"] * k), (0, 255, 0), 1)
    cells.append(big)
    cells.append(_tile(S, k, "static"))
    pred = r[f"{tag}_pred"]
    for key_s, lab in ((r["truth"], "true"), (pred, "chosen")):
        fit = r[f"{tag}_fits"][key_s]
        T = fit_template(key_s, fit, r["scale"]) * 255.0
        canvas = np.zeros(C.shape[:2], np.float32)
        x0, y0 = c - h + fit[2], c - h + fit[3]
        canvas[y0:y0 + W, x0:x0 + W] = T * mask
        name = GLYPHS[tuple(key_s.split(":"))]["name"]
        cells.append(_tile(canvas, k, f"{lab} {name[:12]} {r[f'{tag}_scores'][key_s]:.2f}"))
    H = max(x.shape[0] for x in cells)
    row = np.hstack([_pad(x, H, x.shape[1]) for x in cells] + [np.zeros((H, 4, 3), np.uint8)])
    txt = f"{r['sid']} {r['t_ms'] / 1000:.2f}s {r['src']} truth {r['cat']}"
    bar = np.zeros((14, row.shape[1], 3), np.uint8)
    cv2.putText(bar, txt, (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([bar, row])


#: Each held-out miss's cause, assigned after viewing the montage (misses.png). Key: sid, t_ms (int), label x, y.
#: Dev misses by (sid, t_ms, label): Killjoy's C and Q markers are unassigned by DisplayIcon correlation (0.27, 0.42)
#: though the crops show them; the 48.45 s Spycam is a teal state the references lack.
DEV_CAUSES = {("d95cfad5693a", 24600, "cypher:trapwire"): {"cause": "occlusion_or_stack", "note": "under a portrait"},
              ("d95cfad5693a", 48450, "cypher:spycam"): {"cause": "variant_missing", "note": "teal Spycam state"},
              **{("dae6f33f3f48", t, lab): {"cause": "variant_missing", "note": "Killjoy marker not assigned"}
                 for t, lab in [(16350, "killjoy:nanoswarm"), (25500, "killjoy:alarmbot"), (28950, "killjoy:alarmbot"),
                                (31050, "killjoy:alarmbot"), (37050, "killjoy:alarmbot"), (41700, "killjoy:alarmbot")]}}
CAUSES: dict = {
    ('02cf738b1c8f', 9300, 244, 161): {"cause": 'size_or_rotation_search', "note": 'large piloted-drone disc; label off centre, fit at the dx=3 shift edge'},
    ('043bafca271a', 1480516, 265, 122): {"cause": 'occlusion_or_stack', "note": 'drone disc between two portraits'},
    ('5822b6646448', 1352158, 81, 286): {"cause": 'size_or_rotation_search', "note": 'label ~6 px off the disc; fit at the (-3,-3) shift corner'},
    ('5822b6646448', 132318, 288, 381): {"cause": 'transparency_over_void', "note": "faded disc; the map's wall line shows through"},
    ('5822b6646448', 1715182, 398, 237): {"cause": 'label_error', "note": 'point on a pink ring ~15 px from the mesh disc'},
    ('5822b6646448', 1643544, 340, 233): {"cause": 'occlusion_or_stack', "note": 'sensor disc stacked under a mesh disc'},
    ('96aa1ae9b96f', 561516, 126, 179): {"cause": 'occlusion_or_stack', "note": 'drone disc under portraits'},
    ('9acf02f98283', 1859500, 161, 118): {"cause": 'occlusion_or_stack', "note": 'drone disc almost covered'},
    ('9acf02f98283', 661516, 114, 86): {"cause": 'size_or_rotation_search', "note": 'glyph visible; Recon Bolt ties at 0.56 under rotation, right upright'},
    ('b3b9defb6fd7', 1811500, 101, 218): {"cause": 'occlusion_or_stack', "note": 'under the self portrait'},
    ('b3b9defb6fd7', 1810000, 114, 222): {"cause": 'occlusion_or_stack', "note": 'under the self portrait'},
    ('b3b9defb6fd7', 961500, 125, 201): {"cause": 'occlusion_or_stack', "note": 'seekers among portraits'},
    ('b3b9defb6fd7', 963000, 144, 195): {"cause": 'occlusion_or_stack', "note": 'seekers among portraits'},
    ('b3b9defb6fd7', 960000, 139, 203): {"cause": 'occlusion_or_stack', "note": 'seekers among portraits'},
    ('b3b9defb6fd7', 960000, 129, 204): {"cause": 'occlusion_or_stack', "note": 'seekers among portraits'},
    ('b7d24102a6f6', 1020000, 143, 179): {"cause": 'occlusion_or_stack', "note": 'trailblazer under a portrait'},
    ('bdfdcf009dba', 1263500, 228, 183): {"cause": 'occlusion_or_stack', "note": 'seekers under a portrait'},
    ('bdfdcf009dba', 1928500, 151, 193): {"cause": 'occlusion_or_stack', "note": 'seekers under a portrait'},
    ('bdfdcf009dba', 1927000, 145, 180): {"cause": 'occlusion_or_stack', "note": 'seekers under a portrait'},
    ('bfad2778a372', 1000000, 223, 107): {"cause": 'occlusion_or_stack', "note": 'two adjacent seekers; near-duplicate marks'},
    ('bfad2778a372', 1000000, 225, 108): {"cause": 'occlusion_or_stack', "note": 'two adjacent seekers; near-duplicate marks'},
    ('bfad2778a372', 998500, 206, 98): {"cause": 'occlusion_or_stack', "note": 'seekers under a portrait'},
    ('bfad2778a372', 998500, 200, 101): {"cause": 'occlusion_or_stack', "note": 'seekers under a portrait'},
    ('bfad2778a372', 2215033, 49, 178): {"cause": 'occlusion_or_stack', "note": 'seekers under a portrait'},
    ('bfad2778a372', 2216566, 45, 171): {"cause": 'occlusion_or_stack', "note": 'seekers under a portrait'},
    ('c40d950031bb', 259000, 88, 166): {"cause": 'occlusion_or_stack', "note": 'drone disc under a portrait'},
    ('e37fdeca944f', 287066, 48, 199): {"cause": 'occlusion_or_stack', "note": 'trailblazer under a portrait'},
    ('eb10db50b1fb', 36450, 128, 108): {"cause": 'occlusion_or_stack', "note": 'trapwire half under the yellow portrait'},
}
CAUSE_CLASSES = ("label_error", "kit_lookalike", "occlusion_or_stack", "variant_missing", "size_or_rotation_search",
                 "transparency_over_void")


def cmd_misses(args) -> None:
    out = Path(args.out)
    d, z = load_scores(out)
    res = d["items"]
    tag = "rot"
    rows, tiles = [], []
    for split in ("heldout", "dev"):
        for r in positives(res, split):
            if r.get(f"{tag}_pred") == r["truth"]:
                continue
            sc = r[f"{tag}_scores"]
            order = sorted(sc, key=lambda k: -sc[k])
            key = (r["sid"], int(r["t_ms"]), int(r["x"]), int(r["y"]))
            cause = CAUSES.get(key) or DEV_CAUSES.get((r["sid"], int(r["t_ms"]), r["cat"]), {})
            rows.append({"split": split, "sid": r["sid"], "t_s": round(r["t_ms"] / 1000, 3), "src": r["src"],
                         "label": r["cat"], "truth": r["truth"], "truth_score": round(sc[r["truth"]], 3),
                         "truth_rank": order.index(r["truth"]) + 1,
                         "top2": [[k, round(sc[k], 3), GLYPHS[tuple(k.split(":"))]["name"]] for k in order[:2]],
                         "margin": round(sc[order[0]] - sc[order[1]], 3), "fit_chosen": r[f"{tag}_fits"][order[0]],
                         "fit_truth": r[f"{tag}_fits"][r["truth"]], "snapped": r["snap"] is not None,
                         "cause": cause.get("cause"), "note": cause.get("note")})
            tiles.append(montage_row(r, z))
    wmax = max(t.shape[1] for t in tiles)
    cols = 2
    per = (len(tiles) + cols - 1) // cols
    colimgs = []
    for ci in range(cols):
        part = tiles[ci * per:(ci + 1) * per]
        colimgs.append(np.vstack([_pad(t, t.shape[0], wmax) for t in part]))
    H = max(c.shape[0] for c in colimgs)
    sheet = np.hstack([_pad(c, H, c.shape[1]) for c in colimgs])
    cv2.imwrite(str(out / "misses.png"), sheet)
    json.dump(rows, open(out / "misses.json", "w"), indent=1)
    held = [r for r in rows if r["split"] == "heldout"]
    print(f"held-out misses {len(held)}, dev misses {len(rows) - len(held)}; held-out causes",
          dict(Counter(r["cause"] for r in held)), "dev causes", dict(Counter(r["cause"] for r in rows if r["split"] == "dev")))
    for r in rows:
        print(f"{r['split'][:4]} {r['sid']} {r['t_s']:9.2f} {r['src']:11s} {r['label']:22s} top2 "
              f"{r['top2'][0][2]}:{r['top2'][0][1]:.2f} {r['top2'][1][2]}:{r['top2'][1][1]:.2f} "
              f"truth#{r['truth_rank']} {r['truth_score']:.2f} m {r['margin']:.2f} {r['cause']}")


def cmd_examples(args) -> None:
    """A montage of right verdicts per ability (up to 6 each), the comparison the misses need."""
    out = Path(args.out)
    d, z = load_scores(out)
    tiles = []
    per = defaultdict(list)
    for r in positives(d["items"]):
        if r.get("rot_pred") == r["truth"]:
            per[r["cat"]].append(r)
    for cat, rs in sorted(per.items()):
        for r in rs[:: max(1, len(rs) // 6)][:6]:
            tiles.append(montage_row(r, z, k=4))
    wmax = max(t.shape[1] for t in tiles)
    cols = 3
    n = (len(tiles) + cols - 1) // cols
    colimgs = [np.vstack([_pad(t, t.shape[0], wmax) for t in tiles[i * n:(i + 1) * n]]) for i in range(cols)]
    H = max(c.shape[0] for c in colimgs)
    cv2.imwrite(str(out / "rights.png"), np.hstack([_pad(c, H, c.shape[1]) for c in colimgs]))


# ------------------------------------------------------------------ vectorised scorer and separability methods


#: Rotation policy from dev labels: Cypher's Trapwire is drawn along its wire (dev fits at 90/180 deg; 17/33 upright
#: against 32/33 rotated); Spycam, the other dev glyph with an orientation, fits upright. Every other ability is
#: upright until the player says otherwise (player tool, question "rotation").
ROTATING = {("Cypher", "C")}


def rots_for(key, rotate) -> list[int]:
    if rotate == "policy":
        return ROTS if key in ROTATING else [0]
    return ROTS if rotate else [0]


def bank(scale: float, keys, rotate=True, canvases=None):
    """Every (key, source, canvas, rotation) template as a masked-pixel row; meta rows (key, canvas, rot, si)."""
    W, h, sh, mask = geom(scale)
    m = mask > 0
    rows, meta = [], []
    for key in keys:
        for si in range(len(sources(key))):
            for c in (CANVAS * scale if canvases is None else canvases):
                for rot in rots_for(key, rotate):
                    T = place(template(key, float(round(c)), rot, si), W)
                    if T[m].std() < 1e-3:
                        continue
                    rows.append(T[m])
                    meta.append((key, float(round(c)), rot, si))
    return np.array(rows, np.float32), meta


def patches(Yw: np.ndarray, scale: float, sh: int | None = None):
    """All shifted masked patches of a stored window (rows: dy-major, then dx), or None off the crop."""
    W, h, sh0, mask = geom(scale)
    sh = sh0 if sh is None else sh
    sub = Yw[WIN - h - sh:WIN + h + sh + 1, WIN - h - sh:WIN + h + sh + 1]
    if np.isnan(sub).any():
        return None
    v = np.lib.stride_tricks.sliding_window_view(sub, (W, W)).reshape(-1, W, W)
    return v[:, mask > 0].astype(np.float32)


def zrows(A: np.ndarray) -> np.ndarray:
    A = A - A.mean(1, keepdims=True)
    return A / (np.linalg.norm(A, axis=1, keepdims=True) + 1e-9)


def pearson(P, T, ctx=None):
    return zrows(P) @ zrows(T).T


def wpearson(P, T, Wp=None, Wt=None):
    """Pearson with pixel weights Wp[shift, px] * Wt[template, px] (either may be None), vectorised."""
    Wp = np.ones_like(P) if Wp is None else Wp
    Wt = np.ones_like(T) if Wt is None else Wt
    sw = Wp @ Wt.T
    sx = (Wp * P) @ Wt.T / sw
    st = Wp @ (Wt * T).T / sw
    sxt = (Wp * P) @ (Wt * T).T / sw
    sxx = (Wp * P * P) @ Wt.T / sw
    stt = Wp @ (Wt * T * T).T / sw
    return (sxt - sx * st) / np.sqrt(np.maximum(sxx - sx ** 2, 1e-9) * np.maximum(stt - st ** 2, 1e-9))


def whitened(P, T, L):
    """Pearson after whitening: rows mean-removed, then x @ L (L L^T = Sigma^-1)."""
    Pw = (P - P.mean(1, keepdims=True)) @ L
    Tw = (T - T.mean(1, keepdims=True)) @ L
    return zrows(Pw) @ zrows(Tw).T


def whitener(S: np.ndarray, lam: float) -> np.ndarray:
    """L with L L^T = (shrunk Sigma)^-1; shrinkage toward the diagonal plus a ridge."""
    d = np.diag(S)
    S2 = (1 - lam) * S + lam * np.diag(d) + 1e-3 * d.mean() * np.eye(len(d))
    w, V = np.linalg.eigh(S2)
    return (V / np.sqrt(np.maximum(w, 1e-9))) @ V.T


def per_key(S: np.ndarray, meta, keys):
    """Max over shifts and templates per key: {key: (score, (canvas, rot, si, shift_index))}."""
    best_t = S.max(0)
    arg_s = S.argmax(0)
    out = {}
    for j, (key, c, rot, si) in enumerate(meta):
        if key not in keys:
            continue
        if key not in out or best_t[j] > out[key][0]:
            out[key] = (float(best_t[j]), (c, rot, si, int(arg_s[j])))
    return out


class Engine:
    """Scores stored windows with one method; template banks cached per scale."""

    def __init__(self, d, z, rotate=True, sh=None, canvases=None):
        self.items = [r for r in d["items"] if not r.get("refused") and r.get("kit")]
        self.z, self.rotate, self.sh, self.canvases = z, rotate, sh, canvases
        self.keys = sorted({tuple(k.split(":")) for r in self.items for k in r["kit"]})
        self.banks = {}

    def bank(self, scale):
        s = round(scale, 3)
        if s not in self.banks:
            self.banks[s] = bank(scale, self.keys, self.rotate,
                                 None if self.canvases is None else np.asarray(self.canvases) * scale)
        return self.banks[s]

    def run(self, fn, items=None):
        """fn(P, T, scale, meta, item) -> score matrix (shifts x templates). Returns {win_index: {key_s: (score, fit)}}."""
        out = {}
        for r in (items or self.items):
            P = patches(self.z["Y"][r["win_index"]], r["scale"], self.sh)
            if P is None:
                continue
            T, meta = self.bank(r["scale"])
            kk = {tuple(k.split(":")) for k in r["kit"]}
            sel = [j for j, m in enumerate(meta) if m[0] in kk]
            mt = [meta[j] for j in sel]
            S = fn(P, T[sel], r["scale"], mt, r)
            out[r["win_index"]] = {f"{k[0]}:{k[1]}": v for k, v in per_key(S, mt, kk).items()}
        return out


def verdicts(scores: dict, items, split="heldout") -> dict:
    P = [r for r in positives(items, split) if r["win_index"] in scores]
    right = [r for r in P if max(scores[r["win_index"]], key=lambda k: scores[r["win_index"]][k][0]) == r["truth"]]
    ids = {r["win_index"] for r in right}
    per = defaultdict(lambda: [0, 0])
    for r in P:
        per[r["cat"]][1] += 1
        per[r["cat"]][0] += r["win_index"] in ids
    marg = []
    for r in P:
        s = scores[r["win_index"]]
        marg.append(s[r["truth"]][0] - max(v[0] for k, v in s.items() if k != r["truth"]))
    return {"top1": f"{len(right)}/{len(P)}", "n_right": len(right), "n": len(P), "right_ids": sorted(ids),
            "per": {k: f"{a}/{n}" for k, (a, n) in sorted(per.items())},
            "margin_median": round(float(np.median(marg)), 3) if marg else None}


def d_prime(scores: dict, items, split="heldout", min_n=8) -> dict:
    """Per ability: d' of (true score - best wrong score) and the wrong abilities it lies closest to."""
    by = defaultdict(list)
    for r in positives(items, split):
        if r["win_index"] not in scores:
            continue
        s = scores[r["win_index"]]
        wk = max((k for k in s if k != r["truth"]), key=lambda k: s[k][0])
        by[r["cat"]].append((s[r["truth"]][0] - s[wk][0], GLYPHS[tuple(wk.split(":"))]["name"]))
    out = {}
    for cat, v in sorted(by.items()):
        m = np.array([x[0] for x in v])
        out[cat] = {"n": len(v), "d_prime": round(float(m.mean() / (m.std() + 1e-9)), 2) if len(v) >= min_n else None,
                    "mean_margin": round(float(m.mean()), 3), "closest_wrong": Counter(x[1] for x in v).most_common(2)}
    return out


def kit_confusability(keys_by_kit, scale=1.0) -> dict:
    """Reference-only closeness: best Pearson between two kit glyphs (all sources, upright, canvas 16)."""
    out = {}
    for kit_name, keys in keys_by_kit.items():
        T, meta = bank(scale, keys, False, canvases=[16.0])
        Z = zrows(T)
        rows = []
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                ia = [j for j, m in enumerate(meta) if m[0] == a]
                ib = [j for j, m in enumerate(meta) if m[0] == b]
                if ia and ib:
                    rows.append((round(float((Z[ia] @ Z[ib].T).max()), 3), GLYPHS[a]["name"], GLYPHS[b]["name"]))
        out[kit_name] = sorted(rows, reverse=True)
    return out


def _resample(Yw: np.ndarray, f: float) -> np.ndarray:
    n = int(round(Yw.shape[0] * f)) | 1
    return cv2.resize(Yw, (n, n), interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)


def dev_training(eng: Engine, scale: float) -> dict:
    """Everything the methods learn, from dev sessions only:
    - bg: background patches near labelled icons (window offsets >= 5 px from the centre), mean-removed;
    - res: residuals of dev positives after their true glyph's affine fit (rot policy as in `eng`);
    - opacity: the disc's luma against the baked static map under it (slope = 1 - alpha_disc), the glyph's
      luma at its brightest template pixels, and the residual sd at glyph pixels (sensor noise).
    Windows of the other scale are resampled to this one (INTER_AREA to shrink, linear to enlarge)."""
    W, h, sh, mask = geom(scale)
    m = mask > 0
    res, bg, disc_xy, glyph_y, glyph_res = [], [], [], [], []
    T, meta = eng.bank(scale)
    for r in eng.items:
        if r["split"] != "dev":
            continue
        Yw = eng.z["Y"][r["win_index"]]
        if np.isnan(Yw).any():
            continue
        if abs(r["scale"] - scale) > 0.01:
            Yw = _resample(Yw, scale / r["scale"])
        c = Yw.shape[0] // 2
        v = np.lib.stride_tricks.sliding_window_view(Yw, (W, W))
        for oy in range(-c + h, c - h + 1, 3):
            for ox in range(-c + h, c - h + 1, 3):
                if max(abs(ox), abs(oy)) >= 5:
                    bg.append(v[c - h + oy, c - h + ox][m])
        if r["cat"] in ("NOT", "smoke") or not r.get("truth") or abs(r["scale"] - scale) > 0.01:
            continue
        P = patches(eng.z["Y"][r["win_index"]], scale)
        kk = tuple(r["truth"].split(":"))
        sel = [j for j, mm in enumerate(meta) if mm[0] == kk]
        S = pearson(P, T[sel])
        si, tj = np.unravel_index(np.argmax(S), S.shape)
        p, t = P[si], T[sel][tj]
        A = np.vstack([t, np.ones_like(t)]).T
        coef, *_ = np.linalg.lstsq(A, p, rcond=None)
        e = p - A @ coef
        res.append(e)
        if r.get("static"):
            st = cv2.cvtColor(eng.z["S"][r["win_index"]], cv2.COLOR_BGR2YCrCb)[..., 0].astype(np.float32)
            dy, dx = si // (2 * sh + 1) - sh, si % (2 * sh + 1) - sh
            sp = st[WIN - h + dy:WIN - h + dy + W, WIN - h + dx:WIN - h + dx + W][m]
            off = t < 0.05 * t.max()
            disc_xy.append(np.stack([sp[off], p[off]], 1))
            on = t > 0.6 * t.max()
            glyph_y.append(p[on])
            glyph_res.append(e[on])
    bg = np.array(bg, np.float32)
    bg -= bg.mean(1, keepdims=True)
    out = {"bg": bg, "res": np.array(res, np.float32)}
    if disc_xy:
        xy = np.concatenate(disc_xy)
        A = np.vstack([xy[:, 0], np.ones(len(xy))]).T
        (slope, icpt), *_ = np.linalg.lstsq(A, xy[:, 1], rcond=None)
        out["alpha_disc"] = float(np.clip(1 - slope, 0, 1))
        out["disc_luma"] = float(icpt / max(1 - slope, 1e-3)) if slope < 1 else None
        out["glyph_luma_median"] = float(np.median(np.concatenate(glyph_y)))
        out["sensor_sd"] = float(np.std(np.concatenate(glyph_res)))
        out["n_disc_px"] = int(len(xy))
    return out


def chroma_weight(C: np.ndarray, scale: float, sh: int | None = None, s0: float = 0.35) -> np.ndarray:
    """Per shift, per masked pixel: a soft weight that falls with HSV saturation (portraits, rims, team colours
    occlude the dark neutral disc and its white glyph). Soft, never binarised: w = clip(1 - s / s0, 0, 1)^2."""
    W, h, sh0, mask = geom(scale)
    sh = sh0 if sh is None else sh
    hsv = cv2.cvtColor(C, cv2.COLOR_BGR2HSV).astype(np.float32)
    s = hsv[..., 1] / 255.0
    w = np.clip(1 - s / s0, 0, 1) ** 2 + 1e-3
    sub = w[WIN - h - sh:WIN + h + sh + 1, WIN - h - sh:WIN + h + sh + 1]
    v = np.lib.stride_tricks.sliding_window_view(sub, (W, W)).reshape(-1, W, W)
    return v[:, mask > 0].astype(np.float32)


def composite_weights(T: np.ndarray, tr: dict, scale: float) -> np.ndarray:
    """(d) The composite model's per-pixel noise variance for each template: a glyph drawn white at opacity
    alpha_g over a disc of opacity alpha_disc over the map, so map texture leaks through as
    (1 - alpha_disc)(1 - alpha_g G) and the sensor adds sensor_sd; weights are its inverse."""
    a_d = tr.get("alpha_disc", 0.8)
    bgv = tr["bg"].var(0)
    s0 = tr.get("sensor_sd", 6.0)
    G = T / np.maximum(T.max(1, keepdims=True), 1e-6)
    var = ((1 - a_d) * (1 - G)) ** 2 * bgv[None] + s0 ** 2
    return (1.0 / var).astype(np.float32)


def fisher_weights(T: np.ndarray, meta, scale: float, tr: dict) -> np.ndarray:
    """(a) Per kit and (canvas, rot): between-glyph variance of the kit's mean templates over the within
    variance (dev residual variance, scaled to the between mean, plus the template's own +-1 px jitter)."""
    W, h, sh, mask = geom(scale)
    noise = tr["res"].var(0) if len(tr["res"]) >= 5 else tr["bg"].var(0)
    groups = defaultdict(list)
    for j, (key, c, rot, si) in enumerate(meta):
        groups[(c, rot)].append(j)
    Wt = np.empty_like(T)
    for js in groups.values():
        mu = defaultdict(list)
        for j in js:
            mu[meta[j][0]].append(T[j])
        M = np.array([np.mean(v, 0) for v in mu.values()])
        between = M.var(0) if len(M) > 1 else np.ones(T.shape[1], np.float32)
        jit = []
        for j in js:
            full = np.zeros((W, W), np.float32)
            full[mask > 0] = T[j]
            jit.append(np.var([np.roll(full, sft, ax)[mask > 0] for sft, ax in ((1, 0), (-1, 0), (1, 1), (-1, 1))]
                              + [T[j]], 0))
        within = noise / max(noise.mean(), 1e-9) * between.mean() + np.mean(jit, 0)
        w = between / (within + 1e-6)
        w = w / max(w.mean(), 1e-9) + 0.05
        for j in js:
            Wt[j] = w
    return Wt


def rerank_features(s: dict, key: str) -> list[float]:
    others = [v[0] for k, v in s.items() if k != key]
    sc, (c, rot, si, _) = s[key]
    return [sc, sc - max(others), sc - float(np.mean(others)), float(si > 0)]


def rerank(base: dict, items) -> dict:
    """(c) A kit-agnostic linear discriminant over per-candidate score features (score, margin to the best other,
    margin to the mean other, marker-vs-icon source), trained on dev candidates (right vs wrong) only. Per-kit LDA
    over the 4 glyph scores cannot be trained: dev holds labels for Cypher and Killjoy only."""
    X, y = [], []
    for r in positives(items, "dev"):
        s = base.get(r["win_index"])
        if not s:
            continue
        for k in s:
            X.append(rerank_features(s, k))
            y.append(k == r["truth"])
    X, y = np.array(X), np.array(y)
    mu1, mu0 = X[y].mean(0), X[~y].mean(0)
    Sw = np.cov(X[y].T) + np.cov(X[~y].T) + 1e-4 * np.eye(X.shape[1])
    w = np.linalg.solve(Sw, mu1 - mu0)
    out = {}
    for wi, s in base.items():
        out[wi] = {k: (float(np.dot(w, rerank_features(s, k))), v[1]) for k, v in s.items()}
    return out, w.tolist()


def method_suite(d, z, rotate=True, lam=None) -> tuple:
    """Baseline and the separability methods, each dev-trained or label-free, scored once on held-out."""
    eng = Engine(d, z, rotate=rotate)
    items = eng.items
    scores, notes = {}, {}
    scales = sorted({round(r["scale"], 3) for r in items})
    train = {s: dev_training(eng, s) for s in scales}
    notes["opacity"] = {str(s): {k: v for k, v in tr.items() if not isinstance(v, np.ndarray)} for s, tr in train.items()}
    notes["n_dev_bg"] = {str(s): int(len(tr["bg"])) for s, tr in train.items()}
    notes["n_dev_res"] = {str(s): int(len(tr["res"])) for s, tr in train.items()}
    scores["baseline"] = eng.run(lambda P, T, s, meta, r: pearson(P, T))
    # (b) whitened matched filter: shrinkage chosen on dev only (dev top-1, then dev median margin)
    lams = (0.3, 0.6, 0.9)
    for name, which in (("b_white_bg", "bg"), ("b_white_res_bg", "both")):
        cand = {}
        for lm in lams:
            Ls = {}
            for s, tr in train.items():
                S = np.cov(tr["bg"].T) if which == "bg" else 0.5 * np.cov(tr["bg"].T) + 0.5 * np.cov(tr["res"].T)
                Ls[s] = whitener(S, lm)
            sc = eng.run(lambda P, T, s, meta, r, Ls=Ls: whitened(P, T, Ls[round(s, 3)]))
            dv = verdicts(sc, items, "dev")
            cand[lm] = (dv["n_right"], dv["margin_median"] or 0, sc)
            scores[f"{name}_sweep_lam{lm}"] = sc
        best = max(cand, key=lambda lm: cand[lm][:2]) if lam is None else lam
        scores[name] = cand[best][2]
        notes[f"{name}_lam_dev_selected"] = best
    # (a) Fisher pixel weights per kit
    scores["a_fisher"] = eng.run(lambda P, T, s, meta, r: wpearson(P, T, None, fisher_weights(T, meta, s, train[round(s, 3)])))
    # (c) reranker over the baseline's per-candidate scores, trained on dev
    scores["c_rerank"], notes["c_rerank_w"] = rerank(scores["baseline"], items)
    # (d) composite noise model at the measured opacity
    scores["d_composite"] = eng.run(lambda P, T, s, meta, r: wpearson(P, T, None, composite_weights(T, train[round(s, 3)], s)))
    # (e) occlusion: soft chroma weight per pixel (portraits and rims drawn over the disc); no training
    scores["e_occlusion"] = eng.run(lambda P, T, s, meta, r: wpearson(P, T, chroma_weight(eng.z["C"][r["win_index"]], s), None))
    scores["e_occlusion+d"] = eng.run(lambda P, T, s, meta, r: wpearson(
        P, T, chroma_weight(eng.z["C"][r["win_index"]], s), composite_weights(T, train[round(s, 3)], s)))
    return scores, notes, eng


def cmd_separate(args) -> None:
    out = Path(args.out)
    d, z = load_scores(out)
    t0 = time.time()
    report = {"version": VERSION, "build": BUILD, "split": {"dev": sorted(DEV), "heldout": "every other session"}}
    eng = Engine(d, z, rotate=True)
    sc = eng.run(lambda P, T, s, meta, r: pearson(P, T))
    diffs = [abs(sc[r["win_index"]][r["rot_pred"]][0] - r["rot_score"]) for r in eng.items
             if r["win_index"] in sc and r.get("rot_pred")]
    agree = sum(max(sc[r["win_index"]], key=lambda k: sc[r["win_index"]][k][0]) == r["rot_pred"]
                for r in eng.items if r["win_index"] in sc and r.get("rot_pred"))
    report["instrument"] = {"max_abs_score_diff_vs_cv2": round(float(max(diffs)), 5),
                            "verdict_agreement": f"{agree}/{len(diffs)}"}
    print("instrument", report["instrument"], flush=True)
    # search diagnostic: does a wider centre and size search recover the misses? (cause class, not a method)
    for name, kw in (("search_shift5", {"sh": 5}), ("search_canvas9_26", {"canvases": np.arange(9, 27, 1.0)})):
        e2 = Engine(d, z, rotate=True, **kw)
        v = verdicts(e2.run(lambda P, T, s, meta, r: pearson(P, T)), e2.items)
        report[name] = {k: v[k] for k in ("top1", "per", "right_ids")}
        print(f"{name:20s} held {v['top1']}", flush=True)
    for rot in (True, False, "policy"):
        tag = {True: "rot", False: "norot", "policy": "rotpolicy"}[rot]
        scores, notes, eng = method_suite(d, z, rotate=rot)
        report[tag] = {"notes": notes, "methods": {}}
        for k, v in scores.items():
            vh, vd = verdicts(v, eng.items), verdicts(v, eng.items, "dev")
            report[tag]["methods"][k] = {"heldout": vh["top1"], "dev": vd["top1"], "margin_median": vh["margin_median"],
                                         "per": vh["per"], "right_ids": vh["right_ids"]}
            if "sweep" not in k:
                report[tag]["methods"][k]["d_prime"] = d_prime(v, eng.items)
            print(f"{tag:9s} {k:26s} held {vh['top1']:8s} dev {vd['top1']:6s} margin {vh['margin_median']} {vh['per']}",
                  flush=True)
        print(f"  {time.time() - t0:.0f}s notes {json.dumps(notes, default=str)[:600]}", flush=True)
    kits = defaultdict(list)
    for k in Engine(d, z).keys:
        kits[k[0]].append(k)
    report["kit_confusability_reference"] = kit_confusability(kits)
    report["wall_s"] = round(time.time() - t0, 1)
    json.dump(report, open(out / "separability.json", "w"), indent=1, default=str)


# ------------------------------------------------------------------ follow in time, gated by the stored portraits

FOLLOW_VERSION = "minimap-glyph-follow-0.2.0"
FOLLOW_MS = 3000.0     # how far after the label the object is followed
N_CLEAN = 8            # the decision stops after this many unoccluded frames
OCC_R = 17.0           # a portrait centre within this (px x scale) touches the r = 8.5 scoring disc (portrait r ~8.5)
SAME_R = 2.5           # an ally detection this close is the followed icon itself (the ally reader fits moving discs)
REACH = (4.0, 2.0, 24.0)  # a disc may move this far (px x scale) from the last fix: base + per frame since, cap
ICON_SCORE = 0.4       # the best kit score (label-free) a proposed disc needs to count as the followed icon
MAP_CORR = 0.7         # a proposed disc whose luma correlates this well with the baked static is map, not icon


def vision_rows(sid: str, times) -> dict:
    """{t_ms: (widget, [(role, x, y)])} from the stored team_vision frames at the asked times (never rerun)."""
    want = {round(float(t), 3) for t in times}
    out = {}
    f = STORE / "events" / "team_vision" / f"{sid}.jsonl"
    if not f.exists():
        return out
    rx = re.compile(r'"t_ms":([0-9.eE+-]+)')
    for ln in open(f, encoding="utf-8"):
        if '"kind":"frame"' not in ln[:200]:
            continue
        m = rx.search(ln)
        if not m or round(float(m.group(1)), 3) not in want:
            continue
        r = json.loads(ln)
        out[round(float(r["t_ms"]), 3)] = (r.get("widget"), [(i["role"], float(i["x"]), float(i["y"]))
                                                             for i in (r.get("icons") or [])])
    return out


def portrait_cover(p, icons, scale) -> str | None:
    """Why a stored portrait covers the icon at p, or None. The self icon always counts; an ally detection counts
    in the ring SAME_R..OCC_R, or when two sit on the icon (one of them is the icon itself)."""
    same = 0
    for role, x, y in icons:
        d = float(np.hypot(x - p[0], y - p[1]))
        if d > OCC_R * scale:
            continue
        if role == "self":
            return "self_portrait"
        if d > SAME_R * scale:
            return "ally_portrait"
        same += 1
    return "ally_stack" if same > 1 else None


def window_patches(Y: np.ndarray, p, scale: float, sh: int):
    """Masked patches of a luma crop around p for every integer shift within +-sh (dy-major), or None off the crop."""
    W, h, _, mask = geom(scale)
    ix, iy = int(round(p[0])), int(round(p[1]))
    y0, x0 = iy - h - sh, ix - h - sh
    if y0 < 0 or x0 < 0 or iy + h + sh + 1 > Y.shape[0] or ix + h + sh + 1 > Y.shape[1]:
        return None
    sub = Y[y0:iy + h + sh + 1, x0:ix + h + sh + 1]
    v = np.lib.stride_tricks.sliding_window_view(sub, (W, W)).reshape(-1, W, W)
    return v[:, mask > 0].astype(np.float32)


_fbanks: dict = {}


def kit_bank(scale: float, kit_keys: tuple):
    k = (round(scale, 3), kit_keys)
    if k not in _fbanks:
        T, meta = bank(scale, list(kit_keys), rotate=True)
        _fbanks[k] = (zrows(T), np.array([kit_keys.index(m[0]) for m in meta]))
    return _fbanks[k]


def frame_scores(Y, p, scale, kit_keys):
    """Per-key best score over the usual +-SHIFT centre search at p (the eval's matcher, vectorised)."""
    sh = geom(scale)[2]
    P = window_patches(Y, p, scale, sh)
    if P is None:
        return None
    Tz, owner = kit_bank(scale, kit_keys)
    S = zrows(P) @ Tz.T                                          # shifts x templates
    per = np.full(len(kit_keys), -2.0, np.float32)
    np.maximum.at(per, owner, S.max(0))
    return per


def map_like(Y, static_Y, p, scale) -> bool:
    """True when the crop's luma inside the icon disc at p correlates with the baked static's (a wall notch the
    proposer reads as a dark disc), Pearson >= MAP_CORR."""
    a = window_patches(Y, p, scale, 0)
    b = window_patches(static_Y, p, scale, 0)
    if a is None or b is None or b.std() < 1e-3:
        return False
    return float((zrows(a) @ zrows(b).T)[0, 0]) >= MAP_CORR


def follow_item(r, crops, vis, terms, static_Y=None):
    """Follow one labelled icon over the cached frames after it; decide once from the unoccluded frames.

    The ability-icon owner's proposer (`ability_icons.propose_icons`) supplies the dark discs; the track moves to
    the nearest disc within REACH of its last fix (continue the prior; the reach widens each frame the disc is
    missing) that the baked static does not draw and whose best kit score, label-free (the max over the caster's
    kit, never the true key), reaches ICON_SCORE. The stored
    team_vision portraits gate each frame (`portrait_cover`); the kit's per-key scores are averaged over the clean
    frames, the labelled frame included when clean."""
    from reticle import ability_icons
    kit_keys = tuple(tuple(k.split(":")) for k in r["kit"])
    scale = r["scale"]
    p = (r["cx"], r["cy"])
    steps, clean, since = [], [], 0
    for t, crop in crops:
        widget, icons = vis.get(round(t, 3), (None, None))
        Y = luma(crop)
        per, why = None, None
        if t <= r["t_held"]:                                    # the labelled frame keeps its snapped centre
            per = frame_scores(Y, p, scale, kit_keys)
        elif terms is None:
            why = "no_slab_terms"
        else:
            since += 1
            reach = min(REACH[0] + REACH[1] * (since - 1), REACH[2]) * scale
            best = None
            near = sorted((float(np.hypot(q["cx"] - p[0], q["cy"] - p[1])), i, q)
                          for i, q in enumerate(ability_icons.propose_icons(crop, terms)))
            for dq, _, q in near:                              # nearest first: continue the prior
                if dq > reach:
                    break
                if static_Y is not None and map_like(Y, static_Y, (q["cx"], q["cy"]), scale):
                    continue                                    # the baked map draws this disc: not an icon
                s = frame_scores(Y, (q["cx"], q["cy"]), scale, kit_keys)
                if s is not None and s.max() >= ICON_SCORE:
                    best = (q, s)
                    break
            if best is None:
                why = "no_disc"
            else:
                p, per, since = (float(best[0]["cx"]), float(best[0]["cy"])), best[1], 0
        if per is None and why is None:
            why = "off_crop"
        why = why or ("no_vision_row" if widget is None else None) or \
            (f"widget_{widget}" if widget != "drawn" else None) or portrait_cover(p, icons, scale)
        steps.append({"t": t, "x": float(p[0]), "y": float(p[1]), "skip": why,
                      "scores": None if per is None else [round(float(s), 4) for s in per]})
        if why is None:
            clean.append(per)
        if len(clean) >= N_CLEAN:
            break
    out = {"steps": steps, "n_clean": len(clean), "kit": [f"{k[0]}:{k[1]}" for k in kit_keys]}
    if clean:
        m = np.mean(clean, 0)
        o = np.argsort(-m)
        out["pred"] = f"{kit_keys[o[0]][0]}:{kit_keys[o[0]][1]}"
        out["mean"] = {f"{k[0]}:{k[1]}": round(float(v), 4) for k, v in zip(kit_keys, m)}
        out["margin"] = float(m[o[0]] - (m[o[1]] if len(o) > 1 else -1.0))
        out["decided_by"] = "follow"
    else:
        out["pred"], out["decided_by"] = r.get("rot_pred"), "labelled_frame_no_clean_frame"
    return out


def follow_row(x: dict, got: dict, k: int = 4, R: int = 16, n_used: int = 6, n_skip: int = 3) -> np.ndarray:
    """One montage row: the labelled frame, then the frames the follow used (green ring) and some it skipped
    (red ring, reason), each centred on the tracked position; nearest-neighbour enlargement, display only."""
    def cell(t, px, py, col, cap):
        crop = got[t]
        ix, iy = int(round(px)), int(round(py))
        w = np.zeros((2 * R + 1, 2 * R + 1, 3), np.uint8)
        ya, yb, xa, xb = max(0, iy - R), min(crop.shape[0], iy + R + 1), max(0, ix - R), min(crop.shape[1], ix + R + 1)
        if ya < yb and xa < xb:
            w[ya - iy + R:yb - iy + R, xa - ix + R:xb - ix + R] = crop[ya:yb, xa:xb]
        big = cv2.resize(w, (w.shape[1] * k, w.shape[0] * k), interpolation=cv2.INTER_NEAREST)
        cv2.circle(big, (R * k + k // 2, R * k + k // 2), int(MASK_R * x["scale"] * k), col, 1)
        bar = np.zeros((12, big.shape[1], 3), np.uint8)
        cv2.putText(bar, cap[:22], (1, 9), cv2.FONT_HERSHEY_SIMPLEX, 0.3, col, 1, cv2.LINE_AA)
        return np.vstack([big, bar])

    st = [s for s in x["steps"] if "x" in s]
    cells = [cell(x["t_held"], x["cx"], x["cy"], (255, 255, 255), "label")] if st else []
    used = [s for s in st if s["skip"] is None][:n_used]
    skip = [s for s in st if s["skip"] is not None][:n_skip]
    for s in sorted(used + skip, key=lambda s: s["t"]):
        ok = s["skip"] is None
        cap = f"+{(s['t'] - x['t_held']) / 1000:.2f} " + ("used" if ok else s["skip"].replace("_portrait", ""))
        cells.append(cell(s["t"], s["x"], s["y"], (0, 220, 0) if ok else (0, 0, 255), cap))
    row = np.hstack([np.pad(c, ((0, 0), (0, 3), (0, 0))) for c in cells]) if cells else np.zeros((40, 400, 3), np.uint8)
    mean = x.get("mean") or {}
    top = sorted(mean, key=lambda q: -mean[q])[:2]
    txt = (f"{x['split'][:4]} {x['sid']} {x['t_ms'] / 1000:.2f}s {x['cat']} base {x['base_pred']} -> {x['pred']} "
           f"[{x['decided_by']}, {x['n_clean']} clean] " + " ".join(f"{q.split(':')[1]} {mean[q]:.2f}" for q in top))
    bar = np.zeros((14, max(row.shape[1], 900), 3), np.uint8)
    cv2.putText(bar, txt, (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([bar, _pad(row, row.shape[0], bar.shape[1]), np.zeros((4, bar.shape[1], 3), np.uint8)])


def cmd_follow(args) -> None:
    out = Path(args.out)
    d = json.load(open(out / "items.json", encoding="utf-8"))
    build_extra(None if d["meta"]["states"] == "all" else PROBE_STATES, answers=d["meta"].get("answers", False))
    only = set(args.only.split(",")) if args.only else None
    P = [r for r in positives(d["items"]) if only is None or r["sid"] in only]
    by = defaultdict(list)
    for r in P:
        by[r["sid"]].append(r)
    if only:
        out = out / "follow-sample"
        out.mkdir(exist_ok=True)
    t0 = time.time()
    res, unavailable, tiles = [], Counter(), []
    for sid, its in sorted(by.items()):
        c, why, _ = crop_cache(sid)
        x0, y0, x1, y1 = c.rect_of("minimap")
        h = np.asarray(c.holds())
        plan = {id(r): [float(t) for t in h[(h >= r["t_held"]) & (h <= r["t_held"] + FOLLOW_MS)]] for r in its}
        need = sorted({t for v in plan.values() for t in v})
        vis = vision_rows(sid, need)
        try:
            from reticle import geometry
            st = geometry.reference_static(sid, str(STORE))
            static_Y = luma(st if st.ndim == 3 else cv2.cvtColor(st, cv2.COLOR_GRAY2BGR))
        except (SystemExit, Exception):  # noqa: BLE001
            static_Y = None
            unavailable["no_baked_static"] += 1
        got = {s.t_ms: s.frame[y0:y1, x0:x1].copy() for s in c.samples(need, rois=["minimap"])}
        for r in its:
            ts = plan[id(r)]
            miss = sum(t not in got for t in ts)
            if len(ts) < 2:
                unavailable["no_following_frame"] += 1
            unavailable["frames_not_decoded_from_cache"] += miss
            first = next((got[t] for t in ts if t in got), None)
            terms = icon_terms(sid, first.shape) if first is not None else None
            sY = static_Y if first is not None and static_Y is not None and static_Y.shape == first.shape[:2] else None
            f = follow_item(r, [(t, got[t]) for t in ts if t in got], vis, terms, sY)
            res.append({"sid": sid, "t_ms": r["t_ms"], "x": r["x"], "y": r["y"], "cat": r["cat"], "truth": r["truth"],
                        "split": r["split"], "win_index": r["win_index"], "scale": r["scale"], "cx": r["cx"],
                        "cy": r["cy"], "t_held": r["t_held"], "base_pred": r.get("rot_pred"),
                        "base_scores": r.get("rot_scores"), "n_following_cached": len(ts), **f})
            if r.get("rot_pred") != r["truth"] or f["pred"] != r["truth"]:
                tiles.append((res[-1], follow_row(res[-1], got)))
        print(f"  {sid}: {len(its)} items, {time.time() - t0:.0f}s", flush=True)
    for name, sel in (("follow_misses.png", lambda x: x["pred"] != x["truth"]),
                      ("follow_baseline_misses.png", lambda x: x["base_pred"] != x["truth"])):
        rows = [im for x, im in tiles if x["split"] == "heldout" and sel(x)] + \
               [im for x, im in tiles if x["split"] == "dev" and sel(x)]
        if rows:
            Wm = max(im.shape[1] for im in rows)
            cv2.imwrite(str(out / name), np.vstack([_pad(im, im.shape[0], Wm) for im in rows]))
    summ = {"version": FOLLOW_VERSION, "base": d["meta"]["version"], "build": BUILD,
            "answers": d["meta"].get("answers", False),
            "params": {"FOLLOW_MS": FOLLOW_MS, "N_CLEAN": N_CLEAN, "OCC_R": OCC_R, "SAME_R": SAME_R,
                       "REACH": REACH, "ICON_SCORE": ICON_SCORE, "MAP_CORR": MAP_CORR, "proposer": "reticle.ability_icons.propose_icons"},
            "inputs": {"crops": "roi_cache minimap", "portraits": "events/team_vision frame icons (stored)"},
            "unavailable": dict(unavailable), "wall_s": round(time.time() - t0, 1)}
    for split in ("heldout", "dev"):
        S = [r for r in res if r["split"] == split]
        summ[split] = {"before": f"{sum(r['base_pred'] == r['truth'] for r in S)}/{len(S)}",
                       "after": f"{sum(r['pred'] == r['truth'] for r in S)}/{len(S)}",
                       "fixed": sum(r["pred"] == r["truth"] != r["base_pred"] for r in S),
                       "broken": sum(r["base_pred"] == r["truth"] != r["pred"] for r in S),
                       "no_clean_frame": sum(r["decided_by"] != "follow" for r in S)}
    json.dump({"meta": summ, "items": res}, open(out / "follow.json", "w"), indent=1, default=float)
    print(json.dumps(summ, indent=1))


# ------------------------------------------------------------------ the held-out labelling pass, scored once

HELDOUT_VERSION = "minimap-glyph-heldout-score-0.1.0"
HELDOUT_OUT = STORE / "analysis" / "minimap-heldout-score-20261004"
SNAP_R = 8.0           # cmd_score's snap reach (px x scale); detection counts a disc this near a mark as found
ICON_MARKS = ("named", "unsure", "smoke", "other_agent")   # marks that claim an ability icon at the point


def mark_class(m: dict) -> str:
    """named (a kit key agent:slot), smoke, other_agent, other (typed), or unsure (an icon, ability unsure)."""
    a = m.get("ability")
    if a is None:
        return "unsure"
    if ":" in a:
        return "named"
    return a


def heldout_subsets(row: dict) -> list[str]:
    """The subsets fixed in the queue: the headline (after_cast or control, neither dev nor near a tuned label);
    dev_session and near_tuned_label apart (they may overlap); audit-only frames apart."""
    out = []
    if row["kind"] == "audit_excluded":
        out.append("audit_only")
    elif not row["dev_session"] and not row["near_tuned_label"]:
        out.append("headline")
    if row["dev_session"]:
        out.append("dev_session")
    if row["near_tuned_label"]:
        out.append("near_tuned_label")
    return out


def naming_summary(marks: list[dict], subset: str) -> dict:
    """right / wrong / refused for the follow verdict (the matcher's final) and the single-frame verdict."""
    M = [m for m in marks if m["class"] == "named" and subset in m["subsets"]]
    out = {"n": len(M), "truth_outside_kit": sum(not m["truth_in_kit"] for m in M)}
    for tag in ("follow", "base"):
        right = sum(m.get(f"{tag}_pred") == m["truth"] for m in M)
        refused = sum(m.get(f"{tag}_pred") is None for m in M)
        out[tag] = {"right": right, "wrong": len(M) - right - refused, "refused": refused,
                    "accuracy": round(right / len(M), 4) if M else None}
    per_agent, per_ability = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for m in M:
        for d, k in ((per_agent, m["agent"]), (per_ability, f"{m['truth']} {m['truth_name']}")):
            d[k][1] += 1
            d[k][0] += m.get("follow_pred") == m["truth"]
    out["per_agent"] = {k: f"{a}/{n}" for k, (a, n) in sorted(per_agent.items())}
    out["per_ability"] = {k: f"{a}/{n}" for k, (a, n) in sorted(per_ability.items())}
    out["confusions"] = {f"{t} -> {p}": n for (t, p), n in Counter(
        (m["truth"], m.get("follow_pred")) for m in M if m.get("follow_pred") != m["truth"]).most_common()}
    return out


def detection_summary(frames_: list[dict], subset: str | None = None, kind=None, nothing=None) -> dict:
    """Sure icon marks found by a proposer disc within SNAP_R x scale, and discs no mark explains, raw and after
    the follow's gates (static map, ICON_SCORE) and its stored-portrait gate. A disc near an `other` mark is
    neither found nor false."""
    F = [f for f in frames_ if (subset is None or subset in f["subsets"]) and (kind is None or f["kind"] == kind)
         and (nothing is None or f["nothing"] == nothing)]
    out = {"frames": len(F), "icon_marks": sum(f["n_icon_marks"] for f in F)}
    for g in ("raw", "gated", "gated_uncovered"):
        out[f"found_{g}"] = sum(f[f"found_{g}"] for f in F)
        out[f"false_{g}"] = sum(f[f"false_{g}"] for f in F)
        out[f"false_{g}_per_frame"] = round(out[f"false_{g}"] / len(F), 3) if F else None
    return out


def audit_exclusions(q: dict, rows: dict) -> list[dict]:
    """Per excluded ability: the earlier answer that excluded it, its audit frame's marks, and every sure mark in
    the pass naming it (a self-view mark contradicts the exclusion; a spectator-view one is listed apart)."""
    groups = defaultdict(list)
    for e in q["excluded_casts"]:
        groups[(e["agent"], e["slot"], e["ability"], e["why"])].append(e["key"])
    out = []
    for (agent, slot, name, why), casts in sorted(groups.items()):
        key = f"{agent}:{slot}"
        audit = [it["key"] for it in q["items"] for o in it["opportunity"]
                 if o["role"] == "audit_excluded" and it["agent"] == agent and o["slot"] == slot]
        audit_marks = []
        for k in audit:
            r = rows.get(k)
            audit_marks.append({"item": k, "answered": r is not None, "nothing": r and r["nothing"],
                                "item_unsure": r and r["unsure"],
                                "marks": [] if r is None else [{"class": mark_class(m), "ability": m.get("ability"),
                                                                "other": m.get("other"), "view": m["view"],
                                                                "x": round(m["x"], 1), "y": round(m["y"], 1)}
                                                               for m in r["marks"]]})
        named = [{"item": r["key"], "kind": r["kind"], "view": m["view"], "x": round(m["x"], 1), "y": round(m["y"], 1)}
                 for r in rows.values() if not r["unsure"] for m in r["marks"] if m.get("ability") == key]
        out.append({"ability": key, "name": name, "excluded_by": why, "excluded_casts": len(casts),
                    "audit_items": audit_marks, "marked_self": [n for n in named if n["view"] == "self"],
                    "marked_other_view": [n for n in named if n["view"] != "self"],
                    "contradicts": any(n["view"] == "self" for n in named)})
    return out


def cmd_heldout(args) -> None:
    """Score the matcher, frozen at VERSION / FOLLOW_VERSION with the default states and answers, once on the
    held-out minimap labelling pass (prototypes/label_minimap_glyph_heldout.py; last row per item wins)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import label_minimap_glyph_heldout as lab
    from reticle import ability_icons, geometry
    out = HELDOUT_OUT if args.out == str(OUT) else Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    build_extra(PROBE_STATES, answers=True)
    q = lab.load_queue()
    rows = lab.answered()
    n_rows = sum(len(lab.read_jsonl(f)) for f in glob.glob(str(lab.LABEL_DIR / "*.jsonl")))
    by = defaultdict(list)
    for it in q["items"]:
        if it["key"] in rows:
            by[it["session_id"]].append(rows[it["key"]])
    t0 = time.time()
    marks_out, frames_out, unsure_items = [], [], []
    for sid, its in sorted(by.items()):
        c, why, _ = crop_cache(sid)
        if c is None:
            for r in its:
                frames_out.append({"item": r["key"], "refused": why})
            continue
        cr = c.rect_of("minimap")
        h = np.asarray(c.holds(), dtype=float)
        held = {r["key"]: float(h[np.argmin(np.abs(h - r["t_ms"]))]) for r in its}
        plan = {r["key"]: [float(t) for t in h[(h >= held[r["key"]]) & (h <= held[r["key"]] + FOLLOW_MS)]]
                for r in its}
        need = sorted({t for v in plan.values() for t in v} | set(held.values()))
        got = {s.t_ms: s.frame[cr[1]:cr[3], cr[0]:cr[2]].copy() for s in c.samples(need, rois=["minimap"])}
        vis = vision_rows(sid, need)
        try:
            st = geometry.reference_static(sid, str(STORE))
            static_Y = luma(st if st.ndim == 3 else cv2.cvtColor(st, cv2.COLOR_GRAY2BGR))
        except (SystemExit, Exception):  # noqa: BLE001
            static_Y = None
        for r in its:
            if r["unsure"]:
                unsure_items.append(r["key"])
                continue
            th = held[r["key"]]
            subsets = heldout_subsets(r)
            fr = {"item": r["key"], "sid": sid, "kind": r["kind"], "subsets": subsets, "nothing": r["nothing"],
                  "t_held": th}
            if th not in got or abs(th - r["t_ms"]) > 70:
                fr["refused"] = "no_frame" if th not in got else f"nearest_frame_{th - r['t_ms']:.0f}ms"
                frames_out.append(fr)
                for i, m in enumerate(r["marks"]):
                    marks_out.append({"item": r["key"], "i": i, "class": mark_class(m), "refused": fr["refused"],
                                      "subsets": subsets})
                continue
            crop = got[th]
            scale = crop.shape[1] / 465.0
            Y = luma(crop)
            agent = r["agent"]
            keys = sorted(kit(agent))
            kit_keys = tuple(keys)
            terms = icon_terms(sid, crop.shape)
            sY = static_Y if static_Y is not None and static_Y.shape == crop.shape[:2] else None
            icons = vis.get(round(th, 3), (None, []))[1] or []
            props = []
            for p in (ability_icons.propose_icons(crop, terms) if terms is not None else []):
                pp = (float(p["cx"]), float(p["cy"]))
                s = frame_scores(Y, pp, scale, kit_keys) if keys else None
                gated = not (sY is not None and map_like(Y, sY, pp, scale)) and s is not None and s.max() >= ICON_SCORE
                props.append({"cx": pp[0], "cy": pp[1], "r": float(p["r"]), "gated": bool(gated),
                              "covered": portrait_cover(pp, icons, scale)})
            pts = []
            for i, m in enumerate(r["marks"]):
                x = m["x"] + (r["roi"] or cr)[0] - cr[0]
                y = m["y"] + (r["roi"] or cr)[1] - cr[1]
                cls = mark_class(m)
                pts.append((x, y, cls))
                o = {"item": r["key"], "i": i, "sid": sid, "t_ms": r["t_ms"], "t_held": th, "kind": r["kind"],
                     "subsets": subsets, "agent": agent, "class": cls, "ability": m.get("ability"),
                     "other": m.get("other"), "view": m["view"], "x": round(x, 2), "y": round(y, 2),
                     "scale": scale}
                near = [p for p in props if np.hypot(p["cx"] - x, p["cy"] - y) <= SNAP_R * scale]
                snap = min(near, key=lambda p: np.hypot(p["cx"] - x, p["cy"] - y)) if near else None
                if cls == "named":
                    truth = tuple(m["ability"].rsplit(":", 1))
                    o.update({"truth": m["ability"], "truth_name": m.get("ability_name"),
                              "truth_in_kit": truth in keys, "kit": [f"{k[0]}:{k[1]}" for k in keys]})
                    cx, cy = (snap["cx"], snap["cy"]) if snap else (x, y)
                    o.update({"cx": cx, "cy": cy, "snapped": snap is not None})
                    cl = classify(Y, cx, cy, keys, scale, rotate=True) if keys else None
                    o["base_pred"] = cl and f"{cl['pred'][0]}:{cl['pred'][1]}"
                    o["base_score"], o["base_margin"] = (cl["score"], cl["margin"]) if cl else (None, None)
                    rr = {"kit": o["kit"], "scale": scale, "cx": cx, "cy": cy, "t_held": th, "rot_pred": o["base_pred"]}
                    f = follow_item(rr, [(t, got[t]) for t in plan[r["key"]] if t in got], vis, terms, sY)
                    o.update({"follow_pred": f["pred"], "decided_by": f["decided_by"], "n_clean": f["n_clean"],
                              "follow_mean": f.get("mean"), "follow_margin": f.get("margin"),
                              "n_following_cached": len(plan[r["key"]])})
                marks_out.append(o)
            icon_pts = [(x, y) for x, y, cls in pts if cls in ICON_MARKS]
            all_pts = [(x, y) for x, y, _ in pts]
            fr["n_icon_marks"] = len(icon_pts)
            fr["proposals"] = props
            for g, sel in (("raw", lambda p: True), ("gated", lambda p: p["gated"]),
                           ("gated_uncovered", lambda p: p["gated"] and p["covered"] is None)):
                P = [p for p in props if sel(p)]
                fr[f"found_{g}"] = sum(any(np.hypot(p["cx"] - x, p["cy"] - y) <= SNAP_R * scale for p in P)
                                       for x, y in icon_pts)
                fr[f"false_{g}"] = sum(all(np.hypot(p["cx"] - x, p["cy"] - y) > SNAP_R * scale for x, y in all_pts)
                                       for p in P)
            frames_out.append(fr)
        print(f"  {sid}: {len(its)} items, {time.time() - t0:.0f}s", flush=True)
    F = [f for f in frames_out if not f.get("refused")]
    summ = {"version": HELDOUT_VERSION, "matcher": VERSION, "follow": FOLLOW_VERSION, "build": BUILD,
            "states": "probe", "answers": True, "queue": q["version"], "label_rows": n_rows, "items_answered": len(rows),
            "rule": "last row per item wins; headline = kind after_cast or control, not dev_session, not "
                    "near_tuned_label; the matcher's verdict is follow (base = the labelled frame alone)",
            "candidates": "the session agent's kit (GLYPHS keys); the matcher has no other-agent path",
            "params": {"CANVAS": [float(CANVAS[0]), float(CANVAS[-1])], "MASK_R": MASK_R, "SHIFT": SHIFT,
                       "ROT_STEP": ROTS[1], "SNAP_R": SNAP_R, "FOLLOW_MS": FOLLOW_MS, "N_CLEAN": N_CLEAN, "OCC_R": OCC_R,
                       "SAME_R": SAME_R, "REACH": REACH, "ICON_SCORE": ICON_SCORE, "MAP_CORR": MAP_CORR},
            "answer_log": dict(ANSWER_LOG), "extra": {f"{k[0]}:{k[1]}": [p for _, p in v] for k, v in EXTRA.items()},
            "unsure_items": unsure_items, "refused_frames": [f for f in frames_out if f.get("refused")],
            "wall_s": round(time.time() - t0, 1)}
    summ["naming"] = {s: naming_summary(marks_out, s) for s in ("headline", "dev_session", "near_tuned_label",
                                                                 "audit_only")}
    summ["detection"] = {"headline": detection_summary(F, "headline"),
                         "headline_control": detection_summary(F, "headline", kind="control"),
                         "headline_nothing": detection_summary(F, "headline", nothing=True),
                         "all_control": detection_summary(F, kind="control"),
                         "all_nothing": detection_summary(F, nothing=True), "all": detection_summary(F)}
    summ["not_scored"] = {c: [{k: m.get(k) for k in ("item", "i", "kind", "subsets", "view", "x", "y", "other")}
                              for m in marks_out if m["class"] == c] for c in ("unsure", "smoke", "other_agent", "other")}
    summ["audit"] = audit_exclusions(q, rows)
    json.dump({"meta": summ, "marks": marks_out, "frames": frames_out}, open(out / "heldout.json", "w"),
              indent=1, default=float)
    show = {k: summ[k] for k in ("naming", "detection")}
    show["not_scored"] = {c: len(v) for c, v in summ["not_scored"].items()}
    show["audit_contradictions"] = [a["ability"] for a in summ["audit"] if a["contradicts"]]
    print(json.dumps(show, indent=1))


# ------------------------------------------------------------------ texture inventory

INVENTORY_VERSION = "minimap-texture-inventory-0.1.0"
#: Folders of the export that hold minimap textures an ability may draw (the per-map radar, ping, thumbnail and
#: menu folders are listed by count only).
INV_DIRS = ["minimap/ShooterGame/Content/UI/Shared/Icons/Abilities/Minimap",
            "minimap/ShooterGame/Content/UI/InGame/HUD/Minimap",
            "minimap/ShooterGame/Content/UI/InGame/HUD/Minimap/Possessables",
            "minimap/ShooterGame/Content/UI/InGame/Minimap/Textures/Abilities",
            "minimap-abilities"]
NOT_ABILITY = re.compile(r"OutDebugWrite|CircleIcon256|minimap_background|TX_Hud_Icons$|EdgeIndicator|Kill_S|"
                         r"Minimap_Bomb|LastPlayer|Minimap_Player|_fog|CircleUltRange|Footstep_Radius|Kingpin|"
                         r"SegmentArrowTile|deadPlayerIcon|DeadStripes", re.I)
CODE_RE = re.compile(r"(?:TX_UI_Minimap_|TX_Hud_Icons_Minimap_|TX_Minimap_|TX_)([A-Za-z]+?)(?:_|$)")
EXTRA_CODES = {"Grenadier": "KAY/O", "Kayo": "KAY/O", "Astra": "Astra", "Rift": "Astra", "Sarge": "Brimstone",
               "SMO": "Clove", "Neon": "Neon", "HunterDart": "Sova", "Killjoy": "Killjoy", "Wraith": "Omen",
               "Decoy": "Yoru", "gatecrash": "Yoru", "Cable": "Deadlock", "Chamber": "Chamber", "ShadeActive": None}


def inv_files() -> list[str]:
    fs = []
    for d in INV_DIRS:
        fs += sorted(glob.glob(str(GX / d) + "/**/*.png", recursive=True) if d == "minimap-abilities"
                     else glob.glob(str(GX / d) + "/*.png"))
    return [f.replace("\\", "/") for f in fs]


def tex_agent(name: str) -> str | None:
    agents = {a.replace("/", ""): a for a, _ in GLYPHS}
    for code, agent in {**agents, **CODENAME, **EXTRA_CODES}.items():
        if re.search(rf"(?:^|_){code}(?:_|$)", name):
            return agent
    return None


def is_disc(im: np.ndarray) -> bool:
    a = im[..., 3].astype(np.float32) / 255.0 if im.shape[2] == 4 else np.ones(im.shape[:2], np.float32)
    n = min(a.shape)
    yy, xx = np.mgrid[:a.shape[0], :a.shape[1]]
    d = np.hypot(yy - (a.shape[0] - 1) / 2, xx - (a.shape[1] - 1) / 2)
    return bool(a[d < 0.42 * n].mean() > 0.95 and a[d > 0.52 * n].mean() < 0.2)


def inv_glyph(f: str) -> np.ndarray:
    """The glyph a texture draws: a disc marker's |luma - disc median| inside 0.70 of the disc (a teal Selected
    disc draws a dark glyph, a black one a white glyph), else alpha x luma."""
    im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    if im.shape[2] == 3:
        im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
    if not is_disc(im):
        return icon_glyph(f)
    lum = cv2.cvtColor(im[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    n = im.shape[0]
    k = int(round(n / 2.0 * INNER))
    c = n // 2
    g = lum[c - k:c + k, c - k:c + k].copy()
    yy, xx = np.mgrid[-k:k, -k:k] + 0.5
    inside = np.hypot(xx, yy) <= k
    g = np.abs(g - np.median(g[inside]))
    g[~inside] = 0
    g /= max(g.max(), 1e-6)
    return cv2.resize(g, (128, 128), interpolation=cv2.INTER_AREA if g.shape[0] > 128 else cv2.INTER_LINEAR)


def glyph_bank(g: np.ndarray, scale: float) -> np.ndarray:
    W, h, sh, mask = geom(scale)
    rows = []
    for c in CANVAS * scale:
        n = int(round(c))
        t0 = cv2.resize(g, (n, n), interpolation=cv2.INTER_AREA)
        for rot in ROTS:
            t = t0
            if rot:
                M = cv2.getRotationMatrix2D(((n - 1) / 2, (n - 1) / 2), rot, 1.0)
                t = cv2.warpAffine(t0, M, (n, n), flags=cv2.INTER_LINEAR, borderValue=0)
            T = place(t, W)
            if T[mask > 0].std() >= 1e-3:
                rows.append(T[mask > 0])
    return np.array(rows, np.float32)


def cmd_inventory(args) -> None:
    out = Path(args.out)
    d, z = load_scores(out)
    pos = [r for r in positives(d["items"]) if r.get("truth")]
    by_agent = defaultdict(list)
    for r in pos:
        by_agent[r["truth"].split(":")[0]].append(r)
    rows, tiles = [], []
    for f in inv_files():
        name = os.path.basename(f)[:-4]
        rel = os.path.relpath(f, str(GX)).replace("\\", "/")
        row = {"file": rel, "name": name, "agent": tex_agent(name),
               "state": next((w for w in STATE_WORDS if name.lower().endswith("_" + w)), ""),
               "kind": "not_ability" if NOT_ABILITY.search(name) else "candidate"}
        im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
        row["size"] = list(im.shape[:2])
        if row["kind"] == "candidate":
            g = inv_glyph(f)
            row["disc"] = is_disc(im if im.shape[2] == 4 else np.dstack([im, np.full(im.shape[:2], 255, np.uint8)]))
            # evidence 1: glyph correlation with the agent's DisplayIcons (reference-only, not proof)
            ic = sorted(((max(_corr(g, _scaled(v["glyph"], m)) for m in range(80, 132, 6)), k)
                         for k, v in kit(row["agent"]).items()), reverse=True) if row["agent"] else []
            row["icon_corr"] = [[round(s, 3), f"{k[0]}:{k[1]}", GLYPHS[k]["name"]] for s, k in ic[:2]]
            # evidence 2: median best Pearson over the player's labelled crops of each ability of the agent
            lab = {}
            for r in by_agent.get(row["agent"], []):
                P = patches(z["Y"][r["win_index"]], r["scale"])
                if P is None:
                    continue
                lab.setdefault(r["truth"], []).append(float(pearson(P, glyph_bank(g, r["scale"])).max()))
            row["label_corr"] = sorted([[round(float(np.median(v)), 3), k, GLYPHS[tuple(k.split(":"))]["name"], len(v)]
                                        for k, v in lab.items() if len(v) >= 3], reverse=True)
            lc = row["label_corr"]
            if lc and lc[0][0] >= 0.6 and (len(lc) == 1 or lc[0][0] - lc[1][0] >= 0.1):
                row["proposed"], row["status"] = lc[0][1], "labels"
                row["proposed_name"] = lc[0][2]
            elif ic and ic[0][0] >= 0.5 and (len(ic) == 1 or ic[0][0] - ic[1][0] >= 0.05):
                row["proposed"], row["status"] = f"{ic[0][1][0]}:{ic[0][1][1]}", "icon_correlation"
                row["proposed_name"] = GLYPHS[ic[0][1]]["name"]
            else:
                row["proposed"], row["status"], row["proposed_name"] = None, "open", None
        rows.append(row)
        # contact sheet tile: the texture over grey, its name, agent, proposal and status
        if im.ndim == 2:
            im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
        if im.shape[2] == 3:
            im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
        a = im[..., 3:4].astype(np.float32) / 255
        comp = (im[..., :3] * a + np.full(im.shape[:2] + (3,), 100.0) * (1 - a)).astype(np.uint8)
        s = 80 / max(comp.shape[:2])
        comp = cv2.resize(comp, (max(1, int(comp.shape[1] * s)), max(1, int(comp.shape[0] * s))),
                          interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        t = np.full((122, 170, 3), 30, np.uint8)
        t[2:2 + comp.shape[0], 45:45 + comp.shape[1]] = comp
        col = {"labels": (80, 220, 80), "icon_correlation": (0, 200, 255), "open": (80, 80, 255)}.get(
            row.get("status"), (160, 160, 160))
        short = name.replace("TX_UI_Minimap_", "").replace("TX_Hud_Icons_Minimap_", "HI_")
        cv2.putText(t, short[:27], (2, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (255, 255, 255), 1, cv2.LINE_AA)
        lab_txt = (f"{row.get('proposed_name') or '-'} [{row.get('status')}]" if row["kind"] == "candidate"
                   else "not an ability")
        cv2.putText(t, lab_txt[:30], (2, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.33, col, 1, cv2.LINE_AA)
        cv2.putText(t, str(row["agent"]), (2, 119), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (200, 200, 200), 1, cv2.LINE_AA)
        tiles.append(t)
    cols = 10
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(str(out / "inventory_sheet.png"), np.vstack([np.hstack(tiles[i:i + cols])
                                                             for i in range(0, len(tiles), cols)]))
    counts = Counter(r.get("status", r["kind"]) for r in rows)
    other = {d: len(glob.glob(str(GX / d) + "/**/*.png", recursive=True)) for d in
             ["minimap/ShooterGame/Content/UI/InGame/Minimap/Maps", "minimap/ShooterGame/Content/UI/InGame/QuickComms",
              "minimap/ShooterGame/Content/UI/Shared/Icons/Character/Minimap_Thumbnails"]}
    prov = json.load(open(GX / "minimap-abilities" / "provenance.json")) if (GX / "minimap-abilities").is_dir() else None
    json.dump({"version": INVENTORY_VERSION, "build": BUILD, "export_stamps": {
        "minimap": "game-extract set 'minimap' (provenance.json at the build root)",
        "minimap-abilities": prov and prov.get("version_stamp")}, "counts": dict(counts),
        "listed_by_count_only": other, "rows": rows}, open(out / "inventory.json", "w"), indent=1)
    print(dict(counts))
    for r in rows:
        if r["kind"] == "candidate":
            print(f"{r['name'][:44]:44s} {str(r['agent']):9s} {r['status']:16s} {str(r.get('proposed_name')):18s} "
                  f"label {r['label_corr'][:2]} icon {r['icon_corr'][:1]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["score", "misses", "examples", "separate", "inventory", "follow", "heldout"])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--states", default="probe", choices=["probe", "all"])
    ap.add_argument("--answers", default="on", choices=["on", "off"],
                    help="score: use the player's texture answers as references (follow reads the choice from items.json)")
    ap.add_argument("--only", default=None, help="follow: comma-separated session ids (a small sample)")
    args = ap.parse_args()
    {"score": cmd_score, "misses": cmd_misses, "examples": cmd_examples, "separate": cmd_separate,
     "inventory": cmd_inventory, "follow": cmd_follow, "heldout": cmd_heldout}[args.cmd](args)


if __name__ == "__main__":
    main()
