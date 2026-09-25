"""Compare bounded death events with explicit reference provenance.

Stored pipeline output is accepted only as an agreement reference. Source
accuracy requires independently reviewed source rows and a review revision.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

PROPERTIES = ("victim", "killer", "death_cause", "is_second_life")


def _read(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("event file must be a JSON array")
    return data


def _validate(rows, scope, reference=False):
    seen = set()
    for row in rows:
        for key in ("session_id", "round_no", "t_ms", "side", "death_id"):
            if key not in row:
                raise ValueError(f"missing {key}")
        if row["session_id"] != scope["session_id"] or row["round_no"] not in scope["rounds"]:
            raise ValueError("event outside declared scope")
        if row["death_id"] in seen:
            raise ValueError("duplicate death_id")
        seen.add(row["death_id"])
        for prop in PROPERTIES:
            if prop not in row:
                raise ValueError(f"missing {prop}; use null and a reason")
            if row[prop] is None and not row.get("reasons", {}).get(prop):
                raise ValueError(f"null {prop} lacks reason")
            if reference and prop not in row.get("observability", {}):
                raise ValueError(f"reference lacks {prop} observability")
            if reference and row["observability"].get(prop) == "observable" and row[prop] is None:
                raise ValueError(f"observable reference {prop} has no reviewed value")
        if reference and not row.get("source_keys"):
            raise ValueError("reference lacks source keys")


def _max_match(refs, cands, tolerance, excluded=None):
    """Maximum cardinality first; time breaks ties without sacrificing coverage."""
    edges = []
    for i, ref in enumerate(refs):
        for j, cand in enumerate(cands):
            dt = abs(ref["t_ms"] - cand["t_ms"])
            if (i, j) != excluded and (ref["session_id"], ref["round_no"], ref["side"]) == (cand["session_id"], cand["round_no"], cand["side"]) and dt <= tolerance:
                edges.append((dt, i, j))
    # Dynamic programming is exact for the bounded review slice. Reject a
    # larger partition instead of silently falling back to greedy matching.
    if len(cands) > 18:
        raise ValueError("partition exceeds exact matcher bound of 18 candidates")
    by_ref = defaultdict(list)
    for dt, i, j in edges:
        by_ref[i].append((j, dt))
    states = {0: (0, 0.0, ())}
    for i in range(len(refs)):
        next_states = {}
        for mask, (count, cost, pairs) in states.items():
            options = [(mask, count, cost, pairs)]
            options += [(mask | (1 << j), count + 1, cost + dt, pairs + ((i, j),))
                        for j, dt in by_ref[i] if not mask & (1 << j)]
            for new_mask, n, c, p in options:
                old = next_states.get(new_mask)
                if old is None or (-n, c, p) < (-old[0], old[1], old[2]):
                    next_states[new_mask] = (n, c, p)
        states = next_states
    best = min(states.values(), key=lambda s: (-s[0], s[1], s[2]))
    return best[2]


def compare(reference, candidate, spec):
    scope = spec["scope"]
    provenance = spec["truth_provenance"]
    kind = provenance["kind"]
    if kind not in ("source_review", "stored_agreement"):
        raise ValueError("truth_provenance.kind must be source_review or stored_agreement")
    if kind == "source_review":
        for field in ("review_revision", "reviewer", "source_fingerprint", "selection"):
            if not provenance.get(field):
                raise ValueError(f"source review {field} required")
        if provenance.get("derived_verdicts_shown") is not False:
            raise ValueError("source review must record blinded derived verdicts")
    if kind == "stored_agreement" and not provenance.get("reference_revision"):
        raise ValueError("stored reference revision required")
    if not scope.get("contiguous") or not scope.get("rounds"):
        raise ValueError("explicit contiguous scope required")
    if scope["rounds"] != list(range(min(scope["rounds"]), max(scope["rounds"]) + 1)):
        raise ValueError("scope rounds are not contiguous")
    tolerance = spec["matching_criteria"]["dt_max_ms"]
    _validate(reference, scope, True)
    _validate(candidate, scope)
    grouped_ref, grouped_cand = defaultdict(list), defaultdict(list)
    for row in reference:
        grouped_ref[(row["session_id"], row["round_no"], row["side"])].append(row)
    for row in candidate:
        grouped_cand[(row["session_id"], row["round_no"], row["side"])].append(row)
    pairs, misses, extras, ambiguous = [], [], [], []
    for key in sorted(grouped_ref.keys() | grouped_cand.keys()):
        refs, cands = grouped_ref[key], grouped_cand[key]
        matched = _max_match(refs, cands, tolerance)
        total_dt = sum(abs(refs[i]["t_ms"] - cands[j]["t_ms"]) for i, j in matched)
        for i, j in matched:
            alternative = _max_match(refs, cands, tolerance, (i, j))
            if len(alternative) == len(matched) and sum(
                    abs(refs[x]["t_ms"] - cands[y]["t_ms"]) for x, y in alternative) == total_dt:
                ambiguous.append({"reference": refs[i]["death_id"],
                                  "candidate": cands[j]["death_id"]})
        used_r, used_c = {i for i, _ in matched}, {j for _, j in matched}
        pairs += [(refs[i], cands[j]) for i, j in matched]
        misses += [r["death_id"] for i, r in enumerate(refs) if i not in used_r]
        extras += [c["death_id"] for j, c in enumerate(cands) if j not in used_c]
    properties = {}
    for prop in PROPERTIES:
        counts = dict(observable=0, correct=0, wrong=0, unresolved=0,
                      unobservable=0, unscored_reference=0, unsupported_assertion=0)
        for ref, cand in pairs:
            if ref["observability"][prop] != "observable":
                if ref["observability"][prop] == "source_unobservable":
                    counts["unobservable"] += 1
                else:
                    counts["unscored_reference"] += 1
                counts["unsupported_assertion"] += cand[prop] is not None
            else:
                counts["observable"] += 1
                if cand[prop] is None:
                    counts["unresolved"] += 1
                elif cand[prop] == ref[prop]:
                    counts["correct"] += 1
                else:
                    counts["wrong"] += 1
        properties[prop] = counts
    return {"comparison_kind": "source_accuracy" if kind == "source_review" else "stored_agreement",
            "truth_provenance": provenance, "scope": scope,
            "reference_count": len(reference), "candidate_count": len(candidate),
            "matched": len(pairs), "missed": misses, "extra": extras,
            "matching_ambiguities": ambiguous,
            "count_cancellation": len(reference) == len(candidate) and bool(misses or extras),
            "properties": properties,
            "matches": [{"reference": r["death_id"], "candidate": c["death_id"],
                         "dt_ms": abs(r["t_ms"] - c["t_ms"])} for r, c in pairs]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = compare(_read(args.reference), _read(args.candidate),
                     json.loads(args.spec.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("comparison_kind", "matched", "missed", "extra")}, indent=2))


if __name__ == "__main__":
    main()
