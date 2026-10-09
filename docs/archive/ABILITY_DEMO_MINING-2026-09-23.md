# Ability mining on the solo demos, 2026-09-23

Archived 2026-10-09 from `worktree-agent-a3c32f26e36c27c4f` (453a6b7, also
`origin/unmerged-glyph-refusal-20260923`). The classifier change it describes
never merged: glyph naming moved to `reticle/adjudication/ability_glyph.py`.
The code it names survives only on that branch.

**Outcome: plumbing and cross-checks landed; exemplar harvest is blocked on a
player label.** The HUD tray cannot label a minimap candidate by itself, so no
gallery exemplar was added and retrieval on the unlabelled demos adds nothing.
Web facts now enter as reviewable proposals, two of which contradict accepted
facts. The glyph classifier now names only abilities an independent witness
allows, and refuses where no rule fires.

Commands: `tools/ability_demo_mining.py witness|facts|retrieve|charges` and
`tools/ability_glyph_eval.py [--gate agent]`. Both read stored data; the
evaluation decodes one frame per labelled candidate and keeps features, not
pixels. References and their patch scope live in
`tools/data/ability_web_references.json`; proposals publish under the store's
`analysis/domain-hypotheses/`.

## The tray does not bind a candidate

On the reviewed solo demos, a candidate with exactly one tray edge from
`adjudication.ability` carries the tray's ability name in
[metric:ability_demo_mining/tray-witness#named_same=7] of
[metric:ability_demo_mining/tray-witness#bound=68] cases
([metric:ability_demo_mining/tray-witness#precision=0.103]); the player
rejected [metric:ability_demo_mining/tray-witness#clutter=32] as clutter.
Jett's Tailwind, a dash with no minimap object, binds seven. The filename
labels `load_harvested_gallery` reads rest on this edge.

Consequently retrieval over
[metric:ability_demo_mining/retrieval#candidates=949] candidates on the
unlabelled demos adds [metric:ability_demo_mining/retrieval#added=0] names:
[metric:ability_demo_mining/retrieval#refused=608] refuse (at the player's
icon, or no labelled exemplar of the tray's ability in another session, or too
few on the same map) and [metric:ability_demo_mining/retrieval#unknown=341]
have no unique tray edge and stay unknown.

## Web facts as proposals

`domain_learning` takes a `reference` evidence node (URL, retrieval date,
patch, quote). A reference never counts as independent support, and
references on both sides of a claim raise a source disagreement.
Patch notes 13.04 to 13.06 list no numeric ability change, so the agent pages
apply to the matches (13.04) and the demos (13.05).

[metric:ability_demo_mining/web-facts#proposals=26] proposals, all valid;
[metric:ability_demo_mining/web-facts#source_disagreements=3] carry a source
disagreement (Dark Cover restock 40 s against a tracker's 35 s; Recon Bolt and
Guiding Light cooldowns 50 s against the catalogue's 60 s), and
[metric:ability_demo_mining/web-facts#accepted_fact_conflicts=2] contradict an
accepted fact: [domain:abilities/omen-tray-charges] states a 30 s restock where
the official page and the catalogue say 40 s, and [domain:abilities/phoenix-blaze]
states about 4 s where the page says 8 s. Both accepted facts stay unchanged.

Cross-checks, by kind of evidence:

- **Durations against lifetimes.** A detector candidate is a tracklet: ten
  named Hunter's Fury fragments last 150-1500 ms against a 6 s ultimate. Of
  the fragments, [metric:ability_demo_mining/web-facts#supporting_obs=4]
  support, [metric:ability_demo_mining/web-facts#contradicting_obs=0]
  contradict and [metric:ability_demo_mining/web-facts#unresolved_obs=75] stay
  unresolved. Spans of human-verified casts give
  [metric:ability_demo_mining/web-facts#instance_supporting=2] supporting
  instances (Hunter's Fury 5.25 s, Guiding Light 1.5 s) and
  [metric:ability_demo_mining/web-facts#instance_contradicting=0]
  contradicting.
- **Charges against tray drops.** One cast drops the tray by 1/Uses in
  [metric:ability_demo_mining/tray-charges#matching=31] of
  [metric:ability_demo_mining/tray-charges#casts=33] demo casts. Clove's Ruse
  drops a full slot at once; the source shows both clouds landing together at
  15.0 s, which the ability text describes as one confirmation launching every
  placed cloud. The tray counts charges spent, not casts.

## Classifier changes, scored against human labels

Splits are fixed first: the second half of each solo clip is the
same-session held-out split (not generalisation), the first half is dev, and
the labelled match sessions are scored only.

| Change | Split | Wrong rate before | after | Correct before | after |
| --- | --- | --- | --- | --- | --- |
| Agent gate (0.2.0) | held-out | [metric:ability_glyph_eval/compare-agent-gate-held_out#before_wrong_rate_named=0.842] | [metric:ability_glyph_eval/compare-agent-gate-held_out#after_wrong_rate_named=0.263] | [metric:ability_glyph_eval/compare-agent-gate-held_out#before_correct=6] | [metric:ability_glyph_eval/compare-agent-gate-held_out#after_correct=6] |
| Agent gate (0.2.0) | match | [metric:ability_glyph_eval/compare-agent-gate-match#before_wrong_rate_named=0.989] | [metric:ability_glyph_eval/compare-agent-gate-match#after_wrong_rate_named=0.693] | [metric:ability_glyph_eval/compare-agent-gate-match#before_correct=1] | [metric:ability_glyph_eval/compare-agent-gate-match#after_correct=1] |
| Open-set refusal (0.3.0) | held-out | [metric:ability_glyph_eval/compare-open-set-held_out#before_wrong_rate_named=0.263] | [metric:ability_glyph_eval/compare-open-set-held_out#after_wrong_rate_named=0.079] | [metric:ability_glyph_eval/compare-open-set-held_out#before_correct=6] | [metric:ability_glyph_eval/compare-open-set-held_out#after_correct=6] |
| Open-set refusal (0.3.0) | match | [metric:ability_glyph_eval/compare-open-set-match#before_wrong_rate_named=0.693] | [metric:ability_glyph_eval/compare-open-set-match#after_wrong_rate_named=0.58] | [metric:ability_glyph_eval/compare-open-set-match#before_correct=1] | [metric:ability_glyph_eval/compare-open-set-match#after_correct=0] |

False names on candidates the player rejected fall on held-out from
[metric:ability_glyph_eval/compare-agent-gate-held_out#before_false_name=105]
to [metric:ability_glyph_eval/compare-open-set-held_out#after_false_name=9].
The open-set rule lost two names that were right by elimination (scores 0.10
and 0.30, both failing rules). The Cypher sessions 79a706a7ce4c and
eb10db50b1fb, a true cross-session check, now name none of their nine Trapwire
anchors Spycam.

Both predictions failed on match transfer. The remaining match errors are
Deadlock: the lineup allows Deadlock, the classifier has no Deadlock class, and
Sonic Sensors pass the Alarmbot rule itself. Tuning stopped there.

## Questions for the player

1. Label the 103 `ability-group` review windows on the 22 unlabelled demos with
   `prototypes/label_grouping.py --session S`. Start with Omen
   (`e78e75b2d191`, `b9558488a607`): two clips give the only cross-session
   split among the demos.
2. In `28f53bfddbbe` at 15.0 s, are both dark discs Ruse clouds from the one
   E press at 14.5 s?
3. Omen's Dark Cover restock: is [domain:abilities/omen-tray-charges]'s 30 s
   stale against the pages' 40 s?
4. Phoenix's Blaze: does the minimap draw it for about 4 s, as
   [domain:abilities/phoenix-blaze] says, or for the page's 8 s? The existing
   clip `481336df9adb` (cast at 6.0 s) can answer it with a label.

## Minimum new solo takes

Per the capture policy in
[ABILITY_ENTITY_INFERENCE_DESIGN.md](ABILITY_ENTITY_INFERENCE_DESIGN.md), only
gaps existing footage cannot close:

1. **Deadlock** (no solo clip exists): Sonic Sensor twice, Barrier Mesh once,
   GravNet once, on Ascent with the large minimap, standing still, casts at
   least 5 s apart, holding 10 s after each. It supplies the class whose
   absence causes the remaining match errors.
2. **Viper**: Poison Cloud, Toxic Screen and Viper's Pit each alone, spaced,
   toggling each emitter once. Six labelled Pit and Screen candidates become
   Poison Cloud because the three share one appearance rule.
3. **Clove**: one Ruse confirmed with a single cloud, then one with two. It
   tests the batch-launch proposal against a 0.5 and a 1.0 tray drop.
