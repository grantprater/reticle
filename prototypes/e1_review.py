r"""Check E1's review list against the source video, one y/n per event.

    .\.venv\Scripts\python.exe prototypes\e1_review.py --serve [--open]

Reads `<store>/analysis/e1-agreement/review-20260928.json` (written by
`prototypes/e1_agreement.py`) and the `agreeing.json` beside it for each
event's verdict and names. Every player kill, player death and extra check
becomes one item. The page plays the item's capture from t-2 s to t+1 s,
looping, in the browser's `<video>`; `reticle.clipserve` serves byte ranges
of the original capture, so nothing is decoded or copied. A canvas beside it
enlarges the killfeed ROI of the same video element.

Keys (the labelling-pass layout): Y correct, N wrong (asks what is wrong,
optional), U unsure (kept out of scoring), A back one, S skip, R replay from
t-2 s, T add a note, SPACE pause, H half speed, M sound, Q or ESC quit.

Each answer POSTs to the server, which appends one row to the labels file
(default `<store>/labels/e1_review_20260928.jsonl`) at once: the event key,
the answer, the note, the window and what the page showed. The last row for a
key wins; the page resumes at the first unanswered item. The page shows the
machine's names, so every row records `compared_against_derived: true`.

This is a labeller: it decides nothing and nothing in `reticle/` uses it.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import threading
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle.clipserve import RangeHandler, serve  # noqa: E402
from reticle.killfeed import killfeed_roi  # noqa: E402
from reticle.profiles import DEFAULT_PROFILE, get_profile  # noqa: E402
from reticle.store import Store  # noqa: E402

TOOL = "e1_review 1"
BEFORE_S, AFTER_S = 2.0, 1.0
ANSWERS = {"y", "n", "unsure"}


def _clock(t_s: float) -> str:
    m, s = divmod(t_s, 60.0)
    return f"{int(m)}:{s:04.1f}"


def _name(ident: dict | None) -> tuple[str, str]:
    """The shown name and the identity status; an unread name says why."""
    ident = ident or {}
    status = ident.get("status") or "none"
    if status == "resolved" and ident.get("agent"):
        return ident["agent"], status
    return {"contested": "contested", "abstained": "abstained"}.get(status, "unknown"), status


def _roi(store: Store, sid: str) -> list[float]:
    try:
        name = store.read_manifest(sid).get("source_profile") or DEFAULT_PROFILE
    except SystemExit:
        name = DEFAULT_PROFILE
    r = killfeed_roi(get_profile(name))
    return [r.x0, r.y0, r.x1, r.y1] if r else [0.74, 0.075, 0.995, 0.32]


def _video_url(capture: str, videos_dir: Path) -> str:
    p = Path(capture)
    name = p.name if p.parent.resolve() == videos_dir.resolve() else str(p)
    return "/video/" + urllib.parse.quote(name)


def build_items(review_path: Path, videos_dir: Path, store: Store) -> tuple[list[dict], dict]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    agreeing = json.loads((review_path.parent / "agreeing.json").read_text(encoding="utf-8"))
    if agreeing.get("at") != review.get("at"):
        raise SystemExit(f"agreeing.json at {agreeing.get('at')} is not the review's run "
                         f"{review.get('at')}; regenerate the review list")
    verdict = {}
    for row in agreeing["rows"]:
        for d in row["deaths"]:
            verdict[d["death_id"]] = ("death", d)
        for k in row["kills"]:
            verdict[k["death_id"]] = ("kill", k)
    rois: dict[str, list[float]] = {}
    by_session: dict[str, list[dict]] = {}
    for e in review["events"]:
        sid = e["session"]
        kind, v = verdict.get(e["death_id"], (e["event"], {}))
        if kind == "kill":
            killer, killer_status = "YOU", "player"
            victim, victim_status = _name(v.get("victim"))
            ident = v.get("victim") or {}
        else:
            victim, victim_status = "YOU", "player"
            killer, killer_status = _name(v.get("killer"))
            ident = v.get("killer") or {}
        by_session.setdefault(sid, []).append({
            "key": e["death_id"], "kind": kind, "session": sid, "capture": e["capture"],
            "t_s": e["t_s"], "round_no": e["round_no"],
            "killer": killer, "killer_status": killer_status,
            "victim": victim, "victim_status": victim_status,
            "identity_channels": ident.get("channels"), "p_named": ident.get("p_named"),
            "status": v.get("status"), "reason": v.get("reason"),
            "channels": v.get("channels"), "witnesses": v.get("witnesses"),
            "weapon": v.get("weapon"), "life": v.get("life"),
            "second_life": v.get("second_life") or v.get("victim_second_life"),
            "report_bound": e.get("report_bound")})
    for x in review["extras"]:
        sid = x["session"]
        by_session.setdefault(sid, []).append({
            "key": f"check:{sid}:{int(round(x['t_s'] * 1000))}", "kind": "check",
            "session": sid, "capture": x["capture"], "t_s": x["t_s"], "check": x["check"]})
    items = []
    for sid, rows in by_session.items():
        rois[sid] = _roi(store, sid)
        for it in sorted(rows, key=lambda r: (r["t_s"], r["kind"] == "check")):
            it.update({"t_ms": int(round(it["t_s"] * 1000)), "clock": _clock(it["t_s"]),
                       "start_s": max(0.0, it["t_s"] - BEFORE_S), "end_s": it["t_s"] + AFTER_S,
                       "video": _video_url(it["capture"], videos_dir), "kf_roi": rois[sid]})
            items.append(it)
    meta = {"review": str(review_path), "ledger": review.get("ledger"), "at": review.get("at"),
            "n": len(items)}
    return items, meta


def _answered(labels: Path) -> dict[str, dict]:
    last: dict[str, dict] = {}
    if labels.is_file():
        for line in labels.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                last[row["key"]] = row
    return last


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>E1 review</title>
<style>
:root { --bg:#141414; --fg:#e6e6e6; --dim:#9a9a9a; --ok:#4caf50; --bad:#e53935; --warn:#f0b429; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.35 Consolas, monospace; }
#wrap { display:flex; gap:12px; padding:10px; }
#left { flex:0 0 auto; }
#main { width:min(62vw, 1190px); display:block; background:#000; border:3px solid #000; }
#main.at { border-color:var(--bad); }
#bar { position:relative; height:8px; background:#333; margin-top:4px; }
#bar i { position:absolute; top:0; bottom:0; background:#888; }
#bar b { position:absolute; top:-3px; bottom:-3px; width:2px; background:var(--bad); }
#right { flex:1 1 auto; min-width:360px; }
#kf { width:100%; background:#000; display:block; }
#info { margin-top:8px; white-space:pre-wrap; }
.big { font-size:20px; font-weight:bold; }
.dim { color:var(--dim); }
.ans-y { color:var(--ok); } .ans-n { color:var(--bad); } .ans-unsure { color:var(--warn); }
#keys { margin-top:10px; color:var(--dim); }
#msg { margin-top:6px; color:var(--warn); min-height:1.3em; }
</style></head><body>
<div id="wrap">
 <div id="left">
  <video id="main" muted playsinline preload="auto"></video>
  <div id="bar"><i id="play"></i><b id="mark"></b></div>
  <div id="rel" class="dim"></div>
 </div>
 <div id="right">
  <canvas id="kf" width="640" height="400"></canvas>
  <div id="info"></div>
  <div id="msg"></div>
  <div id="keys">Y correct &nbsp; N wrong &nbsp; U unsure &nbsp; A back &nbsp; S skip &nbsp; R replay<br>
  T note &nbsp; SPACE pause &nbsp; H half speed &nbsp; M sound &nbsp; Q/ESC quit</div>
 </div>
</div>
<video id="pre" muted preload="auto" style="display:none"></video>
<script>
let items = [], meta = {}, answered = {}, idx = 0, pending = {}, half = false;
const main = document.getElementById('main'), pre = document.getElementById('pre');
const kf = document.getElementById('kf'), ctx = kf.getContext('2d');
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function nextOpen(from) {
  for (let i = from; i < items.length; i++) if (!answered[items[i].key]) return i;
  return items.length;
}
function show(i) {
  if (i >= items.length) { done(); return; }
  idx = Math.max(0, i);
  const it = items[idx];
  const r = it.kf_roi;
  kf.height = Math.round(kf.width * ((r[3]-r[1]) * 9) / ((r[2]-r[0]) * 16));
  if (main.getAttribute('src') !== it.video) main.src = it.video;
  main.currentTime = it.start_s;
  main.playbackRate = half ? 0.5 : 1;
  main.play().catch(() => {});
  const win = it.end_s - it.start_s;
  $('mark').style.left = (100 * (it.t_s - it.start_s) / win) + '%';
  const a = answered[it.key];
  const n = Object.values(answered).filter(x => x.answer !== undefined).length;
  let head;
  if (it.kind === 'check') head = `<span class="big">EXTRA CHECK</span>\n${esc(it.check)}\n`;
  else head = `<span class="big">${it.kind === 'kill' ? "the player's KILL" : "the player's DEATH"}</span>\n` +
    `<span class="big">${esc(it.killer)} &rarr; ${esc(it.victim)}</span>\n` +
    `killer ${esc(it.killer_status)}, victim ${esc(it.victim_status)}` +
    (it.identity_channels ? ` (${esc(it.identity_channels.join(', '))})` : '') + `\n` +
    `verdict ${esc(it.status)}${it.reason ? ' (' + esc(it.reason) + ')' : ''}; ` +
    `report ${it.report_bound ? 'bound' : 'unbound'}` + (it.life ? `; life ${it.life}` : '') +
    (it.second_life ? '; second life' : '') + `\nchannels ${esc((it.channels || []).join(', '))}; ` +
    `witnesses ${esc(it.witnesses)}; weapon ${esc(it.weapon)}\n`;
  $('info').innerHTML = head +
    `\ntime ${it.clock} (${it.t_s.toFixed(1)} s)` + (it.round_no != null ? `, round ${it.round_no}` : '') +
    `\nsession ${esc(it.session)}\n<span class="dim">${esc(it.capture)}</span>\n<span class="dim">${esc(it.key)}</span>\n` +
    `\nitem ${idx + 1} / ${items.length}; ${n} answered` +
    (a ? `\nanswered <span class="ans-${esc(a.answer)}">${esc(a.answer)}</span>${a.note ? ': ' + esc(a.note) : ''}` : '') +
    (pending[it.key] ? `\nnote pending: ${esc(pending[it.key])}` : '');
  $('msg').textContent = '';
  const nx = items[nextOpen(idx + 1)];
  if (nx && pre.getAttribute('src') !== nx.video) { pre.src = nx.video; }
  if (nx) { pre.currentTime = nx.start_s; }
}
function done() {
  main.pause();
  $('info').innerHTML = `<span class="big">All ${items.length} items answered.</span>\nA goes back; Q quits.`;
  idx = items.length;
}
function tick() {
  const it = items[idx];
  if (it && main.readyState >= 2) {
    if (main.currentTime >= it.end_s || main.currentTime < it.start_s - 0.5) main.currentTime = it.start_s;
    const r = it.kf_roi, W = main.videoWidth, H = main.videoHeight;
    ctx.drawImage(main, r[0]*W, r[1]*H, (r[2]-r[0])*W, (r[3]-r[1])*H, 0, 0, kf.width, kf.height);
    const dt = main.currentTime - it.t_s;
    main.classList.toggle('at', Math.abs(dt) <= 0.25);
    $('play').style.left = (100 * (main.currentTime - it.start_s) / (it.end_s - it.start_s)) + '%';
    $('play').style.width = '2px';
    $('rel').textContent = `t ${dt >= 0 ? '+' : ''}${dt.toFixed(2)} s  (video ${main.currentTime.toFixed(2)} s)`;
  }
  requestAnimationFrame(tick);
}
async function send(answer, note) {
  const it = items[idx];
  const body = {key: it.key, answer: answer, note: note || null};
  const r = await fetch('/answer', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify(body)});
  if (!r.ok) { $('msg').textContent = 'NOT SAVED: ' + await r.text(); return false; }
  answered[it.key] = await r.json();
  delete pending[it.key];
  return true;
}
async function answer(a) {
  const it = items[idx];
  if (!it) return;
  let note = pending[it.key] || null;
  if (a === 'n') {
    main.pause();
    const w = prompt('What is wrong? (optional)', '');
    if (w) note = note ? note + ' | ' + w : w;
  }
  if (await send(a, note)) show(nextOpen(idx + 1) < items.length ? nextOpen(idx + 1) : idx + 1);
}
async function addNote() {
  const it = items[idx];
  if (!it) return;
  main.pause();
  const w = prompt('Note for ' + it.key, '');
  main.play().catch(() => {});
  if (!w) return;
  const a = answered[it.key];
  if (a && a.answer) {
    const note = a.note ? a.note + ' | ' + w : w;
    if (await send(a.answer, note)) show(idx);
  } else { pending[it.key] = pending[it.key] ? pending[it.key] + ' | ' + w : w; show(idx); }
}
document.addEventListener('keydown', ev => {
  if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
  const k = ev.key.toLowerCase();
  if (k === 'y') answer('y');
  else if (k === 'n') answer('n');
  else if (k === 'u') answer('unsure');
  else if (k === 'a') show(Math.max(0, idx - 1));
  else if (k === 's') show(Math.min(items.length, idx + 1));
  else if (k === 'r') { const it = items[idx]; if (it) { main.currentTime = it.start_s; main.play().catch(() => {}); } }
  else if (k === 't') addNote();
  else if (k === ' ') { ev.preventDefault(); main.paused ? main.play().catch(() => {}) : main.pause(); }
  else if (k === 'h') { half = !half; main.playbackRate = half ? 0.5 : 1; }
  else if (k === 'm') { main.muted = !main.muted; }
  else if (k === 'q' || k === 'escape') {
    main.pause(); fetch('/quit', {method: 'POST'});
    document.body.innerHTML = '<p style="padding:20px">Saved. The server stopped; close this tab.</p>';
  }
});
main.addEventListener('error', () => {
  const e = main.error; $('msg').textContent = 'VIDEO ERROR ' + (e ? e.code + ' ' + (e.message || '') : '');
});
main.addEventListener('waiting', () => { $('msg').textContent = 'loading...'; });
main.addEventListener('playing', () => { if ($('msg').textContent === 'loading...') $('msg').textContent = ''; });
(async () => {
  items = await (await fetch('/items.json')).json();
  answered = await (await fetch('/answered')).json();
  show(nextOpen(0));
  requestAnimationFrame(tick);
})();
</script></body></html>
"""


