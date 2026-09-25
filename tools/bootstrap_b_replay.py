"""Replay a frozen lane B portrait candidate on a caller-selected session.

This command does not harvest from the target. The coordinator supplies the
session and keeps independent evaluation truth outside this adapter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle.adjudication.identity import load_identity_gallery
from reticle.store import Store
from tools.bootstrap_b_run import changes, evaluate, load, resolve_anchors, sha


def qualify_frozen_anchors(anchors, teaching_session="a06f04a0059f"):
    """Translate the old adapter's placeholder entity keys without editing its revision."""
    out = []
    for anchor in anchors:
        if not anchor.get("observation_key", "").startswith(teaching_session + ":"):
            raise ValueError("frozen anchor observation is outside the teaching session")
        entity = anchor.get("label_entity", "")
        if not entity.startswith("death:S:"):
            raise ValueError(f"unexpected frozen death entity: {entity}")
        out.append({**anchor, "label_entity": entity.replace("death:S:",
                    f"death:{teaching_session}:", 1)})
    return out


def comparison_rows(rows, session_id, reference=False):
    """Expose adapter output to the evaluator without inventing unread fields."""
    out = []
    for row in rows:
        death_id = f"death:{session_id}:{int(row['t_ms'])}:{row['slot']}"
        item = {"death_id": death_id, "session_id": session_id,
                "round_no": row["round"], "t_ms": row["t_ms"], "side": row["side"],
                "victim": row["victim"], "killer": row["killer"],
                "death_cause": None, "is_second_life": None,
                "reasons": {"death_cause": "adapter_not_emitted",
                            "is_second_life": "adapter_not_emitted"}}
        for role in ("victim", "killer"):
            if item[role] is None:
                item["reasons"][role] = row.get(f"{role}_reason") or "adapter_abstained"
        if reference:
            item["source_keys"] = ["stored-killfeed-entry:" + death_id]
            item["observability"] = {p: ("observable" if item[p] is not None
                                       else "model_unresolved") for p in
                                     ("victim", "killer", "death_cause", "is_second_life")}
        out.append(item)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--frozen-report", type=Path,
                    help="Defaults to report.json beside the candidate")
    ap.add_argument("--session", required=True)
    ap.add_argument("--rounds", type=int, nargs="+", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    anchors = json.loads(args.candidate.read_text())
    candidate_revision = hashlib.sha256(json.dumps(anchors, sort_keys=True).encode()).hexdigest()
    frozen = json.loads((args.frozen_report or args.candidate.with_name("report.json")).read_text())
    if candidate_revision != frozen["candidate_revision"]:
        raise ValueError("candidate differs from frozen revision")
    store = Store(args.store)
    for path, expected in frozen["input_files"].items():
        if path.endswith("_killfeed_portrait.png") and sha(path) != expected:
            raise ValueError(f"official gallery changed: {path}")
    target = load(store, args.session, args.rounds)
    gallery = load_identity_gallery(store.root)
    baseline_verdicts, before_counts, before = evaluate(target, gallery, [])
    qualified = qualify_frozen_anchors(anchors)
    teacher = (target if args.session == "a06f04a0059f" and 3 in args.rounds
               else load(store, "a06f04a0059f", [3]))
    teacher_baseline = (baseline_verdicts if teacher is target
                        else evaluate(teacher, gallery, [])[0])
    anchor_resolution = resolve_anchors(teacher, teacher_baseline, qualified)
    if not all(a["stored"] and a["claim_count"] for a in anchor_resolution):
        raise ValueError("frozen anchor lacks stored source observation or owner claim")
    _, after_counts, after = evaluate(target, gallery, qualified)
    changed = changes(before, after)
    direct = {d for row in changed for d in row["depends_on"]}
    _, _, after_one = evaluate(target, gallery,
                                [a for a in qualified if a["label_entity"] not in direct])
    remaining = changes(before, after_one)
    contributors = direct | {d for row in remaining for d in row["depends_on"]}
    _, _, after_all = evaluate(target, gallery,
                                [a for a in qualified if a["label_entity"] not in contributors])
    report = {"schema_version": 1, "session": args.session, "rounds": args.rounds,
              "candidate_revision": candidate_revision,
              "candidate_file_sha256": sha(args.candidate),
              "adapter_revision": "bootstrap-integration-0.1.0",
              "teaching_session": "a06f04a0059f",
              "dependency_key_translation": "death:S: -> death:a06f04a0059f: in memory",
              "source_fingerprint": target["manifest"]["source"]["content_key"],
              "input_files": {**teacher["files"], **target["files"]},
              "anchor_resolution": anchor_resolution,
              "lineage_status": "selection_and_association_dependencies_incomplete",
              "baseline_counts": before_counts, "adapted_counts": after_counts,
              "changes": changed,
              "direct_anchor_withdrawal_changes": remaining,
              "all_contributing_anchors": sorted(contributors),
              "all_contributing_withdrawal_changes": changes(before, after_all),
              "independent_truth": None,
              "independent_truth_reason": "this replay only compares two stored-data outputs"}
    for path, expected in {**teacher["files"], **target["files"]}.items():
        if sha(path) != expected:
            raise RuntimeError(f"input changed during replay: {path}")
    for path, expected in frozen["input_files"].items():
        if path.endswith("_killfeed_portrait.png") and sha(path) != expected:
            raise RuntimeError(f"official gallery changed during replay: {path}")
    args.output.mkdir(parents=True)
    eval_spec = {"spec_version": "bootstrap-compare-0.1.0",
                 "scope": {"session_id": args.session, "rounds": args.rounds,
                           "contiguous": args.rounds == list(range(min(args.rounds), max(args.rounds)+1))},
                 "truth_provenance": {"kind": "stored_agreement",
                                      "reference_revision": "current-owner-baseline",
                                      "input_files": target["files"]},
                 "matching_criteria": {"dt_max_ms": 2500}}
    for name, body in (("report.json", report), ("baseline.json", before),
                       ("adapted.json", after),
                       ("comparison_reference.json", comparison_rows(before, args.session, True)),
                       ("comparison_candidate.json", comparison_rows(after, args.session)),
                       ("comparison_spec.json", eval_spec)):
        (args.output / name).write_text(json.dumps(body, indent=2) + "\n")
    print(json.dumps({"candidate_revision": candidate_revision,
                      "changes": report["changes"]}, indent=2))


if __name__ == "__main__":
    main()
