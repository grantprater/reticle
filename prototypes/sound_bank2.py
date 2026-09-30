r"""Rebuild the sound bank from both range clips and score it on the range and the Iso match.

    .\.venv\Scripts\python.exe prototypes\sound_bank2.py features
    .\.venv\Scripts\python.exe prototypes\sound_bank2.py range [--record]
    .\.venv\Scripts\python.exe prototypes\sound_bank2.py overlap [--record]
    .\.venv\Scripts\python.exe prototypes\sound_bank2.py detect
    .\.venv\Scripts\python.exe prototypes\sound_bank2.py match [--record]

Why this exists
---------------
Bank v1 (`sound_bank.py` 0.1.0, one range clip) failed in match audio
(`sound_match.py`): its footsteps agreed with the self audio circle at chance,
and its knife template scored Classic equips, Vandal shots and jumps near 0.87
because the whole-patch z-score let the spectral tilt carry most of a patch's
variance. Bank v2 takes its references from the player's verified labels on
both range clips, the first (a01863947bab, `C:\Users\grant\Videos\2026-09-29
18-50-03.mp4`) and the second (9eb0960b1eff, `C:\Users\grant\Videos\2026-09-30
13-15-03.mp4`), read through `sound_labels.py`'s structured file. It adds
eight guns' equips and shots, one reload class per gun (empty and partial
reloads pooled), and Iso's abilities by phase
[domain:abilities/ability-sound-phases]: Contingency equip, cast and fade-out
[domain:abilities/iso-contingency-sound-phases], Undercut equip and cast
[domain:abilities/iso-undercut-sound-phases], Double Tap cast and fade-out
[domain:abilities/iso-double-tap-sound-phases], Kill Contract's two equip
parts and cast [domain:abilities/iso-kill-contract-sound-phases]. A Sheriff
shot keeps its lingering tail [domain:weapons/sheriff-shot-lingering-fade]
and its reload is two parts [domain:weapons/sheriff-reload-two-part]; the
drop class holds the next item's equip [domain:weapons/drop-with-equip-sound];
a landing can be silent [domain:abilities/silent-landing]. The player's
"nothing" and "silent" rows are negative evidence: every class is scored at
them.

Front ends
----------
All three share the features (`sound_bank.features`: log-mel dB above a +-4 s
context median, floored at 0) and the reference cut (class length, 20 ms lead);
they differ in how a reference is compared with a window:

- `f0_patch_z`: v1's whole-patch z-scored correlation.
- `f1_tilt_free`: each band's mean over the patch removed from both first, so
  the tilt carries nothing.
- `f2_band_z`: each band z-scored within the patch and correlated alone; the
  score is the mean over the reference's active bands (sd >= 0.25 dB), a band
  flat in the window contributing 0.

The choice and the detection threshold are made on the range labels only, by
the rule logged in the store's `notes/predictions.jsonl` under
`bank-v2-20260930` before any score was computed.

Stages
------
`features` decodes each range clip's audio in memory (as `sound_demo` does
for snippets) and caches its features under `<store>/analysis/sound-bank-v2/`.
`range` scores every reference over both clips leave-one-out (a reference
never scores within its own event's span) for every front end; `overlap`
scores each knife reference against every other reference; `detect` runs the
chosen bank over the Iso match's cached audio (4f207c0c4e39, `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`), round by round; `match`
scores those detections with `sound_match.circle`'s witnesses unchanged, plus
reloads against HUD refills and Iso casts against the tray.

Correlations run on the GPU (torch, float64) when one is present. The
instrument: `f0_patch_z` reproduces `sound_bank.slide_corr` to 1e-11, `f1`
and `f2` match a brute-force window score to 1e-12, and v1's references
through `patch_score` give `sound_match knife`'s medians exactly
([metric:sound_bank2/overlap@a01863947bab+9eb0960b1eff#v1refs_f0_patch_z_knife_vs_classic_equip_median=0.886]).
Sensitivity runs (`--fe`, `--theta`) write `match-<fe>-<theta>/` and record
under `match_sensitivity`; they never change the choice.

Findings (2026-09-30)
---------------------
The range chose v1's front end. Macro AUC is
[metric:sound_bank2/range@a01863947bab+9eb0960b1eff#f0_patch_z_macro_auc=0.929]
for f0 against
[metric:sound_bank2/range@a01863947bab+9eb0960b1eff#f1_tilt_free_macro_auc=0.9161]
for f1 and [metric:sound_bank2/range@a01863947bab+9eb0960b1eff#f2_band_z_macro_auc=0.9161]
for f2, which lose on the reloads, the Sheriff equip, the buy-menu select and
purchase, classes whose own events score below their negatives. The rule
kept f0 at theta [metric:sound_bank2/range@a01863947bab+9eb0960b1eff#chosen_theta=0.85].
Two readings favour f2 and were not the rule: its best detection F1 is
[metric:sound_bank2/range@a01863947bab+9eb0960b1eff#f2_band_z_best_f1=0.6078]
against [metric:sound_bank2/range@a01863947bab+9eb0960b1eff#f0_patch_z_best_f1=0.4971],
and the no-sound rows' best score has median
[metric:sound_bank2/range@a01863947bab+9eb0960b1eff#f2_band_z_no_sound_max_median=0.327]
against [metric:sound_bank2/range@a01863947bab+9eb0960b1eff#f0_patch_z_no_sound_max_median=0.5354].
On the range f0 names the class at the onset for
[metric:sound_bank2/range@a01863947bab+9eb0960b1eff#f0_patch_z_micro_onset_acc=0.8444]
of events: every knife equip
([metric:sound_bank2/range@a01863947bab+9eb0960b1eff#knife_equip_onset_right=27]
of 27), every Iso phase class at least half its events, and no reload
([metric:sound_bank2/range@a01863947bab+9eb0960b1eff#sheriff_reload_onset_right=0]
of 4 for the Sheriff): each gun has one empty and one partial reload, and the
class length caps at 1.0 s.

The knife still overlaps under f0: against Classic equips
[metric:sound_bank2/overlap@a01863947bab+9eb0960b1eff#f0_patch_z_knife_vs_classic_equip_median=0.884],
jumps [metric:sound_bank2/overlap@a01863947bab+9eb0960b1eff#f0_patch_z_knife_vs_jump_median=0.845],
Vandal singles [metric:sound_bank2/overlap@a01863947bab+9eb0960b1eff#f0_patch_z_knife_vs_vandal_single_median=0.836],
drops [metric:sound_bank2/overlap@a01863947bab+9eb0960b1eff#f0_patch_z_knife_vs_drop_median=0.935]
(a drop holds the next item's equip), against
[metric:sound_bank2/overlap@a01863947bab+9eb0960b1eff#f0_patch_z_knife_vs_knife_equip_median=0.963]
for another knife. f2 lowers the Classic match to
[metric:sound_bank2/overlap@a01863947bab+9eb0960b1eff#f2_band_z_knife_vs_classic_equip_median=0.741]
and the jump to [metric:sound_bank2/overlap@a01863947bab+9eb0960b1eff#f2_band_z_knife_vs_jump_median=0.711].

On the Iso match the higher threshold buys precision and loses recall. Knife
equips: precision [metric:sound_bank2/match@4f207c0c4e39#equip_knife_equip_precision=1.0]
(v1 0.653), recall of the right class
[metric:sound_bank2/match@4f207c0c4e39#equip_knife_recall_right=0.273]
(v1 0.432), and [metric:sound_bank2/match@4f207c0c4e39#knife_implausible_pairs=2]
implausible knife pairs (v1 36). The new guns' equips name the right gun
[metric:sound_bank2/match@4f207c0c4e39#equip_other_guns_recall_right=0.0] of
[metric:sound_bank2/match@4f207c0c4e39#equip_other_guns_n=22] times;
Classic, Vandal and Phantom [metric:sound_bank2/match@4f207c0c4e39#equip_bank_guns_recall_right=0.188],
as in v1. Own shots: recall [metric:sound_bank2/match@4f207c0c4e39#shot_recall=0.057]
(v1 0.471). Footsteps stay at chance: an onset follows
[metric:sound_bank2/match@4f207c0c4e39#footstep_onset_share=0.029] of them
against [metric:sound_bank2/match@4f207c0c4e39#base_large_onset_share=0.09]
for any own-view instant. Reloads: [metric:sound_bank2/match@4f207c0c4e39#reload_v2_recall_right=0.0]
of own HUD refills hold a right-gun reload. Double Tap casts on the tray:
[metric:sound_bank2/match@4f207c0c4e39#iso_double_tap_recall=0.111] of
[metric:sound_bank2/match@4f207c0c4e39#iso_double_tap_tray_casts=18]. At v1's
theta 0.50 (sensitivity) any-gun reloads appear in
[metric:sound_bank2/match_sensitivity@4f207c0c4e39~2026-09-30T14:24:58#reload_v2_recall=0.875]
of refills, all named Sheriff or Bandit, and shot recall is
[metric:sound_bank2/match_sensitivity@4f207c0c4e39~2026-09-30T14:24:58#shot_recall=0.771]
at precision [metric:sound_bank2/match_sensitivity@4f207c0c4e39~2026-09-30T14:24:58#shot_precision=0.365];
f2 at 0.85 transfers no better
([metric:sound_bank2/match_sensitivity@4f207c0c4e39~2026-09-30T14:31:34#equip_knife_recall_right=0.273]
knife recall, [metric:sound_bank2/match_sensitivity@4f207c0c4e39~2026-09-30T14:31:34#shot_recall=0.071]
shot recall). Range templates at a range-chosen threshold do not transfer to
match audio except the knife; the front end is not the bottleneck.

No stored stream witnesses an ability's equip: the HUD's hidden counter
cannot tell an Iso equip from the knife. The next witness to build is the
ability submenu above the tray [domain:abilities/tray-equip-submenu].

This is a prototype; nothing in `reticle/` uses it.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_var] = "2"

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))
with contextlib.redirect_stdout(io.StringIO()):
    import audio_probe  # noqa: E402
    import sound_bank  # noqa: E402
    import sound_demo  # noqa: E402
    import sound_labels  # noqa: E402
    import sound_match  # noqa: E402
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_var] = "2"          # the imports above reset them; numpy loaded at 2

VERSION = "sound-bank-2.0.0"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "sound-bank-v2"
TASK = "bank-v2-20260930"
FRONT_ENDS = ("f0_patch_z", "f1_tilt_free", "f2_band_z")
HOP, LEAD_S, TOL_S = sound_bank.HOP, sound_bank.LEAD_S, sound_bank.TOL_S
SD_MIN = sound_bank.SD_MIN
BAND_SD_MIN = 0.25               # dB; f2's active band, in the reference and in the window
ONSET_SLACK_S = sound_bank.ONSET_SLACK_S
MIN_EVENTS = 3                   # a class enters the macro means with this many labelled events
THETAS = np.round(np.arange(0.30, 0.951, 0.05), 2)
#: Pre-registered: a challenger replaces f0 only if its macro AUC beats f0's by this much.
AUC_MARGIN = 0.01
#: The Iso match's tray slots onto Iso's abilities.
ISO_SLOT = {"C": "iso_contingency", "Q": "iso_undercut", "E": "iso_double_tap", "X": "iso_kill_contract"}
CAST_WIN = (-0.8, 0.3)           # detection time minus the tray drop's first sample, s
V1_GUNS = ("classic", "vandal", "phantom")
GUNS = sound_labels.GUNS


def _idle() -> None:
    """Idle priority, verified (the venv has no psutil)."""
    if os.name != "nt":
        return
    import ctypes
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k.GetPriorityClass.restype = ctypes.c_uint32
    k.SetPriorityClass(k.GetCurrentProcess(), 0x40)
    got = k.GetPriorityClass(k.GetCurrentProcess())
    if got != 0x40:
        raise SystemExit(f"priority class 0x{got:x}, not Idle")
    print(f"priority: Idle (0x40), BLAS threads {os.environ['OMP_NUM_THREADS']}", flush=True)


# ---------------------------------------------------------------------------
# Labelled events and references
# ---------------------------------------------------------------------------


def bank_class(x: dict) -> str | None:
    """The structured label's bank class: reloads pooled per gun; an ability equip
    whose part the player did not name is kept out of the references."""
    c = x.get("cls")
    if x["kind"] != "sound" or not c:
        return None
    for g in GUNS:
        if c in (f"{g}_reload_empty", f"{g}_reload_partial"):
            return f"{g}_reload"
    if c == "iso_kill_contract_equip":
        return None
    return c


def events() -> list[dict]:
    """Every structured row of both clips: `cls` is the bank class, 'no_sound', or
    None (compound, unmapped, ability without phase, or unparted equip)."""
    out = []
    for tag in sound_labels.TAGS:
        for x in sound_labels.load(tag):
            if x["kind"] == "excluded":
                continue
            cls = "no_sound" if x["kind"] == "no_sound" else bank_class(x)
            out.append({"tag": tag, "key": x["key"], "t0": x["t0"], "t1": x["t1"], "cls": cls,
                        "variant": x.get("variant"), "kind": x["kind"], "label": x["label"],
                        "other_name": x.get("other_name")})
    return out


def class_len(ev: list[dict]) -> dict[str, int]:
    return sound_bank.class_len([e for e in ev if e["cls"] and e["cls"] != "no_sound"])


# ---------------------------------------------------------------------------
# Features (range clips decoded in memory, cached as features only)
# ---------------------------------------------------------------------------


def feat_path(tag: str) -> Path:
    return OUT / f"features-{tag}.npy"


def features(force: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for tag in sound_labels.TAGS:
        p = feat_path(tag)
        if p.is_file() and not force:
            print(f"{p} exists")
            continue
        cap = sound_demo.CLIPS[tag]["capture"]
        x, rate = audio_probe.decode(cap)
        D = sound_bank.features(x.mean(axis=1).astype(np.float64), int(rate))
        np.save(p, D.astype(np.float32))
        print(f"{tag}: {cap} -> {p} {D.shape}", flush=True)


def load_features() -> dict[str, np.ndarray]:
    return {tag: np.load(feat_path(tag)).astype(np.float64) for tag in sound_labels.TAGS}


def refs(ev: list[dict], F: dict[str, np.ndarray], clen: dict[str, int]) -> list[dict]:
    out = []
    for i, e in enumerate(ev):
        if not e["cls"] or e["cls"] == "no_sound":
            continue
        n = clen[e["cls"]]
        f0 = int(round((e["t0"] - LEAD_S) / HOP))
        out.append({"ev": i, "cls": e["cls"], "tag": e["tag"], "t0": e["t0"], "t1": e["t1"],
                    "variant": e["variant"], "key": e["key"], "T": F[e["tag"]][:, f0:f0 + n]})
    return out


# ---------------------------------------------------------------------------
# The three front ends' sliding scores
# ---------------------------------------------------------------------------


def _torch():
    import torch
    torch.set_num_threads(2)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    return torch, dev


class Signal:
    """One feature matrix, prepared once for sliding scores."""

    def __init__(self, D: np.ndarray):
        torch, dev = _torch()
        self.torch, self.dev = torch, dev
        self.nf = D.shape[1]
        self.nfft = 1 << int(np.ceil(np.log2(self.nf + 128)))
        Dt = torch.tensor(D, dtype=torch.float64, device=dev)
        self.FD = torch.fft.rfft(Dt, self.nfft, dim=1)
        z = torch.zeros((D.shape[0], 1), dtype=torch.float64, device=dev)
        self.cs1b = torch.cat([z, torch.cumsum(Dt, 1)], 1)
        self.cs2b = torch.cat([z, torch.cumsum(Dt * Dt, 1)], 1)

    def score(self, T: np.ndarray, fe: str) -> np.ndarray:
        """[nf] score of reference T starting at every frame (0 past the end)."""
        torch = self.torch
        nb, n = T.shape
        L = self.nf - n + 1
        out = np.zeros(self.nf)
        if L <= 0:
            return out
        Tt = torch.tensor(T, dtype=torch.float64, device=self.dev)
        s1b = self.cs1b[:, n:] - self.cs1b[:, :-n]
        s2b = self.cs2b[:, n:] - self.cs2b[:, :-n]
        N = nb * n
        s1, s2 = s1b.sum(0), s2b.sum(0)
        sd = torch.sqrt(torch.clamp(s2 / N - (s1 / N) ** 2, min=0.0))
        if fe == "f0_patch_z":
            Tz = (Tt - Tt.mean()) / (Tt.std(correction=0) + 1e-9)
            num = torch.fft.irfft((torch.conj(torch.fft.rfft(Tz, self.nfft, dim=1)) * self.FD).sum(0), self.nfft)[:L]
            r = num / (N * torch.clamp(sd, min=1e-9))
        elif fe == "f1_tilt_free":
            Tp = Tt - Tt.mean(1, keepdim=True)
            tn = torch.sqrt((Tp * Tp).sum())
            num = torch.fft.irfft((torch.conj(torch.fft.rfft(Tp, self.nfft, dim=1)) * self.FD).sum(0), self.nfft)[:L]
            wv = torch.clamp((s2b - s1b * s1b / n).sum(0), min=0.0)
            r = num / torch.clamp(tn * torch.sqrt(wv), min=1e-9)
            if float(tn) < 1e-9:
                r = torch.zeros_like(r)
        elif fe == "f2_band_z":
            st = Tt.std(1, correction=0)
            act = st >= BAND_SD_MIN
            if int(act.sum()) == 0:
                return out
            Ta = (Tt[act] - Tt[act].mean(1, keepdim=True)) / st[act][:, None]
            num = torch.fft.irfft(torch.conj(torch.fft.rfft(Ta, self.nfft, dim=1)) * self.FD[act], self.nfft, dim=1)[:, :L]
            sdb = torch.sqrt(torch.clamp(s2b[act] / n - (s1b[act] / n) ** 2, min=0.0))
            cb = torch.where(sdb >= BAND_SD_MIN, num / (n * torch.clamp(sdb, min=1e-9)), torch.zeros_like(num))
            r = cb.mean(0)
        else:
            raise ValueError(fe)
        r = torch.where(sd < SD_MIN, torch.zeros_like(r), r)
        out[:L] = r.cpu().numpy()
        return out


def patch_score(A: np.ndarray, B: np.ndarray, fe: str, min_ov: int = 20, max_lag: int = 10) -> float:
    """Best score of two references over +-max_lag frames (`sound_match._best_zc`'s
    alignment) under one front end."""
    best = -1.0
    for L in range(-max_lag, max_lag + 1):
        i0, i1 = max(0, -L), min(A.shape[1], B.shape[1] - L)
        if i1 - i0 < min_ov:
            continue
        a, b = A[:, i0:i1], B[:, i0 + L:i1 + L]
        if fe == "f0_patch_z":
            v = sound_match._zc(a, b)
        elif fe == "f1_tilt_free":
            v = sound_match._zc(a - a.mean(1, keepdims=True), b - b.mean(1, keepdims=True))
        else:
            sa, sb = a.std(1), b.std(1)
            act = sa >= BAND_SD_MIN
            if not act.any():
                continue
            cs = [sound_match._zc(a[k], b[k]) if sb[k] >= BAND_SD_MIN else 0.0 for k in np.nonzero(act)[0]]
            v = float(np.mean(cs))
        best = max(best, v)
    return best


# ---------------------------------------------------------------------------
# Range leave-one-out
# ---------------------------------------------------------------------------


def loo_curves(ev, F, rr, clen, fe) -> dict[str, dict[str, np.ndarray]]:
    """Per clip, per class: the best reference score at every frame, each reference
    masked within its own event's span (v1's rule)."""
    classes = sorted(clen)
    S = {tag: {c: np.full(D.shape[1], -1.0) for c in classes} for tag, D in F.items()}
    sig = {tag: Signal(D) for tag, D in F.items()}
    for k, r in enumerate(rr):
        n = clen[r["cls"]]
        for tag in F:
            c = sig[tag].score(r["T"], fe)
            if tag == r["tag"]:
                a = max(0, int(round((r["t0"] - LEAD_S) / HOP)) - n - int(TOL_S / HOP))
                b = int(round((r["t1"] + TOL_S) / HOP))
                c[a:b] = -1.0
            np.maximum(S[tag][r["cls"]], c, out=S[tag][r["cls"]])
        if k % 100 == 0:
            print(f"  {fe}: {k}/{len(rr)} references", flush=True)
    return S


def at_onset(Sc: np.ndarray, t0: float) -> float:
    f = int(round((t0 - LEAD_S) / HOP))
    k = int(round(ONSET_SLACK_S / HOP))
    return float(Sc[max(0, f - k):f + k + 1].max())


def auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    p, q = np.asarray(pos), np.asarray(neg)
    return float(((p[:, None] > q[None]).sum() + 0.5 * (p[:, None] == q[None]).sum()) / (len(p) * len(q)))


def match_clip(dets, evc, tol=TOL_S):
    """Greedy by score: each detection takes the nearest unused labelled onset within tol."""
    used = set()
    for d in sorted(dets, key=lambda d: -d["score"]):
        near = [k for k, e in enumerate(evc) if k not in used and abs(e["t0"] - d["t"]) <= tol]
        if near:
            k = min(near, key=lambda k: abs(evc[k]["t0"] - d["t"]))
            used.add(k)
            d["match"] = evc[k]["cls"]
    return dets


def evaluate(ev, S, clen) -> dict:
    classes = sorted(clen)
    scored = [e for e in ev if e["cls"]]          # bank classes and no_sound
    sc = [{c: at_onset(S[e["tag"]][c], e["t0"]) for c in classes} for e in scored]
    # Onset naming.
    onset = []
    for e, s in zip(scored, sc):
        best = max(s, key=s.get)
        onset.append({"tag": e["tag"], "t0": e["t0"], "true": e["cls"], "named": best, "score": round(s[best], 4),
                      "true_score": round(s[e["cls"]], 4) if e["cls"] in s else None})
    n_ev = Counter(e["cls"] for e in scored)
    big = [c for c in classes if n_ev[c] >= MIN_EVENTS]
    aucs = {c: auc([s[c] for e, s in zip(scored, sc) if e["cls"] == c],
                   [s[c] for e, s in zip(scored, sc) if e["cls"] != c]) for c in classes}
    acc = {c: sum(1 for o in onset if o["true"] == c and o["named"] == c) / n_ev[c] for c in classes if n_ev[c]}
    ns = [s for e, s in zip(scored, sc) if e["cls"] == "no_sound"]
    # Detection over both clips at each theta.
    sweep = {}
    for th in THETAS:
        tp = nd = 0
        per = defaultdict(lambda: {"tp": 0, "det": 0})
        for tag in S:
            evc = [e for e in ev if e["tag"] == tag and e["cls"]]
            dets = match_clip(sound_bank.detect(S[tag], clen, float(th)), evc)
            for d in dets:
                per[d["cls"]]["det"] += 1
                if d.get("match") == d["cls"]:
                    per[d["cls"]]["tp"] += 1
            nd += len(dets)
            tp += sum(1 for d in dets if d.get("match") == d["cls"])
        npos = sum(n_ev[c] for c in classes)
        p, r = (tp / nd if nd else 0.0), tp / npos
        sweep[float(th)] = {"tp": tp, "det": nd, "precision": round(p, 4), "recall": round(r, 4),
                            "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0, "per": dict(per)}
    return {"onset": onset, "n_events": dict(n_ev), "macro_classes": big,
            "auc": {c: (round(v, 4) if v is not None else None) for c, v in aucs.items()},
            "macro_auc": round(float(np.mean([aucs[c] for c in big if aucs[c] is not None])), 4),
            "onset_acc": {c: round(v, 3) for c, v in acc.items()},
            "macro_onset_acc": round(float(np.mean([acc[c] for c in big])), 4),
            "micro_onset_acc": round(sum(1 for o in onset if o["true"] == o["named"]) /
                                     max(1, sum(1 for o in onset if o["true"] != "no_sound")), 4),
            "no_sound_n": len(ns), "no_sound_max_median": round(float(np.median([max(s.values()) for s in ns])), 4)
            if ns else None,
            "no_sound_best_class": dict(Counter(max(s, key=s.get) for s in ns)),
            "sweep": sweep}


def choose(res: dict) -> tuple[str, float]:
    """The pre-registered rule: highest macro AUC; f0 kept unless beaten by AUC_MARGIN;
    within 0.005 of each other, the higher macro onset accuracy. Theta: the chosen
    front end's highest micro-F1 over both clips (the lower theta on a tie)."""
    f0 = res["f0_patch_z"]["macro_auc"]
    ok = [fe for fe in FRONT_ENDS if fe == "f0_patch_z" or res[fe]["macro_auc"] >= f0 + AUC_MARGIN]
    top = max(res[fe]["macro_auc"] for fe in ok)
    near = [fe for fe in ok if res[fe]["macro_auc"] >= top - 0.005]
    fe = max(near, key=lambda f: (res[f]["macro_onset_acc"], res[f]["macro_auc"]))
    sw = res[fe]["sweep"]
    th = max(sw, key=lambda t: (sw[t]["f1"], -t))
    return fe, float(th)


