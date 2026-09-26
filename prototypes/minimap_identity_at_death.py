r"""Score minimap ally identity against killfeed deaths, an independent witness.

    .\.venv\Scripts\python.exe prototypes\minimap_identity_at_death.py LO_MS HI_MS

A teammate's icon disappears when the killfeed records their death, usually up
to half a second before the entry. An ally segment (`round_entity` entity)
that alone ends within [t - LO_MS, t + HI_MS] of a killfeed ally death with a
named victim is that victim for its last seconds. On those segments this
scores the per-icon best guess (`identity.claims_from_ally_icons`) over the
last 2 s and the stored segment agent. On `a06f04a0059f`, window 500/700 ms:
30 of 82 deaths bind one segment; per-icon 0.684, segment 21 of 29.
Predictions and outcome: `minimap-identity-at-death` in the store's
`notes/predictions.jsonl`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collections import Counter, defaultdict
from reticle.store import Store
from reticle.lineup import load_lineup
from reticle.adjudication.identity import claims_from_ally_icons, load_identity_gallery
S=Store(); sid="a06f04a0059f"; LO, HI = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (500.0, 700.0)
icons=[e for e in S.read_events("ally_icon",sid) if e.get("kind")=="icon"]
cl=claims_from_ally_icons(icons, load_lineup(sid,S.root), gallery=load_identity_gallery(S.root), session_id=sid)
best={c["entity_id"].rsplit(":ally_icon:",1)[-1]:((c.get("evidence") or {}).get("best_guess"), c.get("agent")) for c in cl}
ev=S.read_events("round_entity",sid)
ent={e["id"]:e for e in ev if e.get("kind")=="entity" and e.get("family")=="ally"}
obs=defaultdict(list)
for o in ev:
    if o.get("kind")=="observation" and o.get("entity_id") in ent: obs[o["entity_id"]].append((o["t_ms"],o["observation_key"]))
for k in obs: obs[k].sort()
deaths=[(v["victim"],float(v["t_ms"]),v["death_id"]) for v in S.read_events("death",sid) if v.get("kind")=="death_verdict" and v.get("side")=="ally" and v.get("victim")]
bind=Counter(); icon=Counter(); seg=Counter(); conf=Counter(); rows=[]
for a,t,did in deaths:
    ends=[e for e in obs if obs[e] and t-LO<=obs[e][-1][0]<=t+HI]
    bind[min(len(ends),2)]+=1
    if len(ends)!=1: continue
    e=ends[0]; last=[k for tt,k in obs[e] if tt>=obs[e][-1][0]-2000]
    for k in last:
        bg,named=best.get(k,(None,None))
        if bg: icon["right" if bg==a else "wrong"]+=1; 
        if bg and bg!=a: conf[f"{a} read {bg}"]+=1
    seg["right" if ent[e].get("agent")==a else "none" if not ent[e].get("agent") else "wrong"]+=1
print("deaths",len(deaths),"segments ending in window:",dict(bind))
print("per-icon best guess on last 2 s:",dict(icon), round(icon['right']/max(1,sum(icon.values())),3))
print("stored segment agent:",dict(seg)); print("confusions:",conf.most_common(6))
