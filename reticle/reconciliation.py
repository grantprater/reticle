"""Label-free disagreement localization over independent stored HUD channels.

Agreement is consistency, not detector accuracy. The score audit proposes
confirmed boundaries without changing stored rounds. The roster audit compares
CHANGES from an observed baseline; it never assumes a probe begins at 5v5.
"""
from bisect import bisect_left, bisect_right
from collections import Counter

from .checks import track_entries
from .roster import resolve
from .rounds import round_bounds

SCORE_CONFIRM_GAP_MS = 3000
ROSTER_JOIN_MS = 1000
ENTRY_ALIGNMENT_MS = 1000
AUDIT_WINDOW_MS = 10000


def confirmed_score_runs(t, left, right):
    """Runs of the same score, with missing reads bounded by a time limit."""
    runs = []
    for ts, a, b in zip(t, left, right):
        if a is None or b is None:
            continue
        if (runs and runs[-1]['score'] == (a, b)
                and ts - runs[-1]['last_ms'] <= SCORE_CONFIRM_GAP_MS):
            if runs[-1]['observations'] == 1:
                runs[-1]['confirmed_ms'] = ts
            runs[-1]['last_ms'] = ts
            runs[-1]['observations'] += 1
        else:
            runs.append(dict(score=(a, b), first_ms=ts, last_ms=ts,
                             confirmed_ms=None, observations=1))
    return runs


def audit_scoreline(hud):
    h = hud.to_pydict()
    t, left, right = h['t_ms'], h['score_left'], h['score_right']
    original = round_bounds(t, left, right, h.get('clock_ms'))
    runs = confirmed_score_runs(t, left, right)
    stable = [r for r in runs if r['observations'] >= 2]
    proposed, anomalies = [], []
    previous = None
    for r in stable:
        if previous is not None and r['score'] != previous['score']:
            a, b = r['score']
            pa, pb = previous['score']
            if a >= pa and b >= pb and a+b == pa+pb+1:
                proposed.append(dict(t_ms=r['first_ms'], confirmed_ms=r['confirmed_ms'],
                                     before=(pa, pb), after=(a, b), won_left=a == pa+1))
            else:
                anomalies.append(dict(t_ms=r['first_ms'], before=(pa,pb), after=(a,b),
                                      reason='confirmed_score_jump_or_reversal'))
        previous = r
    proposed_times = {r['t_ms'] for r in proposed}
    old_times = {r['t_end_ms'] for r in original}
    return dict(raw_boundaries=len(original), confirmed_boundaries=len(proposed),
                unsupported_raw_boundaries=[r for r in original if r['t_end_ms'] not in proposed_times],
                additional_confirmed_boundaries=[r for r in proposed if r['t_ms'] not in old_times],
                score_anomalies=anomalies,
                single_read_runs=sum(r['observations'] == 1 for r in runs),
                proposed=proposed)


