// Run the site's search.worker.js in node: input JSON on argv[2], result to stdout.
const fs = require('fs');
const path = require('path');
const code = fs.readFileSync(path.join(__dirname, 'search.worker.js'), 'utf8');
let result = null;
global.self = {
  onmessage: null,
  postMessage: (m) => { if (m.type === 'done') result = m.result; },
};
eval(code);
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
global.self.onmessage({ data: input });
process.stdout.write(JSON.stringify(result));
