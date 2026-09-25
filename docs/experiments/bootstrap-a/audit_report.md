# E1 Event Correspondence Audit: a06f04a0059f Rounds [3, 4, 5, 6]

## Executive Summary

- **Total death opportunities audited**: 34
- **Fully agreed deaths (Killfeed + Scoreboard)**: 10 (29.4%)
- **Single-channel rescues**: 19 (55.9%)
  - Killfeed rescues Scoreboard refusal: 16
  - Scoreboard rescues Killfeed refusal: 3
- **Explicit abstentions (both channels refused)**: 5 (14.7%)

## 1. Cross-Channel Ablation Findings

| Withheld Channel | Resolved Victim Accuracy | Lost Victims (Became Abstained) | Remaining Matches |
|---|---|---|---|
| Scoreboard (`scoreboard_dim`) | 89.7% | 3 | 34 / 34 |
| Killfeed (`killfeed_portrait`) | 44.8% | 16 | 34 / 34 |

### Scoreboard Rescue Details (Deaths lost when scoreboard is withheld)
- **Round 4 at 284.5s**: Victim **Jett** (side: enemy). Scoreboard resolved Jett; Killfeed refused: `portrait_views_refused_or_disagree`.
- **Round 4 at 295.0s**: Victim **Miks** (side: ally). Scoreboard resolved Miks; Killfeed refused: `portrait_single_view`.
- **Round 5 at 443.0s**: Victim **Breach** (side: ally). Scoreboard resolved Breach; Killfeed refused: `portrait_single_view`.

## 2. Refusal and Abstention Diagnosis

When both channels refuse, Reticle explicitly preserves `status = 'abstained'` with concrete reasons rather than guessing:

- **Round 3 at 176.5s** (side: enemy):
  - Killfeed refusal: `portrait_views_refused_or_disagree`
  - Scoreboard refusal: `newly_dim_2_disagrees_with_killfeed_deaths_3`
- **Round 3 at 183.5s** (side: enemy):
  - Killfeed refusal: `portrait_single_view`
  - Scoreboard refusal: `newly_dim_2_disagrees_with_killfeed_deaths_3`
- **Round 6 at 540.0s** (side: enemy):
  - Killfeed refusal: `no_stored_portrait_at_entry`
  - Scoreboard refusal: `interval_unordered ['Iso', 'Jett', 'Killjoy', 'Omen', 'Skye']`
- **Round 6 at 540.0s** (side: enemy):
  - Killfeed refusal: `portrait_single_view`
  - Scoreboard refusal: `interval_unordered ['Iso', 'Jett', 'Killjoy', 'Omen', 'Skye']`
- **Round 6 at 545.0s** (side: enemy):
  - Killfeed refusal: `portrait_single_view`
  - Scoreboard refusal: `interval_unordered ['Iso', 'Jett', 'Killjoy', 'Omen', 'Skye']`

## 3. Combat Report Corroboration on Player Deaths

| Round | Combat Report Player Deaths | Killfeed Player Deaths | Second Life Deaths | Corroboration Verdict |
|---|---|---|---|---|
| Round 3 | 1 | 1 | 0 | Exact agreement (Jett (death)) |
| Round 4 | 1 | 1 | 0 | Exact agreement (Omen (death)) |
| Round 5 | 0 | 0 | 0 | Exact agreement (Survived) |
| Round 6 | 1 | 1 | 0 | Exact agreement (Omen (death)) |

## Conclusion
Total round counts alone conceal intermediate single-channel rescues and abstentions. Exact 1-to-1 event alignment with temporal tolerances exposes these dependencies.