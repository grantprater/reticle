r"""Name the groups of killfeed icons the weapon owner refused as new, one group at a time.

    .\.venv\Scripts\python.exe prototypes\label_killfeed_groups.py <product.json> [--min-size N]

The product is a file `prototypes/killfeed_openset.py groups` wrote under
`<store>/candidates/killfeed_new_icon/`: the stored `killfeed_weapon` rows the
owner (`adjudication.weapon`, weapon-adjudication-0.7.0 or later) refused as
`new`, grouped across sessions by `weapon_icons.cluster`. Stored rows and the
crop cache only; nothing is decoded.

Each group shows its exemplar's icon enlarged, the exemplar's whole killfeed
row from the crop cache with the icon ringed (so the killer's and victim's
names and portraits are in view), and the group's members (up to the
product's MEMBERS_KEPT, spread over their similarity to the exemplar), each
captioned with its session and time. The question is about the ringed icon,
not the row.

Controls
--------
    N, /, Return     type a name: completion offers the gallery's names, the
                     weapon taxonomy and the agents' ability names; Tab takes
                     the first match, Up/Down move through them, Return
                     answers, Esc leaves the box. A name outside those lists
                     is free text and needs its class (gun, ability, other)
                     chosen beside the box.
    O                an icon, but other than any name you can give
    X                not an icon, or the group mixes icons: names nothing
    U                unsure: recorded, and kept out of every use
    F                flash the owner's nearest name for this group for 1.5 s;
                     the next answer records that you saw it
    A                back one group
    Q / Esc          save and quit

No answer is filled in for you; the owner's nearest name appears only on F.

Labels go to `<store>/labels/killfeed_new_icon/<product stem>.jsonl`, keyed
by `<product stem>#<group>`, append-only, last row per key wins; each row
names the product, its SHA-256, the exemplar and every member shown, and `by`.
The run is resumable.

From labels to gallery exemplars
--------------------------------
`prototypes/weapon_icons.py gallery` reads these files
(`weapon_icons.new_icon_entries`): a group whose last row carries a name
(not unsure, not `other`, not `not_icon`) turns the members its row lists,
and only those, into exemplars keyed `new:<sid>:<t_ms>:<slot>`, with the
member's stored grid and aspect. Nothing the player did not name becomes an
exemplar. The gallery file never overwrites a version: bump
`adjudication.weapon.WEAPON_GALLERY_VERSION` to weapon-gallery-0.4.0 before
running `weapon_icons.py gallery`.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.adjudication.weapon import (  # noqa: E402
    ABILITY_CANONICAL_NAMES, MINED_NOT_GUN, WEAPON_TAXONOMY, load_mined_gallery)
from reticle.store import Store  # noqa: E402

VERSION = "label-killfeed-groups-0.1.0"
KIND = "killfeed_new_icon"
ICON_ZOOM = 4                     # the exemplar's icon
ROW_ZOOM = 1.5                    # the exemplar's killfeed row
MEMBER_ZOOM = 2                   # each member's icon
MEMBER_COLS = 4
FLASH_MS = 1500
CLASSES = ("gun", "ability", "other")


def known_names() -> dict[str, str]:
    """{name: class} the completion offers: the gallery's names, the weapon
    taxonomy and every agent's ability names. A class here is the name's
    category, never a guess about the icon."""
    out: dict[str, str] = {}
    for cls, names in WEAPON_TAXONOMY.items():
        for n in names:
            out[n] = {"melee": "melee", "environmental": "environmental"}.get(cls, "gun")
    for n in ABILITY_CANONICAL_NAMES.values():
        out[n] = "ability"
    gal = load_mined_gallery()
    for n in sorted({str(n) for n in (gal or {}).get("names", [])}):
        out.setdefault(n, MINED_NOT_GUN.get(n, "gun"))
    return out


def _cache(sid: str, caches: dict):
    """The session's crop cache and its killfeed rect, loaded once."""
    if sid not in caches:
        from reticle.profiles import get_profile
        from reticle.roi_cache import RoiCache
        store = Store()
        man = store.read_manifest(sid)
        cache, _why = RoiCache.load(store.root, man,
                                    get_profile(man.get("source_profile", "valorant-16x9")))
        caches[sid] = (cache, cache.rect_of("killfeed") if cache is not None else None)
    return caches[sid]


def frame_of(row: dict, caches: dict, frames: dict):
    """The crop-cache frame at a row's time, or None when the cache lacks it."""
    key = (row["session_id"], float(row["t_ms"]))
    if key not in frames:
        cache, _rect = _cache(row["session_id"], caches)
        got = list(cache.samples([float(row["t_ms"])], rois="killfeed")) if cache else []
        frames[key] = got[0].frame if got else None
    return frames[key]


def icon_crop(row: dict, caches: dict, frames: dict) -> np.ndarray | None:
    f = frame_of(row, caches, frames)
    if f is None:
        return None
    x0, y0, _, _ = _cache(row["session_id"], caches)[1]
    return f[y0 + row["y0"]:y0 + row["y1"], x0 + row["wx0"]:x0 + row["wx1"]].copy()