def range_stage(record: bool) -> dict:
    ev = events()
    F = load_features()
    clen = class_len(ev)
    rr = refs(ev, F, clen)
    print(f"{len(rr)} references in {len(clen)} classes; {sum(1 for e in ev if e['cls'] == 'no_sound')} "
          f"no-sound rows; {sum(1 for e in ev if not e['cls'])} rows without a class", flush=True)
    res = {}
    curves = {}
    for fe in FRONT_ENDS:
        S = loo_curves(ev, F, rr, clen, fe)
        curves[fe] = S
        res[fe] = evaluate(ev, S, clen)
        r = res[fe]
        print(f"{fe}: macro AUC {r['macro_auc']}, macro onset acc {r['macro_onset_acc']}, micro onset acc "
              f"{r['micro_onset_acc']}, no-sound best-score median {r['no_sound_max_median']}", flush=True)
    fe, th = choose(res)
    print(f"chosen: {fe} at theta {th}")
    per = per_class(ev, curves[fe], clen, th)
    _print_per(per)
    out = {"version": VERSION, "labels": {t: str(sound_labels.LABELS / f"sound_demo_{t}.structured-{sound_labels.VERSION}.jsonl")
                                          for t in sound_labels.TAGS},
           "class_len_s": {c: clen[c] * HOP for c in sorted(clen)}, "refs": len(rr),
           "front_ends": {k: {kk: vv for kk, vv in v.items() if kk != "onset"} for k, v in res.items()},
           "onset": {k: v["onset"] for k, v in res.items()},
           "chosen": {"front_end": fe, "theta": th}, "per_class": per}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "range-loo.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    (OUT / "chosen.json").write_text(json.dumps({"front_end": fe, "theta": th, "version": VERSION}), encoding="utf-8")
    if record:
        _record_range(out)
    return out


