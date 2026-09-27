r"""Name the local player's ability casts from audio, with a bank cut from the solo demos.

    .\.venv\Scripts\python.exe prototypes\audio_bank.py build [--demos [SID ...]] [--matches [SID ...]] [--census SID ...]
    .\.venv\Scripts\python.exe prototypes\audio_bank.py census [--record]
    .\.venv\Scripts\python.exe prototypes\audio_bank.py sources [--bank-sessions|--bank-slot|--bank-add SID ...]
    .\.venv\Scripts\python.exe prototypes\audio_bank.py retrieve [--bank-sessions|--bank-slot|--bank-add SID ...] [--within] [--template S] [--record]
    .\.venv\Scripts\python.exe prototypes\audio_bank.py transfer [--bank-sessions|--bank-slot|--bank-add SID ...] [--template S] [--record]
    .\.venv\Scripts\python.exe prototypes\audio_bank.py explain KEY [KEY ...] [--score S] [--phase P] [--bank-sessions|--bank-slot|--bank-add SID ...]
    .\.venv\Scripts\python.exe prototypes\audio_bank.py sheet demo_bank|match_windows [--sids ...]

Why this exists
---------------
`audio_channel.py` showed that a 0.6 s log-mel template names an ability within
one session and transfers only partly across two Omen sessions, and it named
what a bank needs before any threshold means anything: a reject class and
references from more than one session. This file builds that bank from all the
solo demos and asks the question that matters for the entity channel: does the
bank name the player's own casts in real matches, where the tray says a slot
dropped but not always which sound went with it? The predictions and outcomes
are in the store's `notes/predictions.jsonl` under `audio-ability-bank`, and the
write-up is `docs/AUDIO_ABILITY_BANK.md`.

What it does
------------
`build` cuts a window from 3 s before to 3 s after every tray drop in the
demo cast caches (`casts/<sid>.step0.5.*.json`), plus the five cast times the
ledger names for the two demos without a cache (`NAMED`), and stores absolute
log-mel dB with the median of an 8 s context around the drop. `build --census`
takes a session's casts from the demo cast census instead (`CENSUS_TABLES`,
`census_rows`), leaving out what the census judged no cast or the settings
menu [domain:hud/menu-dims-tray], and the tray owner's `cooccur` drops and its
`forced` ones the census did not see real, because a reference must be clean.
Census references join the bank beside the older ones and replace nothing.
They bring no reject windows: under infinite abilities the tray drops for some
casts only, so a tray-quiet window in those clips is not quiet.
The front end is `audio_channel`'s (64 bands, 60 Hz-16 kHz, 10 ms hop), with the median taken
over that local context instead of the whole clip, so a 40-minute match and a
30-second demo go through the same arithmetic. Drops of three or more slots
within 1.5 s are the tray changing whose it is and are left out. Windows at
least 8 s from every drop are the reject class. The match side takes every
`player_cast` drop in `events/tray_drop` and every player-verified cast in
`labels/tray_object`, names the agent through the identity arbiter's resolved
verdict for the player's slot, and cuts ten null windows per session from the
round-live span before the player's first death, 8 s from any drop. Audio is
decoded by seeking the audio stream; video packets are read and never decoded.

Each reference offers phase templates [domain:abilities/ability-sound-phases]:
`cast`, starting at the largest onset where the tray allows the cast (the
half-second before the drop, with slack, or around a census drop time refined
at 15 Hz); `equip`, at the largest earlier onset if it rises at least a
quarter as far; and `ongoing`, 1.8 s starting 1.0 s after the cast, when the
sound there stands 3 dB above the context, so an ability with a lifetime shows
itself in the audio. A drop marks the equip for some abilities
[domain:abilities/deadlock-ult-tray-drop-at-equip], and Sova's bolts charge
before release [domain:abilities/sova-bolt-charge-and-bounce], so the names
are positions, not verified phases. Every template keeps its phase
(`refs_from`), and `sources` prints where each agent's references come from.
A query window is scored against every template over the lags its phase allows: `corr` (z-scored patch correlation),
`cover` (the one-sided coverage of `audio_channel`, for voice lines
[domain:abilities/ability-voice-line-mask]), `prod` = max(corr, 0) x cover, and
the same two on absolute levels (`cover_abs`, `prod_abs`). A class scores its
best reference. The kit 4-way scores only the player's agent's four slots,
which the lineup allows; the open set scores all 100 bank classes and refuses
below the 95th percentile of the reject class. The open set is the surprise
path, there to show whether audio alone would name the agent.

By default a run uses 0.1.0's bank: every demo reference and no census one.
`--bank-sessions` names census sessions; each agent they cast for takes its
references only from them, so a slot they never cast leaves the kit, and every
other agent keeps its old ones (`bank_select`). `--bank-slot` replaces only
the slots they cast, and `--bank-add` adds them to the old references.
`retrieve --within` asks only those sessions' casts, each named by the rest.
The re-recorded demos' results are in `docs/AUDIO_ABILITY_BANK.md`,
"Re-recorded references". Scores are
cached per query and template, so a session added to the bank scores only its
own templates. Metric parts carry `_v2`, plus `_rerec` (or `--tag`) under
`--bank-sessions`; 0.1.0's parts and files keep the numbers below.

0.2.0 widened the window and kept the context, so every frame 0.1.0 stored is
stored again unchanged; on two demos and one match its cast-phase scores equal
0.1.0's exactly. The equip search reaches 3 s back instead of 1.5 s, so equip
and "any" scores differ from 0.1.0's, and leave-one-out now removes
same-session references within 3.5 s instead of 2.5 s.

What 0.1.0 measured (2026-09-26)
--------------------------------
The bank holds [metric:audio_bank/build#demo_casts=132] casts from
[metric:audio_bank/build#demo_sessions=29] demos in
[metric:audio_bank/build#bank_classes=100] classes, of which
[metric:audio_bank/build#bank_classes_single=74] hold one reference. Transfer
ran on [metric:audio_bank/build#match_player_casts=483] tray casts in
[metric:audio_bank/build#match_sessions=19] matches, of which
[metric:audio_bank/build#match_labelled=120] carry the player's answer.

1. **The declared score failed.** `prod` on the cast template names the kit
   slot of [metric:audio_bank/transfer#verified_kit_top1=0.325] of the verified
   casts, against a per-agent majority-slot rate of
   [metric:audio_bank/transfer#majority_rate=0.292]. Plain correlation does
   better ([metric:audio_bank/transfer_variants#corr_cast_verified_kit_top1=0.483]),
   and so does coverage on absolute levels with 1.0 s templates
   ([metric:audio_bank/transfer_variants_t100#prod_abs_cast_verified_kit_top1=0.508]);
   both were chosen after the fact.
2. **Some abilities transfer and some never do.** Under correlation Sova's Owl
   Drone ([metric:audio_bank/confusion_verified#corr_cast_Sova_C_hits=8] of 8),
   Clove's Ruse ([metric:audio_bank/confusion_verified#corr_cast_Clove_E_hits=8] of 9)
   and Skye's Trailblazer ([metric:audio_bank/confusion_verified#corr_cast_Skye_Q_hits=8] of 9)
   transfer. Sova's Recon Bolt
   ([metric:audio_bank/confusion_verified#corr_cast_Sova_E_hits=0] of 8) and
   Skye's Regrowth ([metric:audio_bank/confusion_verified#corr_cast_Skye_C_hits=0] of 9)
   fail under every score. Clove's Pick-me-up and Not Dead Yet have no demo cast.
3. **The failures trace to the references.** Skye's demo drops E and X half a
   second apart, so Guiding Light and Seekers share one sound; Sova's Recon
   Bolt was cast while moving, its drop 0.5 s before two Shock Bolt drops, and
   its template sits on footsteps. Blaze's reference is right, yet Hot Hands
   shares its onset and wins; a 1.0 s template did not separate them.
4. **The demo reject class is not a null.** Its tray-quiet windows score above
   the true class ([metric:audio_bank/retrieve#reject_p95=0.746] against a
   median of [metric:audio_bank/retrieve#true_median=0.296]), probably because
   infinite abilities let casts pass without a drop and those windows share the
   references' recording.
   The resulting threshold admits
   [metric:audio_bank/transfer#null_accept_all=3] of 190 match null windows and
   [metric:audio_bank/transfer#verified_open_accepted=4] of 120 verified casts.
5. **Levels agree on the median only.** The match minus demo gain over a true
   reference's loud cells has median [metric:audio_bank/gain#median=-1.9] dB,
   but only [metric:audio_bank/gain#within_3db=41] of 114 casts lie within 3 dB.

What it does not do
-------------------
It emits no events, writes nothing under `events/` or `labels/`, and
`reticle/` does not import it. It stores features, never audio. It does not
decode video, so it cannot say which of two co-occurring demo drops was the
cast; that question is the player's. The stereo difference, which
`audio_channel` found identifies self sounds, is not used.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import io
import json
import os
import sys
import zlib
from pathlib import Path

#: The player's rule for this work (2026-09-26): Below Normal priority, four
#: BLAS threads. The player's own long jobs run beside this one.
THREADS, BELOW_NORMAL = "4", 0x4000
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, THREADS)


def _lower_priority() -> None:
    """Run at Below Normal priority, or stop.

    The handle types are declared: with ctypes' default `int`, the
    pseudo-handle of `GetCurrentProcess` reaches `SetPriorityClass` truncated
    on x64 and the call fails silently (`demo_cast_census.idle`). 0.1.0 made
    that call undeclared and unchecked, so its runs probably kept Normal.
    """
    if os.name != "nt":
        return
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k.GetPriorityClass.restype = ctypes.c_uint32
    if not k.SetPriorityClass(k.GetCurrentProcess(), BELOW_NORMAL):
        raise SystemExit("could not lower this process to Below Normal priority")
    if k.GetPriorityClass(k.GetCurrentProcess()) != BELOW_NORMAL:
        raise SystemExit("the priority class did not change to Below Normal")


_lower_priority()

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))
with contextlib.redirect_stdout(io.StringIO()):
    import audio_channel  # noqa: E402  the front end's mel filterbank

STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "audio-bank"
VERSION = "audio-bank-0.2.0"
#: Features, templates and score caches of this version. The 0.1.0 files stay
#: in OUT, where `docs/AUDIO_ABILITY_BANK.md` cites their plots.
DATA = OUT / VERSION.rsplit("-", 1)[1]
#: Metric parts of this version carry this tag; the 0.1.0 parts keep their
#: names and the numbers the doc cites.
SERIES = "_v2"

#: The front end of `audio_channel.logmel`, unchanged: 64 bands, 60 Hz-16 kHz,
#: 10 ms hop, 2048-point frames of the mono mix.
HOP, NFFT, BANDS, FMIN, FMAX = 0.01, 2048, 64, 60.0, 16000.0
#: The stored window around a tray drop, seconds before and after it. 0.1.0
#: kept 1.5 s and 1.0 s; the equip-hold-cast demos hold longer than 1.5 s, and
#: the ongoing phase needs 3 s after the drop. The context below is unchanged,
#: so every frame 0.1.0 stored is stored again with the same value.
PRE, POST = 3.0, 3.0
#: The context whose per-band median is removed. `audio_channel` used the whole
#: clip; a match is 30-45 minutes of changing ambience, so bank and queries both
#: take the same local context instead.
CTX_PRE, CTX_POST = 5.0, 3.0
#: Template length and the lead before an onset, as `audio_channel`.
TEMPLATE_S, LEAD = 0.6, 0.05
#: The tray samples every 0.5 s, so the cast lies in (t - 0.5, t]; the onset
#: search takes 0.15 s of slack before and 0.10 s after.
CAST_ONSET = (-0.65, 0.10)
#: An equip precedes its cast by a variable hold; only onsets at least 0.25 s
#: before the cast onset and inside the window are equip alternatives.
EQUIP_GAP = 0.25
#: An equip alternative must be an onset, not the floor: at least this
#: fraction of the cast onset's rise. On the Omen demo the equip lies more than
#: 1.5 s before the cast, and without this the alternative was ambience.
EQUIP_MIN = 0.25
#: The ongoing phase [domain:abilities/ability-sound-phases]: a template this
#: many seconds after the cast template's start and this long, in the window
#: 1-3 s after the drop. A reference offers it only when the sound there stands
#: ONGOING_MIN_DB above the context median (the mean of the top quarter of the
#: per-band medians over the template), so an ability with a lifetime is found
#: in the audio, not listed by hand. Guiding Light's activation, a separate
#: sound [domain:abilities/ability-sound-phases], falls in this window too; the
#: end sound is not modelled, because lifetimes differ.
ONGOING_OFFSET, ONGOING_S, ONGOING_MIN_DB = 1.0, 1.8, 3.0
#: A census drop time refined at 15 Hz places the cast within a frame, so its
#: onset search narrows to this slack around the refined time.
REFINED_SLACK = (0.25, 0.10)
#: A reject window lies at least this far from every tray drop.
REJECT_GAP = 8.0
#: The reject grid of 0.1.0 (first anchor, step, end margin), kept so that the
#: reject class and the cast-phase threshold are unchanged by the wider window.
REJECT_GRID = (2.0, 2.5, 1.5)
#: References sharing audio with a query leave the bank with it: the equip
#: search reaches 3 s back and the ongoing template 2.9 s forward, so a
#: same-session reference within this many seconds could match its own audio.
LOO_GAP = 3.5
#: Two slots or more dropping within this window is the tray changing whose it
#: is when three or more drop (`ability_hud.SUSPECT_S`).
SWITCH_S, SWITCH_N = 1.5, 3
NULL_PER_SESSION = 10
#: The refusal threshold is this percentile of the demo reject class.
REJECT_PCT = 95

#: Demos without a cast cache, and the times the ledger and `audio_channel`
#: name for them: (slot, seconds of the cast or equip onset, provenance).
#: A named time is an onset, so its anchor is set 0.25 s later, the middle of
#: the tray's half-second. Everything else in these clips is uncovered.
NAMED = {
    "29eff6920e8f": [("C", 11.91, "ledger audio-channel-control P5, Barrier Mesh cast onset"),
                     ("Q", 24.56, "audio_channel.PAIRS cast Q"),
                     ("Q", 33.40, "audio_channel.PAIRS cast Q"),
                     ("X", 45.30, "ledger P4, tray X drop = ult equip")],
    "afa5bc60b935": [("Q", 18.10, "domain viper-poison-cloud-toggle: tray drop is the throw")],
}
#: Clips whose casts nobody observed: no tray drop in the cache and no named
#: time. Their audio holds casts, so they give no reject windows either.
UNCOVERED = ("2ba870ccbd50", "79a706a7ce4c")
#: The census cast tables, searched in order; a session's rows come from the
#: first that holds it. The re-recorded demos have their own run.
CENSUS_TABLES = (STORE / "analysis" / "demo-cast-census-rerecorded" / "casts.json",
                 STORE / "analysis" / "demo-cast-census" / "casts.json")

FRAMES = int(round((PRE + POST) / HOP))
T = int(round(TEMPLATE_S / HOP))
T_ONGOING = int(round(ONGOING_S / HOP))
#: The census sessions whose references replace their agents' (`--bank-sessions`,
#: mode `only`) or join them (`--bank-add`, mode `add`), and the tag their
#: metric parts carry.
BANK_SESSIONS: tuple[str, ...] = ()
BANK_MODE = "only"
BANK_TAG = ""


def set_template(seconds: float) -> None:
    """Change the cast and equip template length; caches and metric parts carry it."""
    global TEMPLATE_S, T
    TEMPLATE_S, T = seconds, int(round(seconds / HOP))


def set_bank(sessions: list[str] | None, tag: str | None = None, mode: str = "only") -> None:
    """Take these census sessions' references for their agents (see `bank_select`)."""
    global BANK_SESSIONS, BANK_MODE, BANK_TAG
    BANK_SESSIONS, BANK_MODE = tuple(sessions or ()), mode
    default = {"only": "rerec", "slot": "slot", "add": "both"}[mode]
    BANK_TAG = "" if not BANK_SESSIONS else f"_{tag or default}"


