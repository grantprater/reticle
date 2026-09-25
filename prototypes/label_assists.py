r"""Name the assisters in killfeed entries: who, and which ability icon.

    .\.venv\Scripts\python.exe prototypes\label_assists.py prep [--n 140]
    .\.venv\Scripts\python.exe prototypes\label_assists.py label
    .\.venv\Scripts\python.exe prototypes\label_assists.py summary

The assist panel sits left of the killer's portrait, in the band's top half
[domain:killfeed/assist-panel]; the killstreak numeral takes the bottom half
[domain:killfeed/killstreak-indicator]. No reader measures the panel yet, so
nothing can be scored until the player says what is in it.

`prep` draws entries (stored death verdicts) from the 20 sessions with a
`hud` ROI crop cache and frames one mid-life view of each: the entry from the
ROI's left edge to the weapon icon, the region left of the killer's portrait
ringed (anchored by `killfeed.killer_name_start`). Two strata, both seeded and
recorded on every item so rates can be reweighted: entries where
`assist_panel.edge_columns` flags any column left of the killer (`flagged`,
likely panels) and entries where it flags none (`unflagged`, the misses).
It decodes nothing.

`label` asks, per entry, how many assisters are drawn (0, 1, 2), then for
each, left to right: which agent (the match's ten from the lineup, or "Other
agent"), and which ability its icon shows (that agent's kit, "No icon", or
"Other icon"). It never shows a machine answer. U unsure, A back, Q or ESC
save and quit; labels go to `<store>/labels/killfeed_assist/<session>.jsonl`
keyed by death id, last row wins, resumable. An icon-less assister is most
likely a damage assist [domain:killfeed/assist-without-icon], so "No icon" is
an answer, not a refusal; the player's own portrait is framed in yellow
[domain:killfeed/self-yellow-frame].
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from assist_panel import LEFT, edge_columns  # noqa: E402
from reticle import killfeed as kf  # noqa: E402
from reticle.lineup import abilities_for, load_lineup  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

KIND = "killfeed_assist"
PREP = Store().root / "analysis" / "killfeed_assist_labels.npz"
SEED = 20260925
BAND = (44, 520)          # rows, columns of the stored entry view
MARGIN = 5                # rows above and below the band


def _entries(store, sid: str) -> list[dict]:
    """One candidate per death verdict: the killer view a third into its life."""
    out = []
    for r in store.read_events("death", sid):
        if r.get("kind") != "death_verdict":
            continue
        ki = (r.get("metadata") or {}).get("killer_identity") or {}
        obs = [o for c in ki.get("claims", []) if c["channel"] == "killfeed_portrait"
               for o in (c.get("evidence") or {}).get("observations", [])]
        if not obs:
            continue
        o = sorted(obs, key=lambda o: o["t_ms"])[len(obs) // 3]
        out.append({"session_id": sid, "death_id": r["death_id"], "t_ms": float(o["t_ms"]),
                    "slot": int(o["observation_key"].split(":")[2]),
                    "capture": (store.read_manifest(sid)["source"].get("path") or "")})
    return out


def prep(n: int, out: Path = PREP) -> None:
    store = Store()
    sids = sorted(p.stem for p in (store.root / "roi_cache" / "hud").glob("*/*.json"))
    strata = {"flagged": [], "unflagged": []}
    views = []
    for sid in sids:
        man = store.read_manifest(sid)
        prof = get_profile(man["source_profile"])
        cache, why = RoiCache.load(store.root, man, prof, "killfeed")
        if cache is None:
            print(f"{sid}: no crop cache ({why})")
            continue
        roi = kf.killfeed_roi(prof)
        W, H = int(man["source"]["width"]), int(man["source"]["height"])
        x0, y0, x1, y1 = cache.rect_of("killfeed")
        agents = sorted({a for side in (load_lineup(sid, store.root) or {}).get("sides", {}).values()
                         for a in (r.get("agent") for r in side) if a})
        items = {(e["t_ms"], e["slot"]): e for e in _entries(store, sid)}
        for smp in cache.samples(sorted({t for t, _ in items}), rois="killfeed"):
            crop = smp.frame[y0:y1, x0:x1]
            _g, _r, white = kf._plate_masks(crop, np.ones(crop.shape[:2], bool))
            for v in kf.analyse_killfeed(smp.frame, roi, W, H, profile_name=prof.name):
                it = items.get((smp.t_ms, v.slot))
                if it is None or not (v.killer_run and v.victim_run) or v.y1 - v.y0 < 8:
                    continue
                name0 = kf.killer_name_start(white[v.y0:v.y1], v.killer_run)
                left = name0 - int(round(kf.PORTRAIT_ASPECT * (v.y1 - v.y0)))
                if left < 0 or v.y0 < MARGIN:
                    continue
                a = max(0, left - LEFT)
                flagged = bool(edge_columns(crop, v.y0, v.y1, a, left).any())
                view = np.full((*BAND, 3), 25, np.uint8)
                piece = crop[v.y0 - MARGIN:v.y1 + MARGIN, :min(BAND[1], v.wx0 + 4)]
                view[:piece.shape[0], :piece.shape[1]] = piece[:BAND[0]]
                meta = {**it, "y0": v.y0, "y1": v.y1, "left": int(left), "name0": int(name0),
                        "wx0": int(v.wx0), "lineup": agents,
                        "stratum": "flagged" if flagged else "unflagged"}
                strata[meta["stratum"]].append(len(views))
                views.append((view, meta))
    rng = random.Random(SEED)
    k_flag = min(len(strata["flagged"]), (2 * n) // 3)
    pick = (rng.sample(strata["flagged"], k_flag)
            + rng.sample(strata["unflagged"], min(len(strata["unflagged"]), n - k_flag)))
    rng.shuffle(pick)
    for s, idx in strata.items():
        print(f"{s}: {len(idx)} entries, {sum(i in set(idx) for i in pick)} sampled")
    meta = [{**views[i][1], "stratum_size": len(strata[views[i][1]["stratum"]])} for i in pick]
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, views=np.array([views[i][0] for i in pick]).reshape(-1, *BAND, 3),
                        meta=json.dumps(meta))
    print(f"{len(meta)} items -> {out}")


def _labels() -> dict[str, dict]:
    last = {}
    for p in (Store().root / "labels" / KIND).glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
    return last


def _all_agents() -> list[str]:
    root = Store().root / "reference" / "assets" / "agents"
    return sorted({p.name.split("_killfeed")[0] for p in root.glob("*_killfeed_portrait.png")})


def _art(agent: str) -> np.ndarray | None:
    p = Store().root / "reference" / "assets" / "agents" / f"{agent}_killfeed_portrait.png"
    img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.shape[2] == 4:
        a = img[:, :, 3:4] / 255.0
        img = (img[:, :, :3] * a + 40 * (1 - a)).astype(np.uint8)
    return cv2.resize(img, (72, int(72 * img.shape[0] / img.shape[1])), interpolation=cv2.INTER_AREA)


def label(prep_path: Path = PREP) -> int:
    import tkinter as tk

    z = np.load(prep_path)
    views, meta = z["views"], json.loads(str(z["meta"]))
    root_dir = Store().root / "labels" / KIND
    root_dir.mkdir(parents=True, exist_ok=True)
    done = set(_labels())
    order = [i for i, m in enumerate(meta) if m["death_id"] not in done]
    print(f"{len(done)} already done, {len(order)} to go", flush=True)
    if not order:
        return 0
    store_root = Store().root
    handles: dict[str, object] = {}
    # `answer` is built up over the steps of one entry: count, then per
    # assister an agent and an icon.
    st = {"k": 0, "img": None, "art": [], "written": 0, "answer": None}
    root = tk.Tk()
    root.title("reticle - who assisted this kill?")
    canvas = tk.Canvas(root, highlightthickness=0, bg="#191919")
    canvas.pack()
    status = tk.Label(root, anchor="w", font=("Consolas", 11), justify="left")
    status.pack(fill="x")
    pad = tk.Frame(root)
    pad.pack(fill="x", padx=6, pady=4)

    def cur():
        return meta[order[st["k"]]]

    def write(answer: dict | None):
        m = cur()
        sid = m["session_id"]
        if sid not in handles:
            handles[sid] = (root_dir / f"{sid}.jsonl").open("a", encoding="utf-8")
        row = {"key": m["death_id"], "session_id": sid, "t_ms": m["t_ms"], "slot": m["slot"],
               "y0": m["y0"], "y1": m["y1"], "left": m["left"], "stratum": m["stratum"],
               "answer": answer, "uncertain": answer is None, "by": "player"}
        handles[sid].write(json.dumps(row) + "\n")
        handles[sid].flush()
        st["written"] += 1
        step(+1)

    def clear():
        for w in pad.winfo_children():
            w.destroy()
        st["art"] = []

    def ask_count():
        st["answer"] = {"count": None, "assisters": []}
        clear()
        for c in (0, 1, 2):
            tk.Button(pad, text=f"{c}  ({c})", width=14, height=2,
                      command=lambda c=c: got_count(c)).grid(row=0, column=c, padx=4)
        prompt("How many assister portraits are in the ring?  0 / 1 / 2")

    def got_count(c: int):
        st["answer"]["count"] = c
        if c == 0:
            write(st["answer"])
        else:
            ask_agent(0)

    def ask_agent(j: int, agents=None):
        clear()
        agents = agents or cur()["lineup"] or _all_agents()
        for k, a in enumerate(agents):
            art = _art(a)
            if art is not None:
                _ok, buf = cv2.imencode(".png", art)
                img = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
                st["art"].append(img)
                b = tk.Button(pad, image=img, text=a, compound="top", width=80,
                              command=lambda a=a: got_agent(j, a))
            else:
                b = tk.Button(pad, text=a, width=10, command=lambda a=a: got_agent(j, a))
            b.grid(row=k // 10, column=k % 10, padx=2, pady=2)
        tk.Button(pad, text="Other agent", height=3,
                  command=lambda: ask_agent(j, _all_agents())
                  ).grid(row=len(agents) // 10 + 1, column=0, columnspan=2, pady=4)
        tk.Button(pad, text="Can't tell", height=3, command=lambda: got_agent(j, None)
                  ).grid(row=len(agents) // 10 + 1, column=2, columnspan=2, pady=4)
        n = st["answer"]["count"]
        side = "" if n == 1 else (" (LEFT one)" if j == 0 else " (RIGHT one, beside the killer)")
        prompt(f"Assister {j + 1} of {n}{side}: which agent?")

    def got_agent(j: int, agent):
        st["answer"]["assisters"].append({"agent": agent, "icon": None})
        ask_icon(j, agent)

    def ask_icon(j: int, agent):
        clear()
        kit = abilities_for(agent, store_root) if agent else {}
        opts = [(f"{key}: {name}", name) for key, name in kit.items()]
        opts += [("No icon", "none"), ("Other icon", "other")]
        for k, (text, val) in enumerate(opts):
            tk.Button(pad, text=text, width=18, height=2,
                      command=lambda v=val: got_icon(j, v)).grid(row=k // 6, column=k % 6,
                                                                 padx=3, pady=3)
        prompt(f"Assister {j + 1} ({agent or 'unknown agent'}): which icon is to its right?")

    def got_icon(j: int, icon: str):
        st["answer"]["assisters"][j]["icon"] = icon
        if j + 1 < st["answer"]["count"]:
            ask_agent(j + 1)
        else:
            write(st["answer"])

    def prompt(q: str):
        m = cur()
        t = int(m["t_ms"]) // 1000
        status.config(text=f"  {st['k'] + 1}/{len(order)}   {m['session_id']}  {t // 60}:{t % 60:02d}"
                           f"   {m['capture']}\n  {q}      U unsure  A back  Q quit")

    def show():
        i = order[st["k"]]
        m = meta[i]
        v = views[i].copy()
        bh = m["y1"] - m["y0"]
        # Ring the region left of the killer's portrait: where the panel and
        # the numeral are drawn. The killer's portrait is marked, not ringed.
        cv2.rectangle(v, (max(0, m["left"] - LEFT), 1), (m["left"] - 1, MARGIN + bh), (64, 255, 64), 1)
        cv2.line(v, (m["left"], 0), (m["left"], 3), (0, 255, 255), 1)
        big = cv2.resize(v, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
        a = max(0, m["left"] - LEFT - 4)
        zoom = cv2.resize(views[i][:, a:m["left"] + 8], None, fx=5, fy=5,
                          interpolation=cv2.INTER_NEAREST)
        wide = max(big.shape[1], zoom.shape[1])
        padw = lambda im: np.hstack([im, np.full((im.shape[0], wide - im.shape[1], 3), 25, np.uint8)])
        view = np.vstack([padw(big), np.full((8, wide, 3), 25, np.uint8), padw(zoom)])
        _ok, buf = cv2.imencode(".png", view)
        st["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=view.shape[1], height=view.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=st["img"])
        ask_count()

    def step(delta):
        st["k"] += delta
        if not (0 <= st["k"] < len(order)):
            finish()
            return
        show()

    def finish():
        for fh in handles.values():
            fh.close()
        print(f"wrote {st['written']} labels under {root_dir}", flush=True)
        root.destroy()

    for c in (0, 1, 2):
        root.bind(str(c), lambda e, c=c: got_count(c) if st["answer"]["count"] is None else None)
    root.bind("u", lambda e: write(None))
    root.bind("a", lambda e: step(-1))
    root.bind("q", lambda e: finish())
    root.bind("<Escape>", lambda e: finish())
    root.protocol("WM_DELETE_WINDOW", finish)
    show()
    root.mainloop()
    return 0


def summary(prep_path: Path = PREP) -> dict:
    meta = {m["death_id"]: m for m in json.loads(str(np.load(prep_path)["meta"]))}
    labs = [r for r in _labels().values() if r["key"] in meta and not r["uncertain"]]
    by = defaultdict(Counter)
    icons = Counter()
    for r in labs:
        by[r["stratum"]][r["answer"]["count"]] += 1
        for a in r["answer"]["assisters"]:
            icons[f"{a['agent']}:{a['icon']}"] += 1
    return {"labelled": len(labs), "count_by_stratum": {s: dict(c) for s, c in by.items()},
            "icons": dict(icons.most_common())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "label", "summary"])
    ap.add_argument("--n", type=int, default=140)
    args = ap.parse_args()
    if args.cmd == "prep":
        prep(args.n)
    elif args.cmd == "label":
        return label()
    else:
        print(json.dumps(summary(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