def audit_roster_deltas(hud, roster):
    """Nonoverlapping 10s windows, actual baseline, explicit timing tolerance.

    A count rise is flagged as revive/reset/read-error ambiguity, never forced
    monotone. Zero/zero is ambiguous, not declared impossible. Nulls or gaps
    inside a window prevent it from being counted as an agreement.
    """
    if roster is None:
        return dict(status='missing_roster', windows=[], counts={})
    h, v = hud.to_pydict(), dict(roster.to_pydict())
    # Adjudicate from the stored detail with the HUD gate, rather than trusting
    # the ungated counts the reader had to store: a WIPED team reads None
    # without it, and a wipe is exactly the window this audit most wants.
    v['alive_ally'], v['alive_enemy'] = resolve(hud, roster)
    rt = v['t_ms']
    rounds = round_bounds(h['t_ms'], h['score_left'], h['score_right'], h.get('clock_ms'))
    entry_times = [e['t_first'] for e in track_entries(
        h['t_ms'], h['kf_entry_mask'], h.get('kf_entry_wx')) if e['counted']]
    counts, windows = Counter(), []
    counts['zero_zero_rows'] = sum(a == 0 and b == 0 for a,b in
                                  zip(v['alive_ally'], v['alive_enemy']))
    for number, r in enumerate(rounds, 1):
        start, end = r['t_start_ms'], r['t_end_ms']
        # First score interval can contain the entire pre-match menu.
        if number == 1:
            continue
        a = start + AUDIT_WINDOW_MS
        while a + AUDIT_WINDOW_MS < end - SCORE_CONFIRM_GAP_MS:
            z = a + AUDIT_WINDOW_MS
            i, j = bisect_right(rt, a)-1, bisect_right(rt, z)-1
            record = dict(round_no=number, start_ms=a, end_ms=z)
            reason = None
            if i < 0 or j <= i or a-rt[i] > ROSTER_JOIN_MS or z-rt[j] > ROSTER_JOIN_MS:
                reason = 'missing_endpoints'
            else:
                # Equal counts do not corroborate a killfeed that was never
                # sampled here. Both channels must cover the same interval.
                ht = h['t_ms']
                u, w = bisect_right(ht, rt[i])-1, bisect_left(ht, rt[j])
                hud_covered = (u >= 0 and w < len(ht)
                               and rt[i]-ht[u] <= ROSTER_JOIN_MS
                               and ht[w]-rt[j] <= ROSTER_JOIN_MS
                               and all(y-x <= ROSTER_JOIN_MS
                                       for x,y in zip(ht[u:w],ht[u+1:w+1]))
                               and all(x is not None for x in h['kf_entry_mask'][u:w+1]))
                rows = list(zip(v['alive_ally'][i:j+1], v['alive_enemy'][i:j+1]))
                if not hud_covered:
                    reason = 'hud_gap_or_unreadable'
                elif any(x is None or y is None for x,y in rows):
                    reason = 'unreadable_roster'
                elif any(x == 0 and y == 0 for x,y in rows):
                    reason = 'zero_zero_ambiguous'
                elif any(b-a > ROSTER_JOIN_MS for a,b in zip(rt[i:j], rt[i+1:j+1])):
                    reason = 'roster_gap'
                elif any(x2>x1 or y2>y1 for (x1,y1),(x2,y2) in zip(rows,rows[1:])):
                    reason = 'count_increase_requires_explanation'
                else:
                    drop = sum(rows[0])-sum(rows[-1])
                    lo, hi = rt[i], rt[j]
                    deaths = bisect_right(entry_times,hi)-bisect_right(entry_times,lo)
                    certain = max(0,bisect_left(entry_times,hi-ENTRY_ALIGNMENT_MS)
                                  - bisect_right(entry_times,lo+ENTRY_ALIGNMENT_MS))
                    possible = bisect_right(entry_times,hi+ENTRY_ALIGNMENT_MS)-bisect_left(
                        entry_times,lo-ENTRY_ALIGNMENT_MS)
                    reason = ('agree' if deaths == drop else 'timing_ambiguous'
                              if certain <= drop <= possible else 'disagreement')
                    record.update(observed_start=rows[0], observed_end=rows[-1],
                                  roster_drop=drop, killfeed_entries=deaths,
                                  possible_entries=[certain,possible],
                                  observed_start_ms=lo, observed_end_ms=hi)
            record['status'] = reason
            counts[reason] += 1
            windows.append(record)
            a = z
    cancellations = []
    for prev, cur in zip(windows, windows[1:]):
        if (prev['status'] == cur['status'] == 'disagreement'
                and prev['round_no'] == cur['round_no']
                and prev['observed_end_ms'] == cur['observed_start_ms']
                and prev['killfeed_entries'] + cur['killfeed_entries']
                == prev['roster_drop'] + cur['roster_drop']):
            cancellations.append(dict(start_ms=prev['observed_start_ms'],
                                      end_ms=cur['observed_end_ms'],
                                      reason='adjacent_residuals_cancel_check_onset_timing'))
    return dict(status='consistency_audit_not_accuracy', counts=dict(counts),
                windows=windows, adjacent_cancellations=cancellations)

#: Below this many counted tracks the median entry lifetime is a description of
#: one entry rather than a measurement, so `over_long` refuses to answer.
MIN_TRACKS_FOR_LIFETIME = 5
#: Consecutive HUD samples closer than this may belong to one frozen run.
FREEZE_GAP_MS = 1500
#: A frozen run shorter than this is not evidence of anything -- the clock
#: ticks once a second, so ~1.5 s of identical reads happens whenever the clock
#: is briefly unreadable. 5 s is past every ordinary cause measured.
FREEZE_MIN_MS = 5000
#: Columns whose simultaneous equality means the FRAME did not change.
#: `confidence` is the load-bearing one: it is a continuous float from the glyph
#: match, so bit-equality across many samples is not a coincidence.
FREEZE_COLS = ('clock_ms', 'score_left', 'score_right', 'hp', 'shield',
               'ammo_mag', 'ammo_reserve', 'confidence', 'n_glyphs',
               'kf_entry_mask')


def frozen_runs(hud, min_ms: float = FREEZE_MIN_MS):
    """Intervals where every stored HUD column is identical sample to sample.

    A round-end screen, a death screen and a paused capture all read this way,
    and NOTHING in the pipeline currently marks them -- so they are counted as
    ordinary play. Detected with no threshold at all beyond a duration floor:
    either the reads are equal or they are not.

    **Do not read this as a round-boundary detector; it was measured and it is
    not one.** Over 18 sessions only 8% of derived round starts fall inside a
    run of >= 5 s, and the median run sits 25 s from the nearest one. What it
    does say is that 2.8% of derived in-round time is a frame that never
    changed, which is a coaching-state eligibility question rather than a
    timing one.
    """
    h = hud.to_pydict() if hasattr(hud, 'to_pydict') else hud
    t = h['t_ms']
    key = list(zip(*[h[c] for c in FREEZE_COLS]))
    out, i = [], 0
    while i < len(key):
        j = i
        while (j + 1 < len(key) and key[j + 1] == key[i]
               and t[j + 1] - t[j] <= FREEZE_GAP_MS):
            j += 1
        if t[j] - t[i] >= min_ms:
            out.append(dict(start_ms=t[i], end_ms=t[j], samples=j - i + 1))
        i = j + 1
    return out


