"""Name the killfeed icons the stored pipeline could not.

    .\\.venv\\Scripts\\python.exe prototypes\\label_killfeed_icons.py prep
    .\\.venv\\Scripts\\python.exe prototypes\\label_killfeed_icons.py label

Controls
--------
    a gun button          the icon is that gun
    Melee / Environmental / Other / Bad crop
                          not a gun; Bad crop when the ring is not on the icon
    an agent button       then one of that agent's four ability icons (official
                          art), or "Other ability" when none of the four
    U                     unsure: recorded, and kept out of scoring
    A                     back one
    Q / ESC               save and quit

`prep` decodes one frame per item. `prep --batch 3` decodes nothing: it binds
each item's stored weapon-slot rows as `adjudication.weapon` does, frames the
middle one from the `hud` ROI crop cache, and asks again about entries whose
last answer was Bad crop, since the locator has moved their box. The items are the stored deaths (`reticle
deaths`, death-adjudication-0.8.0) whose weapon the owner could not name: an
ability kill known only as "Ability", a weapon verdict refused, or a named
player kill outside its ammo label (the two witnesses conflict). The labeller
shows the whole killfeed row with the weapon slot ringed, so the killer's
portrait is in view, and the slot magnified. No machine name is shown; these
labels are what the gallery, the ability art and the lineup check are scored on.

Labels go to `<store>/labels/killfeed_icon/<session>.jsonl`, keyed by death id,
append-only, last row per key wins; the run is resumable.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.adjudication.death import DEATH_ADJUDICATION_VERSION  # noqa: E402
from reticle.adjudication.weapon import ABILITY_CANONICAL_NAMES  # noqa: E402
from reticle.decode import sample_at  # noqa: E402
from reticle.killfeed import analyse_killfeed, killfeed_roi  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import Store  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import weapon_icons as proto  # noqa: E402

KIND = "killfeed_icon"
PREP = Store().root / "analysis" / "killfeed_icon_labels.npz"
OFFSETS_MS = (500.0, 1000.0, 1500.0)
BAND = (60, 1100)                 # band canvas h, w before scaling
GUNS = [["Classic", "Shorty", "Frenzy", "Ghost", "Bandit", "Sheriff"],
        ["Stinger", "Spectre", "Bucky", "Judge"],
        ["Bulldog", "Guardian", "Phantom", "Vandal"],
        ["Marshal", "Outlaw", "Operator", "Ares", "Odin"],
        ["Melee", "Environmental", "Other", "Bad crop", "Clove expiry"]]
SLOTS = ["Grenade", "Ability1", "Ability2", "Ultimate"]


def items() -> list[dict]:
    """Stored deaths whose weapon the owner left unnamed, with why."""
    store = Store()
    out = []
    for p in sorted((store.root / "events" / "death").glob("*.jsonl")):
        rows = store.read_events("death", p.stem)
        if not rows or rows[0].get("death_adjudication_version") != DEATH_ADJUDICATION_VERSION:
            continue
        hud = None
        for r in rows[1:]:
            ev = r.get("weapon_evidence") or {}
            why = ("unnamed_ability" if ev.get("status") == "resolved" and ev.get("category")
                   == "ability" and not r.get("weapon")
                   else ev.get("reason") if ev.get("status") == "refused" else None)
            if not why and r["kf_player_kill"] and r.get("weapon"):
                if hud is None:
                    hud = proto._hud(p.stem)
                lab = proto.ammo_label(r["t_ms"], hud["t_ms"], hud["ammo_mag"],
                                       hud["ammo_reserve"]).get("label")
                if lab and r["weapon"] not in lab:
                    why = "ammo_conflict"
            if why:
                out.append({"session_id": p.stem, "death_id": r["death_id"], "why": why,
                            "names": ev.get("names") or {},
                            "t_first": r["t_ms"], "slot": r["slot"],
                            "player_kill": r["kf_player_kill"],
                            "player_death": r["kf_player_death"]})
    # Highest signal first, so a pass stopped early still answered the most:
    # two witnesses in conflict, then abilities, then entries never named.
    rank = {"ammo_conflict": 0, "frames_disagree": 1, "unnamed_ability": 2,
            "no_observation": 3, "too_few_named": 4}
    return sorted(out, key=lambda it: (rank[it["why"]], bool(it["names"]),
                                       it["session_id"], it["t_first"]))


def prep(out: Path = PREP, relaxed: bool = False, skip: Path | None = None) -> None:
    store = Store()
    todo = items()
    if skip is not None and skip.is_file():
        framed = {m["death_id"] for m in json.loads(str(np.load(skip)["meta"]))}
        todo = [it for it in todo if it["death_id"] not in framed]
    by = defaultdict(list)
    for it in todo:
        by[it["session_id"]].append(it)
    bands, icons, meta = [], [], []
    for sid, its in sorted(by.items()):
        man = store.read_manifest(sid)
        profile = get_profile(man.get("source_profile", "valorant-16x9"))
        roi = killfeed_roi(profile)
        want = defaultdict(list)
        for it in its:
            for off in OFFSETS_MS:
                want[it["t_first"] + off].append(it)
        found = {}
        src = man["source"]
        for s in sample_at(src["path"], sorted(want), float(src["fps"])):
            h, w = s.frame.shape[:2]
            x0, y0, x1, _ = roi.pixels(w, h)
            views = None
            for it in want.get(s.t_ms) or want[min(want, key=lambda x: abs(x - s.t_ms))]:
                if it["death_id"] in found:
                    continue
                views = views or analyse_killfeed(s.frame, roi, w, h, profile_name=profile.name)
                role = "kill" if it["player_kill"] else "death" if it["player_death"] else None
                if relaxed:
                    # The entry may have risen, or the feed not read it as the
                    # player's: nearest slot at or above, the verdict a preference.
                    cand = sorted((v for v in views if v.wx1 > v.wx0 and v.slot <= it["slot"]),
                                  key=lambda v: (role is not None and v.verdict != role,
                                                 it["slot"] - v.slot))
                else:
                    cand = [v for v in views if v.slot == it["slot"] and v.wx1 > v.wx0
                            and (role is None or v.verdict == role)]
                if not cand:
                    continue
                v = cand[0]
                band = s.frame[y0 + v.y0 - 4:y0 + v.y1 + 4, x0:x1]
                c = np.full((*BAND, 3), 25, np.uint8)
                c[:min(BAND[0], band.shape[0]), :min(BAND[1], band.shape[1])] = \
                    band[:BAND[0], :BAND[1]]
                found[it["death_id"]] = (c, s.frame[y0 + v.y0:y0 + v.y1, x0 + v.wx0:x0 + v.wx1],
                                         {**it, "t_ms": s.t_ms, "ring": [v.wx0, 4, v.wx1,
                                                                         4 + v.y1 - v.y0]})
        for c, icon, m in found.values():
            ic = np.full((40, 160, 3), 25, np.uint8)
            ic[:min(40, icon.shape[0]), :min(160, icon.shape[1])] = icon[:40, :160]
            bands.append(c)
            icons.append(ic)
            meta.append(m)
        missing = [it["death_id"] for it in its if it["death_id"] not in found]
        print(f"{sid}: {len(its)} items, {len(its) - len(missing)} framed"
              + (f", unframed {missing}" if missing else ""))
    order = {it["death_id"]: k for k, it in enumerate(todo)}
    ranked = sorted(range(len(meta)), key=lambda k: order[meta[k]["death_id"]])
    bands = [bands[k] for k in ranked]
    icons = [icons[k] for k in ranked]
    meta = [{**meta[k], "relaxed": relaxed} for k in ranked]
    np.savez_compressed(out, bands=np.array(bands), icons=np.array(icons),
                        meta=json.dumps(meta))
    print(f"{len(meta)} items -> {out}")


def prep_cache(out: Path) -> None:
    """Batch 3: items framed from the crop cache at their bound weapon rows."""
    import glob
    import pyarrow.parquet as pq
    from reticle.adjudication.death import session_entries
    from reticle.adjudication.weapon import bind_entry
    from reticle.roi_cache import RoiCache
    store = Store()
    last = {}
    for path in (store.root / "labels" / KIND).glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
    todo = [it for it in items()
            if it["death_id"] not in last or last[it["death_id"]]["class"] == "bad_crop"]
    by = defaultdict(list)
    for it in todo:
        by[it["session_id"]].append(it)
    bands, icons, meta = [], [], []
    for sid, its in sorted(by.items()):
        man = store.read_manifest(sid)
        profile = get_profile(man.get("source_profile", "valorant-16x9"))
        cache, why = RoiCache.load(store.root, man, profile, "killfeed")
        if cache is None:
            print(f"{sid}: no crop cache ({why}); {len(its)} items skipped")
            continue
        x0, y0, x1, _ = cache.rect_of("killfeed")
        hud = pq.read_table(glob.glob(str(store.root / "l1" / "hud" / "*" / f"session={sid}"
                                          / "hud.parquet"))[0]).to_pydict()
        ents = {(int(e["t_first"]), e["slot"]): e for e in session_entries(hud)}
        obs = store.read_events("killfeed_weapon", sid)
        framed = 0
        for it in its:
            e = ents.get((int(it["t_first"]), it["slot"]))
            rows = [o for o in (bind_entry(e, obs) if e else []) if o.get("grid")]
            if not rows:
                continue
            o = rows[len(rows) // 2]
            got = list(cache.samples([float(o["t_ms"])], rois="killfeed"))
            if not got:
                continue
            f = got[0].frame
            band = f[y0 + o["y0"] - 4:y0 + o["y1"] + 4, x0:x1]
            c = np.full((*BAND, 3), 25, np.uint8)
            c[:min(BAND[0], band.shape[0]), :min(BAND[1], band.shape[1])] = \
                band[:BAND[0], :BAND[1]]
            icon = f[y0 + o["y0"]:y0 + o["y1"], x0 + o["wx0"]:x0 + o["wx1"]]
            ic = np.full((40, 160, 3), 25, np.uint8)
            ic[:min(40, icon.shape[0]), :min(160, icon.shape[1])] = icon[:40, :160]
            bands.append(c)
            icons.append(ic)
            meta.append({**it, "t_ms": float(o["t_ms"]),
                         "ring": [o["wx0"], 4, o["wx1"], 4 + o["y1"] - o["y0"]],
                         "batch": 3,
                         "previous": (last.get(it["death_id"]) or {}).get("class")})
            framed += 1
        print(f"{sid}: {len(its)} items, {framed} framed from the cache")
    np.savez_compressed(out, bands=np.array(bands).reshape(-1, *BAND, 3),
                        icons=np.array(icons).reshape(-1, 40, 160, 3), meta=json.dumps(meta))
    print(f"{len(meta)} items -> {out}")


def ability_art(agent: str) -> list[tuple[str, str, np.ndarray]]:
    """(stem, shown name, art) for an agent's four abilities, from the store."""
    root = Store().root / "reference" / "assets" / "abilities"
    stem_agent = "KAY_O" if agent == "KAY" else agent
    out = []
    for slot in SLOTS:
        stem = f"{stem_agent}_{slot}"
        img = cv2.imread(str(root / f"{stem}.png"), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        if img.shape[2] == 4:
            a = img[:, :, 3:4] / 255.0
            img = (img[:, :, :3] * a + 40 * (1 - a)).astype(np.uint8)
        out.append((stem, ABILITY_CANONICAL_NAMES.get(stem, stem.split("_")[-1]),
                    cv2.resize(img, (72, 72), interpolation=cv2.INTER_AREA)))
    return out


def agents() -> list[str]:
    root = Store().root / "reference" / "assets" / "agents"
    return sorted({p.name.split("_")[0] for p in root.glob("*.png")})


def label(prep_path: Path = PREP) -> int:
    import tkinter as tk

    z = np.load(prep_path)
    bands, icons, meta = z["bands"], z["icons"], json.loads(str(z["meta"]))
    root_dir = Store().root / "labels" / KIND
    root_dir.mkdir(parents=True, exist_ok=True)
    last = {}
    for p in root_dir.glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
    # A Bad crop answer is about the box; batch 3 shows a new box, so ask again.
    reframed = {m["death_id"] for m in meta if m.get("batch") == 3}
    done = {k for k, r in last.items() if r["class"] != "bad_crop" or k not in reframed}
    order = [i for i, m in enumerate(meta) if m["death_id"] not in done]
    if not order:
        print("every item already has a label")
        return 0
    print(f"{len(done)} already done, {len(order)} to go")

    handles: dict[str, object] = {}
    state = {"k": 0, "img": None, "art": [], "written": 0}
    root = tk.Tk()
    root.title("reticle - what is in the ringed weapon slot?")
    canvas = tk.Canvas(root, highlightthickness=0, bg="#191919")
    canvas.pack()
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")
    pad = tk.Frame(root)
    pad.pack(fill="x", padx=6, pady=4)
    ab = tk.Frame(root)
    ab.pack(fill="x", padx=6, pady=4)

    def show():
        i = order[state["k"]]
        m = meta[i]
        band = bands[i].copy()
        x0, y0, x1, y1 = m["ring"]
        cv2.rectangle(band, (x0 - 2, y0 - 2), (x1 + 1, y1 + 1), (64, 255, 64), 1)
        band = cv2.resize(band, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
        big = cv2.resize(icons[i], None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        wide = max(band.shape[1], big.shape[1])
        pad_to = lambda im: np.hstack([im, np.full((im.shape[0], wide - im.shape[1], 3), 25,
                                                   np.uint8)])
        view = np.vstack([pad_to(band), np.full((8, wide, 3), 25, np.uint8), pad_to(big)])
        _ok, buf = cv2.imencode(".png", view)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=view.shape[1], height=view.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        t = int(m["t_ms"]) // 1000
        status.config(text=f"  {state['k'] + 1}/{len(order)}   {m['session_id']}  "
                           f"{t // 60}:{t % 60:02d}   ringed: the weapon slot   "
                           f"U unsure  A back  Q quit")
        for wdg in ab.winfo_children():
            wdg.destroy()

    def write(answer: str | None, cls: str | None, **extra):
        i = order[state["k"]]
        m = meta[i]
        sid = m["session_id"]
        if sid not in handles:
            handles[sid] = (root_dir / f"{sid}.jsonl").open("a", encoding="utf-8")
        row = {"key": m["death_id"], "session_id": sid, "t_ms": m["t_ms"], "slot": m["slot"],
               "ring": m["ring"], "why": m["why"], "answer": answer, "class": cls,
               "uncertain": cls is None, "by": "player", **extra}
        handles[sid].write(json.dumps(row) + "\n")
        handles[sid].flush()
        state["written"] += 1
        step(+1)

    def step(delta):
        state["k"] += delta
        if not (0 <= state["k"] < len(order)):
            finish()
            return
        show()

    def pick_agent(agent: str):
        for wdg in ab.winfo_children():
            wdg.destroy()
        tk.Label(ab, text=f"{agent}:", font=("Consolas", 11)).pack(side="left")
        state["art"] = []
        for stem, name, art in ability_art(agent):
            _ok, buf = cv2.imencode(".png", art)
            img = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
            state["art"].append(img)
            tk.Button(ab, image=img, text=name, compound="top", width=110,
                      command=lambda s=stem, n=name: write(n, "ability", agent=agent,
                                                           ability_stem=s)).pack(side="left",
                                                                                  padx=3)
        tk.Button(ab, text="Other ability", height=4,
                  command=lambda: write(None, "ability", agent=agent,
                                        ability_stem=None)).pack(side="left", padx=3)

    def finish():
        for fh in handles.values():
            fh.close()
        print(f"wrote {state['written']} labels under {root_dir}")
        root.destroy()

    for r, names in enumerate(GUNS):
        for c, nm in enumerate(names):
            cls = {"Melee": "melee", "Environmental": "environmental", "Other": "other",
                   "Bad crop": "bad_crop", "Clove expiry": "ability"}.get(nm, "gun")
            tk.Button(pad, text=nm, width=12,
                      command=lambda nm=nm, cls=cls: write(
                          None if cls == "bad_crop" else nm, cls)).grid(row=r, column=c,
                                                                       padx=2, pady=1)
    ag = tk.Frame(pad)
    ag.grid(row=0, column=7, rowspan=len(GUNS), padx=16, sticky="n")
    for k, a in enumerate(agents()):
        tk.Button(ag, text=a, width=9, command=lambda a=a: pick_agent(a)).grid(
            row=k // 6, column=k % 6, padx=1, pady=1)
    root.bind("u", lambda e: write(None, None))
    root.bind("a", lambda e: step(-1))
    root.bind("q", lambda e: finish())
    root.bind("<Escape>", lambda e: finish())
    root.protocol("WM_DELETE_WINDOW", finish)
    show()
    root.mainloop()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "label"])
    ap.add_argument("--batch", type=int, default=1,
                    help="2: the items batch 1 could not frame, matched loosely; "
                         "3: framed from the crop cache after the locator fix")
    args = ap.parse_args()
    path = PREP if args.batch == 1 else PREP.with_name(f"{PREP.stem}_{args.batch}.npz")
    if args.cmd == "prep":
        if args.batch == 3:
            prep_cache(path)
        else:
            prep(path, relaxed=args.batch > 1, skip=PREP if args.batch > 1 else None)
        return 0
    return label(path)


if __name__ == "__main__":
    raise SystemExit(main())
