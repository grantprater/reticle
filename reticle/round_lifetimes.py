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
from .minimap import REF_WIDGET_W

ROUND_LIFETIME_VERSION = "round-lifetimes-0.6.0"
MAX_ASSOCIATION_HISTORIES = 64

#: Readable kind per family, when a reader does not supply a better one.
#: A raw `E0303 object?` says nothing a person can check against the frame.
NAME_KIND = {"self": "you", "ally": "ally", "enemy": "enemy",
             "barrier": "barrier", "spike": "spike", "object": "?",
             "outline": "outline?", "ally_outline": "ally shape?",
             "hud_ability": "tray"}

#: Kinds that are one thing or a fixed slot, so a number would be noise.
UNNUMBERED = ("you", "tray")

#: How far the best appearance match must beat the runner-up before it may
#: re-acquire an agent across a gap. **A margin, because an absolute bar
#: cannot work here and the old `>= 0.85` was above the signal itself.**
#: Measured on Sunset R6's 2,304 stored ally appearance vectors:
#:
#:     same ally, 0.1 s apart      median 0.708   p05 0.478
#:     different allies, one frame median 0.213   p95 0.556
#:
#: The two overlap, so no threshold on the score separates them -- but ranked
#: against the alternatives in the frame, appearance picks the same icon
#: position-truth does in **97.9% of 1,748 unambiguous pairs**, with a margin
#: of 0.383 when right against 0.037 when wrong. At 0.15 that keeps 91.9% of
#: the correct links and admits 2.7% of the wrong ones.
APPEARANCE_MARGIN = 0.15


def _intersect(a, b):
    """Histogram intersection, the score `composition` vectors are compared by."""
    return sum(min(x, y) for x, y in zip(a, b))


def readable_kind(obs):
    """What to call this observation in English. Readers may override."""
    return obs.get("kind") or NAME_KIND.get(obs["family"], obs["family"])


def known_kind(obs):
    """Only an explicit, resolved reader kind constrains correspondence."""
    kind = obs.get("kind")
    return kind if kind and "?" not in kind else None


