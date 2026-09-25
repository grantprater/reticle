"""Run lane B's single stored-data portrait exemplar experiment.

Selection and reporting live here. The death owner binds observations and
harvests exemplars; adjudication.identity decides every agent name.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle.adjudication.death import portrait_exemplars
from reticle.adjudication.identity import load_identity_gallery
from reticle.cli import _date_of
from reticle import metrics
from reticle.lineup import load_lineup
from reticle.store import Store
from tools.identity_loop import rounds_of, run_pass, summarize


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(store, sid, round_ids):
    manifest = store.read_manifest(sid)
    date = _date_of(manifest)
    hud, roster = store.read_hud(sid, date), store.read_roster(sid, date)
    rounds = [r for r in rounds_of(store, sid, date, hud.to_pydict())
              if r["round"] in round_ids]
    if {r["round"] for r in rounds} != set(round_ids):
        raise ValueError(f"{sid}: required rounds missing")
    lineup = load_lineup(sid, store.root)
    portraits = store.read_events("killfeed_portrait", sid)
    board = store.read_events("scoreboard", sid)
    files = [store.root / "manifests" / f"{sid}.json",
             store.root / "lineups" / f"{sid}.json",
             store.events_path("killfeed_portrait", sid),
             store.events_path("scoreboard", sid)]
    files += list((store.root / "l1").glob(f"**/session={sid}/*.parquet"))
    map_name = next((t.split(":", 1)[1] for t in manifest["tags"]
                     if t.startswith("map:")), None)
    if map_name:
        files.append(store.root / "geometry" /
                     f"{map_name}__{manifest['source_profile']}.npz")
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise ValueError(f"{sid}: missing input {missing}")
    return dict(sid=sid, manifest=manifest, hud=hud, roster=roster, rounds=rounds,
                lineup=lineup, portraits=portraits, board=board,
                files={str(p): sha(p) for p in files})


def evaluate(data, gallery, exemplars):
    results = run_pass(data["rounds"], data["portraits"], data["lineup"], gallery,
                       data["roster"].to_pylist(), data["hud"], data["roster"],
                       data["board"], (data["lineup"].get("player") or {}).get("agent"),
                       exemplars)
    counts, rows = summarize(results)
    return results, counts, rows


def changes(before, after):
    if len(before) != len(after):
        raise ValueError("event count changed")
    changed = []
    for old, new in zip(before, after):
        key = ("round", "t_ms", "slot", "side")
        if any(old[k] != new[k] for k in key):
            raise ValueError("event correspondence changed")
        for role in ("victim", "killer"):
            if old[role] != new[role]:
                changed.append({"round": old["round"], "t_ms": old["t_ms"],
                                "slot": old["slot"], "role": role,
                                "before": old[role], "after": new[role],
                                "depends_on": new[f"{role}_depends_on"]})
    return changed


def resolve_anchors(data, baseline, anchors):
    """Resolve actual stored portrait and owner witness; expose lineage gaps."""
    obs = {r.get("observation_key"): r for r in data["portraits"]
           if r.get("kind") == "portrait_observation"}
    verdicts = [(v, e) for r in baseline for v, e in zip(r["verdicts"], r["entries"])]
    out = []
    for anchor in anchors:
        row = obs.get(anchor["observation_key"])
        claims = []
        for verdict, entry in verdicts:
            if float(entry["t_ms"]) != anchor["entry_t_ms"]:
                continue
            field = "identity" if anchor["role"] == "victim" else "killer_identity"
            identity = verdict.metadata.get(field) or {}
            if identity.get("entity_id") != anchor["label_entity"]:
                continue
            claims += [c for c in identity.get("claims", [])
                       if c.get("channel") == anchor["label_channel"]
                       and c.get("agent") == anchor["agent"]
                       and not c.get("depends_on")]
        reasons = []
        if row is None:
            reasons.append("stored portrait observation missing")
        elif row.get("composition") != anchor["composition"]:
            reasons.append("stored portrait differs from exemplar")
        if not claims:
            reasons.append("owner's independent witness claim missing")
        if any(c.get("binding_from") for c in claims):
            reasons.append("witness binding depends on another channel")
        reasons.append("selection and association rule lineage not recorded transitively")
        out.append({"key": anchor["observation_key"], "source_t_ms": row.get("t_ms")
                    if row else None, "witness": anchor["label_channel"],
                    "entity": anchor["label_entity"], "stored": row is not None,
                    "claim_count": len(claims), "independence": "unknown",
                    "reasons": reasons})
    return out


def run(source, output):
    if output.exists():
        raise FileExistsError(output)
    started = time.perf_counter()
    store = Store(source)
    gallery_files = sorted((store.root / "reference" / "assets" / "agents").glob(
                           "*_killfeed_portrait.png"))
    gallery = load_identity_gallery(store.root)
    dev = load(store, "a06f04a0059f", [3, 4, 5])
    transfer = load(store, "3694746e4e54", [4])
    baseline, base_counts, base_rows = evaluate(dev, gallery, [])
    teacher = [r for r in baseline if r["round"] == 3]
    anchors = portrait_exemplars([v for r in teacher for v in r["verdicts"]],
                                 [e for r in teacher for e in r["entries"]])
    resolution = resolve_anchors(dev, baseline, anchors)
    _, adapted_counts, adapted_rows = evaluate(dev, gallery, anchors)
    query_old = [r for r in base_rows if r["round"] in (4, 5)]
    query_new = [r for r in adapted_rows if r["round"] in (4, 5)]
    added = changes(query_old, query_new)
    withdrawn = sorted({d for row in added for d in row["depends_on"]})
    kept = [a for a in anchors if a["label_entity"] not in withdrawn]
    _, _, withdrawal_rows = evaluate(dev, gallery, kept)
    withdrawal_changes = changes(query_old,
                                 [r for r in withdrawal_rows if r["round"] in (4, 5)])
    contributing = sorted(set(withdrawn) | {d for row in withdrawal_changes
                                           for d in row["depends_on"]})
    no_contributors = [a for a in anchors if a["label_entity"] not in contributing]
    _, _, all_withdrawn_rows = evaluate(dev, gallery, no_contributors)
    all_withdrawn_changes = changes(query_old,
                                    [r for r in all_withdrawn_rows if r["round"] in (4, 5)])
    _, transfer_base_counts, transfer_old = evaluate(transfer, gallery, [])
    _, transfer_adapt_counts, transfer_new = evaluate(transfer, gallery, anchors)
    inputs = {**dev["files"], **transfer["files"],
              **{str(p): sha(p) for p in gallery_files}}
    report = {
        "schema_version": 1, "status": "review_pending",
        "development": {"session": dev["sid"], "rounds": [3, 4, 5],
                        "teaching_round": 3, "query_rounds": [4, 5]},
        "transfer": {"session": transfer["sid"], "rounds": [4],
                     "provisional": True},
        "baseline_revision": "official gallery, no learned exemplars",
        "candidate_revision": hashlib.sha256(json.dumps(anchors, sort_keys=True).encode()).hexdigest(),
        "source_fingerprints": {d["sid"]: d["manifest"]["source"]["content_key"]
                                for d in (dev, transfer)},
        "input_files": inputs, "anchor_count": len(anchors),
        "anchors": anchors, "anchor_resolution": resolution,
        "baseline_counts": base_counts, "adapted_counts": adapted_counts,
        "query_changes": added, "withdrawn_anchor_entities": withdrawn,
        "withdrawal_remaining_changes": withdrawal_changes,
        "withdrawal_retracts_query_changes": not withdrawal_changes,
        "all_contributing_anchor_entities": contributing,
        "all_contributing_withdrawn_changes": all_withdrawn_changes,
        "transfer_baseline_counts": transfer_base_counts,
        "transfer_adapted_counts": transfer_adapt_counts,
        "transfer_changes": changes(transfer_old, transfer_new),
        "counterexample_search": {
            "unresolved": [r for r in query_new if not r["victim"] or not r["killer"]],
            "conflicts": [r for r in query_new if r["victim_status"] == "disagreement"
                          or r["killer_status"] == "disagreement"],
            "seeded_review_event": random.Random(20260924).choice(query_new),
            "no_proposal_window_ms": [233000, 234000]},
        "review_truth": None,
        "review_truth_reason": "labelling-pass capability unavailable in this session",
        "elapsed_seconds": time.perf_counter() - started,
    }
    for path, expected in inputs.items():
        if sha(path) != expected:
            raise RuntimeError(f"input changed during run: {path}")
    output.mkdir(parents=True)
    for name, body in (("report.json", report), ("dev_baseline.json", base_rows),
                       ("dev_adapted.json", adapted_rows),
                       ("candidate.json", anchors),
                       ("transfer_baseline.json", transfer_old),
                       ("transfer_adapted.json", transfer_new)):
        (output / name).write_text(json.dumps(body, indent=2, default=str) + "\n")
    metrics.record("bootstrap-b", part="pilot", session=dev["sid"],
                   values={"anchor_views": len(anchors),
                           "query_changes": len(added),
                           "single_withdrawal_remaining": len(withdrawal_changes),
                           "all_withdrawn_remaining": len(all_withdrawn_changes),
                           "transfer_changes": len(changes(transfer_old, transfer_new)),
                           "unresolved_query_events": len(report["counterexample_search"]["unresolved"]),
                           "elapsed_seconds": report["elapsed_seconds"]},
                   deps={"candidate_revision": report["candidate_revision"],
                         "input_files": inputs},
                   context={"review_truth": "unavailable", "development_rounds": [3, 4, 5]},
                   status=metrics.CANNOT_ANSWER,
                   note="Source truth and transitive selection lineage remain unresolved",
                   log_path=output.parent / "notes" / "metrics.jsonl")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    result = run(args.store, args.output)
    print(json.dumps({k: result[k] for k in ("anchor_count", "query_changes",
                       "withdrawal_remaining_changes", "transfer_changes",
                       "elapsed_seconds")}, indent=2))


if __name__ == "__main__":
    main()
