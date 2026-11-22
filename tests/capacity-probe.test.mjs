import assert from "node:assert/strict";
import {test} from "node:test";
import {webcrypto} from "node:crypto";
import {measureFreeSpace} from "../web/drive.mjs";

globalThis.crypto ||= webcrypto;
const MiB = 2 ** 20;
const GiB = 2 ** 30;

// A fake drive. Each file's extension allocates space that stays taken until
// the file is shrunk, aborted or removed. Options model a sleeping drive
// (coldMs), fixed per-call latency (perCallMs), zero-filling (msPerGiB), a
// per-file limit (perFileCap) and a volume that loses space as it is used
// (driftPerCall bytes per truncate).
function fakeDrive({free, coldMs = 0, perCallMs = 0, msPerGiB = 0, perFileCap = Infinity, driftPerCall = 0}) {
  let calls = 0, drift = 0;
  const allocated = new Map();
  const names = new Set();
  const clock = {now: 0};
  const taken = except => [...allocated].reduce((sum, [name, size]) => name === except ? sum : sum + size, 0);
  const drive = {
    async getFileHandle(name) {
      names.add(name);
      return {async createWritable() {
        return {
          async truncate(size) {
            calls++;
            drift += driftPerCall;
            clock.now += perCallMs + (calls === 1 ? coldMs : 0) + msPerGiB * size / GiB;
            if (size > Math.min(perFileCap, free - drift - taken(name))) {
              throw new DOMException("No space left", "QuotaExceededError");
            }
            allocated.set(name, size);
          },
          async abort() { allocated.delete(name); }
        };
      }};
    },
    async removeEntry(name) {
      if (!names.has(name)) throw new DOMException("Missing entry", "NotFoundError");
      names.delete(name);
      allocated.delete(name);
    }
  };
  return {drive, clock, names, allocated};
}

function withClock(clock, run) {
  const original = performance.now.bind(performance);
  performance.now = () => clock.now;
  return run().finally(() => { performance.now = original; });
}

test("a slow first allocation is retried warm and the probe still measures", async () => {
  const {drive, clock, names, allocated} = fakeDrive({free: 959 * 10 ** 9, coldMs: 400});
  const result = await withClock(clock, () => measureFreeSpace(drive));
  assert.equal(result.kind, "measured");
  assert.ok(959 * 10 ** 9 - result.bytes < 128 * MiB, String(result.bytes));
  assert.equal(names.size, 0, "probe files left behind: " + [...names]);
  assert.equal(allocated.size, 0);
});

test("fixed per-call latency still measures (a spinning USB disk seen through a browser)", async () => {
  const {drive, clock} = fakeDrive({free: 500 * GiB, coldMs: 6_000, perCallMs: 400});
  const result = await withClock(clock, () => measureFreeSpace(drive));
  assert.equal(result.kind, "measured");
  assert.ok(500 * GiB - result.bytes < 128 * MiB, String(result.bytes));
});

test("extension that writes zeros (time grows with size) falls back to the drive label", async () => {
  const {drive, clock} = fakeDrive({free: 500 * GiB, msPerGiB: 10_000});
  const result = await withClock(clock, () => measureFreeSpace(drive));
  assert.equal(result.kind, "manual");
});

test("the search stops at its time budget", async () => {
  const {drive, clock, names} = fakeDrive({free: 500 * GiB, perCallMs: 100});
  const result = await withClock(clock, () => measureFreeSpace(drive, {budgetMs: 1_000}));
  assert.equal(result.kind, "manual");
  assert.equal(names.size, 0);
});

test("free space that drifts during the search backs off instead of failing", async () => {
  const free = 959_050_285_056;
  const {drive, clock} = fakeDrive({free, driftPerCall: 64 * 1024});
  const result = await withClock(clock, () => measureFreeSpace(drive));
  assert.equal(result.kind, "measured");
  assert.ok(free - result.bytes < 256 * MiB, String(result.bytes));
});

test("a per-file limit below free space is summed across files", async () => {
  // Chromium stopped one file at 793.02 GB on a partition with 959.05 GB free.
  const free = 959_050_285_056;
  const {drive, clock, names, allocated} = fakeDrive({free, perFileCap: 793_020_000_000});
  const result = await withClock(clock, () => measureFreeSpace(drive));
  assert.equal(result.kind, "measured");
  assert.ok(result.files >= 2, String(result.files));
  assert.ok(free - result.bytes < 256 * MiB, String(free - result.bytes));
  assert.equal(names.size, 0);
  assert.equal(allocated.size, 0);
});