def _tsuffix() -> str:
    """Score caches depend on the template length only."""
    return "" if T == 60 else f"_t{T}"


def _suffix() -> str:
    """Metric parts: this version, the template length, the bank selection."""
    return SERIES + _tsuffix() + BANK_TAG


def _tlen(phase: str) -> int:
    return T_ONGOING if phase == "ongoing" else T


SCORES = ("corr", "cover", "prod", "cover_abs", "prod_abs")
PHASES = ("cast", "equip", "ongoing")


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _manifest(sid: str) -> dict:
    return json.loads((STORE / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))


def _agents() -> list[str]:
    ref = json.loads((STORE / "reference" / "abilities.json").read_text(encoding="utf-8"))
    return list(ref["agents"])


def tagged_agent(sid: str) -> str | None:
    """The agent a demo's manifest tags, spelled as the ability reference spells it."""
    by_tag = {a.lower().replace("/", ""): a for a in _agents()}
    hits = [by_tag[t] for t in _manifest(sid).get("tags", []) if t in by_tag]
    return hits[0] if len(hits) == 1 else None


def kit(agent: str) -> dict[str, str]:
    from reticle import lineup
    return lineup.abilities_for(agent, STORE)


def demo_sessions() -> list[str]:
    out = []
    for f in sorted((STORE / "manifests").glob("*.json")):
        if "ability-demo" in json.loads(f.read_text(encoding="utf-8")).get("tags", []):
            out.append(f.stem)
    return out


def demo_rows(sid: str) -> tuple[list[dict], list[dict], list[float]]:
    """(casts, excluded tray switches, every drop time) for one demo."""
    caches = sorted((STORE / "casts").glob(f"{sid}.step0.5.*.json"))
    agent = tagged_agent(sid)
    names = kit(agent) if agent else {}
    casts, switch, drops = [], [], []
    if caches:
        rows = json.loads(caches[0].read_text(encoding="utf-8"))
        drops = [float(r[0]) for r in rows]
        for i, (t, slot, a, b, suspect) in enumerate(rows):
            near = {r[1] for r in rows if abs(r[0] - t) <= SWITCH_S}
            rec = {"sid": sid, "agent": agent, "slot": slot, "ability": names.get(slot),
                   "t": float(t), "suspect": bool(suspect), "fill": [a, b],
                   "origin": "cast_cache", "source": f"casts/{caches[0].name}"}
            (switch if len(near) >= SWITCH_N else casts).append(rec)
    for slot, t, why in NAMED.get(sid, []):
        casts.append({"sid": sid, "agent": agent, "slot": slot, "ability": names.get(slot),
                      "t": t + 0.25, "suspect": False, "fill": None, "origin": "named",
                      "source": why})
        drops.append(t + 0.25)
    return casts, switch, drops


