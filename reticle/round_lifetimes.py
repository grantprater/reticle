"""Round-scoped observation lifetimes, pure over stored multi-view evidence.

One-to-one association never turns a missing read into death. Identity remains
provisional for anonymous agents; a unique feasible predecessor is continuity,
multiple predecessors are alternatives. Screen and minimap coordinate systems
never associate spatially with each other. Roster capacity permits acquisition,
not identification. First detection is never substituted for origin time.
"""
from __future__ import annotations

import math
from .track import CLASSES, admits, association_tolerance, assign

ROUND_LIFETIME_VERSION = "round-lifetimes-0.2.0"

#: Readable kind per family, when a reader does not supply a better one.
#: A raw `E0303 object?` says nothing a person can check against the frame.
NAME_KIND = {"self": "you", "ally": "ally", "enemy": "enemy",
             "barrier": "barrier", "spike": "spike", "object": "?",
             "outline": "outline?", "ally_outline": "ally shape?",
             "hud_ability": "tray"}

#: Kinds that are one thing or a fixed slot, so a number would be noise.
UNNUMBERED = ("you", "tray")


def readable_kind(obs):
    """What to call this observation in English. Readers may override."""
    return obs.get("kind") or NAME_KIND.get(obs["family"], obs["family"])


class RoundLifetimes:
    def __init__(self, round_id, start_ms, scale=1.0):
        self.round_id, self.start_ms, self.scale = round_id, start_ms, scale
        self.entities = {}
        self.last_t = None
        self.next_id = 1
        self.name_counts = {}

    def step(self, t_ms, observations, *, source_state="fresh", roster=None):
        if not math.isfinite(t_ms) or (self.last_t is not None and t_ms <= self.last_t):
            raise ValueError("timestamps must be finite and strictly increasing")
        self.last_t = t_ms
        if source_state != "fresh":
            return []
        if any(o.get("observed_t_ms", t_ms) != t_ms for o in observations):
            raise ValueError("carried positions are not new observations")
        prior = [e for e in self.entities.values()
                 if t_ms-e["last_seen_ms"] <= 1000 or e["family"] == "self"
                 or (e["family"] in {"ally","enemy"} and e.get("appearance"))]
        costs, candidates = [], []
        for obs in observations:
            row, parents = [], []
            for ent in prior:
                old = ent["last_observation"]
                dt = (t_ms - ent["last_seen_ms"]) / 1000
                compatible = (obs["view"] == old["view"] and
                              obs["family"] == old["family"])
                d = math.hypot(obs["x"]-old["x"], obs["y"]-old["y"])
                if obs["family"] == "self" and compatible:
                    # The yellow observer icon is unique, not a named agent.
                    allowed = True
                elif obs["view"] == "world":
                    # Screen-space motion includes camera rotation. This is an
                    # association limit, not the minimap's world motion law.
                    allowed = dt <= .3 and d <= max(30, old["box"][2]*.5)
                else:
                    moving = obs["family"] in {"ally", "enemy"}
                    budget = .75 if moving else 1.0
                    motion = CLASSES["walker" if moving else "static"]
                    slack = association_tolerance(self.scale,
                                r_a=obs.get("r"), r_b=old.get("r"))
                    allowed = dt <= budget and admits(motion, max(0,d-slack),dt,self.scale)[0]
                    if moving and not allowed and obs.get("appearance") and ent.get("appearance"):
                        similarity=sum(min(a,b) for a,b in zip(obs["appearance"],ent["appearance"]))
                        # Provisional appearance re-acquisition; never a named
                        # identity claim. Alternatives remain in the output.
                        allowed=similarity >= .85 and admits(motion,max(0,d-slack),dt,self.scale)[0]
                if compatible and allowed:
                    parents.append(ent["id"])
                    row.append(d)
                else:
                    row.append(float("inf"))
            candidates.append(parents)
            costs.append(row)
        assignments = assign(costs)
        output = []
        accepted_allies = 0
        alive = None if roster is None else roster.get("alive_ally")
        # Only subtract an observed self. Spectated/absent self is unknown.
        has_self = any(o["family"] == "self" for o in observations)
        capacity = None if alive is None or not has_self else max(0,alive-1)
        for i, obs in enumerate(observations):
            j = assignments[i]
            parents = candidates[i]
            # Resolve a unique correspondence only. Hungarian ensures one-to-one,
            # but a cheap optimum alone does not prove identity in a crowd.
            unique = j >= 0 and len(parents) == 1 and sum(
                prior[j]["id"] in ps for ps in candidates) == 1
            if j >= 0:
                ent = prior[j]
                state = "continuation" if unique else "ambiguous_continuation"
            else:
                eid = f"{self.round_id}:E{self.next_id:04d}"
                self.next_id += 1
                # The name is fixed AT BIRTH and never revised, because its job
                # is to make a re-birth visible: a fifth `ally` in a 5v5, or a
                # `? 600`, is wrong on the face of the frame in a way that
                # `E0303 object?` is not. The class can still change under it,
                # and `class_history` keeps that.
                kind = readable_kind(obs)
                if kind.startswith(UNNUMBERED):
                    name = kind
                else:
                    self.name_counts[kind] = self.name_counts.get(kind, 0) + 1
                    name = f"{kind} {self.name_counts[kind]}"
                ent = {"id":eid, "name":name, "kind":kind,
                       "view":obs["view"], "family":obs["family"],
                       "first_seen_ms":t_ms, "origin_ms":None,
                       "origin_reason":"origin not independently observed",
                       "observations":0, "gaps":0, "max_gap_ms":0,
                       "class_history":[], "identity_status":"provisional"}
                self.entities[eid] = ent
                state = "ambiguous_continuation" if parents else "first_observed"
            gap = t_ms-ent.get("last_seen_ms",t_ms)
            if gap > 150:
                ent["gaps"] += 1
            ent["max_gap_ms"] = max(ent["max_gap_ms"],gap)
            ent["last_seen_ms"] = t_ms
            ent["last_observation"] = dict(obs)
            if obs.get("appearance"):
                old_appearance=ent.get("appearance",obs["appearance"])
                ent["appearance"]=[.9*a+.1*b for a,b in zip(old_appearance,obs["appearance"])]
            ent["observations"] += 1
            if obs["label"] not in ent["class_history"]:
                ent["class_history"].append(obs["label"])
            acquisition = None
            if obs["family"] == "ally":
                if capacity is None:
                    acquisition = "roster_unknown"
                elif accepted_allies < capacity:
                    acquisition = "roster_slot_available_not_identity"
                    accepted_allies += 1
                else:
                    acquisition = "roster_count_conflict"
            output.append({**obs, "entity_id":ent["id"], "name":ent["name"],
                           "state":state,
                           "alternatives":parents if not unique else [],
                           "acquisition":acquisition, "origin_ms":ent["origin_ms"],
                           "first_seen_ms":ent["first_seen_ms"]})
        return output

    def finish(self, end_ms):
        return [{**{k:v for k,v in e.items() if k != "last_observation"},
                 "end_ms":None, "right_censored_at_ms":end_ms,
                 "end_reason":"last observation does not establish destruction/death"}
                for e in self.entities.values()]


