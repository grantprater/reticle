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
    original = round_bounds(t, left, right)
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
    rounds = round_bounds(h['t_ms'], h['score_left'], h['score_right'])
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
