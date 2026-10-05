r"""Regenerate `domain/game_data.toml` from the extracted game files.

    .\.venv\Scripts\python.exe prototypes\game_data_facts.py            # write the facts file
    .\.venv\Scripts\python.exe prototypes\game_data_facts.py --check    # compare, write nothing
    .\.venv\Scripts\python.exe prototypes\game_data_facts.py --sheet    # print sheet cells, write nothing

What it reads
-------------
The game-extract exports of build release-13.06-shipping-18-5590001 under the
store's `reference/game-files/<build>/` (sets ability-states, ability-data,
game-data, weapon-data, ability-pickup), one JSON file per package, and the
engine config `config/ShooterGame/Config/DefaultEngine.ini` (world gravity),
exported raw by `game-extract export` with its manifest. `SPEC`
names each ability's values by package, export and field; the value itself
is always read from the export, never typed here. A value a class inherits
names its `owner`, and `read` checks that the package sits in the owner's
class chain and that no class between them overrides the field.

What it writes
--------------
`domain/game_data.toml`: one fact per ability plus five movement and unit
facts. Lengths are converted from centimetres to metres, speeds from cm/s to
m/s. Each value sits in a `values` group by what the field is: `life`,
`timing`, `size`, `angle`, `range`, `unconfirmed` (a length whose meaning the
files do not settle), `speed`, `move`, `minimap`, `other`.

It never writes `docs/ABILITY_MECHANICS_SHEET.md`; `--sheet` prints the
Duration cells it would fill and the "Game data" coverage table, for a person
to paste. It decodes no video and launches nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FACTS = REPO / "domain" / "game_data.toml"
SHEET = REPO / "docs" / "ABILITY_MECHANICS_SHEET.md"
STORE = Path(os.environ.get("RETICLE_STORE", "C:/Users/grant/reticle-store"))
BUILD_ID = 'release-13.06-shipping-18-5590001'
BUILD = str(STORE / "reference" / "game-files" / BUILD_ID)
SETS = ['ability-states', 'ability-data', 'game-data', 'weapon-data', 'ability-pickup']
SINCE = '2026-10-04'
STORE_REL = 'reference/game-files/' + BUILD_ID
_cache: dict = {}


# ---------------------------------------------------------------- reading exports

def where(pkg):
    rel = pkg.replace('/Game/', '', 1)
    for s in SETS:
        p = f'{BUILD}/{s}/ShooterGame/Content/{rel}.json'
        if os.path.exists(p):
            return s, p
    raise FileNotFoundError(pkg)


def load(pkg):
    if pkg not in _cache:
        s, p = where(pkg)
        with open(p, encoding='utf-8') as f:
            _cache[pkg] = (s, json.load(f))
    return _cache[pkg]


def super_of(pkg):
    _, d = load(pkg)
    for e in d:
        if e.get('Type') == 'BlueprintGeneratedClass' and e.get('Super'):
            sp = e['Super'].get('ObjectPath', '')
            if sp.startswith('/Game/'):
                return sp.rsplit('.', 1)[0]
    return None


def class_chain(pkg):
    """`pkg` and its parent classes, nearest first, as far as the exports reach."""
    out = [pkg]
    while True:
        try:
            s = super_of(out[-1])
        except FileNotFoundError:
            break
        if not s or s in out:
            break
        out.append(s)
    return out


def _walk(obj, path):
    for token in path.split('.'):
        if isinstance(obj, dict) and token in obj:
            obj = obj[token]
            continue
        m = re.fullmatch(r'([^\[]+)((?:\[\d+\])*)', token)
        if not m or not isinstance(obj, dict) or m.group(1) not in obj:
            raise KeyError(path)
        obj = obj[m.group(1)]
        for i in re.findall(r'\[(\d+)\]', m.group(2)):
            obj = obj[int(i)]
    return obj


def _exports(pkg, export):
    _, d = load(pkg)
    if export.startswith('Default__'):
        return [e for e in d if e.get('Name', '').startswith('Default__') and e.get('Name', '').endswith('_C')
                and e.get('Type', '').endswith('_C') and e.get('Name') == 'Default__' + e.get('Type')]
    return [e for e in d if e.get('Name') == export]


def has_field(pkg, export, field, any_type=False):
    """Whether `pkg` serializes `export.field`: a number, or with `any_type` any value."""
    for e in _exports(pkg, export):
        try:
            if any_type:
                _walk(e.get('Properties') or {}, field)
            else:
                _read(e, field)
            return True
        except (KeyError, IndexError, TypeError):
            pass
    return False


def _read(e, field):
    if field.startswith('Rows.'):
        row = e['Rows'][field[5:]]['Value']
        t = row['Type']
        if 'Float' in t:
            return row['FloatValue']
        if 'Int' in t:
            return row['IntValue']
        raise KeyError(field)
    v = _walk(e.get('Properties') or {}, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise KeyError(field)
    return v


def _check_owner(pkg, export, field, owner, any_type=False):
    if owner and owner != pkg:
        ch = class_chain(owner)
        if pkg not in ch:
            raise ValueError(f'{pkg} not in chain of {owner}: {ch}')
        for mid in ch[:ch.index(pkg)]:
            if has_field(mid, export, field, any_type):
                raise ValueError(f'{mid} overrides {export}.{field} between {owner} and {pkg}')


def read(pkg, export, field, owner=None):
    """Numeric value of `export.field` in `pkg`; with `owner`, check `pkg` is in
    the owner's class chain and that no class between them overrides the field."""
    _, d = load(pkg)
    hits = [e for e in d if e.get('Name') == export]
    if not hits:
        raise KeyError(f'{pkg}: no export {export}')
    v = _read(hits[0], field)
    _check_owner(pkg, export, field, owner)
    return v


def read_ref(pkg, export, field, owner=None):
    """The object path an object-reference field names, with the same owner check."""
    _, d = load(pkg)
    hits = [e for e in d if e.get('Name') == export]
    if not hits:
        raise KeyError(f'{pkg}: no export {export}')
    v = _walk(hits[0].get('Properties') or {}, field)
    if not isinstance(v, dict) or 'ObjectPath' not in v:
        raise KeyError(field)
    _check_owner(pkg, export, field, owner, any_type=True)
    return v['ObjectPath'].rsplit('.', 1)[0]


def asset_path(pkg):
    return 'ShooterGame/Content/' + pkg.replace('/Game/', '', 1) + '.uasset'


# ---------------------------------------------------------------- the citations
# Per-ability citations: role, key, unit, package, export, field (and the owner
# class when the value is inherited). Values are read from the export, never typed.

C = '/Game/Characters/'
A = '/Game/Abilities/'
NSZ = C + 'Global/Smoke/GameObject_NewSmokeZone_Parent'
MOLO = C + 'Global/Patch/Patch_Molotovs_Parent'
BG = A + 'Projectile_BaseGrenade'
BLM = A + 'Projectile_BaseLineMissile'
TOSS = A + 'Projectile_TossBase'
BEND = A + 'Projectile_BaseBendable'
LAUNCH = A + 'Projectile_LauncherBase'
BAI = C + '_Core/AI/BaseAIPawn'
BPAWN = C + '_Core/BasePawn'
FMD = C + '_Core/ForceModule_Dash'
WSM = C + '_Core/ForceModule_Dash_WallSlideMitigation'
DEF = lambda cls: 'Default__' + cls.rsplit('/', 1)[1] + '_C'  # noqa: E731
FSM = 'FiniteSpeedMovement_GEN_VARIABLE'


def V(role, key, unit, pkg, export, field, owner=None, note=None):
    return dict(role=role, key=key, unit=unit, parts=[(pkg, export, field)], owner=owner, note=note)


def P(role, key, unit, parts, owner=None, note=None):
    """A product of fields: a unit sphere's SphereRadius times its RelativeScale3D."""
    return dict(role=role, key=key, unit=unit, parts=parts, owner=owner, note=note)


def SPH(role, key, pkg, comp, radius_pkg=None, owner=None, note=None):
    """Sphere radius = SphereRadius (maybe inherited) x RelativeScale3D.X."""
    return P(role, key, 'cm', [(radius_pkg or pkg, comp, 'SphereRadius'), (pkg, comp, 'RelativeScale3D.X')],
             owner=owner, note=note)


def D(pkg, field, role='duration', key=None, unit='s', owner=None, note=None):
    return V(role, key or field, unit, pkg, DEF(pkg), field, owner, note)


SPEC = []


def ab(agent, slot, ability, values, missing=(), note='', refs=(), see=(), extra=None, supersedes=''):
    """One ability. `refs` cites object-reference fields (package, export, field,
    owner) in the source; `see` adds fact keys; `extra(rows)` returns an
    exceptions sentence computed from the read values; `supersedes` names the
    fact, or the part of one, whose number this fact's value replaces."""
    SPEC.append(dict(agent=agent, slot=slot, ability=ability, values=values, missing=list(missing), note=note,
                     refs=list(refs), see=list(see), extra=extra, supersedes=supersedes))

# ---------------------------------------------------------------- Astra
RIFT = C + 'Rift/S0/'
ab('Astra', 'C', 'Gravity Well', [
    D(RIFT + 'Ability_4/BlackHole/GameObject_Rift_4_BlackHole', 'TotalAbilityTime'),
    D(RIFT + 'Ability_4/BlackHole/GameObject_Rift_4_BlackHole', 'GravityOnlyTime'),
    D(RIFT + 'Ability_4/BlackHole/GameObject_Rift_4_BlackHole', 'ExpandTime'),
    D(RIFT + 'Ability_4/BlackHole/GameObject_Rift_4_BlackHole', 'FragileDuration'),
    SPH('size', 'GravitySphere radius', RIFT + 'Ability_4/BlackHole/GameObject_Rift_4_BlackHole', 'GravitySphere_GEN_VARIABLE'),
    SPH('size', 'ExplosionSphere radius', RIFT + 'Ability_4/BlackHole/GameObject_Rift_4_BlackHole', 'ExplosionSphere_GEN_VARIABLE'),
], missing=['placement range: the ability turns a star Astral Form placed; no range field on the equippable'])
ab('Astra', 'Q', 'Nova Pulse', [
    D(RIFT + 'Ability_Q/GameObject_Rift_Q_FlashBurst', 'ConcussDelay'),
    D(RIFT + 'Ability_Q/GameObject_Rift_Q_FlashBurst', 'ConcussDuration', role='other'),
    D(RIFT + 'Ability_Q/GameObject_Rift_Q_FlashBurst', 'ConcussionRange', role='size', unit='cm'),
], missing=['placement range: placed through a star; no range field'])
ab('Astra', 'E', 'Nebula  / Dissipate', [
    D(NSZ, 'SmokeDuration', owner=RIFT + 'Ability_E/GameObject_Rift_E_SmokeZone', key='SmokeDuration (inherited)'),
    D(RIFT + 'Ability_E/GameObject_Rift_E_SmokeZone', 'SmokeExpandDuration'),
    D(RIFT + 'Ability_E/GameObject_Rift_E_SmokeZone', 'SmokeDelayTime'),
    D(RIFT + 'Ability_E/GameObject_Rift_E_SmokeZone_Fake', 'SmokeDuration', key='Dissipate SmokeDuration'),
    SPH('size', 'VisionBlockingSphere radius', RIFT + 'Ability_E/GameObject_Rift_E_SmokeZone', 'VisionBlockingSphere_GEN_VARIABLE',
        radius_pkg=NSZ, owner=RIFT + 'Ability_E/GameObject_Rift_E_SmokeZone'),
    V('minimap', 'minimap Size', 'cm', RIFT + 'Ability_E/GameObject_Rift_E_SmokeZone', 'BaseMinimapComponent_Parent_GEN_VARIABLE', 'Size.X'),
], missing=['placement range: placed through a star (global placement)'])
ab('Astra', 'X', 'Astral Form / Cosmic Divide', [
    D(RIFT + 'Ability_X/WorldTargeting/GlobalWall/GameObject_Rift_X_GlobalWall', 'UpDuration'),
    D(RIFT + 'Ability_X/GameObject_Rift_X_Markers', 'CreationWarmupTime', key='star CreationWarmupTime'),
    V('range', 'Cosmic Divide MaxCastDistance', 'cm', RIFT + 'Ability_X/WorldTargeting/StateComponent_Rift_X_WallTargeting_FreeTarget',
      'Default__StateComponent_Rift_X_WallTargeting_FreeTarget_C', 'MaxCastDistance'),
    V('minimap', 'Cosmic Divide minimap Size', 'cm', RIFT + 'Ability_X/WorldTargeting/GlobalWall/GameObject_Rift_X_GlobalWall',
      'BaseMinimapComponent_Parent_GEN_VARIABLE', 'Size.X'),
], missing=['wall length and height: GameObject_Rift_X_GlobalWall holds no extent field', 'star placement range'])

# ---------------------------------------------------------------- Breach
BR = C + 'Breach/S0/'
ab('Breach', 'C', 'Aftershock', [
    D(BR + 'Ability_4/GameObject_Breach_4_FusionBlast', 'ChargeTime'),
    D(BR + 'Ability_4/GameObject_Breach_4_FusionBlast', 'ExplodeDelay'),
    D(BR + 'Ability_4/Ability_Breach_4_FusionBlast', 'ExplosionLength', role='size', unit='cm'),
    D(BR + 'Ability_4/Ability_Breach_4_FusionBlast', 'ExplosionWidth', role='size', unit='cm'),
    V('range', 'TargetingRange', 'cm', BR + 'Ability_4/Ability_Breach_4_FusionBlast', 'FilteredWallPenetrationTargetingComponent_GEN_VARIABLE', 'TargetingRange'),
    V('speed', 'ProjectileSpeed', 'cm_s', BR + 'Ability_4/Projectile_Breach_4_FusionBlast', FSM, 'ProjectileSpeed'),
])
ab('Breach', 'Q', 'Flashpoint', [
    V('duration', 'flash MaxDuration', 's', BR + 'Ability_Q/Projectile_Breach_Q_ThroughWalls_Flash', 'FlashbangExplosion_PopFlash_GEN_VARIABLE', 'MaxDuration'),
    D(BR + 'Ability_Q/Projectile_Breach_Q_ThroughWalls_Flash', 'InitialLifeSpan'),
    V('range', 'TargetingRange', 'cm', BR + 'Ability_Q/Ability_Breach_Q_Flash', 'FilteredWallPenetrationTargetingComponent_GEN_VARIABLE', 'TargetingRange'),
    V('speed', 'ProjectileSpeed', 'cm_s', BR + 'Ability_Q/Projectile_Breach_Q_ThroughWalls_Flash', FSM, 'ProjectileSpeed'),
], missing=['flash radius'])
ab('Breach', 'E', 'Fault Line', [
    D(BR + 'Ability_E/GameObject_Breach_E_SweetSpotFissure', 'InitialDelay'),
    D(BR + 'Ability_E/GameObject_Breach_E_SweetSpotFissure', 'ConcussDuration', role='other'),
    D(BR + 'Ability_E/GameObject_Breach_E_SweetSpotFissure', 'FissureMoveSpeed', role='speed', unit='cm_s'),
    V('minimap', 'aim preview Size.X', 'cm', BR + 'Ability_E/Ability_Breach_E_Fissure', 'EquippableMinimapComponent_Line_GEN_VARIABLE', 'Size.X'),
    V('minimap', 'aim preview Size.Y', 'cm', BR + 'Ability_E/Ability_Breach_E_Fissure', 'EquippableMinimapComponent_Line_GEN_VARIABLE', 'Size.Y'),
], missing=['maximum length (set by the charge; no length field)', 'width'])
ab('Breach', 'X', 'Rolling Thunder', [
    D(BR + 'Ability_X/GameObject_Breach_X_Shockwave', 'InitialDelay'),
    D(BR + 'Ability_X/GameObject_Breach_X_Shockwave', 'DelayBetweenZones'),
    D(BR + 'Ability_X/GameObject_Breach_X_Shockwave', 'EndDelay'),
    D(BR + 'Ability_X/GameObject_Breach_X_Shockwave', 'ConcussDuration', role='other'),
    V('size', 'WarningIndicatorZone half-extent X', 'cm', BR + 'Ability_X/GameObject_Breach_X_Shockwave', 'WarningIndicatorZone_GEN_VARIABLE', 'BoxExtent.X'),
    V('size', 'WarningIndicatorZone half-extent Y', 'cm', BR + 'Ability_X/GameObject_Breach_X_Shockwave', 'WarningIndicatorZone_GEN_VARIABLE', 'BoxExtent.Y'),
    D(BR + 'Ability_X/GameObject_Breach_X_Shockwave', 'ForwardVectorOffSet', role='range', unit='cm'),
])

