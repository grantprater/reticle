"""The dev loop's declared audit sample and its windows files.

A change is tested where it is expected to move output (the targeted
windows) plus on a fixed, declared sample of the rest, reported with error
bars; the full corpus run is the batched acceptance run.

The sample (`DEV_SAMPLE_VERSION`) is data, not a rule rerun at each use:
`SAMPLE` holds whole rounds of the 21 Riot-paired matches, two per match,
built by `build` from the stored round tables and frozen here. A rebuilt
round table may move a boundary; `reticle dev-sample --check` reports the
drift, and only a new version changes the windows.

How the rounds were chosen (`build`):

* by opportunity, never by outcome: every stored round the HUD saw start
  and close is a candidate; nothing a reader wrote, and no record of where
  a reader erred, enters the choice;
* round 1 is excluded whole, not trimmed to its buy phase. The round table
  opens round 1 at the capture's first sample (`start_source`
  `capture_start`, `t_start_ms` 0 in all 21 matches), which may hold the
  menu or start inside the round (`rounds.round_bounds`), and it stores no
  buy-phase start from which a window could begin. Sampling round 1 needs
  that start in the round table first;
* stratified by match, which fixes the map, the profile and the widget
  scale (the 1.15x variant `4f207c0c4e39` and `b3b9defb6fd7` among them),
  and by half: one round from rounds 2-12 and one from round 13 on
  (overtime with the second half), or two from the first half when the
  match ended inside it;
* seeded: within a stratum the round with the lowest
  `sha256(f"{SEED}|{session}|{round_no}")` wins;
* a whole round, `t_start_ms` to `t_close_ms`, so every round phase (buy,
  live, post-plant, the end screen) is inside each window.

Held-out sets. The Riot-paired matches carry held-out sets for fitted
models: the entity-state six (`docs/ENTITY_STATE.md`), the `ally_prior`
six, `ability_shape_eval`'s two, the glyph tables' labelled splits and the
audio gate's folds. The sample feeds reader regression checks, which fit no
parameter, so it does not drop those matches; it must never feed a fit
either, and no model with a held-out set may be tuned on its scores.
`HELD_OUT_WINDOWS` names the one reader-evaluation window declared held out
of every total (`prototypes/roster_split_eval.py`); `build` drops any round
that overlaps it.

A windows file is CSV with the header `session,t0,t1,reason`, times in
seconds of capture time, `#` lines ignored. `targets_from_residuals` and
`targets_from_stream` write the targeted half: windows around a residual
list (`session,t[,reason]`) or around stored rows where a changed code path
fires. `reticle dev-sample` takes both at once (`--residuals CSV ...
--stream S --where F=V`) and joins every window they name into one set.

Resolution. The sample holds 309 Riot kills
[metric:riot_truth_window/deaths~devs-master-sample-r2#riot_kills=309]; an
unpaired Wilson interval or a rule-of-three bound over that many resolves
about one percent absolute, while the full run's error rates are fractions
of a percent. A change adding ten errors across the corpus can pass the
sample's intervals unseen.
So a change is compared with its base kill by kill inside the same windows
(`prototypes/riot_ground_truth.py --compare-deaths`): every outcome Riot's
record scores that flips is listed, and any broken one is a fact to read,
whatever the intervals say. Errors outside the windows stay unseen; the targets carry the
places a change is expected to move, and the full run stays the acceptance.

Targets from both codes. Score the base over the whole corpus once and make
targets from its residuals; score the branch in those windows and the
sample with `--compare-deaths`, writing `--residuals-out` (the union of both
codes' residuals, each tagged by the codes that left it); then
`reticle dev-sample --residuals UNION.csv --extend TARGETS.csv` writes the
windows around residuals the windows already held do not cover with their
padding. Rerun the trial and the score on those and repeat until it writes
none (`new_targets`).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Iterable, NamedTuple

import numpy as np

DEV_SAMPLE_VERSION = "dev-sample-0.1.0"
SEED = DEV_SAMPLE_VERSION

#: The Riot-paired matches (`prototypes/riot_ground_truth.py --all`).
MATCHES = ("043bafca271a", "223d636bf8d2", "3694746e4e54", "4f207c0c4e39", "5822b6646448",
           "587c15b07779", "59c70f1ef720", "7010b3d62460", "75a55a296d3b", "96aa1ae9b96f",
           "9acf02f98283", "a06f04a0059f", "a1a995e6b19b", "b3b9defb6fd7", "b7d24102a6f6",
           "bdfdcf009dba", "bfad2778a372", "c40d950031bb", "c62c2b06bcfb", "e37fdeca944f",
           "ff636d173b07")

#: Reader-evaluation windows held out of every total: (session, t0_s, t1_s, owner).
HELD_OUT_WINDOWS = (("587c15b07779", 1474.0, 1484.5, "prototypes/roster_split_eval.py HELD_OUT"),)

#: Rounds per match, and the round that opens the second half.
PER_MATCH = 2
SECOND_HALF = 13

HEADER = ("session", "t0", "t1", "reason")


class Window(NamedTuple):
    session: str
    t0: float     # seconds of capture time, inclusive
    t1: float
    reason: str


# ------------------------------------------------------------------ the sample

def _rank(session: str, round_no: int, seed: str = SEED) -> str:
    return hashlib.sha256(f"{seed}|{session}|{round_no}".encode()).hexdigest()


def opportunity_rounds(rounds: list[dict], held_out=HELD_OUT_WINDOWS) -> list[dict]:
    """The rounds a sample may draw: seen to start and close, clear of every
    held-out window. Opportunity only; no reader output is read."""
    out = []
    for r in rounds:
        t0, t1 = r.get("t_start_ms"), r.get("t_close_ms") or r.get("t_end_ms")
        if t0 is None or t1 is None or r.get("start_source") == "capture_start":
            continue
        sid = r.get("session_id")
        if any(sid == s and t0 / 1000.0 <= b and a <= t1 / 1000.0 for s, a, b, _ in held_out):
            continue
        out.append(r)
    return out


def build(rounds_by_session: dict[str, list[dict]], seed: str = SEED,
          per_match: int = PER_MATCH) -> list[Window]:
    """The sample from stored round rows (`Store.read_rounds(...).to_pylist()`),
    keyed by session. Pure and deterministic."""
    out = []
    for sid in sorted(rounds_by_session):
        rows = [dict(r, session_id=sid) for r in rounds_by_session[sid]]
        cand = opportunity_rounds(rows)
        first = [r for r in cand if int(r["round_no"]) < SECOND_HALF]
        second = [r for r in cand if int(r["round_no"]) >= SECOND_HALF]
        strata = [("first_half", first), ("second_half", second)] if second else \
                 [("first_half", first)]
        take = {name: per_match // len(strata) for name, _ in strata}
        take[strata[0][0]] += per_match - sum(take.values())
        for name, rs in strata:
            rs = sorted(rs, key=lambda r: _rank(sid, int(r["round_no"]), seed))[:take[name]]
            for r in sorted(rs, key=lambda r: r["round_no"]):
                t1 = r.get("t_close_ms") or r.get("t_end_ms")
                out.append(Window(sid, float(r["t_start_ms"]) / 1000.0, float(t1) / 1000.0,
                                  f"{DEV_SAMPLE_VERSION} round {int(r['round_no'])} {name} "
                                  f"{r.get('map') or '?'}"))
    return out


def build_from_store(store, sessions: Iterable[str] = MATCHES) -> list[Window]:
    """`build` over the store's current round tables."""
    rounds = {}
    for sid in sessions:
        man = store.read_manifest(sid)
        tbl = store.read_rounds(sid, man["ingested_at"][:10])
        if tbl is None:
            raise SystemExit(f"{sid}: no stored rounds -- run `reticle rounds {sid}`")
        rounds[sid] = tbl.to_pylist()
    return build(rounds)


