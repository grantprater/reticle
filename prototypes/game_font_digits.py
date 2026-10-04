r"""Which game font each HUD digit field draws in, and whether digit templates
rendered from the extracted font files read as well as the mined ones.

    .\.venv\Scripts\python.exe prototypes\game_font_digits.py census [--n 120] [--out DIR]
    .\.venv\Scripts\python.exe prototypes\game_font_digits.py compare [--cuts ...] [--production] [--out DIR]
    .\.venv\Scripts\python.exe prototypes\game_font_digits.py scoreboard [--pts 11.625] [--envelope 9 12] [--out DIR]

`compare --production` rereads with the reader's own sets
(`ocr.game_font_templates`); `scoreboard` reruns `trial` for the scoreboard
with rendered templates and scores each row against Riot's per-player
kill, death and assist trajectory and round credits. The scoreboard stays on
the mined set: on 5822b6646448 the rendered set reads half-cut digits in
misplaced row bands (88 deaths) that the mined set refuses.

BACKLOG item 2(d): every reader that matches game art uses the extracted game
files (`<store>/reference/game-files/`). The digit readers (`ocr.read_scoreline`,
`ocr.read_bottom_hud`, `scoreboard._read_cell_detail`) match each thresholded
glyph, normalised to a 20x12 grid (`ocr.normalise`), against 44 templates mined
from footage (`valorant-16x9-digits.npz`). The game's widget data names each
field's face and point size (`hud-layout/.../TimerHUDElement.json` and its
siblings) but not its font object, so `census` renders every candidate face at
a sweep of sizes and fits each field's stored glyphs; `compare` rereads every
stored HUD row from the crop cache (no decode) with templates rendered from the
fitted font and diffs the readings against the stored ones.

Glyphs are labelled by the stored reading they belong to (the mined reader's
own output): a fit of shape, not an independent truth. The before/after verdicts
in `compare` rest on independent checks named there.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle import ocr  # noqa: E402

SESSIONS = ("a06f04a0059f", "5822b6646448", "4f207c0c4e39")
FONT_DIR = ("reference/game-files/release-13.06-shipping-18-5590001/fonts/"
            "ShooterGame/Content")
FACES = {
    "Tungsten-Bold": "Tungsten-Bold.otf",
    "Tungsten-Black": "Tungsten-Black.otf",
    "DINNext_Light": "UI/Fonts/FinalFonts/DINNext_Light.ttf",
    "DINNext_Regular": "UI/Fonts/FinalFonts/DINNext_Regular.ttf",
    "DINNext_Medium": "UI/Fonts/FinalFonts/DINNext_Medium.ttf",
    "DINNext_Bold": "UI/Fonts/FinalFonts/DINNext_Bold.ttf",
    "DINNext_Heavy": "UI/Fonts/FinalFonts/DINNext_Heavy.ttf",
    "FoundryGridnik-ExtraBold": "UI/Fonts/FinalFonts/FoundryGridnik-ExtraBold.ttf",
}
#: Each field's widget, face name and point size in the game's UI data.
WIDGET_PT = {
    "clock": ("TimerHUDElement.TimerLine1", "Default", 28.0),
    "score_left": ("TeamScoreHUDElement.Score", "Default", 22.0),
    "score_right": ("TeamScoreHUDElement.Score", "Default", 22.0),
    "hp": ("HealthHUDElement_CharacterHUD.HealthText", "Medium", 36.0),
    "shield": ("(not exported)", None, None),
    "ammo_mag": ("AmmoHUDElement_CharacterHUD.LoadedAmmo", "Medium", 36.0),
    "ammo_reserve": ("AmmoHUDElement_CharacterHUD.ReserveAmmo", "Default", 16.0),
}
SLATE_PX_PER_PT = 96.0 / 72.0
SUPERSAMPLE = 8
PHASES = 4
#: Coverage above which a rendered pixel counts as glyph: white text over a
#: plate of luma b passes the reader's 190 cut where c > (190 - b) / (255 - b),
#: 0.6 at b ~ 90. Fixed before measuring (F5).
COVER_CUT = 0.6


def store_root() -> Path:
    from reticle.store import Store
    return Path(Store().root)


def face_file(face: str) -> str:
    return str(store_root() / FONT_DIR / FACES[face])


def ink(ch: str, font_file: str, px: float, dx: float = 0.0, dy: float = 0.0) -> np.ndarray:
    """`ch` white on black at `px` capture px per em, offset (dx, dy), as
    float32 coverage: drawn SUPERSAMPLE times larger, shrunk with INTER_AREA."""
    from PIL import Image, ImageDraw, ImageFont
    ss = SUPERSAMPLE
    font = ImageFont.truetype(font_file, px * ss, layout_engine=ImageFont.Layout.BASIC)
    left, top, right, bottom = font.getbbox(ch)
    pad = 2 * ss
    w = int(np.ceil((right - left + 2 * pad) / ss)) * ss
    h = int(np.ceil((bottom - top + 2 * pad) / ss)) * ss
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text((pad - left + dx * ss, pad - top + dy * ss), ch, fill=255, font=font)
    a = np.asarray(im, np.float32) / 255.0
    return cv2.resize(a, (w // ss, h // ss), interpolation=cv2.INTER_AREA)


def glyph_bitmap(cover: np.ndarray, cut: float = COVER_CUT):
    """The reader's view of a rendered glyph: cut once, the largest component's
    box, `ocr.normalise`. Returns (bitmap, h, w) or None."""
    binary = (cover > cut).astype(np.uint8) * 255
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(v) for v in stats[i, :4])
    rows = np.nonzero(binary.any(axis=1))[0]
    if h < ocr.BROKEN_GLYPH_H * (rows[-1] - rows[0] + 1):
        return None                      # the cut broke the digit (ocr._cut_glyph)
    return ocr.normalise(binary[y:y + h, x:x + w]), h, w


def render_set(face: str, px: float, phases: int = PHASES, cut: float = COVER_CUT):
    """{digit: [(bitmap, h, w), ...]} over phases x phases sub-pixel offsets."""
    ff = face_file(face)
    out = {}
    for d in "0123456789":
        got = []
        for j in range(phases):
            for i in range(phases):
                g = glyph_bitmap(ink(d, ff, px, i / phases, j / phases), cut)
                if g is not None:
                    got.append(g)
        out[d] = got
    return out


def templates_from(sets: list[dict]) -> ocr.Templates:
    """An `ocr.Templates` holding every distinct rendered bitmap per digit."""
    labels, maps, seen = [], [], set()
    for s in sets:
        for d, gs in s.items():
            for bm, _h, _w in gs:
                k = (d, bm.tobytes())
                if k in seen:
                    continue
                seen.add(k)
                labels.append(d)
                maps.append(bm)
    return ocr.Templates(labels, np.array(maps, np.float32))


# --------------------------------------------------------------------------- stored glyphs

def _session(sid: str):
    from reticle.store import Store
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    store = Store()
    man = store.read_manifest(sid)
    profile = get_profile(man["source_profile"])
    hud = store.read_hud(sid, man["ingested_at"][:10]).to_pydict()
    cache, why = RoiCache.load(store.root, man, profile, "hud")
    if cache is None:
        raise SystemExit(f"{sid}: no hud crop cache ({why})")
    return store, man, profile, hud, cache


def field_glyphs(frame: np.ndarray, profile, w: int, h: int) -> dict[str, list]:
    """Each field's glyph candidates, chosen exactly as the reader chooses them."""
    out: dict[str, list] = {}
    gray = ocr.crop_gray(frame, ocr.scoreline_roi(profile), w, h)
    glyphs, _blk = ocr._components(gray)
    width = gray.shape[1]
    for name, (lo, hi) in ocr.FIELD_BOUNDS.items():
        out[name] = ocr.drop_odd_siblings([g for g in glyphs if lo <= g.cx / max(1, width) < hi])
    by_name = {r.name: r for r in profile.rois}
    for roi_name, fields in ocr.BOTTOM_FIELDS.items():
        g2 = ocr.crop_gray(frame, by_name[roi_name], w, h)
        binary, raw = ocr._raw_components(g2)
        hr, wr = max(1, g2.shape[0]), max(1, g2.shape[1])
        for spec in fields:
            c = []
            for x, y, ww, hh, area in raw:
                if not (spec.x0 <= (x + ww / 2.0) / wr < spec.x1):
                    continue
                if spec.h_lo <= hh / hr <= spec.h_hi and area >= ocr.MIN_AREA and ww / max(1, hh) <= ocr.MAX_ASPECT:
                    c.append(ocr.Glyph(x=x, y=y, w=ww, h=hh,
                                       bitmap=ocr.normalise(binary[y:y + hh, x:x + ww])))
            c.sort(key=lambda g: g.x)
            out[spec.name] = ocr.drop_odd_siblings(c)
    return out


