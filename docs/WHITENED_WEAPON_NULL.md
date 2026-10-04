# Whitened weapon open-set null

Findings of `prototypes/weapon_null_eval.py` (`wire: no`), 2026-10-04, on
branch `whitened-weapon-null-20261004`. Predictions and outcome:
`whitened-weapon-null-20261004` in the store's `notes/predictions.jsonl`.
Outputs: `<store>/analysis/whitened-weapon-null-20261004/`.

**Result: negative; the branch stays held.** No gate tested both names more
on Riot and refuses unseen icons as well as the overlap (IoU) gate does.

## Question

`weapon-adjudication-1.4.0` names a registered soft glyph by the whitened
matched filter, but only among the names the IoU floor clears, so it gains
nothing on Riot. Can a null read from the filter's own geometry replace
the IoU floor, refusing an unseen icon instead of misnaming it?

## Method

The statistic is the glyph's Mahalanobis distance `d2` to the winning
reference row, under the residual covariance `weapon.whiten_covariance`
fits. The split is the separability probe's 11 dev and 10 held sessions;
held was read only after each gate was frozen. Labels are the probe's
pipeline verdicts, so they measure agreement, and they cover only entries
the IoU rule resolved. Leave-one-icon-out (LOIO) refits the covariance
without one name's residuals and drops its references and IoU exemplars.
A left-out crop that a gate names is an unseen icon misnamed. The Riot
scores use the pinned reader-trial inputs of 4f207c0c4e39, 59c70f1ef720
and a06f04a0059f.

Gates:

- IOU: the 1.3.0 rule.
- WIRED: 1.4.0.
- NULL: `d2` at most the 0.999 quantile of right dev crops' leave-one-session-out `d2`, in place of the IoU floor. This gate was pre-registered.
- NULLS: `d2` over the winner's median right-crop `d2`. This gate was chosen on dev after NULL failed.
- INTER: WIRED's name, kept only when the NULLS ratio passes.

## Results

| gate | held right / wrong / refused | held LOIO misnamed | dev LOIO misnamed | Riot right / wrong / refused |
|---|---|---|---|---|
| IOU | [metric:weapon_null/held/iou#right=952] / [metric:weapon_null/held/iou#wrong=0] / [metric:weapon_null/held/iou#refused=0] | [metric:weapon_null/held/iou#loio_named=64] | [metric:weapon_null/dev/iou#loio_named=58] | [metric:weapon_null/riot/iou#weapon_right=531] / [metric:weapon_null/riot/iou#weapon_wrong=0] / [metric:weapon_null/riot/iou#weapon_refused=15] |
| WIRED | [metric:weapon_null/held/wired#right=952] / [metric:weapon_null/held/wired#wrong=0] / [metric:weapon_null/held/wired#refused=0] | [metric:weapon_null/held/wired#loio_named=63] | [metric:weapon_null/dev/wired#loio_named=58] | [metric:weapon_null/riot/wired#weapon_right=531] / [metric:weapon_null/riot/wired#weapon_wrong=0] / [metric:weapon_null/riot/wired#weapon_refused=15] |
| NULL | [metric:weapon_null/held/null#right=951] / [metric:weapon_null/held/null#wrong=0] / [metric:weapon_null/held/null#refused=1] | [metric:weapon_null/held/null#loio_named=535] | [metric:weapon_null/dev/null#loio_named=649] | [metric:weapon_null/riot/null#weapon_right=537] / [metric:weapon_null/riot/null#weapon_wrong=0] / [metric:weapon_null/riot/null#weapon_refused=9] |
| NULLS | [metric:weapon_null/held/nulls#right=943] / [metric:weapon_null/held/nulls#wrong=0] / [metric:weapon_null/held/nulls#refused=9] | [metric:weapon_null/held/nulls#loio_named=218] | [metric:weapon_null/dev/nulls#loio_named=312] | [metric:weapon_null/riot/nulls#weapon_right=537] / [metric:weapon_null/riot/nulls#weapon_wrong=0] / [metric:weapon_null/riot/nulls#weapon_refused=9] |
| INTER | [metric:weapon_null/held/inter#right=943] / [metric:weapon_null/held/inter#wrong=0] / [metric:weapon_null/held/inter#refused=9] | [metric:weapon_null/held/inter#loio_named=0] | [metric:weapon_null/dev/inter#loio_named=0] | [metric:weapon_null/riot/inter#weapon_right=531] / [metric:weapon_null/riot/inter#weapon_wrong=0] / [metric:weapon_null/riot/inter#weapon_refused=15] |

The held set is 952 frames whose label has a whitened reference. The
LOIO counts are out of the same frames.

- **NULL names what the IoU floor refuses.** It turns the 8 Riot entries refused as `new` into 6 right and 2 `registration_failed`. Five of the six are on 4f207c0c4e39: Paint Shells at 1759 s and 1765 s, and Showstopper twice at 888.5 s. The sixth is Nanoswarm on a06f04a0059f at 892.5 s. No session loses a match.
- **NULL cannot refuse an unseen icon.** Right crops' `d2` depends on the name. Wide icons cut to the canvas carry large residuals: the median is 24841 for Ares and 12841 for Marshal, against 375 for Classic and 420 for Vandal. So [metric:weapon_null/dev/thresholds#tau=83820.6] lies far above every unseen icon's nearest `d2`, whose minimum is 23760 on dev (Classic) and 22536 on held (Classic).
- **Per-name scaling does not repair it.** Under NULLS a left-out Phantom wins as a wide name and passes that name's scale.
- **INTER is the safest gate.** It misnames no left-out icon. It refuses 9 held frames WIRED names right, and no Riot entry changes. It refuses Paint Shells, as WIRED does.
- **Paint Shells sits close to its own row.** Its registered frames at 1759 to 1767 s have `d2` near 1500 to 3000, with one at 16183. The next name is at 34000 or more.

## Next

A gate that takes INTER's name, or else a winner within a global radius
below the dev LOIO minimum, might keep both properties. The margin is thin
(16183 against 22536), and held is spent on this round. Test it on sessions
outside the probe. Alternatively, find why the IoU floor scores Paint
Shells at 0.41 to 0.50 against its game icon.
