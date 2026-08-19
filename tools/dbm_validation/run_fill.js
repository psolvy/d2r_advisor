// Run render.js's vendor-fill (ye) with the site's own code, for validation.
// argv[2] = JSON [{lo,hi,npc,rowPool,level,difficulty}], prints [{steps,lo,hi}]
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, 'render.js'), 'utf8');

function balanced(startIdx) { // literal starting at { or [ at startIdx
  const open = src[startIdx];
  const close = open === '{' ? '}' : ']';
  let d = 0;
  for (let k = startIdx; ; k++) {
    if (src[k] === open) d++;
    else if (src[k] === close) { d--; if (!d) return src.slice(startIdx, k + 1); }
  }
}
function grabExpr(prefixRe) {
  const m = src.match(prefixRe);
  if (!m) throw new Error('not found: ' + prefixRe);
  return balanced(m.index + m[0].length - 1);
}
function grabFn(header) {
  const i = src.indexOf(header);
  if (i < 0) throw new Error('not found: ' + header);
  const j = src.indexOf('{', i + header.length - 1);
  return src.slice(i, j) + balanced(j);
}

const we = eval('(' + grabExpr(/\bwe=\{/) + ')');
const ge = eval('(' + grabExpr(/\bge=\[/) + ')');
const xe = eval('(' + grabExpr(/\bxe=\{/) + ')');
const pe = eval('(' + grabExpr(/\bpe=\{/) + ')');
const R = eval('(' + grabFn('function R(l,e,a){') + ')');
const ke = eval('(' + grabFn('function ke(l,e,a){') + ')');
const U = eval('(' + grabFn('function U(l,e){') + ')');
const ye = eval('(' + grabFn('function ye(l,e,a,r,n){') + ')');

class RNG {
  constructor(lo, hi) { this.lo = lo >>> 0; this.hi = hi >>> 0; }
  step() {
    const l = this.lo & 65535, n = this.lo >>> 16, r = l * 37061,
      a = n * 37061 + l * 27334, i = n * 27334, t = r + (a % 65536) * 65536 + this.hi;
    this.lo = t % 4294967296;
    this.hi = i + Math.floor(a / 65536) + Math.floor(t / 4294967296);
    return this.lo;
  }
}

const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = cases.map(c => {
  const rng = new RNG(c.lo, c.hi);
  const steps = ye(rng, c.npc, c.rowPool, c.level, c.difficulty);
  return { steps, lo: rng.lo, hi: rng.hi };
});
process.stdout.write(JSON.stringify(out));