class RoundLifetimes:
    def __init__(self, round_id, start_ms, scale=1.0):
        self.round_id, self.start_ms, self.scale = round_id, start_ms, scale
        self.entities = {}
        self.last_t = None
        self.next_id = 1
        self.name_counts = {}
        self.next_observation = 1
        self.next_component = 1
        self.association_components = {}
        self.association_revisions = []
        # Conservative width-based horizon, not the ROI's actual diagonal:
        # the reference crop is taller than wide (465 x 485). Using width on
        # both axes expires appearance-only links slightly before walking can
        # reach every point in that crop. Scale cancels against walking speed.
        # Appearance is not an independent identity witness.
        self.appearance_gap_s = math.sqrt(2) * REF_WIDGET_W / CLASSES["walker"].max_px_s

    def step(self, t_ms, observations, *, source_state="fresh", roster=None,
             association_evidence=()):
        if not math.isfinite(t_ms) or (self.last_t is not None and t_ms <= self.last_t):
            raise ValueError("timestamps must be finite and strictly increasing")
        self.last_t = t_ms
        for claim in association_evidence:
            self.resolve_association(
                claim["observation_id"], claim["entity_id"],
                claim.get("evidence_ref"), claim.get("available_t_ms", t_ms))
        if source_state != "fresh":
            return []
        if any(o.get("observed_t_ms", t_ms) != t_ms for o in observations):
            raise ValueError("carried positions are not new observations")
        prior = [e for e in self.entities.values()
                 if t_ms-e["last_seen_ms"] <= 1000 or e["family"] == "self"
                 or (e["family"] in {"ally","enemy"} and e.get("appearance")
                     and t_ms-e["last_seen_ms"] < self.appearance_gap_s*1000)]
        # **Appearance is scored COMPARATIVELY, once per observation.** It is a
        # ranking witness, not a measurement: the question it can answer is
        # *which of these entities is this icon*, never *is this icon that
        # entity*. Ranking it here also keeps it out of the per-pair loop.
        best = {}
        for i, obs in enumerate(observations):
            if obs["family"] not in {"ally", "enemy"} or not obs.get("appearance"):
                continue
            scored = sorted(
                ((_intersect(obs["appearance"], e["appearance"]), e["id"])
                 for e in prior
                 if e["family"] == obs["family"] and e["view"] == obs["view"]
                 and e.get("appearance")), reverse=True)
            if scored:
                runner = scored[1][0] if len(scored) > 1 else 0.0
                best[i] = (scored[0][1], scored[0][0] - runner)
        costs, candidates = [], []
        for i, obs in enumerate(observations):
            row, parents = [], []
            for ent in prior:
                old = ent["last_observation"]
                dt = (t_ms - ent["last_seen_ms"]) / 1000
                compatible = (obs["view"] == old["view"] and
                              obs["family"] == old["family"])
                if known_kind(obs) and ent.get("known_kind"):
                    compatible = compatible and known_kind(obs) == ent["known_kind"]
                d = math.hypot(obs["x"]-old["x"], obs["y"]-old["y"])
                if obs["family"] == "self" and compatible:
                    allowed = True
                elif obs["view"] == "world":
                    allowed = dt <= .3 and d <= max(30, old["box"][2]*.5)
                else:
                    moving = obs["family"] in {"ally", "enemy"}
                    budget = .75 if moving else 1.0
                    motion = CLASSES["walker" if moving else "static"]
                    slack = association_tolerance(self.scale,
                                r_a=obs.get("r"), r_b=old.get("r"))
                    allowed = dt <= budget and admits(motion, max(0,d-slack),dt,self.scale)[0]
                    if moving and not allowed and i in best:
                        winner, margin = best[i]
                        informative = motion.max_px_s*self.scale*dt + slack < math.sqrt(2)*REF_WIDGET_W*self.scale
                        allowed = (informative and ent["id"] == winner
                                   and margin >= APPEARANCE_MARGIN
                                   and admits(motion,max(0,d-slack),dt,self.scale)[0])
                    if not moving and allowed:
                        anchor = ent["anchor_observation"]
                        anchor_d = math.hypot(obs["x"]-anchor["x"], obs["y"]-anchor["y"])
                        anchor_slack = association_tolerance(self.scale,
                            r_a=obs.get("r"), r_b=anchor.get("r"))
                        allowed = admits(motion, max(0,anchor_d-anchor_slack),dt,self.scale)[0]
                if compatible and allowed:
                    parents.append(ent["id"])
                    row.append(d)
                else:
                    row.append(float("inf"))
            candidates.append(parents)
            costs.append(row)
        assignments = assign(costs)
        output = []
        alive = None if roster is None else roster.get("alive_ally")
        # Only subtract an observed self. Spectated/absent self is unknown.
        has_self = any(o["family"] == "self" for o in observations)
        capacity = None if alive is None or not has_self else max(0,alive-1)
        accepted_allies = self._fill_roster(observations, assignments, prior,
                                            candidates, capacity)
        observation_ids = []
        for _ in observations:
            observation_ids.append(f"{self.round_id}:O{self.next_observation:06d}")
            self.next_observation += 1
        component_for = self._record_ambiguous_components(
            observation_ids, assignments, prior, candidates)
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
                ent["anchor_observation"] = {k:obs[k] for k in ("x", "y", "r") if k in obs}
                self.entities[eid] = ent
                state = "ambiguous_continuation" if parents else "first_observed"
            gap = t_ms-ent.get("last_seen_ms",t_ms)
            if gap > 150:
                ent["gaps"] += 1
            ent["max_gap_ms"] = max(ent["max_gap_ms"],gap)
            ent["last_seen_ms"] = t_ms
            # The fast track remains a proposal used to generate the next
            # candidates. The association component, not this field, is the
            # authoritative identity account and can revise the proposal later.
            ent["last_observation"] = dict(obs)
            if unique or j < 0:
                if known_kind(obs):
                    ent["known_kind"] = known_kind(obs)
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
                elif i in accepted_allies:
                    acquisition = "roster_slot_available_not_identity"
                else:
                    acquisition = "roster_count_conflict"
            output.append({**obs, "entity_id":ent["id"], "name":ent["name"],
                           "provisional_entity_id": ent["id"],
                           "observation_id": observation_ids[i],
                           "state":state,
                           "alternatives":parents if not unique else [],
                           "identity_status": ("resolved" if unique else
                                               "ambiguous" if parents else "provisional"),
                           "association_component_id": component_for.get(i),
                           "acquisition":acquisition, "origin_ms":ent["origin_ms"],
                           "first_seen_ms":ent["first_seen_ms"]})
        return output

    def association_report(self):
        """Serializable retained histories and later evidence revisions."""
        all_components = list(self.association_components.values())
        components = [c for c in all_components if not c.get("superseded_by")]
        return {
            "producer_version": ROUND_LIFETIME_VERSION,
            "round_id": self.round_id,
            "components": components,
            "revisions": list(self.association_revisions),
            "summary": {
                "components": len(components),
                "ambiguous": sum(c["status"] == "ambiguous" for c in components),
                "resolved": sum(c["status"] == "resolved" for c in components),
                "conflicted": sum(c["status"] == "conflicted" for c in components),
                "incomplete_search": sum(not c["search_complete"] for c in components),
                "retained_histories": sum(len(c["hypotheses"]) for c in components),
                "superseded_components": sum(bool(c.get("superseded_by"))
                                             for c in all_components),
            },
        }

    def _record_ambiguous_components(self, observation_ids, assignments, prior,
                                     candidates):
        """Keep bounded one-to-one histories for each connected ambiguity."""
        ambiguous = [i for i, parents in enumerate(candidates)
                     if parents and not (assignments[i] >= 0 and len(parents) == 1
                     and sum(prior[assignments[i]]["id"] in ps
                             for ps in candidates) == 1)]
        groups = []
        remaining = set(ambiguous)
        while remaining:
            group, frontier = set(), {remaining.pop()}
            while frontier:
                i = frontier.pop()
                group.add(i)
                linked = {j for j in remaining
                          if set(candidates[i]).intersection(candidates[j])}
                remaining.difference_update(linked)
                frontier.update(linked)
            groups.append(sorted(group))

        result = {}
        for group in groups:
            hypotheses = []
            truncated = [False]

            def visit(at, used, mapping):
                if len(hypotheses) >= MAX_ASSOCIATION_HISTORIES:
                    truncated[0] = True
                    return
                if at == len(group):
                    hypotheses.append({"assignments": dict(mapping)})
                    return
                i = group[at]
                for entity_id in sorted(candidates[i]):
                    if entity_id in used:
                        continue
                    mapping[observation_ids[i]] = entity_id
                    visit(at + 1, used | {entity_id}, mapping)
                    mapping.pop(observation_ids[i])

            visit(0, set(), {})
            local_observations = [observation_ids[i] for i in group]
            local_entities = sorted(set().union(*(set(candidates[i]) for i in group)))
            local_membership = {
                observation_ids[i]: ([[entity_id] for entity_id in sorted(candidates[i])]
                                     + ([sorted(candidates[i])]
                                        if len(candidates[i]) > 1 else []))
                for i in group}
            related = [c for c in self.association_components.values()
                       if not c.get("superseded_by") and c["status"] in {"ambiguous", "partial"}
                       and set(c["entity_ids"]).intersection(local_entities)]
            if related:
                related.sort(key=lambda c: c["component_id"])
                component = related[0]
                combined = [{"assignments": {}}]
                combination_truncated = False
                for source_hypotheses in ([c["hypotheses"] for c in related] + [hypotheses]):
                    expanded = []
                    for left in combined:
                        for right in source_hypotheses:
                            if len(expanded) >= MAX_ASSOCIATION_HISTORIES:
                                combination_truncated = True
                                break
                            expanded.append({"assignments": {
                                **left["assignments"], **right["assignments"]}})
                        if combination_truncated:
                            break
                    combined = expanded
                component["observation_ids"] = sorted(set().union(
                    *(set(c["observation_ids"]) for c in related), local_observations))
                component["entity_ids"] = sorted(set().union(
                    *(set(c["entity_ids"]) for c in related), local_entities))
                component["membership_alternatives"] = {
                    **{key: value for c in related
                       for key, value in c["membership_alternatives"].items()},
                    **local_membership,
                }
                component["hypotheses"] = combined
                component["search_complete"] = (
                    all(c["search_complete"] for c in related)
                    and not truncated[0] and not combination_truncated)
                component["evidence"] = [item for c in related for item in c["evidence"]]
                for old in related[1:]:
                    old["superseded_by"] = component["component_id"]
                    old["status"] = "superseded"
                component_id = component["component_id"]
            else:
                component_id = f"{self.round_id}:A{self.next_component:04d}"
                self.next_component += 1
                component = {
                    "component_id": component_id,
                    "observation_ids": local_observations,
                    "entity_ids": local_entities,
                    "hypotheses": hypotheses,
                    # A single rendered blob can contain several icons. Singleton
                    # assignments are histories; set membership remains explicit.
                    "membership_alternatives": local_membership,
                    "search_complete": not truncated[0],
                    "evidence": [],
                }
                self.association_components[component_id] = component
            component["status"] = ("conflicted" if not component["hypotheses"] else
                                   "resolved" if len(component["hypotheses"]) == 1
                                   and component["search_complete"] else
                                   "ambiguous" if component["search_complete"] else "partial")
            for i in group:
                result[i] = component_id
        return result

    def association_for(self, observation_id):
        """Current projection for one observation across retained histories."""
        components = [c for c in self.association_components.values()
                      if not c.get("superseded_by")
                      and observation_id in c["observation_ids"]]
        if len(components) != 1:
            return None
        component = components[0]
        choices = sorted({h["assignments"].get(observation_id)
                          for h in component["hypotheses"]
                          if h["assignments"].get(observation_id) is not None})
        resolved = len(choices) == 1 and component["search_complete"]
        return {"observation_id": observation_id,
                "component_id": component["component_id"],
                "status": ("conflicted" if not choices else
                           "resolved" if resolved else
                           "ambiguous" if component["search_complete"] else "partial"),
                "entity_id": choices[0] if resolved else None,
                "alternatives": choices,
                "membership_alternatives": component["membership_alternatives"][observation_id],
                "search_complete": component["search_complete"]}

    def resolve_association(self, observation_id, entity_id, evidence_ref=None,
                            available_t_ms=None):
        """Apply later evidence without rewriting the original observation."""
        projection = self.association_for(observation_id)
        if projection is None:
            raise ValueError(f"unknown ambiguous observation {observation_id}")
        component = self.association_components[projection["component_id"]]
        kept = [h for h in component["hypotheses"]
                if h["assignments"].get(observation_id) == entity_id]
        if not kept:
            raise ValueError("association evidence conflicts with every retained history")
        component["hypotheses"] = kept
        component["status"] = ("resolved" if len(kept) == 1
                               and component["search_complete"] else
                               "ambiguous" if component["search_complete"] else "partial")
        evidence = {"observation_id": observation_id, "entity_id": entity_id,
                    "evidence_ref": evidence_ref,
                    "available_t_ms": available_t_ms}
        component["evidence"].append(evidence)
        self.association_revisions.append({**evidence,
                                           "component_id": component["component_id"],
                                           "remaining_histories": len(kept)})
        return self.association_for(observation_id)

    def _fill_roster(self, observations, assignments, prior, candidates,
                     capacity):
        """Which ally observations the roster has room for, WEAKEST LAST.

        The count is the whole of what the roster licenses -- it says how many
        teammates are alive, never which icon is which -- so when more ally
        icons are read than there are living teammates, something must carry
        the conflict. Which one is not arbitrary, and it used to be: the flag
        went to whichever ally the observation list reached fifth, so the box
        the overlay painted as suspect was chosen by iteration order.

        Ranked by the strength of the CORRESPONDENCE CLAIM, which is the only
        evidence in scope here: a resolved continuation of an established
        entity outranks an ambiguous one, which outranks an icon seen for the
        first time; ties go to the entity with more observations behind it,
        then to the older id so a replay is deterministic. It does not refuse
        anything and it does not touch identity -- an overflowing ally is
        still emitted, still named, still counted, and now the mark lands on
        the weakest claim in the frame.

        The obvious cross-reference does NOT work and that is worth writing
        down: over the 103 Sunset R6 samples carrying a conflict, the flagged
        ally's `lit_share` ran a median 0.707 against 0.761 for the accepted
        ones, so the light beside an icon does not separate the extra
        teammate. It separates a phantom from a real icon; it does not rank
        four real icons against five.
        """
        if capacity is None:
            return set()
        ranked = []
        for i, obs in enumerate(observations):
            if obs["family"] != "ally":
                continue
            j = assignments[i]
            parents = candidates[i]
            if j >= 0:
                ent = prior[j]
                unique = len(parents) == 1 and sum(
                    ent["id"] in ps for ps in candidates) == 1
                rank = 0 if unique else 1
                seen = ent["observations"]
            else:
                rank, seen = 2, 0
            ranked.append((rank, -seen, i))
        ranked.sort()
        return {i for _, _, i in ranked[:capacity]}

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
    parser.add_argument('--associations-out',type=Path)
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
    if args.associations_out:
        with args.associations_out.open('x', encoding='utf-8') as f:
            json.dump(state.association_report(), f, indent=2)
    print(f"{len(state.entities)} entity hypotheses replayed without decoding, "
          f"at widget scale {scale:.4f} ({source})")
    if args.associations_out:
        summary = state.association_report()["summary"]
        print(f"{summary['components']} association components, "
              f"{summary['retained_histories']} retained histories: {args.associations_out}")


if __name__ == "__main__":
    main()