def _census_owner():
    """The demo cast census: its module, its cast tables, and its menu verdicts.

    The census owns which demo drops are casts. Each row carries `census`,
    false where its eye check judged no cast, and, where the eye looked, a
    `tray_verdict` (`real`, `false`, or `menu` for the settings menu over the
    tray [domain:hud/menu-dims-tray]). The first run's blind read names the
    menu too (`SETTINGS_COVER`), and any truthy row field whose name holds
    `menu` or `settings` is read as that verdict.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        import demo_cast_census as dc
    tables = [(p, json.loads(p.read_text(encoding="utf-8"))["casts"])
              for p in CENSUS_TABLES if p.is_file()]
    menu: set[str] = set()
    if dc.TABLE.is_file():
        for x in json.loads(dc.TABLE.read_text(encoding="utf-8"))["rows"]:
            if dc.SETTINGS_COVER.search(x.get("desc") or ""):
                menu.add(x["key"])
    return dc, tables, menu


def census_rows(sid: str, owner=None) -> tuple[list[dict], dict[str, list], list[float]]:
    """(casts, excluded by reason, every drop time) for one census session.

    The anchor is the 2 Hz drop time, as for the cast caches and the match
    queries; the refined 15 Hz time narrows the onset search (`cast_onset`).
    The census's verdict decides: `false` and `menu` rows leave. A reference
    must also be clean, so the tray owner's `cooccur` (another slot within
    `tray.SUSPECT_S`, two sounds in one window) leaves it out, and so does
    `forced` (the tray undrawn at the drop) unless the eye saw the drop real.
    """
    dc, tables, menu = owner or _census_owner()
    src, every = next(((p, [c for c in rows if c["sid"] == sid]) for p, rows in tables
                       if any(c["sid"] == sid for c in rows)), (None, []))
    agent = every[0]["agent"] if every else None
    names = kit(agent) if agent else {}
    casts, out = [], {"census_false": []}
    drops = [c["t_ms"] / 1000.0 for c in every]
    for c in every:
        verdict = c.get("tray_verdict")
        if not c.get("census", True) or verdict in ("false", "menu"):
            out.setdefault("menu" if verdict == "menu" else "census_false", []).append(c)
            continue
        key = dc.cast_key(c)
        why = []
        if key in menu:
            why.append("menu_blind_read")
        why += [f"menu_field_{f}" for f, v in c.items()
                if ("menu" in f or "settings" in f) and v]
        if c.get("forced") and verdict != "real":
            why.append("forced")
        if c.get("cooccur"):
            why.append("cooccur")
        t = c["t_ms"] / 1000.0
        d = dc.cast_time_ms(c) / 1000.0 - t
        refined = c.get("t_refined_ms") is not None
        rec = {"sid": sid, "agent": c["agent"], "slot": c["slot"],
               "ability": names.get(c["slot"]) or c.get("ability"), "t": round(t, 3),
               "t_refined": round(t + d, 3) if refined else None,
               "suspect": bool(c.get("suspect")),
               "fill": [c.get("from"), c.get("to")], "origin": "census",
               # Unrefined, the cast lies anywhere in the tray's half second. A
               # drop bridged across refused samples refines up to 3.5 s back.
               "cast_onset": [round(d - REFINED_SLACK[0], 3), round(d + REFINED_SLACK[1], 3)]
               if refined else None,
               "tray_verdict": verdict, "forced": bool(c.get("forced")),
               "source": f"{src.parent.name} {dc.VERSION} {key} ({c.get('source_reader')})"}
        if why:
            for w in why:
                out.setdefault(w, []).append(rec)
        else:
            casts.append(rec)
    return casts, out, drops


def match_sessions() -> list[str]:
    return sorted(p.stem for p in (STORE / "events" / "tray_drop").glob("*.jsonl"))


def player_agent(sid: str) -> tuple[str | None, str]:
    """The player's agent from the identity arbiter's resolved verdict, or a reason."""
    from reticle import lineup
    with contextlib.redirect_stdout(io.StringIO()):
        lu = lineup.load_lineup(sid, STORE)
    if lu is None:
        return None, "no lineup"
    slot = (lu.get("player") or {}).get("slot")
    for v in lu.get("agent_identity") or []:
        if v.get("entity_id") == f"{sid}:ally:slot:{slot}" and v.get("status") == "resolved":
            return v.get("agent"), "resolved"
    return None, f"player slot {slot} has no resolved verdict"


def _labels(sid: str) -> dict[str, dict]:
    f = STORE / "labels" / "tray_object" / f"{sid}.jsonl"
    out = {}
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r          # the last row per key wins
    return out


def match_rows(sid: str, agent: str) -> tuple[list[dict], list[dict], list[float]]:
    """(player casts and labelled casts, all drop rows, every drop time)."""
    rows = [json.loads(x) for x in (STORE / "events" / "tray_drop" / f"{sid}.jsonl")
            .read_text(encoding="utf-8").splitlines() if x.strip()]
    drops = [r for r in rows if r.get("kind") == "drop"]
    labels = _labels(sid)
    names = kit(agent)
    out = []
    for r in drops:
        key = f"{sid}:{round(r['t_ms'])}:{r['slot']}"
        lab = labels.get(key)
        if not (r.get("player_cast") or lab):
            continue
        out.append({"sid": sid, "agent": agent, "slot": r["slot"],
                    "ability": names.get(r["slot"]), "t": r["t_ms"] / 1000.0,
                    "key": key, "player_cast": bool(r.get("player_cast")),
                    "across_gap": bool(r.get("across_gap")), "forced": bool(r.get("forced")),
                    "labelled": lab is not None,
                    "label_ability": lab.get("ability") if lab else None,
                    "label_class": lab.get("class") if lab else None})
    return out, drops, [r["t_ms"] / 1000.0 for r in drops]


def live_spans(sid: str, drops: list[dict]) -> list[tuple[float, float]]:
    """Round-live spans, barrier drop to round end or the player's first death.

    `gametime` owns the barrier drop; the tray owner's drop rows carry the
    player's first death per round. A round with no drop row has no known death
    and gives no span.
    """
    from reticle import cli, gametime, stalls
    from reticle.store import Store
    store = Store(STORE)
    date = cli._date_of(_manifest(sid))
    rs, hud = store.read_rounds(sid, date), store.read_hud(sid, date)
    if rs is None or hud is None:
        return []
    with contextlib.redirect_stdout(io.StringIO()):
        gt = gametime.build_session_gametime(sid, hud, rs.to_pylist(),
                                             stall_list=stalls.for_session(store, sid, date))
    death = {}
    for r in drops:
        if r.get("round_ms"):
            death[round(r["round_ms"][0])] = r.get("first_player_death_ms")
    out = []
    for s in gt.schedules:
        k = round(s.t_start_ms)
        if k not in death:
            continue
        end = s.t_end_ms if death[k] is None else min(s.t_end_ms, death[k])
        if end - s.t_live_ms > 10_000:
            out.append((s.t_live_ms / 1000.0 + 5.0, end / 1000.0 - 2.0))
    return out


# ---------------------------------------------------------------------------
# Front end
# ---------------------------------------------------------------------------

def read_spans(path: str, spans: list[tuple[float, float]]):
    """Yield (t0, stereo float32 [n, 2], filled mask, rate) for each span.

    Decodes the audio stream only: the demuxer reads the interleaved video
    packets and never decodes them. Each AAC frame is placed by its own pts,
    so a seek that lands early costs nothing and a gap stays a gap (unfilled).
    """
    import av
    with av.open(str(path)) as c:
        st = c.streams.audio[0]
        rate = st.rate
        for t0, t1 in spans:
            n = int(round((t1 - t0) * rate))
            x = np.zeros((n, 2), np.float32)
            filled = np.zeros(n, bool)
            c.seek(max(0, int((max(0.0, t0) - 0.5) / st.time_base)), stream=st)
            done = False
            for pkt in c.demux(st):
                for fr in pkt.decode():
                    if fr.pts is None:
                        continue
                    ft = float(fr.pts * st.time_base)
                    a = fr.to_ndarray()
                    if a.ndim == 1 or a.shape[0] != 2:
                        raise SystemExit(f"{path}: expected planar stereo, got {a.shape}")
                    i = int(round((ft - t0) * rate))
                    j = i + a.shape[1]
                    lo, hi = max(i, 0), min(j, n)
                    if hi > lo:
                        x[lo:hi] = a[:, lo - i:hi - i].T
                        filled[lo:hi] = True
                    if i >= n:
                        done = True
                if done:
                    break
            yield t0, x, filled, rate


_FB: dict[int, np.ndarray] = {}


def features(x, filled, rate, t0, anchor) -> tuple[np.ndarray, np.ndarray, int]:
    """(absolute log-mel dB [FRAMES, 64], context median [64], padded frames).

    Frame k is centred on anchor - PRE + k * HOP. A frame that reaches outside
    the decoded audio is replaced by the context median, so it scores as
    ambience and is counted.
    """
    if rate not in _FB:
        _FB[rate] = audio_channel._mel_fb(rate, NFFT, BANDS, FMIN, FMAX)
    m = x.mean(axis=1)
    k = int(round((CTX_PRE + CTX_POST) / HOP))
    centres = anchor - CTX_PRE + HOP * np.arange(k)
    c = np.round((centres - t0) * rate).astype(int)
    first = c - NFFT // 2
    cum = np.concatenate([[0], np.cumsum(filled)])
    ok = (first >= 0) & (first + NFFT <= len(m))
    ok[ok] = (cum[first[ok] + NFFT] - cum[first[ok]]) == NFFT
    idx = np.clip(first[:, None] + np.arange(NFFT)[None], 0, len(m) - 1)
    P = np.abs(np.fft.rfft(m[idx] * np.hanning(NFFT), axis=1)) ** 2
    L = 10 * np.log10(P @ _FB[rate].T + 1e-10)
    if not ok.any():
        raise ValueError("no decodable frame in the context")
    med = np.median(L[ok], axis=0)
    L[~ok] = med
    a = int(round((CTX_PRE - PRE) / HOP))
    return L[a:a + FRAMES], med, int((~ok[a:a + FRAMES]).sum())


def _merge(anchors: list[float], dur: float | None = None) -> list[tuple[float, float]]:
    spans = []
    for a in sorted(anchors):
        lo, hi = a - CTX_PRE - 0.1, a + CTX_POST + 0.1
        if dur is not None:
            lo, hi = max(lo, 0.0), min(hi, dur)
        if spans and lo <= spans[-1][1] + 2.0:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])
    return [(float(a), float(b)) for a, b in spans]


def _extract(sid: str, items: list[dict]) -> None:
    """Fill `A`, `med`, `pad` on each item (anchor `t`) from one capture."""
    path = _manifest(sid)["source"]["path"]
    spans = _merge([it["t"] for it in items])
    got = list(read_spans(path, spans))
    for it in items:
        t0, x, filled, rate = next(g for g in got if g[0] <= it["t"] - CTX_PRE - 0.1 + 1e-6
                                   and it["t"] + CTX_POST + 0.1 <= g[0] + len(g[1]) / g[3] + 1e-6)
        it["A"], it["med"], it["pad"] = features(x, filled, rate, t0, it["t"])


def _save(name: str, items: list[dict]) -> Path:
    DATA.mkdir(parents=True, exist_ok=True)
    A = np.stack([it.pop("A") for it in items]).astype(np.float16)
    med = np.stack([it.pop("med") for it in items]).astype(np.float16)
    np.savez_compressed(DATA / f"{name}.npz", A=A, med=med)
    (DATA / f"{name}.json").write_text(json.dumps(
        {"version": VERSION, "front_end": {"hop": HOP, "nfft": NFFT, "bands": BANDS,
                                           "fmin": FMIN, "fmax": FMAX, "pre": PRE,
                                           "post": POST, "ctx": [CTX_PRE, CTX_POST]},
         "items": items}, indent=1), encoding="utf-8")
    return DATA / f"{name}.npz"


def load(name: str) -> tuple[list[dict], np.ndarray, np.ndarray]:
    f = DATA / f"{name}.json"
    if not f.is_file():
        raise SystemExit(f"{f} does not exist; run `build` first")
    meta = json.loads(f.read_text(encoding="utf-8"))
    if meta["version"] != VERSION:
        raise SystemExit(f"{name}: stored {meta['version']} != {VERSION}; rebuild")
    z = np.load(DATA / f"{name}.npz")
    return meta["items"], z["A"].astype(np.float32), z["med"].astype(np.float32)


def _group(it: dict) -> str:
    """Census references and the older demo items are rebuilt apart."""
    return "census" if it.get("origin") == "census" else "demo"


def _keep_stored(name: str, rebuilt: set[tuple[str, str]], by) -> list[dict]:
    """Stored items of this version that this build does not replace, with arrays."""
    if not (DATA / f"{name}.json").is_file():
        return []
    try:
        items, A, med = load(name)
    except SystemExit:
        return []
    out = []
    for i, it in enumerate(items):
        if by(it) not in rebuilt:
            it["A"], it["med"] = A[i], med[i]
            out.append(it)
    return out


def _rejects(sid: str, agent: str | None, drops: list[float], dur: float,
             origin: str) -> list[dict]:
    """Tray-quiet windows on 0.1.0's grid, at least REJECT_GAP from every drop."""
    start, step, margin = REJECT_GRID
    out, a = [], start
    while a + margin <= dur:
        if all(abs(a - d) >= REJECT_GAP for d in drops):
            out.append({"sid": sid, "agent": agent, "slot": None, "ability": None,
                        "t": round(a, 2), "suspect": False, "fill": None,
                        "origin": origin, "source": "tray-quiet"})
        a += step
    return out