def replay_scale(meta, store_root=None):
    """The widget scale an export was adjudicated at.

    The association law is in WIDGET pixels, so replaying a 331 px capture at
    the 465 px scale silently returns a different set of entities. Exports made
    after `full-round-0.2.0` state it; older ones do not, and the answer is
    then DERIVED from the session's stored manifest and profile rather than
    assumed -- `scale=1.0` is right for every big-widget capture and wrong for
    every small one, which is the shape of a silent failure.
    """
    if "widget_scale" in meta:
        return float(meta["widget_scale"]), "provenance"
    from .minimap import minimap_roi_px, widget_scale
    from .profiles import get_profile
    from .store import Store
    import json
    root = Store().root if store_root is None else store_root
    manifest = json.loads((root / "manifests" / f"{meta['session']}.json")
                          .read_text(encoding="utf-8"))
    source = manifest["source"]
    box = minimap_roi_px(get_profile(manifest["source_profile"]),
                         source["width"], source["height"])
    return widget_scale(box[2] - box[0]), "derived from manifest"


def main(argv=None):
    """Replay association from stored observations, without decoding video."""
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    meta=json.loads((args.directory/'provenance.json').read_text(encoding='utf-8'))
    scale,source=replay_scale(meta)
    state=RoundLifetimes(f"{meta['session']}:R{meta['round']['round_no']}",
                         meta['from_ms'],scale)
    for line in (args.directory/'observations.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        state.step(row['t_ms'],row['observations'],source_state=row['source_state'],roster=row.get('roster'))
    with args.out.open('x',encoding='utf-8') as f:
        json.dump(state.finish(meta['to_ms']),f,indent=2)
    print(f"{len(state.entities)} entity hypotheses replayed without decoding, "
          f"at widget scale {scale:.4f} ({source})")


if __name__ == "__main__":
    main()
