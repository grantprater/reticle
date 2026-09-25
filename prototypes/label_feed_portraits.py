r"""Name the killfeed portraits the arbiter named from portraits alone.

    .\.venv\Scripts\python.exe prototypes\label_feed_portraits.py prep [--n 120]
    .\.venv\Scripts\python.exe prototypes\label_feed_portraits.py label
    .\.venv\Scripts\python.exe prototypes\label_feed_portraits.py score

The portrait channel's reliability measured against independent witnesses
(`reticle reliability`) covers the player's own kills and deaths and ability
kills, which are the easiest faces; this samples the rest. `prep` draws `--n`
resolved victim and killer names that no reference witness covers, uniformly
over the stored death streams (seeded), and frames each named portrait view
from the `hud` ROI crop cache: the whole killfeed row, the portrait ringed,
and the portrait enlarged. It decodes nothing.

`label` asks which agent is ringed. It never shows the machine's name. The
buttons are the match's ten agents from the lineup (the top bar, not the
killfeed), with "Other agent" for the full list and "Not a portrait" when the
ring is on something else. U unsure, A back, Q or ESC save and quit; labels go
to `<store>/labels/feed_portrait/<session>.jsonl`, keyed by the verdict's
entity, last row wins, resumable.

`score` compares each label with the stored verdict and prints the
portrait channel's accuracy on this population, per agent. Predictions are
`channel-reliability` in the store's `notes/predictions.jsonl`.
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
from reticle.adjudication.death import DEATH_ADJUDICATION_VERSION  # noqa: E402
from reticle.adjudication.reliability import REFERENCE_CHANNELS  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

KIND = "feed_portrait"
PREP = Store().root / "analysis" / "feed_portrait_labels.npz"
SEED = 20260925
BAND = (60, 1100)


def population() -> list[dict]:
    """Resolved names no reference witness covers, one row per entity."""
    store = Store()
    out = []
    for man in store.sessions():
        sid = man["session_id"]
        rows = store.read_events("death", sid)
        if not rows or rows[0].get("death_adjudication_version") != DEATH_ADJUDICATION_VERSION:
            continue
        for r in rows[1:]:
            for key, role in (("identity", "victim"), ("killer_identity", "killer")):
                v = r["metadata"].get(key) or {}
                by = v.get("by_channel") or {}
                if v.get("status") != "resolved" or any(
                        ch in by and by[ch].get("agent") for ch in REFERENCE_CHANNELS):
                    continue
                obs = [o for c in v.get("claims", []) if c["channel"] == "killfeed_portrait"
                       for o in (c.get("evidence") or {}).get("observations", [])
                       if o.get("agent") == v["agent"]]
                if obs:
                    out.append({"session_id": sid, "entity_id": v["entity_id"], "role": role,
                                "death_id": r["death_id"], "said": v["agent"],
                                "dependent": bool(v.get("depends_on")),
                                "observation_key": obs[len(obs) // 2]["observation_key"]})
    return out


def prep(n: int, out: Path = PREP) -> None:
    store = Store()
    pop = population()
    random.Random(SEED).shuffle(pop)
    pick = pop[:n]
    print(f"{len(pop)} portrait-only names; sampling {len(pick)}")
    by = defaultdict(list)
    for it in pick:
        by[it["session_id"]].append(it)
    bands, faces, meta = [], [], []
    for sid, its in sorted(by.items()):
        man = store.read_manifest(sid)
        cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]), "killfeed")
        if cache is None:
            print(f"{sid}: no crop cache ({why})")
            continue
        x0, y0, x1, _ = cache.rect_of("killfeed")
        views = {r["observation_key"]: r for r in store.read_events("killfeed_portrait", sid)
                 if r.get("kind") == "portrait_observation"}
        agents = sorted({r["agent"] for side in (load_lineup(sid, store.root) or {}).get(
            "sides", {}).values() for r in side if r.get("agent")})
        for it in its:
            v = views.get(it["observation_key"])
            got = list(cache.samples([float(v["t_ms"])], rois="killfeed")) if v else []
            if not got:
                continue
            f = got[0].frame
            band = f[y0 + v["y0"] - 4:y0 + v["y1"] + 4, x0:x1]
            c = np.full((*BAND, 3), 25, np.uint8)
            c[:min(BAND[0], band.shape[0]), :min(BAND[1], band.shape[1])] = band[:BAND[0], :BAND[1]]
            face = f[y0 + v["y0"]:y0 + v["y1"], x0 + v["x0"]:x0 + v["x1"]]
            fc = np.full((40, 90, 3), 25, np.uint8)
            fc[:min(40, face.shape[0]), :min(90, face.shape[1])] = face[:40, :90]
            bands.append(c)
            faces.append(fc)
            meta.append({**it, "t_ms": v["t_ms"], "ring": [v["x0"], 4, v["x1"], 4 + v["y1"] - v["y0"]],
                         "lineup": agents})
    np.savez_compressed(out, bands=np.array(bands).reshape(-1, *BAND, 3),
                        faces=np.array(faces).reshape(-1, 40, 90, 3), meta=json.dumps(meta))
    print(f"{len(meta)} items -> {out}")


def _art(agent: str) -> np.ndarray | None:
    p = Store().root / "reference" / "assets" / "agents" / f"{agent}_killfeed_portrait.png"
    img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.shape[2] == 4:
        a = img[:, :, 3:4] / 255.0
        img = (img[:, :, :3] * a + 40 * (1 - a)).astype(np.uint8)
    return cv2.resize(img, (72, int(72 * img.shape[0] / img.shape[1])), interpolation=cv2.INTER_AREA)


def _all_agents() -> list[str]:
    root = Store().root / "reference" / "assets" / "agents"
    return sorted({p.name.split("_killfeed")[0] for p in root.glob("*_killfeed_portrait.png")})


def _labels() -> dict[str, dict]:
    last = {}
    for p in (Store().root / "labels" / KIND).glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
    return last


def label(prep_path: Path = PREP) -> int:
    import tkinter as tk

    z = np.load(prep_path)
    bands, faces, meta = z["bands"], z["faces"], json.loads(str(z["meta"]))
    root_dir = Store().root / "labels" / KIND
    root_dir.mkdir(parents=True, exist_ok=True)
    done = set(_labels())
    order = [i for i, m in enumerate(meta) if m["entity_id"] not in done]
    print(f"{len(done)} already done, {len(order)} to go", flush=True)
    if not order:
        return 0
    handles: dict[str, object] = {}
    state = {"k": 0, "img": None, "art": [], "written": 0}
    root = tk.Tk()
    root.title("reticle - which agent is ringed?")
    canvas = tk.Canvas(root, highlightthickness=0, bg="#191919")
    canvas.pack()
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")
    pad = tk.Frame(root)
    pad.pack(fill="x", padx=6, pady=4)

    def write(answer, cls):
        m = meta[order[state["k"]]]
        sid = m["session_id"]
        if sid not in handles:
            handles[sid] = (root_dir / f"{sid}.jsonl").open("a", encoding="utf-8")
        row = {"key": m["entity_id"], "session_id": sid, "death_id": m["death_id"],
               "role": m["role"], "t_ms": m["t_ms"], "observation_key": m["observation_key"],
               "ring": m["ring"], "answer": answer, "class": cls, "uncertain": cls is None,
               "by": "player"}
        handles[sid].write(json.dumps(row) + "\n")
        handles[sid].flush()
        state["written"] += 1
        step(+1)

    def buttons(agents):
        for w in pad.winfo_children():
            w.destroy()
        state["art"] = []
        for k, a in enumerate(agents):
            art = _art(a)
            if art is not None:
                _ok, buf = cv2.imencode(".png", art)
                img = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
                state["art"].append(img)
                b = tk.Button(pad, image=img, text=a, compound="top", width=80,
                              command=lambda a=a: write(a, "agent"))
            else:
                b = tk.Button(pad, text=a, width=10, command=lambda a=a: write(a, "agent"))
            b.grid(row=k // 10, column=k % 10, padx=2, pady=2)
        n = len(agents)
        tk.Button(pad, text="Other agent", height=3, command=lambda: buttons(_all_agents())
                  ).grid(row=n // 10 + 1, column=0, columnspan=2, pady=4)
        tk.Button(pad, text="Not a portrait", height=3, command=lambda: write(None, "not_portrait")
                  ).grid(row=n // 10 + 1, column=2, columnspan=2, pady=4)

    def show():
        i = order[state["k"]]
        m = meta[i]
        band = bands[i].copy()
        x0, y0, x1, y1 = m["ring"]
        cv2.rectangle(band, (x0 - 2, y0 - 2), (x1 + 1, y1 + 1), (64, 255, 64), 2)
        band = cv2.resize(band, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
        big = cv2.resize(faces[i], None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        wide = max(band.shape[1], big.shape[1])
        padw = lambda im: np.hstack([im, np.full((im.shape[0], wide - im.shape[1], 3), 25, np.uint8)])
        view = np.vstack([padw(band), np.full((8, wide, 3), 25, np.uint8), padw(big)])
        _ok, buf = cv2.imencode(".png", view)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=view.shape[1], height=view.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        t = int(m["t_ms"]) // 1000
        status.config(text=f"  {state['k'] + 1}/{len(order)}   {m['session_id']}  {t // 60}:{t % 60:02d}"
                           f"   ringed: the {m['role']}'s portrait   U unsure  A back  Q quit")
        buttons(m["lineup"] or _all_agents())

    def step(delta):
        state["k"] += delta
        if not (0 <= state["k"] < len(order)):
            finish()
            return
        show()

    def finish():
        for fh in handles.values():
            fh.close()
        print(f"wrote {state['written']} labels under {root_dir}", flush=True)
        root.destroy()

    root.bind("u", lambda e: write(None, None))
    root.bind("a", lambda e: step(-1))
    root.bind("q", lambda e: finish())
    root.bind("<Escape>", lambda e: finish())
    root.protocol("WM_DELETE_WINDOW", finish)
    show()
    root.mainloop()
    return 0


def score(prep_path: Path = PREP) -> dict:
    meta = {m["entity_id"]: m for m in json.loads(str(np.load(prep_path)["meta"]))}
    labs = [r for r in _labels().values() if r["key"] in meta and not r["uncertain"]]
    res, per, conf = Counter(), defaultdict(Counter), Counter()
    for r in labs:
        m = meta[r["key"]]
        if r["class"] == "not_portrait":
            res["not_portrait"] += 1
            continue
        ok = r["answer"] == m["said"]
        res["right" if ok else "wrong"] += 1
        res[f"{'dependent' if m['dependent'] else 'independent'}_{'right' if ok else 'wrong'}"] += 1
        per[r["answer"]]["right" if ok else "wrong"] += 1
        if not ok:
            conf[f"{r['answer']} read as {m['said']}"] += 1
    return {"labelled": len(labs), **res, "per_agent": {a: dict(c) for a, c in sorted(per.items())},
            "confusions": dict(conf.most_common())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "label", "score"])
    ap.add_argument("--n", type=int, default=120)
    args = ap.parse_args()
    if args.cmd == "prep":
        prep(args.n)
    elif args.cmd == "label":
        return label()
    else:
        print(json.dumps(score(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
