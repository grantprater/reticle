// Exercise an exported review page's controls in memory. Never writes player
// labels. Both pages are asked the same question -- does clicking through
// classifications produce the append-only JSONL a player pass depends on --
// so they share one harness rather than one each.
//
//   node tests/review_harness.cjs PAGE.html [answer ...]
//
// The DOM here is a stub, not a browser: it proves the page's own logic runs
// and exports, and says nothing about whether the page LOOKS right. A page
// that passes this can still be unreviewable, so look at it too.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const file = process.argv[2];
const answers = process.argv.length > 3 ? process.argv.slice(3) : ['ally', 'nothing'];
const html = fs.readFileSync(file, 'utf8');
const elements = {}, blobs = [];
const canvas = {drawImage(){}, beginPath(){}, arc(){}, stroke(){},
                fillRect(){}, clearRect(){}, fillText(){}};
function element() {
  return {value: 'test', checked: false, textContent: '', style: {},
          clientWidth: 960, clientHeight: 540, currentTime: 0, files: [],
          append(){}, click(){}, pause(){}, play(){}, addEventListener(){},
          getContext(){return canvas;}};
}
const store = {};
const document = {
  querySelector(s){return elements[s] ??= element();},
  getElementById(id){return elements['#' + id] ??= element();},
  createElement: element,
  addEventListener(){},
};
class Image {constructor(){this.complete = true; this.naturalWidth = 960;}}
const context = vm.createContext({
  document, Image, Blob, console, Date, JSON, Map, Math, Number, Error,
  window: {addEventListener(){}},
  localStorage: {getItem(k){return store[k] ?? null;}, setItem(k, v){store[k] = v;}},
  URL: {createObjectURL(b){blobs.push(b); return 'memory:test';}, revokeObjectURL(){}},
  setInterval(){}, clearInterval(){}, setTimeout(){},
});
vm.runInContext(html.split('<script>')[1].split('</script>')[0], context);
vm.runInContext(answers.map(a => `answer(${JSON.stringify(a)});`).join('') + 'save()',
                context);

assert.ok(blobs.length, 'clicking a classification produced no downloadable answers');
blobs[0].text().then(text => {
  const rows = text.trim().split('\n').map(JSON.parse);
  assert.deepEqual(rows.map(r => r.answer), answers);
  // Append-only, and keyed so a resumed pass can find the same observation.
  rows.forEach(r => assert.ok(r.key && r.answered_at && r.by,
                              'an answer must say which observation, when, and by whom'));
  assert.equal(new Set(rows.map(r => r.key)).size, rows.length,
               'two answers landed on the same observation');
  console.log(`PASS: ${rows.length} answers exported from ${file}`);
}).catch(error => {console.error(error); process.exitCode = 1;});
