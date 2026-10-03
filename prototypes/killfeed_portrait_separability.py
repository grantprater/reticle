r"""Which descriptor separates killfeed agent portraits, measured on Riot labels.

    .\.venv\Scripts\python.exe prototypes\killfeed_portrait_separability.py extract --riot RIOT_JSON --out DIR [--sessions S ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_portrait_separability.py score --out DIR [--sessions S ...] [--only NAME ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_portrait_separability.py claims --out DIR [--record]
    .\.venv\Scripts\python.exe prototypes\killfeed_portrait_separability.py sheet --out DIR --png PNG [--entries D|ROLE ...]
    .\.venv\Scripts\python.exe prototypes\killfeed_portrait_separability.py fingerprint --out DIR --png PNG

Question. The killfeed draws each agent's official portrait art (256x128,
`<store>/reference/assets/agents/<Agent>_killfeed_portrait.png`) at one band
height (34 px at 1080p): two drawings of one agent are the same picture.
The stored descriptor (`appearance.hsv_composition`, a 10x3x3 HSV histogram
of the plate-masked tile, scored by histogram intersection against the art
in `adjudication.identity`) is layout-free, so it throws away the face and
keeps the palette; Fade and Iso, both dark-haired on dark clothing, sit
within 0.1 of each other. This measures descriptors that keep the layout.

Labels. Riot's match records, scored against the stored deaths by
`prototypes/riot_ground_truth.py` (`RIOT_JSON`, its per-session
`death_rows`): an unambiguous row paired by time gives Riot's killer and
victim for the stored death's bound portrait views (the death row's
`killer_identity` claim and its `killfeed_portrait` witness list the
observation keys; `events/killfeed_portrait` holds the boxes). Riot labels
are used offline only, to evaluate and to mine references; every score is
leave-one-session-out.

Tiles (`extract`). Per labelled view, a strip of the band (`YPAD` rows
either side) cut from the HUD ROI crop cache (a lossless crop of a fixed
reader ROI; no decode): for a killer, the stored box's columns widened by
`PAD` each side; for a victim, the same width about the right-aligned
anchor (`VICTIM_OUTER`), since stored victim boxes wander. Victim strips are
mirrored on load: the victim portrait is the art drawn mirrored. The stored
composition and shifts ride along so the current scorer reruns on the same
views.

Descriptors (`score`), each a score per agent (higher is better):

* `current` -- the stored composition and shifts against the official art
  (`identity._portrait_scores`, art only), the runtime's art path;
* `zncc_box`, `zncc_anchor`, `zncc_wide` -- render-and-compare: zero-mean
  normalised correlation of the strip's Lab with each agent's art shrunk to
  the tile (INTER_AREA, alpha-premultiplied), weighted by the art's alpha;
  best over +-2 x, +-1 y about the stored box, about the anchor (killer:
  the box; victim: the right-aligned anchor), or over the whole strip for a
  killer; no training;
* `zncc_inner` -- `zncc_wide` (killer) and `zncc_anchor` (victim) with the
  art's `INNER_MARGIN` border unweighted, so the self entry's yellow frame
  does not count;
* `grid_lab` -- mean Lab over a 4x8 grid of the anchored tile; nearest class
  mean, diagonal whitening;
* `hog` -- gradient-orientation histograms (9 bins) of the lightness over
  the same 4x8 cells, L2 per cell; nearest class mean;
* `grid_hog` -- both, concatenated;
* `lda` -- the fingerprint: `grid_hog` projected by shrinkage LDA fitted on
  the training sessions (classes - 1 dimensions), nearest class mean;
  `lda_zncc` adds the anchored ZNCC on the LDA's scale;
* `phash` -- 63-bit DCT hash of the 32x64 lightness, majority-bit class
  hash, Hamming distance (a speed reference only).

`claims` simulates the portrait claim per entry role from these scores;
`sheet` draws tiles with each scorer's pick; `fingerprint` draws, per pair,
the mean aligned tiles, the per-pixel Fisher ratio, where the inner ZNCC's
evidence lies, and the LDA's per-cell weight.

Each descriptor yields a score per agent (higher is better). Accuracy is
top-1 within the side's five Riot agents (`side5`), the match's ten
(`match10`) and every agent with a reference (`all`); margin is the true
agent's score less the best other's in the side's five, also in units of
the descriptor's own within-class spread (`zmargin`).

Predictions and outcome: `killfeed-portrait-separability-20261003` in the
store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "4")

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.roi_cache import CACHE_SETS  # noqa: E402
from reticle.store import Store  # noqa: E402

ROOT = Path(Store().root)
EV = ROOT / "events"
ART = ROOT / "reference" / "assets" / "agents"
#: Columns kept either side of the stored box, for the shift search.
SEPARABILITY_VERSION = "portrait-separability-0.1.0"
PAD = 24
YPAD = 3
BH = 34                      # the band height every 1080p capture draws
TW = 2 * BH                  # tile width: the art is two band heights wide
GRID = (4, 8)                # rows, columns of the colour and gradient grids
HOG_BINS = 9
#: The runtime search about an anchor: columns and rows either side.
SEARCH_X, SEARCH_Y = 2, 1
#: The victim portrait's last (outer) column is ROI column roi_w - VICTIM_OUTER:
#: the feed is right-aligned. Measured here: 22291 of 22891 victim views
#: whose Riot agent correlates >= 0.6 anywhere in the strip end there, on all
#: 21 matches (1920x1080, ROI right edge at x 1910).
VICTIM_OUTER = 11
#: A tile is clean when the art at its anchor lies wholly inside the ROI and
#: its best agent correlates at least this well (label-free).
CLEAN_ZNCC = 0.5
#: The share of the art's weight that must fall inside the ROI for a ZNCC to count.
MIN_COVER = 0.4
#: Rows and columns of the art's border left unweighted by `zncc_inner`. The
#: player's own portrait carries a yellow frame [domain:killfeed/self-yellow-frame]
#: that covers the art's outer rows; weighted, it held those killers' true-agent
#: ZNCC near 0.5 against about 0.88 elsewhere.
INNER_MARGIN = 4


def inner_weights(ref_a: np.ndarray, margin: int = INNER_MARGIN) -> np.ndarray:
    """The art's alpha with its `margin`-pixel border set to zero."""
    w = ref_a.copy()
    w[:, :margin] = 0
    w[:, BH - margin:] = 0
    w[:, :, :margin] = 0
    w[:, :, TW - margin:] = 0
    return w


def below_normal() -> None:
    """Below Normal priority on Windows; nothing elsewhere."""
    if os.name == "nt":
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)


def canon(name):
    return None if name is None else str(name).strip().replace("/", "_").casefold()


def art_names() -> dict[str, str]:
    """canon name -> the art file's agent name."""
    return {canon(p.name[:-len("_killfeed_portrait.png")]): p.name[:-len("_killfeed_portrait.png")]
            for p in ART.glob("*_killfeed_portrait.png")}


# ------------------------------------------------------------------- extract

class Cache:
    """The HUD crop cache's killfeed rectangle for one session (PNG blob)."""

    def __init__(self, sid: str):
        d = ROOT / "roi_cache" / "hud" / "roi-cache-0.1.0"
        self.ok = (d / f"{sid}.json").is_file()
        if not self.ok:
            return
        rec = json.loads((d / f"{sid}.json").read_text(encoding="utf-8"))
        k = CACHE_SETS[rec["roi"]].index("killfeed")
        self.wh = rec["wh"]
        idx = np.load(d / f"{sid}.idx.npy")
        if idx.shape[1] == 4:
            idx = np.insert(idx, 2, 0, axis=1)
        self.idx = idx[idx[:, 2].astype(int) == k]
        self.by_t = {float(t): i for i, t in enumerate(self.idx[:, 0])}
        self.fh = open(d / f"{sid}.bin", "rb")

    def crop(self, t: float):
        i = self.by_t.get(float(t))
        if i is None:
            return None
        self.fh.seek(int(self.idx[i, 3]))
        buf = self.fh.read(int(self.idx[i, 4]))
        return cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)


def _views(evidence: dict) -> list[str]:
    return [o.get("observation_key") for o in (evidence or {}).get("observations") or []
            if o.get("observation_key")]