def per_class(ev, S, clen, th) -> dict:
    """Per class at the chosen theta: onset accuracy, and detection recall and precision."""
    classes = sorted(clen)
    per = {c: {"n": 0, "onset_right": 0, "det": 0, "tp": 0} for c in classes}
    for e in ev:
        if e["cls"] in per:
            per[e["cls"]]["n"] += 1
            s = {c: at_onset(S[e["tag"]][c], e["t0"]) for c in classes}
            per[e["cls"]]["onset_right"] += max(s, key=s.get) == e["cls"]
    for tag in S:
        evc = [e for e in ev if e["tag"] == tag and e["cls"]]
        for d in match_clip(sound_bank.detect(S[tag], clen, th), evc):
            per[d["cls"]]["det"] += 1
            per[d["cls"]]["tp"] += d.get("match") == d["cls"]
    for c, p in per.items():
        p["recall"] = round(p["tp"] / p["n"], 3) if p["n"] else None
        p["precision"] = round(p["tp"] / p["det"], 3) if p["det"] else None
        p["onset_acc"] = round(p["onset_right"] / p["n"], 3) if p["n"] else None
    return per


def _print_per(per: dict) -> None:
    print(f"{'class':<28}{'n':>4}{'onset':>7}{'det':>5}{'tp':>4}{'recall':>8}{'prec':>7}")
    for c, p in sorted(per.items()):
        print(f"{c:<28}{p['n']:>4}{p['onset_right']:>7}{p['det']:>5}{p['tp']:>4}{p['recall']!s:>8}{p['precision']!s:>7}")