def row_band(row: dict, caches: dict, frames: dict) -> np.ndarray | None:
    """The exemplar's whole killfeed row with its icon ringed."""
    f = frame_of(row, caches, frames)
    if f is None:
        return None
    x0, y0, x1, _ = _cache(row["session_id"], caches)[1]
    band = f[max(0, y0 + row["y0"] - 6):y0 + row["y1"] + 6, x0:x1].copy()
    top = 6 if y0 + row["y0"] - 6 >= 0 else y0 + row["y0"]
    cv2.rectangle(band, (row["wx0"] - 2, top - 2), (row["wx1"] + 1, top + row["y1"] - row["y0"] + 1),
                  (64, 255, 64), 1)
    return band


def _blank(h: int, w: int) -> np.ndarray:
    return np.full((h, w, 3), 25, np.uint8)


def _zoom(img: np.ndarray | None, z: float, missing=(20, 80)) -> np.ndarray:
    if img is None or img.size == 0:
        out = _blank(*missing)
        cv2.putText(out, "no cache", (4, missing[0] // 2 + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                    (160, 160, 160), 1)
        return out
    return cv2.resize(img, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)


def _stack(rows: list[np.ndarray], gap: int = 6) -> np.ndarray:
    w = max(r.shape[1] for r in rows)
    out = []
    for r in rows:
        out += [np.hstack([r, _blank(r.shape[0], w - r.shape[1])]), _blank(gap, w)]
    return np.vstack(out[:-1])


def view(group: dict, caches: dict, frames: dict) -> np.ndarray:
    ex = group["exemplar"]
    head = _zoom(icon_crop(ex, caches, frames), ICON_ZOOM, (80, 320))
    band = _zoom(row_band(ex, caches, frames), ROW_ZOOM, (40, 600))
    cells = []
    for m in group["members"]:
        c = _zoom(icon_crop(m, caches, frames), MEMBER_ZOOM, (40, 160))
        cap = _blank(16, max(c.shape[1], 170))
        cv2.putText(cap, f"{m['session_id'][:6]} {m['t_ms'] / 1000:.1f}s s{m['slot']}", (2, 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (190, 190, 190), 1)
        cells.append(_stack([c, cap], gap=1))
    grid_rows = []
    for k in range(0, len(cells), MEMBER_COLS):
        part = cells[k:k + MEMBER_COLS]
        h = max(c.shape[0] for c in part)
        part = [np.vstack([c, _blank(h - c.shape[0], c.shape[1])]) for c in part]
        grid_rows.append(np.hstack([np.hstack([c, _blank(h, 10)]) for c in part]))
    return _stack([head, band] + ([_stack(grid_rows)] if grid_rows else []), gap=10)


def load_last(path: Path) -> dict[str, dict]:
    last: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
    return last


def label(product: Path, min_size: int = 1) -> int:
    import tkinter as tk

    raw = product.read_bytes()
    body = json.loads(raw.decode("utf-8"))
    sha = hashlib.sha256(raw).hexdigest()
    out_dir = Store().root / "labels" / KIND
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{product.stem}.jsonl"
    last = load_last(out_path)
    groups = [g for g in body["groups"] if g["size"] >= min_size]
    keyed = lambda g: f"{product.stem}#{g['group']}"
    order = [k for k, g in enumerate(groups) if keyed(g) not in last]
    if not order:
        print(f"every group of {product.name} already has a label in {out_path}")
        return 0
    print(f"{len(groups) - len(order)} already done, {len(order)} to go -> {out_path}")
    names = known_names()
    lower = {n.lower(): n for n in names}

    fh = out_path.open("a", encoding="utf-8")
    caches: dict = {}
    frames: dict = {}
    state = {"k": 0, "img": None, "written": 0, "flashed": False, "flash_job": None}
    root = tk.Tk()
    root.title("reticle - what is the ringed killfeed icon?")
    canvas = tk.Canvas(root, highlightthickness=0, bg="#191919")
    canvas.pack()
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")
    flash = tk.Label(root, anchor="w", font=("Consolas", 11), fg="#b05000")
    flash.pack(fill="x")
    bar = tk.Frame(root)
    bar.pack(fill="x", padx=6, pady=4)
    tk.Label(bar, text="name:", font=("Consolas", 11)).pack(side="left")
    text = tk.StringVar()
    entry = tk.Entry(bar, textvariable=text, width=28, font=("Consolas", 12))
    entry.pack(side="left", padx=4)
    cls_var = tk.StringVar(value="")
    for c in CLASSES:
        tk.Radiobutton(bar, text=c, value=c, variable=cls_var, takefocus=0).pack(side="left")
    hint = tk.Label(bar, anchor="w", font=("Consolas", 10), fg="#a00000")
    hint.pack(side="left", padx=8)
    match = tk.Listbox(root, height=6, font=("Consolas", 11), exportselection=False)
    match.pack(fill="x", padx=6, pady=2)

    def group():
        return groups[order[state["k"]]]

    def show():
        g = group()
        v = view(g, caches, frames)
        _ok, buf = cv2.imencode(".png", v)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=v.shape[1], height=v.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        sess = ", ".join(f"{s} x{n}" for s, n in g["sessions"].items())
        status.config(text=f"  {state['k'] + 1}/{len(order)}  {g['group']}: {g['size']} rows, "
                           f"{g['entries']} entries ({sess})   N name  O other  X not an icon  "
                           f"U unsure  F flash  A back  Q quit  (X O U also work in an empty name box)")
        flash.config(text="")
        hint.config(text="")
        text.set("")
        cls_var.set("")
        state["flashed"] = False
        refresh()
        root.focus_set()

    def refresh(*_):
        q = text.get().strip().lower()
        hits = sorted((n for n in names if q and q in n.lower()),
                      key=lambda n: (not n.lower().startswith(q), n))
        match.delete(0, "end")
        for n in hits[:12]:
            match.insert("end", f"{n}  ({names[n]})")
        if hits:
            match.selection_set(0)

    def chosen_hit() -> str | None:
        sel = match.curselection()
        return match.get(sel[0]).rsplit("  (", 1)[0] if sel else None

    def write(answer: str | None, cls: str | None, **extra):
        g = group()
        member = lambda m: [m["session_id"], m["t_ms"], m["slot"]]
        row = {"key": keyed(g), "product": product.name, "product_sha256": sha,
               "product_version": body.get("version"), "group": g["group"],
               "answer": answer, "class": cls, "uncertain": cls is None,
               "exemplar": member(g["exemplar"]), "members": [member(m) for m in g["members"]],
               "size": g["size"], "compared_against_derived": state["flashed"],
               "by": "player", "labeller": VERSION,
               "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               **extra}
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        state["written"] += 1
        step(+1)

    def submit(_e=None):
        typed = text.get().strip()
        if not typed:
            return "break"
        name = lower.get(typed.lower())
        if name is not None:
            write(name, names[name], free_text=False)
        elif not cls_var.get():
            hint.config(text="free text: choose gun, ability or other")
        else:
            write(typed, cls_var.get(), free_text=True)
        return "break"

    def tab(_e=None):
        hit = chosen_hit()
        if hit:
            text.set(hit)
            entry.icursor("end")
        return "break"

    def move(d):
        def go(_e=None):
            sel = match.curselection()
            k = (sel[0] if sel else -1) + d
            if 0 <= k < match.size():
                match.selection_clear(0, "end")
                match.selection_set(k)
                match.see(k)
            return "break"
        return go

    def leave(_e=None):
        root.focus_set()
        return "break"

    def focus_entry(_e=None):
        entry.focus_set()
        return "break"

    def show_flash(_e=None):
        g = group()
        best = ", ".join(f"{n} x{c}" for n, c in g.get("best", []))
        flash.config(text=f"  owner's nearest: {best} (median IoU {g.get('median_score')})")
        state["flashed"] = True
        if state["flash_job"]:
            root.after_cancel(state["flash_job"])
        state["flash_job"] = root.after(FLASH_MS, lambda: flash.config(text=""))

    def step(delta):
        state["k"] += delta
        if not (0 <= state["k"] < len(order)):
            finish()
            return
        show()

    def back(_e=None):
        if state["k"] > 0:
            step(-1)

    def finish(_e=None):
        fh.close()
        print(f"wrote {state['written']} labels to {out_path}")
        root.destroy()

    def hot(fn):
        # The letter keys act only outside the name box.
        return lambda e: None if root.focus_get() is entry else fn(e)

    def empty_box(fn):
        # X, O and U also act in the name box while it is empty; once a
        # name is typed they are letters again.
        def go(e):
            if text.get():
                return None
            fn(e)
            return "break"
        return go

    text.trace_add("write", refresh)
    entry.bind("<Return>", submit)
    entry.bind("<Tab>", tab)
    entry.bind("<Down>", move(+1))
    entry.bind("<Up>", move(-1))
    entry.bind("<Escape>", leave)
    root.bind("<slash>", hot(focus_entry))
    root.bind("<Return>", hot(focus_entry))
    # Each letter binds both cases, so Shift and Caps Lock work too.
    letters = {"n": focus_entry, "f": show_flash, "a": back, "q": finish,
               "o": lambda e: write(None, "other"),
               "x": lambda e: write(None, "not_icon"),
               "u": lambda e: write(None, None)}
    for key, fn in letters.items():
        for k in (key, key.upper()):
            root.bind(k, hot(fn))
            if key in "oxu":
                entry.bind(k, empty_box(fn))
    root.bind("<Escape>", hot(finish))
    root.protocol("WM_DELETE_WINDOW", finish)
    show()
    root.mainloop()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("product", type=Path, help="a killfeed_new_icon group product (.json)")
    ap.add_argument("--min-size", type=int, default=1, help="skip groups with fewer rows")
    a = ap.parse_args()
    return label(a.product, a.min_size)


if __name__ == "__main__":
    raise SystemExit(main())