def _item_key(it: dict) -> str:
    base = f"{it['sid']}:{it['t']:.2f}:{it['slot'] or '-'}"
    return base + ("#census" if _group(it) == "census" else "")


def build_bank(demos: list[str] | None = None, matches: list[str] | None = None,
               census_sids: list[str] | None = None) -> dict:
    """Cut the demo bank (casts and reject windows) and the match windows.

    Each argument is None to leave that part as stored, an empty list for every
    session, or the sessions to rebuild; a rebuilt session replaces its stored
    items of the same group and the others stay. `census_sids` must be named.
    """
    counts: dict = {}
    if demos is not None or census_sids:
        items, n_switch, rebuilt, excluded = [], 0, set(), {}
        for sid in (demos or demo_sessions()) if demos is not None else []:
            casts, switch, drops = demo_rows(sid)
            n_switch += len(switch)
            rebuilt.add((sid, "demo"))
            if sid in UNCOVERED or not casts:
                continue
            dur = float(_dur(sid))
            # A clip the tray never watched (named times only) is not tray-quiet
            # anywhere: its other casts are simply unobserved.
            rej = [] if sid in NAMED else _rejects(sid, casts[0]["agent"], drops, dur,
                                                     "tray-quiet")
            for it in casts:
                it["kind"] = "cast"
            for it in rej:
                it["kind"] = "reject"
            _extract_demo(sid, casts + rej, dur)
            items += casts + rej
        owner = _census_owner() if census_sids else None
        for sid in census_sids or []:
            casts, out, drops = census_rows(sid, owner)
            if not drops:
                print(f"  census {sid}: the census holds no drop for this session yet; "
                      "its stored references, if any, stay")
                continue
            rebuilt.add((sid, "census"))
            for why, rows in out.items():
                excluded.setdefault(why, 0)
                excluded[why] += len(rows)
            if not casts:
                print(f"  census {sid}: no clean cast ({ {k: len(v) for k, v in out.items()} })")
                continue
            dur = float(_dur(sid))
            # No reject windows: under infinite abilities the tray shows a drop
            # for some casts only (the re-recorded demos: 15 real drops for three
            # casts of each ability), so a tray-quiet window there is not quiet.
            rej: list[dict] = []
            for it in casts:
                it["kind"] = "cast"
            for it in rej:
                it["kind"] = "reject"
            _extract_demo(sid, casts + rej, dur)
            items += casts + rej
            print(f"  census {sid} {casts[0]['agent']}: {len(casts)} casts, {len(rej)} rejects, "
                  f"excluded { {k: len(v) for k, v in out.items() if v} }")
            for it in casts:
                print(f"    kept {it['slot']} {it['ability']:<16} t {it['t']:>6.2f} "
                      f"refined {it['t_refined']} verdict {it['tray_verdict']}"
                      f"{' forced' if it['forced'] else ''}")
            for why, rows in out.items():
                for c in rows:
                    t = c["t_ms"] / 1000 if "t_ms" in c else c["t"]
                    print(f"    left out ({why}) {c['slot']} {c.get('ability')} "
                          f"t {t:.2f}: {c.get('tray_verdict_reason') or ''}")
        for it in items:
            it["key"] = _item_key(it)
        kept = _keep_stored("demo_bank", rebuilt, lambda it: (it["sid"], _group(it)))
        items = kept + items
        _save("demo_bank", items)
        counts.update({"demo_casts": sum(it["kind"] == "cast" and _group(it) == "demo"
                                         for it in items),
                       "demo_rejects": sum(it["kind"] == "reject" and _group(it) == "demo"
                                           for it in items),
                       "census_casts": sum(it["kind"] == "cast" and _group(it) == "census"
                                           for it in items),
                       "demo_switch_excluded": n_switch,
                       **{f"census_excluded_{k}": v for k, v in excluded.items()}})
    if matches is not None:
        items, skipped, rebuilt = [], {}, set()
        for sid in matches or match_sessions():
            rebuilt.add(sid)
            agent, why = player_agent(sid)
            if agent is None:
                skipped[sid] = why
                continue
            casts, drops, times = match_rows(sid, agent)
            for it in casts:
                it["kind"] = "cast"
            rng = np.random.default_rng(zlib.crc32(sid.encode()))
            cand = []
            for lo, hi in live_spans(sid, drops):
                for a in np.arange(lo, hi, 1.0):
                    if all(abs(a - d) >= REJECT_GAP for d in times):
                        cand.append(float(a))
            pick = sorted(rng.choice(cand, size=min(NULL_PER_SESSION, len(cand)),
                                     replace=False)) if cand else []
            nulls = [{"sid": sid, "agent": agent, "slot": None, "ability": None,
                      "t": round(float(a), 2), "key": f"{sid}:{int(a * 1000)}:-",
                      "kind": "null", "player_cast": False, "labelled": False}
                     for a in pick]
            _extract(sid, casts + nulls)
            items += casts + nulls
            print(f"  {sid} {agent}: {len(casts)} casts, {len(nulls)} null windows")
        items = _keep_stored("match_windows", rebuilt, lambda it: it["sid"]) + items
        _save("match_windows", items)
        counts.update({"match_casts": sum(it["kind"] == "cast" for it in items),
                       "match_player_casts": sum(it.get("player_cast", False) for it in items),
                       "match_labelled": sum(it.get("labelled", False) for it in items),
                       "match_null": sum(it["kind"] == "null" for it in items),
                       "match_sessions": len({it["sid"] for it in items}),
                       "match_skipped": len(skipped)})
        for sid, why in skipped.items():
            print(f"  skipped {sid}: {why}")
    return counts


def inventory() -> dict:
    """Counts of what the stored bank and match windows hold."""
    bank, A, med = load("demo_bank")
    q, _A, _m = load("match_windows")
    casts = [it for it in bank if it["kind"] == "cast" and _group(it) == "demo"]
    classes = {_cls(it) for it in casts}
    per = {}
    for it in casts:
        per[_cls(it)] = per.get(_cls(it), 0) + 1
    switch = sum(len(demo_rows(s)[1]) for s in demo_sessions())
    refs = refs_from(bank, A, med)
    by_phase = {}
    for i, ph, _s in refs["rows"]:
        g = _group(bank[i])
        by_phase[f"{g}_{ph}_templates"] = by_phase.get(f"{g}_{ph}_templates", 0) + 1
    return {"demo_casts": len(casts), "demo_named": sum(it["fill"] is None for it in casts),
            "demo_suspect": sum(it["suspect"] for it in casts),
            "demo_rejects": sum(it["kind"] == "reject" and _group(it) == "demo" for it in bank),
            "demo_switch_excluded": switch,
            "demo_sessions": len({it["sid"] for it in casts}),
            "bank_classes": len(classes),
            "bank_classes_single": sum(v == 1 for v in per.values()),
            "census_casts": sum(it["kind"] == "cast" and _group(it) == "census" for it in bank),
            "census_sessions": len({it["sid"] for it in bank if _group(it) == "census"}),
            **by_phase,
            "kit_abilities": sum(len(kit(a)) for a in _agents()),
            "match_casts": sum(it["kind"] == "cast" for it in q),
            "match_player_casts": sum(bool(it.get("player_cast")) for it in q),
            "match_labelled": sum(bool(it.get("labelled")) for it in q),
            "match_labelled_player_cast": sum(bool(it.get("labelled") and it.get("player_cast"))
                                              for it in q),
            "match_across_gap": sum(bool(it.get("player_cast") and it.get("across_gap"))
                                    for it in q),
            "match_null": sum(it["kind"] == "null" for it in q),
            "match_sessions": len({it["sid"] for it in q}),
            # The labeller's own ability string beside the reference's name for
            # the slot, ignoring case. Truth here is the slot either way.
            "label_ability_mismatch": sum(1 for it in q if it.get("labelled")
                                          and (it["label_ability"] or "").lower()
                                          != (it["ability"] or "").lower())}


def _dur(sid: str) -> float:
    import av
    with av.open(_manifest(sid)["source"]["path"]) as c:
        st = c.streams.audio[0]
        return float(st.duration * st.time_base) if st.duration else c.duration / 1e6