def killfeed_health(hud):
    """Diagnostics on the entry TRACKER, from stored L1 and nothing else.

    Every unresolved window in `analysis/reconciliation.json` was inspected by
    rendering on 2026-09-07 and NOT ONE was a roster error. Three were the
    documented Run It Back divergence, three were tracker defects and one was a
    late onset. These are the two tracker signatures that were confirmed by eye,
    reported so the next session does not re-diagnose them:

        no_divider    a COUNTED track no observation of which ever showed a
                      name either side of the weapon icon. Confirmed spurious
                      once (587c15b07779 1472.5-1474.0s: two isolated scenery
                      detections 1.5 s apart, linked across a gap of no
                      detections at all). 61 of 2859 counted tracks corpus-wide.
                      NOT proof: an occluded killer name looks the same.
        over_long     a counted track lasting far beyond the entry lifetime.
                      That lifetime is a hard constant -- median 10 samples and
                      4.5 s on every one of 18 sessions -- and CLAUDE.md records
                      long tracks as eliminated by the divider test, which is
                      FALSE: 154 counted tracks exceed 12 samples and 83 exceed
                      16, to a maximum of 38.

    **`over_long` is NOT a merge detector, and assuming it was is a mistake
    already made here.** One over-long track was confirmed to be a real merge
    (587c15b07779 775.5s, 19 samples, swallowing a visible `Phoenix -> Fade`
    entry at 781.0s). The very next one tested -- the corpus maximum, 38 samples
    on 59c70f1ef720 at 2197-2215s -- is a single genuine entry on a FROZEN
    frame, and every HUD column there is identical for 17 s. So the two
    populations overlap and `frozen_runs` is what separates them; neither count
    is a defect rate on its own.
    """
    h = hud.to_pydict() if hasattr(hud, 'to_pydict') else hud
    ev = [e for e in track_entries(h['t_ms'], h['kf_entry_mask'],
                                   h.get('kf_entry_wx')) if e['counted']]
    if not ev:
        return dict(counted=0)
    obs = sorted(e['n_obs'] for e in ev)
    med = obs[len(obs) // 2]
    frozen = frozen_runs(hud)
    # The lifetime is measured from the session's OWN tracks, so it needs
    # enough of them to be a median rather than a description of one entry.
    # Below this, say so instead of reporting a bound as a finding.
    if len(ev) < MIN_TRACKS_FOR_LIFETIME:
        return dict(counted=len(ev), median_samples=med,
                    over_long='unknown_too_few_tracks',
                    no_divider=[dict(t_first=e['t_first'], t_last=e['t_last'],
                                     n_obs=e['n_obs'], slot=e['slot'])
                                for e in ev if e['sig'] is None],
                    frozen_runs=len(frozen),
                    frozen_seconds=round(sum(f['end_ms'] - f['start_ms']
                                             for f in frozen) / 1000.0, 1))
    def in_freeze(e):
        """Was MOST of this track's life a frame that never changed?

        Overlap, not containment: a track brackets the freeze it sits in,
        because the entry is detected on the last moving frame before and the
        first after. The corpus's longest track (59c70f1ef720, 2197.0-2215.5s)
        overhangs its frozen run at both ends by one sample and strict
        containment scored it 0.
        """
        span = e['t_last'] - e['t_first']
        if span <= 0:
            return False
        cover = sum(max(0.0, min(e['t_last'], f['end_ms'])
                        - max(e['t_first'], f['start_ms'])) for f in frozen)
        return cover / span >= 0.5
    long_ = [e for e in ev if e['n_obs'] > med + 6]
    return dict(
        counted=len(ev), median_samples=med,
        no_divider=[dict(t_first=e['t_first'], t_last=e['t_last'],
                         n_obs=e['n_obs'], slot=e['slot'])
                    for e in ev if e['sig'] is None],
        over_long=[dict(t_first=e['t_first'], t_last=e['t_last'],
                        n_obs=e['n_obs'], inside_frozen_frame=in_freeze(e))
                   for e in long_],
        over_long_inside_frozen=sum(in_freeze(e) for e in long_),
        frozen_runs=len(frozen),
        frozen_seconds=round(sum(f['end_ms'] - f['start_ms']
                                 for f in frozen) / 1000.0, 1))