def _deps(extra: dict) -> dict:
    lab = {}
    for t in sound_labels.TAGS:
        p = sound_labels.LABELS / f"sound_demo_{t}.jsonl"
        lab[t] = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
    return {"version": VERSION, "labels_version": sound_labels.VERSION, "labels_rows": lab,
            "band_sd_min": BAND_SD_MIN, "sd_min": SD_MIN, "lead_s": LEAD_S, "tol_s": TOL_S, **extra}


def _record_range(out: dict) -> None:
    from reticle import metrics
    vals = {}
    for fe, r in out["front_ends"].items():
        vals[f"{fe}_macro_auc"] = r["macro_auc"]
        vals[f"{fe}_macro_onset_acc"] = r["macro_onset_acc"]
        vals[f"{fe}_micro_onset_acc"] = r["micro_onset_acc"]
        vals[f"{fe}_no_sound_max_median"] = r["no_sound_max_median"]
        best = max(r["sweep"].values(), key=lambda s: s["f1"])
        vals[f"{fe}_best_f1"] = best["f1"]
        for c, v in r["auc"].items():
            if v is not None:
                vals[f"{fe}_auc_{c}"] = v
    vals["chosen_theta"] = out["chosen"]["theta"]
    vals["chosen_front_end_index"] = FRONT_ENDS.index(out["chosen"]["front_end"])
    for c, p in out["per_class"].items():
        for k in ("n", "onset_right", "det", "tp", "recall", "precision"):
            if p[k] is not None:
                vals[f"{c}_{k}"] = p[k]
    metrics.record("sound_bank2", part="range", session="a01863947bab+9eb0960b1eff", values=vals,
                   deps=_deps({"thetas": THETAS.tolist(), "auc_margin": AUC_MARGIN, "min_events": MIN_EVENTS,
                               "chosen": out["chosen"]}))
    print(f"recorded {len(vals)} values under sound_bank2/range")


