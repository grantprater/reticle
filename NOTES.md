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

**2026-09-05. The ability channel was re-founded on a different question, and
the full argument is a document rather than a handoff:**

**The ability event log** -- `docs/ability-recognition.html`,
https://claude.ai/code/artifact/bffd7660-cd3e-4e6f-ada9-3be6b0dca887
**The minimap entity model** -- `docs/minimap-entity-model.html`,
https://claude.ai/code/artifact/324e1c5f-9240-4b13-8ff1-59adb24a2f06
The first is what the log contains; the second is what an entity IS, with a
driver PER PARAMETER. Read both before picking this up; below is only state.

**What today settled, in one place.**

* **the labelling pass is DONE** -- 5 sessions, 161 records, 58 new positives,
  giving 85 pos / 252 neg over 9 sessions, up from 27 over 4;
* **it falsified the claim it was run to support.** `patch_range` pooled AUC
  **0.86 -> 0.57**, consistent 4 of 9. The break is perfectly confounded with
  capture regime (4 ordinary captures vs 5 `infinite-abilities` demos), so the
  corpus cannot say whether the feature never generalised or the demos are a
  different world. **One ordinary-capture session labelled the new way is the
  one footage ask**, and it is worth more than any number of demo clips;
* **the weighted combiner does not earn its parameters.** Equal-weight z-sum
  matches or beats it in every configuration (0.74 vs 0.69 AUC), and sign
  agreement is 100% across all 8 folds -- so this is not fold noise, the
  features are near-redundant. Label volume was never the blocker;
* **per-session z-scoring is worth more than any weighting** (0.74 vs 0.64).
  The dominant recoverable variance is per-session, not per-object;
* **current honest best**: equal-weight z-sum, per-session z, leave-one-session-
  out -- precision 0.36, recall 0.68, AUC 0.74, against a 0.21 baseline. Worse
  than the 0.49 @ 0.85 that was on record, on three times the data;
* **the cast-anchored detector is built and emitting.**
  `prototypes/ability_cast.py`, joining `ability_hud.py`'s tray drops to the
  reference kit: **24 casts, 27 of 43 agent-named positives explained (63%)**,
  and `--emit` writes events to `<store>/events/ability/`;
* **"slot X never drops" was a defect in the READER.** The ult pips desaturate
  with the bar, so the existing teal mask reads them: slot X goes 909 -> 0 teal
  px between 28.0s and 28.5s against a Hunter's Fury label at 28.2s. Two bugs
  compounded -- `casts()` looped `range(3)`, and `drawn()` refused the frame
  because an all-spent tray reads as "not rendered". Both fixed;
* **a cast buys the EVENT cheaply and NOT the POSITION.** Widening the position
  window never raised the number of correct picks (3, at every width), so
  position is emitted only when the window holds exactly one candidate -- 2 of 2
  exact -- and is null otherwise, with the candidates carried along. Time and
  identity come free from HUD structure; location still needs the weak detector.
  **State this wherever the 63% is quoted.**

**the domain facts from today, none recoverable from pixels.** Detail is in
the module docstrings and the design doc; the heads only:

* **controllable deployables emit vision cones too** -- Owl Drone, Tejo's
  Stealth Drone, Skye's Trailblazer AND Guiding Light, Fade's Prowler, Killjoy's
  turret. Same half-angle is EXPECTED, not known. `self_cone()` cannot see them,
  and `cone_cond` -- now the best single feature, inverted, 7 of 9 consistent --
  is computed against the player's cone only. See `minimap_cone.py`;
* **`radius_ring` is what a DEPLOYED device draws, not placement** (Killjoy,
  Chamber, Veto). The ring is not the device: a candidate on the perimeter sits
  tens of px from its object;
* **held placeables want a `mode` field**, currently leaking into category names
  (`place_color`, `smoke` vs `smoke_deployed`). A preview sits at the player's
  feet, so it contaminates `self_d_med`;
* **deployed smokes are one agent-independent class on purpose** -- Jett's
  Cloudburst and Viper's Poison Cloud are both generic `smoke`, because the
  minimap carries no thrower identity;
* **placement hold time is unbounded** -- only the ~1-2s before the commit
  carries positional information; a long hold is its own signal;
* **`infinite-abilities` is a misleading tag on the five demo sessions** --
  toggled on to charge the ult, then off. `2ba870ccbd50` (Brimstone) genuinely
  had it on. **Viper's Pit is SUSTAINED**, so its bar releases when the pit ENDS
  (drop at 44.0s against labels at 36.9-42.6s);
* **Skye's Regrowth drains only while healing someone**, so `no cast` in a solo
  clip is correct, not a sampling defect.

**The cone tint is real and `blob_colour` structurally cannot see it.** Killjoy's
turret cone is green-tinted; `minimap_dynamic.blob_colour` gates on `s > 90`
before naming any colour and a translucent tint never clears it. Needs its own
low-saturation hue test -- do NOT loosen `COLOUR_SAT`, which is load-bearing.