def _extract_demo(sid: str, items: list[dict], dur: float) -> None:
    """A demo is short, so its whole audio decodes once."""
    path = _manifest(sid)["source"]["path"]
    t0, x, filled, rate = next(read_spans(path, [(0.0, dur)]))
    for it in items:
        it["A"], it["med"], it["pad"] = features(x, filled, rate, t0, it["t"])


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _frame(s: float) -> int:
    """Window frame of a time relative to the drop."""
    return int(round((s + PRE) / HOP))


def onset_curve(W: np.ndarray) -> np.ndarray:
    """Band-summed positive 20 ms rise of the median-removed log-mel."""
    d = np.maximum(W[2:] - W[:-2], 0).sum(1)
    return np.concatenate([[0.0, 0.0], d])


def ongoing_rise(W: np.ndarray, start: int) -> float:
    """dB above the context median of a sustained sound in the ongoing template:
    the mean of the top quarter of the per-band medians over its frames."""
    seg = W[start:start + T_ONGOING]
    if len(seg) < T_ONGOING:
        return float("nan")
    return float(np.sort(np.median(seg, axis=0))[-BANDS // 4:].mean())


def phase_starts(W: np.ndarray, onset: list[float] | None = None,
                 rises: dict | None = None) -> dict[str, int]:
    """Template start frame of each phase of one reference.

    `cast` starts LEAD before the largest onset where the tray allows the cast
    (`onset`, seconds from the drop, else CAST_ONSET); `equip` before the
    largest onset at least EQUIP_GAP earlier, if the window holds one;
    `ongoing` ONGOING_OFFSET after the cast start, if its sound stands
    ONGOING_MIN_DB above the context [domain:abilities/ability-sound-phases].
    The tray drop does not say which onset is which for an ability whose drop
    is its equip [domain:abilities/deadlock-ult-tray-drop-at-equip], or for a
    bolt charged before release [domain:abilities/sova-bolt-charge-and-bounce].
    `rises`, if given, receives the ongoing rise whether or not it passed.
    """
    f = onset_curve(W)
    lead = int(round(LEAD / HOP))
    lo, hi = _frame((onset or CAST_ONSET)[0]), _frame((onset or CAST_ONSET)[1])
    lo, hi = max(lo, lead), min(hi, FRAMES - T + lead)
    if lo > hi:
        lo, hi = _frame(CAST_ONSET[0]), _frame(CAST_ONSET[1])
    cast = lo + int(np.argmax(f[lo:hi + 1]))
    out = {"cast": min(max(cast - lead, 0), FRAMES - T)}
    ehi = cast - int(round(EQUIP_GAP / HOP))
    if ehi - lead > 5:
        eq = lead + int(np.argmax(f[lead:ehi]))
        if f[eq] >= EQUIP_MIN * f[cast]:
            out["equip"] = eq - lead
    on = out["cast"] + int(round(ONGOING_OFFSET / HOP))
    rise = ongoing_rise(W, on)
    if rises is not None:
        rises["ongoing"] = rise
    if np.isfinite(rise) and rise >= ONGOING_MIN_DB:
        out["ongoing"] = on
    return out


#: Query template starts each phase may take, from its onset range. The
#: ongoing template follows the cast start by ONGOING_OFFSET, so its lags do.
_LEADF = int(round(LEAD / HOP))
LAGS = {"cast": (_frame(CAST_ONSET[0]) - _LEADF, _frame(CAST_ONSET[1]) - _LEADF),
        "equip": (0, _frame(-EQUIP_GAP) - _LEADF)}
LAGS["ongoing"] = tuple(x + int(round(ONGOING_OFFSET / HOP)) for x in LAGS["cast"])


def _z(M: np.ndarray) -> np.ndarray:
    M = M - M.mean(-1, keepdims=True)
    return M / (np.linalg.norm(M, axis=-1, keepdims=True) + 1e-9)


def refs_from(items, A, med) -> dict:
    """Phase templates of every bank cast, median-removed and absolute, grouped
    by phase because the ongoing template is longer. `rows[j]` is (item, phase,
    start frame) of template j; `rise[j]` its ongoing rise."""
    rows, rise, by = [], [], {}
    for i, it in enumerate(items):
        if it["kind"] != "cast":
            continue
        W = A[i] - med[i]
        r: dict = {}
        for ph, s in phase_starts(W, it.get("cast_onset"), r).items():
            L = _tlen(ph)
            d = by.setdefault(ph, {"idx": [], "tm": [], "ta": []})
            d["idx"].append(len(rows))
            d["tm"].append(W[s:s + L])
            d["ta"].append(A[i][s:s + L])
            rows.append((i, ph, s))
            rise.append(r.get("ongoing", float("nan")))
    for d in by.values():
        tm, ta = np.stack(d["tm"]), np.stack(d["ta"])
        flat = tm.reshape(len(tm), -1)
        d.update({"idx": np.asarray(d["idx"]), "tm": tm, "ta": ta, "z": _z(flat),
                  "loud": flat > np.percentile(flat, 70, axis=1, keepdims=True)})
    return {"rows": rows, "rise": rise, "phases": by}


def score_query(Aq: np.ndarray, medq: np.ndarray, refs: dict, only=None,
                tol: float = 3.0, step: int = 2) -> np.ndarray:
    """[n_templates, len(SCORES) + 2]: each template's best score over its
    phase's lags, the best-correlation lag, and the unbounded gain (absolute
    dB) there. Templates outside `only` stay NaN."""
    W = Aq - medq
    out = np.full((len(refs["rows"]), len(SCORES) + 2), np.nan, np.float32)
    for ph, d in refs["phases"].items():
        sel = [k for k, j in enumerate(d["idx"]) if only is None or only[j]]
        if not sel:
            continue
        L = _tlen(ph)
        win = np.lib.stride_tricks.sliding_window_view(W, (L, BANDS))[:, 0]
        wia = np.lib.stride_tricks.sliding_window_view(Aq, (L, BANDS))[:, 0]
        lo, hi = LAGS[ph]
        lags = np.arange(lo, min(hi, len(win) - 1) + 1)
        g = np.arange(0, len(lags), step)
        flat = win[lags].reshape(len(lags), -1)
        flata = wia[lags].reshape(len(lags), -1)
        C = _z(flat) @ d["z"][sel].T                       # [lags, selected templates]
        for c_i, k in enumerate(sel):
            j = d["idx"][k]
            loud = d["loud"][k]
            tm, ta = d["tm"][k].reshape(-1)[loud], d["ta"][k].reshape(-1)[loud]
            D = flat[g][:, loud] - tm
            gg = np.clip(np.percentile(D, 20, axis=1), -tol, tol)
            cov = ((D - gg[:, None]) >= -tol).mean(1)
            Da = flata[g][:, loud] - ta
            ga = np.clip(np.percentile(Da, 20, axis=1), -tol, tol)
            cova = ((Da - ga[:, None]) >= -tol).mean(1)
            c = C[g, c_i]
            b = int(np.argmax(C[:, c_i]))
            gain = float(np.median(flata[b][loud] - ta))
            out[j] = (C[:, c_i].max(), cov.max(), (np.clip(c, 0, None) * cov).max(),
                      cova.max(), (np.clip(c, 0, None) * cova).max(), int(lags[b]), gain)
    return out


def _template_ids(bank: list[dict], refs: dict) -> list[str]:
    return [f"{bank[i]['key']}|{ph}|{s}" for i, ph, s in refs["rows"]]


def scores(name: str, rescore: bool = False):
    """(query items, bank items, templates, [queries, templates, cols]).

    Scored against every template in the bank and cached by query key and
    template id, so a census session added to the bank scores only its own
    templates; `bank_select` chooses which templates a run may use.
    """
    bank, Ab, medb = load("demo_bank")
    refs = refs_from(bank, Ab, medb)
    q, Aq, medq = (bank, Ab, medb) if name == "demo_bank" else load(name)
    f = DATA / f"scores_{name}{_tsuffix()}.npy"
    stamp = DATA / f"scores_{name}{_tsuffix()}.json"
    want = {"version": VERSION, "template_s": TEMPLATE_S, "lags": LAGS,
            "ongoing": [ONGOING_OFFSET, ONGOING_S, ONGOING_MIN_DB]}
    tid, qid = _template_ids(bank, refs), [it["key"] for it in q]
    S = np.full((len(q), len(tid), len(SCORES) + 2), np.nan, np.float32)
    known = np.zeros((len(q), len(tid)), bool)
    if not rescore and f.is_file() and stamp.is_file():
        meta = json.loads(stamp.read_text(encoding="utf-8"))
        if meta["want"] == json.loads(json.dumps(want)):
            old = np.load(f)
            oq = {k: n for n, k in enumerate(meta["queries"])}
            ot = {k: n for n, k in enumerate(meta["templates"])}
            cols = [(j, ot[t]) for j, t in enumerate(tid) if t in ot]
            if cols:
                nj, oj = map(np.asarray, zip(*cols))
                for i, k in enumerate(qid):
                    if k in oq:
                        S[i, nj] = old[oq[k], oj]
                        known[i, nj] = True
    todo = [i for i in range(len(q)) if not known[i].all()]
    if todo:
        print(f"  scoring {len(todo)} of {len(q)} {name} queries "
              f"({int((~known).sum())} query-template pairs)")
        for i in todo:
            S[i, ~known[i]] = score_query(Aq[i], medq[i], refs, ~known[i])[~known[i]]
        DATA.mkdir(parents=True, exist_ok=True)
        np.save(f, S)
        stamp.write_text(json.dumps({"want": want, "queries": qid, "templates": tid}),
                         encoding="utf-8")
    return q, bank, refs, S


def bank_select(bank: list[dict], refs: dict, sessions=None, mode: str | None = None
                ) -> tuple[np.ndarray, np.ndarray]:
    """(template mask, item mask) of the references and reject windows a run uses.

    By default the bank is 0.1.0's: every demo item, no census item. Given
    census sessions in mode `only`, each agent those sessions cast for takes
    its references only from their census items, so a slot they never cast
    has none and the kit narrows; in mode `slot` only the slots they cast
    change, so the kit keeps its four slots; in mode `add` their census items
    join the demo references. Every other agent keeps its demo references.
    The reject class is the demo rejects plus those sessions' own (none,
    today: `build_bank`).
    """
    sessions = set(BANK_SESSIONS if sessions is None else sessions)
    mode = mode or BANK_MODE
    cast_new = [it for it in bank
                if it["kind"] == "cast" and _group(it) == "census" and it["sid"] in sessions]
    new = {it["agent"] for it in cast_new} if mode == "only" else (
        {_cls(it) for it in cast_new} if mode == "slot" else set())
    use = np.zeros(len(bank), bool)
    for i, it in enumerate(bank):
        from_new = _group(it) == "census" and it["sid"] in sessions
        if it["kind"] == "reject":
            use[i] = _group(it) == "demo" or from_new
        elif (it["agent"] if mode == "only" else _cls(it)) in new:
            use[i] = from_new
        else:
            use[i] = _group(it) == "demo" or from_new
    return np.array([use[i] for i, _p, _s in refs["rows"]], bool), use


def print_sources(bank: list[dict], refs: dict, tmask: np.ndarray,
                  agents: list[str] | None = None) -> None:
    """Per agent and slot: the sessions its references come from, and per
    census reference its phases and ongoing rise."""
    per: dict = {}
    for j, (i, ph, _s) in enumerate(refs["rows"]):
        if not tmask[j]:
            continue
        it = bank[i]
        slot = per.setdefault(it["agent"], {}).setdefault(it["slot"], {})
        src = slot.setdefault(f"{it['sid']}:{_group(it)}", {"casts": set(), "phases": {}})
        src["casts"].add(i)
        src["phases"][ph] = src["phases"].get(ph, 0) + 1
    print("\nreferences per agent (session:group casts phases)")
    for agent in sorted(per, key=lambda a: (agents is not None and a not in agents, a)):
        cells = []
        for slot in ("C", "Q", "E", "X"):
            srcs = per[agent].get(slot)
            cells.append(f"{slot} " + (", ".join(
                f"{s} x{len(v['casts'])} " + "/".join(f"{p[0]}{n}" for p, n in
                                                     sorted(v["phases"].items()))
                for s, v in sorted(srcs.items())) if srcs else "-"))
        print(f"  {agent:<9}" + " | ".join(cells))
    census_rows_ = sorted({i for j, (i, _p, _s) in enumerate(refs["rows"])
                           if tmask[j] and _group(bank[i]) == "census"},
                          key=lambda i: (bank[i]["sid"], bank[i]["t"]))
    if census_rows_:
        print("\ncensus references: key ability phases (start s from the drop) ongoing rise dB")
    for i in census_rows_:
        ph = {p: round(s * HOP - PRE, 2) for ii, p, s in refs["rows"] if ii == i}
        rise = next(refs["rise"][j] for j, (ii, _p, _s) in enumerate(refs["rows"]) if ii == i)
        print(f"  {bank[i]['key']:<34}{bank[i]['ability'] or '':<16}{ph}  {rise:.1f}")


#: The score declared primary in the ledger before any measurement.
PRIMARY = ("prod", "cast")
VARIANTS = [PRIMARY, ("corr", "cast"), ("cover", "cast"), ("cover_abs", "cast"),
            ("prod_abs", "cast"), ("prod", "any"), ("prod", "equip"), ("corr", "equip"),
            ("prod", "ongoing"), ("corr", "ongoing")]
#: Confusions printed and recorded on the verified casts.
CONFUSIONS = [PRIMARY, ("corr", "cast"), ("prod_abs", "cast"), ("corr", "ongoing"),
              ("prod", "ongoing")]


def _cls(it: dict) -> tuple[str, str]:
    return (it["agent"], it["slot"])


def class_best(Sq: np.ndarray, refs: dict, bank: list[dict], variant, valid=None
               ) -> dict[tuple[str, str], tuple[float, int]]:
    """{(agent, slot): (best score, template index)} for one query."""
    col = SCORES.index(variant[0])
    out: dict = {}
    for j, (i, ph, _s) in enumerate(refs["rows"]):
        if variant[1] != "any" and ph != variant[1]:
            continue
        if valid is not None and not valid[j]:
            continue
        v = float(Sq[j, col])
        k = _cls(bank[i])
        if np.isfinite(v) and (k not in out or v > out[k][0]):
            out[k] = (v, j)
    return out


def _top(best: dict, agent: str | None = None):
    c = {k: v for k, v in best.items() if agent is None or k[0] == agent}
    if not c:
        return None, float("nan")
    k = max(c, key=lambda k: c[k][0])
    return k, c[k][0]


def _field(agent: str, slot: str | None = None) -> str:
    a = agent.replace("/", "")
    return a if slot is None else f"{a}_{slot}"


def threshold(variant, demo, tmask, imask) -> tuple[float, list[float]]:
    """The REJECT_PCT percentile of the selected reject class's best score."""
    q, bank, refs, S = demo
    null = [_top(class_best(S[i], refs, bank, variant, tmask))[1]
            for i, it in enumerate(q) if it["kind"] == "reject" and imask[i]]
    null = [x for x in null if np.isfinite(x)]
    return (float(np.percentile(null, REJECT_PCT)) if null else float("nan")), null


def _deps() -> dict:
    return {"version": VERSION, "primary": list(PRIMARY), "template_s": TEMPLATE_S,
            "reject_pct": REJECT_PCT, "loo_gap": LOO_GAP, "pre": PRE, "post": POST,
            "ongoing": [ONGOING_OFFSET, ONGOING_S, ONGOING_MIN_DB],
            "bank_sessions": list(BANK_SESSIONS), "bank_mode": BANK_MODE if BANK_SESSIONS else None}


def retrieve(record: bool = False, rescore: bool = False, within: bool = False) -> dict:
    """Leave-one-cast-out over the selected bank, per (agent, slot).

    `within` asks only the bank sessions' own casts, so each is named by the
    other casts of its session (and, in mode `add`, the older demos).
    """
    demo = scores("demo_bank", rescore)
    q, bank, refs, S = demo
    tmask, imask = bank_select(bank, refs)
    print_sources(bank, refs, tmask)
    rsid = np.array([bank[i]["sid"] for i, _p, _s in refs["rows"]])
    rt = np.array([bank[i]["t"] for i, _p, _s in refs["rows"]])
    casts = [i for i, it in enumerate(q) if it["kind"] == "cast" and imask[i]
             and (not within or (_group(it) == "census" and it["sid"] in BANK_SESSIONS))]
    if within:
        print("\nwithin the bank sessions, leave-one-cast-out: query, kit top-1 per variant")
        for i in casts:
            it = q[i]
            valid = tmask & ~((rsid == it["sid"]) & (np.abs(rt - it["t"]) < LOO_GAP))
            picks, answerable = [], _cls(it) in class_best(S[i], refs, bank, PRIMARY, valid)
            for variant in (PRIMARY, ("corr", "cast"), ("corr", "ongoing")):
                kt, ks = _top(class_best(S[i], refs, bank, variant, valid), it["agent"])
                picks.append(f"{variant[0]}/{variant[1]} {kt[1] if kt else '-'} {ks:.2f}")
            print(f"  {it['key']:<34}{it['slot']} {it['ability']:<16}"
                  f"{'answerable' if answerable else 'no other ref':<14}" + "  ".join(picks))
    summary, per = {}, {}
    for variant in VARIANTS:
        theta, null = threshold(variant, demo, tmask, imask)
        v = {"n": len(casts), "answerable": 0, "kit_hits": 0, "all_hits": 0,
             "cross_answerable": 0, "cross_kit_hits": 0, "above_threshold": 0}
        trues = []
        for i in casts:
            it = q[i]
            same = rsid == it["sid"]
            valid = tmask & ~(same & (np.abs(rt - it["t"]) < LOO_GAP))
            best = class_best(S[i], refs, bank, variant, valid)
            k = _cls(it)
            row = per.setdefault(variant, {}).setdefault(k, {"n": 0, "answerable": 0,
                                                             "kit_hits": 0, "all_hits": 0,
                                                             "true": [], "rival": []})
            row["n"] += 1
            if k not in best:
                continue
            v["answerable"] += 1
            row["answerable"] += 1
            kit_top = _top(best, it["agent"])[0]
            all_top = _top(best)[0]
            v["kit_hits"] += kit_top == k
            v["all_hits"] += all_top == k
            row["kit_hits"] += kit_top == k
            row["all_hits"] += all_top == k
            trues.append(best[k][0])
            v["above_threshold"] += best[k][0] >= theta
            row["true"].append(best[k][0])
            row["rival"].append(max((s for kk, (s, _j) in best.items() if kk != k),
                                    default=float("nan")))
            cross = class_best(S[i], refs, bank, variant, tmask & ~same)
            if k in cross:
                v["cross_answerable"] += 1
                v["cross_kit_hits"] += _top(cross, it["agent"])[0] == k
        v.update({"kit_top1": round(v["kit_hits"] / max(v["answerable"], 1), 3),
                  "all_top1": round(v["all_hits"] / max(v["answerable"], 1), 3),
                  "true_median": round(float(np.median(trues)), 3) if trues else None,
                  "reject_n": len(null), "reject_p95": round(theta, 3),
                  "reject_median": round(float(np.median(null)), 3) if null else None,
                  "classes": len({_cls(bank[i]) for j, (i, _p, _s) in enumerate(refs["rows"])
                                  if tmask[j]})})
        summary[variant] = v
    _print_retrieve(summary, per)
    if record:
        from reticle import metrics
        deps = _deps() | {"within": within}
        name = "retrieve_within" if within else "retrieve"
        metrics.record("audio_bank", part=name + _suffix(), values=summary[PRIMARY],
                       deps=deps)
        metrics.record("audio_bank", part=name + "_variants" + _suffix(), deps=deps, values={
            f"{s}_{p}_{f}": summary[(s, p)][f] for (s, p) in VARIANTS
            for f in ("kit_hits", "kit_top1", "all_top1", "answerable", "reject_p95",
                      "true_median")})
        vals = {}
        for variant in (PRIMARY, ("corr", "cast")) if within else (PRIMARY,):
            pre = "" if variant == PRIMARY else f"{variant[0]}_{variant[1]}_"
            for k, row in per[variant].items():
                kk = pre + _field(*k)
                vals.update({f"{kk}_n": row["n"], f"{kk}_answerable": row["answerable"],
                             f"{kk}_kit_hits": row["kit_hits"],
                             f"{kk}_all_hits": row["all_hits"]})
        metrics.record("audio_bank", part=name + "_ability" + _suffix(), values=vals, deps=deps)
    return summary


def _print_retrieve(summary, per) -> None:
    print(f"\n{'variant':<18}{'n':>4}{'ans':>5}{'kit':>7}{'all':>7}{'x-ans':>6}{'x-kit':>6}"
          f"{'true med':>9}{'rej p95':>8}{'rej med':>8}{'>thr':>6}")
    for (s, p), v in summary.items():
        print(f"{s + '/' + p:<18}{v['n']:>4}{v['answerable']:>5}{v['kit_top1']:>7.2f}"
              f"{v['all_top1']:>7.2f}{v['cross_answerable']:>6}{v['cross_kit_hits']:>6}"
              f"{v['true_median'] if v['true_median'] is not None else float('nan'):>9.2f}"
              f"{v['reject_p95']:>8.2f}"
              f"{v['reject_median'] if v['reject_median'] is not None else float('nan'):>8.2f}"
              f"{v['above_threshold']:>6}")
    print(f"\nper (agent, slot), primary {PRIMARY}: n answerable kit-hits all-hits "
          "true-median rival-median")
    for k, row in sorted(per[PRIMARY].items()):
        if row["answerable"]:
            print(f"  {k[0]:<9}{k[1]:<3}{row['n']:>3}{row['answerable']:>4}{row['kit_hits']:>4}"
                  f"{row['all_hits']:>4}{np.median(row['true']):>7.2f}"
                  f"{np.nanmedian(row['rival']):>7.2f}")
    one = sum(1 for r in per[PRIMARY].values() if not r["answerable"])
    print(f"  {one} (agent, slot) classes have no second reference and are unanswerable")


SETS = (("verified", lambda it: it.get("labelled")),
        ("tray", lambda it: it.get("player_cast")),
        ("tray_clean", lambda it: it.get("player_cast") and not it.get("across_gap")))


def transfer(record: bool = False, rescore: bool = False) -> dict:
    """Score the match casts and null windows against the selected bank."""
    demo = scores("demo_bank", rescore)
    q, bank, refs, S = scores("match_windows", rescore)
    tmask, imask = bank_select(bank, refs)
    print_sources(bank, refs, tmask, sorted({it["agent"] for it in q}))
    out, per = {}, {}
    for variant in VARIANTS:
        theta, _null = threshold(variant, demo, tmask, imask)
        res = {}
        for name, keep in SETS:
            v = {"n": 0, "answerable": 0, "kit_hits": 0, "open_accepted": 0,
                 "open_correct": 0, "open_top_correct": 0, "agents": {}}
            for i, it in enumerate(q):
                if it["kind"] != "cast" or not keep(it):
                    continue
                best = class_best(S[i], refs, bank, variant, tmask)
                k = _cls(it)
                v["n"] += 1
                kt = _top(best, it["agent"])[0]
                ot, os_ = _top(best)
                hit = kt == k
                v["kit_hits"] += hit
                a = v["agents"].setdefault(it["agent"], [0, 0])
                a[0] += 1
                a[1] += hit
                v["answerable"] += k in best
                v["open_top_correct"] += ot == k
                if os_ >= theta:
                    v["open_accepted"] += 1
                    v["open_correct"] += ot == k
                if variant == PRIMARY:
                    row = per.setdefault(name, {}).setdefault(k, {
                        "n": 0, "kit_hits": 0, "open_accepted": 0, "open_correct": 0,
                        "true": [], "wrong": {}, "gain": []})
                    row["n"] += 1
                    row["kit_hits"] += hit
                    row["open_accepted"] += os_ >= theta
                    row["open_correct"] += (os_ >= theta) and ot == k
                    if k in best:
                        row["true"].append(best[k][0])
                        row["gain"].append(float(S[i, best[k][1], len(SCORES) + 1]))
                    if not hit and kt:
                        row["wrong"][kt[1]] = row["wrong"].get(kt[1], 0) + 1
            n = max(v["n"], 1)
            v.update({"kit_top1": round(v["kit_hits"] / n, 3),
                      "open_accept_rate": round(v["open_accepted"] / n, 3),
                      "open_precision": round(v["open_correct"] / max(v["open_accepted"], 1), 3),
                      "open_top1": round(v["open_top_correct"] / n, 3)})
            res[name] = v
        nulls = [i for i, it in enumerate(q) if it["kind"] == "null"]
        fa_all = sum(_top(class_best(S[i], refs, bank, variant, tmask))[1] >= theta
                     for i in nulls)
        fa_kit = sum(_top(class_best(S[i], refs, bank, variant, tmask), q[i]["agent"])[1]
                     >= theta for i in nulls)
        res["null"] = {"n": len(nulls), "accept_all": int(fa_all), "accept_kit": int(fa_kit),
                       "accept_all_rate": round(fa_all / max(len(nulls), 1), 3),
                       "accept_kit_rate": round(fa_kit / max(len(nulls), 1), 3),
                       "threshold": round(theta, 3)}
        out[variant] = res
    base = _majority(q)
    _print_transfer(out, per, base)
    confusion = {}
    for variant in CONFUSIONS:
        print(f"\nconfusion on the verified casts, {variant[0]}/{variant[1]} "
              "(rows true, columns kit top-1)")
        conf = confusion.setdefault(variant, {})
        for i, it in enumerate(q):
            if it["kind"] == "cast" and it.get("labelled"):
                kt = _top(class_best(S[i], refs, bank, variant, tmask), it["agent"])[0]
                row = conf.setdefault(it["agent"], {}).setdefault(it["slot"], {})
                row[kt[1] if kt else "-"] = row.get(kt[1] if kt else "-", 0) + 1
        for agent, rows in sorted(conf.items()):
            print(f"  {agent:<8}" + "  ".join(f"{s}:" + ",".join(
                f"{p}{n}" for p, n in sorted(r.items())) for s, r in sorted(rows.items())))
    if record:
        _record_transfer(out, per, base)
        from reticle import metrics
        metrics.record("audio_bank", part="confusion_verified" + _suffix(), values={
            f"{v[0]}_{v[1]}_{_field(agent, s)}_as_{p}": n
            for v, conf in confusion.items() for agent, rows in conf.items()
            for s, r in rows.items() for p, n in r.items()} | {
            f"{v[0]}_{v[1]}_{_field(agent, s)}_hits": r.get(s, 0)
            for v, conf in confusion.items() for agent, rows in conf.items()
            for s, r in rows.items()},
            deps=_deps(), note="rows true slot, columns the kit top-1 slot; verified casts only")
    return out


def _majority(q) -> dict:
    """Per-agent majority-slot rate of the verified casts, pooled."""
    by = {}
    for it in q:
        if it["kind"] == "cast" and it.get("labelled"):
            by.setdefault(it["agent"], []).append(it["slot"])
    hits = sum(max(s.count(x) for x in set(s)) for s in by.values())
    n = sum(len(s) for s in by.values())
    return {"n": n, "hits": hits, "rate": round(hits / max(n, 1), 3)}


def _print_transfer(out, per, base) -> None:
    print(f"\n{'variant':<18}{'set':<11}{'n':>4}{'ans':>5}{'kit':>6}{'open1':>6}{'acc':>5}"
          f"{'prec':>6}{'null acc all/kit':>18}{'thr':>6}")
    for (s, p), res in out.items():
        nl = res["null"]
        for name, _keep in SETS:
            v = res[name]
            print(f"{s + '/' + p:<18}{name:<11}{v['n']:>4}{v['answerable']:>5}"
                  f"{v['kit_top1']:>6.2f}{v['open_top1']:>6.2f}{v['open_accepted']:>5}"
                  f"{v['open_precision']:>6.2f}"
                  f"{nl['accept_all']:>9}/{nl['accept_kit']:<3}of {nl['n']:<4}{nl['threshold']:>6.2f}")
    agents = sorted(out[PRIMARY]["verified"]["agents"])
    print("\nkit hits per agent on the verified casts: " + "  ".join(
        f"{a} n={out[PRIMARY]['verified']['agents'][a][0]}" for a in agents))
    for (s, p), res in out.items():
        ag = res["verified"]["agents"]
        print(f"  {s + '/' + p:<18}" + "".join(f"{a:>10} {ag.get(a, [0, 0])[1]:>3}"
                                              for a in agents))
    print(f"\nmajority-slot rate on the verified casts: {base['hits']}/{base['n']} = {base['rate']}")
    for name in ("verified", "tray"):
        print(f"\nper ability, primary, {name}: n kit-hits recall accepted correct "
              "true-median gain-median  wrong-as")
        for k, r in sorted(per.get(name, {}).items()):
            print(f"  {k[0]:<9}{k[1]:<3}{r['n']:>4}{r['kit_hits']:>5}{r['kit_hits'] / r['n']:>7.2f}"
                  f"{r['open_accepted']:>5}{r['open_correct']:>5}"
                  f"{np.median(r['true']) if r['true'] else float('nan'):>8.2f}"
                  f"{np.median(r['gain']) if r['gain'] else float('nan'):>8.1f}  {r['wrong']}")


def _record_transfer(out, per, base) -> None:
    from reticle import metrics
    deps = _deps()
    res = out[PRIMARY]
    vals = {f"{name}_{f}": res[name][f] for name, _k in SETS
            for f in ("n", "answerable", "kit_hits", "kit_top1", "open_top1", "open_accepted",
                      "open_correct", "open_precision")}
    vals.update({f"verified_{_field(a)}_{f}": x for a, (n, h) in res["verified"]["agents"].items()
                 for f, x in (("n", n), ("kit_hits", h))})
    vals.update({f"null_{f}": res["null"][f] for f in res["null"]})
    vals.update({"majority_hits": base["hits"], "majority_rate": base["rate"]})
    metrics.record("audio_bank", part="transfer" + _suffix(), values=vals, deps=deps)
    metrics.record("audio_bank", part="transfer_variants" + _suffix(), deps=deps, values={
        f"{s}_{p}_{name}_{f}": out[(s, p)][name][f] for (s, p) in VARIANTS
        for name in ("verified", "tray") for f in ("kit_hits", "kit_top1", "answerable",
                                                    "open_accepted")} | {
        f"{s}_{p}_verified_{_field(a)}_kit_hits": h for (s, p) in VARIANTS
        for a, (_n, h) in out[(s, p)]["verified"]["agents"].items()} | {
        f"{s}_{p}_null_accept_all": out[(s, p)]["null"]["accept_all"] for (s, p) in VARIANTS})
    for name in ("verified", "tray"):
        vals = {}
        for k, r in per[name].items():
            kk = _field(*k)
            vals.update({f"{kk}_n": r["n"], f"{kk}_kit_hits": r["kit_hits"],
                         f"{kk}_open_accepted": r["open_accepted"],
                         f"{kk}_open_correct": r["open_correct"]})
            if r["gain"]:
                vals[f"{kk}_gain_median"] = round(float(np.median(r["gain"])), 1)
        metrics.record("audio_bank", part=f"transfer_ability_{name}" + _suffix(), values=vals,
                       deps=deps)
    g = [x for r in per["verified"].values() for x in r["gain"]]
    metrics.record("audio_bank", part="gain" + _suffix(), deps=deps, values={
        "n": len(g), "median": round(float(np.median(g)), 1),
        "q25": round(float(np.percentile(g, 25)), 1), "q75": round(float(np.percentile(g, 75)), 1),
        "within_3db": sum(abs(x) <= 3 for x in g)})


#: Box colours (BGR) of each phase's template on a plot.
PHASE_BGR = {"cast": (0, 255, 0), "equip": (255, 255, 0), "ongoing": (0, 200, 255)}


def explain_failure(key: str, variant=PRIMARY, out: str | None = None) -> Path:
    """Render a match query beside its best true-class and best rival references."""
    q, bank, refs, S = scores("match_windows")
    _qi, Aq, medq = load("match_windows")
    _b, Ab, medb = load("demo_bank")
    tmask, _imask = bank_select(bank, refs)
    i = next(n for n, it in enumerate(q) if it["key"] == key)
    it = q[i]
    best = class_best(S[i], refs, bank, variant, tmask)
    k = _cls(it)
    kt = _top(best, it["agent"])[0]
    col = SCORES.index(variant[0])
    marks, refrows = [], []
    for name, cls in (("true", k), ("pick", kt)):
        if cls in best:
            j = best[cls][1]
            bi, ph, s = refs["rows"][j]
            marks.append((int(S[i, j, len(SCORES)]), _tlen(ph), PHASE_BGR[ph]))
            refrows.append((f"{name}: {bank[bi]['key']} {cls[0]} {cls[1]} {bank[bi]['ability']} "
                            f"{ph} {variant[0]}={S[i, j, col]:.2f} corr={S[i, j, 0]:.2f} "
                            f"gain={S[i, j, len(SCORES) + 1]:.1f}dB",
                            Ab[bi] - medb[bi], [(s, _tlen(ph), PHASE_BGR[ph])]))
    rows = [(f"{key} query {it['agent']} {it['slot']} {it['ability']}"
             f" {'verified' if it.get('labelled') else 'tray'}"
             f"{' across_gap' if it.get('across_gap') else ''}", Aq[i] - medq[i], marks)]
    return render_rows(rows + refrows, DATA / "plots" / (
        out or f"explain-{key.replace(':', '_')}_{variant[0]}_{variant[1]}{_suffix()}.png"))


# ---------------------------------------------------------------------------
# Looking
# ---------------------------------------------------------------------------

def render_rows(rows: list[tuple[str, np.ndarray, list]], out: Path, sx: int = 2,
                sy: int = 3) -> Path:
    """One median-removed window per row, low bands at the bottom.

    Magenta marks the tray drop; the half second before it, where the cast
    lies, is underlined. Each mark is a template box (start frame, length,
    colour): green cast, cyan equip, orange ongoing. Ticks every 0.5 s.
    """
    import cv2
    imgs = []
    for label, W, marks in rows:
        v = np.clip((W + 6.0) / 36.0, 0, 1).T[::-1]      # -6..+30 dB over the median
        img = cv2.applyColorMap((v * 255).astype(np.uint8), cv2.COLORMAP_MAGMA)
        img = cv2.resize(img, (W.shape[0] * sx, W.shape[1] * sy),
                         interpolation=cv2.INTER_NEAREST)
        h = img.shape[0]
        x = _frame(0.0) * sx
        cv2.line(img, (x, 0), (x, h), (255, 0, 255), 1)
        cv2.line(img, (_frame(-0.5) * sx, h - 2), (x, h - 2), (255, 0, 255), 2)
        for s, length, col in marks:
            cv2.rectangle(img, (int(s) * sx, 1), ((int(s) + length) * sx, h - 4), col, 1)
        for k in range(0, W.shape[0] + 1, 50):
            cv2.line(img, (k * sx, h - 8), (k * sx, h), (200, 200, 200), 1)
        cv2.putText(img, label, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255),
                    1, cv2.LINE_AA)
        imgs.append(img)
    grid = np.vstack([np.vstack([im, np.full((4, im.shape[1], 3), 60, np.uint8)])
                      for im in imgs])
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), grid)
    return out