# ---------------------------------------------------------------------------
# Knife overlap
# ---------------------------------------------------------------------------


def overlap(record: bool) -> dict:
    ev = events()
    F = load_features()
    clen = class_len(ev)
    rr = refs(ev, F, clen)
    knives = [k for k, r in enumerate(rr) if r["cls"] == "knife_equip"]
    res = {}
    # The instrument: v1's references through patch_score must give `sound_match knife`'s
    # recorded medians (0.886 / 0.871 / 0.869 / 0.967; tilt-free jump 0.717).
    rf1, _, _ = sound_match.load_refs()
    base = {}
    for fe in ("f0_patch_z", "f1_tilt_free"):
        by = defaultdict(list)
        for i, (ci, A) in enumerate(rf1):
            if ci == "knife_equip":
                for j, (cj, B) in enumerate(rf1):
                    if j != i and cj in ("classic_equip", "vandal_single", "jump", "knife_equip"):
                        by[cj].append(patch_score(A, B, fe))
        base[fe] = {c: round(float(np.median(v)), 3) for c, v in sorted(by.items())}
    print("v1 references (instrument):", base, flush=True)
    res["v1_refs_instrument"] = base
    for fe in FRONT_ENDS:
        by = defaultdict(list)
        for i in knives:
            for j, r in enumerate(rr):
                if j != i:
                    by[r["cls"]].append(patch_score(rr[i]["T"], r["T"], fe))
        res[fe] = {c: {"pairs": len(v), "median": round(float(np.median(v)), 3),
                       "p90": round(float(np.percentile(v, 90)), 3)}
                   for c, v in sorted(by.items(), key=lambda kv: -np.median(kv[1]))}
        top = list(res[fe].items())[:8]
        print(fe, "knife vs:", {c: v["median"] for c, v in top}, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "knife-overlap.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if record:
        from reticle import metrics
        vals = {f"{fe}_knife_vs_{c}_median": v["median"] for fe, r in res.items() if fe in FRONT_ENDS
                for c, v in r.items()}
        vals.update({f"v1refs_{fe}_knife_vs_{c}_median": v for fe, r in res["v1_refs_instrument"].items()
                     for c, v in r.items()})
        metrics.record("sound_bank2", part="overlap", session="a01863947bab+9eb0960b1eff", values=vals,
                       deps=_deps({"min_ov": 20, "max_lag": 10}))
        print(f"recorded {len(vals)} values under sound_bank2/overlap")
    return res


# ---------------------------------------------------------------------------
# The Iso match: detection from cached audio, then the stored witnesses
# ---------------------------------------------------------------------------


def chosen() -> tuple[str, float]:
    c = json.loads((OUT / "chosen.json").read_text(encoding="utf-8"))
    return c["front_end"], float(c["theta"])


def match_dir(fe: str | None, th: float | None) -> Path:
    """The pre-registered run's directory, or a sensitivity run's (another front end or theta)."""
    if fe is None and th is None:
        return OUT / "match"
    cfe, cth = chosen()
    return OUT / f"match-{fe or cfe}-{(cth if th is None else th):.2f}"


def detect_match(fe_arg: str | None = None, th_arg: float | None = None) -> None:
    md = match_dir(fe_arg, th_arg)
    fe, th = chosen()
    fe, th = fe_arg or fe, th if th_arg is None else th_arg
    ev = events()
    F = load_features()
    clen = class_len(ev)
    rr = refs(ev, F, clen)
    del F
    d = md / "detections"
    d.mkdir(parents=True, exist_ok=True)
    classes = sorted(clen)
    for r_no, a, b in sound_match.chunks():
        t_off = max(0.0, a - sound_match.PAD_S)
        x, rate = sound_match.read_audio(t_off, b + sound_match.PAD_S)
        D = sound_bank.features(x.mean(axis=1), rate)
        sig = Signal(D)
        S = {c: np.full(D.shape[1], -1.0) for c in classes}
        for r in rr:
            np.maximum(S[r["cls"]], sig.score(r["T"], fe), out=S[r["cls"]])
        dets = sound_bank.detect(S, clen, th)
        L = sound_bank.bandpass(x[:, 0], rate) ** 2
        R = sound_bank.bandpass(x[:, 1], rate) ** 2
        cl, cr = np.concatenate([[0.0], np.cumsum(L)]), np.concatenate([[0.0], np.cumsum(R)])
        rows = []
        for q in dets:
            t = t_off + q["t"]
            if not (a <= t < b):
                continue
            f = int(round((q["t"] - LEAD_S) / HOP))
            sc = sorted(((float(S[c][f]), c) for c in classes if c != q["cls"]), reverse=True)
            i0 = int(round(q["t"] * rate))
            i1 = i0 + int(round(max(0.1, clen[q["cls"]] * HOP) * rate))
            el, er = cl[min(i1, len(cl) - 1)] - cl[i0], cr[min(i1, len(cr) - 1)] - cr[i0]
            rows.append({"round": r_no, "t": round(t, 3), "cls": q["cls"], "score": round(q["score"], 4),
                         "second": sc[0][1], "second_score": round(sc[0][0], 4),
                         "ild_db": round(float(10 * np.log10((el + 1e-12) / (er + 1e-12))), 2),
                         "level_db": round(float(10 * np.log10((el + er) / max(1, i1 - i0) + 1e-12)), 1)})
        (d / f"r{r_no:02d}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        print(f"round {r_no:>2} {a:7.1f}-{b:7.1f} s: {len(rows)} detections "
              f"{dict(Counter(r['cls'] for r in rows).most_common(6))}", flush=True)
    (md / "detect.json").write_text(json.dumps(
        {"version": VERSION, "front_end": fe, "theta": th, "refs": len(rr), "classes": classes,
         "session_id": sound_match.SESSION, "source_path": sound_match.CAPTURE,
         "audio": str(sound_match.WAV)}, indent=1), encoding="utf-8")


@contextlib.contextmanager
def v2_witness(classes: list[str], md: Path):
    """Point `sound_match`'s circle stage at the v2 detections and class lists; the
    witnesses and windows stay unchanged. `BANK_GUNS` stays v1's three, so its
    `other_guns` row is the new guns."""
    sm = sound_match
    saved = {k: getattr(sm, k) for k in ("OUT", "EQUIP", "SHOT", "CIRCLE_OUT", "CIRCLE_LISTEN")}
    try:
        sm.OUT = md
        sm.EQUIP = ("knife_equip",) + tuple(c for c in classes if c.split("_")[0] in GUNS and c.endswith("_equip"))
        sm.SHOT = tuple(c for c in classes if c.split("_")[0] in GUNS and c.split("_")[1] in ("single", "burst", "spray"))
        sm.CIRCLE_OUT = md
        sm.CIRCLE_LISTEN = md / "listen.csv"
        yield
    finally:
        for k, v in saved.items():
            setattr(sm, k, v)


def match_stage(record: bool, fe_arg: str | None = None, th_arg: float | None = None) -> dict:
    sm = sound_match
    md = match_dir(fe_arg, th_arg)
    info = json.loads((md / "detect.json").read_text(encoding="utf-8"))
    classes = info["classes"]
    with v2_witness(classes, md):
        res = sm.circle(False)
        dets = sm.load_dets()
    spans = sm.pov_spans()
    s = sm.hud_samples()
    for d in dets:
        d["pov"] = sm.pov_at(spans, d["t"])
    own = [d for d in dets if d["pov"] == "own"]
    extra: dict = {}
    # Knife runs, as `sound_match.knife` counts them.
    pairs, runs = sm.knife_runs([d for d in dets if d["cls"] == "knife_equip"], s)
    extra["knife"] = {"n": sum(1 for d in dets if d["cls"] == "knife_equip"), "implausible_pairs": len(pairs),
                      "implausible_runs": len(runs)}
    # Reloads: own HUD refills on one gun segment against reload detections.
    refills = [r for r in sm.hud_refills(s, spans) if r["kind"] == "reload"]
    rel = [d for d in own if d["cls"].endswith("_reload")]
    rows = []
    for r in refills:
        a, b = r["t_prev"] + sm.REFILL_WIN[0], r["t_new"] + sm.REFILL_WIN[1]
        near = [d for d in rel if a <= d["t"] <= b]
        best = max(near, key=lambda d: d["score"]) if near else None
        rows.append({"t_prev": r["t_prev"], "gun": r["gun"], "det": best["cls"] if best else None,
                     "right": bool(best and sm._gun_ok(best["cls"], r["gun"]))})
    win = [(r["t_prev"] + sm.REFILL_WIN[0], r["t_new"] + sm.REFILL_WIN[1]) for r in sm.hud_refills(s, spans)]
    in_win = sum(1 for d in rel if any(a <= d["t"] <= b for a, b in win))
    extra["reload"] = {"refills": len(rows), "detected": sum(1 for x in rows if x["det"]),
                       "right": sum(1 for x in rows if x["right"]),
                       "recall": sm._share(sum(1 for x in rows if x["det"]), len(rows)),
                       "recall_right": sm._share(sum(1 for x in rows if x["right"]), len(rows)),
                       "own_dets": len(rel), "own_dets_in_refill": in_win,
                       "precision": sm._share(in_win, len(rel)), "rows": rows}
    # Iso casts against the tray's own-cast drops (2 Hz).
    drops = [json.loads(line) for line in (STORE / "events" / "tray_drop" / f"{sm.SESSION}.jsonl")
             .read_text(encoding="utf-8").splitlines() if line.strip()]
    casts = [x for x in drops if x.get("kind") == "drop" and x.get("player_cast")]
    anydrop = [x for x in drops if x.get("kind") == "drop"]
    iso = {}
    for slot, ab in ISO_SLOT.items():
        cc = [x["t_ms"] / 1000.0 for x in casts if x["slot"] == slot]
        dd = [d for d in own if d["cls"] == f"{ab}_cast"]
        hit = sum(1 for t in cc if any(t + CAST_WIN[0] <= d["t"] <= t + CAST_WIN[1] for d in dd))
        at_drop = sum(1 for d in dd if any(x["slot"] == slot and x["t_ms"] / 1000.0 + CAST_WIN[0] <= d["t"]
                                           <= x["t_ms"] / 1000.0 + CAST_WIN[1] for x in anydrop))
        iso[ab] = {"tray_casts": len(cc), "cast_detected": hit, "recall": sm._share(hit, len(cc)),
                   "own_cast_dets": len(dd), "own_cast_dets_at_slot_drop": at_drop,
                   "precision": sm._share(at_drop, len(dd))}
    iso["all_iso_dets"] = dict(Counter(d["cls"] for d in dets if d["cls"].startswith("iso_")))
    iso["own_iso_dets"] = dict(Counter(d["cls"] for d in own if d["cls"].startswith("iso_")))
    extra["iso"] = iso
    # Non-gun equips: the HUD's gun->hidden changes, knife or an Iso equip.
    rows_eq = sm.equip_rows([dict(d) for d in dets], s, spans, sm.phases(), 0.0, 1e9)
    ng = [r for r in rows_eq if r["stable"] and r["pov"] == "own" and r["kind"] == "nongun"]
    iso_eq = [d for d in own if d["cls"].startswith("iso_") and "_equip" in d["cls"]]
    extra["nongun"] = {"n": len(ng), "iso_equip_in_window": sum(
        1 for r in ng if any(r["t_prev"] - sm.SLACK_S <= d["t"] <= r["t_new"] + sm.SLACK_S for d in iso_eq)),
        "iso_equip_own_dets": len(iso_eq)}
    extra["classes"] = dict(Counter(d["cls"] for d in dets))
    _print_extra(extra)
    out = {"version": VERSION, "detect": info, "circle": res, "extra": extra}
    (md / "match-score.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    if record:
        _record_match(res, extra, info, "match" if md == OUT / "match" else "match_sensitivity", md)
    return out


def _print_extra(x: dict) -> None:
    print("knife:", x["knife"])
    print("reload:", {k: v for k, v in x["reload"].items() if k != "rows"})
    for k, v in x["iso"].items():
        print("iso", k, v)
    print("non-gun equips:", x["nongun"])
    print("classes:", x["classes"])


def _record_match(res: dict, extra: dict, info: dict, part: str, md: Path) -> None:
    from reticle import metrics
    vals = sound_match.circle_values(res)
    for k, v in extra["knife"].items():
        vals[f"knife_{k}"] = v
    for k, v in extra["reload"].items():
        if isinstance(v, (int, float)) and v is not None:
            vals[f"reload_v2_{k}"] = v
    for ab, v in extra["iso"].items():
        if ab.startswith("iso_") and isinstance(v, dict) and "tray_casts" in v:
            for k, w in v.items():
                if w is not None:
                    vals[f"{ab}_{k}"] = w
    for k, v in extra["nongun"].items():
        vals[f"nongun_{k}"] = v
    metrics.record("sound_bank2", part=part, session=sound_match.SESSION, values=vals,
                   deps=_deps({"front_end": info["front_end"], "theta": info["theta"], "refs": info["refs"],
                               "circle_version": sound_match.CIRCLE_VERSION, "cast_win": CAST_WIN,
                               "windows": res["windows"], "dets": str(md / "detections"),
                               "pre_registered": part == "match"}),
                   context={"hud": "hud-0.16.0 2 Hz", "tray_kit": "tray-kit-0.1.0", "tray": "tray-0.1.0",
                            "player_cast": "player-cast-0.7.0", "minimap": "minimap-0.7.0",
                            "gametime": "gametime-0.1.0"})
    print(f"recorded {len(vals)} values under sound_bank2/{part}@{sound_match.SESSION}")


def main(argv=None) -> int:
    _idle()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("features")
    p.add_argument("--force", action="store_true")
    for name in ("range", "overlap", "match"):
        p = sub.add_parser(name)
        p.add_argument("--record", action="store_true")
    p = sub.add_parser("detect")
    for p in (p, sub.choices["match"]):
        p.add_argument("--fe", choices=FRONT_ENDS, help="a sensitivity run: another front end")
        p.add_argument("--theta", type=float, help="a sensitivity run: another threshold")
    a = ap.parse_args(argv)
    if a.cmd == "features":
        features(a.force)
    elif a.cmd == "range":
        range_stage(a.record)
    elif a.cmd == "overlap":
        overlap(a.record)
    elif a.cmd == "detect":
        detect_match(a.fe, a.theta)
    else:
        match_stage(a.record, a.fe, a.theta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