**NEXT, in order.** (The design doc's SS8 is the fuller version.)

1. **Label negatives on `a06f04a0059f` (53 positives) and `5822b6646448` (35).**
   Both were labelled POSITIVES-ONLY, so the scorer skips them for having no
   both-class labels, silently -- 88 positives stranded, more than the whole
   usable corpus. No new footage, no decode. Render and review the candidates
   first; that mistake has three recorded recurrences.
2. **One ordinary-capture session labelled the new way**, to break the regime
   confound. Until it exists, do not fit anything across both regimes.
3. **Audit the other readers for silent exclusions.** Every real gain today came
   from finding something discarded without a word -- the both-class check,
   `range(3)`, `drawn()`. `killfeed.py`, `scoreboard.py` and
   `minimap_temporal.usable()` all carry guards of the same shape.
4. **Audio**, now genuinely unblocked: `audio_probe.py` killed onset detection
   and said a matched filter needs a reference cut at a known cast time. The 56
   ultimate voicelines are the cuts and the tray now supplies the times. It is
   also the only channel for OTHER players' casts -- and the framing is why
   that generalises: **audio range is roughly the observable range, and roughly
   what is worth recording**.
5. **A low-saturation tint test, and a deployable cone seed.** New observations
   rather than recombinations of the exhausted bank. Killjoy's turret cone is
   **100 degrees** against the player's measured ~112 -- from the reference
   text, not a measurement, so do not reuse `CONE_HALF_ANGLE_DEG` for it.
6. **A per-ability distance-from-player prior**, to break the position ties this
   module currently refuses. the player: only Omen's smoke and ultimate are truly
   global, so the shipped self track constrains every other ability. Measured
   medians span 21 px (Viper's Pit) to 180 px (Toxic Screen) and the ordering
   matches his families -- but n is 1-3 placements per ability, and the
   reference's `Deployment Type` is a different axis. See `ability_cast.py`.
7. **Represent an ability as ORIGIN + an OPTIONAL DEPLOYMENT VECTOR + a
   TRAJECTORY DRIVER.** the player proposed origin+vector, then withdrew it the same
   hour: objects change state after deployment, and the useful axis is what
   DRIVES the motion -- static, enemy-reactive (Killjoy's Alarmbot and turret),
   player-piloted (the scouts), player-aimed (Cypher's cam), or freeform-at-cast
   (Phoenix's wall). The vector is absent for rotation-invariant smokes: absent
   by construction, which is information, not a failed fit. `icon_facing()`
   already returns the pose half. It also re-justifies `cv2.minAreaRect` --
   deferred as a classifier feature, but the long axis of a grouped region IS
   the deployment vector, and measuring an object whose identity the cast
   already gave you is not classification.
8. **Enemy-reactive motion is an ENEMY DETECTION**, and CLAUDE.md lists opponent
   priors as blocked for want of enemy positions. An Alarmbot that moves is
   moving toward one; a turret that snaps is snapping onto one. Needs no new
   extractor -- the position track applied to an object the cast identified.
   Both are UNTESTABLE on the demo corpus (solo game, no enemies to react to),
   so this needs match footage.

**Do NOT**: add shape features (the bank is near-redundant and cannot be
usefully weighted -- measured); record more demo clips; chase `patch_range`.

**Standing hazards.** Never re-scan `2ba870ccbd50`, `eb10db50b1fb`,
`d95cfad5693a`, `79a706a7ce4c` -- the label store key is unstable. Never seed a
label file. **The tile is not the object**: at the candidate's own pixel 177 of
205 sit on FLOOR.

**`64d0fb783be2` (Vyse) is PULLED and TABLED at the call** -- 65 of 96
candidates in one 10s window, rendering as flat salmon tiles with no object.
Worth revisiting with the tint/illumination work: a coherent lit region produces
exactly that signature.

**Other live threads, not touched.** Detail in `git show HEAD~1:NOTES.md` and in
the module docstrings; heads only, because this section grows by stacking.

* **minimap position (self) is shipped; allies are not.** Next: ally identity
  across frames, then the visibility computation dA/ds, then enemy-icon states.
  Note ally CONES need no identity -- a cone is per-frame, and `ally_rings()`
  already returns the tuple `self_cone()` seeds from -- but the demo corpus is
  SOLO, so ally cones buy nothing there and everything on real-match footage;
* **vision cones:** confirm the half-angle on a second map, and find a case
  where a raycast actually crosses a boxedge pixel. Deployable cones are a
  second cone per clip on a path the player never walks, which is the cheap way
  out of "more footage than one clip supplies".

**Still true and still queued:** `ability_corpus.load_events` takes `min(dists)`
across an event's fragments, re-introducing the Phase 0a failure one level up;
three different `floor` conventions feed `self_rings`; a pulsing region still
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