def sheet(name: str, keys: list[str] | None = None, sids: list[str] | None = None,
          out: str | None = None) -> Path:
    """Render stored windows by key or by session, with their phase templates."""
    items, A, med = load(name)
    rows = []
    for i, it in enumerate(items):
        if (keys and it["key"] not in keys) or (sids and it["sid"] not in sids):
            continue
        W = A[i] - med[i]
        r: dict = {}
        starts = phase_starts(W, it.get("cast_onset"), r) if it["kind"] == "cast" else {}
        marks = [(s, _tlen(ph), PHASE_BGR[ph]) for ph, s in starts.items()]
        label = (f"{it['key']} {it['kind']} {it.get('agent')} {it.get('slot') or ''} "
                 f"{it.get('ability') or ''}{' suspect' if it.get('suspect') else ''}"
                 f"{' pad' + str(it['pad']) if it.get('pad') else ''}"
                 f"{' rise %.1f' % r['ongoing'] if 'ongoing' in r else ''}")
        rows.append((label, W, marks))
    tag = "-".join(sids) if sids and len(sids) <= 2 else ""
    return render_rows(rows, DATA / "plots" / (out or f"sheet-{name}{'-' + tag if tag else ''}.png"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="cut windows; with no part named, the demos and matches")
    b.add_argument("--demos", nargs="*", help="the cast-cache demos (none named: all)")
    b.add_argument("--matches", nargs="*", help="the match sessions (none named: all)")
    b.add_argument("--census", nargs="+", help="census sessions whose casts join the bank")
    b.add_argument("--record", action="store_true")
    s = sub.add_parser("sheet")
    s.add_argument("name", choices=("demo_bank", "match_windows"))
    s.add_argument("--keys", nargs="*")
    s.add_argument("--sids", nargs="*")
    s.add_argument("--out")
    for name in ("retrieve", "transfer", "explain", "sources"):
        p = sub.add_parser(name)
        if name == "explain":
            p.add_argument("keys", nargs="+")
            p.add_argument("--score", default=PRIMARY[0], choices=SCORES)
            p.add_argument("--phase", default=PRIMARY[1], choices=PHASES + ("any",))
        elif name != "sources":
            p.add_argument("--record", action="store_true")
            p.add_argument("--rescore", action="store_true")
        p.add_argument("--template", type=float, default=TEMPLATE_S)
        g = p.add_mutually_exclusive_group()
        g.add_argument("--bank-sessions", nargs="+",
                       help="census sessions whose references replace their agents'")
        g.add_argument("--bank-slot", nargs="+",
                       help="census sessions whose references replace the slots they cast")
        g.add_argument("--bank-add", nargs="+",
                       help="census sessions whose references join their agents'")
        p.add_argument("--tag", help="metric-part tag (default rerec, slot or both)")
        if name == "retrieve":
            p.add_argument("--within", action="store_true",
                           help="ask only the bank sessions' own casts")
    c = sub.add_parser("census")
    c.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    if getattr(a, "template", None):
        set_template(a.template)
    if getattr(a, "bank_sessions", None):
        set_bank(a.bank_sessions, a.tag, "only")
    elif getattr(a, "bank_slot", None):
        set_bank(a.bank_slot, a.tag, "slot")
    elif getattr(a, "bank_add", None):
        set_bank(a.bank_add, a.tag, "add")
    if getattr(a, "within", False) and not BANK_SESSIONS:
        raise SystemExit("--within needs --bank-sessions, --bank-slot or --bank-add")
    if a.cmd == "census":
        counts = inventory()
        print(json.dumps(counts, indent=1))
        if a.record:
            from reticle import metrics
            metrics.record("audio_bank", part="build" + SERIES, values=counts, deps=_deps())
    elif a.cmd == "retrieve":
        retrieve(a.record, a.rescore, a.within)
    elif a.cmd == "transfer":
        transfer(a.record, a.rescore)
    elif a.cmd == "explain":
        for k in a.keys:
            print(explain_failure(k, (a.score, a.phase)))
    elif a.cmd == "sources":
        bank, A, med = load("demo_bank")
        refs = refs_from(bank, A, med)
        tmask, _imask = bank_select(bank, refs)
        print_sources(bank, refs, tmask)
    elif a.cmd == "build":
        named = a.demos is not None or a.matches is not None or a.census
        demos = a.demos if named else []
        matches = a.matches if named else []
        counts = build_bank(demos, matches, a.census)
        print(json.dumps(counts))
        bank, A, med = load("demo_bank")
        refs = refs_from(bank, A, med)
        print_sources(bank, refs, np.ones(len(refs["rows"]), bool))
        if a.record:
            from reticle import metrics
            metrics.record("audio_bank", part="build" + SERIES, deps=_deps(),
                           values=inventory() | {k: v for k, v in counts.items()
                                                 if k.startswith("census_excluded")})
    elif a.cmd == "sheet":
        print(sheet(a.name, a.keys, a.sids, a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
