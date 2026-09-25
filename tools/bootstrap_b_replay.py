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
from tools.bootstrap_b_run import changes, evaluate, load, sha


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
    _, before_counts, before = evaluate(target, gallery, [])
    _, after_counts, after = evaluate(target, gallery, anchors)
    report = {"schema_version": 1, "session": args.session, "rounds": args.rounds,
              "candidate_revision": candidate_revision,
              "candidate_file_sha256": sha(args.candidate),
              "source_fingerprint": target["manifest"]["source"]["content_key"],
              "input_files": target["files"],
              "baseline_counts": before_counts, "adapted_counts": after_counts,
              "changes": changes(before, after),
              "independent_truth": None,
              "independent_truth_reason": "this replay only compares two stored-data outputs"}
    for path, expected in target["files"].items():
        if sha(path) != expected:
            raise RuntimeError(f"input changed during replay: {path}")
    for path, expected in frozen["input_files"].items():
        if path.endswith("_killfeed_portrait.png") and sha(path) != expected:
            raise RuntimeError(f"official gallery changed during replay: {path}")
    args.output.mkdir(parents=True)
    for name, body in (("report.json", report), ("baseline.json", before),
                       ("adapted.json", after)):
        (args.output / name).write_text(json.dumps(body, indent=2) + "\n")
    print(json.dumps({"candidate_revision": candidate_revision,
                      "changes": report["changes"]}, indent=2))


if __name__ == "__main__":
    main()
