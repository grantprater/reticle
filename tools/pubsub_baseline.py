"""Usage-record analysis for the pub/sub performance baseline. Stored data only."""
import json, statistics as st, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORE = Path.home() / "reticle-store"
OUT = Path(sys.argv[1])
rows = [json.loads(l) for l in (STORE / "notes" / "usage.jsonl").open(encoding="utf-8") if l.strip()]
CUTOFF = "2026-09-27T08:58:31"
rows = [r for r in rows if r.get("version") == "scan-usage-1" and r["recorded_at"][:19] <= CUTOFF]
S = 1e9
NVDEC_COMMIT = datetime(2026, 9, 26, 9, 20, 5, tzinfo=timezone.utc)   # 8002303, inference only
BUCKETS = ["<0.1", "0.1-0.5", "0.5-1", "1-2", "2-5", "5-10", "10-50", "50-100", ">=100"]  # ms
# Profile minimap ROI fractions (reticle/profiles.py): std and bigmap.
PIX_RATIO = ((0.250 - 0.008) * (0.463 - 0.014)) / ((0.180 - 0.008) * (0.325 - 0.020))

man = {}
def manifest(sid):
    if sid not in man:
        p = STORE / "manifests" / f"{sid}.json"
        m = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        src = m.get("source", {})
        man[sid] = {"dur_s": (src.get("duration_ms") or 0) / 1000 or None,
                    "frames": src.get("frame_count"), "fps": src.get("fps"),
                    "demo": "ability-demo" in m.get("tags", [])}
    return man[sid]

def r3(x):
    return None if x is None else round(x, 3)

recs = []
for r in rows:
    m = manifest(r["session_id"])
    end = datetime.fromisoformat(r["recorded_at"])
    wall = (r["setup_ns"] + r["pass_ns"] + r["publish_ns"]) / S
    src = r["source_calls"]["total_ns"] / S
    per = {n: (v["feed"]["total_ns"] + v["finish_ns"]) / S for n, v in r["readers"].items()}
    rd = sum(per.values())
    other = r["pass_other_ns"] / S
    heavy = max(per, key=per.get)
    hv = r["readers"][heavy]
    fc = hv["feed"]["count"]
    b = hv["feed"]["buckets"]
    # Overlap bounds: source on its own worker; the consumer keeps readers + dispatch.
    pass_s = r["pass_ns"] / S
    ovl = max(src, rd + other)
    par = max(src, max(per.values()) + other)
    recs.append({
        "i": len(recs), "session": r["session_id"], "recorded_at": r["recorded_at"][:19] + "Z",
        "start": end - timedelta(seconds=wall), "end": end,
        "source": "video" if r["source"] == "video" else "cache",
        "profile": "bigmap" if r["profile"].endswith("bigmap") else "std",
        "readers": "+".join(sorted(r["readers"])), "kind": "demo" if m["demo"] else "match",
        "after_nvdec_commit": end > NVDEC_COMMIT,
        "frames": r["source_calls"]["count"], "wall_s": wall, "pass_s": pass_s,
        "source_s": src, "readers_s": rd, "other_s": other,
        "setup_s": r["setup_ns"] / S, "publish_s": r["publish_ns"] / S,
        "share_source": src / wall, "share_readers": rd / wall,
        "share_rest": (wall - src - rd) / wall,
        "source_ms_per_frame": src / max(1, r["source_calls"]["count"]) * 1e3,
        "heaviest": heavy, "heaviest_share": per[heavy] / wall,
        "heaviest_ms_per_call": hv["feed"]["total_ns"] / max(1, fc) / 1e6,
        "heaviest_max_ms": hv["feed"]["max_ns"] / 1e6,
        "heaviest_buckets": b, "heaviest_hz": hv["hz"], "heaviest_spans": hv["spans"],
        "finish_s": sum(v["finish_ns"] for v in r["readers"].values()) / S,
        "per": per,
        "vod_min": (m["dur_s"] / 60) if m["dur_s"] else None,
        "x_realtime": (m["dur_s"] / wall) if m["dur_s"] else None,
        "retrieved_fps": r["source_calls"]["count"] / wall,
        "decoded_fps_upper": (m["frames"] / pass_s) if (r["source"] == "video" and m["frames"]) else None,
        "pass_overlap_s": ovl, "gain_overlap_s": pass_s - ovl,
        "gain_overlap_frac_wall": (pass_s - ovl) / wall,
        "speedup_overlap": wall / (wall - (pass_s - ovl)),
        "pass_parallel_s": par, "gain_parallel_frac_wall": (pass_s - par) / wall,
        "speedup_parallel": wall / (wall - (pass_s - par)),
    })

