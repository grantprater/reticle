"""Build an offline player-review page from an overlay's evidence sidecar.

Usage: .venv/Scripts/python.exe tools/minimap_sequence_review.py VIDEO.mp4
No labels are seeded. Downloaded answers can be imported to resume the page.
"""
import argparse
import base64
import json
from pathlib import Path


def build(video, output=None):
    sidecar = video.with_suffix(".minimap.jsonl")
    rows = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
    provenance, frames = rows[0], rows[1:]
    candidates = []
    for frame_index, row in enumerate(frames):
        for obs in row.get("observations", []):
            if obs["position_state"] == "observed":
                candidates.append({"frame": frame_index, "t_ms": row["t_ms"],
                                   "x": obs["x"], "y": obs["y"],
                                   "track_id": obs["track_id"], "role": obs["role"]})
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from reticle.profiles import get_profile
    from reticle.minimap import minimap_roi_px
    src = provenance["source"]
    box = minimap_roi_px(get_profile(provenance["profile"]), src["width"], src["height"])
    # Browser support for OpenCV's mp4v varies. Embed preview frames from the
    # DERIVED overlay, never from/copied as raw media, so review is portable.
    import cv2
    cap = cv2.VideoCapture(str(video))
    previews = []
    try:
        while True:
            ok, image = cap.read()
            if not ok:
                break
            image = cv2.resize(image, (960, 540))
            ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise ValueError("could not encode preview")
            previews.append('data:image/jpeg;base64,' + base64.b64encode(encoded).decode('ascii'))
    finally:
        cap.release()
    if len(previews) != len(frames):
        raise ValueError("video and evidence frame counts differ")
    data = {"candidates": candidates, "provenance": provenance, "box": box,
            "previews": previews}
    output = output or video.with_suffix(".review.html")
    payload = json.dumps(data).replace("<", "\\u003c")
    with output.open("x", encoding="utf-8") as f:
        f.write(PAGE.replace("__DATA__", payload))
    print(output)