#: `build` over the round tables of 2026-10-05 (round-0.8.0), frozen.
SAMPLE: tuple[Window, ...] = (
    Window('043bafca271a', 1081.0, 1179.5, 'dev-sample-0.1.0 round 11 first_half haven'),
    Window('043bafca271a', 1814.0, 1900.0, 'dev-sample-0.1.0 round 20 second_half haven'),
    Window('223d636bf8d2', 854.0, 952.0, 'dev-sample-0.1.0 round 8 first_half haven'),
    Window('223d636bf8d2', 1397.5, 1482.5, 'dev-sample-0.1.0 round 14 second_half haven'),
    Window('3694746e4e54', 535.0, 626.0, 'dev-sample-0.1.0 round 6 first_half ascent'),
    Window('3694746e4e54', 1755.5, 1825.25, 'dev-sample-0.1.0 round 19 second_half ascent'),
    Window('4f207c0c4e39', 78.0, 186.0, 'dev-sample-0.1.0 round 2 first_half split'),
    Window('4f207c0c4e39', 1712.5, 1790.5, 'dev-sample-0.1.0 round 18 second_half split'),
    Window('5822b6646448', 506.5, 567.0, 'dev-sample-0.1.0 round 7 first_half lotus'),
    Window('5822b6646448', 1230.5, 1298.0, 'dev-sample-0.1.0 round 14 second_half lotus'),
    Window('587c15b07779', 455.5, 549.0, 'dev-sample-0.1.0 round 6 first_half lotus'),
    Window('587c15b07779', 1322.5, 1401.5, 'dev-sample-0.1.0 round 16 second_half lotus'),
    Window('59c70f1ef720', 1077.5, 1222.0, 'dev-sample-0.1.0 round 12 first_half ascent'),
    Window('59c70f1ef720', 1675.5, 1770.0, 'dev-sample-0.1.0 round 17 second_half ascent'),
    Window('7010b3d62460', 736.5, 846.0, 'dev-sample-0.1.0 round 8 first_half lotus'),
    Window('7010b3d62460', 1632.0, 1726.5, 'dev-sample-0.1.0 round 17 second_half lotus'),
    Window('75a55a296d3b', 301.5, 379.5, 'dev-sample-0.1.0 round 2 first_half abyss'),
    Window('75a55a296d3b', 379.5, 447.5, 'dev-sample-0.1.0 round 3 first_half abyss'),
    Window('96aa1ae9b96f', 621.5, 727.0, 'dev-sample-0.1.0 round 6 first_half haven'),
    Window('96aa1ae9b96f', 1274.0, 1381.5, 'dev-sample-0.1.0 round 13 second_half haven'),
    Window('9acf02f98283', 287.5, 353.5, 'dev-sample-0.1.0 round 3 first_half ascent'),
    Window('9acf02f98283', 2141.0, 2276.5, 'dev-sample-0.1.0 round 23 second_half ascent'),
    Window('a06f04a0059f', 1122.0, 1261.0, 'dev-sample-0.1.0 round 12 first_half ascent'),
    Window('a06f04a0059f', 1358.5, 1427.5, 'dev-sample-0.1.0 round 14 second_half ascent'),
    Window('a1a995e6b19b', 248.0, 347.5, 'dev-sample-0.1.0 round 4 first_half sunset'),
    Window('a1a995e6b19b', 2091.0, 2169.0, 'dev-sample-0.1.0 round 24 second_half sunset'),
    Window('b3b9defb6fd7', 527.0, 641.0, 'dev-sample-0.1.0 round 4 first_half summit'),
    Window('b3b9defb6fd7', 1593.0, 1676.0, 'dev-sample-0.1.0 round 15 second_half summit'),
    Window('b7d24102a6f6', 965.0, 1032.5, 'dev-sample-0.1.0 round 9 first_half split'),
    Window('b7d24102a6f6', 1759.0, 1819.5, 'dev-sample-0.1.0 round 17 second_half split'),
    Window('bdfdcf009dba', 1103.5, 1214.5, 'dev-sample-0.1.0 round 11 first_half lotus'),
    Window('bdfdcf009dba', 1987.5, 2101.0, 'dev-sample-0.1.0 round 19 second_half lotus'),
    Window('bfad2778a372', 349.5, 451.0, 'dev-sample-0.1.0 round 3 first_half split'),
    Window('bfad2778a372', 1381.5, 1482.5, 'dev-sample-0.1.0 round 13 second_half split'),
    Window('c40d950031bb', 216.5, 320.0, 'dev-sample-0.1.0 round 2 first_half ascent'),
    Window('c40d950031bb', 741.0, 838.0, 'dev-sample-0.1.0 round 7 first_half ascent'),
    Window('c62c2b06bcfb', 1044.0, 1106.0, 'dev-sample-0.1.0 round 11 first_half split'),
    Window('c62c2b06bcfb', 1378.0, 1447.0, 'dev-sample-0.1.0 round 15 second_half split'),
    Window('e37fdeca944f', 1102.5, 1193.5, 'dev-sample-0.1.0 round 12 first_half sunset'),
    Window('e37fdeca944f', 2118.5, 2189.0, 'dev-sample-0.1.0 round 23 second_half sunset'),
    Window('ff636d173b07', 317.0, 397.0, 'dev-sample-0.1.0 round 4 first_half summit'),
    Window('ff636d173b07', 1447.5, 1535.0, 'dev-sample-0.1.0 round 15 second_half summit'),
)


