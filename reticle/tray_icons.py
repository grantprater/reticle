r"""Score the ability tray's four slot icons against the catalogue's icons.

    (read by `reticle tray-kit` from the stored `hud_abilities` crops; no decode)

Owns [owns:tray-icon].

What is drawn. Each tray slot draws its ability's icon above the charge bar
that `tray` reads, white while the ability is available and dimmed while it
is not, over the semi-transparent tray and the world behind it
[domain:hud/tray-slot-icons]. After the player dies the tray shows a
spectated teammate's kit [domain:hud/tray-after-player-death], so the icons
say whose kit it is.

The reference is the catalogue, never the session. `reference/abilities.json`
names each ability's official icon (`icon.file`): 128 px white glyphs on an
alpha channel (Veto's four are 512 px and are resized to 128), every opaque
pixel white. The slot is the ability's `key` (C, Q, E, X), the same keys
`lineup.abilities_for` reads. The drawn icon is that glyph composited over the
background: grey = a * alpha + b, with a gain `a` (white or dimmed) and an
offset `b` (the background) that vary from sample to sample. Normalised
cross-correlation (`cv2.TM_CCOEFF_NORMED`) is invariant to both, so the
template is the alpha channel itself and one template reads a lit and a dimmed
icon. The only fitted parameter is the scale, ICON_PX, and the only search is a
shift of up to SHIFT_PX round the slot's centre.

Geometry, at 1920x1080. The slot centres are `tray`'s (SLOT_X0 + SLOT_DX * k),
since the icon sits over its bar; the icon's centre row is ICON_CY. Omen's C
on `4f207c0c4e39` 1960 s draws white from x 767 to 812 and y 984 to 1024,
about 46 px across its white core, from an asset whose opaque pixels span 128
by 111. ICON_PX, 48, is the scale at which the named kit fits best on each of
the three sessions of `docs/TRAY_KIT_WITNESS.md`, where the fits are cited; a
glyph's soft edge lies outside its white core, so the fitted scale is a little
wider. The same values serve the big-minimap profile, since the tray is
anchored to the screen edge.

Why not `lineup.tray_shapes`. That reader, the player-agent witness, thresholds
the grey at 170 and gates on the mask's fill, which is right for its question
(one confident vote per frame is enough) and wrong for this one: a dimmed icon
falls under the threshold, and an unavailable ability is exactly what a
spectated kit shows most. It is not restated here; this module answers a
different question and names nobody. `adjudication.tray_kit` decides.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from . import tray

#: The slot keys, in `tray`'s order.
SLOT_KEYS = tray.SLOT_KEYS
#: A 128 px catalogue icon drawn at this many pixels. See the module docstring.
ICON_PX = 48
#: The icon's centre row, at 1920x1080.
ICON_CY = 1004
#: The largest shift, in pixels, searched round a slot's nominal centre.
SHIFT_PX = 6
#: The catalogue's icon size; larger icons are resized to it first.
ASSET_PX = 128
#: The catalogue spells one agent otherwise than the asset names the lineup
#: uses (`lineup.ASSET_TO_AGENT`); the icons are keyed by the lineup's names.
_CATALOGUE_TO_ASSET = {"KAY/O": "KAY_O"}


def catalogue(store_root) -> dict:
    """`{agent: {key: icon path}}` from `reference/abilities.json`, keyed by the
    lineup's agent names, for the four tray keys."""
    root = Path(store_root)
    ref = json.loads((root / "reference" / "abilities.json").read_text(encoding="utf-8"))
    out: dict[str, dict[str, Path]] = {}
    for name, entry in ref["agents"].items():
        per = {}
        for ab in entry.get("abilities", []):
            key, icon = ab.get("key"), (ab.get("icon") or {}).get("file")
            if key in SLOT_KEYS and icon:
                per[key] = root / "reference" / icon.replace("\\", "/")
        if per:
            out[_CATALOGUE_TO_ASSET.get(name, name)] = per
    return out


def reference_key(store_root) -> str:
    """A short digest of the catalogue file and every icon it names, so a row
    says which references scored it."""
    h = hashlib.sha256()
    root = Path(store_root)
    h.update((root / "reference" / "abilities.json").read_bytes())
    for agent, per in sorted(catalogue(root).items()):
        for key, path in sorted(per.items()):
            h.update(f"{agent}:{key}".encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


def icon_template(path: Path, px: int = ICON_PX) -> np.ndarray | None:
    """One icon's alpha channel at `px` pixels, float32 in [0, 1]."""
    im = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if im is None or im.ndim != 3 or im.shape[2] != 4:
        return None
    alpha = im[:, :, 3].astype(np.float32) / 255.0
    if alpha.shape != (ASSET_PX, ASSET_PX):
        alpha = cv2.resize(alpha, (ASSET_PX, ASSET_PX), interpolation=cv2.INTER_AREA)
    return cv2.resize(alpha, (px, px), interpolation=cv2.INTER_AREA)


def load_slot_icons(store_root, px: int = ICON_PX) -> dict[str, dict[str, np.ndarray]]:
    """`{agent: {key: template}}` for every agent the catalogue holds."""
    out = {}
    for agent, per in catalogue(store_root).items():
        got = {k: t for k, p in per.items() if (t := icon_template(p, px)) is not None}
        if got:
            out[agent] = got
    return out


def slot_patches(frame: np.ndarray, px: int = ICON_PX) -> list[np.ndarray]:
    """The grey patch round each slot's icon, `px` + 2 * SHIFT_PX square."""
    half = px // 2
    y0 = ICON_CY - half - SHIFT_PX
    out = []
    for k in range(len(SLOT_KEYS)):
        cx = tray.SLOT_X0 + tray.SLOT_DX * k
        x0 = cx - half - SHIFT_PX
        bgr = frame[y0:y0 + px + 2 * SHIFT_PX, x0:x0 + px + 2 * SHIFT_PX]
        out.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32))
    return out


def match_icon(patch: np.ndarray, tpl: np.ndarray) -> tuple[float, tuple[int, int]]:
    """(the best normalised cross-correlation of `tpl` inside `patch`, and the
    template's centre offset from the patch's centre in pixels). A flat patch
    scores 0: it holds no icon."""
    if patch.std() < 1e-3:
        return 0.0, (0, 0)
    r = cv2.matchTemplate(patch, tpl, cv2.TM_CCOEFF_NORMED)
    _lo, hi, _plo, (x, y) = cv2.minMaxLoc(r)
    if not np.isfinite(hi):
        return 0.0, (0, 0)
    c = (patch.shape[1] - tpl.shape[1]) // 2, (patch.shape[0] - tpl.shape[0]) // 2
    return float(hi), (x - c[0], y - c[1])


def slot_scores(patches: list[np.ndarray], icons: dict, agents) -> np.ndarray:
    """`len(agents)` x 4 scores: each agent's icon for each slot matched in
    that slot's patch; NaN where the catalogue holds no icon."""
    out = np.full((len(agents), len(SLOT_KEYS)), np.nan)
    for i, a in enumerate(agents):
        per = icons.get(a) or {}
        for k, key in enumerate(SLOT_KEYS):
            if key in per:
                out[i, k] = match_icon(patches[k], per[key])[0]
    return out