# Concurrency: other usage records whose run interval overlaps this one's.
for a in recs:
    ov = [b for b in recs if b is not a and b["start"] < a["end"] and a["start"] < b["end"]]
    a["concurrent_records"] = len(ov)
    a["overlap_frac"] = (sum((min(a["end"], b["end"]) - max(a["start"], b["start"])).total_seconds()
                             for b in ov) / a["wall_s"]) if ov else 0.0

# Batches: same (readers, source, kind), split at gaps over 30 minutes.
recs_sorted = sorted(recs, key=lambda x: x["end"])
last = {}
batch_no = {}
for a in recs_sorted:
    k = (a["readers"], a["source"], a["kind"])
    prev = last.get(k)
    if prev is None or (a["start"] - prev["end"]).total_seconds() > 1800:
        batch_no[k] = batch_no.get(k, 0) + 1
    a["batch"] = f"{a['readers']}/{a['source']}/{a['kind']}/b{batch_no[k]}"
    last[k] = a

def summ(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {"n": len(vals), "median": r3(st.median(vals)), "min": r3(min(vals)), "max": r3(max(vals))}

groups = {}
for a in recs:
    groups.setdefault(a["batch"], []).append(a)
FIELDS = ["wall_s", "share_source", "share_readers", "share_rest", "source_ms_per_frame",
          "heaviest_ms_per_call", "x_realtime", "retrieved_fps", "decoded_fps_upper",
          "gain_overlap_frac_wall", "speedup_overlap", "gain_parallel_frac_wall",
          "publish_s", "concurrent_records", "overlap_frac"]
gsum = {}
for k, g in sorted(groups.items(), key=lambda kv: kv[1][0]["end"]):
    b = [sum(a["heaviest_buckets"][i] for a in g) for i in range(9)]
    tot = sum(b)
    gsum[k] = {"records": len(g), "first": g[0]["recorded_at"], "last": g[-1]["recorded_at"],
               "after_nvdec_commit": sorted({a["after_nvdec_commit"] for a in g}),
               "profiles": sorted({a["profile"] for a in g}),
               **{f: summ([a[f] for a in g]) for f in FIELDS},
               "heaviest_bucket_frac": dict(zip(BUCKETS, [r3(x / tot) for x in b]))}

# Per-pixel test: ms per call, bigmap over std, within each batch.
pix = {}
for k, g in groups.items():
    big = [a["heaviest_ms_per_call"] for a in g if a["profile"] == "bigmap" and a["kind"] == "match"]
    std = [a["heaviest_ms_per_call"] for a in g if a["profile"] == "std" and a["kind"] == "match"]
    bs = [a["source_ms_per_frame"] for a in g if a["profile"] == "bigmap" and a["kind"] == "match"]
    ss = [a["source_ms_per_frame"] for a in g if a["profile"] == "std" and a["kind"] == "match"]
    if big and std:
        pix[k] = {"big_n": len(big), "std_n": len(std),
                  "reader_ms_big": r3(st.median(big)), "reader_ms_std": r3(st.median(std)),
                  "reader_ratio": r3(st.median(big) / st.median(std)),
                  "source_ms_big": r3(st.median(bs)), "source_ms_std": r3(st.median(ss)),
                  "source_ratio": r3(st.median(bs) / st.median(ss))}

# Same session, three video passes: does source time fall when reader time rises?
same = {}
for a in recs:
    if a["source"] == "video" and a["kind"] == "match":
        same.setdefault(a["session"], {})[a["readers"]] = a
src_cmp = []
for sid, d in sorted(same.items()):
    if "roi_cache:minimap" in d and "scoreboard" in d:
        x, y = d["roi_cache:minimap"], d["scoreboard"]
        row = {"session": sid, "roi_cache_source_s": r3(x["source_s"]), "roi_cache_readers_s": r3(x["readers_s"]),
               "scoreboard_source_s": r3(y["source_s"]), "scoreboard_readers_s": r3(y["readers_s"]),
               "scoreboard_concurrent": y["concurrent_records"],
               "source_ratio_scoreboard_over_roi": r3(y["source_s"] / x["source_s"])}
        if "minimap" in d:
            z = d["minimap"]
            row.update({"minimap_source_s": r3(z["source_s"]), "minimap_readers_s": r3(z["readers_s"]),
                        "source_ratio_minimap_over_roi": r3(z["source_s"] / x["source_s"])})
        src_cmp.append(row)

# Composite fused scan per full-match session: separate records, NOT a measured scan.
# Decode = the roi_cache:minimap video record's source time (grab-through, uncontended batch);
# each reader = its least-contended record's feed+finish.
CORE = ("roi_cache:minimap", "ally_icon", "scoreboard", "killfeed_portrait", "hud")
comp = []
for sid in sorted({a["session"] for a in recs if a["kind"] == "match"}):
    mine = [a for a in recs if a["session"] == sid]
    dec = [a for a in mine if a["readers"] == "roi_cache:minimap" and a["source"] == "video"]
    if not dec:
        continue
    best = {}                      # reader -> (seconds, record): lowest recorded feed + finish
    for a in mine:
        for name, sec in a["per"].items():
            if name not in best or sec < best[name][0]:
                best[name] = (sec, a)
    d = dec[0]["source_s"]
    entry = {"session": sid, "vod_min": r3(dec[0]["vod_min"]), "decode_s": r3(d),
             "decode_from": dec[0]["recorded_at"],
             "readers": {k: {"s": r3(v[0]), "from": v[1]["recorded_at"],
                             "concurrent": v[1]["concurrent_records"]} for k, v in sorted(best.items())}}
    for label, names in (("core", CORE), ("core_plus_minimap", CORE + ("minimap",))):
        if not all(n in best for n in names):
            entry[label] = None
            continue
        rs = [best[n][0] for n in names]
        rsum, rmax = sum(rs), max(rs)
        serial = d + rsum
        entry[label] = {"readers_sum_s": r3(rsum), "serial_s": r3(serial),
                        "overlap_bound_s": r3(max(d, rsum)), "parallel_bound_s": r3(max(d, rmax)),
                        "heaviest": max(names, key=lambda n: best[n][0]),
                        "heaviest_share_of_serial": r3(rmax / serial),
                        "decode_share_of_serial": r3(d / serial),
                        "overlap_speedup": r3(serial / max(d, rsum)),
                        "parallel_speedup": r3(serial / max(d, rmax)),
                        "x_realtime_serial": r3(dec[0]["vod_min"] * 60 / serial),
                        "x_realtime_parallel_bound": r3(dec[0]["vod_min"] * 60 / max(d, rmax))}
    comp.append(entry)


# Corpus cost per batch: summed wall, and elapsed from first start to last end.
totals = {}
for k, g in groups.items():
    first = min(a["start"] for a in g)
    lastend = max(a["end"] for a in g)
    totals[k] = {"records": len(g), "sessions": len({a["session"] for a in g}),
                 "wall_sum_min": round(sum(a["wall_s"] for a in g) / 60, 1),
                 "elapsed_min": round((lastend - first).total_seconds() / 60, 1),
                 "source_sum_min": round(sum(a["source_s"] for a in g) / 60, 1),
                 "readers_sum_min": round(sum(a["readers_s"] for a in g) / 60, 1),
                 "publish_sum_min": round(sum(a["publish_s"] for a in g) / 60, 1)}

KEEP = {"s": ["wall_s", "pass_s", "source_s", "readers_s", "other_s", "setup_s", "publish_s", "finish_s"],
        "f": ["share_source", "share_readers", "share_rest", "heaviest_share", "gain_overlap_frac_wall",
              "gain_parallel_frac_wall", "speedup_overlap", "speedup_parallel", "overlap_frac"],
        "ms": ["source_ms_per_frame", "heaviest_ms_per_call", "heaviest_max_ms"],
        "x": ["x_realtime", "retrieved_fps", "decoded_fps_upper", "vod_min"]}
ORDER = ["session", "recorded_at", "batch", "profile", "frames", "concurrent_records",
         "wall_s", "source_s", "readers_s", "other_s", "setup_s", "publish_s",
         "share_source", "share_readers", "share_rest", "heaviest", "heaviest_share",
         "heaviest_ms_per_call", "gain_overlap_frac_wall", "gain_parallel_frac_wall",
         "vod_min", "x_realtime", "heaviest_buckets"]
def rnd(k, v):
    if not isinstance(v, float):
        return v
    if k in KEEP["s"] or k in KEEP["x"]:
        return round(v, 1)
    if k in KEEP["ms"]:
        return round(v, 2)
    return round(v, 3)
out_recs = [{k: rnd(k, a[k]) for k in ORDER} for a in recs]

meta = {
    "what": "Pub/sub performance baseline: derived from Reticle's VOD scan usage log "
            "(<store>/notes/usage.jsonl, version scan-usage-1). Aggregate timings only.",
    "records": len(recs), "first": recs[0]["recorded_at"], "last": recs[-1]["recorded_at"],
    "cutoff_utc": CUTOFF + "Z",
    "definitions": {
        "wall_s": "setup + pass + publish",
        "share_rest": "(pass_other + setup + publish) / wall",
        "readers_s": "sum of feed + finish over the record's readers",
        "pass_overlap_s": "max(source, readers + other): source on its own worker, consumer unchanged",
        "pass_parallel_s": "max(source, slowest reader + other): readers also run concurrently",
        "gain_*_frac_wall": "(pass - bound) / wall; an upper bound that assumes free cores",
        "speedup_*": "wall / (wall - gain)",
        "x_realtime": "VOD duration (manifest) / wall",
        "decoded_fps_upper": "manifest frame_count / pass; decode may stop at the last span end",
        "concurrent_records": "other usage records whose run interval overlaps this one's",
        "overlap_frac": "summed overlap with other recorded scans / wall (about the extra scans running)",
        "after_nvdec_commit": "recorded after commit 8002303 (NVDEC decode); an inference, the record "
                              "names no backend",
        "heaviest_buckets": "feed-call counts per bucket, upper bounds in ms: "
                            "0.1, 0.5, 1, 2, 5, 10, 50, 100, open",
        "composite": "a fused scan estimated from SEPARATE single-reader records: decode = the "
                     "roi_cache:minimap video record's source time; each reader = its lowest recorded "
                     "feed + finish. Not a measured scan; readers with no record are absent."},
    "pixel_ratio_bigmap_over_std": r3(PIX_RATIO),
}
csum = {}
for label in ("core", "core_plus_minimap"):
    cs = [c[label] for c in comp if c.get(label)]
    csum[label] = {"sessions": len(cs), **{f: summ([c[f] for c in cs]) for f in
                   ("decode_share_of_serial", "heaviest_share_of_serial", "overlap_speedup",
                    "parallel_speedup", "x_realtime_serial", "x_realtime_parallel_bound")},
                   "heaviest": {h: sum(1 for c in cs if c["heaviest"] == h)
                                for h in sorted({c["heaviest"] for c in cs})}}
meta["definitions"]["composite_core"] = ", ".join(CORE)
meta["definitions"]["composite_core_plus_minimap"] = "core plus minimap, on the sessions with a minimap record"
def line(x):
    return json.dumps(x, separators=(",", ":"))
def section(name, obj):
    if isinstance(obj, dict):
        inner = ",\n".join(f"  {json.dumps(k)}: {line(v)}" for k, v in obj.items())
        return f' {json.dumps(name)}: {{\n{inner}\n }}'
    inner = ",\n".join(f"  {line(v)}" for v in obj)
    return f' {json.dumps(name)}: [\n{inner}\n ]'
comp_lines = [{k: v for k, v in c.items()} for c in comp]
parts = [section("meta", meta), section("groups", gsum), section("batch_totals", totals),
         section("per_pixel", pix), section("same_session_source", src_cmp),
         section("composite_summary", csum), section("composite", comp_lines),
         ' "records": {\n  "columns": ' + line(ORDER) + ',\n  "rows": [\n'
         + ",\n".join("   " + line([x[k] for k in ORDER]) for x in out_recs) + "\n  ]\n }"]
OUT.write_text("{\n" + ",\n".join(parts) + "\n}\n", encoding="utf-8")
json.loads(OUT.read_text(encoding="utf-8"))   # must parse

print("records", len(recs), recs[0]["recorded_at"], recs[-1]["recorded_at"])
print("\n== batch totals"); [print(" ", k, v) for k, v in totals.items()]
print("\n== composite summary"); [print(" ", k, v) for k, v in csum.items()]
for c in comp:
    k = c.get("core") or {}
    print(" ", c["session"], "dec", c["decode_s"], c["decode_from"][11:19], "core", k.get("serial_s"),
          k.get("overlap_speedup"), k.get("parallel_speedup"), k.get("heaviest"), k.get("heaviest_share_of_serial"),
          "xrt", k.get("x_realtime_serial"), "+mm", (c.get("core_plus_minimap") or {}).get("parallel_speedup"),
          {n: (v["s"], v["from"][11:19], v["concurrent"]) for n, v in c["readers"].items()})
