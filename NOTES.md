# Reticle — working notes

Where the work stands **today**: the handoff into the next session, and the
defects that are live rather than standing. `CLAUDE.md` carries what stays
true across sessions — the conventions, the domain rules, the mistakes worth
not repeating. This file carries what is true this week, and it is read on
demand rather than loaded into every session.

Read it when picking up unfinished work. Update it in place; let it go stale
rather than let it grow.

Split out of `CLAUDE.md` on 2026-08-27.

## Picking up

**2026-09-04. A LABELLING PASS IS QUEUED AND READY — that is the next action.**
Five sessions are filtered, rendered, reviewed and stamped. the player runs:

    .\.venv\Scripts\python.exe prototypes\label_ability.py <session>

    dae6f33f3f48  Killjoy  76 candidates   Nanoswarm / Alarmbot / Turret / Lockdown
    02cf738b1c8f  Sova     29              Owl Drone / Shock Bolt / Recon Bolt / Hunter's Fury
    6bb88dba5d2c  Viper    22              Snake Bite / Poison Cloud / Toxic Screen / Viper's Pit
    6ab7a9e99235  Skye     16              Regrowth / Trailblazer / Guiding Light / Seekers
    ff19748eea8c  Jett     13              CONTROL -- no persistent minimap devices

the player chose the spread over labelling one session deep, because the corpus that
failed to transfer was five ability classes from three agents. Jett is in as the
false-positive floor: nearly everything it surfaces should be a negative, and if
it is not, the detector is finding something nobody has named.

**`64d0fb783be2` (Vyse) was PULLED and its stamp revoked.** 65 of its 96
candidates fall in a single 10-second window of a 56-second clip, and they render
as flat salmon-pink tiles with no object in them. That is one event flooding the
file, not a detection class. Find out what happens at 40-50s before labelling it.

**What was measured this session, in one place**

* **`patch_range` is the first ability feature that transfers.** Precision
  0.13 -> **0.49 at 0.85 recall**, leave-one-session-out. It is the median over
  the window of `g_max - g_min` in the 15x15 patch: intra-patch contrast. Most
  of its signal is SPATIAL -- a single frame scores 0.76 pooled against the
  median's 0.86 -- so Phase 1's payoff here was cheap aggregation, not a
  temporal signal. `prototypes/ability_features.py`;
* **complements are real, weighting them is not affordable.** `n_runs`
  (correlation 0.26 with contrast) and `cone_cond` (0.04) separate the
  candidates that PASS the contrast gate. `AND` them and precision goes 0.49 ->
  0.73 -> 0.80 while recall collapses; an equal-weight z-sum ties at best. A
  weighted combiner is what the evidence asks for and 27 positives will not
  support fitting one. **This is why the labelling pass is the next action** --
  the blocker stopped being feature design;
* **`cone_cond` is NOT falsified**, though an earlier commit said so. A
  single-feature AUC structurally cannot see a complement;
* **noise normalisation hurts** (`dark_z_p90` 0.63 vs plain `dark_p90` 0.79).
  The earlier 1.36 -> 2.69 figure was five positives of one class and does not
  survive four sessions;
* **`patch_range AND n_runs` gives 0.73 precision at 0.41 recall** -- a usable
  operating point for ranking candidates in assisted labelling, though its F1 is
  worse than contrast alone.

**The reference harvest is done and is a new substrate.**
`prototypes/ability_reference.py`, into `<store>/reference/`: 29 agents, 121
abilities, 118 icons, 29 minimap portraits, **56 ultimate voicelines as isolated
game-file MP3s** (ally and enemy variants). `check` passes 74 agree / 0 disagree,
so `ability_hud.py`'s C/Q/E/X slot mapping is now measured against an
independent source. `Deployment Type` gives the shape family per ability
(13 Placement, 10 Missile, 9 Self-targeted, 4 Grounded AoE, 3 Grounded Object)
and 21 deployables state a Health. **The class list for any ability labeller is
now derivable** -- the agent is in the manifest `tags`, the kit is in the
reference.

**Two things the official art did NOT do.** `minimapPortrait` scored by pixel
NCC misses badly (41.8% against a 70.4% bar) -- and that re-ran a method
`prototypes/CLAUDE.md` already records as dead, since identity at 11 px lives in
the palette, not the layout. By COMPOSITION it reaches **78.5% at zero
parameters** against the scoreboard's 77.2%, which is a wash on accuracy and a
real win operationally: it needs no scoreboard opening, and scoreboard portrait
extraction is recorded as wrong on two sessions of three.

**NEXT, in order.**