def extract_session(ss: dict, out: Path, names: dict, extra: set = frozenset()) -> dict:
    """`extra` death ids are kept even when Riot's pairing is ambiguous, marked
    `eval_only` so no metric or reference uses them (the gallery's entries)."""
    sid = ss["session"]
    rows = [dict(r, eval_only=not (r.get("paired_by") == "time" and not r.get("ambiguous")))
            for r in ss.get("death_rows") or []
            if (r.get("paired_by") == "time" and not r.get("ambiguous")) or r["death_id"] in extra]
    p = EV / "death" / f"{sid}.jsonl"
    if not rows or not p.is_file():
        return {"session": sid, "tiles": 0, "why": "no rows or no death stream"}
    verdicts = {}
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("kind") == "death_verdict":
                verdicts[d["death_id"]] = d
    # the match's agents by Riot side (victim side of each row; killer opposite)
    sides = defaultdict(set)
    for r in ss.get("death_rows") or []:
        vs = r["side"][0]
        if r["victim"][0]:
            sides[vs].add(names.get(canon(r["victim"][0]), r["victim"][0]))
        if r["killer"][0] and not r.get("self_kill"):
            ks = {"ally": "enemy", "enemy": "ally"}.get(vs)
            if ks:
                sides[ks].add(names.get(canon(r["killer"][0]), r["killer"][0]))
    want = {}                     # observation key -> label row
    for r in rows:
        d = verdicts.get(r["death_id"])
        if d is None:
            continue
        meta = d.get("metadata") or {}
        kclaim = next((c for c in (meta.get("killer_identity") or {}).get("claims") or []
                       if c.get("channel") == "killfeed_portrait"), None)
        vwit = next((w for w in d.get("witnesses") or [] if w.get("channel") == "killfeed_portrait"),
                    None)
        vs = r["side"][0]
        for role, claim, riot, ours, side in (
                ("killer", kclaim, r["killer"][0], r["killer"][1],
                 {"ally": "enemy", "enemy": "ally"}.get(vs)),
                ("victim", vwit, r["victim"][0], r["victim"][1], vs)):
            if not claim or not riot or (role == "killer" and r.get("self_kill")):
                continue
            lab = names.get(canon(riot))
            if lab is None:
                continue
            for key in _views(claim.get("evidence")):
                if key.endswith(":" + role):
                    want[key] = {"label": lab, "role": role, "death_id": r["death_id"],
                                 "riot_side": side, "ours": ours,
                                 "death_t_ms": float(d["t_ms"]), "eval_only": r["eval_only"]}
    boxes = {}
    pp = EV / "killfeed_portrait" / f"{sid}.jsonl"
    with open(pp, encoding="utf-8") as fh:
        for line in fh:
            i = line.find('"observation_key":"')
            if i < 0:
                continue
            key = line[i + 19:line.find('"', i + 19)]
            if key in want:
                boxes[key] = json.loads(line)
    cache = Cache(sid)
    if not cache.ok:
        return {"session": sid, "tiles": 0, "why": "no hud crop cache"}
    by_t = defaultdict(list)
    for key, b in boxes.items():
        by_t[float(b["t_ms"])].append(key)
    strips, meta, comps, shifts = [], [], [], []
    skipped = Counter()
    for t in sorted(by_t):
        img = cache.crop(t)
        if img is None:
            skipped["no_crop"] += len(by_t[t])
            continue
        h, w = img.shape[:2]
        for key in by_t[t]:
            b = boxes[key]
            if b.get("reason") or "x0" not in b:
                skipped["refused_view"] += 1
                continue
            if b["y1"] - b["y0"] != BH:
                skipped[f"band_h_{b['y1'] - b['y0']}"] += 1    # kept: rows from y0
            # columns: a killer's from the box's inner (name) edge, a victim's
            # from the feed's right edge (`VICTIM_OUTER`), widened by PAD;
            # rows: BH from the box top, widened by YPAD
            x0 = (b["x1"] - TW if want[key]["role"] == "killer"
                  else w - VICTIM_OUTER + 1 - TW)
            s = np.zeros((BH + 2 * YPAD, TW + 2 * PAD, 3), np.uint8)
            a, z = x0 - PAD, x0 + TW + PAD
            ya, yz = b["y0"] - YPAD, b["y0"] + BH + YPAD
            sa, sz = max(0, a), min(w, z)
            ta, tz = max(0, ya), min(h, yz)
            s[ta - ya:tz - ya, sa - a:sz - a] = img[ta:tz, sa:sz]
            strips.append(s)
            comp = np.asarray(b.get("composition") or [], np.float32)
            comps.append(comp if comp.size == 90 else np.zeros(90, np.float32))
            sh = b.get("shifts") or {}
            shifts.append(np.stack([np.asarray(sh.get(str(k)) or np.zeros(90), np.float32)
                                    if len(sh.get(str(k)) or []) == 90 else np.zeros(90, np.float32)
                                    for k in (-4, -2, 0, 2, 4)]))
            m = want[key]
            meta.append({"key": key, "t_ms": t, "slot": b["slot"], "role": m["role"],
                         "label": m["label"], "death_id": m["death_id"], "eval_only": m["eval_only"],
                         "riot_side": m["riot_side"], "ours": m["ours"], "ally": b.get("ally"),
                         "box_x0": b["x0"], "box_x1": b["x1"], "strip_x0": x0 - PAD,
                         "box_y0": b["y0"], "bh": b["y1"] - b["y0"], "strip_y0": b["y0"] - YPAD,
                         "roi_h": h,
                         "clipped": b.get("clipped"), "art_fraction": b.get("art_fraction"),
                         "roi_w": w})
    if not strips:
        return {"session": sid, "tiles": 0, "why": "no tiles", "skipped": dict(skipped)}
    np.savez_compressed(out / f"{sid}.npz", strips=np.stack(strips),
                        composition=np.stack(comps), shifts=np.stack(shifts))
    (out / f"{sid}.json").write_text(json.dumps(
        {"session": sid, "map": ss.get("map"), "sides": {k: sorted(v) for k, v in sides.items()},
         "tiles": meta, "skipped": dict(skipped)}, indent=0), encoding="utf-8")
    return {"session": sid, "tiles": len(strips), "skipped": dict(skipped),
            "sides": {k: len(v) for k, v in sides.items()}}


def cmd_extract(args) -> None:
    below_normal()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    score = json.loads(Path(args.riot).read_text(encoding="utf-8"))
    names = art_names()
    extra = set()
    if args.extra:
        extra = {e["death_id"] for e in json.loads(Path(args.extra).read_text(encoding="utf-8"))}
    for ss in score["sessions"]:
        if args.sessions and ss["session"] not in args.sessions:
            continue
        t0 = time.perf_counter()
        r = extract_session(ss, out, names, extra)
        print(json.dumps(r), f"{time.perf_counter() - t0:.1f}s", flush=True)


# ------------------------------------------------------------------ load

def load_session(out: Path, sid: str, mirror_victims: bool = True) -> dict:
    """One session's tiles: strips in art orientation (a victim strip is
    mirrored when `mirror_victims`), their in-ROI mask, and the stored
    composition and shifts."""
    z = np.load(out / f"{sid}.npz")
    m = json.loads((out / f"{sid}.json").read_text(encoding="utf-8"))
    strips = z["strips"].copy()
    n, H, W = strips.shape[:3]
    t = m["tiles"]
    sx = np.array([r["strip_x0"] for r in t])[:, None]
    sy = np.array([r["strip_y0"] for r in t])[:, None]
    rw = np.array([r["roi_w"] for r in t])[:, None]
    rh = np.array([r["roi_h"] for r in t])[:, None]
    cx = sx + np.arange(W)[None]
    cy = sy + np.arange(H)[None]
    valid = (((cy >= 0) & (cy < rh))[:, :, None] & ((cx >= 0) & (cx < rw))[:, None, :])
    victim = np.array([r["role"] == "victim" for r in t])
    if mirror_victims:
        strips[victim] = strips[victim][:, :, ::-1]
        valid[victim] = valid[victim][:, :, ::-1]
    return {"sid": sid, "strips": strips, "valid": valid, "tiles": t, "sides": m["sides"],
            "composition": z["composition"], "shifts": z["shifts"], "victim": victim}


