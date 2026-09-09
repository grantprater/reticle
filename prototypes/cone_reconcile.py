"""Source-aligned cone disagreements; no labels or accuracy claims.

Sample specified round offsets, warming trackers for one second per window.
Save source/lighting/geometric/disagreement panels and machine-readable counts.
Raw media is only read at its original path. Output directories must be new.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'prototypes'))
from full_round_entities import RoundReader, round_candidates, serial
from reticle import cone, lighting
from reticle.store import Store


def tint(src, mask, colour):
    out = src.copy()
    out[mask] = (.45*out[mask] + .55*np.array(colour)).astype(np.uint8)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('session')
    ap.add_argument('--round', type=int, required=True)
    ap.add_argument('--offsets', type=float, nargs='+', required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    store = Store()
    manifest, rounds, freeze = round_candidates(store, args.session)
    selected = next(r for r in rounds if r['round_no'] == args.round)
    cap = cv2.VideoCapture(manifest['source']['path'])
    reports = []
    for offset in args.offsets:
        reader = RoundReader(manifest, selected, freeze, store)
        target = selected['t_start_ms'] + offset*1000
        fps = manifest['source']['fps']
        first = round(max(selected['t_start_ms'], target-1000)*fps/1000)
        last = round(target*fps/1000)
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        for i in range(first, last+1):
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('source ended')
            if (i-first) % round(fps/10) == 0 or i == last:
                sample = reader.read(frame, i*1000/fps)
        x0,y0,x1,y1 = reader.box
        src = frame[y0:y1,x0:x1]
        lit = lighting.lit_mask(src, reader.light)
        known = reader.light.known
        team = [o for o in sample['observations'] if o['family'] in ('self','ally')]
        agg, per = cone.observable(reader.passable, [(o['x'],o['y'],o.get('facing')) for o in team], visible=reader.floor)
        rows = []
        for o,m in zip(team,per):
            x,y = round(o['x']),round(o['y'])
            comparable = m & known
            rows.append(dict(family=o['family'], x=x,y=y,facing=o.get('facing'),
                origin_passable=bool(reader.passable[y,x]),cone_px=int(m.sum()),
                known_px=int(comparable.sum()),lit_px=int((m&lit).sum()),
                legacy_share=float((m&lit).sum()/m.sum()) if m.any() else None,
                known_share=float((m&lit).sum()/comparable.sum()) if comparable.any() else None))
        record = dict(offset=offset,t_ms=sample['t_ms'],widget=sample['widget'],emitters=rows,
            lit_px=int(lit.sum()), residual_px=int((lit&~agg).sum()),
            cone_px=int(agg.sum()),unknown_cone_px=int((agg&~known).sum()))
        reports.append(record)
        panels = [src.copy(),tint(src,lit,(80,230,100)),tint(src,agg,(235,180,80)),src.copy()]
        panels[3] = tint(panels[3],lit&~agg,(210,80,240))
        panels[3] = tint(panels[3],agg&known&~lit,(50,100,255))
        panels[3] = tint(panels[3],agg&~known,(180,180,180))
        for j,o in enumerate(rows):
            for panel in panels[2:]:
                cv2.circle(panel,(o['x'],o['y']),11,(0,240,255),1)
                cv2.putText(panel,str(j),(o['x']+10,o['y']),0,.45,(0,255,255),1)
        titles = ['SOURCE','LIGHT READER (green)','GEOMETRIC CONES (blue)','missing light magenta / dark red / unknown gray']
        tiles=[]
        for title,panel in zip(titles,panels):
            tile=np.zeros((panel.shape[0]+35,panel.shape[1],3),np.uint8)
            tile[35:]=panel
            cv2.putText(tile,title,(5,22),0,.4,(255,255,255),1)
            tiles.append(tile)
        cv2.imwrite(str(args.out/f'{offset:06.1f}.jpg'),np.vstack((np.hstack(tiles[:2]),np.hstack(tiles[2:]))))
        print(json.dumps(record,default=serial),flush=True)
    cap.release()
    (args.out/'report.json').write_text(json.dumps(reports,indent=2,default=serial),encoding='utf-8')


if __name__ == '__main__':
    main()