def drift(frozen: Iterable[Window], fresh: Iterable[Window], tol_s: float = 1.0) -> list[str]:
    """Lines naming each frozen window the fresh build moved or dropped."""
    fresh = {(w.session, w.reason): w for w in fresh}
    out = []
    for w in frozen:
        f = fresh.get((w.session, w.reason))
        if f is None:
            out.append(f"{w.session} {w.reason}: not in the rebuilt sample")
        elif abs(f.t0 - w.t0) > tol_s or abs(f.t1 - w.t1) > tol_s:
            out.append(f"{w.session} {w.reason}: frozen {w.t0:.1f}-{w.t1:.1f} s, "
                       f"stored rounds {f.t0:.1f}-{f.t1:.1f} s")
    return out


# --------------------------------------------------------------- windows files

def read_windows(path) -> list[Window]:
    """A windows file: CSV `session,t0,t1,reason`, seconds, `#` lines skipped."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_windows(text, str(path))


def parse_windows(text: str, where: str = "<windows>") -> list[Window]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    rows = list(csv.reader(lines))
    head = tuple(c.strip() for c in rows[0])
    if head[:3] != HEADER[:3]:
        raise ValueError(f"{where}: header must start {','.join(HEADER)}, got {','.join(head)}")
    out = []
    for i, r in enumerate(rows[1:], 2):
        if len(r) < 3:
            raise ValueError(f"{where} row {i}: needs session,t0,t1")
        sid = r[0].strip()
        try:
            t0, t1 = float(r[1]), float(r[2])
        except ValueError:
            raise ValueError(f"{where} row {i}: t0 and t1 must be seconds, got {r[1]!r}, {r[2]!r}")
        if not sid or not np.isfinite(t0) or not np.isfinite(t1) or t1 < t0:
            raise ValueError(f"{where} row {i}: needs a session and finite t0 <= t1")
        out.append(Window(sid, t0, t1, ",".join(r[3:]).strip() if len(r) > 3 else ""))
    return out


def format_windows(windows: Iterable[Window]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    for x in windows:
        w.writerow([x.session, f"{x.t0:.3f}", f"{x.t1:.3f}", x.reason])
    return buf.getvalue()


def write_windows(path, windows: Iterable[Window]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(format_windows(windows), encoding="utf-8")
    return p


def load(files: Iterable = (), sample: bool = False) -> list[Window]:
    """The windows a dev check reads: each file's, then the declared sample."""
    out = []
    for f in files or ():
        out += read_windows(f)
    if sample:
        out += list(SAMPLE)
    return out