def make_handler(items: list[dict], meta: dict, labels: Path, html: Path, videos_dir: Path):
    by_key = {it["key"]: it for it in items}
    lock = threading.Lock()

    class ReviewHandler(RangeHandler):
        html_path = html

        def route_get(self, req_path: str) -> bool:
            if req_path == "/items.json":
                self.send_bytes(json.dumps(items).encode(), "application/json")
                return True
            if req_path == "/answered":
                with lock:
                    rows = _answered(labels)
                self.send_bytes(json.dumps(rows).encode(), "application/json")
                return True
            return False

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/quit":
                self.send_bytes(b"bye", "text/plain")
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path != "/answer":
                self.send_error(404)
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                it = by_key[body["key"]]
                if body.get("answer") not in ANSWERS:
                    raise ValueError(f"answer must be one of {sorted(ANSWERS)}")
            except (KeyError, ValueError, TypeError) as exc:
                self.send_bytes(f"refused: {exc!r}".encode(), "text/plain", 400)
                return
            note = body.get("note")
            row = {"key": it["key"], "answer": body["answer"],
                   "note": str(note)[:500] if note else None,
                   "kind": it["kind"], "session_id": it["session"], "t_ms": it["t_ms"],
                   "window_ms": [int(round(it["start_s"] * 1000)), int(round(it["end_s"] * 1000))],
                   "source_path": it["capture"],
                   "shown": {k: it.get(k) for k in ("killer", "victim", "killer_status",
                                                    "victim_status", "status", "report_bound",
                                                    "check")},
                   "compared_against_derived": True, "by": "player",
                   "review": meta["review"], "ledger": meta["ledger"], "review_at": meta["at"],
                   "tool": TOOL, "at": _dt.datetime.now().isoformat(timespec="seconds")}
            with lock:
                labels.parent.mkdir(parents=True, exist_ok=True)
                with labels.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                    f.flush()
            self.send_bytes(json.dumps(row).encode(), "application/json")

    ReviewHandler.videos_dir = videos_dir
    return ReviewHandler


