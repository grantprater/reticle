r"""Read the combat report, the post-death panel, with no labels.

    .\.venv\Scripts\python.exe prototypes\combat_report.py scan <session> [--hz 1]
    .\.venv\Scripts\python.exe prototypes\combat_report.py judge <session>

Why this exists
---------------
The panel [domain:combat_report/panel-layout] is the one surface that states,
per enemy engaged, the damage each way, the head/body/legs hit split and who
killed whom. The killfeed gives only the kill. Nothing here is labelled: the
panel's own arithmetic and the channels already stored are the checks.

* **Locator.** The COMBAT REPORT header is fixed UI text. One crop of it, mined
  from `a06f04a0059f` at 187 s, is matched over the right of the frame by
  normalised correlation. The panel's height changes with its row count and
  with the round's end [domain:combat_report/frozen-after-death], so every
  field is placed relative to the header, never at a fixed screen position.
* **Digits.** The scoreline's mined digit templates (`ocr.Templates`), matched
  after `ocr.normalise` scales each blob to the shared grid. Whether they read
  a different size of the same font is prediction P3, not an assumption.
* **Checks, all label-free.** A panel is read in every frame it is up and the
  reads must agree (P2); each damage number must be explained by hits times one
  weapon's damage (P4, P5); KILLED YOU must appear once and KILLED must match
  the player's killfeed kills (P6). `scan` stores the reads; `judge` scores them
  from storage without decoding video.

Coverage is every death [domain:combat_report/appears-on-death] plus any buy-phase
reopen, which can carry extra row kinds [domain:combat_report/survived-round-rows].

Predictions are logged in the store's `notes/predictions.jsonl` under
`combat-report`.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import ocr  # noqa: E402
from reticle.decode import sample_at, sample_frames  # noqa: E402
from reticle.store import Store  # noqa: E402

VERSION = "combat-report-proto-0.1.2"

# The mined header: session, time and box (x0, y0, x1, y1) at 1080p.
HEADER_SRC = ("a06f04a0059f", 187000.0, (1633, 465, 1778, 481))
SEARCH = (1300, 120, 1920, 960)          # x0, y0, x1, y1 searched for the header
HEADER_MIN = 0.70                        # correlation that counts as found

# Offsets from the header's top-left (hx, hy), measured on 187 s.
ROW0, PITCH, MAX_ROWS = 25, 58, 5
OUT_NUM = (-121, 6, -55, 42)             # x0, y0, x1, y1 within a row
IN_NUM = (199, 6, 262, 42)
OUT_HITS = (-53, 3, -37, 55)
IN_HITS = (180, 3, 196, 55)
OUT_FLAG = (-121, 43, -55, 56)           # KILLED
IN_FLAG = (195, 43, 262, 56)             # KILLED YOU
NAME = (55, 43, 140, 56)

BIG_H = (18, 40)                         # damage digit height band, px
SMALL_H = (6, 14)                        # hit-count digit height band, px
# Zero hit counts and both flags are drawn grey (~150-200), not white, so they
# take their own threshold; the panel background sits near 40.
DIM = 110


def _source(sid: str) -> tuple[str, float]:
    m = json.loads((Store().root / "manifests" / f"{sid}.json").read_text())
    return m["source"]["path"], float(m["source"]["fps"])


def header_template() -> np.ndarray:
    cache = Store().root / "reference" / "templates" / "combat-report-header.png"
    if cache.is_file():
        return cv2.imread(str(cache), cv2.IMREAD_GRAYSCALE)
    sid, t, (x0, y0, x1, y1) = HEADER_SRC
    path, fps = _source(sid)
    s = next(sample_at(path, [t], fps))
    g = cv2.cvtColor(s.frame, cv2.COLOR_BGR2GRAY)[y0:y1, x0:x1]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(cache), g)
    return g


def locate(gray: np.ndarray, tpl: np.ndarray) -> tuple[float, int, int]:
    x0, y0, x1, y1 = SEARCH
    r = cv2.matchTemplate(gray[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(r)
    return float(mx), x0 + loc[0], y0 + loc[1]


def _field(gray, hx, hy, box, dy=0):
    x0, y0, x1, y1 = box
    return gray[hy + dy + y0: hy + dy + y1, hx + x0: hx + x1]


def read_number(patch, tpl, band, threshold=ocr.THRESHOLD):
    """Digits in `patch` within the height band: (text, worst score, worst
    margin), or (None, reason) fields when nothing digit-shaped is there."""
    if patch.size == 0:
        return {"text": None, "reason": "off-frame"}
    binary, raw = ocr._raw_components(patch, threshold)
    lo, hi = band
    glyphs = [ocr.Glyph(x=x, y=y, w=w, h=h,
                        bitmap=ocr.normalise(binary[y:y + h, x:x + w]))
              for x, y, w, h, a in sorted(raw) if lo <= h <= hi and w <= h]
    if not glyphs:
        return {"text": None, "reason": "no-glyph"}
    return _labelled(glyphs, tpl)


def _labelled(glyphs, tpl):
    text, score, margin = "", 1.0, 1.0
    for g in glyphs:
        lab, s, m = tpl.match(g)
        text += lab
        score, margin = min(score, s), min(margin, m)
    return {"text": text, "score": round(score, 3), "margin": round(margin, 3)}


def read_hits(patch, tpl, threshold=DIM):
    """Three stacked hit counts, head to legs, one blob per count."""
    if patch.size == 0:
        return {"text": None, "reason": "off-frame"}
    binary, raw = ocr._raw_components(patch, threshold)
    lo, hi = SMALL_H
    blobs = sorted((b for b in raw if lo <= b[3] <= hi), key=lambda b: b[1])
    if len(blobs) != 3:
        return {"text": None, "reason": f"{len(blobs)}-blobs"}
    # The panel draws a zero count grey and any other count white, so the
    # blob's peak decides zero; only a white blob is matched, re-thresholded
    # at the white level so its grey anti-aliasing does not thicken it.
    text, score, margin = "", 1.0, 1.0
    for x, y, w, h, a in blobs:
        cell = patch[y:y + h, x:x + w]
        if cell.max() < ocr.THRESHOLD:
            text += "0"
            continue
        wb = (cell >= ocr.THRESHOLD).astype(np.uint8)
        ys, xs = np.nonzero(wb)
        wb = wb[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        lab, s, m = tpl.match(ocr.Glyph(x=x, y=y, w=wb.shape[1], h=wb.shape[0],
                                        bitmap=ocr.normalise(wb)))
        text += lab
        score, margin = min(score, s), min(margin, m)
    return {"text": text, "score": round(score, 3), "margin": round(margin, 3)}


def bright(patch, threshold=ocr.THRESHOLD) -> float:
    return float((patch >= threshold).mean()) if patch.size else 0.0


def read_panel(gray, hx, hy, tpl):
    rows = []
    for k in range(MAX_ROWS):
        dy = ROW0 + k * PITCH
        out = read_number(_field(gray, hx, hy, OUT_NUM, dy), tpl, BIG_H)
        inc = read_number(_field(gray, hx, hy, IN_NUM, dy), tpl, BIG_H)
        if out["text"] is None and inc["text"] is None:
            break
        rows.append({
            "out": out, "in": inc,
            "out_hits": read_hits(_field(gray, hx, hy, OUT_HITS, dy), tpl),
            "in_hits": read_hits(_field(gray, hx, hy, IN_HITS, dy), tpl),
            "out_flag": round(bright(_field(gray, hx, hy, OUT_FLAG, dy), DIM), 3),
            "in_flag": round(bright(_field(gray, hx, hy, IN_FLAG, dy), DIM), 3),
            "name_ink": round(bright(_field(gray, hx, hy, NAME, dy), 150), 3),
        })
    return rows


def scan(sid: str, hz: float) -> Path:
    path, fps = _source(sid)
    head = header_template()
    tpl = ocr.Templates.load(json.loads(
        (Store().root / "manifests" / f"{sid}.json").read_text())["source_profile"])
    out = Store().root / "analysis" / f"combat_report_{sid}.jsonl"
    n = found = 0
    with out.open("w", encoding="utf-8") as f:
        for s in sample_frames(path, hz, fps):
            g = cv2.cvtColor(s.frame, cv2.COLOR_BGR2GRAY)
            score, hx, hy = locate(g, head)
            rec = {"t_ms": s.t_ms, "header": round(score, 3), "hx": hx, "hy": hy,
                   "version": VERSION}
            if score >= HEADER_MIN:
                rec["rows"] = read_panel(g, hx, hy, tpl)
                found += 1
            f.write(json.dumps(rec) + "\n")
            n += 1
    print(f"{n} frames, header found in {found}; wrote {out}")
    return out


def _deaths(sid: str) -> np.ndarray:
    import pyarrow.parquet as pq
    f = glob.glob(str(Store().root / "l1" / "hud" / "*" / f"session={sid}" / "hud.parquet"))[0]
    t = pq.read_table(f, columns=["t_ms", "kf_player_death"]).to_pydict()
    tm = np.array(t["t_ms"])
    d = np.array([(v or 0) > 0 for v in t["kf_player_death"]])
    return tm[np.flatnonzero(d & ~np.r_[False, d[:-1]])]


def _rounds(sid: str) -> list[dict]:
    import pyarrow.parquet as pq
    f = glob.glob(str(Store().root / "l2" / "rounds" / "*" / f"session={sid}" / "*.parquet"))[0]
    return pq.read_table(f).to_pylist()


def judge(sid: str) -> None:
    recs = [json.loads(l) for l in
            (Store().root / "analysis" / f"combat_report_{sid}.jsonl").open()]
    hs = np.array([r["header"] for r in recs])
    print("header score quantiles (all frames):",
          np.round(np.quantile(hs, [0.5, 0.9, 0.95, 0.99, 1.0]), 3))
    print("header score histogram:", np.histogram(hs, bins=[0, .3, .4, .5, .6, .7, .8, .9, 1.01])[0])
    up = [r for r in recs if r["header"] >= HEADER_MIN]
    # Panel episodes: runs of found frames separated by < 3 s.
    eps, cur = [], []
    for r in up:
        if cur and r["t_ms"] - cur[-1]["t_ms"] > 3000:
            eps.append(cur); cur = []
        cur.append(r)
    if cur: eps.append(cur)
    deaths = _deaths(sid)
    print(f"{len(eps)} panel episodes; {len(deaths)} killfeed death onsets")
    totals, disagreements, rowcounts = {}, [], {}
    pairs, seen = [], set()
    for e in eps:
        t0, t1 = e[0]["t_ms"], e[-1]["t_ms"]
        near = deaths[(deaths >= t0 - 5000) & (deaths <= t0 + 2000)]
        sigs = {}
        for r in e:
            sig = tuple((row["out"]["text"], row["in"]["text"],
                         row["out_hits"]["text"], row["in_hits"]["text"])
                        for row in r.get("rows", []))
            sigs[sig] = sigs.get(sig, 0) + 1
        top = max(sigs.items(), key=lambda kv: kv[1])
        print(f"  {t0/1000:7.1f}-{t1/1000:7.1f}s  n={len(e):3d}  death={[round(x/1000,1) for x in near]}"
              f"  reads={len(sigs)}  modal({top[1]})={list(top[0])}")
        # P2 per field: each (row, field) read against the episode's mode.
        # A null read is a refusal and is counted apart from a disagreement.
        for k in range(len(top[0])):
            for f, name in enumerate(("out", "in", "out_hits", "in_hits")):
                vals = [r["rows"][k][name]["text"] for r in e if len(r.get("rows", [])) > k]
                mode = top[0][k][f]
                n_null = sum(v is None for v in vals)
                bad = [(r["t_ms"] / 1000, r["rows"][k][name]["text"]) for r in e
                       if len(r.get("rows", [])) > k
                       and r["rows"][k][name]["text"] not in (None, mode)]
                totals.setdefault(name, [0, 0, 0])
                totals[name][0] += len(vals) - n_null - len(bad)
                totals[name][1] += len(bad)
                totals[name][2] += n_null
                if bad:
                    disagreements.append((t0 / 1000, k, name, mode, bad[:4]))
        rowcounts[len(top[0])] = rowcounts.get(len(top[0]), 0) + 1
        # Episodes that repeat an earlier episode's panel (a buy-phase reopen)
        # would double-count its rows in the arithmetic.
        if top[0] not in seen:
            seen.add(top[0])
            for out, inc, oh, ih in top[0]:
                pairs.append(("out", oh, out, t0 / 1000))
                pairs.append(("in", ih, inc, t0 / 1000))
    print("\nP2 field agreement with episode mode (agree, disagree, refused):")
    for name, v in totals.items():
        print(f"  {name:9s} {v}")
    print("modal row counts:", rowcounts)
    print("disagreements (episode start, row, field, mode, first reads):")
    for d in disagreements:
        print("  ", d)
    arithmetic(pairs)


def arithmetic(pairs) -> None:
    """P4/P5 without a weapon table typed from memory: per-hit values come from
    rows that hit one location only, and every other row must be an exact sum
    of those values. A row no combination explains is listed, not dropped."""
    unit = {"in": {0: set(), 1: set(), 2: set()}, "out": {0: set(), 1: set(), 2: set()}}
    clean = []
    for side, hits, dmg, t in pairs:
        if hits is None or dmg is None or not hits.isdigit() or not dmg.isdigit():
            continue
        h = [int(c) for c in hits]; d = int(dmg)
        clean.append((side, h, d, t))
        nz = [i for i in range(3) if h[i]]
        if len(nz) == 1 and d % h[nz[0]] == 0:
            unit[side][nz[0]].add(d // h[nz[0]])
    for side in ("in", "out"):
        print(f"\nP4 {side}: per-hit values from single-location rows "
              f"(head, body, legs): {[sorted(unit[side][i]) for i in range(3)]}")
    allu = {i: unit["in"][i] | unit["out"][i] for i in range(3)}
    for side in ("in", "out"):
        ok, zero_hits, unexplained = 0, [], []
        for s, h, d, t in clean:
            if s != side:
                continue
            if sum(h) == 0:
                if d:
                    zero_hits.append((t, h, d))
                continue
            # One weapon per row: the same weapon's head/body/leg values, so
            # try each observed unit value per location independently -- a loose
            # test, reported as such.
            cands = {0}
            for i in range(3):
                vals = allu[i] or {0}
                cands = {c + h[i] * v for c in cands for v in vals} if h[i] else cands
            if d in cands:
                ok += 1
            else:
                unexplained.append((t, h, d))
        print(f"P4 {side}: explained {ok}; damage with zero hits {len(zero_hits)}; "
              f"unexplained {len(unexplained)}")
        for u in zero_hits[:12]:
            print("   zero-hit", u)
        for u in unexplained[:20]:
            print("   unexplained", u)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("scan"); a.add_argument("session"); a.add_argument("--hz", type=float, default=1.0)
    b = sub.add_parser("judge"); b.add_argument("session")
    args = ap.parse_args()
    if args.cmd == "scan":
        scan(args.session, args.hz)
    else:
        judge(args.session)


if __name__ == "__main__":
    main()
