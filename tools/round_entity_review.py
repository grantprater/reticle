"""Offline review for full_round_entities exports. No answer is seeded.

Population: up to three observations per association ID (first/middle/last),
including unresolved candidates and controls. Derived annotations are visible.
Downloads append-only answers; imported answers resume by source observation key.
"""
import argparse
import json
from pathlib import Path


def build_round_review(directory):
    meta=json.loads((directory/'provenance.json').read_text())
    by_id={}
    for line in (directory/'observations.jsonl').read_text().splitlines():
        frame=json.loads(line)
        for row in frame['adjudication']:
            by_id.setdefault(row['entity_id'],[]).append(row)
    candidates=[]
    for rows in by_id.values():
        for i in sorted({0,len(rows)//2,len(rows)-1}):
            candidates.append(rows[i])
    candidates.sort(key=lambda r:(r['observed_t_ms'],r['entity_id']))
    data=json.dumps({'meta':meta,'candidates':candidates}).replace('</','<\\/')
    page='''<!doctype html><meta charset="utf-8"><title>Reticle round review</title>
<style>body{margin:0;background:#14191e;color:#eee;font:15px system-ui}header,section{padding:12px 22px}h1{font-size:22px;margin:0}main{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:12px;padding:0 22px}video{width:100%;max-height:72vh}button,select,input{padding:8px;margin:3px;background:#29343e;color:white;border:1px solid #627480;border-radius:4px}#stage{position:relative}#ring{position:absolute;border:3px solid #fff300;pointer-events:none;box-shadow:0 0 0 2px #000;display:none}small{color:#b4c1ca}#classes{display:flex;flex-wrap:wrap}#status{white-space:pre-wrap}a{color:#9bdaff}</style>
<header><h1>Reticle · full-round review</h1><p>Play the round normally, or review the yellow-boxed candidate. Classify the boxed thing, not the whole frame. The detector's annotations are visible; this is a correction pass.</p></header>
<main><div><div id="stage"><video id="video" src="round.mp4" controls></video><div id="ring"></div></div><p><button id="previous">A · Back</button><button id="next">D · Next candidate</button><button id="context">Play context</button><button id="save">Q · Download answers</button></p><div id="classes"></div></div>
<aside><h2>Candidate</h2><p id="status"></p><label>Your name <input id="by" value="human"></label><p><input id="resume" type="file" accept=".jsonl"></p><small>Import a previous answer file to resume. Answers are append-only; the last answer for an observation wins. Unsure stays outside scoring. Nothing and Other are different answers.</small><p><a href="coverage.json">Coverage and limitations</a> · <a href="lifetimes.json">Lifetimes</a> · <a href="provenance.json">Provenance</a></p><p><small>Keys: 0–9 classify, U unsure, A back, D next, Q/Esc download. Space uses the video player's playback control.</small></p></aside></main>
<script>const DATA=__DATA__;const candidates=DATA.candidates;let index=0,answers=[];
const video=document.getElementById('video'),ring=document.getElementById('ring');
const classes=['nothing','agent','ability','ping','spawn_barrier','spike_dropped','spike_planted','death_mark','last_known','other'];
function key(c){return [DATA.meta.session,c.observed_t_ms,c.view,c.x,c.y].join(':')}
function lastAnswers(){const m=new Map();answers.forEach(a=>m.set(a.key,a));return m}
function show(){if(!candidates.length)return;const c=candidates[index];video.pause();video.currentTime=(c.observed_t_ms-DATA.meta.from_ms)/1000;const a=lastAnswers().get(key(c));document.getElementById('status').textContent=`${index+1} / ${candidates.length}\n${c.entity_id}\nSource ${(c.observed_t_ms/1000).toFixed(2)}s\n${c.view} · ${c.label}\nSaved answer: ${a?a.answer:'unanswered'}`;position()}
function position(){if(!candidates.length)return;const c=candidates[index];let [x,y,w,h]=c.box;if(c.view==='minimap'){const p=DATA.meta.source; x+=Math.round(p.width*.008);y+=Math.round(p.height*.014)}const sx=video.clientWidth/(DATA.meta.source.width+640),sy=video.clientHeight/DATA.meta.source.height;Object.assign(ring.style,{display:'block',left:(x*sx)+'px',top:(y*sy)+'px',width:(w*sx)+'px',height:(h*sy)+'px'})}
function advance(d){index=Math.max(0,Math.min(candidates.length-1,index+d));show()}
function answer(value){const c=candidates[index];if(!c)return;answers.push({key:key(c),session:DATA.meta.session,round:DATA.meta.round.round_no,t_ms:c.observed_t_ms,x:c.x,y:c.y,view:c.view,entity_id:c.entity_id,answer:value,by:document.getElementById('by').value||'human',compared_against_derived:true,answered_at:new Date().toISOString()});localStorage.setItem('reticle-round-'+DATA.meta.session+'-'+DATA.meta.round.round_no,JSON.stringify(answers));advance(1)}
function save(){const blob=new Blob([answers.map(a=>JSON.stringify(a)).join('\\n')+(answers.length?'\\n':'')],{type:'application/x-ndjson'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=DATA.meta.session+'-round-'+DATA.meta.round.round_no+'-answers.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
classes.forEach((name,i)=>{const b=document.createElement('button');b.textContent=i+' · '+name.replaceAll('_',' ');b.onclick=()=>answer(name);document.getElementById('classes').append(b)});const unsure=document.createElement('button');unsure.textContent='U · Unsure';unsure.onclick=()=>answer('unsure');document.getElementById('classes').append(unsure);
document.getElementById('previous').onclick=()=>advance(-1);document.getElementById('next').onclick=()=>advance(1);document.getElementById('save').onclick=save;document.getElementById('context').onclick=()=>{video.currentTime=Math.max(0,video.currentTime-2);ring.style.display='none';video.play()};
document.getElementById('resume').onchange=async e=>{try{const imported=(await e.target.files[0].text()).split(/\\r?\\n/).filter(Boolean).map(JSON.parse);if(imported.some(a=>a.session!==DATA.meta.session||a.round!==DATA.meta.round.round_no))throw Error('Answers belong to another round');answers.push(...imported);const done=lastAnswers();index=Math.max(0,candidates.findIndex(c=>!done.has(key(c))));show()}catch(e){alert(e.message)}};
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;const k=e.key.toLowerCase();if(/^[0-9]$/.test(k))answer(classes[Number(k)]);else if(k==='u')answer('unsure');else if(k==='a')advance(-1);else if(k==='d')advance(1);else if(k==='q'||k==='escape')save();else return;e.preventDefault()});window.addEventListener('resize',position);video.addEventListener('loadedmetadata',show);
try{answers=JSON.parse(localStorage.getItem('reticle-round-'+DATA.meta.session+'-'+DATA.meta.round.round_no)||'[]')}catch(e){}show();</script>'''
    output=directory/'review.html'
    with output.open('x',encoding='utf-8') as f:
        f.write(page.replace('__DATA__',data))
    return len(candidates)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    a=p.parse_args()
    print(build_round_review(a.directory),'review candidates')
