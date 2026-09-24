r"""The combat report experiment: what the production reader's rows say.

    .\.venv\Scripts\python.exe -m reticle scan <session> --only combat_report
    .\.venv\Scripts\python.exe prototypes\combat_report.py judge <session>
    .\.venv\Scripts\python.exe prototypes\combat_report.py flags <session>
    .\.venv\Scripts\python.exe prototypes\combat_report.py icons <session>
    .\.venv\Scripts\python.exe prototypes\combat_report.py weapons <session>

The reader was promoted on 2026-09-24 into `reticle.combat_report` and the
panel and round rules into `reticle.adjudication.combat_report`; this file
calls both and keeps what is still an experiment. Nothing here is labelled:
the panel's own arithmetic and the channels already stored are the checks.

* `judge` -- frame-to-frame agreement per field inside each panel (P2), and
  damage against per-hit values pooled over all rows (P4, loose).
* `flags` -- the report's per-round kills and deaths against the stored rounds
  and `checks.KNOWN_KD` (R1, R2), recorded as the `combat_report/flags` series.
* `icons`, `weapons` -- rows grouped by the enemy's weapon icon, and each row's
  damage decomposed into per-hit values from the OTHER rows in its group
  [domain:combat_report/damage-decomposition].

Coverage is every death [domain:combat_report/appears-on-death] plus the
buy-phase round summary [domain:combat_report/round-summary], which can carry
extra row kinds [domain:combat_report/survived-round-rows]; the panel freezes
at death and grows at the round's end [domain:combat_report/frozen-after-death].

Predictions are logged in the store's `notes/predictions.jsonl` under
`combat-report`.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import metrics, ocr  # noqa: E402
from reticle.adjudication import combat_report as adj  # noqa: E402
from reticle.checks import KNOWN_KD  # noqa: E402
from reticle.combat_report import PITCH, ROW0, field_at  # noqa: E402
from reticle.decode import sample_at  # noqa: E402
from reticle.rounds import player_death_times  # noqa: E402
from reticle.store import Store  # noqa: E402
from reticle.version import COMBAT_REPORT_ROUND_VERSION, COMBAT_REPORT_VERSION  # noqa: E402


def _manifest(sid: str) -> dict:
    return Store().read_manifest(sid)


def _date(sid: str) -> str:
    from reticle.cli import _date_of
    return _date_of(_manifest(sid))


def _frames(sid: str) -> list[dict]:
    rows = Store().read_events("combat_report", sid)
    if not rows or rows[0].get("combat_report_version") != COMBAT_REPORT_VERSION:
        raise SystemExit(f"{sid}: scan first: reticle scan {sid} --only combat_report")
    return [r for r in rows if r.get("kind") == "frame"]


def _deaths(sid: str) -> list[float]:
    return player_death_times(Store().read_hud(sid, _date(sid)))


def _rounds(sid: str) -> list[dict]:
    return Store().read_rounds(sid, _date(sid)).to_pylist()


def _panels(sid: str) -> list[dict]:
    ps = adj.panels(_frames(sid), _deaths(sid))
    adj.assign_rounds(ps, _rounds(sid))
    return ps


ICON = (35, 0, 160, 32)                  # weapon icon box within a row
ICON_GRID = (24, 96)                     # h, w after tight crop


def crop_icons(sid: str) -> Path:
    """Crop each panel's weapon icons from one frame that shows its modal read."""
    frames = _frames(sid)
    reps = []
    for p in _panels(sid):
        want = tuple(tuple(row[f] for f in adj.FIELDS) for row in p["rows"])
        shown = [r for r in frames if p["start_ms"] <= r["t_ms"] <= p["end_ms"]
                 and "rows" in r and (r.get("header") or 0) >= adj.HEADER_MIN
                 and adj.frame_read(r) == want]
        if shown:
            reps.append((shown[len(shown) // 2], p))
    m = _manifest(sid)["source"]
    by_t = {r["t_ms"]: (r, p) for r, p in reps}
    bitmaps, meta = [], []
    for s in sample_at(m["path"], sorted(by_t), float(m["fps"])):
        r, p = by_t.get(s.t_ms) or min(reps, key=lambda q: abs(q[0]["t_ms"] - s.t_ms))
        g = cv2.cvtColor(s.frame, cv2.COLOR_BGR2GRAY)
        for k, row in enumerate(p["rows"]):
            cell = field_at(g, r["hx"], r["hy"], ICON, ROW0 + k * PITCH)
            b = (cell >= ocr.THRESHOLD).astype(np.uint8)
            ys, xs = np.nonzero(b)
            if len(xs) < 30:
                continue
            b = b[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            bitmaps.append(cv2.resize(b, ICON_GRID[::-1], interpolation=cv2.INTER_AREA))
            meta.append({"t_ms": r["t_ms"], "episode_start_ms": p["start_ms"], "row": k,
                         "read": [row[f] for f in adj.FIELDS],
                         "aspect": round(b.shape[1] / b.shape[0], 2)})
    out = Store().root / "analysis" / f"combat_report_icons_{sid}.npz"
    np.savez_compressed(out, bitmaps=np.array(bitmaps), meta=json.dumps(meta))
    print(f"{len(reps)} panels, {len(bitmaps)} icons; wrote {out}")
    return out


SAME_ICON = 0.78                         # IoU joining two icons; Q1 says the gap is 0.70-0.85


def _cluster(bm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Single-link groups of binary icons by IoU, and the IoU matrix."""
    f = bm.reshape(len(bm), -1).astype(bool)
    inter = (f[:, None, :] & f[None, :, :]).sum(-1)
    union = (f[:, None, :] | f[None, :, :]).sum(-1)
    iou = inter / np.maximum(union, 1)
    lab = np.arange(len(bm))
    for i in range(len(bm)):
        for j in range(i + 1, len(bm)):
            if iou[i, j] >= SAME_ICON and lab[i] != lab[j]:
                lab[lab == lab[j]] = lab[i]
    _, lab = np.unique(lab, return_inverse=True)
    return lab, iou


def _sums(hits: list[int], vals: list[set[int]], mixed: bool) -> set[int]:
    """Totals reachable with one value per location (`mixed` False) or one value
    per bullet (`mixed` True)."""
    out = {0}
    for n, vs in zip(hits, vals):
        if not n:
            continue
        if mixed:
            for _ in range(n):
                out = {a + v for a in out for v in vs}
        else:
            out = {a + n * v for a in out for v in vs}
    return out


def decompose(rows: list[tuple[list[int], int]]) -> list[tuple[str, str]]:
    """Classify each (hits, damage) row of one weapon group against per-hit
    values taken from the OTHER rows only [domain:combat_report/damage-decomposition].

    Returns (class, detail) per row: exact-one-band, exact-mixed, short (wallbang
    or cap candidate), excess (ability candidate), inside (between the bounds
    but no sum hits it), or unknown (no values for a hit location)."""
    out = []
    for k, (h, d) in enumerate(rows):
        vals = [set(), set(), set()]
        others = [r for j, r in enumerate(rows) if j != k]
        for hh, dd in others:
            nz = [i for i in range(3) if hh[i]]
            if len(nz) == 1 and dd % hh[nz[0]] == 0:
                vals[nz[0]].add(dd // hh[nz[0]])
        # One pass of solving a two-location row for its unknown location.
        for hh, dd in others:
            nz = [i for i in range(3) if hh[i]]
            if len(nz) == 2:
                a, b = nz
                for known, unk in ((a, b), (b, a)):
                    if vals[known] and not vals[unk]:
                        for v in list(vals[known]):
                            rest = dd - hh[known] * v
                            if rest > 0 and rest % hh[unk] == 0:
                                vals[unk].add(rest // hh[unk])
        if sum(h) == 0:
            out.append(("excess" if d else "exact-one-band", f"{d} with no hits"))
            continue
        if any(h[i] and not vals[i] for i in range(3)):
            out.append(("unknown", f"no per-hit value for {[i for i in range(3) if h[i] and not vals[i]]}"))
            continue
        one, mix = _sums(h, vals, False), _sums(h, vals, True)
        if d in one:
            out.append(("exact-one-band", ""))
        elif d in mix:
            out.append(("exact-mixed", ""))
        elif d < min(mix):
            out.append(("short", f"{min(mix) - d} below the lowest sum"))
        elif d > max(mix):
            out.append(("excess", f"{d - max(mix)} above the highest sum"))
        else:
            out.append(("inside", f"between {min(mix)} and {max(mix)}"))
    return out


def weapons(sid: str) -> None:
    z = np.load(Store().root / "analysis" / f"combat_report_icons_{sid}.npz")
    bm, meta = z["bitmaps"], json.loads(str(z["meta"]))
    lab, iou = _cluster(bm)
    tri = iou[np.triu_indices(len(bm), 1)]
    print(f"{len(bm)} icons, {lab.max() + 1} groups at IoU >= {SAME_ICON}")
    print("Q1 pairwise IoU histogram:",
          dict(zip(["<.5", ".5-.6", ".6-.7", ".7-.78", ".78-.85", ".85-.9", ">=.9"],
                   np.histogram(tri, [0, .5, .6, .7, .78, .85, .9, 1.01])[0].tolist())))
    # Contact sheet: one line per group.
    sheet = []
    for g in range(lab.max() + 1):
        idx = np.flatnonzero(lab == g)[:12]
        line = np.hstack([np.pad(bm[i] * 255, 2) for i in idx] +
                         [np.zeros((ICON_GRID[0] + 4, (ICON_GRID[1] + 4) * (12 - len(idx))), np.uint8)])
        sheet.append(line)
    cv2.imwrite(str(Store().root / "analysis" / f"combat_report_icons_{sid}.png"),
                cv2.resize(np.vstack(sheet).astype(np.uint8), None, fx=2, fy=2,
                           interpolation=cv2.INTER_NEAREST))
    for side, hk, dk in (("in", 3, 1), ("out", 2, 0)):
        print(f"\n== {side} rows grouped by icon ==")
        tally = {}
        for g in range(lab.max() + 1):
            rows, where = [], []
            for i in np.flatnonzero(lab == g):
                m = meta[i]; hits, dmg = m["read"][hk], m["read"][dk]
                if hits and dmg and hits.isdigit() and dmg.isdigit():
                    rows.append(([int(c) for c in hits], int(dmg)))
                    where.append(m["episode_start_ms"] / 1000)
            if not rows:
                continue
            per = [sorted({d // h[i] for h, d in rows
                           if [x for x in h if x] == [h[i]] and h[i] and d % h[i] == 0})
                   for i in range(3)]
            cls = decompose(rows)
            for c, _ in cls:
                tally[c] = tally.get(c, 0) + 1
            print(f" group {g} (n={len(rows)}) per-hit head/body/legs {per}")
            for (h, d), (c, why), t in zip(rows, cls, where):
                if c not in ("exact-one-band",):
                    print(f"    {t:7.1f}s  hits {h} dmg {d}: {c} {why}")
        print(f" {side} tally: {tally}")


def flags(sid: str) -> None:
    """R1/R2: the adjudication's per-round counts, printed and recorded against
    the stored rounds and `checks.KNOWN_KD`."""
    rounds = _rounds(sid)
    ev = adj.events(sid, _frames(sid), rounds, _deaths(sid))
    head = ev[0]
    for r in (e for e in ev if e["kind"] == "round"):
        tag = (("" if r["kills_agree"] is not False else " KILLS-DIFFER")
               + ("" if r["deaths_agree"] is not False else " DEATHS-DIFFER")
               + (" no panel" if r["kills"] is None else ""))
        print(f"{r['round_no']:>3} stored K{r['stored_kills']} D{r['stored_deaths']}  "
              f"report K{r['kills']} D{r['deaths']} A{r['assists']}{tag}")
    print(f"\nrounds with a panel {head['rounds_with_panel']}/{head['rounds']}; "
          f"report kills {head['kills']}, deaths {head['deaths']}, assists {head['assists']}")
    known = KNOWN_KD.get(sid)
    controls = [] if not known else [
        {"name": "kills_vs_known_kd", "observed": head["kills"], "expected": known[0], "tol": 0},
        {"name": "deaths_vs_known_kd", "observed": head["deaths"], "expected": known[1], "tol": 0}]
    seen = [r for r in ev if r["kind"] == "round" and r["kills"] is not None]
    metrics.record("combat_report", part="flags", session=sid,
                   values={"kills": head["kills"], "deaths": head["deaths"],
                           "rounds_with_panel": head["rounds_with_panel"], "rounds": head["rounds"],
                           "kills_agree_rounds": sum(r["kills_agree"] is True for r in seen),
                           "deaths_agree_rounds": sum(r["deaths_agree"] is True for r in seen),
                           "stored_round_kills": sum(r["player_kills"] or 0 for r in rounds),
                           "stored_round_deaths": sum(r["player_deaths"] or 0 for r in rounds)},
                   deps={"version": COMBAT_REPORT_VERSION, "round_version": COMBAT_REPORT_ROUND_VERSION,
                         "flag_min": adj.FLAG_MIN, "header_min": adj.HEADER_MIN},
                   context={"rounds_version": rounds[0].get("round_version")},
                   controls=controls)


def judge(sid: str) -> None:
    """P2 per field inside each panel, then the loose pooled arithmetic."""
    ps = _panels(sid)
    totals = {f: [0, 0, 0] for f in adj.FIELDS}
    for p in ps:
        for f, v in p["agreement"].items():
            totals[f] = [a + b for a, b in zip(totals[f], v)]
        print(f"  {p['start_ms']/1000:7.1f}-{p['end_ms']/1000:7.1f}s  {p['kind']:7s} round {p['round_no']}  "
              f"frames {p['frames']} (modal {p['modal_frames']})  "
              + str([tuple(row[f] for f in adj.FIELDS) for row in p["rows"]]))
    print("\nP2 field agreement with the panel's mode (agree, disagree, refused):")
    for f, v in totals.items():
        print(f"  {f:9s} {v}")
    pairs = []
    for p in ps:
        for row in p["rows"]:
            pairs.append(("out", row["out_hits"], row["out"], p["start_ms"] / 1000))
            pairs.append(("in", row["in_hits"], row["in"], p["start_ms"] / 1000))
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


PORTRAIT_SAME = 0.8                      # thumbnail correlation joining two row portraits
CARD = (-123, -125, -38, -35)            # killer card portrait, header-relative
ROW_PORTRAIT = (-6, 2, 34, 56)           # row portrait inside its chevron edge
ROW_NAME = (40, 36, 155, 50)             # player name text under the weapon
ART_V_MIN = 30                           # drop only near-black; the art is often dark


def _composition(crop):
    from reticle import appearance
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return appearance.hsv_composition(crop, hsv[:, :, 2] >= ART_V_MIN)


def _name_bits(gray):
    b = (gray >= 150).astype(np.uint8)
    ys, xs = np.nonzero(b)
    if len(xs) < 20:
        return None
    return cv2.resize(b[ys.min():ys.max() + 1, xs.min():xs.max() + 1], (80, 12),
                      interpolation=cv2.INTER_AREA)


def portraits(sid: str) -> None:
    """I1-I3: name report portraits against the gallery over the enemy lineup."""
    from reticle import appearance  # noqa: F401
    from reticle.adjudication.identity import (PORTRAIT_MARGIN_MIN, _portrait_scores,
                                               load_identity_gallery)
    from reticle.lineup import load_lineup
    store = Store()
    gallery = load_identity_gallery(store.root)
    lineup = load_lineup(sid, store.root)
    enemy = [r.get("agent") or r.get("best_guess") for r in lineup["sides"]["enemy"]]
    allies = [r.get("agent") or r.get("best_guess") for r in lineup["sides"]["ally"]]
    frames = _frames(sid)
    reps = []
    for p in _panels(sid):
        want = tuple(tuple(row[f] for f in adj.FIELDS) for row in p["rows"])
        shown = [r for r in frames if p["start_ms"] <= r["t_ms"] <= p["end_ms"]
                 and "rows" in r and (r.get("header") or 0) >= adj.HEADER_MIN
                 and adj.frame_read(r) == want]
        if shown:
            reps.append((shown[len(shown) // 2], p))
    m = _manifest(sid)["source"]
    by_t = {r["t_ms"]: (r, p) for r, p in reps}

    def name(comp, cands):
        sc = sorted(_portrait_scores(comp, cands, gallery).items(), key=lambda kv: -kv[1])
        if len(sc) < 2:
            return None, 0.0, sc
        return (sc[0][0] if sc[0][1] - sc[1][1] >= PORTRAIT_MARGIN_MIN else None,
                round(sc[0][1] - sc[1][1], 3), sc[:2])

    rows_out, cards = [], []
    for s in sample_at(m["path"], sorted(by_t), float(m["fps"])):
        r, p = by_t[s.t_ms]
        f = s.frame
        hx, hy = r["hx"], r["hy"]
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        if p["kind"] == "death":
            c = f[hy + CARD[1]:hy + CARD[3], hx + CARD[0]:hx + CARD[2]]
            cards.append((p, name(_composition(c), enemy)))
        for k, row in enumerate(p["rows"]):
            dy = ROW0 + k * PITCH
            crop = field_at(f, hx, hy, ROW_PORTRAIT, dy)
            nm = _name_bits(field_at(g, hx, hy, ROW_NAME, dy))
            thumb = cv2.resize(crop, (20, 27), interpolation=cv2.INTER_AREA).astype(np.float32)
            rows_out.append({"t": p["start_ms"] / 1000, "row": k, "kind": p["kind"],
                             "killed_you": row["killed_you"], "name_bits": nm, "thumb": thumb,
                             "enemy": name(_composition(crop), enemy),
                             "open": name(_composition(crop), sorted(gallery))})
    named = [x for x in rows_out if x["enemy"][0]]
    print(f"I1: {len(named)}/{len(rows_out)} rows named over the enemy lineup {enemy}")
    for x in rows_out:
        print(f"  {x['t']:7.1f}s row {x['row']} {x['kind']:7s} KY={x['killed_you']!s:5s} "
              f"enemy {x['enemy'][0]!s:9s} m={x['enemy'][1]:.3f} {x['enemy'][2]}  "
              f"open-gallery top {x['open'][2][:1]}")
    # I2: group rows by name crop (IoU of binarised text) and check one agent per group.
    groups = []
    for x in rows_out:
        if x["name_bits"] is None:
            continue
        for gset in groups:
            a, b = gset[0]["name_bits"].astype(bool), x["name_bits"].astype(bool)
            if (a & b).sum() / max(1, (a | b).sum()) >= 0.6:
                gset.append(x)
                break
        else:
            groups.append([x])
    bad = 0
    for gset in groups:
        agents = {x["enemy"][0] for x in gset if x["enemy"][0]}
        bad += len(agents) > 1
        print(f"  name group n={len(gset)}: agents {sorted(agents)}  unnamed {sum(1 for x in gset if not x['enemy'][0])}")
    print(f"I2: {len(groups)} name groups, {bad} with more than one agent")
    # Portrait clusters by direct correlation: the same agent's art repeats.
    def corr(a, b):
        a = (a - a.mean()) / (a.std() + 1e-6); b = (b - b.mean()) / (b.std() + 1e-6)
        return float((a * b).mean())
    clusters = []
    for x in rows_out:
        for c in clusters:
            if corr(c[0]["thumb"], x["thumb"]) >= PORTRAIT_SAME:
                c.append(x)
                break
        else:
            clusters.append([x])
    name_of = {id(x): gi for gi, gset in enumerate(groups) for x in gset}
    print(f"portrait clusters at corr >= {PORTRAIT_SAME}: {len(clusters)}")
    for c in clusters:
        agents = Counter(x["enemy"][0] for x in c)
        names = Counter(name_of.get(id(x)) for x in c)
        print(f"  n={len(c):2d} gallery names {dict(agents)}  name groups {dict(names)}")
    agree = 0
    for p, c in cards:
        ky = [x for x in rows_out if x["t"] == p["start_ms"] / 1000 and x["killed_you"]]
        kya = ky[0]["enemy"][0] if ky else None
        agree += c[0] is not None and c[0] == kya
        print(f"  card {p['start_ms']/1000:7.1f}s {c[0]!s:9s} m={c[1]:.3f}  KILLED YOU row {kya}")
    print(f"I3: card and KILLED YOU row agree on {agree}/{len(cards)} death panels")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("judge", "flags", "icons", "weapons", "portraits"):
        sub.add_parser(name).add_argument("session")
    args = ap.parse_args()
    {"judge": judge, "flags": flags, "icons": crop_icons, "weapons": weapons,
     "portraits": portraits}[args.cmd](args.session)


if __name__ == "__main__":
    main()