PAGE = r'''<!doctype html><meta charset="utf-8"><title>Minimap sequence review</title>
<style>body{background:#161b24;color:#eef2f8;font:16px system-ui;max-width:1050px;margin:20px auto}
button,input{font:inherit;margin:4px;padding:7px}canvas{width:min(100%,960px);display:block}
.muted{color:#b1bed0}video{display:none}#question{font-weight:bold}</style>
<h1>Minimap sequence review</h1>
<p>Classify the ringed candidate. Track IDs are hypotheses. Watch nearby frames before answering.</p>
<p class="muted">This view includes detector annotations. Answers record that comparison. Nothing is pre-labelled.</p>
<label>Your name <input id="by" placeholder="Required before answering"></label>
<label>Resume answers <input id="resume" type="file" accept=".jsonl"></label>
<div id="question"></div><canvas id="canvas" width="960" height="540"></canvas>
<video id="video" muted preload="auto"></video>
<p><button id="back">A: Back</button><button id="play">Play / pause context</button>
<button id="previous">Previous frame</button><button id="next">Next frame</button>
<button id="advance">Space / D: Advance</button><button id="save">Q / Esc: Save answers</button></p>
<div id="classes"></div><p id="status" role="status"></p>
<script>
const data=__DATA__, cs=data.candidates, canvas=document.querySelector('#canvas'),
ctx=canvas.getContext('2d'), status=document.querySelector('#status');
const images=data.previews.map(src=>{let image=new Image();image.src=src;return image});
let playbackFrame=0,timer=null;
const video={readyState:2,paused:true,duration:(images.length-1)/data.provenance.output_fps,
get currentTime(){return playbackFrame/data.provenance.output_fps},
set currentTime(t){playbackFrame=Math.max(0,Math.min(images.length-1,Math.round(t*data.provenance.output_fps)));draw()},
pause(){this.paused=true;clearInterval(timer)},
play(){this.paused=false;timer=setInterval(()=>{if(playbackFrame>=images.length-1){this.pause();return}playbackFrame++;draw()},1000/data.provenance.output_fps)}};
const classes={'0':'nothing','1':'ally','2':'self','3':'enemy','4':'ability','5':'ping','6':'death_mark','7':'last_known','8':'other','u':'unsure'};
let index=0, answers=[], dirty=false;
function key(c){return [data.provenance.session,c.t_ms,c.x,c.y].join('|')}
function show(){if(!cs.length){status.textContent='No candidates in this sequence.';return}
video.pause();video.currentTime=cs[index].frame/data.provenance.output_fps;
document.querySelector('#question').textContent=`Candidate ${index+1}/${cs.length}, source ${(cs[index].t_ms/1000).toFixed(3)}s: what is the ringed thing?`;
status.textContent=answers.some(a=>a.key===key(cs[index]))?'Answered (a new answer appends a correction).':'Unanswered';draw()}
function draw(){if(images[playbackFrame]?.complete){ctx.drawImage(images[playbackFrame],0,0,960,540);let c=cs[index];
if(c){let sx=960/data.provenance.source.width,sy=540/data.provenance.source.height;
ctx.strokeStyle='#ff44ec';ctx.lineWidth=3;ctx.beginPath();ctx.arc((data.box[0]+c.x)*sx,(data.box[1]+c.y)*sy,14,0,Math.PI*2);ctx.stroke()}}
}
function advance(delta){index=Math.max(0,Math.min(cs.length-1,index+delta));show()}
function answer(value){let by=document.querySelector('#by').value.trim();if(!by){status.textContent='Enter your name first.';return}if(!cs.length)return;
let c=cs[index];answers.push({key:key(c),session:data.provenance.session,t_ms:c.t_ms,x:c.x,y:c.y,answer:value,by,
compared_against_derived:true,answered_at:new Date().toISOString()});dirty=true;advance(1)}
function save(){const blob=new Blob([answers.map(a=>JSON.stringify(a)).join('\n')+(answers.length?'\n':'')],{type:'application/x-ndjson'});
const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=data.provenance.session+'.minimap_sequence.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);dirty=false;
status.textContent='Answers downloaded. Keep the file and import it here to resume.'}
for(let [k,v] of Object.entries(classes)){let b=document.createElement('button');b.textContent=k.toUpperCase()+': '+v.replaceAll('_',' ');b.onclick=()=>answer(v);document.querySelector('#classes').append(b)}
document.querySelector('#back').onclick=()=>advance(-1);document.querySelector('#advance').onclick=()=>advance(1);document.querySelector('#save').onclick=save;
document.querySelector('#play').onclick=()=>{if(video.paused){video.play();draw()}else video.pause()};
document.querySelector('#previous').onclick=()=>{video.pause();video.currentTime=Math.max(0,video.currentTime-1/data.provenance.output_fps)};
document.querySelector('#next').onclick=()=>{video.pause();video.currentTime=Math.min(video.duration,video.currentTime+1/data.provenance.output_fps)};
document.querySelector('#resume').onchange=async e=>{try{let rows=(await e.target.files[0].text()).trim().split('\n').filter(Boolean).map(JSON.parse);
if(rows.some(r=>r.session!==data.provenance.session||!r.key||!r.by||!Object.values(classes).includes(r.answer)))throw Error('Wrong session or invalid answer file');
answers=rows;let next=cs.findIndex(c=>!answers.some(a=>a.key===key(c)));index=next<0?0:next;show()}catch(e){status.textContent=e.message}};
document.onkeydown=e=>{if(e.target.tagName==='INPUT')return;let k=e.key.toLowerCase();if(classes[k])answer(classes[k]);else if(k==='a')advance(-1);
else if(k===' '||k==='d'){e.preventDefault();advance(1)}else if(k==='q'||k==='escape')save()};
if(images[0]?.complete)show();else if(images[0])images[0].onload=show;
window.onbeforeunload=e=>{if(dirty){e.preventDefault();e.returnValue=''}};
</script>'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    build(args.video.resolve(), args.out)
