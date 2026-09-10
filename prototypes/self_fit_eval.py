r"""Score the self-fit labels: how often is an ACCEPTED fit the player.

    .\.venv\Scripts\python.exe prototypes\self_fit_eval.py c40d950031bb

The population is the reader's own accepted fits, sampled in two strata --
`crowded`, another read icon within 25 px, and `clear` -- at 100 each. The
strata are NOT equally common, so the sample rate is not the session rate:
every number here is reweighted by the stratum sizes recomputed from L1.

**Class provenance is unknown per row on the first pass.** The stamp meant to
record which class list a row was answered under never reached the writer, so
`spike` there may be a dropped spike or the carried badge, and site paint had
no class for most of the run. Later passes carry `class_set` and can say.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle import geometry  # noqa: E402
from reticle.decode import sample_windows  # noqa: E402
from reticle.minimap import (floor_mask, minimap_roi_px, self_icons,  # noqa: E402
                             slab_mask)
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

CROWD_PX = 25.0
#: `coincident` is not a failure and not a success: the ring holds two things
#: that cannot be separated, so there is no single right answer to score.
PLAYER = {"local_player"}
WRONG = {"teammate", "enemy", "spike", "spike_carried", "ability", "mark",
         "site_paint", "other", "nothing"}
AMBIGUOUS = {"coincident"}
EXCLUDED = {"unsure"}


def strata_sizes(rows: list[dict]) -> dict[str, int]:
    """How common each stratum is among ALL accepted fits, not in the sample."""
    counts = Counter()
    for r in rows:
        if r["self_x"] is None:
            continue
        near = any(
            r.get(f"ally{i}_x") is not None
            and np.hypot(r[f"ally{i}_x"] - r["self_x"],
                         r[f"ally{i}_y"] - r["self_y"]) <= CROWD_PX
            for i in range(4))
        counts["crowded" if near else "clear"] += 1
    return dict(counts)


def features(store: Store, root: Path, sid: str, labels: dict) -> list[dict]:
    """Recompute each labelled fit's SHAPE, cached beside the labels.

    Features are recomputed rather than stored, which is why a label row keeps
    only the answer and enough to find the pixel again. This is the one decode
    in the scoring path and it caches, so an operating point can be re-swept
    for free.
    """
    cache = root / "notes" / f"self-fit-features-{sid}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifests" / f"{sid}.json")
                          .read_text(encoding="utf-8"))
    src = manifest["source"]
    x0, y0, x1, y1 = minimap_roi_px(get_profile(manifest["source_profile"]),
                                    int(src["width"]), int(src["height"]))
    med = geometry.reference_static(sid, root)
    sd = geometry.stability(sid, root, med.shape[:2])
    floor, slab = floor_mask(med, sd=sd), slab_mask(med, sd=sd)
    want = {round(r["t_ms"], 1): r for r in labels.values()}
    times = sorted(want)
    out, done = [], set()
    for _w, smp in sample_windows(src["path"], float(src["fps"]),
                                  {"c": (float(src["fps"]),
                                         [(t - 40, t + 40) for t in times])}):
        key = min(times, key=lambda t: abs(t - smp.t_ms))
        if abs(key - smp.t_ms) > 40 or key in done:
            continue
        r = want[key]
        fits = self_icons(smp.frame[y0:y1, x0:x1], floor,
                          require_facing=False, support=slab)
        if not fits:
            continue
        f = min(fits, key=lambda d: np.hypot(d["cx"] - r["x"],
                                             d["cy"] - r["y"]))
        if np.hypot(f["cx"] - r["x"], f["cy"] - r["y"]) > 3.0:
            continue
        out.append({"answer": r["answer"], "stratum": r["stratum"],
                    "cov": f["cov"], "lobe": f["lobe"], "inner": f["inner"],
                    "r": f["r"], "n_fits": len(fits),
                    "has_facing": f["facing"] is not None})
        done.add(key)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def operating_points(feats: list[dict], sizes: dict[str, int]) -> None:
    """What raising the arc-coverage gate would buy, and what it would cost.

    Scored against LABELS, not against the channel's own output, so this is an
    operating point rather than the threshold tuning the standing rule refuses.
    Both columns are reweighted by stratum: the sample is half crowded and the
    session is not.
    """
    total = sum(sizes.values())
    print(f"\n{'cov >=':>7s}  {'players kept':>13s}  {'wrong kept':>11s}  "
          f"{'wrong share of kept':>20s}")
    for gate in (0.25, 0.28, 0.30, 0.32, 0.35, 0.40):
        kept_p = kept_w = all_p = all_w = 0.0
        for stratum in ("crowded", "clear"):
            share = sizes.get(stratum, 0) / total
            sub = [f for f in feats if f["stratum"] == stratum]
            if not sub:
                continue
            pl = [f for f in sub if f["answer"] in PLAYER]
            wr = [f for f in sub if f["answer"] in WRONG]
            n = len(sub)
            all_p += share * len(pl) / n
            all_w += share * len(wr) / n
            kept_p += share * sum(f["cov"] >= gate for f in pl) / n
            kept_w += share * sum(f["cov"] >= gate for f in wr) / n
        kept = kept_p + kept_w
        print(f"{gate:7.2f}  {kept_p / all_p * 100:12.1f}%  "
              f"{kept_w / all_w * 100:10.1f}%  "
              f"{(kept_w / kept * 100) if kept else 0:19.2f}%")
    print("  players kept and wrong kept are shares of their own class; the last "
          "column is\n  the wrong-object rate among everything the gate would "
          "still accept.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--features", action="store_true",
                    help="recompute fit shape and sweep the coverage gate "
                         "(decodes once, then caches)")
    args = ap.parse_args(argv)

    store = Store(args.store)
    path = next(p for p in Path(args.store).glob("l1/minimap/**/*.parquet")
                if args.session in str(p))
    rows = pq.read_table(path).to_pylist()
    sizes = strata_sizes(rows)
    total = sum(sizes.values())

    lp = Path(args.store) / "labels" / "self_fit" / f"{args.session}.jsonl"
    labels = {}
    for line in lp.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            labels[r["key"]] = r          # last row for a key wins
    print(f"{len(labels)} labelled candidates; "
          f"{total} accepted fits in the session")
    sets = Counter(r.get("class_set", "unstamped") for r in labels.values())
    print(f"class sets: {dict(sets)}")

    weighted = {"player": 0.0, "wrong": 0.0, "ambiguous": 0.0}
    print(f"\n{'stratum':9s} {'n':>4s} {'share':>7s}  "
          f"{'player':>8s} {'wrong':>8s} {'ambig':>8s}")
    for stratum in ("crowded", "clear"):
        sub = [r for r in labels.values()
               if r["stratum"] == stratum and r["answer"] not in EXCLUDED]
        if not sub:
            continue
        share = sizes.get(stratum, 0) / total
        c = Counter(r["answer"] for r in sub)
        p = sum(v for k, v in c.items() if k in PLAYER) / len(sub)
        w = sum(v for k, v in c.items() if k in WRONG) / len(sub)
        a = sum(v for k, v in c.items() if k in AMBIGUOUS) / len(sub)
        weighted["player"] += share * p
        weighted["wrong"] += share * w
        weighted["ambiguous"] += share * a
        print(f"{stratum:9s} {len(sub):4d} {share*100:6.1f}%  "
              f"{p*100:7.1f}% {w*100:7.1f}% {a*100:7.1f}%")

    print(f"\nreweighted over all accepted fits:")
    print(f"  the player            {weighted['player']*100:6.2f}%")
    print(f"  a DIFFERENT object    {weighted['wrong']*100:6.2f}%")
    print(f"  cannot be separated   {weighted['ambiguous']*100:6.2f}%")
    n = sum(1 for r in labels.values() if r["answer"] not in EXCLUDED)
    lo = weighted["wrong"] * (1 - 1.96 * np.sqrt(
        max(weighted["wrong"], 1e-9) * (1 - weighted["wrong"]) / n) /
        max(weighted["wrong"], 1e-9))
    hi = weighted["wrong"] + 1.96 * np.sqrt(
        weighted["wrong"] * (1 - weighted["wrong"]) / n)
    print(f"  wrong-object 95% interval roughly {max(0.0, lo)*100:.2f}"
          f"-{hi*100:.2f}% on n={n}")

    print("\nwhat the wrong ones were:")
    c = Counter(r["answer"] for r in labels.values() if r["answer"] in WRONG)
    for k, v in c.most_common():
        print(f"  {k:14s} {v:4d}")
    amb = [r for r in labels.values() if r["answer"] in AMBIGUOUS]
    if amb:
        print(f"\ncoincident, by stratum: "
              f"{dict(Counter(r['stratum'] for r in amb))}")

    if args.features:
        feats = features(store, Path(args.store), args.session, labels)
        print(f"\nrecomputed shape for {len(feats)} labelled fits")
        print(f"{'label':14s} {'n':>4s}  {'cov median [p10-p90]':>24s}  "
              f"{'lobe':>6s}  {'facing':>7s}")
        by = Counter(f["answer"] for f in feats)
        for k, _ in by.most_common():
            v = [f for f in feats if f["answer"] == k]
            cov = np.array([f["cov"] for f in v])
            print(f"{k:14s} {len(v):4d}  {np.median(cov):.2f} "
                  f"[{np.percentile(cov, 10):.2f}-{np.percentile(cov, 90):.2f}]"
                  f"{'':>10s}  {np.median([f['lobe'] for f in v]):.2f}  "
                  f"{np.mean([f['has_facing'] for f in v]) * 100:6.1f}%")
        operating_points(feats, sizes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
