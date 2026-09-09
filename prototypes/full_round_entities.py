"""Full-round multi-view evidence and annotated video.

Run --select SESSION... to rank complete stored rounds by capture stalls.
Run SESSION --round N --out NEW_DIRECTORY to render a selected round.
Uses existing prototype readers, rather than copying their recognition rules.
Unknown glyphs and screen outlines remain candidates. The right panel reports
coverage; a full-duration render is not a claim of complete class recognition.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))
from reticle import barriers, cone, geometry, lighting, lineup, screen, stalls
from reticle.minimap import (ally_icons, self_icons, floor_mask, slab_mask,
                             minimap_roi_px, widget_drawn, widget_scale, ally_mask)
from reticle.ocr import Templates, read_scoreline, crop_gray, scoreline_roi
from reticle.roster import alive_counts
from reticle.profiles import get_profile
from reticle.rounds import build_rounds
from reticle.round_lifetimes import RoundLifetimes, ROUND_LIFETIME_VERSION
from reticle.store import Store
from reticle.track import Tracker
from reticle.ping import sightings, classify as ping_class
from minimap_icons import red_mask                                 # noqa: E402
from minimap_ring_fit import find as enemy_rings, is_icon
#: `minimap_ring_fit.find`'s own default. Named here because `ring_supported`
#: must score the SAME red the fit was made from -- two saturation cuts for one
#: question is how a gate ends up judging pixels its detector never saw.
RING_SAT_MIN=100
from minimap_dynamic import detect as dynamic_objects
from ability_disc import find_discs
from plant_spike import centre_box, spike_cover, COVER_MIN
from minimap_portrait import composition
from ability_hud import slot_counts, SLOT_X0, SLOT_DX, SLOT_KEYS

VERSION = "full-round-0.10.0"
CONE_CHECK_VERSION = "cone-checks-0.2.0"
CONE_TINT = (235,180,80)          # the observable area, as `overlay.py` draws it
PALETTE = {"self":(90,235,250), "ally":(170,240,100), "enemy":(95,90,255),
           "barrier":(255,210,90), "object":(245,140,225),
           "outline":(90,170,255), "hud_ability":(240,190,130),
           "spike":(100,160,255)}


def serial(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def mask_runs(mask):
    """Lossless true runs [start, length] in row-major observation coordinates."""
    edges=np.flatnonzero(np.diff(np.r_[False,mask.ravel(),False].astype(np.int8)))
    return [[int(a),int(b-a)] for a,b in zip(edges[::2],edges[1::2])]


def round_candidates(store, sid):
    manifest = json.loads(store.manifest_path(sid).read_text())
    date = manifest["ingested_at"][:10]
    hud = store.read_hud(sid,date)
    if hud is None:
        raise SystemExit(f"Run reticle scan {sid} --only hud roster first")
    freeze = stalls.for_session(store,sid,date)
    rounds = build_rounds(hud)
    rows = hud.to_pylist()
    for i,r in enumerate(rounds):
        a,b = r["t_start_ms"],r["t_end_ms"]
        # Include the aftermath through the next buy reset, never the next round.
        end = rounds[i+1]["t_start_ms"] if i+1 < len(rounds) else b+5000
        end = min(end,manifest["source"]["duration_ms"])
        r["render_end_ms"] = end
        r["stalled_ms"] = None if freeze is None else sum(max(0,min(end,s["t_end_ms"])-max(a,s["t_start_ms"])) for s in freeze)
        active = [x for x in rows if a <= x["t_ms"] < b and x["clock_ms"] is not None and x["clock_ms"] >= 65000]
        r["live_start_ms"] = active[0]["t_ms"] if active else None
        r["complete"] = r["start_source"] == "clock_reset" and r["live_start_ms"] is not None and end > b
    return manifest, rounds, freeze


def observation(family,label,x,y,box,view="minimap",**extras):
    return {"family":family,"label":label,"x":float(x),"y":float(y),
            "box":[int(v) for v in box],"view":view,**extras}


class RoundReader:
    def __init__(self, manifest, selected, freeze, store):
        self.manifest,self.selected,self.freeze = manifest,selected,freeze
        src=manifest["source"]
        self.w,self.h=src["width"],src["height"]
        self.profile=get_profile(manifest["source_profile"])
        self.templates=Templates.load(self.profile.name)
        self.box=minimap_roi_px(self.profile,self.w,self.h)
        self.store_root=store.root
        self.geo_path=geometry.require(manifest["session_id"],store.root)
        with np.load(self.geo_path) as z:
            self.med=z["static"].copy()
            self.light=lighting.reference(z)
            self.lo=z["lo_gray"].copy()
            self.hi=z["hi_gray"].copy()
            # `sd_lo` is what keeps the location-name banner out of the map:
            # it is drawn 9 px above Sunset's body and BRIDGE swallowed it.
            self.sd=z["sd_lo"].copy()
            self.floor=floor_mask(self.med,sd=self.sd)
            self.slab=slab_mask(self.med,sd=self.sd)
            # SEARCH on the floor, which is the slab dilated by 9 px so an icon
            # at the map's edge is not clipped -- but REQUIRE support on the
            # slab, the opaque part. The margin is 20% of the floor and it lies
            # over the see-through widget, so a channel handed `floor` alone
            # leaks at roughly the margin's own area: measured over Sunset R6,
            # enemy 39.2% and raw pings 16.8% with no slab support, against
            # 0.8% for discs and 0.2% for dynamic, which are handed the slab.
            # That was a per-call-site decision and this is the one rule.
            self.support=self.slab
            self.passable=cone.passable_from(z["labels"],self.floor)
        self.gray=cv2.cvtColor(self.med,cv2.COLOR_BGR2GRAY).astype(float)
        if self.gray.shape != (self.box[3]-self.box[1],self.box[2]-self.box[0]):
            raise ValueError("geometry/profile dimensions disagree")
        self.scale=widget_scale(self.box[2]-self.box[0])
        self.self_track=Tracker("walker",scale=self.scale)
        self.ally_track=Tracker("walker",scale=self.scale)
        self.barrier_counts=np.zeros(self.gray.shape,np.uint16)
        self.buy_samples=0
        self.barriers=[]
        # Baked map state if this map has any. A round on an unbaked map is a
        # CALIBRATION round and reports no barriers, because the running 75%
        # rule cannot refuse anything until the buy phase has run: at sample
        # five a blob needs four hits to score 80%, which is how a handful of
        # real bars arrived as 57 entities. Render once to calibrate, bake with
        # `python -m reticle.barriers`, render again to observe.
        self.anchors=barriers.load(manifest["session_id"],store.root)
        self.cone_mask=None
        self.lit_mask=None
        # Identity, if this session has been read. The player's own agent is
        # the only one established -- the tray names it outright and the top
        # bar corroborates -- so it is the only one used. Ally ICONS are not
        # named: knowing WHO is on the team is not knowing which icon is which,
        # and `ally 3` stays honest until a per-icon witness exists.
        self.lineup=lineup.load_lineup(manifest["session_id"],store.root)
        self.player_agent=(self.lineup or {}).get("player",{}).get("agent")
        self.abilities=(lineup.abilities_for(self.player_agent,store.root)
                        if self.player_agent else {})

    def barrier_candidates(self,crop,t_ms):
        """Phase-conditioned persistent straight bars, retained as candidates.

        Anchors accumulate only during buy, never from live observations.
        Straightness distinguishes the painted bar from a portrait ring, but
        this is still a provisional map-state calibration, saved for inspection.
        """
        if t_ms >= self.selected["live_start_ms"]:
            return []
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        hu,sa,va=cv2.split(hsv)
        keyed=(((hu>65)&(hu<100))|((hu<10)|(hu>165)))&(sa>85)&(va>90)&self.support
        self.barrier_counts += keyed.astype(np.uint16)
        self.buy_samples += 1
        # With the map baked there is nothing to calibrate: the bar's position
        # is known, so the only question a frame answers is whether it is DRAWN.
        # ANY keyed pixel inside the anchor, not a fraction of it -- the same
        # rule the slab-support gate settled on, and for the same reason: the
        # key catches part of a bar and which part varies.
        if self.anchors:
            drawn=[]
            for i,a in enumerate(self.anchors["anchors"],1):
                x,y,w,h=a["box"]
                if not keyed[y:y+h,x:x+w].any():
                    continue
                drawn.append(observation("barrier","spawn barrier",a["x"],a["y"],
                             (x,y,w,h),kind="barrier",anchor=i,
                             evidence=["buy_phase","baked_map_anchor","team_colour_drawn"],
                             confidence="anchored"))
            self.barrier_candidates_calibration(keyed)
            return drawn
        if self.buy_samples < 5:
            return []
        stable=(self.barrier_counts >= self.buy_samples*.75).astype(np.uint8)
        n,lab,stats,centres=cv2.connectedComponentsWithStats(stable,8)
        out=[]
        for k in range(1,n):
            x,y,w,h,area=map(int,stats[k])
            if area < 12 or max(w,h)<7 or max(w,h)>130 or max(w,h)/max(1,min(w,h))<2.0 or area/(w*h)<.6:
                continue
            cx,cy=centres[k]
            out.append(observation("barrier","spawn barrier?",cx,cy,(x,y,w,h),kind="barrier",
                         evidence=["buy_phase","persistent_straight_team_colour"],
                         confidence="candidate",calibration_samples=self.buy_samples))
        # The calibration always runs, because it is what `reticle.barriers`
        # bakes FROM. What it does not do any more is speak.
        self.barriers=out
        return []

    def cone_checks(self,team,agg,per,lit):
        """Two crosschecks between the drawn LIGHT and the icons we found.

        FIRST DRAFT. Both directions are recorded per frame and neither gates
        anything yet -- the point is to get the residual on disk so it can be
        scored before it is trusted.

        **Residual light: lit floor no known cone explains.** The widget draws
        an ally's cone whether or not this pipeline found that ally, so lit
        floor outside every cone we cast is evidence of an emitter we are
        MISSING -- which is the one signal that could speak to ally
        fragmentation, because a fragmented ally leaves its light behind. The
        largest residual component's centroid is reported as a position HINT,
        not a detection: a cone's apex is at its narrow end and a centroid is
        not an apex, so this bounds where to look rather than saying where it is.

        **Unlit cone: an icon whose cone lands on dark floor.** The converse,
        and the cheaper one. `resolve_lobe` already picks the better of two
        lobes, but it never asks whether the WINNER is any good -- a phantom
        icon has no light on either side and still gets a bearing. `lit_share`
        near zero says the icon is claiming a view nothing corroborates.
        """
        if lit is None or agg is None:
            return None
        known=self.light.known & self.floor
        floor_lit=lit & known
        residual=floor_lit & ~agg
        out={"version":CONE_CHECK_VERSION,
             "comparison":"lighting consistency, not accuracy",
             "known_floor_px":int(known.sum()),
             "lit_floor_px":int(floor_lit.sum()),
             "residual_px":int(residual.sum()),
             "residual_frac":float(residual.sum())/int(floor_lit.sum()) if floor_lit.any() else None,
             "aggregate":cone.compare_evidence(agg,lit,known),
             "per_emitter":[]}
        for o,m in zip(team,per):
            ix,iy=round(o["x"]),round(o["y"])
            origin_ok=bool(self.passable[iy,ix])
            out["per_emitter"].append({
                "name_hint":o["kind"],"x":round(o["x"],1),"y":round(o["y"],1),
                "detector_track_id":o.get("detector_track_id"),
                "origin_passable":origin_ok,
                "bearing_state":o.get("bearing_state"),
                "refusal":"bearing_unavailable" if o.get("facing") is None else "origin_impassable" if not origin_ok else None,
                **cone.compare_evidence(m,lit,known)})
        n,lab,stats,cent=cv2.connectedComponentsWithStats(
            residual.astype(np.uint8),8)
        blobs=sorted(((int(stats[k,4]),k) for k in range(1,n)),reverse=True)[:3]
        out["residual_blobs"]=[{"area":a,
                                "centroid":[round(float(cent[k][0]),1),
                                            round(float(cent[k][1]),1)],
                                "note":"position HINT: a centroid is not a cone apex"}
                               for a,k in blobs if a>=40]
        return out

    def supported(self,x,y):
        """Does a detection at (x, y) touch the opaque slab at all.

        ANY support, not a fraction -- settled when the quarantined Ascent
        burst turned out to be the world showing through the widget's margin,
        and 452/452 real detections had support against 0/51 phantoms.

        **This asks about a POINT, so only give it a point a detector actually
        read.** A ring fit's centre is not one: see `ring_supported`.
        """
        ix,iy=int(round(x)),int(round(y))
        return bool(self.support[iy,ix]) if (0<=iy<self.support.shape[0]
                    and 0<=ix<self.support.shape[1]) else False

    def ring_supported(self,red,d,frac_min=.5):
        """Is the ring's OWN red drawn on the map, or on the world behind it?

        **A fitted centre is the model's output, not evidence** -- and the
        enemy channel was gating on exactly that. An arc fits its centre at
        `p + r*n`, so red lying in the widget's transparent surround places a
        centre 3-9 px INSIDE the slab, and the point test passes for a ring
        with no pixel on the map at all. Measured over Sunset R6: 28 of 42
        detections in the two worst bursts had a centre on the slab and ZERO
        ring red on it.

        The player asked whether a KAY/O knife was changing pixels somewhere
        unseen. It is not an ability at all -- he turned to face Sunset's
        red-brick architecture, and the widget is semi-transparent. `red_mask`
        went from 613 px to 40,851 px between +30.0s and +31.2s and **the
        count ON the slab did not move: 90 -> 114**. Everything new was the
        wall behind the map.

        So the test is the same rule as `supported`, applied to the pixels a
        detector actually read. Over the round's 1,303 ring fits the answer is
        bimodal with an empty middle -- 676 in 0.0-0.1, 482 in 0.9-1.0, 29 in
        all of 0.1-0.5 -- so `frac_min` is a statement rather than a fit: most
        of an icon's ring is drawn on the map its agent stands on.
        """
        h,w=self.support.shape
        cx,cy,r=d["cx"],d["cy"],d["r"]
        lo_y,hi_y=max(0,int(cy-r-3)),min(h,int(cy+r+4))
        lo_x,hi_x=max(0,int(cx-r-3)),min(w,int(cx+r+4))
        if lo_y>=hi_y or lo_x>=hi_x:
            return False,0,0
        yy,xx=np.mgrid[lo_y:hi_y,lo_x:hi_x]
        d2=(xx-cx)**2+(yy-cy)**2
        ring=(d2>=(r-2.5)**2)&(d2<=(r+2.5)**2)&red[lo_y:hi_y,lo_x:hi_x]
        total=int(ring.sum())
        on=int((ring&self.support[lo_y:hi_y,lo_x:hi_x]).sum())
        return (total>0 and on/total >= frac_min),on,total

    def barrier_candidates_calibration(self,keyed):
        """Keep deriving the anchor set even when a baked one is in use.

        A map's bars do not change, but the SET can still be incomplete -- the
        cut law says Lotus is missing one -- so a session that reads baked
        anchors must still produce the evidence a better bake would come from.
        """
        if self.buy_samples < 5:
            return
        stable=(self.barrier_counts >= self.buy_samples*.75).astype(np.uint8)
        n,lab,stats,centres=cv2.connectedComponentsWithStats(stable,8)
        out=[]
        for k in range(1,n):
            x,y,w,h,area=map(int,stats[k])
            if area < 12 or max(w,h)<7 or max(w,h)>130 or max(w,h)/max(1,min(w,h))<2.0 or area/(w*h)<.6:
                continue
            cx,cy=centres[k]
            out.append(observation("barrier","spawn barrier?",cx,cy,(x,y,w,h),kind="barrier",
                         evidence=["buy_phase","persistent_straight_team_colour"],
                         confidence="candidate",calibration_samples=self.buy_samples))
        self.barriers=out

    def read(self,frame,t_ms):
        # Masks describe this observation only, including unreadable samples.
        self.cone_mask=None
        self.lit_mask=None
        base={"type":"sample","t_ms":t_ms,"source_state":"fresh",
              "widget":"unknown","observations":[],"cross_view":[],
              # Refusals are kept per channel, never silently dropped: a gate
              # nobody can count is a gate nobody can score.
              # Refusals are kept BY REASON, not merged: `no_slab_support` is
              # a claim about where a blob sat and `barrier_phase` is a claim
              # about what the round was doing, and collapsing them would make
              # both uncountable.
              "off_support":{"enemy":[],"ping":[]},
              "refused":{"enemy_barrier_phase":[]}}
        if stalls.stalled_at(self.freeze,t_ms):
            base.update(source_state="stale",widget="stale",roster=None)
            return base
        ra,re=alive_counts(frame,self.profile,self.w,self.h)
        # A completely absent roster is not 0v0.
        if ra == 0 and re == 0:
            ra=re=None
        base["roster"]={"alive_ally":ra,"alive_enemy":re,"observed_t_ms":t_ms}
        sr=read_scoreline(crop_gray(frame,scoreline_roi(self.profile),self.w,self.h),self.templates)
        base["hud"]={"score_left":sr.score_left,"score_right":sr.score_right,"clock_ms":sr.clock_ms}
        scorebox=scoreline_roi(self.profile).pixels(self.w,self.h)
        plant_score=spike_cover(frame,centre_box(scorebox),scorebox)
        base["hud"]["plant_score"]=plant_score
        planted=plant_score >= COVER_MIN and sr.clock_ms is None
        base["hud"]["planted"]=planted
        if planted:
            x0,y0,x1,y1=centre_box(scorebox)
            base["observations"].append(observation("spike","SPIKE planted (HUD)",(x0+x1)/2,(y0+y1)/2,(x0,y0,x1-x0,y1-y0),"hud",kind="spike",evidence=["spike_graphic","clock_replaced"]))
        x0,y0,x1,y1=self.box
        crop=frame[y0:y1,x0:x1]
        drawn=widget_drawn(crop,self.gray,self.floor)
        base["widget"]="drawn" if drawn else "not_drawn"
        agent_obs=[]
        if drawn:
            bars=self.barrier_candidates(crop,t_ms)
            base["observations"].extend(bars)
            def on_bar(d):
                return any(abs(d["cx"]-b["x"]) <= b["box"][2]/2+4 and abs(d["cy"]-b["y"]) <= b["box"][3]/2+4 for b in bars)
            allies=ally_icons(crop,self.floor,require_facing=False,support=self.support)
            selves=self_icons(crop,self.floor,require_facing=False,support=self.support)
            base["raw_allies"],base["raw_self"]=allies,selves
            rejected=[d for d in allies if on_bar(d)]
            base["barrier_conflicts"]=rejected
            allies=[d for d in allies if not on_bar(d)]
            lit=lighting.lit_mask(crop,self.light) if self.light is not None else None
            if lit is not None:
                allies=cone.resolve_lobe(self.passable,lit,allies,visible=self.floor,known=self.light.known)
                selves=cone.resolve_lobe(self.passable,lit,selves,visible=self.floor,known=self.light.known)
                self.lit_mask=lit
                base["lighting"]={"version":lighting.LIGHTING_VERSION,
                    "state":"observed","shape":list(lit.shape),
                    "lit_px":int(lit.sum()),"known_px":int(self.light.known.sum()),
                    "mask_runs":mask_runs(lit),
                    "meaning":"drawn light; ability light and foreground contamination possible; emitter attribution unresolved"}
            self.self_track.step(t_ms,selves)
            self.ally_track.step(t_ms,allies)
            principal=self.self_track.principal()
            for family,tracks in [("self",[principal] if principal else []),("ally",self.ally_track.tracks)]:
                for tr in tracks:
                    if tr.t_ms != t_ms:
                        continue
                    tracker=self.self_track if family=="self" else self.ally_track
                    bearing=tracker.bearings(t_ms,tracks=[tr])[0][2]
                    r=round(tr.r or 10)
                    agent_obs.append(observation(family,"self / observer" if family=="self" else "ally agent?",tr.x,tr.y,(round(tr.x)-r,round(tr.y)-r,2*r,2*r),kind=(self.player_agent.lower() if family=="self" and self.player_agent else "you") if family=="self" else "ally",r=r,facing=bearing,detector_track_id=tr.tid,evidence=["icon_ring"],confidence="observed_icon" if family=="self" else "candidate"))
                    agent_obs[-1].update(bearing_state="fresh" if bearing is not None else "no_fresh_measurement" if tr.facing_t_ms != t_ms else "temporal_disagreement",
                                        measured_facing=tr.facing if tr.facing_t_ms == t_ms else None)
            # THE VIEWCONE, restored to the round pipeline. The 2 s diagnostic
            # renders had it and the full-round ones lost it, so the two rounds
            # rendered so far carry no observable area at all. `per_icon` is
            # kept because the aggregate cannot say WHICH teammate saw a pixel.
            team=[o for o in agent_obs if o["family"] in ("self","ally")]
            agg,per=cone.observable(self.passable,
                        [(o["x"],o["y"],o.get("facing")) for o in team],
                        visible=self.floor)
            self.cone_mask=agg
            base["viewcone"]={"coverage":cone.coverage(agg,self.floor),
                              "emitters":len(team),
                              "with_bearing":sum(1 for o in team if o.get("facing") is not None)}
            for o,m in zip(team,per):
                o["cone_px"]=int(m.sum())
            base["cone_checks"]=self.cone_checks(team,agg,per,lit)
            # The enemy ring reads the DILATED floor while ally/self read the
            # opaque slab, and that asymmetry is most of this channel: over the
            # round 39.2% of enemy detections have no slab support against 4.2%
            # of ally, 1.1% of self and 0.9% of object. The player watched three
            # ability casts throw red markers "all at the map border" -- and
            # 50% of the knife burst and 74% of the grenade burst are OFF the
            # slab entirely, against a 29% baseline. Same rule as `ally_icons`:
            # ANY support at all, not a fraction.
            # THE SPAWN BARRIERS SAY THE ROUND HAS NOT GONE LIVE, and while
            # they are drawn the widget cannot be showing an enemy: both teams
            # are behind their own bars and nobody has line of sight. This is
            # the barrier channel gating the enemy channel, not a threshold on
            # the enemy detector -- measured over Sunset R6, **359 of 531 enemy
            # detections (67.6%) land while barriers are drawn**, and 83 of the
            # round's 166 enemy entities live entirely inside that window. The
            # two channels agree about where the window ends without being told:
            # barriers are observed +1.5s to +29.2s and the round's independently
            # derived `live_start` is +29.5s, with ZERO barrier samples after it.
            red=red_mask(crop,RING_SAT_MIN)
            for d in enemy_rings(crop,self.floor):
                if is_icon(d) and not on_bar(d):
                    if bars:
                        base["refused"]["enemy_barrier_phase"].append([d["cx"],d["cy"]])
                        continue
                    ok,on,total=self.ring_supported(red,d)
                    if not ok:
                        base["off_support"]["enemy"].append([d["cx"],d["cy"],on,total])
                        continue
                    r=int(d["r"])
                    agent_obs.append(observation("enemy","enemy agent?",d["cx"],d["cy"],(int(d["cx"])-r,int(d["cy"])-r,2*r,2*r),kind="enemy",r=r,evidence=["red_portrait_ring"],confidence="candidate"))
            base["observations"].extend(agent_obs)
            for o in agent_obs:
                cx,cy,r=round(o["x"]),round(o["y"]),max(3,round(o["r"]*.55))
                patch=crop[max(0,cy-r):cy+r+1,max(0,cx-r):cx+r+1]
                if patch.size:
                    o["appearance"]=composition(patch).tolist()
            # Keep all competing detector claims in raw evidence. Display one
            # object with alternatives rather than identical overlapping boxes.
            # Same rule, same reason: 846 of 5024 raw sightings over this
            # round sit in the margin, which is the see-through widget.
            ping=[]
            for q in sightings(crop,self.floor):
                (ping if self.supported(q[0],q[1])
                 else base["off_support"]["ping"]).append(q)
            discs=find_discs(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),self.support)
            dynamic=dynamic_objects(crop,self.lo,self.support,static_gray2=self.hi)
            base["raw_pings"],base["raw_discs"],base["raw_dynamic"]=ping,discs,dynamic
            # A dark icon disc is an independent reader, not merely a feature
            # on the bright dynamic blobs; using it only as a join lost glyphs.
            for x,y,score,area,circularity in discs:
                if any(math.hypot(x-a["x"],y-a["y"]) < a.get("r",10)+3 for a in agent_obs) or on_bar({"cx":x,"cy":y}):
                    continue
                r=max(5,min(18,round(math.sqrt(area/math.pi))))
                base["observations"].append(observation("object","ability icon?",x,y,(round(x)-r,round(y)-r,2*r,2*r),kind="ability?",hypotheses=["ability_icon","map_detail"],evidence=["dark_disc"],confidence="candidate"))
            for d in dynamic:
                x,y=d["xy"]
                if any(math.hypot(x-a["x"],y-a["y"]) < a.get("r",10)+3 for a in agent_obs):
                    continue
                if on_bar({"cx":x,"cy":y}):
                    continue
                if any(o["family"]=="object" and math.hypot(x-o["x"],y-o["y"])<12 for o in base["observations"]):
                    continue
                ps=[p for p in ping if math.hypot(x-p[0],y-p[1])<8]
                ds=[p for p in discs if math.hypot(x-p[0],y-p[1])<10]
                hypotheses=["dynamic_object"]
                label="object?"; kind="?"
                if ds:
                    hypotheses.append("ability_icon")
                    label="ability icon?"; kind="ability?"
                if ps:
                    # `classify` names the ping and the name was being thrown
                    # away: every ping read `ping?` on the frame while the type
                    # sat in `hypotheses`. An unclassified hue stays `ping?`.
                    named=ping_class(ps[0][2])
                    hypotheses.append("ping:"+str(named))
                    label="ping / icon?" if ds else "ping?"
                    kind="ping:"+named if named else "ping?"
                base["observations"].append(observation("object",label,x,y,d["box"],kind=kind,colour=d["colour"],hypotheses=hypotheses,evidence=["dynamic_mask"],confidence="unresolved"))
            # The four actual ability-glyph regions, only with visible tray art.
        else:
            self.self_track.step(t_ms,[])
            self.ally_track.step(t_ms,[])
        tray_counts,tray_clean=slot_counts(frame)
        base["ability_tray"]={"counts":tray_counts,"clean":tray_clean}
        for k,key in enumerate(SLOT_KEYS):
            cx=SLOT_X0+SLOT_DX*k
            patch=frame[974:1031,cx-30:cx+30]
            gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
            bright=int((gray>210).sum())
            if bright>60 and max(tray_counts)>100 and ra is not None:
                base["observations"].append(observation("hud_ability",lineup.ability_label(self.player_agent,key,self.store_root) or f"ability {key}",cx,1002,(cx-30,974,60,57),"hud",kind=lineup.ability_label(self.player_agent,key,self.store_root) or f"tray {key}",evidence=["tray_glyph_region"],confidence="HUD_region_not_cast"))
        # The existing screen reader masks HUD and the actual enlarged minimap.
        # No named identity or shootability is inferred from a coloured outline.
        outlines=screen.outline_candidates(frame,minimap_box=self.box)
        enemies=[o for o in agent_obs if o["family"]=="enemy"]
        for x,y,w,h,area in outlines:
            base["observations"].append(observation("outline","enemy outline?",x+w/2,y+h/2,(x,y,w,h),"world",kind="outline?",area=area,evidence=["screen_outline"],hypotheses=["enemy","revealed","corpse","deployable","scenery"]))
        if outlines and enemies:
            base["cross_view"].append({"kind":"simultaneous_enemy_evidence","world_count":len(outlines),"minimap_count":len(enemies),"identity_link":None,"reason":"co-occurrence supports presence, not one-to-one identity"})
        # Flat team-coloured silhouettes are independently drawn through walls.
        # Keep as candidates: costume colour and scenery can share this key.
        team=ally_mask(frame).astype(np.uint8)
        team[:120,:]=0; team[900:,:]=0
        team[y0:y1,x0:x1]=0
        team[650:,960:]=0
        n,lab,stats,centres=cv2.connectedComponentsWithStats(team,8)
        for k in range(1,n):
            x,y,w,h,area=map(int,stats[k])
            if 160<=area<=25000 and h>=24 and 1.1<=h/max(1,w)<=5 and area/(w*h)>.2:
                cx,cy=centres[k]
                base["observations"].append(observation("ally_outline","ally silhouette?",cx,cy,(x,y,w,h),"world",kind="ally shape?",hypotheses=["ally_silhouette","scenery"],evidence=["team_colour_silhouette"],confidence="candidate"))
        for o in base["observations"]:
            o["observed_t_ms"]=t_ms
        return base


#: Where a row sits in the sidecar list, most informative first. It used to be
#: `{"barrier":0,"spike":0,"object":1,...}` ascending, so the six STATIC spawn
#: barriers took six of the nine slots for the whole buy phase and the self,
#: ally and enemy rows -- the ones a person checks a frame against -- were
#: sorted last and never printed. Measured on Sunset R6: 16.4 rows per sample,
#: so what the list omits is most of them.
PANEL_ORDER={"self":0,"enemy":1,"ally":2,"spike":3,"object":4,
             "ally_outline":5,"outline":6,"hud_ability":7,"barrier":8}


def place(taken,x,y,w,h,limit,step=11,tries=4):
    """A free spot for a label near `(x, y)`, or the original if none is free.

    Crowds are exactly where the overlay has to stay readable, and exactly
    where two boxes want the same 12 px of text baseline. This nudges DOWN,
    never sideways, so a label stays over its own box; and it gives up rather
    than dropping the label, because an unreadable name is a smaller lie than
    a missing one.
    """
    for k in range(tries):
        yy=y+k*step
        box=(x,yy-h,x+w,yy)
        if all(box[2]<=t[0] or t[2]<=box[0] or box[3]<=t[1] or t[3]<=box[1]
               for t in taken) and yy<limit:
            taken.append(box)
            return yy
    taken.append((x,y-h,x+w,y))
    return y


def ink(img,text,xy,colour=(235,235,235),scale=.45):
    cv2.putText(img,text,xy,cv2.FONT_HERSHEY_SIMPLEX,scale,(10,12,15),3,cv2.LINE_AA)
    cv2.putText(img,text,xy,cv2.FONT_HERSHEY_SIMPLEX,scale,colour,1,cv2.LINE_AA)


def draw_review(frame,sample,rows,reader,t_ms,start_ms):
    h,w=frame.shape[:2]
    canvas=np.full((h,w+640,3),(26,23,20),np.uint8)
    canvas[:,:w]=frame
    x0,y0,x1,y1=reader.box
    zoom=600/(x1-x0)
    ch=round((y1-y0)*zoom)
    src=frame[y0:y1,x0:x1]
    # Draw the observed light even when no emitter bearing was recovered.
    # Geometric visibility remains a separate prediction with a thin outline.
    if reader.lit_mask is not None and reader.lit_mask.any():
        src=src.copy()
        m=reader.lit_mask
        src[m]=(0.72*src[m]+0.28*np.array((110,245,135),np.float32)).astype(np.uint8)
    if reader.cone_mask is not None:
        src=src.copy()
        contours,_=cv2.findContours(reader.cone_mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(src,contours,-1,CONE_TINT,1)
    panel=cv2.resize(src,(600,ch),interpolation=cv2.INTER_NEAREST)
    age=t_ms-sample["t_ms"]
    # Draw the informative families FIRST so that, when labels compete for the
    # same baseline, an agent keeps its own spot and a transient blob moves.
    rows=sorted(rows,key=lambda o:(PANEL_ORDER.get(o["family"],9),o["entity_id"]))
    taken_canvas,taken_panel=[],[]
    for o in rows:
        col=PALETTE.get(o["family"],(220,220,220))
        if o.get("acquisition")=="roster_count_conflict":
            col=(100,110,240)
        x,y,bw,bh=o["box"]
        # The NAME, not the id. `ally 7` in a 5v5 is a visible bug; `E0303` is
        # a serial number, and reading a round through serial numbers is what
        # hid the re-births. The id stays in the sidecar files.
        short=o.get("name") or o["entity_id"].split(":")[-1]
        label=short
        if o["state"]=="ambiguous_continuation":
            label+=" ~"
        if o["view"]=="minimap":
            cv2.rectangle(canvas,(x0+x,y0+y),(x0+x+bw,y0+y+bh),col,1)
            cx_=max(0,x0+x)
            cy_=place(taken_canvas,cx_,max(12,y0+y-3),
                      round(7*len(short)*.32/.45),9,y0+(y1-y0))
            ink(canvas,short,(cx_,cy_),col,.32)
            px,py=round(x*zoom),round(y*zoom)
            cv2.rectangle(panel,(px,py),(round((x+bw)*zoom),round((y+bh)*zoom)),col,1)
            # Short labels above each box; verbose class lives in the panel list.
            lx=max(0,min(520,px))
            ly=place(taken_panel,lx,max(12,py-3),
                     round(9*len(label)*.38/.45),11,ch)
            ink(panel,label,(lx,ly),col,.38)
            facing=o.get("facing")
            if facing is not None:
                c=(round(o["x"]*zoom),round(o["y"]*zoom))
                th=math.radians(facing)
                cv2.arrowedLine(panel,c,(round(c[0]+25*math.cos(th)),round(c[1]+25*math.sin(th))),col,1)
        else:
            cv2.rectangle(canvas,(x,y),(x+bw,y+bh),col,2 if o["view"]=="world" else 1)
            ink(canvas,label,(x,max(15,y-5)),col,.43)
    canvas[70:70+ch,w+20:w+620]=panel
    ink(canvas,"RETICLE / FULL ROUND",(w+22,28),(225,220,200),.65)
    ink(canvas,f"Source {t_ms/1000:.2f}s  |  round +{(t_ms-start_ms)/1000:.2f}s",(w+22,52),scale=.48)
    yy=ch+96
    ink(canvas,f"{sample['widget']} | detection age {age:.0f} ms",(w+22,yy),scale=.49)
    roster=sample.get("roster") or {}
    ink(canvas,f"Roster {roster.get('alive_ally','?')} vs {roster.get('alive_enemy','?')} | ? = unresolved class",(w+22,yy+22),scale=.46)
    ink(canvas,"Names are round-scoped hypotheses, fixed at birth; ~ = alternatives",(w+22,yy+44),scale=.43)
    ink(canvas,"Boxes between samples show the last observation",(w+22,yy+65),scale=.43)
    if reader.player_agent:
        team=", ".join(r["agent"] for r in (reader.lineup or {}).get("sides",{})
                       .get("ally",[]) if r.get("agent")) or "not separated"
        ink(canvas,f"you are {reader.player_agent} | team read: {team}",
            (w+22,yy+126),(150,220,250),.44)
    vc=sample.get("viewcone") or {}
    cc=sample.get("cone_checks") or {}
    if vc:
        ink(canvas,f"geometric cone {vc['coverage']*100:.1f}% of search floor; "
                   f"{vc['with_bearing']}/{vc['emitters']} emitters",
            (w+22,yy+86),CONE_TINT,.46)
    if cc:
        residual="unreadable" if cc['residual_frac'] is None else f"{cc['residual_frac']*100:.0f}% unexplained light"
        ink(canvas,f"Green: observed light | blue edge: prediction | {residual}",(w+22,yy+106),(110,245,135),.36)
    important=rows                                # already in PANEL_ORDER
    for i,o in enumerate(important[:9]):
        label=f"{o.get('name') or o['entity_id'].split(':')[-1]:<16}{o['label']}"
        if o.get("acquisition")=="roster_count_conflict": label+=" [roster conflict]"
        ink(canvas,label,(w+22,yy+152+i*21),PALETTE.get(o["family"],(220,220,220)),.43)
    if len(important)>9:
        ink(canvas,f"+ {len(important)-9} observations in sidecar",(w+22,yy+345),scale=.4)
    return canvas


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session",nargs="?")
    ap.add_argument("--select",nargs="+")
    ap.add_argument("--round",type=int)
    ap.add_argument("--out",type=Path)
    ap.add_argument("--hz",type=float,default=10)
    ap.add_argument("--seconds",type=float,help="bounded smoke render; explicitly not a full round")
    ap.add_argument("--ffmpeg",help="path to a portable FFmpeg executable")
    args=ap.parse_args(argv)
    store=Store()
    if args.select:
        result=[]
        for sid in args.select:
            m,rounds,freeze=round_candidates(store,sid)
            print(sid, "stall seconds",stalls.total_ms(freeze)/1000)
            for r in rounds:
                if r["complete"]:
                    result.append({"session":sid,**r})
        result.sort(key=lambda r:(r["stalled_ms"] if r["stalled_ms"] is not None else float("inf"),-r["player_kills"],-int(r["spike_planted"])))
        print(json.dumps(result,indent=2,default=serial))
        if args.out:
            with args.out.open("x",encoding="utf-8") as f: json.dump(result,f,indent=2,default=serial)
        return 0
    if not args.session or not args.round or not args.out:
        ap.error("session, --round and --out are required for rendering")
    m,rs,freeze=round_candidates(store,args.session)
    selected=next(r for r in rs if r["round_no"]==args.round)
    if not selected["complete"]:
        raise SystemExit("Selected round has unverified/incomplete boundaries")
    if not 0 < args.hz <= m["source"]["fps"]:
        ap.error("hz must be positive and no higher than source fps")
    reader=RoundReader(m,selected,freeze,store)
    out=args.out
    out.mkdir(parents=True,exist_ok=False)
    ffmpeg=args.ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        installed=sorted((store.root/"tools/ffmpeg").glob("*/bin/ffmpeg.exe"))
        ffmpeg=str(installed[-1]) if installed else None
    if not ffmpeg:
        raise SystemExit("ffmpeg is required for H.264 + source audio")
    start,end=selected["t_start_ms"],selected["render_end_ms"]
    if args.seconds:
        end=min(end,start+args.seconds*1000)
    fps=m["source"]["fps"]
    first=math.ceil(start*fps/1000)
    last=math.ceil(end*fps/1000)
    start=first*1000/fps
    producers=[Path(__file__),ROOT/"reticle/round_lifetimes.py",ROOT/"reticle/screen.py",
               ROOT/"reticle/minimap.py",ROOT/"reticle/track.py",ROOT/"reticle/roster.py",
               ROOT/"prototypes/minimap_dynamic.py",ROOT/"prototypes/minimap_ring_fit.py",
               ROOT/"prototypes/ability_disc.py",ROOT/"prototypes/plant_spike.py",
               ROOT/"reticle/ping.py",ROOT/"reticle/cone.py",ROOT/"reticle/lighting.py",
               ROOT/"reticle/ocr.py",ROOT/"reticle/stalls.py",ROOT/"reticle/rounds.py",
               ROOT/"reticle/barriers.py",ROOT/"reticle/lineup.py",ROOT/"prototypes/ability_hud.py"]
    metadata={"type":"provenance","version":VERSION,"lifetime_version":ROUND_LIFETIME_VERSION,
              "source":m["source"],"session":args.session,"round":selected,
              "from_ms":start,"to_ms":end,"detection_hz":args.hz,"video_fps":fps,
              # The association law is in widget pixels: an export that does not
              # state its scale cannot be replayed without deriving it again.
              "widget_scale":reader.scale,"widget_px":reader.box[2]-reader.box[0],
              "minimap_box":list(reader.box),"cone_check_version":CONE_CHECK_VERSION,
              "lighting_version":lighting.LIGHTING_VERSION,
              "full_round":args.seconds is None,"geometry_sha256":hashlib.sha256(reader.geo_path.read_bytes()).hexdigest(),
              "producer_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in producers}}
    (out/"provenance.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    cap=cv2.VideoCapture(m["source"]["path"])
    cap.set(cv2.CAP_PROP_POS_FRAMES,first)
    logfile=(out/"encoder.log").open("w")
    command=[ffmpeg,"-hide_banner","-loglevel","warning","-n","-f","rawvideo","-pixel_format","bgr24","-video_size",f"{reader.w+640}x{reader.h}","-framerate",str(fps),"-i","pipe:0","-ss",str(start/1000),"-i",m["source"]["path"],"-map","0:v:0","-map","1:a:0?","-t",str((last-first)/fps),"-c:v","libx264","-preset","veryfast","-crf","22","-threads","4","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(out/"round.mp4")]
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=logfile)
    life=RoundLifetimes(f"{args.session}:R{args.round}",start,reader.scale)
    counts=Counter(); states=Counter(); sample=None; rows=[]; next_read=start
    t0=time.perf_counter(); written=0
    try:
        with (out/"observations.jsonl").open("x",encoding="utf-8") as evidence:
            for index in range(first,last):
                ok,frame=cap.read()
                if not ok: raise RuntimeError(f"source ended at frame {index}, expected {last}")
                t_ms=index*1000/fps
                if t_ms+1e-6 >= next_read:
                    sample=reader.read(frame,t_ms)
                    rows=life.step(t_ms,sample["observations"],source_state=sample["source_state"],roster=sample.get("roster"))
                    sample["adjudication"]=rows
                    evidence.write(json.dumps(sample,default=serial)+"\n")
                    counts.update(o["label"] for o in rows)
                    states.update([sample["widget"]])
                    next_read += 1000/args.hz
                canvas=draw_review(frame,sample,rows,reader,t_ms,start)
                proc.stdin.write(canvas.tobytes())
                written += 1
                if written % 600 == 0:
                    print(f"{written}/{last-first} frames; source {t_ms/1000:.1f}s; elapsed {time.perf_counter()-t0:.1f}s",flush=True)
                if index in {first,first+round(15*fps),last-1}:
                    cv2.imwrite(str(out/f"preview-{index}.jpg"),canvas)
    finally:
        cap.release()
        proc.stdin.close()
        rc=proc.wait()
        logfile.close()
    if rc: raise RuntimeError(f"encoder failed: {out/'encoder.log'}")
    entities=life.finish(end)
    (out/"lifetimes.json").write_text(json.dumps(entities,indent=2,default=serial),encoding="utf-8")
    report={"frames":written,"expected_frames":last-first,"duration_s":written/fps,"sample_states":states,
            "observation_counts":counts,"entity_count":len(entities),
            "stalled_ms":selected["stalled_ms"],"complete_round_rendered":args.seconds is None and written==last-first,
            "limitations":["Anonymous IDs remain association hypotheses, especially across crowds and gaps.","Ability and ping classification is provisional; dropped spike, death marks and last-known marks may remain generic objects.","First-person boxes are outline candidates, not established living enemies; no first-person ally/body/ability detector is claimed.","Simultaneous cross-view evidence supports presence but does not identify a specific agent."]}
    samples=[json.loads(line) for line in (out/"observations.jsonl").read_text().splitlines()]
    # What each gate REFUSED, alongside what was kept. A gate nobody can count
    # is a gate nobody can score, and these are the numbers the next change to
    # either channel has to beat.
    refusals=Counter()
    for row in samples:
        for reason,pts in (row.get("refused") or {}).items():
            refusals[reason]+=len(pts)
        for chan,pts in (row.get("off_support") or {}).items():
            refusals[f"{chan}_no_slab_support"]+=len(pts)
    report["refusals"]=dict(refusals)
    checks=[row.get("cone_checks") for row in samples]
    checks=[c for c in checks if c]
    emitters=[e for c in checks for e in c["per_emitter"]]
    report["cone_consistency"]={"version":CONE_CHECK_VERSION,
        "samples":len(checks),"emitters":len(emitters),
        "refusals":dict(Counter(e.get("refusal") or "cast" for e in emitters)),
        "comparable_px":sum(e["comparable_px"] for e in emitters),
        "unknown_px":sum(e["unknown_px"] for e in emitters),
        "unlit_px":sum(e["unlit_px"] for e in emitters),
        "low_light_share_emitters":sum(e["lit_share"] is not None and e["lit_share"]<.1 for e in emitters),
        "median_unexplained_light":float(np.median([c["residual_frac"] for c in checks if c["residual_frac"] is not None])) if any(c["residual_frac"] is not None for c in checks) else None,
        "meaning":"cross-channel disagreements, not false-positive or recall measurements"}
    (out/"coverage.json").write_text(json.dumps(report,indent=2,default=serial),encoding="utf-8")
    (out/"barrier-candidates.json").write_text(json.dumps(reader.barriers,indent=2,default=serial),encoding="utf-8")
    print(json.dumps(report,indent=2,default=serial))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