def spans_ms(windows: Iterable[Window]) -> dict[str, list[tuple[float, float]]]:
    """Merged (t0_ms, t1_ms) spans per session."""
    by: dict[str, list[tuple[float, float]]] = {}
    for w in windows:
        by.setdefault(w.session, []).append((w.t0 * 1000.0, w.t1 * 1000.0))
    return {s: merge(v) for s, v in by.items()}


def merge(spans) -> list[tuple[float, float]]:
    """Overlapping or touching spans joined, sorted."""
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def in_spans(t_ms, spans) -> np.ndarray:
    """Boolean mask: each time inside some inclusive span (spans merged)."""
    t = np.asarray(t_ms, dtype=float)
    if not len(spans):
        return np.zeros(t.shape, dtype=bool)
    sp = np.asarray(merge(spans), dtype=float)
    j = np.searchsorted(sp[:, 0], t, side="right") - 1
    ok = j >= 0
    jj = np.clip(j, 0, len(sp) - 1)
    return ok & (t <= sp[jj, 1])


# ----------------------------------------------------------------- the targets

def read_residuals(path) -> list[tuple[str, float, str]]:
    """A residual list: CSV `session,t[,reason]` (seconds), as
    `prototypes/riot_ground_truth.py --residuals-out` writes it."""
    lines = [ln for ln in Path(path).read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    rows = list(csv.reader(lines))
    if not rows or [c.strip() for c in rows[0][:2]] != ["session", "t"]:
        raise ValueError(f"{path}: header must start session,t")
    out = []
    for i, r in enumerate(rows[1:], 2):
        try:
            out.append((r[0].strip(), float(r[1]), ",".join(r[2:]).strip()))
        except (IndexError, ValueError):
            raise ValueError(f"{path} row {i}: needs session,t in seconds")
    return out


def targets_from_residuals(residuals, pad_s: float = 15.0) -> list[Window]:
    """A window of +-pad_s around each residual, overlapping ones joined.
    Residuals from several lists (both codes' residuals) pass as one."""
    return _join_windows([Window(s, t - pad_s, t + pad_s, why or "residual")
                          for s, t, why in residuals])


def new_targets(existing: Iterable[Window], residuals, pad_s: float = 15.0) -> list[Window]:
    """Windows around the residuals whose own +-pad_s window no existing
    window holds whole: a residual outside every window, or so near an edge
    that the reader's context was cut. Empty when the windows already cover
    every residual; the targeted loop stops there."""
    by: dict[str, list[tuple[float, float]]] = {}
    for w in existing:
        by.setdefault(w.session, []).append((w.t0, w.t1))
    spans = {sid: merge(v) for sid, v in by.items()}
    fresh = [(s, t, why) for s, t, why in residuals
             if not any(a <= max(0.0, t - pad_s) and t + pad_s <= b for a, b in spans.get(s, []))]
    return targets_from_residuals(fresh, pad_s)


def join_windows(windows: Iterable[Window]) -> list[Window]:
    """Windows of one or many sources as one set: overlapping ones in a
    session joined, their reasons kept."""
    return _join_windows(list(windows))


def _match(row: dict, where: dict) -> bool:
    for k, v in where.items():
        x = row
        for part in k.split("."):
            x = x.get(part) if isinstance(x, dict) else None
        if v is True and not x:
            return False
        if v is not True and x != v:
            return False
    return True


def parse_where(items: Iterable[str]) -> dict:
    """`field=value` (value as JSON, else a string; dotted fields reach into
    nested dicts) or a bare `field`, which asks for a truthy value."""
    out = {}
    for it in items or ():
        k, eq, v = it.partition("=")
        if not eq:
            out[k] = True
            continue
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def targets_from_stream(store, sessions: Iterable[str], stream: str, where: dict,
                        pad_s: float = 15.0) -> list[Window]:
    """Windows around the stored `stream` rows that satisfy `where`: the
    places a changed code path fires, read from what the code wrote last."""
    out = []
    label = f"{stream} " + " ".join(f"{k}={v}" for k, v in where.items())
    for sid in sessions:
        for r in store.read_events(stream, sid):
            if "t_ms" in r and _match(r, where):
                t = float(r["t_ms"]) / 1000.0
                out.append(Window(sid, t - pad_s, t + pad_s, label.strip()))
    return _join_windows(out)


def _join_windows(windows: list[Window]) -> list[Window]:
    out: list[Window] = []
    for w in sorted(windows, key=lambda w: (w.session, w.t0)):
        if out and out[-1].session == w.session and w.t0 <= out[-1].t1:
            p = out[-1]
            why = p.reason if w.reason in p.reason.split("; ") else f"{p.reason}; {w.reason}"
            out[-1] = Window(p.session, p.t0, max(p.t1, w.t1), why)
        else:
            out.append(w)
    return [Window(w.session, max(0.0, w.t0), w.t1, w.reason) for w in out]