def main() -> int:
    store = Store()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--serve", action="store_true", help="serve the review page")
    ap.add_argument("--open", action="store_true", help="open the page in the default browser")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--review", default=str(store.root / "analysis" / "e1-agreement" / "review-20260928.json"))
    ap.add_argument("--labels", default=str(store.root / "labels" / "e1_review_20260928.jsonl"))
    ap.add_argument("--videos-dir", default=r"C:\Users\grant\Videos")
    args = ap.parse_args()

    review = Path(args.review)
    videos_dir = Path(args.videos_dir)
    items, meta = build_items(review, videos_dir, store)
    missing = sorted({it["capture"] for it in items if not Path(it["capture"]).is_file()})
    html = review.with_suffix(".html")
    html.write_text(PAGE, encoding="utf-8")
    review.with_suffix(".items.json").write_text(json.dumps(items, indent=1), encoding="utf-8")
    labels = Path(args.labels)
    done = sum(1 for r in _answered(labels).values() if r.get("answer") in ANSWERS)
    print(f"{len(items)} items ({sum(it['kind'] != 'check' for it in items)} events, "
          f"{sum(it['kind'] == 'check' for it in items)} checks); {done} answered in {labels}")
    for m in missing:
        print(f"MISSING capture: {m}")
    if not args.serve:
        print(f"page {html}; pass --serve to review")
        return 0
    return serve(make_handler(items, meta, labels, html, videos_dir), args.port,
                 "the E1 review", open_browser=args.open)


if __name__ == "__main__":
    raise SystemExit(main())
