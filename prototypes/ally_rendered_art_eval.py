r"""Score ally-icon identity with rendered-art references against the composition.

    .\.venv\Scripts\python.exe prototypes\ally_rendered_art_eval.py [SID ...]

Both sources read the same stored `ally_icon` events (0.4.0 carries both the
composition and `portrait_features`): `composition` calls
`identity.claims_from_ally_icons` without references, `rendered` with the
baked table (`reticle ally-portrait-refs`).

(a) Labels: the player's answers (`<store>/labels/death_icon/*.jsonl`, last
row per key, class `agent`) matched by `observation_key`; per icon whether
the claim names the answer, names another agent, or refuses, and whether its
best guess is the answer.

(b) Segments: round entities rebuilt in memory WITHOUT deaths
(`round_entities.session_lifetimes`, as `minimap_fidelity.build_entities`),
so no death names a segment. A killfeed ally death with a named victim binds
the one segment that ends within [-500, +700] ms of it, and counts only when
that segment ends at least 200 ms before the death.

(c) The share of frames whose entities name one agent twice.
(d) Everything per widget width.

No decode. Predictions and outcome: `ally-icon-rendered-art` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.adjudication.identity import (claims_from_ally_icons,  # noqa: E402
                                           load_ally_portrait_references,
                                           load_identity_gallery)
from reticle.cli import _date_of  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.minimap import minimap_roi_px, widget_scale  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.round_entities import session_lifetimes  # noqa: E402
from reticle.rounds import build_rounds  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Store()
WINDOW_MS = (500.0, 700.0)
LEAD_MS = 200.0


def labels() -> dict:
    out = {}
    for p in sorted((STORE.root / "labels" / "death_icon").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return {r["observation_key"]: r for r in out.values()
            if r.get("class") == "agent" and r.get("answer")}


def widget_width(man) -> int:
    box = minimap_roi_px(get_profile(man["source_profile"]), int(man["source"]["width"]),
                         int(man["source"]["height"]))
    return box[2] - box[0]


def entities(sid, man, events, lineup, gallery, refs):
    date = _date_of(man)
    rounds = build_rounds(STORE.read_hud(sid, date))
    roster = None
    if STORE.has_roster(sid, date):
        t = STORE.read_roster(sid, date)
        roster = {"t_ms": t.column("t_ms").to_pylist(),
                  "alive_ally": t.column("alive_ally").to_pylist()}
    return session_lifetimes(sid, events, rounds, widget_scale(widget_width(man)), roster,
                             None, deaths=None, lineup=lineup, gallery=gallery,
                             references=refs)


def segments(sid, rows) -> Counter:
    ents = {e["id"]: e for e in rows if e.get("kind") == "entity" and e.get("family") == "ally"}
    obs, frames = defaultdict(list), defaultdict(list)
    for o in rows:
        if o.get("kind") == "observation" and o.get("entity_id") in ents:
            obs[o["entity_id"]].append(o["t_ms"])
            frames[o["t_ms"]].append(ents[o["entity_id"]].get("agent"))
    c = Counter()
    lo, hi = WINDOW_MS
    for v in STORE.read_events("death", sid):
        if v.get("kind") != "death_verdict" or v.get("side") != "ally" or not v.get("victim"):
            continue
        t = float(v["t_ms"])
        ends = [e for e in obs if t - lo <= max(obs[e]) <= t + hi]
        if len(ends) != 1 or max(obs[ends[0]]) > t - LEAD_MS:
            continue
        got = ents[ends[0]].get("agent")
        c["seg_bound"] += 1
        c["seg_right" if got == v["victim"] else "seg_none" if got is None else "seg_wrong"] += 1
    c["frames"] += len(frames)
    c["dup_frames"] += sum(1 for n in frames.values()
                           if any(k > 1 for k in Counter(x for x in n if x).values()))
    return c


def per_icon(sid, claims, labs) -> Counter:
    c = Counter()
    for cl in claims:
        key = cl["entity_id"].rsplit(":ally_icon:", 1)[-1]
        r = labs.get(key)
        if r is None:
            continue
        ev = cl.get("evidence") or {}
        c["lab_n"] += 1
        c["lab_named_right" if cl.get("agent") == r["answer"] else
          "lab_refused" if cl.get("agent") is None else "lab_named_wrong"] += 1
        c["lab_best_right"] += ev.get("best_guess") == r["answer"]
        c[f"lab_source_{ev.get('reference_source')}"] += 1
    return c


def main(sids) -> dict:
    labs = labels()
    gallery = load_identity_gallery(STORE.root)
    refs = load_ally_portrait_references(STORE.root)
    total = defaultdict(Counter)
    for sid in sids:
        events = STORE.read_events("ally_icon", sid)
        lineup = load_lineup(sid, STORE.root)
        if not events or not lineup:
            print(sid, "skipped: no events or no lineup", flush=True)
            continue
        man = STORE.read_manifest(sid)
        w = widget_width(man)
        icons = [e for e in events if e.get("kind") == "icon"]
        for name, r in (("composition", None), ("rendered", refs)):
            claims = claims_from_ally_icons(icons, lineup, gallery=gallery, session_id=sid,
                                            references=r)
            c = per_icon(sid, claims, labs) + segments(
                sid, entities(sid, man, events, lineup, gallery, r))
            total[name] += c
            total[f"{name}@{w}"] += c
        print(sid, w, dict(total["rendered"]), flush=True)
    out = {k: dict(sorted(v.items())) for k, v in sorted(total.items())}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(sys.argv[1:] or sorted(p.stem for p in (STORE.root / "events" / "ally_icon").glob("*.jsonl")))
