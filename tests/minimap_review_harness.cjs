// Exercise exported page controls in memory. Never writes player labels.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(process.argv[2], 'utf8');
const elements = {}, blobs = [];
const canvas = {drawImage(){}, beginPath(){}, arc(){}, stroke(){},
                fillRect(){}, clearRect(){}, fillText(){}};
function element() {
  return {value: 'test', checked: false, textContent: '', append(){}, click(){},
          getContext(){return canvas;}};
}
const document = {querySelector(s){return elements[s] ??= element();}, createElement: element};
class Image {constructor(){this.complete = true; this.naturalWidth = 960;}}
const context = vm.createContext({document, Image, Blob, console, window: {},
  URL: {createObjectURL(b){blobs.push(b);return 'memory:test';}, revokeObjectURL(){}},
  setInterval(){}, clearInterval(){}, setTimeout(){}});
vm.runInContext(html.split('<script>')[1].split('</script>')[0], context);
vm.runInContext('answer("ally");answer("nothing");save()', context);
blobs[0].text().then(text => {
  const answers = text.trim().split('\n').map(JSON.parse);
  assert.equal(answers.length, 2);
  assert.equal(answers[0].answer, 'ally');
  assert.equal(answers[1].answer, 'nothing');
  console.log('PASS: answer, advance and JSONL export');
}).catch(error => {console.error(error);process.exitCode = 1;});