# ---------------------------------------------------------------- Brimstone
SG = C + 'Sarge/S0/'
ab('Brimstone', 'C', 'Stim Beacon', [
    V('duration', 'StimBeaconDuration', 's', SG + 'Ability_SpeedStim/AbilityTuning_Sarge_E_SpeedStim', 'AbilityTuning_Sarge_E_SpeedStim', 'Rows.StimBeaconDuration'),
    D(SG + 'Ability_SpeedStim/GameObject_Sarge_E_SpeedStim', 'ZoneLifetime'),
    V('size', 'StimBeaconInnerRadius', 'cm', SG + 'Ability_SpeedStim/AbilityTuning_Sarge_E_SpeedStim', 'AbilityTuning_Sarge_E_SpeedStim', 'Rows.StimBeaconInnerRadius'),
    V('size', 'StimBeaconOuterRadius', 'cm', SG + 'Ability_SpeedStim/AbilityTuning_Sarge_E_SpeedStim', 'AbilityTuning_Sarge_E_SpeedStim', 'Rows.StimBeaconOuterRadius'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', TOSS, FSM, 'ProjectileSpeed', owner=SG + 'Ability_SpeedStim/Projectile_Sarge_E_SpeedStim'),
])
ab('Brimstone', 'Q', 'Incendiary', [
    D(MOLO, 'FireActiveDuration', owner=SG + 'Ability_Molotov/Patch_Sarge_Q_Molotov_Production', key='FireActiveDuration (inherited)'),
    D(MOLO, 'ClampedRadius', role='size', unit='cm', owner=SG + 'Ability_Molotov/Patch_Sarge_Q_Molotov_Production', key='ClampedRadius (inherited)'),
    V('speed', 'ProjectileSpeed', 'cm_s', SG + 'Ability_Molotov/Projectile_Sarge_Q_Molotov_Production', FSM, 'ProjectileSpeed'),
], missing=['throw range (a ballistic throw; no range field)'])
ab('Brimstone', 'E', 'Sky Smoke', [
    D(SG + 'Ability_MapTargetSmoke/GameObject_Sarge_4_Smoke_ProductionNEW', 'SmokeDuration'),
    D(SG + 'Ability_MapTargetSmoke/GameObject_Sarge_4_Smoke_ProductionNEW', 'SmokeDelayTime'),
    D(SG + 'Ability_MapTargetSmoke/GameObject_Sarge_4_Smoke_ProductionNEW', 'SmokeExpandDuration'),
    SPH('size', 'VisionBlockingSphere radius (inherited)', NSZ, 'VisionBlockingSphere_GEN_VARIABLE', owner=SG + 'Ability_MapTargetSmoke/GameObject_Sarge_4_Smoke_ProductionNEW'),
    V('range', 'MapRange', 'cm', SG + 'Ability_MapTargetSmoke/Ability_Sarge_4_MapTargetSmoke_Production', 'MapTargetingState_GEN_VARIABLE', 'MapRange'),
], note='the smoke radius is the parent class GameObject_NewSmokeZone_Parent sphere, which GameObject_Sarge_4_Smoke_ProductionNEW does not override')
ab('Brimstone', 'X', 'Orbital Strike', [
    D(SG + 'Ability_OrbitalStrike/GameObject_Sarge_X_OrbitalStrike_Production', 'TelegraphTime'),
    V('size', 'damageCapsule radius', 'cm', SG + 'Ability_OrbitalStrike/GameObject_Sarge_X_OrbitalStrike_Production', 'damageCapsule_GEN_VARIABLE', 'CapsuleRadius'),
    V('size', 'visionBlockingCapsule radius', 'cm', SG + 'Ability_OrbitalStrike/GameObject_Sarge_X_OrbitalStrike_Production', 'visionBlockingCapsule_GEN_VARIABLE', 'CapsuleRadius'),
    V('range', 'MapRange', 'cm', SG + 'Ability_OrbitalStrike/Ability_Sarge_X_OrbitalStrike', 'MapTargetingState_GEN_VARIABLE', 'MapRange'),
], missing=['strike duration after the telegraph'])

# ---------------------------------------------------------------- Chamber
DE = C + 'Deadeye/S0/'
ab('Chamber', 'C', 'Trademark', [
    D(DE + 'Ability_4/GameObject_Deadeye_E_Trap', 'InitialArmTime'),
    D(DE + 'Ability_4/Patch_Deadeye_E_Slow_Large', 'FireActiveDuration', key='slow field FireActiveDuration'),
    D(DE + 'Ability_4/GameObject_Deadeye_E_Trap', 'DetectionRadius2D', role='size', unit='cm'),
    D(DE + 'Ability_4/Patch_Deadeye_E_Slow_Large', 'ClampedRadius', role='size', unit='cm', key='slow field ClampedRadius'),
    V('range', 'TargetingRange', 'cm', DE + 'Ability_4/Ability_Deadeye_4_Trap', 'PlacementTargetingState_GEN_VARIABLE', 'TargetingRange'),
    V('minimap', 'MinimapTriggerRange Size', 'cm', DE + 'Ability_4/GameObject_Deadeye_E_Trap', 'MinimapTriggerRange_GEN_VARIABLE', 'Size.X'),
])
ab('Chamber', 'E', 'Rendezvous', [
    V('move', 'TeleportRadius', 'cm', DE + 'Ability_E/AbilityTuning_Deadeye_E_Teleport_Tether', 'AbilityTuning_Deadeye_E_Teleport_Tether', 'Rows.TeleportRadius'),
    V('range', 'TargetingRange', 'cm', DE + 'Ability_E/Ability_Deadeye_E_Teleporter_Tethers', 'StateComponent_PlacementTargeting_RequiredDistanceFromContext_GEN_VARIABLE', 'TargetingRange'),
    V('minimap', 'Minimap_ActivationRange Size', 'cm', DE + 'Ability_E/GameObject_Deadeye_E_Teleporter_Tether', 'Minimap_ActivationRange_GEN_VARIABLE', 'Size.X'),
], missing=['duration (a placed anchor persists; no lifetime field)'])
ab('Chamber', 'Q', 'Headhunter', [
    V('other', 'Capacity', 'n', DE + 'Ability_Q/AbilityTuning_Deadeye_Q_Pistol', 'AbilityTuning_Deadeye_Q_Pistol', 'Rows.Capacity'),
], missing=['duration and geometry: a gun, which places nothing'])
ab('Chamber', 'X', 'Tour De Force', [
    V('other', 'Ammo', 'n', DE + 'Ability_X/AbilityTuning_Deadeye_X', 'AbilityTuning_Deadeye_X', 'Rows.Ammo'),
], missing=['duration and geometry: a gun; the slow field a kill leaves is not tied to this ability by a field read here'])

# ---------------------------------------------------------------- Clove
SM = C + 'Smonk/S0/'
ab('Clove', 'C', 'Pick-me-up', [
    V('duration', 'BuffActive TimerLength', 's', SM + 'Ability_4/ReactiveArmor/Ability_Smonk_BFArmor_Reactive', 'UseMachineState_BuffActive_GEN_VARIABLE', 'TimerLength'),
    D(SM + 'Ability_4/ReactiveArmor/Ability_Smonk_BFArmor_Reactive', 'TempHealthSustainTime'),
], missing=['geometry: a self buff'])
ab('Clove', 'Q', 'Meddle', [
    D(SM + 'Ability_Q/DebuffKnife/DecayLauncher/GameObject_Smonk_Q_DecayExplosion', 'InitialLifeSpan'),
    D(SM + 'Ability_Q/DebuffKnife/DecayLauncher/GameObject_Smonk_Q_DecayExplosion', 'Radius', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed', 'cm_s', SM + 'Ability_Q/DebuffKnife/DecayLauncher/Projectile_Smonk_DecayNade', FSM, 'ProjectileSpeed'),
    V('duration', 'FuseTimer', 's', SM + 'Ability_Q/DebuffKnife/DecayLauncher/Projectile_Smonk_DecayNade', 'FuseTimer_GEN_VARIABLE', 'TimerDuration'),
], missing=['decay duration on a target'])
ab('Clove', 'E', 'Ruse', [
    D(SM + 'Ability_E/MapTargetSmoke/GameObject_Smonk_NewSmoke', 'SmokeDuration'),
    D(SM + 'Ability_E/MapTargetSmoke/GameObject_Smonk_NewSmoke', 'SmokeDelayTime'),
    D(SM + 'Ability_E/MapTargetSmoke/GameObject_Smonk_NewSmoke_PDS', 'SmokeDuration', key='post-death SmokeDuration'),
    SPH('size', 'VisionBlockingSphere radius (inherited)', NSZ, 'VisionBlockingSphere_GEN_VARIABLE', owner=SM + 'Ability_E/MapTargetSmoke/GameObject_Smonk_NewSmoke'),
    V('range', 'MapRange', 'cm', SM + 'Ability_E/MapTargetSmoke/Ability_Smonk_E_MapTargetSmokeV2', 'MapTargetingState_GEN_VARIABLE', 'MapRange'),
    V('range', 'MapTargetingRange', 'cm', SM + 'Ability_E/MapTargetSmoke/Ability_Smonk_E_MapTargetSmokeV2', 'MapTargetingState_GEN_VARIABLE', 'MapTargetingRange'),
], note='the radius is GameObject_NewSmokeZone_Parent\'s sphere, inherited by GameObject_Smonk_NewSmoke')
ab('Clove', 'X', 'Not Dead Yet', [
    V('duration', 'RepositioningState TimerLength', 's', SM + 'Ability_X/ReactiveRes/Ability_Smonk_X_ReactiveRes_Engineering', 'RepositioningState_GEN_VARIABLE', 'TimerLength'),
    V('duration', 'FightingState AssistTimeAllowance', 's', SM + 'Ability_X/ReactiveRes/Ability_Smonk_X_ReactiveRes_Engineering', 'FightingState_WaitForKillOrAssist_GEN_VARIABLE', 'AssistTimeAllowance'),
], missing=['geometry: a self revive'])

# ---------------------------------------------------------------- Cypher
GU = C + 'Gumshoe/S0/'
ab('Cypher', 'C', 'Trapwire', [
    V('size', 'MaxWireLength', 'cm', GU + 'Ability_4/AbilityTuning_Gumshoe_4_TripWire', 'AbilityTuning_Gumshoe_4_TripWire', 'Rows.MaxWireLength'),
    V('range', 'WireTargetingDistance', 'cm', GU + 'Ability_4/AbilityTuning_Gumshoe_4_TripWire', 'AbilityTuning_Gumshoe_4_TripWire', 'Rows.WireTargetingDistance'),
    D(GU + 'Ability_4/GameObject_Gumshoe_4_TripWire', 'ArmTime'),
], missing=['duration (the wire persists; no lifetime field)'])
ab('Cypher', 'E', 'Spycam', [
    V('range', 'TargetingRange', 'cm', GU + 'Ability_E/Ability_Gumshoe_E_Camera', 'PlaceCamera_GEN_VARIABLE', 'TargetingRange'),
    V('speed', 'dart ProjectileSpeed', 'cm_s', GU + 'Ability_E/Projectile_Gumshoe_E_CameraTrackingDart', FSM, 'ProjectileSpeed'),
    D(GU + 'Ability_E/GameObject_RemovableObject_GumshoeTrackingDart', 'PingMarkedTargetDelay'),
], missing=['camera duration (persists; no lifetime field)'])
ab('Cypher', 'Q', 'Cyber Cage', [
    D(GU + 'Ability_Q/Zone_Gumshoe_Q_Cage', 'SustainTime'),
    D(GU + 'Ability_Q/Zone_Gumshoe_Q_Cage', 'DeployTime'),
    D(GU + 'Ability_Q/Zone_Gumshoe_Q_Cage', 'ContractTime'),
    V('size', 'CageRadius', 'cm', GU + 'Ability_Q/AbilityTuning_Gumshoe_Q_CageTrap', 'AbilityTuning_Gumshoe_Q_CageTrap', 'Rows.CageRadius'),
    V('size', 'Capsule radius', 'cm', GU + 'Ability_Q/Zone_Gumshoe_Q_Cage', 'Capsule_GEN_VARIABLE', 'CapsuleRadius'),
    V('size', 'Capsule half-height', 'cm', GU + 'Ability_Q/Zone_Gumshoe_Q_Cage', 'Capsule_GEN_VARIABLE', 'CapsuleHalfHeight'),
    V('speed', 'ProjectileSpeed', 'cm_s', GU + 'Ability_Q/Projectile_Gumshoe_Q_CageTrap', FSM, 'ProjectileSpeed'),
])
ab('Cypher', 'X', 'Neural Theft', [
    V('range', 'CorpseTargeting Radius', 'cm', GU + 'Ability_X/Ability_Gumshoe_X_InterrogateV2', 'CorpseTargetingStateComponent_GEN_VARIABLE', 'Radius'),
    V('duration', 'Reveal Delay', 's', GU + 'Ability_X/GameObject_Gumshoe_X_InterrogateHat', 'Default__GameObject_Gumshoe_X_InterrogateHat_C', 'Reveal Delay'),
    V('duration', 'Reping Delay', 's', GU + 'Ability_X/GameObject_Gumshoe_X_InterrogateHat', 'Default__GameObject_Gumshoe_X_InterrogateHat_C', 'Reping Delay'),
    V('other', 'MaxCorpseTime', 's', GU + 'Ability_X/Ability_Gumshoe_X_InterrogateV2', 'CorpseTargetingStateComponent_GEN_VARIABLE', 'MaxCorpseTime'),
], missing=['geometry: reveals enemies wherever they are'])

# ---------------------------------------------------------------- Deadlock
CB = C + 'Cable/S0/'
ab('Deadlock', 'C', 'Barrier Mesh', [
    V('duration', 'LifeDuration', 's', CB + 'Ability_E/GameObject_CableJamRoot', 'Comp_Actor_DamageOverTime_GEN_VARIABLE', 'LifeDuration'),
    V('duration', 'FortificationDelay', 's', CB + 'Ability_E/GameObject_CableJamRoot', 'Comp_Actor_FortifyAfterTime_GEN_VARIABLE', 'FortificationDelay'),
    D(CB + 'Ability_E/GameObject_CableJamRoot', 'MaxHorizontalWallRange', role='size', unit='cm'),
    D(CB + 'Ability_E/GameObject_CableJam_CableDeployer_Precomputed', 'WallHeight', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed', 'cm_s', CB + 'Ability_E/Projectile_CableJam_InAir', FSM, 'ProjectileSpeed'),
])
ab('Deadlock', 'E', 'GravNet', [
    D(CB + 'Ability_4/Patch_Cable_4_NetToss', 'FireActiveDuration'),
    V('duration', 'PullOutDuration', 's', CB + 'Ability_4/AbilityTuning_Cable_4_NetToss', 'AbilityTuning_Cable_4_NetToss', 'Rows.PullOutDuration'),
    D(CB + 'Ability_4/Patch_Cable_4_NetToss', 'ClampedRadius', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BG, FSM, 'ProjectileSpeed', owner=CB + 'Ability_4/Projectile_Cable_4_NetToss'),
])
ab('Deadlock', 'Q', 'Sonic Sensor', [
    V('range', 'TargetingRange', 'cm', CB + 'Ability_Q/Ability_Cable_Q_SoundSensor', 'LineTargetingState_VerticalDistanceClamp_GEN_VARIABLE', 'TargetingRange'),
    V('size', 'BoxSenseArea half-extent X', 'cm', CB + 'Ability_Q/GameObject_StealthingTrap_SoundSensor', 'BoxSenseArea_GEN_VARIABLE', 'BoxExtent.X'),
    V('size', 'BoxSenseArea half-extent Y', 'cm', CB + 'Ability_Q/GameObject_StealthingTrap_SoundSensor', 'BoxSenseArea_GEN_VARIABLE', 'BoxExtent.Y'),
    V('size', 'HearingRange', 'cm', CB + 'Ability_Q/GameObject_StealthingTrap_SoundSensor', 'AISenseConfig_Hearing_0', 'HearingRange'),
    D(CB + 'Ability_Q/GameObject_SoundSensor_SweetSpotFissure', 'ConcussDuration', role='other'),
    V('duration', 'ArmTime (inherited)', 's', A + 'GameObject_StealthingTrap_Base', 'Default__GameObject_StealthingTrap_Base_C', 'ArmTime', owner=CB + 'Ability_Q/GameObject_StealthingTrap_SoundSensor'),
], missing=['duration (the sensor persists; no lifetime field)'])
ab('Deadlock', 'X', 'Annihilation', [
    V('range', 'Maximum Range', 'cm', CB + 'Ability_X/Actor_FishingHook', 'Default__Actor_FishingHook_C', 'Maximum Range'),
    V('speed', 'Collider Speed', 'cm_s', CB + 'Ability_X/Actor_FishingHook', 'Default__Actor_FishingHook_C', 'Collider Speed'),
    V('size', 'Projectile Stopped Radius', 'cm', CB + 'Ability_X/Actor_FishingHook', 'Default__Actor_FishingHook_C', 'Projectile Stopped Radius'),
    V('duration', 'Spline Duration', 's', CB + 'Ability_X/GameObject_Spline', 'Spline_GEN_VARIABLE', 'Duration'),
    V('duration', 'cage FullTimerForSpline', 's', CB + 'Ability_X/GameObject_FishingHook_CageSphere', 'SyncedTimer_FullTimerForSpline_GEN_VARIABLE', 'TimerDuration'),
])

# ---------------------------------------------------------------- Fade
BH = C + 'BountyHunter/S0/'
ab('Fade', 'C', 'Prowler', [
    D(BH + 'Ability_4/Pawn_BountyHunter_4_WolfHound', 'Duration'),
    V('speed', 'MovementTuning.BaseValues.MaxSpeed', 'cm_s', BH + 'Ability_4/Pawn_BountyHunter_4_WolfHound', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
    D(BH + 'Ability_4/Pawn_BountyHunter_4_WolfHound', 'Nearsight Radius', role='size', unit='cm'),
    V('range', 'SightRadius', 'cm', BH + 'Ability_4/Controller_BountyHunter_4_WolfHound', 'AISenseConfig_Sight_0', 'SightRadius'),
])
ab('Fade', 'E', 'Haunt', [
    V('duration', 'Duration', 's', BH + 'Ability_E/AbilityTuning_BountyHunter_E_ReconDiveBomb', 'AbilityTuning_BountyHunter_E_ReconDiveBomb', 'Rows.Duration'),
    D(BH + 'Ability_E/GameObject_BountyHunter_E_LoSReveal_Source_Reactivate', 'Radius', role='size', unit='cm'),
    V('duration', 'drop TimeDelay', 's', BH + 'Ability_E/Projectile_E_BountyHunter_Divebomb', 'Comp_Projectile_DropAfterTimeout_GEN_VARIABLE', 'TimeDelay'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BG, FSM, 'ProjectileSpeed', owner=BH + 'Ability_E/Projectile_E_BountyHunter_Divebomb'),
    V('minimap', 'reveal radius minimap Size', 'cm', BH + 'Ability_E/GameObject_BountyHunter_E_LoSReveal_Source_Reactivate', 'MinimapComponent_EnemyRequiredDistance_Radius_GEN_VARIABLE', 'Size.X'),
])
ab('Fade', 'Q', 'Seize', [
    D(BH + 'Ability_Q/GameObject_Q_BountyHunter_Tether_SphereExpansion', 'InitialLifeSpan'),
    D(BH + 'Ability_Q/GameObject_Q_BountyHunter_Tether_SphereExpansion', 'Tether Scan Radius', role='size', unit='cm'),
    V('duration', 'drop TimeDelay', 's', BH + 'Ability_Q/Projectile_Q_BountyHunter_TetherGrenade_SphereExpansion', 'Comp_Projectile_DropAfterTimeout_GEN_VARIABLE', 'TimeDelay'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BG, FSM, 'ProjectileSpeed', owner=BH + 'Ability_Q/Projectile_Q_BountyHunter_TetherGrenade_SphereExpansion'),
])
ab('Fade', 'X', 'Nightfall', [
    D(BH + 'Ability_X/GameObject_BountyHunter_X_WaveForm', 'EndDelay'),
    D(BH + 'Ability_X/GameObject_BountyHunter_X_WaveForm', 'DelayBetweenZones'),
    D(BH + 'Ability_X/GameObject_BountyHunter_X_WaveForm', 'ForwardVectorOffSet', role='range', unit='cm'),
], missing=['wave length and width: GameObject_BountyHunter_X_WaveForm holds no extent field'])

# ---------------------------------------------------------------- Gekko
AG = C + 'AggroBot/S0/'
ab('Gekko', 'C', 'Mosh Pit', [
    D(AG + 'Ability_4/Patch_Aggrobot_C_ExplodeyPatch', 'FireActiveDuration'),
    V('duration', 'SyncedTimer', 's', AG + 'Ability_4/Patch_Aggrobot_C_ExplodeyPatch', 'SyncedTimer_GEN_VARIABLE', 'TimerDuration'),
    D(AG + 'Ability_4/Patch_Aggrobot_C_ExplodeyPatch', 'ClampedRadius', role='size', unit='cm'),
    D(AG + 'Ability_4/Patch_Aggrobot_C_ExplodeyPatch', 'Inner Radius', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BG, FSM, 'ProjectileSpeed', owner=AG + 'Ability_4/Projectile_Aggrobot_C_ExplodeyPatch'),
])
ab('Gekko', 'E', 'Dizzy', [
    D(AG + 'Ability_E/Projectile_E_Aggrobot_DiscTurret_PowerWave', 'InitialLifeSpan'),
    V('range', 'SightRadius', 'cm', AG + 'Ability_E/Projectile_E_Aggrobot_DiscTurret_PowerWave', 'AISenseConfig_Sight_0', 'SightRadius'),
    V('speed', 'ProjectileSpeed', 'cm_s', AG + 'Ability_E/Projectile_E_Aggrobot_DiscTurret_PowerWave', FSM, 'ProjectileSpeed'),
    V('speed', 'plasma ProjectileSpeed', 'cm_s', AG + 'Ability_E/Projectile_Aggrobot_Zamboni_Rocket', FSM, 'ProjectileSpeed'),
    D(AG + 'Ability_E/Projectile_Aggrobot_Zamboni_Rocket', 'Damage Radius', role='size', unit='cm', key='plasma Damage Radius'),
])
ab('Gekko', 'Q', 'Wingman', [
    V('duration', 'SeekTimeout', 's', AG + 'Ability_Q/AbilityTuning_Aggrobot_Q_SeekerNade', 'AbilityTuning_Aggrobot_Q_SeekerNade', 'Rows.SeekTimeout'),
    V('speed', 'MovementTuning.BaseValues.MaxSpeed', 'cm_s', AG + 'Ability_Q/Pawn_Aggrobot_SeekerNade', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
    V('range', 'SightRadius', 'cm', AG + 'Ability_Q/Pawn_Aggrobot_SeekerNade', 'AISenseConfig_Sight_0', 'SightRadius'),
    D(AG + 'Ability_Q/Pawn_Aggrobot_SeekerNade', 'Attack Distance', role='range', unit='cm'),
    V('size', 'PlayerExplodeSphere radius', 'cm', AG + 'Ability_Q/Pawn_Aggrobot_SeekerNade', 'PlayerExplodeSphere_GEN_VARIABLE', 'SphereRadius'),
    D(AG + 'Ability_Q/Ability_Q_Aggrobot_SeekerNade', 'Max Path Distance', role='range', unit='cm'),
])
ab('Gekko', 'X', 'Thrash', [
    D(AG + 'Ability_X/Pawn_Aggrobot_RollyPolly', 'Lifetime Duration'),
    V('speed', 'MovementTuning.BaseValues.MaxSpeed', 'cm_s', AG + 'Ability_X/Pawn_Aggrobot_RollyPolly', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
    D(AG + 'Ability_X/Pawn_Aggrobot_RollyPolly', 'Detain Radius', role='size', unit='cm'),
    D(AG + 'Ability_X/Pawn_Aggrobot_RollyPolly', 'Stun Duration', role='other'),
])

# ---------------------------------------------------------------- Harbor
MAX2D_NOTE = ("Max2D_Distance caps the 2D path of the projectile that lays the wall; whether that cap is the wall's length or the throw's range is unconfirmed, so it is filed as unconfirmed, not as a size")
MG = C + 'Mage/S0/'
ab('Harbor', 'C', 'Storm Surge', [
    D(MG + 'Ability_4/GameObject_Mage_4_SplashGrenade', 'ExplosionRadius', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed', 'cm_s', MG + 'Ability_4/Projectile_Mage_4_SplashGrenade', FSM, 'ProjectileSpeed'),
    V('minimap', 'minimap Size', 'cm', MG + 'Ability_4/GameObject_Mage_4_SplashGrenade', 'AresFastMinimapIcon_GEN_VARIABLE', 'Size.X'),
], missing=['effect duration'])
ab('Harbor', 'E', 'Cove', [
    D(MG + 'Ability_E/GameObject_Mage_E_WorldSmoke', 'SmokeDuration'),
    D(MG + 'Ability_E/GameObject_Mage_E_WorldSmoke', 'ShieldFormDelay'),
    SPH('size', 'VisionBlockingSphere radius', MG + 'Ability_E/GameObject_Mage_E_WorldSmoke', 'VisionBlockingSphere_GEN_VARIABLE',
        radius_pkg=NSZ, owner=MG + 'Ability_E/GameObject_Mage_E_WorldSmoke'),
    V('range', 'MaxDistance', 'cm', MG + 'Ability_E/Projectile_Mage_E_WorldSmoke', 'Comp_Projectile_Charged_StraightLineDistance_GEN_VARIABLE', 'MaxDistance'),
    V('speed', 'ProjectileSpeed', 'cm_s', MG + 'Ability_E/Projectile_Mage_E_WorldSmoke', FSM, 'ProjectileSpeed'),
])
ab('Harbor', 'Q', 'High Tide', [
    D(MG + 'Ability_Q/GameObject_Mage_Q_WallManager', 'WallDuration'),
    D(MG + 'Ability_Q/Projectile_Mage_Q_Wall', 'Max2D_Distance', role='unconfirmed', unit='cm'),
    D(MG + 'Ability_Q/Projectile_Mage_Q_Wall', '2D_DistanceBetweenWallAnchors', role='other', unit='cm'),
    V('speed', 'ProjectileSpeed', 'cm_s', MG + 'Ability_Q/Projectile_Mage_Q_Wall', FSM, 'ProjectileSpeed'),
], missing=['wall height and thickness'], note=MAX2D_NOTE)
ab('Harbor', 'X', 'Reckoning', [
    D(MG + 'Ability_X/GameObject_Mage_X_TidalWave', 'Range', role='size', unit='cm'),
    D(MG + 'Ability_X/GameObject_Mage_X_TidalWave', 'Velocity', role='speed', unit='cm_s'),
    D(MG + 'Ability_X/GameObject_Mage_X_TidalWave_Chunk', 'ChunkWidth', role='size', unit='cm'),
    V('other', 'WaveNumChunks', 'n', MG + 'Ability_X/AbilityTuning_Mage_X_Wave', 'AbilityTuning_Mage_X_Wave', 'Rows.WaveNumChunks'),
    V('duration', 'WallLingerState CountdownTime', 's', MG + 'Ability_X/GameObject_Mage_X_TidalWave_Chunk', 'WallLingerState_GEN_VARIABLE', 'CountdownTime'),
])

# ---------------------------------------------------------------- Iso
SQ = C + 'Sequoia/S0/'
ab('Iso', 'C', 'Contingency', [
    D(SQ + 'Ability_4/GameObject_Sequoia_4_MovingCover', 'SplineTotalLength', role='size', unit='cm', key='SplineTotalLength (travel)'),
    V('size', 'FrontWallLength', 'cm', SQ + 'Ability_4/AbilityTuning_Sequoia_4_Wave', 'AbilityTuning_Sequoia_4_Wave', 'Rows.FrontWallLength'),
    V('size', 'FrontWallHitbox half-height', 'cm', SQ + 'Ability_4/GameObject_Sequoia_4_MovingCover', 'FrontWallHitbox_GEN_VARIABLE', 'BoxExtent.Z'),
    V('minimap', 'minimap Size.Y', 'cm', SQ + 'Ability_4/GameObject_Sequoia_4_MovingCover', 'AresFastMinimapIcon_GEN_VARIABLE', 'Size.Y'),
], missing=['duration', 'speed: MovementSpeed 3.6 has no stated unit'])
ab('Iso', 'Q', 'Undercut', [
    V('range', 'TriggerDistance', 'cm', SQ + 'Ability_Q/Projectile_Sequoia_Q_FragileMissile', 'Comp_Projectile_MaximumRange_GEN_VARIABLE', 'TriggerDistance'),
    V('size', 'Sphere radius', 'cm', SQ + 'Ability_Q/Projectile_Sequoia_Q_FragileMissile', 'Sphere_GEN_VARIABLE', 'SphereRadius'),
    V('speed', 'ProjectileSpeed', 'cm_s', SQ + 'Ability_Q/Projectile_Sequoia_Q_FragileMissile', FSM, 'ProjectileSpeed'),
], missing=['debuff duration'])
ab('Iso', 'E', 'Double Tap', [
    D(SQ + 'Ability_E/WreckingBall/GameObject_Sequoia_E_Orb', 'InitialLifeSpan', key='orb InitialLifeSpan'),
    V('size', 'orb Sphere radius', 'cm', SQ + 'Ability_E/WreckingBall/GameObject_Sequoia_E_Orb', 'Sphere_GEN_VARIABLE', 'SphereRadius'),
], missing=['focus-state duration'])
ab('Iso', 'X', 'Kill Contract', [
    D(SQ + 'Ability_X/GameObject_Sequoia_X_LineCapture', 'InitialLifeSpan'),
    D(SQ + 'Ability_X/Actor_Sequoia_X_StandardArena', 'DuelTimeoutDuration'),
    V('size', 'Capsule radius', 'cm', SQ + 'Ability_X/Ability_X_Sequoia_ArenaLineCapture', 'Capsule_GEN_VARIABLE', 'CapsuleRadius'),
    V('size', 'Capsule half-height', 'cm', SQ + 'Ability_X/Ability_X_Sequoia_ArenaLineCapture', 'Capsule_GEN_VARIABLE', 'CapsuleHalfHeight'),
    V('minimap', 'minimap Size.X', 'cm', SQ + 'Ability_X/GameObject_Sequoia_X_LineCapture', 'BaseMinimapComponent_Parent_GEN_VARIABLE', 'Size.X'),
    V('minimap', 'minimap Size.Y', 'cm', SQ + 'Ability_X/GameObject_Sequoia_X_LineCapture', 'BaseMinimapComponent_Parent_GEN_VARIABLE', 'Size.Y'),
], missing=['move: the caster is teleported into an arena; no distance field'])

# ---------------------------------------------------------------- Jett
WU = C + 'Wushu/S0/'
ab('Jett', 'C', 'Cloudburst', [
    V('duration', 'SmokeDuration', 's', WU + 'Ability_4/AbilityTuning_Wushu_4_Smoke', 'AbilityTuning_Wushu_4_Smoke', 'Rows.SmokeDuration'),
    D(WU + 'Ability_4/GameObject_Wushu_4_SmokeZone', 'SmokeExpandDuration'),
    SPH('size', 'VisionBlockingSphere radius', WU + 'Ability_4/GameObject_Wushu_4_SmokeZone', 'VisionBlockingSphere_GEN_VARIABLE',
        radius_pkg=NSZ, owner=WU + 'Ability_4/GameObject_Wushu_4_SmokeZone'),
    V('speed', 'ProjectileSpeed', 'cm_s', WU + 'Ability_4/Projectile_Wushu_4_Smoke', FSM, 'ProjectileSpeed'),
    V('duration', 'travel GrenadeStopAfterTimeout', 's', WU + 'Ability_4/Projectile_Wushu_4_Smoke', 'GrenadeStopAfterTimeout_GEN_VARIABLE', 'TimeDelay'),
    V('minimap', 'minimap Size', 'cm', WU + 'Ability_4/GameObject_Wushu_4_SmokeZone', 'BaseMinimapComponent_Parent_GEN_VARIABLE', 'Size.X'),
])
ab('Jett', 'Q', 'Updraft', [
    D(WU + 'Ability_Q/ForceModule_Wushu_Q_SelfBoost', 'MaxImpulse', role='move', unit='raw'),
    V('duration', 'ApplyForceModuleState TimerLength', 's', WU + 'Ability_Q/Ability_Wushu_Q_CycloneBoost', 'ApplyForceModuleState_GEN_VARIABLE', 'TimerLength'),
], missing=['rise height: set by curves (DesiredZVelocityByJumpHeight) with no numeric default'])
ab('Jett', 'E', 'Tailwind', [
    D(WU + 'Ability_E/ForceModule_Wushu_E_Dash', 'BaseVelocity', role='move', unit='cm_s'),
    D(WU + 'Ability_E/ForceModule_Wushu_E_Dash', 'Duration', role='move'),
    V('duration', 'PrimeDuration', 's', WU + 'Ability_E/AbilityTuning_Wushu_E_Dash', 'AbilityTuning_Wushu_E_Dash', 'Rows.PrimeDuration'),
], note='speed x duration is 11.25 m; that product is arithmetic, not a field, and ignores the stopping phase')
ab('Jett', 'X', 'Blade Storm', [], missing=['duration and geometry: thrown knives; no lifetime or area field'])

# ---------------------------------------------------------------- KAY/O
GR = C + 'Grenadier/S0/'
ab('KAY/O', 'C', 'FRAG/ment', [
    V('duration', 'SyncedTimer', 's', GR + 'Ability_Q/Projectile_Grenadier_Q_SemtexBasic', 'SyncedTimer_GEN_VARIABLE', 'TimerDuration'),
    D(GR + 'Ability_Q/Projectile_Grenadier_Q_SemtexBasic', 'Damage Outer Radius', role='size', unit='cm'),
    D(GR + 'Ability_Q/Projectile_Grenadier_Q_SemtexBasic', 'Damage Inner Radius', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BG, FSM, 'ProjectileSpeed', owner=GR + 'Ability_Q/Projectile_Grenadier_Q_SemtexBasic'),
])
ab('KAY/O', 'Q', 'FLASH/drive', [
    V('duration', 'flash MaxDuration', 's', GR + 'Ability_4/Projectile_C_Grenadier_Flash', 'FlashbangExplosion_GEN_VARIABLE', 'MaxDuration'),
    V('duration', 'Explosion Timer', 's', GR + 'Ability_4/Projectile_C_Grenadier_Flash', 'Explosion Timer_GEN_VARIABLE', 'TimerDuration'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BG, FSM, 'ProjectileSpeed', owner=GR + 'Ability_4/Projectile_C_Grenadier_Flash'),
], missing=['flash radius'])
ab('KAY/O', 'E', 'ZERO/point', [
    D(GR + 'Ability_E/Gameobject_Grenadier_E_SuppressionPulse', 'InitialLifeSpan'),
    D(GR + 'Ability_E/Comp_Grenadier_Knife_Tracking', 'Suppression Duration', role='other'),
    D(GR + 'Ability_E/Gameobject_Grenadier_E_SuppressionPulse', 'Tech Scan Radius', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BLM, FSM, 'ProjectileSpeed', owner=GR + 'Ability_E/Projectile_Grenadier_E_SuppressionBlade'),
])
ab('KAY/O', 'X', 'NULL/cmd', [
    V('duration', 'WaitForDowned TimerLength', 's', GR + 'Ability_X/Ability_Grenadier_X_OverloadPulse', 'StateComponent_TimedState_WaitForDowned_GEN_VARIABLE', 'TimerLength'),
    D(GR + 'Ability_X/Gameobject_Grenadier_X_UltPulse', 'ActualFinalRadius', role='size', unit='cm'),
    D(GR + 'Ability_X/Gameobject_Grenadier_X_UltPulse', 'Pulse Out Total Time'),
])

# ---------------------------------------------------------------- Killjoy
KJ = C + 'Killjoy/S0/'
ab('Killjoy', 'C', 'Nanoswarm', [
    D(KJ + 'Ability_4/GameObject_Killjoy_4_BeeSwarm_Damage', 'Duration'),
    V('size', 'FeedbackSphere radius', 'cm', KJ + 'Ability_4/Projectile_Killjoy_4_RemoteBees_MultiDetonate', 'FeedbackSphere_GEN_VARIABLE', 'SphereRadius'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BG, FSM, 'ProjectileSpeed', owner=KJ + 'Ability_4/Projectile_Killjoy_4_RemoteBees_MultiDetonate'),
], missing=['damage radius distinct from the feedback sphere'])
ab('Killjoy', 'Q', 'ALARMBOT', [
    V('range', 'TargetingRange', 'cm', KJ + 'Ability_Q/Ability_Killjoy_Q_Alarmbot', 'PlacementTargetingState_GEN_VARIABLE', 'TargetingRange'),
    V('size', 'DetectEnemySphere radius', 'cm', KJ + 'Ability_Q/Pawn_Killjoy_Q_StealthAlarmbot', 'DetectEnemySphere_GEN_VARIABLE', 'SphereRadius'),
    V('range', 'MaxDistanceBeforeDisable', 'cm', KJ + 'Ability_Q/Pawn_Killjoy_Q_StealthAlarmbot', 'Comp_GameObject_DisableOwnerDistance_GEN_VARIABLE', 'MaxDistanceBeforeDisable'),
    V('speed', 'MovementTuning.BaseValues.MaxSpeed', 'cm_s', KJ + 'Ability_Q/Pawn_Killjoy_Q_StealthAlarmbot', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
    V('minimap', 'minimap circle Size', 'cm', KJ + 'Ability_Q/Pawn_Killjoy_Q_StealthAlarmbot', 'BaseMinimapComponent_Parent_Circle_GEN_VARIABLE', 'Size.X'),
], missing=['duration (persists; no lifetime field)'])
ab('Killjoy', 'E', 'TURRET', [
    V('range', 'TargetingRange', 'cm', KJ + 'Ability_E/Ability_Killjoy_E_Turret', 'PlacementTargetingState_GEN_VARIABLE', 'TargetingRange'),
    V('angle', 'PeripheralVisionAngleDegrees', 'deg', KJ + 'Ability_E/Controller_Killjoy_E_Turret', 'AISenseConfig_Sight_0', 'PeripheralVisionAngleDegrees'),
    V('range', 'MaxDistanceBeforeDisable', 'cm', KJ + 'Ability_E/Pawn_Killjoy_E_Turret', 'Comp_GameObject_DisableOwnerDistance_GEN_VARIABLE', 'MaxDistanceBeforeDisable'),
    V('duration', 'DeployState TimerLength', 's', KJ + 'Ability_E/Ability_Killjoy_E_TurretAttack', 'DeployState_GEN_VARIABLE', 'TimerLength'),
], missing=['duration (persists; no lifetime field)'])
ab('Killjoy', 'X', 'Lockdown', [
    D(KJ + 'Ability_X/GameObject_Killjoy_X_Bomb', 'ShockwaveDelay'),
    D(KJ + 'Ability_X/GameObject_Killjoy_X_Bomb', 'WindupTime'),
    D(KJ + 'Ability_X/GameObject_Killjoy_X_Shockwave', 'InitialLifeSpan', key='shockwave InitialLifeSpan'),
    V('size', 'BombRadius', 'cm', KJ + 'Ability_X/GameObject_Killjoy_X_Bomb', 'BombRadius_GEN_VARIABLE', 'SphereRadius'),
    V('minimap', 'minimap Size', 'cm', KJ + 'Ability_X/GameObject_Killjoy_X_Bomb', 'AresFastMinimapArea_GEN_VARIABLE', 'Size.X'),
])

# ---------------------------------------------------------------- Miks


def _miks_disagreement(rows):
    """The files' smoke duration against the player's, stored as a disagreement."""
    v = {r['tkey']: r['value'] for r in rows}
    d, x, e, c = (v['smoke_delay_time_s'], v['smoke_duration_s'], v['smoke_expand_duration_s'],
                  v['smoke_contract_duration_s'])
    return (f"The player and the wiki gave 16.75 s [domain:abilities/miks-smoke-duration]; SmokeDuration here "
            f"is {fmt(x)} s, with a {fmt(d)} s delay, a {fmt(e)} s expansion and a {fmt(c)} s contraction. Delay, "
            f"duration and contraction sum to {fmt(d)} + {fmt(x)} + {fmt(c)} = {fmt(d + x + c)} s, close to the "
            f"18.2 s minimap disc [domain:abilities/miks-smoke-minimap-disc]. The files' values stand "
            f"[domain:abilities/game-files-outrank-player-quantities]; the 16.75 s stays on the player's fact "
            f"as its record.")


def _omen_disc(rows):
    """The measured minimap disc against the files' timings: a stored surprise."""
    v = {r['tkey']: r['value'] for r in rows}
    d, x, c, life = (v['smoke_delay_time_s'], v['smoke_duration_s'], v['smoke_contract_duration_s'],
                     v['initial_life_span_s'])
    return (f"Surprise, stored: the measured minimap disc lasts 15.0 s [domain:abilities/omen-dark-cover], "
            f"which equals delay plus duration, {fmt(d)} + {fmt(x)} = {fmt(d + x)} s, not InitialLifeSpan "
            f"({fmt(life)} s) nor delay, duration and contraction ({fmt(d + x + c)} s). Miks's disc instead "
            f"spans its delay, duration and contraction; each ability draws by its own rule "
            f"[domain:abilities/ability-rules-are-unique]. The files' values stand "
            f"[domain:abilities/game-files-outrank-player-quantities].")


IR = C + 'Iris/S0/'
ab('Miks', 'C', 'M-pulse', [
    D(IR + 'Ability_4/GameObject_Thumper_Base', 'ThumpDuration'),
    D(IR + 'Ability_4/GameObject_Thumper_Base', 'WindupDuration'),
    V('other', 'NumPulses', 'n', IR + 'Ability_4/AbilityTuning_Iris_Thumper', 'AbilityTuning_Iris_Thumper', 'Rows.NumPulses'),
    V('size', 'Radius', 'cm', IR + 'Ability_4/AbilityTuning_Iris_Thumper', 'AbilityTuning_Iris_Thumper', 'Rows.Radius'),
    V('speed', 'ProjectileSpeed', 'cm_s', IR + 'Ability_4/Projectile_Thumper_Base', FSM, 'ProjectileSpeed'),
    V('minimap', 'minimap Size', 'cm', IR + 'Ability_4/GameObject_Thumper_Concuss', 'AresFastMinimapArea_GEN_VARIABLE', 'Size.X'),
])
ab('Miks', 'E', 'Waveform', [
    D(IR + 'Ability_E/GameObject_Iris_E_Smoke', 'SmokeDuration'),
    D(IR + 'Ability_E/GameObject_Iris_E_Smoke', 'SmokeDelayTime'),
    D(IR + 'Ability_E/GameObject_Iris_E_Smoke', 'SmokeExpandDuration'),
    D(IR + 'Ability_E/GameObject_Iris_E_Smoke', 'SmokeContractDuration'),
    SPH('size', 'VisionBlockingSphere radius (inherited)', NSZ, 'VisionBlockingSphere_GEN_VARIABLE', owner=IR + 'Ability_E/GameObject_Iris_E_Smoke'),
    V('range', 'MapRange', 'cm', IR + 'Ability_E/Ability_Iris_E_MT_Smoke_Production', 'MapTargetingState_GEN_VARIABLE', 'MapRange'),
], note='GameObject_Iris_E_Smoke sits in the ability folder; the entity walk of ability-states-gamedata-0.2.0 does not reach it',
   see=['abilities/miks-smoke-duration', 'abilities/miks-smoke-minimap-disc',
        'abilities/game-files-outrank-player-quantities'], extra=_miks_disagreement,
   supersedes='[domain:abilities/miks-smoke-duration]: its 16.75 s smoke duration, by the player\'s ruling '
              'that game-file quantities outrank the player\'s and the wiki\'s numbers '
              '[domain:abilities/game-files-outrank-player-quantities]')
ab('Miks', 'Q', 'Harmonize', [
    V('duration', 'Buff Duration', 's', IR + 'Ability_Q/Ability_Iris_Harmonize', 'Default__Ability_Iris_Harmonize_C', 'Buff Duration'),
], missing=['geometry: a buff on one ally'])
ab('Miks', 'X', 'Bassquake', [
    V('size', 'Wave Radius', 'cm', IR + 'Ability_X/Ability_Iris_X_SonicWave', 'Default__Ability_Iris_X_SonicWave_C', 'Wave Radius'),
    V('angle', 'Wave Angle', 'deg', IR + 'Ability_X/Ability_Iris_X_SonicWave', 'Default__Ability_Iris_X_SonicWave_C', 'Wave Angle'),
    V('duration', 'Windup Duration', 's', IR + 'Ability_X/Ability_Iris_X_SonicWave', 'Default__Ability_Iris_X_SonicWave_C', 'Windup Duration'),
    V('other', 'Slow Buff Duration', 's', IR + 'Ability_X/Ability_Iris_X_SonicWave', 'Default__Ability_Iris_X_SonicWave_C', 'Slow Buff Duration'),
])

# ---------------------------------------------------------------- Neon
SP = C + 'Sprinter/S0/'
ab('Neon', 'C', 'Fast Lane', [
    D(SP + 'Ability_4/GameObject_Sprinter_4_Tunnel', 'WallDuration'),
    D(SP + 'Ability_4/Projectile_Neon_C_Tunnel', 'MaxDistance', role='unconfirmed', unit='cm'),
    D(SP + 'Ability_4/GameObject_Sprinter_4_Tunnel', 'TunnelWidth', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed', 'cm_s', SP + 'Ability_4/Projectile_Neon_C_Tunnel', FSM, 'ProjectileSpeed'),
], note="MaxDistance caps the travel of the projectile that lays the two walls; whether that cap is the walls' "
        "length or the throw's range is unconfirmed, so it is filed as unconfirmed, not as a size")
ab('Neon', 'Q', 'Relay Bolt', [
    D(SP + 'Ability_Q/GameObject_Sprinter_Q_ElectricSphere', 'Final Radius', role='size', unit='cm'),
    D(SP + 'Ability_Q/GameObject_Sprinter_Q_ElectricSphere', 'Concuss Duration', role='other'),
    V('duration', 'SyncedTimer', 's', SP + 'Ability_Q/GameObject_Sprinter_Q_ElectricSphere', 'SyncedTimer_GEN_VARIABLE', 'TimerDuration'),
    V('speed', 'ProjectileSpeed', 'cm_s', SP + 'Ability_Q/Projectile_Sprinter_4_GroundStrike', FSM, 'ProjectileSpeed'),
    V('range', 'MaximumRange', 'cm', SP + 'Ability_Q/Projectile_Sprinter_4_GroundStrike', FSM, 'MaximumRange'),
])
ab('Neon', 'E', 'High Gear', [
    D(SP + 'Ability_E/FM_Sprinter_SlideDash', 'BaseVelocity', role='move', unit='cm_s', key='slide BaseVelocity'),
    V('move', 'Slide_State_Sliding TimerLength', 's', SP + 'Ability_E/Ability_Sprinter_E_Sprint_Production', 'Slide_State_Sliding_GEN_VARIABLE', 'TimerLength'),
], missing=['sprint speed: no speed field on the sprint state or its buff', 'duration: fuel-based'])
ab('Neon', 'X', 'Overdrive', [], missing=['duration and geometry: a gun; no lifetime or area field'])

# ---------------------------------------------------------------- Omen
WR = C + 'Wraith/S0/'
ab('Omen', 'C', 'Shrouded Step', [
    V('move', 'ShroudedStepRange', 'cm', WR + 'Ability_E/AbilityTuning_Wraith_E_ShortTeleport', 'AbilityTuning_Wraith_E_ShortTeleport', 'Rows.ShroudedStepRange'),
    V('range', 'TargetingRange', 'cm', WR + 'Ability_E/Ability_Wraith_E_ShortTeleport', 'PlacementTargetingState_GEN_VARIABLE', 'TargetingRange'),
    V('duration', 'TeleportExecute TimerLength', 's', WR + 'Ability_E/Ability_Wraith_E_ShortTeleport', 'StartTeleportAndCheckDestination_TeleportExecute_GEN_VARIABLE', 'TimerLength'),
])
ab('Omen', 'Q', 'Paranoia', [
    V('range', 'TriggerDistance', 'cm', WR + 'Ability_Q/Projectile_Wraith_Q_NearsightMissile', 'Comp_Projectile_MaximumRange_GEN_VARIABLE', 'TriggerDistance'),
    V('size', 'CollisionSphere radius', 'cm', WR + 'Ability_Q/Projectile_Wraith_Q_NearsightMissile', 'CollisionSphere_GEN_VARIABLE', 'SphereRadius'),
    V('speed', 'ProjectileSpeed', 'cm_s', WR + 'Ability_Q/Projectile_Wraith_Q_NearsightMissile', FSM, 'ProjectileSpeed'),
], missing=['nearsight duration'])
ab('Omen', 'E', 'Dark Cover', [
    D(WR + 'Ability_4/Zone_Wraith_4_Smoke', 'SmokeDuration'),
    D(WR + 'Ability_4/Zone_Wraith_4_Smoke', 'SmokeDelayTime'),
    D(WR + 'Ability_4/Zone_Wraith_4_Smoke', 'SmokeContractDuration'),
    D(WR + 'Ability_4/Zone_Wraith_4_Smoke', 'InitialLifeSpan'),
    SPH('size', 'VisionBlockingSphere radius', WR + 'Ability_4/Zone_Wraith_4_Smoke', 'VisionBlockingSphere_GEN_VARIABLE',
        radius_pkg=NSZ, owner=WR + 'Ability_4/Zone_Wraith_4_Smoke'),
    V('range', 'MaxDistance', 'cm', WR + 'Ability_4/Projectile_Wraith_4_Smoke', 'Comp_Projectile_Charged_StraightLineDistance_GEN_VARIABLE', 'MaxDistance'),
    V('speed', 'ProjectileSpeed', 'cm_s', WR + 'Ability_4/Projectile_Wraith_4_Smoke', 'Comp_Projectile_FloatCurveMovement_GEN_VARIABLE', 'ProjectileSpeed'),
], see=['abilities/omen-dark-cover', 'abilities/game-files-outrank-player-quantities'], extra=_omen_disc)
ab('Omen', 'X', 'From the Shadows', [
    V('duration', 'DisappearAndEQS TimerLength', 's', WR + 'Ability_X/Ability_Wraith_X_GlobalTeleport', 'DisappearAndEQS_GEN_VARIABLE', 'TimerLength'),
    V('duration', 'Appear TimerLength', 's', WR + 'Ability_X/Ability_Wraith_X_GlobalTeleport', 'Appear_GEN_VARIABLE', 'TimerLength'),
], missing=['move: teleports anywhere on the map; no range field'])

# ---------------------------------------------------------------- Phoenix
PH = C + 'Phoenix/S0/'
ab('Phoenix', 'C', 'Blaze', [
    D(PH + 'Ability_Q/Production/GameObject_Phoenix_Q_FlameWallManager_Production', 'WallDuration'),
    V('duration', 'WallProjectileDuration', 's', PH + 'Ability_Q/Production/AbilityTuning_Phoenix_Q_FlameWall', 'AbilityTuning_Phoenix_Q_FlameWall', 'Rows.WallProjectileDuration'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BEND, FSM, 'ProjectileSpeed', owner=PH + 'Ability_Q/Production/Projectile_Phoenix_Q_FlameWall_Production'),
], missing=['wall length (the wall projectile travels for WallProjectileDuration; no length field)', 'wall height'])
ab('Phoenix', 'Q', 'Hot Hands', [
    D(PH + 'Ability_4/Production/NewMolotov/Patch_Phoenix_MolotovFire', 'FireActiveDuration'),
    D(PH + 'Ability_4/Production/NewMolotov/Patch_Phoenix_MolotovFire', 'ClampedRadius', role='size', unit='cm'),
    V('duration', 'drop TimeDelay', 's', PH + 'Ability_4/Production/Projectile_Phoenix_4_Molotov_Production', 'Comp_Projectile_DropAfterTimeout_GEN_VARIABLE', 'TimeDelay'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BG, FSM, 'ProjectileSpeed', owner=PH + 'Ability_4/Production/Projectile_Phoenix_4_Molotov_Production'),
])
ab('Phoenix', 'E', 'Curveball', [
    V('duration', 'DetonationSyncedTimer', 's', PH + 'Ability_E/Production/Projectile_Phoenix_E_FlareCurve_Synced', 'DetonationSyncedTimer_GEN_VARIABLE', 'TimerDuration'),
    V('speed', 'PrecalculatedProjectileMovement ProjectileSpeed', 'cm_s', PH + 'Ability_E/Production/Projectile_Phoenix_E_FlareCurve_Synced', 'PrecalculatedProjectileMovement_GEN_VARIABLE', 'ProjectileSpeed'),
    V('other', 'flash MaxDuration (Production projectile)', 's', PH + 'Ability_E/Production/Projectile_Phoenix_E_FlareCurve_Production', 'FlashbangExplosion_PopFlash_GEN_VARIABLE', 'MaxDuration'),
], missing=['flash radius'], note='the walk reaches Projectile_Phoenix_E_FlareCurve_Synced; the Production projectile beside it carries the flash duration')
ab('Phoenix', 'X', 'Run it Back', [
    V('duration', 'PreventDeathState TimerLength', 's', PH + 'Ability_X/Production/Ability_Phoenix_X_SelfRes_Production', 'PreventDeathState_GEN_VARIABLE', 'TimerLength'),
], missing=['move: returns the caster to the cast point; no distance field'])

# ---------------------------------------------------------------- Raze
CL = C + 'Clay/S0/'
ab('Raze', 'C', 'Boom Bot', [
    D(CL + 'Ability_E/Pawn_Clay_E_Boomba', 'Duration'),
    V('speed', 'MovementTuning.BaseValues.MaxSpeed', 'cm_s', CL + 'Ability_E/Pawn_Clay_E_Boomba', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
    D(CL + 'Ability_E/Pawn_Clay_E_Boomba', 'ExplosionOuterRadius', role='size', unit='cm'),
    V('range', 'SightRadius', 'cm', CL + 'Ability_E/Controller_Clay_E_Boomba', 'AISenseConfig_Sight_0', 'SightRadius'),
    V('angle', 'PeripheralVisionAngleDegrees', 'deg', CL + 'Ability_E/Controller_Clay_E_Boomba', 'AISenseConfig_Sight_0', 'PeripheralVisionAngleDegrees'),
])
ab('Raze', 'Q', 'Blast Pack', [
    D(CL + 'Ability_Q/Projectile_Clay_Q_Satchel_Arming', 'InitialLifeSpan'),
    D(CL + 'Ability_Q/Projectile_Clay_Q_Satchel_Arming', 'ArmTime'),
    D(CL + 'Ability_Q/GameObject_Clay_Q_Explosion', 'DamageOuterRadius', role='size', unit='cm'),
    D(CL + 'Ability_Q/ForceModule_Clay_Q_KnockbackSelf', 'KnockbackStrength', role='move', unit='raw'),
    D(CL + 'Ability_Q/ForceModule_Clay_Q_KnockbackSelf', 'KnockUp', role='move', unit='raw'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', TOSS, FSM, 'ProjectileSpeed', owner=CL + 'Ability_Q/Projectile_Clay_Q_Satchel_Arming'),
])
ab('Raze', 'E', 'Paint Shells', [
    D(CL + 'Ability_4/Projectile_Clay_4_Projectile_Primary', 'InitialLifeSpan'),
    V('size', 'primary ExplosionRadius', 'cm', CL + 'Ability_4/Projectile_Clay_4_Projectile_Primary', 'RadialDamageProjectileEffect_GEN_VARIABLE', 'ExplosionRadius'),
    V('size', 'secondary ExplosionRadius', 'cm', CL + 'Ability_4/Projectile_Clay_4_Projectile_Secondary', 'RadialDamageProjectileEffect_GEN_VARIABLE', 'ExplosionRadius'),
    V('other', 'ClusterGrenadeNumSecondaryGrenades', 'n', CL + 'Ability_4/AbilityTuning_Clay_4_ClusterGrenade', 'AbilityTuning_Clay_4_ClusterGrenade', 'Rows.ClusterGrenadeNumSecondaryGrenades'),
    V('speed', 'secondary ProjectileSpeed', 'cm_s', CL + 'Ability_4/Projectile_Clay_4_Projectile_Secondary', FSM, 'ProjectileSpeed'),
])
ab('Raze', 'X', 'Showstopper', [
    V('duration', 'RocketTimer TimerLength', 's', CL + 'Ability_X/Ability_Clay_X_RocketLauncher', 'RocketTimer_GEN_VARIABLE', 'TimerLength'),
    V('size', 'ExplosionRadius', 'cm', CL + 'Ability_X/Projectile_Clay_X_Rocket', 'RadialDamageProjectileEffect_GEN_VARIABLE', 'ExplosionRadius'),
    V('speed', 'ProjectileSpeed', 'cm_s', CL + 'Ability_X/Projectile_Clay_X_Rocket', FSM, 'ProjectileSpeed'),
], note='the rocket\'s ProjectileSpeed default is 250 cm/s; the class may accelerate it at run time')

# ---------------------------------------------------------------- Reyna
VA = C + 'Vampire/S0/'
ab('Reyna', 'C', 'Leer', [
    D(VA + 'Ability_4/GameObject_Vampire_4_NearsightAOE_Source', 'InitialLifeSpan'),
    V('range', 'TriggerDistance', 'cm', VA + 'Ability_4/Projectile_Vampire_4_NearsightAoE', 'Comp_Projectile_MaximumRange_GEN_VARIABLE', 'TriggerDistance'),
    V('speed', 'ProjectileSpeed', 'cm_s', VA + 'Ability_4/Projectile_Vampire_4_NearsightAoE', 'Comp_Projectile_FloatCurveMovement_GEN_VARIABLE', 'ProjectileSpeed'),
    D(VA + 'Ability_4/GameObject_Vampire_4_NearsightAOE_Source', 'Radius', role='size', unit='cm'),
])
ab('Reyna', 'Q', 'Devour', [
    D(VA + 'Ability_Q/GameObject_Vampire_Q_Heal_HealPool_Parent', 'OrbLifetimeDuration', key='soul orb OrbLifetimeDuration'),
    D(VA + 'Ability_Q/GameObject_Vampire_Q_Heal_HealPool_Parent', 'FullHealTime'),
    V('range', 'FindBloodPools SearchRadius', 'cm', VA + 'Ability_Q/Ability_Vampire_Q_Heal', 'FindBloodPools_GEN_VARIABLE', 'SearchRadius'),
], missing=['geometry: a self heal'])
ab('Reyna', 'E', 'Dismiss', [
    V('duration', 'InvisAndInvulnBuff TimerLength', 's', VA + 'Ability_E/Ability_Vampire_E_Escape', 'InvisAndInvulnBuff_GEN_VARIABLE', 'TimerLength'),
], missing=['move: a speed buff; its force module holds only curves, no numeric speed'])
ab('Reyna', 'X', 'Empress', [
    V('duration', 'TimedState_CastDelay TimerLength', 's', VA + 'Ability_X/Ability_Vampire_X_Frenzy', 'TimedState_CastDelay_GEN_VARIABLE', 'TimerLength'),
], missing=['ult duration: the wait-for-kill state carries an unbounded timer (1e21 s)', 'geometry: a self buff'])

# ---------------------------------------------------------------- Sage
TH = C + 'Thorne/S0/'
ab('Sage', 'C', 'Barrier Orb', [
    V('duration', 'segment LifeDuration', 's', TH + 'Ability_E/GameObject_Thorne_E_Wall_Segment_Fortifying', 'Comp_Actor_DamageOverTime_GEN_VARIABLE', 'LifeDuration'),
    V('duration', 'segment FortificationDelay', 's', TH + 'Ability_E/GameObject_Thorne_E_Wall_Segment_Fortifying', 'Comp_Actor_FortifyAfterTime_GEN_VARIABLE', 'FortificationDelay'),
    D(TH + 'Ability_E/GameObject_Thorne_E_Wall_Fortifying', 'WallSegmentLength', role='size', unit='cm'),
    V('other', 'NumWallSegments', 'n', TH + 'Ability_E/AbilityTuning_Thorne_4_Wall', 'AbilityTuning_Thorne_4_Wall', 'Rows.NumWallSegments'),
    V('range', 'TargetingRange', 'cm', TH + 'Ability_E/StateComponent_PlacementTargeting_ThorneWall', 'Default__StateComponent_PlacementTargeting_ThorneWall_C', 'TargetingRange'),
], missing=['wall height'])
ab('Sage', 'Q', 'Slow Orb', [
    D(TH + 'Ability_4/Patch_Thorne_4_SlowField_Production', 'MaixmumLifetime'),
    D(TH + 'Ability_4/Patch_Thorne_4_SlowField_Production', 'ClampedRadius', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed', 'cm_s', TH + 'Ability_4/Projectile_Thorne_4_SlowFIeld_Production', FSM, 'ProjectileSpeed'),
])
ab('Sage', 'E', 'Healing Orb', [
    V('range', 'DamagedPlayerTargeting Radius', 'cm', TH + 'Ability_Q/Ability_Thorne_Q_Heal_Production_New', 'StateComponent_DamagedPlayerTargeting_GEN_VARIABLE', 'Radius'),
], missing=['heal duration', 'geometry: a heal on one player'])
ab('Sage', 'X', 'Resurrection', [
    V('range', 'CorpseTargeting Radius', 'cm', TH + 'Ability_X/Ability_Thorne_X_Resurrect_Production', 'CorpseTargetingStateComponent_GEN_VARIABLE', 'Radius'),
], missing=['duration: a revive, no lifetime'])

# ---------------------------------------------------------------- Skye
GD = C + 'Guide/S0/'
ab('Skye', 'C', 'Regrowth', [
    V('size', 'OverlapSphere radius', 'cm', GD + 'Ability_4/GameObject_Guide_4_Heal_AOE', 'OverlapSphere_GEN_VARIABLE', 'SphereRadius'),
    V('minimap', 'minimap Size', 'cm', GD + 'Ability_4/GameObject_Guide_4_Heal_AOE', 'BaseMinimapComponent_Parent_GEN_VARIABLE', 'Size.X'),
], missing=['duration: fuel-based channel; the fuel state timer is unbounded'])
ab('Skye', 'Q', 'Trailblazer', [
    V('duration', 'PossessDuration TimerLength', 's', GD + 'Ability_Q/Ability_Guide_Q_PossessableScout_ScoutAbilities', 'PossessDuration_GEN_VARIABLE', 'TimerLength'),
    V('speed', 'MovementTuning.BaseValues.MaxSpeed', 'cm_s', GD + 'Ability_Q/Pawn_Guide_Q_PossessableScout', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
    V('size', 'ConcussionRange', 'cm', GD + 'Ability_Q/Pawn_Guide_Q_PossessableScout', 'Comp_Actor_ConcussionExplosion_AtLocation_GEN_VARIABLE', 'ConcussionRange'),
    V('range', 'attack Radius', 'cm', GD + 'Ability_Q/Ability_Guide_Q_PossessableScout_ScoutAbilities', 'ActorTargetingState_Attack_GEN_VARIABLE', 'Radius'),
])
ab('Skye', 'E', 'Guiding Light', [
    D(GD + 'Ability_E/Projectile_Guide_E_HawkFlash', 'Duration'),
    V('speed', 'ProjectileSpeed', 'cm_s', GD + 'Ability_E/Projectile_Guide_E_HawkFlash', FSM, 'ProjectileSpeed'),
    D(GD + 'Ability_E/GameObject_Guide_E_HawkFlash_FlashSource', 'Radius', role='size', unit='cm', key='flash Radius'),
    V('other', 'flash MaxDuration', 's', GD + 'Ability_E/GameObject_Guide_E_HawkFlash_FlashSource', 'FlashbangExplosion_GEN_VARIABLE', 'MaxDuration'),
])
ab('Skye', 'X', 'Seekers', [
    D(GD + 'Ability_X/Pawn_Guide_X_Pack', 'FollowDuration'),
    V('speed', 'MovementTuning.BaseValues.MaxSpeed', 'cm_s', GD + 'Ability_X/Pawn_Guide_X_Pack', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
    V('other', 'MaxSeekersSpawned', 'n', GD + 'Ability_X/AbilityTuning_Guide_X_Pack', 'AbilityTuning_Guide_X_Pack', 'Rows.MaxSeekersSpawned'),
])

# ---------------------------------------------------------------- Sova
HU = C + 'Hunter/S0/'
ab('Sova', 'C', 'Owl Drone', [
    V('duration', 'DroneDuration TimerLength', 's', HU + 'Ability_E/Drone/Ability_Hunter_E_Drone_Abilities', 'DroneDuration_GEN_VARIABLE', 'TimerLength'),
    P('speed', 'BaseValues.MaxSpeed x DefaultStateMultipliers[5].MaxSpeed', 'cm_s',
      [(HU + 'Ability_E/Drone/Pawn_Hunter_E_Drone', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
       (HU + 'Ability_E/Drone/Pawn_Hunter_E_Drone', 'CharMoveComp', 'MovementTuning.DefaultStateMultipliers[5].MaxSpeed')],
      note='index 5 of EAresMovementType is Flying (usmap enum); the product is arithmetic'),
    D(HU + 'Ability_E/Drone/GameObject_Hunter_E_Drone_RevealDart', 'InitialLifeSpan', key='dart InitialLifeSpan'),
])
ab('Sova', 'Q', 'Shock Bolt', [
    V('size', 'ExplosiveBoltOuterRadius', 'cm', HU + 'Ability_4/AbilityTuning_Hunter_4_BoltExplosive', 'AbilityTuning_Hunter_4_BoltExplosive', 'Rows.ExplosiveBoltOuterRadius'),
    V('size', 'ExplosiveBoltInnerRadius', 'cm', HU + 'Ability_4/AbilityTuning_Hunter_4_BoltExplosive', 'AbilityTuning_Hunter_4_BoltExplosive', 'Rows.ExplosiveBoltInnerRadius'),
    D(HU + 'Ability_4/GameObject_Hunter_4_ExplosiveBolt_Explosion', 'InitialDelay'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BLM, FSM, 'ProjectileSpeed', owner=HU + 'Ability_4/Projectile_Hunter_4_ExplosiveBolt'),
], note='the bow\'s draw may set the bolt speed at run time; the class default is what is cited')
ab('Sova', 'E', 'Recon Bolt', [
    D(HU + 'Ability_Q/GameObject_Hunter_Q_SonarPing', 'MaxSonarRadius', role='size', unit='cm'),
    D(HU + 'Ability_Q/GameObject_Hunter_Q_SonarPing', 'SonarSpreadTime'),
    D(HU + 'Ability_Q/GameObject_Hunter_Q_SonarBolt', 'InitialPingDelay'),
    D(HU + 'Ability_Q/GameObject_Hunter_Q_SonarBolt', 'DelayBetweenPings'),
    V('other', 'RevealBoltMaxPulses', 'n', HU + 'Ability_Q/AbilityTuning_Hunter_Q_RevealBolt', 'AbilityTuning_Hunter_Q_RevealBolt', 'Rows.RevealBoltMaxPulses'),
    V('speed', 'ProjectileSpeed (inherited)', 'cm_s', BLM, FSM, 'ProjectileSpeed', owner=HU + 'Ability_Q/Projectile_Hunter_Q_RevealBolt'),
    V('minimap', 'minimap Size', 'cm', HU + 'Ability_Q/GameObject_Hunter_Q_SonarBolt', 'MinimapComponent_EnemyRequiredDistance_Radius_GEN_VARIABLE', 'Size.X'),
], note='the bow\'s draw may set the bolt speed at run time; the class default is what is cited')
ab('Sova', 'X', "Hunter's Fury", [
    V('size', 'CapsuleRange', 'cm', HU + 'Ability_X/Ability_Hunter_X_LaserMulti', 'LSM_SphereSweepTargetingState_GEN_VARIABLE', 'CapsuleRange'),
    V('size', 'sweep SphereRadius', 'cm', HU + 'Ability_X/Ability_Hunter_X_LaserMulti', 'LSM_SphereSweepTargetingState_GEN_VARIABLE', 'SphereRadius'),
    V('duration', 'LaserActiveTimedState TimerLength', 's', HU + 'Ability_X/Ability_Hunter_X_LaserMulti', 'LaserActiveTimedState_GEN_VARIABLE', 'TimerLength'),
])

# ---------------------------------------------------------------- Tejo
CW = C + 'Cashew/S0/'
ab('Tejo', 'C', 'Stealth Drone', [
    D(CW + 'Ability_4/Pawn_Cashew_4_Spider_LockOn', 'Drone Lifetime'),
    D(CW + 'Ability_4/GameObject_Cashew_4_SonarPing', 'MaxSonarRadius', role='size', unit='cm'),
    V('range', 'SightRadius', 'cm', CW + 'Ability_4/Pawn_Cashew_4_Spider_LockOn', 'AISenseConfig_Sight_1', 'SightRadius'),
    V('speed', 'MovementTuning.BaseValues.MaxSpeed (inherited)', 'cm_s', BPAWN, 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed', owner=CW + 'Ability_4/Pawn_Cashew_4_Spider_LockOn'),
])
ab('Tejo', 'Q', 'Special Delivery', [
    D(CW + 'Ability_Q/GameObject_Cashew_Q_ShellShockGrenade', 'Explosion Radius', role='size', unit='cm'),
    D(CW + 'Ability_Q/GameObject_Cashew_Q_ShellShockGrenade', 'ConcussDuration', role='other'),
    V('duration', 'ExplosionDelayTimer', 's', CW + 'Ability_Q/GameObject_Cashew_Q_ShellShockGrenade', 'ExplosionDelayTimer_GEN_VARIABLE', 'TimerDuration'),
    V('speed', 'ProjectileSpeed', 'cm_s', CW + 'Ability_Q/Projectile_Cashew_Q_ShellShockGrenade', FSM, 'ProjectileSpeed'),
])
ab('Tejo', 'E', 'Guided Salvo', [
    V('size', 'ExplosionRadius', 'cm', CW + 'Ability_E/AbilityTuning_Cashew_E_Airstrike', 'AbilityTuning_Cashew_E_Airstrike', 'Rows.ExplosionRadius'),
    V('range', 'MapRange', 'cm', CW + 'Ability_E/Ability_Cashew_E_Airstrike', 'MapTargetingState_GEN_VARIABLE', 'MapRange'),
    V('minimap', 'marker minimap Size', 'cm', CW + 'Ability_E/GameObject_Cashew_E_MapMissileMarker', 'AresFastMinimapArea_GEN_VARIABLE', 'Size.X'),
], missing=['missile speed: the missile pawn flies and its flying multiplier is not serialized', 'duration'])
ab('Tejo', 'X', 'Armageddon', [
    D(CW + 'Ability_X/GameObject_Cashew_X_SegmentManager', 'InitialLifeSpan'),
    D(CW + 'Ability_X/GameObject_Cashew_X_SegmentManager', 'InitialVisualsDelay'),
    P('size', 'Volume_EntireAffectedZone half-length', 'cm',
      [(CW + 'Ability_X/GameObject_Cashew_X_SegmentManager', 'Volume_EntireAffectedZone_GEN_VARIABLE', 'BoxExtent.X'),
       (CW + 'Ability_X/GameObject_Cashew_X_SegmentManager', 'Volume_EntireAffectedZone_GEN_VARIABLE', 'RelativeScale3D.X')]),
    V('minimap', 'minimap Size.X', 'cm', CW + 'Ability_X/GameObject_Cashew_X_SegmentManager', 'AresFastMinimapIcon_GEN_VARIABLE', 'Size.X'),
    V('minimap', 'minimap Size.Y', 'cm', CW + 'Ability_X/GameObject_Cashew_X_SegmentManager', 'AresFastMinimapIcon_GEN_VARIABLE', 'Size.Y'),
    V('range', 'MapRange', 'cm', CW + 'Ability_X/Ability_Cashew_X_Airstrike', 'MapTargetingState_GEN_VARIABLE', 'MapRange'),
])

# ---------------------------------------------------------------- Veto
PI = C + 'Pine/S0/'
ab('Veto', 'C', 'Crosscut', [
    V('move', 'RangeCollider radius', 'cm', PI + 'Ability_4/GameObject_Pine_4_UsableTeleport', 'RangeCollider_GEN_VARIABLE', 'SphereRadius'),
    V('range', 'TargetingRange', 'cm', PI + 'Ability_4/Ability_Pine_4_UsableTP', 'PlacementTargetingState_GEN_VARIABLE', 'TargetingRange'),
    V('minimap', 'minimap Size', 'cm', PI + 'Ability_4/GameObject_Pine_4_UsableTeleport', 'AresFastMinimapArea_GEN_VARIABLE', 'Size.X'),
], missing=['duration (the beacon persists; no lifetime field)'])
ab('Veto', 'E', 'Interceptor', [
    V('duration', 'Deployable Lifetime', 's', PI + 'Ability_E/Ability_Pine_E_RadEater', 'Default__Ability_Pine_E_RadEater_C', 'Deployable Lifetime'),
    V('range', 'Projection Range', 'cm', PI + 'Ability_E/Ability_Pine_E_RadEater', 'Default__Ability_Pine_E_RadEater_C', 'Projection Range'),
    V('minimap', 'minimap Size', 'cm', PI + 'Ability_E/Pawn_Pine_E_RadEater', 'AresFastMinimapArea_GEN_VARIABLE', 'Size.X'),
    V('speed', 'ProjectileSpeed', 'cm_s', PI + 'Ability_E/Projectile_Pine_E_RadEaterSpawner', 'Comp_Projectile_FloatCurveMovement_GEN_VARIABLE', 'ProjectileSpeed'),
], missing=['intercept radius (only the minimap area size is read)'])
ab('Veto', 'Q', 'Chokehold', [
    V('size', 'ActivationSphere radius', 'cm', PI + 'Ability_Q/GameObject_Pine_Q_SeizeTrap', 'ActivationSphere_GEN_VARIABLE', 'SphereRadius'),
    D(PI + 'Ability_Q/GameObject_Pine_Q_Tether_SphereExpansion', 'InitialLifeSpan', key='tether InitialLifeSpan'),
    D(PI + 'Ability_Q/GameObject_Pine_Q_SeizeTrap', 'Armed Delay'),
    V('minimap', 'MinimapActivationRange Size', 'cm', PI + 'Ability_Q/GameObject_Pine_Q_SeizeTrap', 'MinimapActivationRange_GEN_VARIABLE', 'Size.X'),
], missing=['trap duration (persists; no lifetime field)'])
ab('Veto', 'X', 'Evolution', [
    V('other', 'HealDelay', 's', PI + 'Ability_X/Ability_Pine_X_SelfBuffVers_Engineering', 'Default__Ability_Pine_X_SelfBuffVers_Engineering_C', 'HealDelay'),
], missing=['duration and geometry: a self buff'])

# ---------------------------------------------------------------- Viper
PD = C + 'Pandemic/S0/'
ab('Viper', 'C', 'Snake Bite', [
    D(PD + 'Ability_Q/Patch_Pandemic_AcidMolotov_NewMolotov', 'FireActiveDuration'),
    D(MOLO, 'ClampedRadius', role='size', unit='cm', owner=PD + 'Ability_Q/Patch_Pandemic_AcidMolotov_NewMolotov', key='ClampedRadius (inherited)'),
    V('speed', 'ProjectileSpeed', 'cm_s', PD + 'Ability_Q/Projectile_Pandemic_Q_AcidGrenade', FSM, 'ProjectileSpeed'),
    V('range', 'MaximumRange', 'cm', PD + 'Ability_Q/Projectile_Pandemic_Q_AcidGrenade', FSM, 'MaximumRange'),
])
ab('Viper', 'Q', 'Poison Cloud', [
    SPH('size', 'SmokeSphere radius', PD + 'Ability_4/GameObject_Pandemic_4_SmokeZone', 'SmokeSphere_GEN_VARIABLE',
        radius_pkg=C + 'Global/Smoke/GameObject_Zone_Smoke_Parent', owner=PD + 'Ability_4/GameObject_Pandemic_4_SmokeZone'),
    D(PD + 'Ability_4/GameObject_Pandemic_4_SmokeZone', 'SmokeExpandTime'),
    D(PD + 'Ability_4/GameObject_Pandemic_4_SmokeZone', 'DelayTime'),
    V('minimap', 'minimap Size', 'cm', PD + 'Ability_4/GameObject_Pandemic_4_SmokeZone', 'BaseMinimapComponent_Parent_GEN_VARIABLE', 'Size.X'),
], missing=['duration: fuel-based toggle', 'throw speed and range'])
ab('Viper', 'E', 'Toxic Screen', [
    D(PD + 'Ability_E/Projectile_Pandemic_E_SmokeScreen_NoCollision', 'Max2D_Distance', role='unconfirmed', unit='cm'),
    D(PD + 'Ability_E/Projectile_Pandemic_E_SmokeScreen_NoCollision', '2D_DistanceBetweenScreenPoints', role='other', unit='cm'),
    V('speed', 'ProjectileSpeed', 'cm_s', PD + 'Ability_E/Projectile_Pandemic_E_SmokeScreen_NoCollision', FSM, 'ProjectileSpeed'),
    D(PD + 'Ability_E/GameObject_Pandemic_E_SmokeScreenManager', 'WallDelay'),
], missing=['duration: fuel-based toggle', 'wall height and thickness'], note=MAX2D_NOTE)
ab('Viper', 'X', "Viper's Pit", [
    D(PD + 'Ability_X/Patch_Pandemic_X_Circular', 'ExpandDuration'),
    D(PD + 'Ability_X/Patch_Pandemic_X_Circular', 'MaxTimeOutOfSmoke'),
    V('range', 'TargetingRange', 'cm', PD + 'Ability_X/Ability_Pandemic_X_SmokeSite_New', 'PlacementTargetingState_Pandemic_X_GEN_VARIABLE', 'TargetingRange'),
], missing=['pit radius: no radius field on the patch or its parents', 'duration: lasts while Viper stays in or near it'])

# ---------------------------------------------------------------- Vyse
NX = C + 'Nox/S0/'
ab('Vyse', 'C', 'Razorvine', [
    D(NX + 'Ability_4/Patch_Nox_BarbedWire', 'FireActiveDuration'),
    D(NX + 'Ability_4/Patch_Nox_BarbedWire', 'ClampedRadius', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed', 'cm_s', NX + 'Ability_4/Projectile_Nox_BarbedWire', FSM, 'ProjectileSpeed'),
    V('range', 'MaximumRange', 'cm', NX + 'Ability_4/Projectile_Nox_BarbedWire', FSM, 'MaximumRange'),
])
ab('Vyse', 'E', 'Arc Rose', [
    V('range', 'TargetingRange', 'cm', NX + 'Ability_E/Ability_Nox_FlashTrap', 'LineTargetingStateBlockOverlappingComponents_GEN_VARIABLE', 'TargetingRange'),
    V('other', 'flash MaxDuration', 's', NX + 'Ability_E/GameObject_Nox_StealthingTrap_Flash_2', 'FlashbangExplosion_GEN_VARIABLE', 'MaxDuration'),
    V('duration', 'BlindWindup', 's', NX + 'Ability_E/GameObject_Nox_StealthingTrap_Flash_2', 'BlindWindup_GEN_VARIABLE', 'TimerDuration'),
], missing=['flash radius', 'device duration (persists; no lifetime field)'])
ab('Vyse', 'Q', 'Shear', [
    D(NX + 'Ability_Q/GameObject_Nox_Wall', 'ActorLifeTime'),
    D(NX + 'Ability_Q/LineTargetingState_NoxWallFirstAnchor', 'MaxWallLength', role='size', unit='cm'),
    V('size', 'DynamicCollisionComp half-extent Y', 'cm', NX + 'Ability_Q/GameObject_Nox_Wall', 'DynamicCollisionComp_GEN_VARIABLE', 'BoxExtent.Y'),
    V('size', 'DynamicCollisionComp half-extent X', 'cm', NX + 'Ability_Q/GameObject_Nox_Wall', 'DynamicCollisionComp_GEN_VARIABLE', 'BoxExtent.X'),
    D(NX + 'Ability_Q/GameObject_Nox_WallTrap', 'ArmingDelay'),
    V('range', 'TargetingRange', 'cm', NX + 'Ability_Q/Ability_Nox_Wall', 'FirstAnchorLineTargetingState_GEN_VARIABLE', 'TargetingRange'),
], missing=['wall height'])
ab('Vyse', 'X', 'Steel Garden', [
    D(NX + 'Ability_X/Gameobject_Nox_DisarmPulse', 'ActualFinalRadius', role='size', unit='cm'),
    D(NX + 'Ability_X/Gameobject_Nox_DisarmPulse', 'Pulse Out Total Time'),
    V('duration', 'EndJamTimer', 's', NX + 'Ability_X/Gameobject_Nox_DisarmPulse', 'EndJamTimer_GEN_VARIABLE', 'TimerDuration'),
    D(NX + 'Ability_X/Gameobject_Nox_DisarmPulse', 'LIfe Time'),
])

# ---------------------------------------------------------------- Waylay
TE = C + 'Terra/S0/'
ab('Waylay', 'C', 'Saturate', [
    D(TE + 'Ability_4/GameObject_Terra_C_TimeSlowGrenade_Explosion', 'InitialLifeSpan'),
    D(TE + 'Ability_4/GameObject_Terra_C_TimeSlowGrenade_Explosion', 'Debuff Radius', role='size', unit='cm'),
    V('speed', 'ProjectileSpeed', 'cm_s', TE + 'Ability_4/Projectile_Terra_C_TimeSlowGrenade', FSM, 'ProjectileSpeed'),
])
ab('Waylay', 'E', 'Refract', [
    V('duration', 'RecordForDurationCanRewindState TimerLength', 's', TE + 'Ability_E/Ability_Terra_E_RewindTime', 'RecordForDurationCanRewindState_GEN_VARIABLE', 'TimerLength'),
], missing=['move: returns the caster to the beacon; no distance field'])
ab('Waylay', 'Q', 'Lightspeed', [
    V('move', 'TargetSpeed (inherited)', 'cm_s', FMD, 'Default__ForceModule_Dash_C', 'SettingsWhileDashing.TargetSpeed_2_27A3F5A944DD74D5A96D52960AB94C13',
      owner=TE + 'Ability_Q/ForceModule_Terra_Q_DoubleDash_Single'),
    V('move', 'BaseSpeed (inherited)', 'cm_s', WSM, DEF(WSM), 'BaseSpeed', owner=TE + 'Ability_Q/ForceModule_Terra_Q_DoubleDash_Single'),
    V('move', 'Duration (inherited)', 's', WSM, DEF(WSM), 'Duration', owner=TE + 'Ability_Q/ForceModule_Terra_Q_DoubleDash_Single'),
    V('other', 'DashCount', 'n', TE + 'Ability_Q/AbilityTuning_Terra_Q_DoubleDash', 'AbilityTuning_Terra_Q_DoubleDash', 'Rows.DashCount'),
], refs=[(WSM, DEF(WSM), 'VelocityCurve', TE + 'Ability_Q/ForceModule_Terra_Q_DoubleDash_Single')],
   note="ForceModule_Dash_WallSlideMitigation, between the dash base and Waylay's module, sets BaseSpeed and a VelocityCurve "
        'made for Terra (cited in the source) beside the TargetSpeed it inherits; which of the three sets the applied '
        'speed is unread, and the dash force modules override GetAppliedForce in script, so the class-default speed '
        'may not be the speed applied')
ab('Waylay', 'X', 'Convergent Paths', [
    D(TE + 'Ability_X/GameObject_Terra_X_DelayedBeam_Beam', 'InitialLifeSpan'),
    D(TE + 'Ability_X/GameObject_Terra_X_DelayedBeam_Beam', 'ActivationDelay'),
    V('size', 'LeftCollider half-extent X', 'cm', TE + 'Ability_X/GameObject_Terra_X_DelayedBeam_Beam', 'LeftCollider_GEN_VARIABLE', 'BoxExtent.X'),
    V('size', 'LeftCollider half-extent Y', 'cm', TE + 'Ability_X/GameObject_Terra_X_DelayedBeam_Beam', 'LeftCollider_GEN_VARIABLE', 'BoxExtent.Y'),
    V('minimap', 'minimap Size.X', 'cm', TE + 'Ability_X/GameObject_Terra_X_DelayedBeam_Beam', 'MinimapComponentLeft_GEN_VARIABLE', 'Size.X'),
])

# ---------------------------------------------------------------- Yoru
ST = C + 'Stealth/S0/'
ab('Yoru', 'C', 'FAKEOUT', [
    D(ST + 'Ability_4/Pawn_Stealth_4_Decoy_V2', 'Duration'),
    V('speed', 'MovementTuning.BaseValues.MaxSpeed', 'cm_s', ST + 'Ability_4/Pawn_Stealth_4_Decoy_V2', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
    V('angle', 'flash MaxAngle', 'deg', ST + 'Ability_4/Pawn_Stealth_4_Decoy_V2', 'ConalFlashbangExplosion_GEN_VARIABLE', 'MaxAngle'),
    V('other', 'flash MaxDuration', 's', ST + 'Ability_4/Pawn_Stealth_4_Decoy_V2', 'ConalFlashbangExplosion_GEN_VARIABLE', 'MaxDuration'),
])
ab('Yoru', 'Q', 'BLINDSIDE', [
    D(ST + 'Ability_Q/Projectile_Stealth_Q_BounceFlash', 'FlashDelay'),
    V('other', 'flash MaxDuration', 's', ST + 'Ability_Q/Projectile_Stealth_Q_BounceFlash', 'FlashbangExplosion_GEN_VARIABLE', 'MaxDuration'),
    V('speed', 'ProjectileSpeed', 'cm_s', ST + 'Ability_Q/Projectile_Stealth_Q_BounceFlash', FSM, 'ProjectileSpeed'),
], missing=['flash radius'])
ab('Yoru', 'E', 'GATECRASH', [
    D(ST + 'Ability_E/Pawn_Stealth_E_TeleporterMoving', 'Duration'),
    D(ST + 'Ability_E/Pawn_Stealth_E_TeleporterMoving', 'Max Travel Distance', role='range', unit='cm'),
    V('speed', 'tether MaxSpeed (inherited)', 'cm_s', BAI, 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed', owner=ST + 'Ability_E/Pawn_Stealth_E_TeleporterMoving'),
    V('speed', 'fake tether MaxSpeed', 'cm_s', ST + 'Ability_E/Pawn_Stealth_E_TeleporterMoving_FakeTP', 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed'),
    V('range', 'stationary TargetingRange', 'cm', ST + 'Ability_E/Ability_Stealth_E_Teleport', 'UpdatedPlacementTargetingState_GEN_VARIABLE', 'TargetingRange'),
], note='the caster teleports to the tether, so the move distance is wherever the tether is; the tether speed is the AI pawn base value before any movement-state multiplier')
ab('Yoru', 'X', 'DIMENSIONAL DRIFT', [
    V('duration', 'CloakBuff TimerLength', 's', ST + 'Ability_X/Ability_Stealth_X_Cloak_Equip', 'CloakState_CloakBuff_GEN_VARIABLE', 'TimerLength'),
], missing=['geometry: a self state'])


# ---------------------------------------------------------------- evaluation

UNIT = {'cm': ('_m', 0.01), 'cm_s': ('_m_s', 0.01), 's': ('_s', 1), 'deg': ('_deg', 1), 'n': ('_n', 1), 'raw': ('_raw', 1)}


def slug(label):
    s = re.sub(r'\(.*?\)', '', label).replace('2D', '2d')
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_').lower()
    s = re.sub(r'_+', '_', s)
    return s


def evaluate(spec=SPEC):
    out, errors = [], []
    for a in spec:
        rows = []
        for v in a['values']:
            try:
                raws = [read(p, e, f, owner=v['owner']) for (p, e, f) in v['parts']]
            except Exception as ex:
                errors.append(f"{a['agent']} {a['slot']} {a['ability']} :: {v['key']} :: {ex!r}")
                continue
            raw = 1.0
            for r in raws:
                raw *= r
            suf, k = UNIT[v['unit']]
            val = raw * k
            val = float(f'{val:.6g}') if isinstance(val, float) else val
            if v['unit'] == 'n':
                val = int(raw)
            rows.append(dict(v, raws=raws, raw=raw, value=val, tkey=slug(v['key']) + suf))
        out.append(dict(a, rows=rows))
    return out, errors


# ---------------------------------------------------------------- the facts

LIFE = re.compile(r'^(smoke_duration|dissipate_smoke_duration|post_death_smoke_duration|wall_duration|fire_active_duration|'
                  r'slow_field_fire_active_duration|life_duration|segment_life_duration|zone_lifetime|stim_beacon_duration|'
                  r'duration|initial_life_span|shockwave_initial_life_span|tether_initial_life_span|orb_initial_life_span|'
                  r'life_time|actor_life_time|drone_lifetime|deployable_lifetime|maixmum_lifetime|sustain_time|up_duration|'
                  r'buff_duration|possess_duration_timer_length|drone_duration_timer_length|follow_duration|'
                  r'cloak_buff_timer_length|prevent_death_state_timer_length|end_jam_timer|laser_active_timed_state_timer_length|'
                  r'buff_active_timer_length|total_ability_time|spline_duration|wall_linger_state_countdown_time|end_delay|'
                  r'duel_timeout_duration|record_for_duration_can_rewind_state_timer_length|soul_orb_orb_lifetime_duration|'
                  r'wait_for_downed_timer_length|seek_timeout|thump_duration|flash_max_duration|lifetime_duration|'
                  r'invis_and_invuln_buff_timer_length|stim_beacon_duration)_s$')

ROLE_WORDS = [('life', 'lifetime or active duration'), ('timing', 'other timings'), ('size', 'sizes'),
              ('angle', 'angles'), ('range', 'placement, throw or targeting range'),
              ('unconfirmed', 'a length the files do not settle as size or range'), ('speed', 'speeds'), ('move', 'caster movement'),
              ('minimap', 'minimap component size, in world units'), ('other', 'other values')]
UNIT_WORD = {'_m': 'm', '_m_s': 'm/s', '_s': 's', '_deg': 'degrees', '_n': '', '_raw': '(force units)'}


def agent_slug(a):
    return re.sub(r'[^a-z0-9]+', '', a.lower())


def ability_slug(a):
    s = a.lower().replace("'", '')
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def fmt(v):
    if isinstance(v, int):
        return str(v)
    s = f'{v:.6g}'
    return s if ('.' in s or 'e' in s) else s + '.0'


def unit_of(tkey):
    for suf in ('_m_s', '_m', '_s', '_deg', '_n', '_raw'):
        if tkey.endswith(suf):
            return suf
    return ''


def words(tkey, v):
    suf = unit_of(tkey)
    name = tkey[: -len(suf)].replace('_', ' ') if suf else tkey
    u = UNIT_WORD[suf]
    return f'{name} {fmt(v)}{(" " + u) if u else ""}'


def wrap(text, width=78):
    return '\n'.join(textwrap.wrap(' '.join(text.split()), width, break_long_words=False, break_on_hyphens=False))


def tq(text):
    return '"""\n' + wrap(text) + '\n"""'


def raw_cite(r):
    """One value as stored. A product cites each factor with its own unit: a
    RelativeScale3D or state-multiplier factor is unitless, never a length or
    a speed."""
    unit = {'cm': 'cm', 'cm_s': 'cm/s', 's': 's', 'deg': 'deg', 'n': '', 'raw': ''}[r['unit']]
    parts = []
    for (pkg, exp, field), raw in zip(r['parts'], r['raws']):
        text = f'{asset_path(pkg)} {exp}.{field} = {fmt(raw) if isinstance(raw, float) else raw}'
        if len(r['parts']) > 1:
            if 'RelativeScale3D' in field:
                text += ' (unitless scale)'
            elif 'Multipliers' in field:
                text += ' (unitless multiplier)'
            elif unit:
                text += ' ' + unit
        parts.append(text)
    joined = ' x '.join(parts)
    if len(r['parts']) == 1 and unit:
        joined += ' ' + unit
    inh = f' (inherited by {r["owner"].rsplit("/", 1)[1]}, no class between overrides it)' if r.get('owner') else ''
    return f'{r["tkey"]}: {joined}{inh}'


def ref_cites(a):
    out = []
    for pkg, exp, field, owner in a.get('refs') or ():
        target = read_ref(pkg, exp, field, owner=owner)
        inh = f' (inherited by {owner.rsplit("/", 1)[1]}, no class between overrides it)' if owner else ''
        out.append(f'{asset_path(pkg)} {exp}.{field} names {target.rsplit("/", 1)[1]}{inh}')
    return ('. Object references: ' + '; '.join(out)) if out else ''


def values_table(rows):
    groups = {}
    for r in rows:
        role = r['role']
        if role == 'duration':
            role = 'life' if LIFE.match(r['tkey']) else 'timing'
        r['group'] = role
        groups.setdefault(role, {})
        k = r['tkey']
        n = 2
        while k in groups[role]:
            k = f"{r['tkey']}_{n}"
            n += 1
        groups[role][k] = r['value']
    order = [w for w, _ in ROLE_WORDS]
    inner = []
    for g in order:
        if g in groups:
            inner.append(f'{g} = {{ ' + ', '.join(f'{k} = {fmt(v)}' for k, v in groups[g].items()) + ' }')
    return '{ ' + ', '.join(inner) + ' }', groups


def ability_fact(a):
    fid = f"{agent_slug(a['agent'])}-{ability_slug(a['ability'])}-game-data"
    vt, groups = values_table(a['rows'])
    name = ' '.join(a['ability'].split())
    if a['rows']:
        bits = []
        for g, label in ROLE_WORDS:
            rs = [r for r in a['rows'] if r['group'] == g]
            if rs:
                bits.append(f'{label}: ' + ', '.join(words(r['tkey'], r['value']) for r in rs))
        claim = (f"The game files of build 13.06 give {a['agent']}'s {name} (slot {a['slot']}) these class-default values, "
                 f"converted from centimetres [domain:game_data/game-units-centimetres]: " + '; '.join(bits) + '.')
    else:
        claim = (f"The game files of build 13.06 hold no duration, size, range or speed value for {a['agent']}'s "
                 f"{name} (slot {a['slot']}).")
    src = (f"game-extract exports of {BUILD_ID} under the store's {STORE_REL}/ (sets ability-states, ability-data and "
           f"game-data, each with its manifest and provenance); the ability's equippable and entities from "
           f"ability-states-gamedata-0.2.0 and its ability folder. Each value, as stored: " +
           '; '.join(raw_cite(r) for r in a['rows']) + ref_cites(a)) if a['rows'] else (
           f"game-extract exports of {BUILD_ID} under the store's {STORE_REL}/; the ability's equippable, entities and "
           f"folder were searched")
    exc = []
    if a['missing']:
        exc.append('Not found in the equippable, its entities, their parent classes or the ability folder: '
                   + '; '.join(a['missing']) + '.')
    if a['note']:
        exc.append(a['note'][0].upper() + a['note'][1:] + '.')
    if a.get('extra'):
        exc.append(a['extra'](a['rows']))
    exc.append('These are class defaults; a blueprint may change a value at run time, and a field name '
               'is the designers\' word, not a measured meaning.')
    lines = [f'[{fid}]', f'claim = {tq(claim)}', 'kind = "measurement"', 'known = "measured"', f'since = "{SINCE}"',
             f'subject = "{agent_slug(a["agent"]) if a["agent"] != "KAY/O" else "kay/o"}:{name.lower()}"',
             f'source = {tq(src)}',
             'use = """\nthe world shape, life and motion of this ability\'s child in the entity-state design: read\n'
             'each value through its own key, never by analogy with another ability\n"""',
             f'exceptions = {tq(" ".join(exc))}']
    if a['rows']:
        lines.append(f'values = {vt}')
    if a.get('supersedes'):
        lines.append(f"supersedes = {tq(a['supersedes'])}")
    see = ['abilities/ability-rules-are-unique', 'game_data/game-units-centimetres'] + list(a.get('see') or ())
    lines.append('see = [' + ', '.join(f'"{s}"' for s in see) + ']')
    return fid, '\n'.join(lines) + '\n', groups


def native_parent(pkg):
    """The native class a blueprint class derives from directly, or None."""
    _, d = load(pkg)
    for e in d:
        if e.get('Type') == 'BlueprintGeneratedClass':
            sp = (e.get('SuperStruct') or e.get('Super') or {}).get('ObjectPath', '')
            if sp.startswith('/Script/'):
                return sp + '.' + (e.get('SuperStruct') or e.get('Super'))['ObjectName'].split("'")[1]
    return None


#: Engine floor fields a character's movement component may serialize; the
#: player's class chain serializes none of them (checked on regeneration).
FLOOR_FIELDS = ('WalkableFloorAngle', 'WalkableFloorZ', 'MaxStepHeight', 'PerchRadiusThreshold')


INI_REL = 'config/ShooterGame/Config/DefaultEngine.ini'


def ini_value(rel, section, key):
    """One `key=value` of an exported engine config's `[section]`, as a float."""
    head = None
    with open(f'{BUILD}/{rel}', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            t = line.strip()
            if t.startswith('[') and t.endswith(']'):
                head = t[1:-1]
            elif head == section and t.split('=', 1)[0] == key:
                return float(t.split('=', 1)[1])
    raise KeyError(f'{rel} [{section}] {key}')


def jump_fact(BP, BPC):
    """The player character's jump tuning, read from BasePawn's movement
    component and inherited unchanged by BasePlayerCharacter, beside the
    world gravity of the engine config."""
    f = {k: read(BP, 'CharMoveComp', k, owner=BPC) for k in
         ('DefaultJumpTuning.MaxJumpHeight', 'DefaultJumpTuning.JumpTotalTime', 'JumpZVelocity', 'GravityScale',
          'AirControl')}
    for k in FLOOR_FIELDS:
        assert not has_field(BP, 'CharMoveComp', k) and not has_field(BPC, 'CharMoveComp', k), k
    native = native_parent(BP)
    assert native, BP
    h, t, vz, gs = (f['DefaultJumpTuning.MaxJumpHeight'], f['DefaultJumpTuning.JumpTotalTime'],
                    f['JumpZVelocity'], f['GravityScale'])
    gz = ini_value(INI_REL, '/Script/Engine.PhysicsSettings', 'DefaultGravityZ')
    g = -gz * gs                    # the character's gravity, cm/s^2
    rise, flight = vz * vz / (2 * g), 2 * vz / g
    claim = (f"A player character's jump tuning sets a maximum jump height of {fmt(h / 100)} m "
             f"(DefaultJumpTuning.MaxJumpHeight) and a total jump time of {fmt(t)} s; the engine fields beside it "
             f"give a jump launch speed of {fmt(vz / 100)} m/s (JumpZVelocity), a gravity scale of {fmt(gs)} and an "
             f"air control of {fmt(f['AirControl'])}. World gravity is {fmt(gz / 100)} m/s^2 "
             f"(DefaultGravityZ). The class chain serializes no walkable floor angle, walkable "
             f"floor Z or movement step height (MaxStepHeight): those are the native class's defaults, unread; "
             f"the navigation agent's step is a separate field [domain:game_data/character-eye-height].")
    src = (f"{BUILD_ID}, set ability-states: {asset_path(BP)} CharMoveComp.DefaultJumpTuning.MaxJumpHeight = "
           f"{fmt(h)} cm, .DefaultJumpTuning.JumpTotalTime = {fmt(t)} s, .JumpZVelocity = {fmt(vz)} cm/s, "
           f".GravityScale = {fmt(gs)}, .AirControl = {fmt(f['AirControl'])}; inherited unchanged by "
           f"{asset_path(BPC)}, the parent of every agent's <Codename>_PC (its CharMoveComp overrides only "
           f"JumpOffJumpZFactor, MovementTuning, JumpLandSlowTuningV2 and NavAgentProps). Neither CharMoveComp "
           f"serializes {', '.join(FLOOR_FIELDS)}; BasePawn_C derives from the native class {native}, whose "
           f"defaults no export carries. World gravity: {STORE_REL}/{INI_REL} "
           f"[/Script/Engine.PhysicsSettings] DefaultGravityZ = {fmt(gz)} cm/s^2, exported raw by "
           f"game-extract export (config/manifest.jsonl).")
    exc = (f"Which jump the native movement code runs is unread. The following arithmetic is ours, not a "
           f"field: a ballistic launch at JumpZVelocity under GravityScale times world gravity "
           f"({fmt(round(g, 3) / 100)} m/s^2) rises {fmt(round(rise) / 100)} m and lasts "
           f"{fmt(round(flight, 3))} s, which agrees with JumpTotalTime ({fmt(t)} s); MaxJumpHeight "
           f"({fmt(h / 100)} m) sits {fmt(round(rise - h) / 100)} m under that rise, and which of the two "
           f"limits a jump is native code. Crouching in the air is native code; what it adds to a reachable "
           f"ledge is not included. The walkable floor angle for sightline floors stays the engine default, a "
           f"placeholder.")
    return '\n'.join([
        '[character-jump]', f'claim = {tq(claim)}', 'kind = "measurement"', 'known = "measured"',
        f'since = "{SINCE}"', 'subject = "movement:jump"', f'source = {tq(src)}',
        'use = """\nsightline walk graph: neighbouring floors join when their heights differ by at most the '
        'maximum jump height\n"""',
        f'exceptions = {tq(exc)}',
        f"values = {{ jump = {{ max_jump_height_m = {fmt(h / 100)}, jump_total_time_s = {fmt(t)}, "
        f"jump_z_velocity_m_s = {fmt(vz / 100)} }}, scale = {{ gravity_scale = {fmt(gs)}, "
        f"air_control = {fmt(f['AirControl'])} }}, world = {{ default_gravity_z_m_s2 = {fmt(gz / 100)} }} }}",
        'see = ["game_data/game-units-centimetres", "game_data/character-eye-height"]']) + '\n'


def movement_facts():
    BPC = '/Game/Characters/_Core/BasePlayerCharacter'
    BP = '/Game/Characters/_Core/BasePawn'
    base = read(BPC, 'CharMoveComp', 'MovementTuning.BaseValues.MaxSpeed')
    walk = read(BPC, 'CharMoveComp', 'MovementTuning.DefaultStateMultipliers.MaxSpeed')
    jump = read(BPC, 'CharMoveComp', 'MovementTuning.DefaultStateMultipliers[2].MaxSpeed')
    crouch = read(BPC, 'CharMoveComp', 'MovementTuning.DefaultStateMultipliers[3].MaxSpeed')
    asc = read(BP, 'CharMoveComp', 'MovementTuning.DefaultStateMultipliers[4].MaxSpeed', owner=BPC)
    assert not has_field(BPC, 'CharMoveComp', 'MovementTuning.DefaultStateMultipliers[1].MaxSpeed')
    assert not has_field(BP, 'CharMoveComp', 'MovementTuning.DefaultStateMultipliers[1].MaxSpeed')
    out = []
    claim = (f"A player character's movement tuning sets a base top speed of {fmt(base / 100)} m/s "
             f"({fmt(base)} cm/s) and a top-speed multiplier per movement state, indexed by EAresMovementType "
             f"(0 Walking, 1 Running, 2 Jumping, 3 Crouching, 4 OnAscender, 5 Flying): walking {fmt(walk)}, "
             f"jumping {fmt(jump)}, crouching {fmt(crouch)}, on a rope {fmt(asc)}. The running multiplier is not "
             f"serialized in any class of the chain, so it is the native default, unread here. With a running "
             f"multiplier of 1 the top run speed is {fmt(base / 100)} m/s; walking is then {fmt(base * walk / 100)} m/s "
             f"and crouching {fmt(base * crouch / 100)} m/s, products of the fields. A held weapon scales the run "
             f"speed [domain:game_data/weapon-run-speed-multipliers].")
    src = (f"{BUILD_ID}, set ability-states: {asset_path(BPC)} CharMoveComp.MovementTuning.BaseValues.MaxSpeed = {fmt(base)} cm/s, "
           f".DefaultStateMultipliers.MaxSpeed = {fmt(walk)} (index 0), .DefaultStateMultipliers[2].MaxSpeed = {fmt(jump)}, "
           f".DefaultStateMultipliers[3].MaxSpeed = {fmt(crouch)}; {asset_path(BP)} CharMoveComp.MovementTuning."
           f"DefaultStateMultipliers[4].MaxSpeed = {fmt(asc)}, inherited by BasePlayerCharacter, the parent class of every "
           f"agent's <Codename>_PC. The index meaning is the usmap enum EAresMovementType of VALORANT_13.06_zs.usmap; the "
           f"weapons' MovementCurves (index 0 Walking, 1 Running, 3 Crouching, 4 Ascenders curve names) agree with it.")
    exc = ("The array index is matched to EAresMovementType by its length and the curve names, not by a declaration "
           "the export carries. The engine field CharMoveComp.MaxWalkSpeed is 560 or 590 cm/s per agent "
           "(Breach_PC 560, Rift_PC 590, ...); the movement tuning governs Valorant's own movement, and which field "
           "the native code reads is unread. Clove's Smonk_PC sets multiplier [5] (Flying) to 3.0. Abilities that "
           "change speed (Stim Beacon, High Gear, Dismiss, ...) are not included.")
    out.append(('character-movement-speeds', '\n'.join([
        '[character-movement-speeds]', f'claim = {tq(claim)}', 'kind = "measurement"', 'known = "measured"',
        f'since = "{SINCE}"', 'subject = "movement:speed"', f'source = {tq(src)}',
        'use = """\nthe reach region\'s growth rate: the top run speed times the held weapon\'s multiplier\n"""',
        f'exceptions = {tq(exc)}',
        f'values = {{ speed = {{ base_max_speed_m_s = {fmt(base / 100)} }}, state_multiplier = {{ walking = {fmt(walk)}, '
        f'jumping = {fmt(jump)}, crouching = {fmt(crouch)}, on_ascender = {fmt(asc)} }} }}',
        'see = ["game_data/game-units-centimetres", "game_data/weapon-run-speed-multipliers"]']) + '\n'))
    # weapons
    W = '/Game/Equippables/Guns/'
    weapons = [('odin', 'HvyMachineGuns/HMG/HeavyMachineGunUIData'), ('ares', 'HvyMachineGuns/LMG/LightMachineGunUIData'),
               ('vandal', 'Rifles/AK/AssaultRifle_AKUIData'), ('warden', 'Rifles/BattleRifle/BattleRifle_UIData'),
               ('bulldog', 'Rifles/Burst/AssaultRifle_BurstUIData'), ('phantom', 'Rifles/Carbine/AssaultRifle_ACRUIData'),
               ('judge', 'Shotguns/AutoShotgun/AutomaticShotgunUIData'), ('bucky', 'Shotguns/PumpShotgun/PumpShotgunUIData'),
               ('frenzy', 'Sidearms/AutoPistol/AutomaticPistolUIData'), ('classic', 'Sidearms/BasePistol/BasePistolUIData'),
               ('bandit', 'Sidearms/Compact/Compact_UIData'), ('ghost', 'Sidearms/Luger/LugerPistolUIData'),
               ('sheriff', 'Sidearms/Revolver/RevolverPistolUIData'), ('shorty', 'Sidearms/Slim/SawedOffShotgunUIData'),
               ('operator', 'SniperRifles/Boltsniper/BoltSniperUIData'), ('guardian', 'SniperRifles/DMR/DMRUIData'),
               ('outlaw', 'SniperRifles/Doublesniper/DS_Gun_UIData'), ('marshal', 'SniperRifles/Leversniper/LeverSniperRifleUIData'),
               ('spectre', 'SubMachineGuns/MP5/SubMachineGun_MP5UIData'), ('stinger', 'SubMachineGuns/Vector/VectorUIData')]
    run, ads, cites = {}, {}, []
    for name, rel in weapons:
        pkg = W + rel
        exp = 'Default__' + rel.rsplit('/', 1)[1] + '_C'
        run[name] = read(pkg, exp, 'WeaponStats.RunSpeedMultiplier')
        try:
            ads[name] = read(pkg, exp, 'WeaponStats.ADSStats.RunSpeedMultiplier')
        except KeyError:
            pass
        cites.append(f'{name} {asset_path(pkg)} {exp}.WeaponStats.RunSpeedMultiplier = {fmt(run[name])}'
                     + (f', .ADSStats.RunSpeedMultiplier = {fmt(ads[name])}' if name in ads else ''))
    groups = {}
    for n, v in run.items():
        groups.setdefault(v, []).append(n)
    claim = ('Each gun\'s stat block gives a run-speed multiplier: ' + '; '.join(
        f'{fmt(v)} for ' + ', '.join(ns) for v, ns in sorted(groups.items(), reverse=True)) +
        '. The guns with an aimed-down-sights stat block carry a second multiplier there: ' +
        ', '.join(f'{n} {fmt(v)}' for n, v in ads.items()) + '. The knife\'s stat block has no multiplier.')
    src = (f'{BUILD_ID}, set weapon-data, each gun\'s UIData class default: ' + '; '.join(cites))
    exc = ('These are the UIData stat blocks, the numbers the game\'s shop and collection screens show; the gun '
           'blueprints serialize no speed field, so the native code that applies the multiplier is unread. Whether '
           'the knife\'s speed is the base run speed is not stated by a field.')
    out.append(('weapon-run-speed-multipliers', '\n'.join([
        '[weapon-run-speed-multipliers]', f'claim = {tq(claim)}', 'kind = "measurement"', 'known = "measured"',
        f'since = "{SINCE}"', 'subject = "weapons:run speed"', f'source = {tq(src)}',
        'use = """\nscale the top run speed by the held gun\'s multiplier where the held gun is known\n"""',
        f'exceptions = {tq(exc)}',
        'values = { run = { ' + ', '.join(f'{n} = {fmt(v)}' for n, v in run.items()) + ' }, ads_run = { '
        + ', '.join(f'{n} = {fmt(v)}' for n, v in ads.items()) + ' } }',
        'see = ["game_data/character-movement-speeds", "weapons/per-weapon-properties"]']) + '\n'))
    # eye heights and body
    vals = dict(base_eye=read(BP, 'Default__BasePawn_C', 'BaseEyeHeight'),
                crouched_eye=read(BP, 'Default__BasePawn_C', 'CrouchedEyeHeight'),
                standing_eye_offset=read(BP, 'Default__BasePawn_C', 'StandingEyeOffset'),
                crouching_eye_offset=read(BP, 'Default__BasePawn_C', 'CrouchingEyeOffset'),
                crouch_compression=read(BP, 'Default__BasePawn_C', 'CrouchCompressionAmount'),
                crouch_time=read(BP, 'Default__BasePawn_C', 'CrouchTimeSeconds'),
                capsule_half=read(BP, 'CollisionCylinder', 'CapsuleHalfHeight'),
                capsule_r=read(BP, 'CollisionCylinder', 'CapsuleRadius'),
                crouched_half=read(BP, 'CharMoveComp', 'CrouchedHalfHeight'),
                nav_h=read(BPC, 'CharMoveComp', 'NavAgentProps.AgentHeight'),
                nav_r=read(BPC, 'CharMoveComp', 'NavAgentProps.AgentRadius'),
                step=read(BPC, 'CharMoveComp', 'NavAgentProps.AgentStepHeight'))
    for k in ('BaseEyeHeight', 'CrouchedEyeHeight'):
        assert not has_field(BPC, 'Default__BasePlayerCharacter_C', k)
    assert not has_field(BPC, 'CollisionCylinder', 'CapsuleHalfHeight')
    v = vals
    claim = (f"A player character's base class sets the eye {fmt(v['base_eye'] / 100)} m above the capsule centre standing "
             f"(BaseEyeHeight) and {fmt(v['crouched_eye'] / 100)} m crouched (CrouchedEyeHeight); the capsule is "
             f"{fmt(v['capsule_r'] / 100)} m in radius with a half-height of {fmt(v['capsule_half'] / 100)} m, "
             f"{fmt(v['crouched_half'] / 100)} m crouched (CrouchedHalfHeight); the navigation agent is "
             f"{fmt(v['nav_h'] / 100)} m tall, {fmt(v['nav_r'] / 100)} m in radius, with a {fmt(v['step'] / 100)} m step. "
             f"Valorant's own fields add an eye offset of {fmt(v['standing_eye_offset'])} cm standing and "
             f"{fmt(v['crouching_eye_offset'])} cm crouched, a crouch compression of {fmt(v['crouch_compression'])} cm "
             f"and a {fmt(v['crouch_time'])} s crouch. Under the engine's convention (eye height above the centre of a "
             f"capsule standing on the floor) the standing eye is {fmt((v['capsule_half'] + v['base_eye']) / 100)} m above "
             f"the floor; the crouched eye is not derivable, since the native crouch code that applies the "
             f"compression and offsets is unread.")
    src = (f"{BUILD_ID}, set ability-states: {asset_path(BP)} Default__BasePawn_C.BaseEyeHeight = {fmt(v['base_eye'])}, "
           f".CrouchedEyeHeight = {fmt(v['crouched_eye'])}, .StandingEyeOffset = {fmt(v['standing_eye_offset'])}, "
           f".CrouchingEyeOffset = {fmt(v['crouching_eye_offset'])}, .CrouchCompressionAmount = {fmt(v['crouch_compression'])}, "
           f".CrouchTimeSeconds = {fmt(v['crouch_time'])}; CollisionCylinder.CapsuleHalfHeight = {fmt(v['capsule_half'])}, "
           f".CapsuleRadius = {fmt(v['capsule_r'])}; CharMoveComp.CrouchedHalfHeight = {fmt(v['crouched_half'])}; "
           f"{asset_path(BPC)} CharMoveComp.NavAgentProps.AgentHeight = {fmt(v['nav_h'])}, .AgentRadius = {fmt(v['nav_r'])}, "
           f".AgentStepHeight = {fmt(v['step'])} (all cm). BasePlayerCharacter, the parent of every agent's <Codename>_PC, "
           f"inherits BasePawn's eye and capsule fields without overriding them; a game-wide name search (game-extract "
           f"whorefs) finds BaseEyeHeight serialized in no other player-character package.")
    exc = (f"The standing eye height of {fmt((v['capsule_half'] + v['base_eye']) / 100)} m is the engine convention's sum, "
           f"not a field, and ignores StandingEyeOffset, whose use is unread; with the offset it would be "
           f"{fmt((v['capsule_half'] + v['base_eye'] + v['standing_eye_offset']) / 100)} m. A crouched eye height for "
           f"sightlines needs the native crouch code or a measurement (the replay's camera, or a capture).")
    out.append(('character-eye-height', '\n'.join([
        '[character-eye-height]', f'claim = {tq(claim)}', 'kind = "measurement"', 'known = "measured"',
        f'since = "{SINCE}"', 'subject = "movement:body"', f'source = {tq(src)}',
        'use = """\nsightline eye height: the standing value under the stated convention; no crouched value. '
        'Crouch room above a floor: the crouched capsule, twice CrouchedHalfHeight\n"""',
        f'exceptions = {tq(exc)}',
        f"values = {{ eye = {{ base_eye_height_m = {fmt(v['base_eye'] / 100)}, crouched_eye_height_m = {fmt(v['crouched_eye'] / 100)}, "
        f"standing_eye_offset_m = {fmt(v['standing_eye_offset'] / 100)}, crouching_eye_offset_m = {fmt(v['crouching_eye_offset'] / 100)} }}, "
        f"capsule = {{ radius_m = {fmt(v['capsule_r'] / 100)}, half_height_m = {fmt(v['capsule_half'] / 100)}, "
        f"crouched_half_height_m = {fmt(v['crouched_half'] / 100)}, crouch_compression_m = {fmt(v['crouch_compression'] / 100)} }}, "
        f"nav_agent = {{ height_m = {fmt(v['nav_h'] / 100)}, radius_m = {fmt(v['nav_r'] / 100)}, step_height_m = {fmt(v['step'] / 100)} }} }}",
        'see = ["game_data/game-units-centimetres"]']) + '\n'))
    out.append(('character-jump', jump_fact(BP, BPC)))
    unit = '\n'.join([
        '[game-units-centimetres]',
        f'claim = {tq("The game files measure lengths in Unreal units, one centimetre each, and speeds in centimetres per second. A player capsule 1.96 m tall and a 6.75 m/s run fit that unit [domain:game_data/character-eye-height] [domain:game_data/character-movement-speeds].")}',
        'kind = "rule"', 'known = "cited"', f'since = "{SINCE}"', 'subject = "game files:units"',
        f'source = {tq("Unreal Engine documentation: one Unreal unit is one centimetre by default; VALORANT is built on Unreal Engine (the export JSON carries engine class names such as CharacterMovementComponent fields and UScriptClass). No VALORANT file states the unit.")}',
        'use = "divide a game-file length by 100 for metres"',
        'see = ["game_data/character-eye-height", "game_data/character-movement-speeds"]']) + '\n'
    out.insert(0, ('game-units-centimetres', unit))
    return out




# ---------------------------------------------------------------- the file and the sheet

HEADER = ('# Values read from the extracted game files of build 13.06\n'
          f'# ({BUILD_ID}), one table per ability or movement fact.\n'
          '# Each value cites its asset, export and field; lengths are converted from\n'
          '# centimetres. Schema and the citation form: reticle/domain.py.\n'
          '# Regenerate with prototypes/game_data_facts.py; never edit by hand.\n')


# ---------------------------------------------------------------- restock times
# Each ability's cooldown component, as (agent, catalogue name, package, component
# export, tuning row or None, field). A component may name an AbilityTuning row
# (CooldownDurationTuningTag); the row's value then is the files' value. A
# component may also carry DPT_Cooldown, the cooldown while its DPT_FeatureToggle
# is on; the toggle's state is a server setting the files do not carry.
CCD = C + 'Components/Comp_Ability_CooldownComponent'
CDC = 'Comp_Ability_CooldownComponent_GEN_VARIABLE'
RESTOCK = [
    ('Astra', 'Gravity Well', C + 'Rift/S0/Ability_4/BlackHole/Ability_Rift_4_BlackHole', CDC, None, 'CooldownSeconds'),
    ('Astra', 'Nova Pulse', C + 'Rift/S0/Ability_Q/Ability_Rift_Q_FlashBurst', CDC, None, 'CooldownSeconds'),
    ('Astra', 'Nebula / Dissipate', C + 'Rift/S0/Ability_E/Ability_Rift_E_TransformRift_Smoke', CDC, None, 'CooldownSeconds'),
    ('Breach', 'Fault Line', C + 'Breach/S0/Ability_E/Ability_Breach_E_Fissure', CDC, None, 'CooldownSeconds'),
    ('Chamber', 'Rendezvous', C + 'Deadeye/S0/Ability_E/Ability_Deadeye_E_Teleporter_Tethers', CDC,
     (C + 'Deadeye/S0/Ability_E/AbilityTuning_Deadeye_E_Teleport_Tether', 'AbilityTuning_Deadeye_E_Teleport_Tether',
      'Rows.TeleportCooldown'), 'CooldownSeconds'),
    ('Clove', 'Ruse', C + 'Smonk/S0/Ability_E/MapTargetSmoke/Ability_Smonk_E_MapTargetSmokeV2', CDC, None, 'CooldownSeconds'),
    ('Cypher', 'Spycam', C + 'Gumshoe/S0/Ability_E/Ability_Gumshoe_E_Camera', CDC, None, 'CooldownSeconds'),
    ('Deadlock', 'GravNet', C + 'Cable/S0/Ability_4/Ability_Cable_4_NetToss', CDC,
     (C + 'Cable/S0/Ability_4/AbilityTuning_Cable_4_NetToss', 'AbilityTuning_Cable_4_NetToss', 'Rows.Cooldown'), None),
    ('Fade', 'Haunt', C + 'BountyHunter/S0/Ability_E/Ability_E_BountyHunter_ReconDivebomb', CDC,
     (C + 'BountyHunter/S0/Ability_E/AbilityTuning_BountyHunter_E_ReconDiveBomb', 'AbilityTuning_BountyHunter_E_ReconDiveBomb',
      'Rows.Cooldown'), 'CooldownSeconds'),
    ('Gekko', 'Mosh Pit', C + 'AggroBot/S0/Ability_4/Ability_Aggrobot_C_ExplodeyPatch', CDC, None, 'CooldownSeconds'),
    ('Gekko', 'Wingman', C + 'AggroBot/S0/Ability_Q/Ability_Q_Aggrobot_SeekerNade', CDC, None, 'CooldownSeconds'),
    ('Gekko', 'Dizzy', C + 'AggroBot/S0/Ability_E/Ability_E_Aggrobot_DiscTurret', CDC,
     (C + 'AggroBot/S0/Ability_E/AbilityTuning_Aggrobot_E', 'AbilityTuning_Aggrobot_E', 'Rows.DizzyCooldown'), None),
    ('Gekko', 'Thrash', C + 'AggroBot/S0/Ability_X/Ability_Aggrobot_X_RollyExplosion', 'Comp_Aggrobot_X_Cooldown_GEN_VARIABLE',
     None, 'CooldownInSeconds'),
    ('Harbor', 'Cove', C + 'Mage/S0/Ability_E/Ability_Mage_E_WorldSmoke', CDC, None, 'CooldownSeconds'),
    ('KAY/O', 'ZERO/point', C + 'Grenadier/S0/Ability_E/Ability_E_Grenadier_EMPKnife', CDC, None, 'CooldownSeconds'),
    ('Miks', 'Waveform', C + 'Iris/S0/Ability_E/Ability_Iris_E_MT_Smoke_Production', CDC, None, 'CooldownSeconds'),
    ('Omen', 'Dark Cover', C + 'Wraith/S0/Ability_4/Ability_Wraith_4_Smoke', CDC, None, 'CooldownSeconds'),
    ('Sage', 'Healing Orb', C + 'Thorne/S0/Ability_Q/Ability_Thorne_Q_Heal_Production_New', CDC, None, 'CooldownSeconds'),
    ('Skye', 'Guiding Light', C + 'Guide/S0/Ability_E/Ability_Guide_E_HawkFlash', CDC, None, 'CooldownSeconds'),
    ('Sova', 'Recon Bolt', C + 'Hunter/S0/Ability_Q/Ability_Hunter_Q_RevealBolt_Signature', 'Comp_Ability_CooldownComponent1_GEN_VARIABLE',
     (C + 'Hunter/S0/Ability_Q/AbilityTuning_Hunter_Q_RevealBolt', 'AbilityTuning_Hunter_Q_RevealBolt', 'Rows.RevealBoltCooldown'),
     'CooldownSeconds'),
    ('Vyse', 'Arc Rose', C + 'Nox/S0/Ability_E/Ability_Nox_FlashTrap', CDC, None, 'CooldownSeconds'),
    ('Vyse', 'Shear', C + 'Nox/S0/Ability_Q/Ability_Nox_Wall', 'AbilityCooldownComp_GEN_VARIABLE', None, 'CooldownSeconds'),
]


def read_text(pkg, export, field):
    """A string field (an enum or a tag name) of `export` in `pkg`, or None."""
    for e in load(pkg)[1]:
        if e.get('Name') == export:
            try:
                v = _walk(e.get('Properties') or {}, field)
            except (KeyError, IndexError, TypeError):
                return None
            return v if isinstance(v, str) else None
    return None


def wiki_restock():
    """`{(agent, ability name): restock text}` from the wiki harvest; '' for none."""
    path = STORE / 'reference' / 'abilities.json'
    with open(path, encoding='utf-8') as f:
        agents = json.load(f)['agents']
    return {(ag, ' '.join(x['name'].split())): (x.get('infobox') or {}).get('Restock', '')
            for ag, v in agents.items() for x in v['abilities']}


def _catalogue_seconds(text):
    return [float(n) for n in re.findall(r'(\d+(?:\.\d+)?) seconds', text or '')]


def restock_rows():
    """One row per RESTOCK entry: files value, toggled value and toggle, the
    catalogue's text and how the two compare."""
    cat = wiki_restock()
    default_toggle = read_text(CCD, 'Default__Comp_Ability_CooldownComponent_C', 'DPT_FeatureToggle')
    rows = []
    for agent, name, pkg, comp, tuning, field in RESTOCK:
        r = dict(agent=agent, ability=name, pkg=pkg, comp=comp, cites=[])
        base = read(pkg, comp, field) if field and has_field(pkg, comp, field) else None
        if base is not None:
            r['cites'].append(f'{asset_path(pkg)} {comp}.{field} = {fmt(base)} s')
        files = base
        tag = read_text(pkg, comp, 'CooldownDurationTuningTag.TagName')
        r['tagged'] = bool(tag) and tag != 'None'
        if tuning:
            files = read(*tuning)
            r['cites'].append(f'{comp}.CooldownDurationTuningTag = {tag}; {asset_path(tuning[0])} '
                              f'{tuning[1]}.{tuning[2]} = {fmt(files)} s')
        r['files'] = files
        r['toggled'] = read(pkg, comp, 'DPT_Cooldown') if has_field(pkg, comp, 'DPT_Cooldown') else None
        r['blocked'] = None
        if r['toggled'] is not None and r['tagged']:
            # Comp_Ability_CooldownComponent's bytecode: AuthUpdateCooldownTimeForDPT applies DPT_Cooldown
            # through AuthSetCooldownDuration, which refuses while IsUsingTuningTag is true, and
            # AuthSetupCooldownDurationTuning sets that flag from the tag at BeginPlay. A tagged
            # component's DPT value therefore never applies.
            r['blocked'], r['toggled'] = r['toggled'], None
            r['cites'].append(f'{comp}.DPT_Cooldown = {fmt(r["blocked"])} s, which never applies: the '
                              f'component uses a tuning tag, and AuthSetCooldownDuration refuses a manual '
                              f'duration while IsUsingTuningTag is set (Comp_Ability_CooldownComponent bytecode)')
        if r['toggled'] is not None:
            tog = read_text(pkg, comp, 'DPT_FeatureToggle') or default_toggle
            r['toggle'] = tog.split('::')[-1]
            r['cites'].append(f'{comp}.DPT_Cooldown = {fmt(r["toggled"])} s under DPT_FeatureToggle {tog}'
                              + ('' if read_text(pkg, comp, 'DPT_FeatureToggle') else
                                 ' (the component class default)'))
        key = (agent, name)
        if key not in cat:
            raise KeyError(f'no catalogue entry {key}')
        r['catalogue'] = cat[key]
        secs = _catalogue_seconds(cat[key])
        if not secs:
            r['verdict'] = 'catalogue none'
        elif files in secs:
            r['verdict'] = 'agrees'
        elif r['toggled'] in secs:
            r['verdict'] = 'agrees with toggled'
        else:
            r['verdict'] = 'disagrees'
        r['key'] = agent_slug(agent) + '_' + ability_slug(name).replace('-', '_')
        rows.append(r)
    return rows


def restock_fact():
    rows = restock_rows()

    def label(r):
        return f"{r['agent']} {r['ability']}"

    def files_words(r):
        s = f"{label(r)} {fmt(r['files'])} s"
        if r['toggled'] is not None and r['toggled'] != r['files']:
            s += f" ({fmt(r['toggled'])} s under {r['toggle']})"
        return s
    by = {}
    for r in rows:
        by.setdefault(r['verdict'], []).append(r)
    claim = ("The cooldown components of build 13.06 give these restock times, the seconds after use before a "
             "spent charge returns: " + '; '.join(files_words(r) for r in rows) + ". A value in brackets is the "
             "component's DPT_Cooldown, which applies while the named DPT_FeatureToggle is on; the toggle is a "
             "server setting, so the files give both values and not which one plays.")
    src = (f"game-extract exports of {BUILD_ID}, set ability-states, under the store's {STORE_REL}/; the catalogue "
           f"is the wiki harvest reference/abilities.json (2026-09-04), infobox Restock. Each value, as stored: "
           + '; '.join(f"{label(r)}: " + '; '.join(r['cites']) for r in rows))

    def cat_words(rs):
        out = []
        for r in rs:
            tog = (f", {fmt(r['toggled'])} s under {r['toggle']}" if r['toggled'] is not None
                   and r['toggled'] != r['files'] else '')
            out.append(f"{label(r)} (files {fmt(r['files'])} s{tog}; catalogue \"{r['catalogue']}\")")
        return ', '.join(out)
    exc = []
    differ = sorted(by.get('agrees with toggled', []) + by.get('disagrees', []), key=label)
    if differ:
        exc.append('The catalogue differs from the files\' base value on ' + cat_words(differ) + '. Each stands '
                   'as a disagreement, not a supersession: an AbilityTuning row may be retuned and a feature '
                   'toggle set on the server, neither readable from the client files, so a timed restock in a '
                   'capture decides.')
    blocked = [r for r in rows if r['blocked'] is not None]
    if blocked:
        exc.append('A DPT_Cooldown never applies on '
                   + ', '.join(f"{label(r)} ({fmt(r['blocked'])} s)" for r in blocked)
                   + ': each component uses a tuning tag, and the component\'s bytecode refuses a manual '
                   'duration while IsUsingTuningTag is set.')
    toggled_base = [r for r in by.get('agrees', []) if r['toggled'] is not None and r['toggled'] != r['files']]
    if toggled_base:
        exc.append('It matches the base value, not the toggled one, on '
                   + ', '.join(f"{label(r)} ({r['toggle']} would give {fmt(r['toggled'])} s)" for r in toggled_base)
                   + '.')
    states = {}
    for r in by.get('agrees with toggled', []):
        states.setdefault(r['toggle'], [set(), set()])[0].add(label(r))
    for r in toggled_base:
        states.setdefault(r['toggle'], [set(), set()])[1].add(label(r))
    words_ = []
    for tog, (on, off) in sorted(states.items()):
        if on and off:
            words_.append(f'{tog} splits ({len(on)} toggled, {len(off)} base)')
        else:
            words_.append(f"{tog} matches its {'toggled' if on else 'base'} value on all {len(on) + len(off)}")
    if words_:
        exc.append('By toggle, the catalogue: ' + '; '.join(words_) + '. A split means the '
                   'catalogue mixes dates or the toggle is not the whole story; the files do not say which '
                   'value plays, so a timed restock in a capture decides.')
    if by.get('catalogue none'):
        exc.append('The catalogue lists no restock for ' + ', '.join(label(r) for r in by['catalogue none'])
                   + ', whose components carry one; a recall or pickup restock is the likely use, unread here.')
    exc.append("Gekko's restocks run through reclaimed globules [domain:abilities/gekko-abilities-drop-pickups]; "
               "the component's time is the wait after a reclaim, as far as its field name says. An AbilityTuning "
               "row may be retuned on the server. These are class defaults; a field name is the designers' word, "
               "not a measured meaning.")
    files_t = ', '.join(f"{r['key']} = {fmt(float(r['files']))}" for r in rows)
    tog_t = ', '.join(f"{r['key']} = {fmt(float(r['toggled']))}" for r in rows if r['toggled'] is not None)
    text = '\n'.join([
        '[ability-restock-times]', f'claim = {tq(claim)}', 'kind = "measurement"', 'known = "measured"',
        f'since = "{SINCE}"', 'subject = "abilities:restock"', f'source = {tq(src)}',
        'use = """\nan ability\'s restock time: `files`; where `toggled` holds a value, the live time depends on a\n'
        'server toggle the files do not carry, and is one of the two\n"""',
        f'exceptions = {tq(" ".join(exc))}',
        f'values = {{ files_s = {{ {files_t} }}, toggled_s = {{ {tog_t} }} }}',
        'see = ["abilities/catalogue-restock-and-ult-points-confirmed", '
        '"abilities/game-files-outrank-player-quantities", "abilities/gekko-abilities-drop-pickups"]']) + '\n'
    return 'ability-restock-times', text, rows


def render():
    """The facts file's text and, per ability, the coverage row it implies."""
    evald, errors = evaluate()
    if errors:
        raise ValueError('unreadable citations:\n' + '\n'.join(errors))
    parts = [HEADER]
    for _, text in movement_facts():
        parts.append(text)
    parts.append(restock_fact()[1])
    cov = []
    for a in evald:
        fid, text, groups = ability_fact(a)
        parts.append(text)
        cov.append(dict(agent=a['agent'], slot=a['slot'], ability=' '.join(a['ability'].split()),
                        fact='game_data/' + fid, roles=sorted(groups), life=dict(groups.get('life', {}))))
    return '\n'.join(parts), cov


SHEET_ROLES = [('life', 'Life'), ('size', 'Size'), ('angle', 'Angle'), ('range', 'Range'),
               ('unconfirmed', 'Unconfirmed length'), ('speed', 'Speed'), ('move', 'Moves caster'),
               ('minimap', 'Minimap size')]


def coverage_table(cov):
    rows = ['| Agent | Slot | Ability | ' + ' | '.join(r[1] for r in SHEET_ROLES) + ' | Fact |',
            '|---|---|---|' + '---|' * len(SHEET_ROLES) + '---|']
    for c in cov:
        rows.append(f"| {c['agent']} | {c['slot']} | {c['ability']} | "
                    + ' | '.join('yes' if r in c['roles'] else '' for r, _ in SHEET_ROLES)
                    + f" | [domain:{c['fact']}] |")
    return '\n'.join(rows)


def duration_cell(c):
    words_ = ', '.join(f"{k[:-2].replace('_', ' ')} {v:g} s" for k, v in c['life'].items())
    return f"game data: {words_} [domain:{c['fact']}]"


def sheet_proposals(cov, sheet_text):
    """(agent, slot, current cell, proposed cell) for each Duration cell of the
    sheet that is open (`?`) or already cites game data, where the facts hold a
    lifetime. A player's answer is never proposed over."""
    by = {(c['agent'], c['slot']): c for c in cov}
    out, agent = [], None
    for line in sheet_text.split('\n'):
        m = re.match(r'^## (.+)$', line)
        if m:
            agent = m.group(1).strip()
            continue
        if not (agent and line.startswith('| ')) or line.startswith('| Slot') or line.startswith('|---'):
            continue
        cells = line.split(' | ')
        slot = cells[0][2:].strip()
        c = by.get((agent, slot))
        if c is None or len(cells) != 11 or not c['life']:
            continue
        cur = cells[9].strip()
        if cur == '?' or cur.startswith('game data:'):
            out.append((agent, slot, cur, duration_cell(c)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', type=Path, default=FACTS, help='where to write the facts file')
    ap.add_argument('--check', action='store_true', help='compare with --out and write nothing')
    ap.add_argument('--sheet', action='store_true',
                    help='print the sheet cells and coverage table the facts imply; write nothing')
    args = ap.parse_args(argv)
    text, cov = render()
    if args.sheet:
        for agent, slot, cur, new in sheet_proposals(cov, SHEET.read_text(encoding='utf-8')):
            if cur != new:
                print(f'{agent} {slot}: {cur} -> {new}')
        print(coverage_table(cov))
        return 0
    if args.check:
        same = args.out.exists() and args.out.read_bytes() == text.encode('utf-8')
        print(f"{args.out}: {'matches' if same else 'DIFFERS from'} the regenerated text")
        return 0 if same else 1
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('wrote', args.out, len(cov), 'ability facts')
    return 0


if __name__ == '__main__':
    sys.exit(main())