def stored_text(hud: dict, i: int, field: str) -> str | None:
    v = hud[field if field != "clock" else "clock_ms"][i]
    if v is None:
        return None
    if field == "clock":
        s = int(v) // 1000
        return f"{s // 60}{s % 60:02d}"
    return str(int(v))


FIELDS = ("clock", "score_left", "score_right", "hp", "shield", "ammo_mag", "ammo_reserve")


def collect_glyphs(sid: str, n: int) -> dict[str, list]:
    """Labelled glyphs per field from up to `n` stored rows that read every
    scoreline field, plus up to `n` that read the bottom HUD."""
    store, man, profile, hud, cache = _session(sid)
    w, h = int(man["source"]["width"]), int(man["source"]["height"])
    t = np.asarray(hud["t_ms"], float)
    held = set(cache.holds())
    full = [i for i in range(len(t)) if float(t[i]) in held and any(
        hud[f if f != "clock" else "clock_ms"][i] is not None for f in FIELDS)]
    pick = full[:: max(1, len(full) // n)][:n]
    out = defaultdict(list)
    times = [float(t[i]) for i in pick]
    for i, smp in zip(pick, cache.samples(times, rois=("scoreline", "hud_hp", "hud_ammo"))):
        fg = field_glyphs(smp.frame, profile, w, h)
        for f in FIELDS:
            txt = stored_text(hud, i, f)
            if txt is None or len(txt) != len(fg[f]):
                continue
            for ch, g in zip(txt, fg[f]):
                out[f].append((ch, g.h, g.w, g.bitmap))
    return out


def font_census(args) -> dict:
    glyphs = defaultdict(list)
    for sid in SESSIONS:
        for f, gs in collect_glyphs(sid, args.n).items():
            glyphs[f].extend(gs)
    result = {}
    for f in FIELDS:
        gs = glyphs.get(f, [])
        if not gs:
            result[f] = {"glyphs": 0}
            continue
        hs = np.array([g[1] for g in gs])
        by_d = defaultdict(list)
        for ch, _h, _w, bm in gs:
            by_d[ch].append(bm)
        print(f"{f}: {len(gs)} glyphs, h median {np.median(hs):.0f} "
              f"(p10 {np.percentile(hs, 10):.0f}, p90 {np.percentile(hs, 90):.0f}), "
              f"digits {sorted(by_d)}")
        rows = []
        for face in FACES:
            for em in np.arange(10.0, 56.0, 0.5):
                # Cheap first: one phase, height within 3 px of the median.
                rs = render_set(face, em, phases=1)
                hr = np.median([gs_[0][1] for gs_ in rs.values() if gs_])
                if abs(hr - np.median(hs)) > 3:
                    continue
                rs = render_set(face, em, phases=2)
                mads = []
                for d, bms in by_d.items():
                    tm = np.array([b for b, _h, _w in rs.get(d, [])])
                    if not len(tm):
                        continue
                    for bm in bms:
                        mads.append(np.abs(tm - bm).reshape(len(tm), -1).mean(axis=1).min())
                rows.append({"face": face, "em_px": float(em), "h_render": float(hr),
                             "mad": float(np.mean(mads)), "n": len(mads)})
        rows.sort(key=lambda r: r["mad"])
        best_face = {}
        for r in rows:
            best_face.setdefault(r["face"], r)
        for r in sorted(best_face.values(), key=lambda r: r["mad"]):
            print(f"   {r['face']:26s} em {r['em_px']:5.1f} px  h {r['h_render']:4.1f}  "
                  f"mad {r['mad']:.4f}")
        result[f] = {"glyphs": len(gs), "h_median": float(np.median(hs)),
                     "best_per_face": sorted(best_face.values(), key=lambda r: r["mad"]),
                     "widget": WIDGET_PT[f]}
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / "census.json").write_text(json.dumps(result, indent=1))
    return result


#: The fitted fonts: face and em px per field. Every em but the shield's is
#: the widget's point size times 96/72 (the census fits each within 0.7 px);
#: 'Default' resolves to DINNext_Font's first typeface, Regular. The shield's
#: widget (ArmorHUDElement_CharacterHUD) is not exported; the census fits
#: DIN Next Medium at 19 px, and 14 pt (18.67 px) is the nearest point size.
FIELD_FONT = {
    "clock": ("DINNext_Regular", 28.0 * SLATE_PX_PER_PT),
    "score": ("DINNext_Regular", 22.0 * SLATE_PX_PER_PT),
    "hp": ("DINNext_Medium", 36.0 * SLATE_PX_PER_PT),
    "ammo_mag": ("DINNext_Medium", 36.0 * SLATE_PX_PER_PT),
    "shield": ("DINNext_Medium", 14.0 * SLATE_PX_PER_PT),
    "ammo_reserve": ("DINNext_Regular", 16.0 * SLATE_PX_PER_PT),
}


def font_templates(keys, cuts=(COVER_CUT,)) -> ocr.Templates:
    """Every field in `keys` rendered at each coverage cut in `cuts`."""
    return templates_from([render_set(*FIELD_FONT[k], cut=c) for k in keys for c in cuts])


def read_row(frame, profile, w, h, tpl_line, tpl_bottom, tpl_fields=None):
    """The reader's own calls; `tpl_fields` maps a bottom sub-field to its
    own templates (per-field sets), else `tpl_bottom` serves them all."""
    r = ocr.read_scoreline(ocr.crop_gray(frame, ocr.scoreline_roi(profile), w, h), tpl_line,
                           0.82, 0.05)
    out = {"clock_ms": r.clock_ms, "score_left": r.score_left, "score_right": r.score_right,
           "clock_reason": r.clock_reason}
    if tpl_fields is None:
        b = ocr.read_bottom_hud(frame, profile, tpl_bottom, w, h, 0.82, 0.05)
        out.update(hp=b.hp, shield=b.shield, ammo_mag=b.ammo_mag, ammo_reserve=b.ammo_reserve)
    else:
        by_name = {r_.name: r_ for r_ in profile.rois}
        for roi_name, fields in ocr.BOTTOM_FIELDS.items():
            g = ocr.crop_gray(frame, by_name[roi_name], w, h)
            for spec in fields:
                vals, _occ, _c = ocr.read_subfields(g, [spec], tpl_fields[spec.name], 0.82, 0.05)
                out[spec.name] = vals[spec.name]
    return out


VALUE_FIELDS = ("clock_ms", "score_left", "score_right", "hp", "shield", "ammo_mag", "ammo_reserve")


def clock_consistent(t_ms: np.ndarray, clock_ms: list, win_s: float = 5.0) -> np.ndarray:
    """1 where a clock read agrees with a 1 s per s countdown: at least two
    other reads of the same reader within `win_s` give t + clock within 1.5 s;
    0 where it disagrees; -1 where the clock is null."""
    k = np.array([np.nan if c is None else t / 1000.0 + c / 1000.0 for t, c in zip(t_ms, clock_ms)])
    t = np.asarray(t_ms) / 1000.0
    out = np.full(len(k), -1, int)
    for i in np.where(~np.isnan(k))[0]:
        lo, hi = np.searchsorted(t, t[i] - win_s), np.searchsorted(t, t[i] + win_s)
        near = k[lo:hi]
        near = near[~np.isnan(near)]
        out[i] = int((np.abs(near - k[i]) <= 1.5).sum() - 1 >= 2)
    return out


def neighbour_agree(vals: list) -> np.ndarray:
    """1 where a read equals the nearest non-null read before or after it, 0
    where it equals neither, -1 where null or isolated."""
    out = np.full(len(vals), -1, int)
    idx = [i for i, v in enumerate(vals) if v is not None]
    for j, i in enumerate(idx):
        nb = [vals[idx[j - 1]]] if j > 0 else []
        nb += [vals[idx[j + 1]]] if j + 1 < len(idx) else []
        if nb:
            out[i] = int(vals[i] in nb)
    return out


def riot_score_pairs(sid: str):
    """Every (ally rounds, enemy rounds) the scoreline can show by Riot's
    round results: (0, 0) and the score after each round. None without a
    record."""
    sys.path.insert(0, str(ROOT / "prototypes"))
    import riot_ground_truth as rgt
    root = store_root()
    recs = rgt.riot_records(root)
    if sid not in recs:
        return None
    d = recs[sid]
    ref = rgt.Reference(root / "external" / "valorant-api", fetch=False)
    ident = rgt.resolve_lineup_player(d, rgt.identify_player(recs, root)[sid], ref)
    who = {p["subject"]: p for p in d["match"]["players"]}
    if ident.get("subject") not in who:
        return None
    mine = who[ident["subject"]]["teamId"]
    a = e = 0
    out = {(0, 0)}
    for r in sorted(d["match"]["roundResults"], key=lambda r: r["roundNum"]):
        if r["winningTeam"] == mine:
            a += 1
        else:
            e += 1
        out.add((a, e))
    return out


def compare(args) -> dict:
    """Every stored HUD row the crop cache holds, reread with the mined set
    (it must equal storage) and with the rendered sets."""
    cuts = tuple(args.cuts)
    if args.production:
        # The reader's own per-field sets (`ocr.game_font_templates`).
        prod = ocr.game_font_templates()
        sets = {"production": (prod, prod, None)}
    else:
        union = font_templates(FIELD_FONT, cuts)
        sets = {
            "union": (union, union, None),
            "per_field": (font_templates(("clock", "score"), cuts), None,
                          {k: font_templates((k,), cuts)
                           for k in ("hp", "ammo_mag", "shield", "ammo_reserve")}),
        }
    for name, (tl, tb, tf) in sets.items():
        print(f"{name}: " + (", ".join(f"{k} {len(v)}" for k, v in tl.by_field.items())
                             if isinstance(tl, ocr.FieldTemplates) else
                             f"{len(tl)} scoreline templates"
                             + (f", {len(tb)} bottom" if tb is not None else
                                ", " + ", ".join(f"{k} {len(v)}" for k, v in tf.items()))))
    report = {}
    outdir = Path(args.out) if args.out else None
    for sid in args.sessions:
        store, man, profile, hud, cache = _session(sid)
        w, h = int(man["source"]["width"]), int(man["source"]["height"])
        mined = ocr.Templates.load(profile.name)
        if args.production:
            # As `HudReader` builds it: fields without a font read the mined set.
            prod = ocr.game_font_templates(default=mined)
            sets["production"] = (prod, prod, None)
        held = set(cache.holds())
        t_all = [float(x) for x in hud["t_ms"]]
        rows_i = [i for i, x in enumerate(t_all) if x in held]
        if args.limit:
            rows_i = rows_i[:: max(1, len(rows_i) // args.limit)]
        times = [t_all[i] for i in rows_i]
        reads = {"mined": [], **{k: [] for k in sets}}
        for smp in cache.samples(times, rois=("scoreline", "hud_hp", "hud_ammo")):
            reads["mined"].append(read_row(smp.frame, profile, w, h, mined, mined))
            for k, (tl, tb, tf) in sets.items():
                reads[k].append(read_row(smp.frame, profile, w, h, tl, tb, tf))
        stored = [{f: hud[f][i] for f in VALUE_FIELDS} for i in rows_i]
        sanity = sum(any(m[f] != s[f] for f in VALUE_FIELDS) for m, s in zip(reads["mined"], stored))
        rep = {"rows": len(rows_i), "mined_rows_differing_from_storage": sanity}
        t = np.array(times)
        for k in ("mined", *sets):
            rr = reads[k]
            fr = {}
            for f in VALUE_FIELDS:
                new = [r[f] for r in rr]
                old = [s[f] for s in stored]
                d = {"read": sum(v is not None for v in new),
                     "same": sum(a == b and a is not None for a, b in zip(new, old)),
                     "gained": sum(a is not None and b is None for a, b in zip(new, old)),
                     "lost": sum(a is None and b is not None for a, b in zip(new, old)),
                     "changed": sum(a is not None and b is not None and a != b for a, b in zip(new, old))}
                if f == "clock_ms":
                    cc = clock_consistent(t, new)
                    d["consistent"], d["inconsistent"] = int((cc == 1).sum()), int((cc == 0).sum())
                else:
                    na = neighbour_agree(new)
                    d["neighbour_agree"], d["neighbour_disagree"] = int((na == 1).sum()), int((na == 0).sum())
                fr[f] = d
            pairs = riot_score_pairs(sid)
            if pairs is not None:
                both = [(r["score_left"], r["score_right"]) for r in rr
                        if r["score_left"] is not None and r["score_right"] is not None]
                fr["riot_score_pairs"] = {"read": len(both),
                                          "in_riot": sum(p in pairs for p in both),
                                          "not_in_riot": sum(p not in pairs for p in both)}
            rep[k] = fr
        report[sid] = rep
        print(f"\n{sid} ({man['source']['path']}): {len(rows_i)} rows; mined set differs from "
              f"storage on {sanity}")
        for f in VALUE_FIELDS:
            line = f"  {f:13s}"
            for k in ("mined", *sets):
                d = rep[k][f]
                ext = (f"cons {d['consistent']}/incons {d['inconsistent']}" if f == "clock_ms"
                       else f"nb {d['neighbour_agree']}/{d['neighbour_disagree']}")
                line += (f" | {k}: read {d['read']} same {d['same']} +{d['gained']} -{d['lost']} "
                         f"~{d['changed']} {ext}")
            print(line)
        for k in ("mined", *sets):
            if "riot_score_pairs" in rep[k]:
                print(f"  riot score pairs {k}: {rep[k]['riot_score_pairs']}")
        if outdir is not None:
            outdir.mkdir(parents=True, exist_ok=True)
            diffs = []
            nb = {(k, f): (clock_consistent(t, [r[f] for r in reads[k]]) if f == "clock_ms"
                           else neighbour_agree([r[f] for r in reads[k]]))
                  for k in sets for f in VALUE_FIELDS}
            for j, i in enumerate(rows_i):
                for k in sets:
                    for f in VALUE_FIELDS:
                        if reads[k][j][f] != stored[j][f]:
                            diffs.append({"set": k, "t_ms": times[j], "field": f,
                                          "stored": stored[j][f], "font": reads[k][j][f],
                                          "agrees": int(nb[(k, f)][j])})
            (outdir / f"diffs-{sid}.jsonl").write_text(
                "".join(json.dumps(x) + "\n" for x in diffs))
    if outdir is not None:
        (outdir / "compare.json").write_text(json.dumps(report, indent=1))
    return report


# --------------------------------------------------------------------------- scoreboard

#: The scoreboard player card's kills, deaths, assists and credits text:
#: face Medium at 11 pt (scoreboardPlayerCardAllyExtended3.json).
SCOREBOARD_FONT = ("DINNext_Medium", 11.0 * SLATE_PX_PER_PT)


def scoreboard_trial(sid: str, tpl, glyph_log=None, envelope=None) -> dict:
    """`trial.run` of the scoreboard reader from the crop cache with `tpl` in
    place of the mined set (None keeps it); `glyph_log`, a list, collects
    (digit, h, w, bitmap) of every accepted cell; `envelope` (min_h, max_h)
    replaces the cell digit height band."""
    from reticle import scoreboard, trial
    from reticle.store import Store
    store = Store()
    man = store.read_manifest(sid)
    orig_load, orig_cell = scoreboard.Templates.load, scoreboard._read_cell_detail
    orig_env = scoreboard.D_MIN_H, scoreboard.D_MAX_H
    if envelope is not None:
        scoreboard.D_MIN_H, scoreboard.D_MAX_H = envelope
    if tpl is not None:
        scoreboard.Templates.load = classmethod(lambda cls, name: tpl)
    if glyph_log is not None:
        def cell(gray, templates, min_conf, min_margin, maximum):
            got = orig_cell(gray, templates, min_conf, min_margin, maximum)
            if got[0] is not None:
                binary, raw = ocr._raw_components(gray)
                keep = sorted((x, y, w, h) for x, y, w, h, a in raw
                              if scoreboard.D_MIN_H <= h <= scoreboard.D_MAX_H
                              and w <= scoreboard.D_MAX_W and a >= scoreboard.D_MIN_AREA)
                txt = str(got[0])
                if len(txt) == len(keep):
                    for ch, (x, y, w, h) in zip(txt, keep):
                        glyph_log.append((ch, h, w, ocr.normalise(binary[y:y + h, x:x + w])))
            return got
        scoreboard._read_cell_detail = cell
    try:
        return trial.run(store, man, reader="scoreboard", source="cache", windows="all")
    finally:
        scoreboard.Templates.load, scoreboard._read_cell_detail = orig_load, orig_cell
        scoreboard.D_MIN_H, scoreboard.D_MAX_H = orig_env


SB_FIELDS = ("kills", "deaths", "assists", "credits")


def riot_trajectories(sid: str):
    """Riot's per-player (kills, deaths, assists) after each kill event, keyed
    by (side, canonical agent), and each player's possible credits: every
    round's `remaining` and `remaining + spent` (`playerEconomies`). Side is
    'ally' for the capturing player's team. None where no record exists."""
    sys.path.insert(0, str(ROOT / "prototypes"))
    import riot_ground_truth as rgt
    root = store_root()
    recs = rgt.riot_records(root)
    if sid not in recs:
        return None
    d = recs[sid]
    ref = rgt.Reference(root / "external" / "valorant-api", fetch=False)
    ident = rgt.resolve_lineup_player(d, rgt.identify_player(recs, root)[sid], ref)
    m = d["match"]
    who = {p["subject"]: p for p in m["players"]}
    me = ident.get("subject")
    if me not in who:
        return None
    my_team = who[me]["teamId"]
    key = {s: ("ally" if p["teamId"] == my_team else "enemy", rgt.canon(ref.agent(p["characterId"])))
           for s, p in who.items()}
    kda = {s: [0, 0, 0] for s in who}
    traj = {s: {(0, 0, 0)} for s in who}
    for k in sorted(m["kills"], key=lambda k: k["gameTime"]):
        if k.get("killer") in kda:
            kda[k["killer"]][0] += 1
        if k.get("victim") in kda:
            kda[k["victim"]][1] += 1
        for a in k.get("assistants") or []:
            if a in kda:
                kda[a][2] += 1
        for s in who:
            traj[s].add(tuple(kda[s]))
    credits = {s: set() for s in who}
    for r in m["roundResults"]:
        for e in r.get("playerEconomies") or []:
            if e["subject"] in credits:
                credits[e["subject"]] |= {e["remaining"], e["remaining"] + e["spent"]}
    out = defaultdict(lambda: {"traj": set(), "credits": set(), "n": 0})
    for s in who:
        o = out[key[s]]
        o["traj"] |= traj[s]
        o["credits"] |= credits[s]
        o["n"] += 1
    side = defaultdict(lambda: {"traj": set(), "credits": set()})
    for (sd, _a), o in list(out.items()):
        side[sd]["traj"] |= o["traj"]
        side[sd]["credits"] |= o["credits"]
    return dict(out), dict(side), {"me": me, "basis": ident.get("basis")}


def riot_row_verdict(row: dict, riot) -> dict:
    """Whether a row's read K/D/A lies on its player's Riot trajectory (the
    player named by the row's side and portrait agent; the side's union where
    the portrait names none), and its credits among the player's round
    credits. Each verdict is True, False or None (nothing read)."""
    import riot_ground_truth as rgt
    by_agent, by_side, _meta = riot
    sd = row.get("team")
    agent = row.get("portrait_agent_best")
    p = by_agent.get((sd, rgt.canon(agent))) if agent else None
    pool = p if p is not None else by_side.get(sd, {"traj": set(), "credits": set()})
    got = [(i, row.get(f)) for i, f in enumerate(("kills", "deaths", "assists"))]
    got = [(i, v) for i, v in got if v is not None]
    kda = None if not got else any(all(t[i] == v for i, v in got) for t in pool["traj"])
    # A cell above the player's (else the side's) final count plus one is a
    # misread whatever Riot's kill order: robust to trades and assist rules.
    top = [max(t[i] for t in pool["traj"]) for i in range(3)] if pool["traj"] else [0, 0, 0]
    impossible = sum(v > top[i] + 1 for i, v in got)
    cr = None if row.get("credits") is None else row["credits"] in pool["credits"]
    return {"kda": kda, "credits": cr, "named": p is not None, "impossible": impossible}


def scoreboard_compare(args) -> dict:
    cuts = tuple(args.cuts)
    sets = {}
    for pt in args.pts:
        tpl = templates_from([render_set(SCOREBOARD_FONT[0], pt * SLATE_PX_PER_PT, cut=c)
                              for c in cuts])
        sets[f"pt{pt:g}"] = (tpl, None)
        if args.envelope:
            sets[f"pt{pt:g}-h{args.envelope[0]}-{args.envelope[1]}"] = (tpl, tuple(args.envelope))
    report = {}
    outdir = Path(args.out) if args.out else None
    for sid in args.sessions:
        glyphs: list = []
        base = scoreboard_trial(sid, None, glyphs if args.census else None)
        rows0 = {r["observation_key"]: r for r in base["rows"]["scoreboard"]
                 if r.get("kind") == "row_observation"}
        rep = {"rows": len(rows0), "baseline_diff": base["diff"]["scoreboard"]["only_trial"]}
        if args.census and glyphs:
            hs = np.array([g_[1] for g_ in glyphs])
            print(f"{sid}: {len(glyphs)} scoreboard glyphs, h median {np.median(hs):.0f}")
            fits = []
            for face in ("DINNext_Regular", "DINNext_Medium", "DINNext_Bold", "Tungsten-Bold"):
                for em in np.arange(11.0, 19.01, 0.5):
                    rs = render_set(face, em, phases=2)
                    mads = []
                    for ch, _h, _w, bm in glyphs[:: max(1, len(glyphs) // 400)]:
                        tm = np.array([b for b, _hh, _ww in rs.get(ch, [])])
                        if len(tm):
                            mads.append(np.abs(tm - bm).reshape(len(tm), -1).mean(axis=1).min())
                    fits.append((float(np.mean(mads)), face, float(em)))
            fits.sort()
            best = {}
            for m, face, em in fits:
                best.setdefault(face, (m, em))
            for face, (m, em) in sorted(best.items(), key=lambda kv: kv[1][0]):
                print(f"   {face:18s} em {em:5.1f} px  mad {m:.4f}")
            rep["census"] = {f: {"mad": m, "em_px": em} for f, (m, em) in best.items()}
        for k, (tpl, env) in sets.items():
            res = scoreboard_trial(sid, tpl, envelope=env)
            rows1 = {r["observation_key"]: r for r in res["rows"]["scoreboard"]
                     if r.get("kind") == "row_observation"}
            fr = {}
            changed = []
            for f in SB_FIELDS:
                a = [rows1.get(key, {}).get(f) for key in rows0]
                b = [rows0[key].get(f) for key in rows0]
                fr[f] = {"read": sum(v is not None for v in a),
                         "same": sum(x == y and x is not None for x, y in zip(a, b)),
                         "gained": sum(x is not None and y is None for x, y in zip(a, b)),
                         "lost": sum(x is None and y is not None for x, y in zip(a, b)),
                         "changed": sum(x is not None and y is not None and x != y
                                        for x, y in zip(a, b))}
                changed += [{"key": key, "t_ms": rows0[key]["t_ms"],
                             "row": rows0[key]["display_row"], "field": f,
                             "stored": y, "font": x}
                            for key, x, y in zip(rows0, a, b) if x != y]
            rep[k] = fr
            rep[k + "_rows_missing"] = len(set(rows0) - set(rows1))
            riot = riot_trajectories(sid)
            if riot is not None:
                for name, rows in (("mined", rows0), (k, rows1)):
                    v = [riot_row_verdict(r, riot) for r in rows.values()]
                    rep[f"riot_{name}"] = {
                        "kda_on_trajectory": sum(x["kda"] is True for x in v),
                        "kda_off_trajectory": sum(x["kda"] is False for x in v),
                        "credits_in_round_set": sum(x["credits"] is True for x in v),
                        "credits_outside": sum(x["credits"] is False for x in v),
                        "rows_named": sum(x["named"] for x in v),
                        "impossible_cells": sum(x["impossible"] for x in v)}
                    print(f"  riot {name}: {rep[f'riot_{name}']}")
                # Each changed or gained cell with its Riot verdict.
                for c in changed:
                    r1 = rows1.get(c["key"])
                    c["riot_font"] = None if r1 is None else riot_row_verdict(r1, riot)
                    c["riot_mined"] = riot_row_verdict(rows0[c["key"]], riot)
            if outdir is not None:
                outdir.mkdir(parents=True, exist_ok=True)
                (outdir / f"scoreboard-diffs-{k}-{sid}.jsonl").write_text(
                    "".join(json.dumps(x) + "\n" for x in changed))
        report[sid] = rep
        print(f"{sid}: {len(rows0)} rows; baseline differs from storage on {rep['baseline_diff']}")
        for f in SB_FIELDS:
            print(f"  {f:8s} " + " | ".join(
                f"{k}: read {rep[k][f]['read']} same {rep[k][f]['same']} +{rep[k][f]['gained']} "
                f"-{rep[k][f]['lost']} ~{rep[k][f]['changed']}" for k in sets))
    if outdir is not None:
        (outdir / "scoreboard-compare.json").write_text(json.dumps(report, indent=1))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("census")
    c.add_argument("--n", type=int, default=120)
    c.add_argument("--out", default=None)
    c = sub.add_parser("compare")
    c.add_argument("--sessions", nargs="+", default=list(SESSIONS))
    c.add_argument("--limit", type=int, default=0, help="rows per session (0: all)")
    c.add_argument("--production", action="store_true",
                   help="compare the reader's own sets (ocr.game_font_templates) only")
    c.add_argument("--cuts", type=float, nargs="+", default=[COVER_CUT],
                   help="coverage cuts each glyph is rendered at")
    c.add_argument("--out", default=None)
    c = sub.add_parser("scoreboard")
    c.add_argument("--sessions", nargs="+", default=list(SESSIONS))
    c.add_argument("--cuts", type=float, nargs="+", default=[0.4, 0.55, 0.7, 0.85])
    c.add_argument("--census", action="store_true")
    c.add_argument("--envelope", type=int, nargs=2, default=None,
                   help="also run each size with this cell digit height band")
    c.add_argument("--pts", type=float, nargs="+", default=[11.0],
                   help="point sizes to render the scoreboard digits at")
    c.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if args.cmd == "scoreboard":
        scoreboard_compare(args)
    if args.cmd == "census":
        font_census(args)
    elif args.cmd == "compare":
        compare(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