1. **The labelling pass above.** Then re-run `ability_features.py --gate`; with
   positives in the hundreds a weighted combiner becomes fittable, and the shape
   and colour families have something to join.
2. **The mini design doc for ability recognition** -- the player asked for this
   explicitly as the next session's work. It should supersede the Phase 2 plan in
   `docs/ability-temporal.html`, whose first-named feature (the cone-coverage
   two-factor conditional) failed as a gate.
3. **Shape features**, deferred deliberately: `cv2.minAreaRect` elongation,
   solidity, Euler number, `cv2.matchShapes` Hu moments. They need a decode pass,
   and adding a family to a set that cannot be weighted will produce better
   single-feature AUCs and no better detector.
4. **The free geometry trim.** VOID / BOXEDGE / unreadable candidates are 28 of
   205 labelled and **0 of them are real** -- precision 15% -> 17% at zero recall
   cost. `geo_label` is in the candidate schema and is never populated.
5. **Ultimate voicelines**, now unblocked: `audio_probe.py` killed onset
   detection and said a matched filter needs a reference cut at a known cast
   time. The 56 MP3s are those cuts, and ally-vs-enemy carries team identity.

**Standing hazards.** Never re-scan `2ba870ccbd50`, `eb10db50b1fb`,
`d95cfad5693a`, `79a706a7ce4c` -- the label store key is unstable. Never seed a
label file. **The tile is not the object**: reading the Killjoy contact sheet I
called "map line-work" a large false-positive class, and at the candidate's own
pixel 177 of 205 sit on FLOOR. The eye pools a neighbourhood; the detector must
commit to a pixel.

**Other live threads, not touched this session.** Detail is in
`git show HEAD~1:NOTES.md` and in the module docstrings; only the heads are kept
here, because this section grew to 744 lines by stacking handoffs and the
standing instruction is to keep it short.

* **minimap position (self) is shipped; allies are not.** Next: ally identity
  across frames (nearest-to-previous per slot, seeded at round start while the
  spawn barrier is up), then the visibility computation dA/ds that position
  tracking was always gating -- `floor_mask` is already the occlusion grid it
  needs -- then enemy-icon states (solid / question-mark / X), still unread;
* **vision cones:** confirm the half-angle on a second map, and find a case
  where a raycast actually crosses a boxedge pixel to confirm pass-through.
  the follow-up: use many cone instances to tell a real wall from a
  mislabelled box in `minimap_geometry`, which needs more footage than one clip.

**Still true and still queued:** `ability_corpus.load_events` takes `min(dists)`
across an event's fragments, re-introducing the Phase 0a failure one level up;
three different `floor` conventions feed `self_rings`; grouping lives in
`load_events` and should be lifted out for the labeller; a pulsing region still
gets one event per pulse; teleports break the shipped position track for Veto,
Omen, Chamber and Waylay.

## Live defects

Bugs with an owner and an end. The standing hazards — the ones that are properties
of the problem rather than tickets — stay in `CLAUDE.md` under "Open defects".

- **One known read error, plus two unexplained**, across 372 events at
  `hud-0.8.1`. The raw gap against `checks.KNOWN_KD` is 8 events, from 24 at
  `hud-0.6.0`: five are verified Run It Back, one is the ability kill below, and
  two are `e37fdeca944f`'s missing deaths, which nobody has looked at yet. See
  "Scoreboard divergence is a finding" in `CLAUDE.md` before quoting the 8.
  `killfeed.py` has the per-session table.
- **The one real miss left is an ability kill.** `c40d950031bb` 13:14,
  `HungryHamster5 ⊗ Me`, killed by Raze. There is no weapon icon, and the
  ability mark fragments under the white-text cut into pieces too small to be a
  divider candidate, so the band goes *unparsed* and the death is lost. Reading
  it needs a divider that does not depend on the icon — the boundary between the
  two plate colours is the candidate, and it needs no list of icons. A prototype
  landed the split correctly on 6 of 8 test bands; the estimator needs to be
  edge detection on the plate chevron rather than a brute-force search.
- **Scoreline OCR drops a transient extra digit.** On `9acf02f98283` the score
  reads `1 → 11 → 1` and `9 → 19 → 9` within half a second, i.e. a spurious
  leading `1`, and `verify` flags 8 violations there. Single-sample, reverts
  immediately, and unrelated to the killfeed. Clock read rate on that session is
  also low (39.7%). Worth a look when next in `ocr.py`.
- **`README.md` is stale.** It says HP, ammo and the killfeed are unbuilt; they
  are built, and it still describes stage 02 as scoreline-only. Fix it when next
  touching that area.
