"""Mine, cluster, and catalog killfeed divider and scoreboard loadout icons.

Extracts divider icons from counted killfeed tracks across recorded sessions,
matches against official ability assets, clusters recurring weapon silhouettes,
and exports contact sheets and a JSON catalog for review and ground-truth labelling.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

import cv2
import duckdb
import numpy as np

# Ensure reticle is on path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reticle.adjudication.weapon import (
    ABILITY_CANONICAL_NAMES,
    classify_killfeed_icon,
    estimate_weapon_class,
    extract_icon_observation,
    load_ability_gallery,
)
from reticle.checks import track_entries
from reticle.killfeed import analyse_killfeed, killfeed_roi
from reticle.profiles import get_profile
from reticle.store import Store


def load_session_manifest(session_id: str, store_root: Path) -> dict:
    manifest_path = store_root / "manifests" / f"{session_id}.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_killfeed_icons(
    session_id: str,
    store_root: Path,
    cap: cv2.VideoCapture,
    max_tracks: int = 200,
) -> list[dict[str, Any]]:
    """Extract divider icon observations from all counted killfeed tracks."""
    manifest = load_session_manifest(session_id, store_root)
    profile_name = manifest.get("source_profile", "valorant-16x9")
    profile = get_profile(profile_name)
    roi = killfeed_roi(profile)
    if roi is None:
        return []

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    rx0, ry0, rx1, ry1 = roi.pixels(w, h)

    hud_parquet = store_root / "l1" / "hud" / f"date={manifest['ingested_at'][:10]}" / f"session={session_id}" / "hud.parquet"
    if not hud_parquet.is_file():
        # Search anywhere in l1/hud
        matches = list((store_root / "l1" / "hud").glob(f"*/session={session_id}/hud.parquet"))
        if not matches:
            print(f"[{session_id}] No hud.parquet found")
            return []
        hud_parquet = matches[0]

    con = duckdb.connect()
    df = con.execute(f"""
        SELECT t_ms, kf_entry_mask, kf_entry_wx
        FROM read_parquet('{hud_parquet.as_posix()}')
        ORDER BY t_ms
    """).fetchall()

    t = [r[0] for r in df]
    mask = [r[1] for r in df]
    wx = [r[2] for r in df]

    tracks = [tr for tr in track_entries(t, mask, wx) if tr.get("counted", False)]
    print(f"[{session_id}] Found {len(tracks)} counted tracks in {hud_parquet.name}")

    gallery = load_ability_gallery(store_root / "reference" / "assets" / "abilities")
    records: list[dict[str, Any]] = []

    for idx, tr in enumerate(tracks[:max_tracks]):
        t_sample_ms = tr["t_first"] + 1200.0  # Sample 1.2s in when entry is stable
        cap.set(cv2.CAP_PROP_POS_MSEC, t_sample_ms)
        ret, frame = cap.read()
        if not ret:
            continue

        views = analyse_killfeed(frame, roi, w, h, profile_name=profile.name)
        matching = [v for v in views if v.slot == tr["slot"] and v.wx0 is not None and v.wx1 is not None]
        if not matching:
            continue
        v = matching[0]
        if v.wx1 <= v.wx0 or v.y1 <= v.y0:
            continue

        crop = frame[ry0 + v.y0:ry0 + v.y1, rx0 + v.wx0:rx0 + v.wx1]
        if crop.size == 0 or crop.shape[0] < 5 or crop.shape[1] < 5:
            continue

        obs = extract_icon_observation(crop)
        verdict = classify_killfeed_icon(obs, gallery=gallery)

        # Extract tight foreground bounding box
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        white = (hsv[:, :, 2] > 170) & (hsv[:, :, 1] < 55)
        ys, xs = np.where(white)
        if len(ys) > 10:
            y_min, y_max = int(ys.min()), int(ys.max())
            x_min, x_max = int(xs.min()), int(xs.max())
            tight_crop = crop[y_min:y_max+1, x_min:x_max+1]
            tight_mask = white[y_min:y_max+1, x_min:x_max+1]
        else:
            tight_crop = crop
            tight_mask = white

        records.append({
            "session_id": session_id,
            "track_idx": idx,
            "t_ms": t_sample_ms,
            "t_s": round(t_sample_ms / 1000.0, 2),
            "slot": v.slot,
            "raw_crop": crop,
            "tight_crop": tight_crop,
            "tight_mask": tight_mask,
            "width": obs.width,
            "height": obs.height,
            "tight_width": tight_crop.shape[1],
            "tight_height": tight_crop.shape[0],
            "aspect_ratio": round(obs.aspect_ratio, 2),
            "tight_aspect": round(tight_crop.shape[1] / max(1, tight_crop.shape[0]), 2),
            "fill_ratio": round(obs.fill_ratio, 3),
            "verdict": verdict.to_dict(),
            "source": "killfeed",
        })

    return records


def extract_scoreboard_icons(
    session_id: str,
    store_root: Path,
    cap: cv2.VideoCapture,
    max_frames: int = 15,
) -> list[dict[str, Any]]:
    """Extract clean loadout weapon silhouettes from Scoreboard (Tab) frames."""
    sb_path = store_root / "events" / "scoreboard" / f"{session_id}.jsonl"
    if not sb_path.is_file():
        return []

    # Read unique frame timestamps where scoreboard was open
    frames_open = set()
    rows_by_frame: dict[int, list[dict]] = {}
    with open(sb_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            if data.get("kind") == "row_observation":
                f_idx = data["frame_idx"]
                frames_open.add(f_idx)
                rows_by_frame.setdefault(f_idx, []).append(data)

    sorted_frames = sorted(frames_open)
    # Stride across session
    step = max(1, len(sorted_frames) // max_frames)
    sampled_frames = sorted_frames[::step][:max_frames]

    records: list[dict[str, Any]] = []

    for f_idx in sampled_frames:
        row_obs = rows_by_frame[f_idx]
        if not row_obs:
            continue
        t_ms = row_obs[0]["t_ms"]
        cap.set(cv2.CAP_PROP_POS_MSEC, t_ms)
        ret, frame = cap.read()
        if not ret:
            continue

        for r_data in row_obs:
            team = r_data.get("team")
            table_x0 = r_data.get("table_x0")
            table_x1 = r_data.get("table_x1")
            row_y0 = r_data.get("row_y0")
            row_y1 = r_data.get("row_y1")
            if None in (table_x0, table_x1, row_y0, row_y1):
                continue

            table_w = table_x1 - table_x0
            # Loadout weapon sits at x: 0.63..0.76 of table width
            lx0 = int(table_x0 + 0.63 * table_w)
            lx1 = int(table_x0 + 0.77 * table_w)
            loadout_crop = frame[row_y0:row_y1, lx0:lx1]
            if loadout_crop.size == 0:
                continue

            # Find bright weapon pixels (excluding right shield area)
            gray = cv2.cvtColor(loadout_crop, cv2.COLOR_BGR2GRAY)
            bright = gray > 130
            if np.sum(bright) < 40:
                continue

            ys, xs = np.where(bright)
            # Guns sit on the left (x < 95 px inside loadout crop).
            # Shields sit on the right (x > 105 px).
            gun_mask_cols = xs < 95
            if not np.any(gun_mask_cols):
                continue
            gun_xs = xs[gun_mask_cols]
            gun_ys = ys[gun_mask_cols]

            if len(gun_xs) < 40:
                continue

            gx0, gx1 = int(gun_xs.min()), int(gun_xs.max())
            gy0, gy1 = int(gun_ys.min()), int(gun_ys.max())
            gw = gx1 - gx0 + 1
            gh = gy1 - gy0 + 1

            # Ignore horizontal dividers or thin lines (e.g. gh <= 4 or extreme aspect)
            if gh < 8 or gw < 16:
                continue
            aspect = round(gw / float(gh), 2)
            if aspect > 7.0 or aspect < 0.6:
                continue

            gun_crop = loadout_crop[gy0:gy1+1, gx0:gx1+1]
            gun_mask = bright[gy0:gy1+1, gx0:gx1+1]
            w_class = estimate_weapon_class(gw, aspect)

            records.append({
                "session_id": session_id,
                "track_idx": None,
                "t_ms": t_ms,
                "t_s": round(t_ms / 1000.0, 2),
                "slot": r_data.get("display_row"),
                "raw_crop": gun_crop,
                "tight_crop": gun_crop,
                "tight_mask": gun_mask,
                "width": gw,
                "height": gh,
                "tight_width": gw,
                "tight_height": gh,
                "aspect_ratio": aspect,
                "tight_aspect": aspect,
                "fill_ratio": round(float(np.sum(gun_mask)) / (gw * gh), 3),
                "verdict": {
                    "category": "gun",
                    "weapon_class": w_class,
                    "name": None,
                    "confidence": 0.5,
                },
                "source": "scoreboard",
            })

    print(f"[{session_id}] Mined {len(records)} weapon exemplars from scoreboard frames")
    return records


def exemplar_quality(crop: np.ndarray, mask: np.ndarray, fill: float) -> float:
    """Score exemplar quality: favors sharp edges and typical icon fill ratio (~0.30)."""
    if fill > 0.60 or fill < 0.10:
        return -1000.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    detail = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    fill_penalty = abs(fill - 0.28) * 150.0
    return detail - fill_penalty


def cluster_icons(icons: list[dict[str, Any]], match_threshold: float = 0.65) -> list[dict[str, Any]]:
    """Cluster extracted icons by aspect ratio and correlation distance."""
    clusters: list[dict[str, Any]] = []

    for item in icons:
        crop = item["tight_crop"]
        mask = item["tight_mask"].astype(np.float32)
        h, w = mask.shape
        aspect = item["tight_aspect"]
        quality = exemplar_quality(crop, mask, item["fill_ratio"])

        best_cluster = None
        best_sim = 0.0

        # If item has a resolved canonical name, match cluster with same name directly
        item_name = item["verdict"].get("name")
        if item_name:
            for c in clusters:
                if c.get("suggested_name") == item_name:
                    best_cluster = c
                    break

        if best_cluster is None:
            for c in clusters:
                # If existing cluster has a different resolved name, don't mix
                if c.get("suggested_name") and item_name and c["suggested_name"] != item_name:
                    continue

                # Aspect ratio gate
                if abs(c["aspect"] - aspect) > 0.40:
                    continue

                # Normalized correlation with exemplar
                ex_mask = c["exemplar_mask"]
                eh, ew = ex_mask.shape
                # Resize mask to exemplar shape
                resized_mask = cv2.resize(mask, (ew, eh))
                res = cv2.matchTemplate(ex_mask, resized_mask, cv2.TM_CCOEFF_NORMED)
                score = float(res[0, 0]) if not math.isnan(res[0, 0]) else 0.0

                if score > match_threshold and score > best_sim:
                    best_sim = score
                    best_cluster = c

        if best_cluster is not None:
            best_cluster["members"].append(item)
            best_cluster["count"] += 1
            if item["verdict"].get("name") and not best_cluster.get("suggested_name"):
                best_cluster["suggested_name"] = item["verdict"]["name"]
                best_cluster["category"] = item["verdict"]["category"]
                best_cluster["weapon_class"] = item["verdict"]["weapon_class"]
            # Update exemplar if this one has higher quality
            if quality > best_cluster.get("exemplar_quality", -999.0):
                best_cluster["exemplar_crop"] = crop
                best_cluster["exemplar_mask"] = mask
                best_cluster["exemplar_quality"] = quality
                best_cluster["fill_ratio"] = item["fill_ratio"]
                best_cluster["width"] = w
                best_cluster["height"] = h
                best_cluster["aspect"] = aspect
        else:
            clusters.append({
                "cluster_id": len(clusters),
                "aspect": aspect,
                "width": w,
                "height": h,
                "fill_ratio": item["fill_ratio"],
                "exemplar_crop": crop,
                "exemplar_mask": mask,
                "exemplar_quality": quality,
                "count": 1,
                "category": item["verdict"]["category"],
                "weapon_class": item["verdict"]["weapon_class"],
                "suggested_name": item["verdict"]["name"],
                "members": [item],
            })

    clusters.sort(key=lambda c: c["count"], reverse=True)
    for idx, c in enumerate(clusters):
        c["cluster_id"] = idx
    return clusters


def build_contact_sheet(
    clusters: list[dict[str, Any]],
    output_path: Path,
    title: str = "Icon Catalog",
) -> None:
    """Render a visual contact sheet of clustered exemplars with metadata."""
    if not clusters:
        return

    cell_w = 240
    cell_h = 100
    cols = 4
    rows = int(math.ceil(len(clusters) / cols))

    sheet_w = cols * cell_w + 40
    sheet_h = rows * cell_h + 80
    sheet = np.zeros((sheet_h, sheet_w, 3), dtype=np.uint8)
    sheet[:] = (26, 26, 30)  # Dark slate background

    # Header title
    cv2.putText(sheet, title, (25, 45), cv2.FONT_HERSHEY_DUPLEX, 0.9, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(sheet, f"Total clusters: {len(clusters)}", (sheet_w - 220, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1, cv2.LINE_AA)

    for idx, c in enumerate(clusters):
        grid_x = idx % cols
        grid_y = idx // cols
        x0 = 20 + grid_x * cell_w
        y0 = 70 + grid_y * cell_h

        # Cell border box
        cv2.rectangle(sheet, (x0, y0), (x0 + cell_w - 8, y0 + cell_h - 8), (45, 45, 50), 1)

        # Place exemplar crop
        crop = c["exemplar_crop"]
        ch, cw = crop.shape[:2]
        # Scale crop to fit inside 90x60
        scale = min(90.0 / max(1, cw), 55.0 / max(1, ch), 2.5)
        new_w = max(1, int(round(cw * scale)))
        new_h = max(1, int(round(ch * scale)))
        scaled_crop = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

        # Center crop in left half of cell
        cx = x0 + 10 + (90 - new_w) // 2
        cy = y0 + 10 + (55 - new_h) // 2
        sheet[cy:cy+new_h, cx:cx+new_w] = scaled_crop

        # Metadata text on right half
        tx = x0 + 110
        label = c["suggested_name"] or f"Class: {c['weapon_class']}"
        cv2.putText(sheet, f"#{c['cluster_id']}: {label}", (tx, y0 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1, cv2.LINE_AA)
        cv2.putText(sheet, f"n={c['count']} | ar={c['aspect']:.2f}", (tx, y0 + 45), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (160, 160, 160), 1, cv2.LINE_AA)
        cv2.putText(sheet, f"{c['width']}x{c['height']} px", (tx, y0 + 65), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (130, 130, 130), 1, cv2.LINE_AA)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), sheet)
    print(f"Contact sheet saved to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mine weapon and ability icons from video sessions.")
    parser.add_argument(
        "--sessions",
        type=str,
        default="a06f04a0059f,59c70f1ef720,ff636d173b07",
        help="Comma-separated session IDs to scan",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "scratch" / "mined_icons",
        help="Directory to save mined crops, contact sheets, and json",
    )
    parser.add_argument(
        "--max-tracks",
        type=int,
        default=120,
        help="Maximum killfeed tracks to sample per session",
    )
    args = parser.parse_args()

    store_root = Store().root
    sessions = [s.strip() for s in args.sessions.split(",") if s.strip()]
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    all_icons: list[dict[str, Any]] = []

    for sid in sessions:
        manifest_path = store_root / "manifests" / f"{sid}.json"
        if not manifest_path.is_file():
            print(f"Manifest not found for {sid}, skipping")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        video_path = Path(manifest["source"]["path"])
        if not video_path.is_file():
            print(f"Video file not found at {video_path}, skipping {sid}")
            continue

        cap = cv2.VideoCapture(str(video_path))
        print(f"\n================ Mining {sid} ================")
        kf_icons = extract_killfeed_icons(sid, store_root, cap, max_tracks=args.max_tracks)
        sb_icons = extract_scoreboard_icons(sid, store_root, cap)
        cap.release()

        session_icons = kf_icons + sb_icons
        all_icons.extend(session_icons)

        # Per-session clusters and contact sheet
        sess_clusters = cluster_icons(session_icons)
        build_contact_sheet(
            sess_clusters,
            out_dir / f"contact_sheet_{sid}.png",
            title=f"Icon Catalog: {sid} ({manifest.get('tags', [''])[0]})",
        )

    print(f"\n================ Overall Summary ================")
    print(f"Total icons mined across {len(sessions)} sessions: {len(all_icons)}")
    all_clusters = cluster_icons(all_icons)
    print(f"Clustered into {len(all_clusters)} unique icon classes")

    # Save overall contact sheet
    build_contact_sheet(
        all_clusters,
        out_dir / "contact_sheet_all_sessions.png",
        title="VALORANT Mined Weapon & Ability Icon Catalog",
    )

    # Save clean exemplar PNGs for top clusters
    exemplar_dir = out_dir / "exemplars"
    exemplar_dir.mkdir(parents=True, exist_ok=True)
    catalog_summary = []

    for c in all_clusters:
        label = c["suggested_name"] or f"{c['weapon_class']}_{c['cluster_id']}"
        safe_label = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in label)
        ex_filename = f"cluster_{c['cluster_id']:02d}_{safe_label}.png"
        cv2.imwrite(str(exemplar_dir / ex_filename), c["exemplar_crop"])

        catalog_summary.append({
            "cluster_id": c["cluster_id"],
            "label": label,
            "category": c["category"],
            "weapon_class": c["weapon_class"],
            "suggested_name": c["suggested_name"],
            "count": c["count"],
            "aspect_ratio": c["aspect"],
            "width": c["width"],
            "height": c["height"],
            "exemplar_file": ex_filename,
            "sample_sources": [
                {"session": m["session_id"], "t_s": m["t_s"], "source": m["source"]}
                for m in c["members"][:5]
            ],
        })

    json_path = out_dir / "icon_catalog.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(catalog_summary, f, indent=2)
    print(f"Saved catalog JSON to {json_path}")


if __name__ == "__main__":
    main()
