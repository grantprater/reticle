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

from .version import EXTRACTOR_VERSION, HUD_VERSION, SCHEMA_VERSION, SEGMENTER_VERSION

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

    def primitives_glob(self) -> str:
        return str(self.root / "l1" / "primitives" / "**" / "*.parquet")

    def spans_glob(self) -> str:
        return str(self.root / "l2" / "spans" / "**" / "*.parquet")

    def hud_glob(self) -> str:
        return str(self.root / "l1" / "hud" / "**" / "*.parquet")

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
            # Each entry's weapon-icon divider column, packed nine bits per
            # stack slot. An entry's divider does not move while it is on
            # screen, so this is what tells one entry from the next when both
            # occupy the same slot in turn -- the merge the masks above cannot
            # see. int64: six slots of nine bits. See killfeed.divider_of_ys.
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

    def read_hud(self, session_id: str, date: str):
        path = self.hud_path(session_id, date)
        if not path.is_file():
            raise SystemExit(
                f"no HUD reads for session {session_id} -- run `reticle hud` first"
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
            "session_id": pa.array([session_id] * n, type=pa.string()),
            "schema_version": pa.array([SCHEMA_VERSION] * n, type=pa.int32()),
        }).replace_schema_metadata({"session_id": session_id,
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
