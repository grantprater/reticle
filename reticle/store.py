"""The event store (design doc SS7).

Layout on disk:

    <store>/manifests/<session_id>.json                          L0 pointer
    <store>/l1/primitives/date=<d>/session=<sid>/primitives.parquet
    <store>/l2/spans/date=<d>/session=<sid>/spans.parquet

Conventions carried from the design doc:
  * L0 raw media is never copied. The manifest records where it lives.
  * Wide and denormalised -- context columns sit inline on every row.
  * Append-only in spirit; a rewrite is a new version, never an edit.
  * Every row carries the versions and identity that produced it.
  * Stages are keyed by (content_key, code_version), so a re-run is a cache hit.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .version import (EXTRACTOR_VERSION, HUD_VERSION, MINIMAP_VERSION, ROSTER_VERSION, ROUND_VERSION,
                      SCHEMA_VERSION, SEGMENTER_VERSION)

DEFAULT_STORE = Path.home() / "reticle-store"


class Store:
    def __init__(self, root: str | Path = DEFAULT_STORE):
        self.root = Path(root).resolve()

    # ---------- paths ----------

    def manifest_path(self, session_id: str) -> Path:
        return self.root / "manifests" / f"{session_id}.json"

    def primitives_path(self, session_id: str, date: str) -> Path:
        return self.root / "l1" / "primitives" / f"date={date}" / f"session={session_id}" / "primitives.parquet"

    def rounds_path(self, session_id: str, date: str) -> Path:
        return self.root / "l2" / "rounds" / f"date={date}" / f"session={session_id}" / "rounds.parquet"

    def spans_path(self, session_id: str, date: str) -> Path:
        return self.root / "l2" / "spans" / f"date={date}" / f"session={session_id}" / "spans.parquet"

    def hud_path(self, session_id: str, date: str) -> Path:
        return self.root / "l1" / "hud" / f"date={date}" / f"session={session_id}" / "hud.parquet"

    def minimap_path(self, session_id: str, date: str) -> Path:
        return self.root / "l1" / "minimap" / f"date={date}" / f"session={session_id}" / "minimap.parquet"

    def roster_path(self, session_id: str, date: str) -> Path:
        return self.root / "l1" / "roster" / f"date={date}" / f"session={session_id}" / "roster.parquet"

    def primitives_glob(self) -> str:
        return str(self.root / "l1" / "primitives" / "**" / "*.parquet")

    def spans_glob(self) -> str:
        return str(self.root / "l2" / "spans" / "**" / "*.parquet")

    def hud_glob(self) -> str:
        return str(self.root / "l1" / "hud" / "**" / "*.parquet")

    def minimap_glob(self) -> str:
        return str(self.root / "l1" / "minimap" / "**" / "*.parquet")

    # ---------- manifests ----------

    def write_manifest(self, fingerprint, profile_name: str, extra: dict | None = None) -> Path:
        path = self.manifest_path(fingerprint.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "schema_version": SCHEMA_VERSION,
            "session_id": fingerprint.session_id,
            "source_profile": profile_name,
            "ingested_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "source": fingerprint.as_dict(),
        }
        if extra:
            doc.update(extra)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return path

    def read_manifest(self, session_id: str) -> dict:
        path = self.manifest_path(session_id)
        if not path.is_file():
            raise SystemExit(f"no manifest for session {session_id} in {self.root}")
        return json.loads(path.read_text(encoding="utf-8"))

    def sessions(self) -> list[dict]:
        d = self.root / "manifests"
        if not d.is_dir():
            return []
        out = []
        for p in sorted(d.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return out

    # ---------- L1 ----------

    def has_primitives(self, session_id: str, date: str) -> bool:
        path = self.primitives_path(session_id, date)
        if not path.is_file():
            return False
        try:
            meta = pq.read_schema(path).metadata or {}
            return meta.get(b"extractor_version", b"").decode() == EXTRACTOR_VERSION
        except Exception:
            return False

    def write_primitives(self, rows: list[dict], fingerprint, profile_name: str, date: str) -> Path:
        if not rows:
            raise SystemExit("no frames were decoded -- nothing to write")

        columns = {k: [r[k] for r in rows] for k in rows[0]}
        arrays: dict[str, pa.Array] = {}
        for name, values in columns.items():
            if name == "frame_idx":
                arrays[name] = pa.array(values, type=pa.int64())
            elif name.endswith("_dhash"):
                arrays[name] = pa.array(values, type=pa.uint64())
            elif name.endswith("_dchange"):
                arrays[name] = pa.array(values, type=pa.int16())
            else:
                arrays[name] = pa.array(values, type=pa.float64())

        n = len(rows)
        # Identity and version columns, inline on every row per SS7.
        arrays["session_id"] = pa.array([fingerprint.session_id] * n, type=pa.string())
        arrays["content_key"] = pa.array([fingerprint.content_key] * n, type=pa.string())
        arrays["source_profile"] = pa.array([profile_name] * n, type=pa.string())
        arrays["extractor_version"] = pa.array([EXTRACTOR_VERSION] * n, type=pa.string())
        arrays["schema_version"] = pa.array([SCHEMA_VERSION] * n, type=pa.int32())

        table = pa.table(arrays)
        table = table.replace_schema_metadata(
            {
                "extractor_version": EXTRACTOR_VERSION,
                "schema_version": str(SCHEMA_VERSION),
                "session_id": fingerprint.session_id,
                "content_key": fingerprint.content_key,
                "source_profile": profile_name,
            }
        )
        path = self.primitives_path(fingerprint.session_id, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
        return path

    def read_primitives(self, session_id: str, date: str) -> dict[str, np.ndarray]:
        path = self.primitives_path(session_id, date)
        if not path.is_file():
            raise SystemExit(
                f"no L1 primitives for session {session_id} -- run `reticle ingest` first"
            )
        table = pq.read_table(path)
        return {name: table.column(name).to_numpy(zero_copy_only=False) for name in table.column_names}

    # ---------- L1 · HUD reads (stage 02) ----------

    def has_hud(self, session_id: str, date: str) -> bool:
        path = self.hud_path(session_id, date)
        if not path.is_file():
            return False
        try:
            meta = pq.read_schema(path).metadata or {}
            return meta.get(b"hud_version", b"").decode() == HUD_VERSION
        except Exception:
            return False

    def write_hud(self, rows: list[dict], fingerprint, profile_name: str, date: str) -> Path:
        if not rows:
            raise SystemExit("no frames were read -- nothing to write")
        n = len(rows)
        col = lambda k: [r[k] for r in rows]
        arrays = {
            "frame_idx": pa.array(col("frame_idx"), type=pa.int64()),
            "t_ms": pa.array(col("t_ms"), type=pa.float64()),
            # Nullable on purpose: a field the extractor could not read stays
            # null rather than being guessed. Stage 05 needs to tell "unread"
            # from "read as zero".
            "clock_ms": pa.array(col("clock_ms"), type=pa.int32()),
            "score_left": pa.array(col("score_left"), type=pa.int16()),
            "score_right": pa.array(col("score_right"), type=pa.int16()),
            # WHY a field above is null, when it is. Six different guards in
            # `read_scoreline` return None and every one of them read
            # identically here -- so the clock read rate of 33-60% this stage
            # has reported since it was built said nothing at all about its
            # cause, and could not be acted on. `clock:no_glyphs` (nothing in
            # the field, e.g. the spike graphic standing where the digits go)
            # and `clock:low_confidence` (a clock that was there and could not
            # be matched) are opposite problems that looked the same.
            #
            # Dictionary-encoded: a handful of distinct short strings over
            # thousands of rows costs almost nothing, and it keeps the column
            # readable in `sql` without a join. Null means the field was READ,
            # which is the common case, so the column is mostly nulls by design.
            "clock_reason": pa.array(col("clock_reason"),
                                     type=pa.dictionary(pa.int8(), pa.string())),
            "score_left_reason": pa.array(col("score_left_reason"),
                                          type=pa.dictionary(pa.int8(), pa.string())),
            "score_right_reason": pa.array(col("score_right_reason"),
                                           type=pa.dictionary(pa.int8(), pa.string())),
            # Bottom HUD (stage 02). Ammunition is the load-bearing one: a
            # magazine count that falls between samples is a shot fired.
            "hp": pa.array(col("hp"), type=pa.int16()),
            "shield": pa.array(col("shield"), type=pa.int16()),
            "ammo_mag": pa.array(col("ammo_mag"), type=pa.int16()),
            "ammo_reserve": pa.array(col("ammo_reserve"), type=pa.int16()),
            "confidence": pa.array(col("confidence"), type=pa.float64()),
            "bottom_confidence": pa.array(col("bottom_confidence"), type=pa.float64()),
            # Killfeed (stage 02). Entry count plus whether the local player is
            # in one, and on which side -- the only source that confirms a death,
            # since the bottom HUD vanishes when the player dies.
            "kf_entries": pa.array(col("kf_entries"), type=pa.int16()),
            "kf_player_kill": pa.array(col("kf_player_kill"), type=pa.bool_()),
            "kf_player_death": pa.array(col("kf_player_death"), type=pa.bool_()),
            # Which stack positions the player's own entries occupy, as a
            # 6-bit mask. Needed to follow one entry across frames and so tell
            # a second kill from the same kill still on screen -- a bare flag
            # cannot. Absolute positions, not detection order.
            "kf_entry_mask": pa.array(col("kf_entry_mask"), type=pa.int16()),
            "kf_kill_mask": pa.array(col("kf_kill_mask"), type=pa.int16()),
            "kf_death_mask": pa.array(col("kf_death_mask"), type=pa.int16()),
            "kf_unattributed": pa.array(col("kf_unattributed"), type=pa.int16()),
            # The same idea for the killfeed: how many bands this frame held
            # that could not be parsed, and which guard refused the first of
            # them. `no_divider` is the ability-kill signature and was
            # indistinguishable from empty scenery until it was named.
            "kf_unparsed": pa.array(col("kf_unparsed"), type=pa.int16()),
            "kf_unparsed_reason": pa.array(col("kf_unparsed_reason"),
                                           type=pa.dictionary(pa.int8(), pa.string())),
            # Each entry's weapon-icon divider column, packed nine bits per
            # stack slot. An entry's divider does not move while it is on
            # screen, so this is what tells one entry from the next when both
            # occupy the same slot in turn -- the merge the masks above cannot
            # see. int64: six slots of nine bits. See killfeed.divider_of_ys.
            # Which team each entry's victim was on, as two slot masks. Every
            # killfeed entry is a death, so these give both teams' alive counts
            # -- the state a win-probability model is built on. A slot present
            # in kf_entry_mask but in neither could not be read.
            "kf_ally_mask": pa.array(col("kf_ally_mask"), type=pa.int16()),
            "kf_enemy_mask": pa.array(col("kf_enemy_mask"), type=pa.int16()),
            "kf_entry_wx": pa.array(col("kf_entry_wx"), type=pa.int64()),
            "kf_kill_wx": pa.array(col("kf_kill_wx"), type=pa.int64()),
            "kf_death_wx": pa.array(col("kf_death_wx"), type=pa.int64()),
            "n_glyphs": pa.array(col("n_glyphs"), type=pa.int16()),
            "session_id": pa.array([fingerprint.session_id] * n, type=pa.string()),
            "content_key": pa.array([fingerprint.content_key] * n, type=pa.string()),
            "source_profile": pa.array([profile_name] * n, type=pa.string()),
            "hud_version": pa.array([HUD_VERSION] * n, type=pa.string()),
            "schema_version": pa.array([SCHEMA_VERSION] * n, type=pa.int32()),
        }
        table = pa.table(arrays).replace_schema_metadata(
            {
                "hud_version": HUD_VERSION,
                "schema_version": str(SCHEMA_VERSION),
                "session_id": fingerprint.session_id,
                "content_key": fingerprint.content_key,
                "source_profile": profile_name,
            }
        )
        path = self.hud_path(fingerprint.session_id, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
        return path

    def static_map_path(self, session_id: str) -> Path:
        return self.root / "masks" / f"{session_id}.static.npy"

    def read_static_map(self, session_id: str):
        """The cached per-pixel median of the minimap widget, or None.

        The most expensive per-session constant in the pipeline: 120 `cap.set`
        seeks, three times the killfeed mask's 40, and EVERY minimap prototype
        rebuilds it from scratch -- `xmark_eval`, `chokepoint_eval`,
        `ping_scan`, `reader_census` and the shipped reader all pay it
        separately. Caching it is worth more than any decoder flag measured
        today (hardware acceleration was 8%, PyAV's frame skipping 25%).

        Keyed on session alone and NOT version-stamped, for the same reason as
        the killfeed mask: it is a property of the recording. If `static_map`
        or the minimap ROI changes, delete `<store>/masks/`.

        **One caveat that is real.** `static_map` takes its frames from ACTIVE
        SPANS, so a cache written before `segment` ran, or from different
        spans, is a different median. It is stable in practice because spans
        move only when the segmenter does, but a session whose spans changed
        should have its cache dropped -- which is why the file is a plain npy
        under `masks/` and not something clever.
        """
        p = self.static_map_path(session_id)
        return np.load(p) if p.is_file() else None

    def write_static_map(self, session_id: str, med) -> Path:
        p = self.static_map_path(session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        np.save(p, med)
        return p

    def kf_mask_path(self, session_id: str) -> Path:
        return self.root / "masks" / f"{session_id}.kf.npy"

    def read_kf_mask(self, session_id: str):
        """The cached killfeed overlay mask, or None.

        A per-session constant that costs 40 seeks over the whole file to
        derive -- 6.9 s on a 16 minute capture, measured, which is a tenth of
        the whole HUD stage and is paid again by every probe that needs it.
        Which optional HUD readouts the player has switched on cannot change
        within a capture, so caching it is not an approximation.

        Keyed on session alone and NOT version-stamped, deliberately: it is a
        property of the recording, not of any extractor. If `overlay_mask`
        itself changes, delete `<store>/masks/`.
        """
        p = self.kf_mask_path(session_id)
        return np.load(p) if p.is_file() else None

    def write_kf_mask(self, session_id: str, mask) -> Path:
        p = self.kf_mask_path(session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        np.save(p, mask)
        return p

    def read_hud(self, session_id: str, date: str):
        path = self.hud_path(session_id, date)
        if not path.is_file():
            raise SystemExit(
                f"no HUD reads for session {session_id} -- run `reticle hud` first"
            )
        return pq.read_table(path)

    # ---------- L1 · minimap position (stage 02) ----------

    def has_minimap(self, session_id: str, date: str) -> bool:
        path = self.minimap_path(session_id, date)
        if not path.is_file():
            return False
        try:
            meta = pq.read_schema(path).metadata or {}
            return meta.get(b"minimap_version", b"").decode() == MINIMAP_VERSION
        except Exception:
            return False

    def has_roster(self, session_id: str, date: str) -> bool:
        path = self.roster_path(session_id, date)
        if not path.is_file():
            return False
        try:
            meta = pq.read_schema(path).metadata or {}
            return meta.get(b"roster_version", b"").decode() == ROSTER_VERSION
        except Exception:
            return False

    def write_roster(self, rows: list[dict], fingerprint, profile_name: str, date: str) -> Path:
        """Per-frame alive counts. Two nullable columns and nothing derived.

        `alive_ally` / `alive_enemy` are NULL where the frame could not be read
        -- the bar is covered, or no split was unambiguous. That is the whole
        reason this is worth storing rather than recomputed on demand: a null
        here is a measurement that refused, and the RATE of refusal is the
        first thing anyone auditing the killfeed against this needs to know.
        Guessing a count would silently corrupt the audit it exists to provide.
        """
        if not rows:
            raise SystemExit("no frames were read -- nothing to write")
        n = len(rows)
        col = lambda k: [r[k] for r in rows]
        arrays = {
            "frame_idx": pa.array(col("frame_idx"), type=pa.int64()),
            "t_ms": pa.array(col("t_ms"), type=pa.float64()),
            "alive_ally": pa.array(col("alive_ally"), type=pa.int8()),
            "alive_enemy": pa.array(col("alive_enemy"), type=pa.int8()),
            "session_id": pa.array([fingerprint.session_id] * n, type=pa.string()),
            "content_key": pa.array([fingerprint.content_key] * n, type=pa.string()),
            "source_profile": pa.array([profile_name] * n, type=pa.string()),
            "roster_version": pa.array([ROSTER_VERSION] * n, type=pa.string()),
            "schema_version": pa.array([SCHEMA_VERSION] * n, type=pa.int32()),
        }
        table = pa.table(arrays).replace_schema_metadata(
            {
                "roster_version": ROSTER_VERSION,
                "schema_version": str(SCHEMA_VERSION),
                "session_id": fingerprint.session_id,
                "content_key": fingerprint.content_key,
                "source_profile": profile_name,
            }
        )
        path = self.roster_path(fingerprint.session_id, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
        return path

    def read_roster(self, session_id: str, date: str):
        path = self.roster_path(session_id, date)
        if not path.is_file():
            raise SystemExit(
                f"no roster for session {session_id} -- run `reticle scan` first"
            )
        return pq.read_table(path)

    def write_minimap(self, rows: list[dict], fingerprint, profile_name: str, date: str) -> Path:
        if not rows:
            raise SystemExit("no frames were read -- nothing to write")
        n = len(rows)
        col = lambda k: [r[k] for r in rows]
        arrays = {
            "frame_idx": pa.array(col("frame_idx"), type=pa.int64()),
            "t_ms": pa.array(col("t_ms"), type=pa.float64()),
            # Raw per-frame detections, unfiltered -- nothing here has been
            # through filter_track's jump rejection or gap interpolation, so
            # a change to RUN_PX/GAP_MS never invalidates this cache. Self is
            # a real track (nearest-to-previous); allies are per-frame
            # candidates with no identity across frames -- see minimap.py.
            "self_x": pa.array(col("self_x"), type=pa.float32()),
            "self_y": pa.array(col("self_y"), type=pa.float32()),
            "n_allies": pa.array(col("n_allies"), type=pa.int8()),
        }
        for i in range(len(rows[0]["ally_x"])):
            arrays[f"ally{i}_x"] = pa.array([r["ally_x"][i] for r in rows], type=pa.float32())
            arrays[f"ally{i}_y"] = pa.array([r["ally_y"][i] for r in rows], type=pa.float32())
        arrays["session_id"] = pa.array([fingerprint.session_id] * n, type=pa.string())
        arrays["content_key"] = pa.array([fingerprint.content_key] * n, type=pa.string())
        arrays["source_profile"] = pa.array([profile_name] * n, type=pa.string())
        arrays["minimap_version"] = pa.array([MINIMAP_VERSION] * n, type=pa.string())
        arrays["schema_version"] = pa.array([SCHEMA_VERSION] * n, type=pa.int32())

        table = pa.table(arrays).replace_schema_metadata(
            {
                "minimap_version": MINIMAP_VERSION,
                "schema_version": str(SCHEMA_VERSION),
                "session_id": fingerprint.session_id,
                "content_key": fingerprint.content_key,
                "source_profile": profile_name,
            }
        )
        path = self.minimap_path(fingerprint.session_id, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
        return path

    def read_minimap(self, session_id: str, date: str):
        path = self.minimap_path(session_id, date)
        if not path.is_file():
            raise SystemExit(
                f"no minimap position for session {session_id} -- run `reticle minimap` first"
            )
        return pq.read_table(path)

    # ---------- L2 ----------

    def write_spans(self, spans: list[dict], session_id: str, date: str, cfg) -> Path:
        n = len(spans)
        arrays = {
            "span_idx": pa.array([s["span_idx"] for s in spans], type=pa.int32()),
            "state": pa.array([s["state"] for s in spans], type=pa.string()),
            "t_start_ms": pa.array([s["t_start_ms"] for s in spans], type=pa.float64()),
            "t_end_ms": pa.array([s["t_end_ms"] for s in spans], type=pa.float64()),
            "duration_ms": pa.array([s["duration_ms"] for s in spans], type=pa.float64()),
            "n_samples": pa.array([s["n_samples"] for s in spans], type=pa.int32()),
            "mean_motion": pa.array([s["mean_motion"] for s in spans], type=pa.float64()),
            "session_id": pa.array([session_id] * n, type=pa.string()),
            "segmenter_version": pa.array([SEGMENTER_VERSION] * n, type=pa.string()),
            "schema_version": pa.array([SCHEMA_VERSION] * n, type=pa.int32()),
        }
        table = pa.table(arrays).replace_schema_metadata(
            {
                "segmenter_version": SEGMENTER_VERSION,
                "session_id": session_id,
                "config": json.dumps(cfg.as_dict()),
            }
        )
        path = self.spans_path(session_id, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
        return path

    def write_rounds(self, rounds: list[dict], session_id: str, date: str) -> Path:
        n = len(rounds)
        hud_path = self.hud_path(session_id, date)
        hud_meta = (pq.read_schema(hud_path).metadata or {}) if hud_path.is_file() else {}
        source_version = hud_meta.get(b"hud_version", b"").decode() or None
        content_key = hud_meta.get(b"content_key", b"").decode() or None
        col = lambda k, ty: pa.array([r.get(k) for r in rounds], type=ty)
        table = pa.table({
            "round_no": col("round_no", pa.int16()),
            "t_start_ms": col("t_start_ms", pa.float64()),
            "t_end_ms": col("t_end_ms", pa.float64()),
            # Nullable on purpose: an unresolved side leaves `won` null rather
            # than guessed, so a coin flip cannot corrupt a win rate downstream.
            "won": col("won", pa.bool_()),
            "won_left": col("won_left", pa.bool_()),
            "player_side": col("player_side", pa.string()),
            "score_us": col("score_us", pa.int16()),
            "score_them": col("score_them", pa.int16()),
            "player_kills": col("player_kills", pa.int16()),
            "player_deaths": col("player_deaths", pa.int16()),
            "multikill": col("multikill", pa.int16()),
            "first_event": col("first_event", pa.string()),
            "spike_planted": col("spike_planted", pa.bool_()),
            "plant_t_ms": col("plant_t_ms", pa.float64()),
            "post_plant_ms": col("post_plant_ms", pa.float64()),
            "side_inferred": col("side_inferred", pa.string()),
            "side_separation": col("side_separation", pa.float64()),
            "side_agrees": col("side_agrees", pa.bool_()),
            "map": col("map", pa.string()),
            "round_version": pa.array([ROUND_VERSION] * n, type=pa.string()),
            "hud_version": pa.array([source_version] * n, type=pa.string()),
            "content_key": pa.array([content_key] * n, type=pa.string()),
            "session_id": pa.array([session_id] * n, type=pa.string()),
            "schema_version": pa.array([SCHEMA_VERSION] * n, type=pa.int32()),
        }).replace_schema_metadata({"session_id": session_id,
                                    "round_version": ROUND_VERSION,
                                    "hud_version": source_version or "unknown",
                                    "content_key": content_key or "unknown",
                                    "schema_version": str(SCHEMA_VERSION)})
        path = self.rounds_path(session_id, date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd")
        return path

    def read_rounds(self, session_id: str, date: str):
        path = self.rounds_path(session_id, date)
        return pq.read_table(path) if path.is_file() else None

    def read_spans(self, session_id: str, date: str):
        path = self.spans_path(session_id, date)
        if not path.is_file():
            return None
        return pq.read_table(path)

    # ----------------------------------------------------------------- events

    def events_path(self, kind: str, session_id: str) -> Path:
        return self.root / "events" / kind / f"{session_id}.jsonl"

    def write_events(self, kind: str, session_id: str, rows: list[dict]) -> Path:
        """One JSONL file per (kind, session). Rewritten whole, never appended.

        The layout is the one `prototypes/ability_*` already wrote by hand;
        having it here is what stops the next reader inventing a third. Rows
        are things that HAPPENED at an instant, so they are not the wide
        per-frame tables L1 uses and do not belong in one -- a session's pings
        are tens of rows, not tens of thousands.

        A rewrite rather than an append because a re-read supersedes: the
        alternative is two runs of the same detector both present in the file
        with nothing to say which is current.
        """
        path = self.events_path(kind, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        return path

    def events_version(self, kind: str, session_id: str) -> str | None:
        """The version an event file was written at, or None if there is none.

        Reads ONE line rather than parsing the whole file, because the caller
        is asking an existence-and-staleness question and a session's events
        are answered by any row -- `write_events` rewrites whole, so a file
        cannot hold two versions.
        """
        path = self.events_path(kind, session_id)
        if not path.is_file():
            return None
        with open(path, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    return json.loads(ln).get(f"{kind}_version")
        return None

    def read_events(self, kind: str, session_id: str) -> list[dict]:
        path = self.events_path(kind, session_id)
        if not path.is_file():
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]
