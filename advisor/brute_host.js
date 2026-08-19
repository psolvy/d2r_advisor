// Runs the DBM site's own brute.worker.js in Node worker_threads at native
// V8 speed — the same kernel the website uses, so the same ~seconds-class
// search times. Launched by advisor/gamble_seed.py.
//
// argv[2] = JSON job file: { params: {level,rowPool,poolOrder,entries},
//                            threads, chunkBits }
// stdout JSON lines: {type:"progress",done} {type:"match",seed} {type:"done"}
"use strict";
const { Worker } = require("worker_threads");
const fs = require("fs");
const path = require("path");

const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const SRC = fs.readFileSync(
  path.join(__dirname, "..", "tools", "dbm_validation", "brute.worker.js"),
  "utf8");
const TOTAL = 4294967296;
const CHUNK = Math.pow(2, job.chunkBits || 24);
const os = require("os");
const threads = Math.max(1, job.threads ||
  Math.min(16, (os.cpus() || []).length || 4));

const boot = `
const { parentPort, workerData } = require("worker_threads");
global.self = {
  onmessage: null,
  postMessage: (m) => parentPort.postMessage(m),
};
(0, eval)(workerData.src);
parentPort.on("message", (m) => global.self.onmessage({ data: m }));
`;

let nextStart = 0;
let inFlight = 0;
let done = 0;
let ended = false;
const workers = [];
const out = (o) => process.stdout.write(JSON.stringify(o) + "\n");

function finish() {
  if (ended) return;
  ended = true;
  out({ type: "done", done });
  for (const w of workers) w.terminate();
  setTimeout(() => process.exit(0), 50);
}

function assign(w) {
  if (ended) return;
  if (nextStart >= TOTAL) {
    if (inFlight === 0) finish();
    return;
  }
  const start = nextStart;
  const end = Math.min(TOTAL, start + CHUNK);
  nextStart = end;
  inFlight++;
  w.postMessage({ type: "run", chunkId: start, start, end });
}

out({ type: "hello", threads });
for (let i = 0; i < threads; i++) {
  const w = new Worker(boot, { eval: true, workerData: { src: SRC } });
  workers.push(w);
  w.on("message", (m) => {
    if (m.type === "ready") assign(w);
    else if (m.type === "match") out({ type: "match", seed: m.seed });
    else if (m.type === "chunkDone") {
      done += CHUNK;
      inFlight--;
      out({ type: "progress", done: Math.min(done, TOTAL) });
      assign(w);
    }
  });
  w.on("error", (e) => { out({ type: "error", error: String(e) }); finish(); });
  w.postMessage({ type: "init", params: job.params });
}