def lab(bgr_u8: np.ndarray) -> np.ndarray:
    """CIE Lab (float32, L 0-100) of a stack of BGR uint8 images."""
    sh = bgr_u8.shape
    flat = bgr_u8.reshape(-1, sh[-2], 3).astype(np.float32) / 255.0
    return cv2.cvtColor(flat, cv2.COLOR_BGR2Lab).reshape(sh).astype(np.float32)


def art_refs(names=None) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Each agent's official killfeed art shrunk to the tile (INTER_AREA, on
    alpha-premultiplied colour): agent names, Lab (A, BH, TW, 3), alpha (A, BH, TW)."""
    agents, labs, alphas = [], [], []
    for p in sorted(ART.glob("*_killfeed_portrait.png")):
        name = p.name[:-len("_killfeed_portrait.png")]
        if names is not None and name not in names:
            continue
        im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED).astype(np.float32) / 255.0
        a = im[:, :, 3:4]
        pm = cv2.resize(im[:, :, :3] * a, (TW, BH), interpolation=cv2.INTER_AREA)
        al = cv2.resize(a[:, :, 0], (TW, BH), interpolation=cv2.INTER_AREA)
        col = pm / np.maximum(al, 1e-3)[:, :, None]
        labs.append(cv2.cvtColor(np.clip(col, 0, 1).astype(np.float32), cv2.COLOR_BGR2Lab))
        alphas.append(al)
        agents.append(name)
    return agents, np.stack(labs), np.stack(alphas)


# ------------------------------------------------------------------ render and compare

def _device():
    import torch
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def strip_zncc(strip_lab: np.ndarray, valid: np.ndarray, ref_lab: np.ndarray, ref_a: np.ndarray,
             batch: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """Weighted zero-mean normalised correlation of every tile window with
    every agent's art, at every offset the strip allows.

    Weights are the art's alpha times the in-ROI mask, so the plate and the
    world behind the art's transparent pixels never enter the score. Returns
    (zncc (N, A, dy, dx), coverage (N, A, dy, dx): the in-ROI share of the
    art's weight). Runs as convolutions (torch, GPU when present)."""
    import torch
    import torch.nn.functional as F
    dev = _device()
    Wk = torch.from_numpy(ref_a[:, None]).to(dev)                         # A,1,h,w
    R = torch.from_numpy(np.ascontiguousarray(ref_lab.transpose(0, 3, 1, 2))).to(dev)  # A,3,h,w
    WR = Wk * R
    WR2 = Wk * R * R
    wsum = Wk.sum(dim=(1, 2, 3))
    outs, covs = [], []
    for i in range(0, len(strip_lab), batch):
        X = torch.from_numpy(np.ascontiguousarray(strip_lab[i:i + batch].transpose(0, 3, 1, 2))).to(dev)
        V = torch.from_numpy(valid[i:i + batch, None].astype(np.float32)).to(dev)
        X = X * V
        Sw = F.conv2d(V, Wk)                                              # N,A,dy,dx
        num = torch.zeros_like(Sw)
        vx = torch.zeros_like(Sw)
        vr = torch.zeros_like(Sw)
        for c in range(3):
            Xc = X[:, c:c + 1]
            Sx = F.conv2d(Xc, Wk)
            Sxx = F.conv2d(Xc * Xc, Wk)
            Sr = F.conv2d(V, WR[:, c:c + 1])
            Srr = F.conv2d(V, WR2[:, c:c + 1])
            Sxr = F.conv2d(Xc, WR[:, c:c + 1])
            sw = Sw.clamp_min(1e-6)
            num += Sxr - Sx * Sr / sw
            vx += Sxx - Sx * Sx / sw
            vr += Srr - Sr * Sr / sw
        cv = Sw / wsum[None, :, None, None]
        z = num / torch.sqrt(vx.clamp_min(1e-6) * vr.clamp_min(1e-6))
        # under MIN_COVER of the art inside the ROI, or a flat window, is no evidence
        z = torch.where((cv >= MIN_COVER) & (vx > 1e-3 * vr), z.clamp(-1, 1), torch.zeros_like(z))
        outs.append(z.float().cpu().numpy())
        covs.append(cv.float().cpu().numpy())
    return np.concatenate(outs), np.concatenate(covs)


# ------------------------------------------------------------------ anchors and descriptors

def anchors(S: dict) -> tuple[np.ndarray, np.ndarray]:
    """Each tile's window column in its (art-oriented) strip: the stored box
    (`box`), and the geometry anchor (`anchor`): the box for a killer, the
    feed's right edge less `VICTIM_OUTER` for a victim (where `extract` cut
    the victim strip). Clipped to the strip; a stored victim box further
    than PAD from the anchor lands on the strip's end."""
    W = S["strips"].shape[2]
    t = S["tiles"]
    sx0 = np.array([r["strip_x0"] for r in t])
    bx0 = np.array([r["box_x0"] for r in t])
    box = np.where(S["victim"], W - TW - (bx0 - sx0), PAD)  # mirrored start of the stored box
    anc = np.full(len(t), PAD)
    return np.clip(box, SEARCH_X, W - TW - SEARCH_X), anc


def windows(S: dict, x: np.ndarray, dx: int = 0, dy: int = 0, key: str = "lab") -> np.ndarray:
    """The (N, BH, TW, C) tiles at columns x + dx, rows YPAD + dy."""
    A = S[key]
    cols = (x + dx)[:, None] + np.arange(TW)[None]
    rows = YPAD + dy + np.arange(BH)
    return A[np.arange(len(A))[:, None, None], rows[None, :, None], cols[:, None, :]]


def _area(n_out: int, n_in: int) -> np.ndarray:
    """(n_out, n_in) area-average weights: each output cell's share of each
    input pixel, as INTER_AREA shrinks; rows sum to 1."""
    edges = np.arange(n_out + 1) * n_in / n_out
    lo, hi = edges[:-1, None], edges[1:, None]
    px = np.arange(n_in)[None]
    w = np.clip(np.minimum(hi, px + 1) - np.maximum(lo, px), 0, None)
    return (w / w.sum(1, keepdims=True)).astype(np.float32)


RY, RX = _area(GRID[0], BH), _area(GRID[1], TW)


def grid_lab(L: np.ndarray) -> np.ndarray:
    """Mean Lab over a GRID of cells (area averaging): (N, 4*8*3)."""
    return np.einsum("yh,nhwc,xw->nyxc", RY, L, RX, optimize=True).reshape(len(L), -1)


def sobel(g: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """3x3 Sobel derivatives of a stack of images (reflect-101 borders, as
    cv2.Sobel), vectorised over the stack."""
    p = np.pad(g, ((0, 0), (1, 1), (1, 1)), mode="reflect")
    sm_y = p[:, :-2] + 2 * p[:, 1:-1] + p[:, 2:]              # smooth along y
    sm_x = p[:, :, :-2] + 2 * p[:, :, 1:-1] + p[:, :, 2:]     # smooth along x
    return sm_y[:, :, 2:] - sm_y[:, :, :-2], sm_x[:, 2:] - sm_x[:, :-2]


def hog(L: np.ndarray) -> np.ndarray:
    """Unsigned gradient-orientation histograms (HOG_BINS, linear vote between
    the two nearest bins) of the lightness over the GRID cells (area
    weights), L2 per cell: (N, 4*8*9)."""
    gx, gy = sobel(np.ascontiguousarray(L[..., 0]))
    mag = np.hypot(gx, gy)
    ang = (np.arctan2(gy, gx) % np.pi) / np.pi * HOG_BINS - 0.5
    b0 = np.floor(ang).astype(int)
    f = (ang - b0).astype(np.float32)
    b0 %= HOG_BINS
    b1 = (b0 + 1) % HOG_BINS
    bins = np.arange(HOG_BINS)
    vote = (mag * (1 - f))[..., None] * (b0[..., None] == bins) + \
           (mag * f)[..., None] * (b1[..., None] == bins)               # N, h, w, B
    h = np.einsum("yh,nhwb,xw->nyxb", RY, vote.astype(np.float32), RX, optimize=True)
    h = h.reshape(len(L), GRID[0] * GRID[1], HOG_BINS)
    h /= np.maximum(np.linalg.norm(h, axis=2, keepdims=True), 1e-3)
    return h.reshape(len(L), -1).astype(np.float32)


def phash(L: np.ndarray) -> np.ndarray:
    """63-bit DCT hash of the lightness: the 8x8 lowest frequencies of the
    32x64 area shrink, DC dropped, each against their median."""
    import scipy.fft
    s = np.einsum("yh,nhw,xw->nyx", _PH_Y, L[..., 0], _PH_X, optimize=True)
    d = scipy.fft.dctn(s, axes=(1, 2), norm="ortho")[:, :8, :8].reshape(len(L), 64)[:, 1:]
    return d > np.median(d, axis=1, keepdims=True)


_PH_Y, _PH_X = _area(32, BH), _area(64, TW)


def lda_fit(X: np.ndarray, y: np.ndarray, shrink: float = 0.1):
    """Shrinkage LDA: standardise, pooled within-class scatter shrunk toward
    its mean variance, generalised eigenvectors of the between-class scatter.
    Returns (mean, scale, W (d, k)) with k = classes - 1; W' Sw W = I."""
    import scipy.linalg
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = (X - mu) / sd
    classes = np.unique(y)
    M = np.stack([Z[y == c].mean(0) for c in classes])
    R = Z - M[np.searchsorted(classes, y)]
    Sw = R.T @ R / len(Z)
    Sw = (1 - shrink) * Sw + shrink * np.trace(Sw) / len(Sw) * np.eye(len(Sw))
    n_c = np.array([(y == c).sum() for c in classes], float)
    Mc = M - (n_c[:, None] * M).sum(0) / n_c.sum()
    Sb = (Mc * n_c[:, None]).T @ Mc / n_c.sum()
    ev, V = scipy.linalg.eigh(Sb, Sw)
    k = min(len(classes) - 1, X.shape[1])
    W = V[:, ::-1][:, :k]
    return mu.astype(np.float32), sd.astype(np.float32), W.astype(np.float32)


def lda_project(X, model):
    mu, sd, W = model
    return ((X - mu) / sd) @ W


# ------------------------------------------------------------------ evaluation

DESCRIPTORS = ("current", "zncc_box", "zncc_anchor", "zncc_wide", "zncc_inner", "grid_lab", "hog",
               "grid_hog", "lda", "lda_zncc", "phash")


def session_features(out: Path, sid: str, agents, RL, RA) -> dict:
    """Everything one session contributes: per-tile art ZNCC per agent (best
    over the runtime search about the stored box and about the anchor, and
    over the whole strip), the anchored tile's descriptors, the current
    scorer's art scores, and the label-free clean flag."""
    from reticle.adjudication import identity
    S = load_session(out, sid)
    S["lab"] = lab(S["strips"])
    z, cov = strip_zncc(S["lab"], S["valid"], RL, RA)       # N, A, 2*YPAD+1, W-TW+1
    n = len(z)
    box, anc = anchors(S)
    ys = slice(YPAD - SEARCH_Y, YPAD + SEARCH_Y + 1)

    def around(x):
        idx = x[:, None] + np.arange(-SEARCH_X, SEARCH_X + 1)[None]
        zz = z[:, :, ys, :]                                 # N, A, 3, W'
        g = np.take_along_axis(zz, np.broadcast_to(idx[:, None, None, :],
                               (n, zz.shape[1], zz.shape[2], idx.shape[1])), axis=3)
        cc = np.take_along_axis(cov[:, :, ys, :], np.broadcast_to(idx[:, None, None, :],
                                (n, zz.shape[1], zz.shape[2], idx.shape[1])), axis=3)
        flat = g.reshape(n, g.shape[1], -1)
        k = flat.argmax(-1)
        return flat.max(-1), np.take_along_axis(cc.reshape(n, g.shape[1], -1), k[..., None], -1)[..., 0]

    zb, _ = around(box)
    za, ca = around(anc)
    wide = z.reshape(n, z.shape[1], -1).max(-1)
    # the anchored window, at the shift the best agent chose (label-free)
    best_agent = za.argmax(1)
    zsel = z[np.arange(n), best_agent][:, ys, :]          # N, 3, W'
    idx = anc[:, None] + np.arange(-SEARCH_X, SEARCH_X + 1)[None]
    g = np.take_along_axis(zsel, np.broadcast_to(idx[:, None, :], (n, zsel.shape[1], idx.shape[1])), 2)
    k = g.reshape(n, -1).argmax(1)
    ddy, ddx = np.unravel_index(k, g.shape[1:])
    T = np.empty((n, BH, TW, 3), np.float32)
    for dyv in range(g.shape[1]):
        for dxv in range(g.shape[2]):
            sel = (ddy == dyv) & (ddx == dxv)
            if sel.any():
                sub = {"lab": S["lab"][sel]}
                T[sel] = windows(sub, anc[sel], dxv - SEARCH_X, dyv - SEARCH_Y)
    # stored composition and shifts, scored as the runtime's art path does
    gallery = identity.load_identity_gallery(ROOT)
    cur = np.full((n, len(agents)), -1.0, np.float32)
    for i in range(n):
        sh = {str(k_): S["shifts"][i, j] for j, k_ in enumerate((-4, -2, 0, 2, 4))
              if S["shifts"][i, j].sum() > 0}
        sc = identity._portrait_scores(S["composition"][i], agents, gallery, shifts=sh or None)
        for a, v in sc.items():
            cur[i, agents.index(a)] = v
    clean = (ca.max(1) >= 0.999) & (za.max(1) >= CLEAN_ZNCC)
    # a killer searched over the whole strip (box -PAD..+PAD, rows +-YPAD): the
    # art finds its own portrait where the name start misplaced the box
    zw = np.where(S["victim"][:, None], za, wide)
    # the same searches with the art's border unweighted (INNER_MARGIN)
    zi, _ = strip_zncc(S["lab"], S["valid"], RL, inner_weights(RA))
    zia = np.take_along_axis(
        zi[:, :, ys, :], np.broadcast_to((anc[:, None] + np.arange(-SEARCH_X, SEARCH_X + 1)[None])
                                         [:, None, None, :], (n, zi.shape[1], 2 * SEARCH_Y + 1,
                                                              2 * SEARCH_X + 1)), 3)
    zinner = np.where(S["victim"][:, None], zia.reshape(n, zi.shape[1], -1).max(-1),
                      zi.reshape(n, zi.shape[1], -1).max(-1))
    # a self-framed portrait is clean too: its inner core matches at the anchor
    clean |= (ca.max(1) >= 0.999) & (zia.reshape(n, -1).max(1) >= CLEAN_ZNCC)
    flat = z.reshape(n, z.shape[1], -1)
    kbest = np.unravel_index(flat.max(1).argmax(1), z.shape[2:])
    return {"sid": sid, "tiles": S["tiles"], "sides": S["sides"], "victim": S["victim"],
            "zncc_box": zb, "zncc_anchor": za, "zncc_wide": zw, "zncc_inner": zinner, "current": cur,
            "best_dy": kbest[0] - YPAD, "best_dx": kbest[1] - PAD,
            "grid_lab": grid_lab(T), "hog": hog(T), "phash": phash(T), "clean": clean,
            "anchor_cov": ca.max(1)}


def features(out: Path, sids, agents, RL, RA, refresh=False) -> list[dict]:
    """Per-session features, cached beside the tiles."""
    import pickle
    got = []
    for sid in sids:
        f = out / f"feat_{sid}.pkl"
        if f.is_file() and not refresh:
            got.append(pickle.loads(f.read_bytes()))
            continue
        t0 = time.perf_counter()
        F = session_features(out, sid, agents, RL, RA)
        f.write_bytes(pickle.dumps(F))
        print(f"features {sid}: {len(F['tiles'])} tiles {time.perf_counter() - t0:.1f}s", flush=True)
        got.append(F)
    return got


def _centroid_scores(Xtr, ytr, Xte, A: int, whiten=True):
    """Negative half squared distance to each class mean, per dimension
    scaled by the pooled within-class variance; -inf where a class has no
    training tile."""
    sc = np.full((len(Xte), A), -np.inf, np.float32)
    classes = np.unique(ytr)
    M = np.stack([Xtr[ytr == c].mean(0) for c in classes])
    var = ((Xtr - M[np.searchsorted(classes, ytr)]) ** 2).mean(0) + 1e-4 if whiten else 1.0
    w = 1.0 / np.sqrt(var)
    a, b = Xte * w, M * w
    d2 = (a * a).sum(1)[:, None] - 2 * a @ b.T + (b * b).sum(1)[None]
    sc[:, classes] = -0.5 * d2
    return sc, M


def _hash_scores(Htr, ytr, Hte, A: int):
    sc = np.full((len(Hte), A), -np.inf, np.float32)
    classes = np.unique(ytr)
    M = np.stack([Htr[ytr == c].mean(0) > 0.5 for c in classes])
    ham = (Hte[:, None, :] != M[None]).sum(2)
    sc[:, classes] = -ham
    return sc, M


def _llr_slope(score_true, score_other):
    """`identity.portrait_llr`'s form: (same - diff) / var, for a score."""
    m1, m0 = np.mean(score_true), np.mean(score_other)
    var = (np.var(score_true) + np.var(score_other)) / 2
    return (m1 - m0) / max(var, 1e-9)


def loso_scores(F: list[dict], agents) -> dict:
    """Every descriptor's per-tile, per-agent scores, each test session
    scored with references from the other sessions only."""
    A = len(agents)
    ai = {a: i for i, a in enumerate(agents)}
    for f in F:
        f["y"] = np.array([ai[t["label"]] for t in f["tiles"]])
        f["train"] = f["clean"] & ~np.array([bool(t.get("eval_only")) for t in f["tiles"]])
        f["grid_hog"] = np.concatenate([f["grid_lab"], f["hog"]], 1)
    timing = {}
    for k, f in enumerate(F):
        tr = [g for j, g in enumerate(F) if j != k]
        y = np.concatenate([g["y"][g["train"]] for g in tr])
        sc = {"current": f["current"], "zncc_box": f["zncc_box"], "zncc_anchor": f["zncc_anchor"],
              "zncc_wide": f["zncc_wide"], "zncc_inner": f["zncc_inner"]}
        for name in ("grid_lab", "hog", "grid_hog"):
            X = np.concatenate([g[name][g["train"]] for g in tr])
            sc[name], _ = _centroid_scores(X, y, f[name], A)
        X = np.concatenate([g["grid_hog"][g["train"]] for g in tr])
        model = lda_fit(X, y)
        P = lda_project(X, model)
        sc["lda"], _ = _centroid_scores(P, y, lda_project(f["grid_hog"], model), A, whiten=False)
        H = np.concatenate([g["phash"][g["train"]] for g in tr])
        sc["phash"], _ = _hash_scores(H, y, f["phash"], A)
        # lda + art: the art ZNCC on the LDA's log-likelihood scale, its slope
        # fitted on the training sessions' true and side-rival scores
        zt = np.concatenate([g["zncc_anchor"][g["train"], g["y"][g["train"]]] for g in tr])
        zo = np.concatenate([g["zncc_anchor"][g["train"]].mean(1) for g in tr])
        sc["lda_zncc"] = sc["lda"] + _llr_slope(zt, zo) * f["zncc_anchor"]
        f["scores"] = sc
        f["lda_model"] = model
    return timing


def _cands(f, n, which, A, ai):
    t = f["tiles"][n]
    if which == "side5":
        return [ai[a] for a in f["sides"].get(t["riot_side"], []) if a in ai]
    if which == "match10":
        return sorted({ai[a] for v in f["sides"].values() for a in v if a in ai})
    return list(range(A))


def metrics(F: list[dict], agents, name: str, subset: str = "all", role: str | None = None) -> dict:
    """Top-1 over the side's five, the match's ten and every agent; margin
    (true less best other, side's five) raw and in within-class SDs.

    A tile whose agent has no reference in its fold (a trained descriptor
    that never saw the agent outside the test session) is `unscorable`:
    counted, and left out of the rates, which are over references held."""
    A = len(agents)
    ai = {a: i for i, a in enumerate(agents)}
    rows = []
    unscorable = Counter()
    for f in F:
        sc = f["scores"][name]
        for n, t in enumerate(f["tiles"]):
            if t.get("eval_only") or (subset == "clean" and not f["clean"][n]):
                continue
            if role and t["role"] != role:
                continue
            y = f["y"][n]
            if not np.isfinite(sc[n, y]):
                unscorable[t["label"]] += 1
                continue
            out = {"y": y, "sid": f["sid"], "true": sc[n, y]}
            for which in ("side5", "match10", "all"):
                c = [i for i in _cands(f, n, which, A, ai) if i != y]
                o = sc[n, c]
                out[which] = bool(sc[n, y] > o.max())
                if which == "side5":
                    out["margin"] = float(sc[n, y] - o.max()) if np.isfinite(o.max()) else np.nan
                    out["rival"] = c[int(o.argmax())]
            rows.append(out)
    if not rows:
        return {}
    true = np.array([r["true"] for r in rows])
    ys = np.array([r["y"] for r in rows])
    resid = true - np.array([true[ys == c].mean() for c in ys])
    sd = float(resid.std()) or 1.0
    mg = np.array([r["margin"] for r in rows])
    mg = mg[np.isfinite(mg)]
    pairs = defaultdict(list)
    for r in rows:
        if np.isfinite(r["margin"]):
            pairs[(agents[r["y"]], agents[r["rival"]])].append(r["margin"])
    worst = sorted(((float(np.median(v)) / sd, k, len(v)) for k, v in pairs.items() if len(v) >= 10))[:5]
    return {"n": len(rows), "unscorable": dict(unscorable),
            "side5": float(np.mean([r["side5"] for r in rows])),
            "match10": float(np.mean([r["match10"] for r in rows])),
            "all": float(np.mean([r["all"] for r in rows])),
            "wrong_side5": int(sum(not r["side5"] for r in rows)),
            "margin_med": float(np.median(mg)), "margin_p5": float(np.percentile(mg, 5)),
            "zmargin_med": float(np.median(mg) / sd), "zmargin_p5": float(np.percentile(mg, 5) / sd),
            "sd": sd, "worst_pairs": [(f"{a}/{b}", round(m, 2), k) for m, (a, b), k in worst]}


def entry_metrics(F, agents, name, role="killer", deaths=None) -> dict:
    """Per entry role: scores summed over its views, top-1 over the side's five."""
    ai = {a: i for i, a in enumerate(agents)}
    A = len(agents)
    res = {}
    for f in F:
        sc = f["scores"][name]
        by = defaultdict(list)
        for n, t in enumerate(f["tiles"]):
            if t["role"] == role and (deaths is None or t["death_id"] in deaths) \
                    and (deaths is not None or not t.get("eval_only")):
                by[t["death_id"]].append(n)
        for d, ns in by.items():
            y = f["y"][ns[0]]
            c = _cands(f, ns[0], "side5", A, ai)
            if y not in c:
                c = c + [y]
            s = np.where(np.isfinite(sc[ns][:, c]), sc[ns][:, c], -1e6).sum(0)
            pick = c[int(s.argmax())]
            res[d] = {"label": agents[y], "pick": agents[pick], "right": pick == y,
                      "views": len(ns),
                      "views_right": int(sum(int(np.argmax(np.where(np.isfinite(sc[n, c]), sc[n, c], -1e6))) == c.index(y) for n in ns))}
    return res


def time_descriptors(F, agents, RL, RA, n=500) -> dict:
    """Microseconds per tile, one CPU thread, on n anchored tiles: descriptor
    plus scoring against the side's five (and for ZNCC the 5x3 search)."""
    cv2.setNumThreads(1)
    f = F[0]
    S = load_session(Path(f["out"]), f["sid"])
    S["strips"], S["valid"] = S["strips"][:n], S["valid"][:n]
    S["victim"], S["tiles"] = S["victim"][:n], S["tiles"][:n]
    _, anc = anchors(S)
    us = {}
    t0 = time.perf_counter()
    S["lab"] = lab(S["strips"])
    us["lab_convert"] = (time.perf_counter() - t0) / n * 1e6
    T = windows(S, anc)
    for nm, fn in (("grid_lab", grid_lab), ("hog", hog), ("phash", phash)):
        t0 = time.perf_counter()
        fn(T)
        us[nm] = (time.perf_counter() - t0) / n * 1e6
    model = f["lda_model"]
    X = np.concatenate([f["grid_lab"][:n], f["hog"][:n]], 1)
    M = np.random.default_rng(0).normal(size=(5, model[2].shape[1])).astype(np.float32)
    t0 = time.perf_counter()
    P = lda_project(X, model)
    d = ((P[:, None, :] - M[None]) ** 2).sum(2)
    us["lda_project_and_score5"] = (time.perf_counter() - t0) / n * 1e6
    # CPU ZNCC: 5 agents, 5x3 offsets, numpy; the art's terms are constants
    ref, al = RL[:5], RA[:5]
    P = BH * TW
    w = (al / al.sum(axis=(1, 2), keepdims=True)).reshape(5, P)         # A, P
    mr = np.einsum("ap,apc->ac", w, ref.reshape(5, P, 3))
    rc = ref.reshape(5, P, 3) - mr[:, None, :]
    vr = np.einsum("ap,apc->a", w, rc * rc)
    rcw = (rc * w[..., None]).reshape(5, P * 3).T.copy()               # P*3, A
    wT = w.T.copy()                                                     # P, A
    sy, sx = 2 * SEARCH_Y + 1, 2 * SEARCH_X + 1
    t0 = time.perf_counter()
    for i in range(n):
        x0 = int(anc[i]) - SEARCH_X
        reg = S["lab"][i, YPAD - SEARCH_Y:YPAD + SEARCH_Y + BH, x0:x0 + TW + 2 * SEARCH_X]
        Wn = np.lib.stride_tricks.sliding_window_view(reg, (BH, TW), axis=(0, 1))
        Wn = Wn.transpose(0, 1, 3, 4, 2).reshape(sy * sx, P, 3)          # O, P, 3
        mx = np.stack([Wn[:, :, c] @ wT for c in range(3)], -1)           # O, A, 3
        xx = (Wn * Wn).sum(-1) @ wT - (mx * mx).sum(-1)
        cross = Wn.reshape(sy * sx, P * 3) @ rcw
        (cross / np.sqrt(np.maximum(xx, 1e-6) * vr[None])).max(0)
    us["zncc5_search15_cpu"] = (time.perf_counter() - t0) / n * 1e6
    # the current path: five shifted HSV compositions, intersected with 5 agents' art
    from reticle import appearance
    from reticle.adjudication import identity
    gallery = identity.load_identity_gallery(ROOT)
    t0 = time.perf_counter()
    for i in range(n):
        sh = {}
        for k_ in (-4, -2, 0, 2, 4):
            x = int(anc[i]) + k_
            art = np.ascontiguousarray(S["strips"][i, YPAD:YPAD + BH, x:x + TW])
            sh[str(k_)] = appearance.hsv_composition(art, np.ones(art.shape[:2], bool))
        identity._portrait_scores(None, agents[:5], gallery, shifts=sh)
    us["current_5shift_5agents"] = (time.perf_counter() - t0) / n * 1e6
    return us


def cmd_score(args) -> None:
    below_normal()
    out = Path(args.out)
    sids = args.sessions or sorted(p.stem for p in out.glob("*.npz"))
    agents, RL, RA = art_refs()
    F = features(out, sids, agents, RL, RA, refresh=args.refresh)
    for f in F:
        f["out"] = str(out)
    loso_scores(F, agents)
    report = {"sessions": sids, "tiles": int(sum(len(f["tiles"]) for f in F)), "rows": {}}
    names = args.only or DESCRIPTORS
    for nm in names:
        r = {}
        for subset in ("all", "clean"):
            for role in ("killer", "victim"):
                r[f"{subset}/{role}"] = metrics(F, agents, nm, subset, role)
        em = entry_metrics(F, agents, nm, "killer")
        vm = entry_metrics(F, agents, nm, "victim")
        r["entries_killer"] = {"n": len(em), "wrong": sum(not v["right"] for v in em.values())}
        r["entries_victim"] = {"n": len(vm), "wrong": sum(not v["right"] for v in vm.values())}
        if args.gallery:
            gal = json.loads(Path(args.gallery).read_text(encoding="utf-8"))
            ids = {e["death_id"]: e for e in gal}
            gm = entry_metrics(F, agents, nm, "killer", deaths=set(ids))
            r["gallery"] = {d: dict(v, cause=ids[d].get("cause")) for d, v in gm.items()}
        report["rows"][nm] = r
        k = r["clean/killer"]
        print(f"{nm:12s} killer clean side5 {k['side5']:.4f} all {k['all']:.4f} "
              f"zmed {k['zmargin_med']:.2f} zp5 {k['zmargin_p5']:.2f} | victim clean side5 "
              f"{r['clean/victim']['side5']:.4f} | entries wrong k {r['entries_killer']['wrong']}/"
              f"{r['entries_killer']['n']} v {r['entries_victim']['wrong']}/{r['entries_victim']['n']}",
              flush=True)
    if args.timing:
        report["us_per_tile"] = time_descriptors(F, agents, RL, RA)
        print(report["us_per_tile"])
    clean = np.concatenate([f["clean"] for f in F])
    report["clean_share"] = float(clean.mean())
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print("wrote", out / "report.json")
    if args.record:
        from reticle import metrics as run_log
        deps = {"prototype": SEPARABILITY_VERSION, "inner_margin": INNER_MARGIN,
                "search": [SEARCH_X, SEARCH_Y], "pad": PAD, "victim_outer": VICTIM_OUTER}
        ctx = {"sessions": sids, "riot": Path(args.riot_label).name if args.riot_label else None,
               "tiles": report["tiles"]}
        for nm, r in report["rows"].items():
            vals = {}
            for sub in ("clean/killer", "clean/victim", "all/killer", "all/victim"):
                m = r[sub]
                p = sub.replace("/", "_")
                vals.update({f"{p}_side5": round(m["side5"], 4), f"{p}_all": round(m["all"], 4),
                             f"{p}_n": m["n"], f"{p}_zmargin_med": round(m["zmargin_med"], 2),
                             f"{p}_zmargin_p5": round(m["zmargin_p5"], 2)})
            vals["entries_killer_wrong"] = r["entries_killer"]["wrong"]
            vals["entries_victim_wrong"] = r["entries_victim"]["wrong"]
            vals["entries_killer_n"] = r["entries_killer"]["n"]
            if "gallery" in r:
                for cause in sorted({v["cause"] for v in r["gallery"].values()}):
                    g = [v for v in r["gallery"].values() if v["cause"] == cause]
                    vals[f"gallery_{cause}_right"] = int(sum(bool(v["right"]) for v in g))
                    vals[f"gallery_{cause}_n"] = len(g)
            if nm in report.get("us_per_tile", {}):
                vals["us_per_tile"] = round(report["us_per_tile"][nm], 1)
            run_log.record("portrait_separability", part=nm, values=vals, deps=deps, context=ctx)
        if "us_per_tile" in report:
            run_log.record("portrait_separability", part="timing",
                           values={k: round(v, 1) for k, v in report["us_per_tile"].items()},
                           deps=deps, context=ctx)
        print("recorded portrait_separability")


def _gauss_llr_table(Fs, key, ai, A) -> dict:
    """Same-agent and other-agent score means and their pooled variance over
    clean labelled views of the side's five: `identity.portrait_llr`'s form."""
    same, diff = [], []
    for f in Fs:
        for n, t in enumerate(f["tiles"]):
            if t.get("eval_only") or not f["clean"][n]:
                continue
            c = _cands(f, n, "side5", A, ai)
            same.append(f[key][n, f["y"][n]])
            diff += [f[key][n, j] for j in c if j != f["y"][n]]
    same, diff = np.array(same), np.array(diff)
    var = (same.var() * len(same) + diff.var() * len(diff)) / (len(same) + len(diff))
    return {"same": float(same.mean()), "diff": float(diff.mean()), "var": float(var)}


def cmd_claims(args) -> None:
    """The portrait claim simulated per entry role: each view's posterior over
    the side's five (Gaussian LLR, `identity.portrait_llr`'s form; with
    `none`, plus a 'none of them' hypothesis at LLR 0) names at >= 0.9; an
    entry is named when >= 2 views name and all named views agree, as
    `death._portrait_channel` rules. `current` uses the stored art table;
    `zncc_inner` a table fitted leave-one-session-out. Exemplars and other
    channels are not simulated."""
    from reticle.adjudication import identity
    below_normal()
    out = Path(args.out)
    sids = sorted(p.stem for p in out.glob("*.npz"))
    agents, RL, RA = art_refs()
    ai = {a: i for i, a in enumerate(agents)}
    A = len(agents)
    F = features(out, sids, agents, RL, RA)
    for f in F:
        f["y"] = np.array([ai[t["label"]] for t in f["tiles"]])
    res = defaultdict(Counter)
    for k, f in enumerate(F):
        tabs = {("current", False): identity.PORTRAIT_LIKELIHOOD["art"],
                ("zncc_inner", True): _gauss_llr_table(F[:k] + F[k + 1:], "zncc_inner", ai, A)}
        by = defaultdict(list)
        for n, t in enumerate(f["tiles"]):
            if not t.get("eval_only"):
                by[(t["death_id"], t["role"])].append(n)
        for (key, none), tab in tabs.items():
            name = key + ("+none" if none else "")
            slope = (tab["same"] - tab["diff"]) / tab["var"]
            mid = (tab["same"] + tab["diff"]) / 2.0
            picks = []
            for n, t in enumerate(f["tiles"]):
                c = _cands(f, n, "side5", A, ai)
                s = f[key][n, c]
                if key == "current" and (s <= -1).all():
                    picks.append(None)
                    continue
                L = slope * (s - mid)
                if none:
                    L = np.append(L, 0.0)
                p = np.exp(L - L.max())
                p /= p.sum()
                b = int(p.argmax())
                picks.append(c[b] if b < len(c) and p[b] >= identity.PORTRAIT_POSTERIOR_MIN else None)
            for (d, role), ns in by.items():
                named = [picks[n] for n in ns if picks[n] is not None]
                y = f["y"][ns[0]]
                o = (("right" if named[0] == y else "wrong")
                     if len(named) >= 2 and len(set(named)) == 1 else "refused")
                res[(name, role)][o] += 1
                ours = f["tiles"][ns[0]].get("ours")
                if name == "current":
                    res[("stored_verdict", role)]["null" if not ours else
                                                  "right" if canon(ours) == canon(agents[y]) else "wrong"] += 1
    for k in sorted(res):
        print(k, dict(res[k]))
    if args.record:
        from reticle import metrics as run_log
        deps = {"prototype": SEPARABILITY_VERSION, "inner_margin": INNER_MARGIN,
                "posterior_min": identity.PORTRAIT_POSTERIOR_MIN}
        for (name, role), c in res.items():
            run_log.record("portrait_separability", part=f"claims/{name}/{role}",
                           values=dict(c), deps=deps, context={"sessions": sids})
        print("recorded portrait_separability claims")


# ------------------------------------------------------------------ pictures

def _bgr(L: np.ndarray) -> np.ndarray:
    """Lab float tiles back to uint8 BGR (display)."""
    return (np.clip(cv2.cvtColor(L.astype(np.float32), cv2.COLOR_Lab2BGR), 0, 1) * 255).astype(np.uint8)


def _art_bgr(RL, RA, a: int) -> np.ndarray:
    return (_bgr(RL[a]) * RA[a][..., None]).astype(np.uint8)


def aligned_tiles(out: Path, sid: str, idx, label_agents, RL, RA):
    """The (n, BH, TW, 3) Lab tiles at the shift where each view's own agent's
    art (inner weights) correlates best, victims mirrored; with that ZNCC."""
    S = load_session(out, sid)
    L = lab(S["strips"][idx])
    w = inner_weights(RA)
    T = np.empty((len(idx), BH, TW, 3), np.float32)
    best = np.empty(len(idx), np.float32)
    for a in sorted(set(label_agents)):
        sel = np.array([x == a for x in label_agents])
        z, _ = strip_zncc(L[sel], S["valid"][np.asarray(idx)[sel]], RL[a:a + 1], w[a:a + 1])
        zf = z[:, 0].reshape(sel.sum(), -1)
        k = zf.argmax(1)
        dy, dx = np.unravel_index(k, z.shape[2:])
        Ls = L[sel]
        T[sel] = Ls[np.arange(len(Ls))[:, None, None], dy[:, None, None] + np.arange(BH)[None, :, None],
                    dx[:, None, None] + np.arange(TW)[None, None, :]]
        best[sel] = zf.max(1)
    return T, best


def _caption(img: np.ndarray, text: str, scale: int = 3) -> np.ndarray:
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    big = np.pad(big, ((14, 2), (0, 4), (0, 0)))
    cv2.putText(big, text, (1, 11), cv2.FONT_HERSHEY_PLAIN, 0.8, (255, 255, 255), 1)
    return big


def _sheet_grid(cells: list[np.ndarray], cols: int) -> np.ndarray:
    h = max(c.shape[0] for c in cells)
    w = max(c.shape[1] for c in cells)
    cells = [np.pad(c, ((0, h - c.shape[0]), (0, w - c.shape[1]), (0, 0))) for c in cells]
    cells += [np.zeros_like(cells[0])] * (-len(cells) % cols)
    return np.vstack([np.hstack(cells[i:i + cols]) for i in range(0, len(cells), cols)])


def cmd_sheet(args) -> None:
    """Fade and Iso tiles from 223d636bf8d2 and the other matches holding
    either, each captioned with the stored scorer's pick and the inner art
    ZNCC's pick over the side's five; then any `--entries` (death_id|role)."""
    below_normal()
    out = Path(args.out)
    agents, RL, RA = art_refs()
    ai = {a: i for i, a in enumerate(agents)}
    sids = sorted(p.stem for p in out.glob("*.npz"))
    F = {f["sid"]: f for f in features(out, sids, agents, RL, RA)}
    pair = args.pair
    blocks = [np.vstack([_caption(_art_bgr(RL, RA, ai[a]), f"art {a}") for a in pair])]
    rng = np.random.default_rng(0)
    for sid, f in F.items():
        lab_ = [t["label"] for t in f["tiles"]]
        if not any(x in pair for x in lab_):
            continue
        cells = []
        for a in pair:
            for role in ("killer", "victim"):
                idx = [i for i, t in enumerate(f["tiles"]) if t["label"] == a and t["role"] == role
                       and not t.get("eval_only")]
                if not idx:
                    continue
                idx = sorted(rng.choice(idx, min(args.per, len(idx)), replace=False).tolist())
                T, best = aligned_tiles(out, sid, idx, [ai[a]] * len(idx), RL, RA)
                for j, i in enumerate(idx):
                    c = _cands(f, i, "side5", len(agents), ai)
                    cur = agents[c[int(np.argmax(f["current"][i, c]))]]
                    new = agents[c[int(np.argmax(f["zncc_inner"][i, c]))]]
                    cells.append(_caption(_bgr(T[j]), f"{sid[:4]} {f['tiles'][i]['t_ms'] / 1000:.0f}s "
                                          f"{role[0]} {a}: cur {cur} / zncc {new} {best[j]:.2f}"))
        if cells:
            blocks.append(_sheet_grid(cells, args.per))
    W = max(b.shape[1] for b in blocks)
    sheet = np.vstack([np.pad(b, ((0, 6), (0, W - b.shape[1]), (0, 0))) for b in blocks])
    cv2.imwrite(args.png, sheet)
    print("wrote", args.png, sheet.shape)
    if args.entries:
        cells = []
        for spec in args.entries:
            d, role = spec.split("|")
            sid = d.split(":")[1]
            f = F[sid]
            idx = [i for i, t in enumerate(f["tiles"]) if t["death_id"] == d and t["role"] == role]
            if not idx:
                continue
            i = idx[len(idx) // 2]
            c = _cands(f, i, "side5", len(agents), ai)
            new = c[int(np.argmax(f["zncc_inner"][i, c]))]
            y = ai[f["tiles"][i]["label"]]
            T, best = aligned_tiles(out, sid, [i], [new], RL, RA)
            row = np.hstack([_bgr(T[0]), np.zeros((BH, 3, 3), np.uint8), _art_bgr(RL, RA, new),
                             np.zeros((BH, 3, 3), np.uint8), _art_bgr(RL, RA, y)])
            cells.append(_caption(row, f"{sid[:4]} {f['tiles'][i]['t_ms'] / 1000:.1f}s {role}: tile | "
                                  f"art {agents[new]} z{f['zncc_inner'][i, new]:.2f} | Riot {agents[y]} "
                                  f"z{f['zncc_inner'][i, y]:.2f}"))
        p = args.png.replace(".png", "_disputed.png")
        cv2.imwrite(p, np.vstack(cells))
        print("wrote", p)


def cmd_fingerprint(args) -> None:
    """Per worst pair: the two agents' mean aligned tiles, the per-pixel Fisher
    ratio, where the art ZNCC's evidence for one over the other lies, and the
    LDA fingerprint's per-cell weight; with the LDA pair separation ratio."""
    below_normal()
    out = Path(args.out)
    agents, RL, RA = art_refs()
    ai = {a: i for i, a in enumerate(agents)}
    sids = sorted(p.stem for p in out.glob("*.npz"))
    F = features(out, sids, agents, RL, RA)
    for f in F:
        f["y"] = np.array([ai[t["label"]] for t in f["tiles"]])
        f["train"] = f["clean"] & ~np.array([bool(t.get("eval_only")) for t in f["tiles"]])
    X = np.concatenate([np.concatenate([f["grid_lab"], f["hog"]], 1)[f["train"]] for f in F])
    y = np.concatenate([f["y"][f["train"]] for f in F])
    model = lda_fit(X, y)
    P = lda_project(X, model)
    classes = np.unique(y)
    C = {c: P[y == c].mean(0) for c in classes}
    # every pair's centroid distance over the two classes' within RMS
    ratios = {}
    for i, a in enumerate(classes):
        for b in classes[i + 1:]:
            rms = np.sqrt(np.concatenate([((P[y == a] - C[a]) ** 2).sum(1),
                                          ((P[y == b] - C[b]) ** 2).sum(1)]).mean())
            ratios[(agents[a], agents[b])] = float(np.linalg.norm(C[a] - C[b]) / rms)
    worst = sorted(ratios.items(), key=lambda kv: kv[1])[:5]
    rng = np.random.default_rng(0)
    w_in = inner_weights(RA)
    rows = []
    report = {"lda_dims": int(model[2].shape[1]), "input_dims": int(X.shape[1]),
              "worst_pairs_ratio": [(f"{a}/{b}", round(r, 2)) for (a, b), r in worst], "pairs": {}}
    for pa in args.pairs:
        a, b = pa.split("/")
        tiles = {}
        for ag in (a, b):
            got = []
            for f in F:
                idx = [i for i in np.flatnonzero(f["train"]) if f["y"][i] == ai[ag]]
                if idx:
                    idx = sorted(rng.choice(idx, min(args.per_session, len(idx)), replace=False).tolist())
                    T, _ = aligned_tiles(out, f["sid"], idx, [ai[ag]] * len(idx), RL, RA)
                    got.append(T)
            tiles[ag] = np.concatenate(got)
        Ta, Tb = tiles[a], tiles[b]
        fisher = (((Ta.mean(0) - Tb.mean(0)) ** 2) / (Ta.var(0) + Tb.var(0) + 1e-3)).sum(-1)
        # the inner art ZNCC's evidence for a over b, per pixel, averaged over
        # views of a and (sign flipped) views of b: x_hat . (r_hat_a - r_hat_b)
        def hat(Z, w):
            m = (Z * w[..., None]).sum((-3, -2), keepdims=True) / w.sum()
            Zc = Z - m
            return Zc / np.sqrt((Zc * Zc * w[..., None]).sum((-3, -2, -1), keepdims=True) / w.sum())
        wa, wb = w_in[ai[a]], w_in[ai[b]]
        ra, rb = hat(RL[ai[a]], wa), hat(RL[ai[b]], wb)
        ev = ((hat(Ta, wa) * ra * wa[..., None] - hat(Ta, wb) * rb * wb[..., None]).sum(-1).mean(0)
              - (hat(Tb, wa) * ra * wa[..., None] - hat(Tb, wb) * rb * wb[..., None]).sum(-1).mean(0)) / 2
        # LDA: the pair's discriminant on the standardised inputs, contribution
        # per input = weight x the two means' difference; summed per grid cell
        mu, sd, Wm = model
        g = Wm @ (C[ai[a]] - C[ai[b]])
        da = (X[y == ai[a]].mean(0) - X[y == ai[b]].mean(0)) / sd
        contrib = np.abs(g * da)
        nlab = GRID[0] * GRID[1] * 3
        cell = contrib[:nlab].reshape(GRID[0], GRID[1], 3).sum(-1) + \
            contrib[nlab:].reshape(GRID[0], GRID[1], HOG_BINS).sum(-1)
        top = np.argsort(cell.ravel())[::-1][:6]
        report["pairs"][pa] = {"n": [len(Ta), len(Tb)], "lda_ratio": round(ratios.get((a, b), ratios.get((b, a), 0)), 2),
                               "lda_top_cells_rc": [divmod(int(t), GRID[1]) for t in top],
                               "lda_share_hog": round(float(contrib[nlab:].sum() / contrib.sum()), 3)}

        def heat(m):
            m = np.clip(m / max(np.percentile(m, 99), 1e-6), 0, 1)
            return cv2.applyColorMap((m * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)

        def over(base, m):
            return cv2.addWeighted(base, 0.45, heat(m), 0.55, 0)

        cellmap = cv2.resize(cell.astype(np.float32), (TW, BH), interpolation=cv2.INTER_NEAREST)
        ma, mb = _bgr(Ta.mean(0)), _bgr(Tb.mean(0))
        cells = [_caption(ma, f"mean {a} (n{len(Ta)})", 4), _caption(mb, f"mean {b} (n{len(Tb)})", 4),
                 _caption(over(ma, fisher), "Fisher per pixel", 4),
                 _caption(over(ma, np.clip(ev, 0, None)), f"ZNCC evidence {a}>{b}", 4),
                 _caption(over(ma, cellmap), "LDA cell weight", 4),
                 _caption(over(mb, cellmap), "LDA cell weight", 4)]
        rows.append(_sheet_grid(cells, 6))
    cv2.imwrite(args.png, np.vstack([np.pad(r, ((0, 8), (0, 0), (0, 0))) for r in rows]))
    print(json.dumps(report))
    print("wrote", args.png)


# ------------------------------------------------------------------ main

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--riot", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--sessions", nargs="*")
    e.add_argument("--extra", help="a gallery entries.json whose death ids are kept as eval_only")
    v = sub.add_parser("score")
    v.add_argument("--out", required=True)
    v.add_argument("--sessions", nargs="*")
    v.add_argument("--only", nargs="*")
    v.add_argument("--gallery")
    v.add_argument("--refresh", action="store_true")
    v.add_argument("--timing", action="store_true")
    v.add_argument("--record", action="store_true", help="append run summaries to the metrics log")
    v.add_argument("--riot-label", help="the Riot score file the tiles came from (context only)")
    c = sub.add_parser("claims")
    c.add_argument("--out", required=True)
    c.add_argument("--record", action="store_true")
    s = sub.add_parser("sheet")
    s.add_argument("--out", required=True)
    s.add_argument("--png", required=True)
    s.add_argument("--pair", nargs=2, default=["Fade", "Iso"])
    s.add_argument("--per", type=int, default=6, help="tiles per agent, role and session")
    s.add_argument("--entries", nargs="*", help="death_id|role entries drawn beside both arts")
    g = sub.add_parser("fingerprint")
    g.add_argument("--out", required=True)
    g.add_argument("--png", required=True)
    g.add_argument("--pairs", nargs="*", default=["Fade/Iso", "Clove/Reyna", "Brimstone/Breach"])
    g.add_argument("--per-session", type=int, default=40)
    args = ap.parse_args(argv)
    {"extract": cmd_extract, "score": cmd_score, "claims": cmd_claims, "sheet": cmd_sheet,
     "fingerprint": cmd_fingerprint}[args.cmd](args)


if __name__ == "__main__":
    main()
