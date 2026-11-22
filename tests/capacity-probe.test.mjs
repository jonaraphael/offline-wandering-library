import assert from "node:assert/strict";
import {test} from "node:test";
import {webcrypto} from "node:crypto";
import {measureFreeSpace} from "../web/drive.mjs";

globalThis.crypto ||= webcrypto;
const MiB = 2 ** 20;
const GiB = 2 ** 30;

// A fake drive whose truncate allocates instantly up to `free` bytes, after an
// optional one-time delay on the first allocation (a sleeping USB drive).
function fakeDrive({free, coldMs = 0, perCallMs = 0}) {
  let calls = 0;
  const removed = [];
  const clock = {now: 0};
  const drive = {
    async getFileHandle() {
      return {async createWritable() {
        return {
          async truncate(size) {
            calls++;
            clock.now += perCallMs + (calls === 1 ? coldMs : 0);
            if (size > free) throw new DOMException("No space left", "QuotaExceededError");
          },
          async abort() {}
        };
      }};
    },
    async removeEntry(name) { removed.push(name); }
  };
  return {drive, removed, clock};
}

function withClock(clock, run) {
  const original = performance.now.bind(performance);
  performance.now = () => clock.now;
  return run().finally(() => { performance.now = original; });
}

test("a slow first allocation is retried warm and the probe still measures", async () => {
  const {drive, removed, clock} = fakeDrive({free: 959 * 10 ** 9, coldMs: 400});
  const result = await withClock(clock, () => measureFreeSpace(drive));
  assert.equal(result.kind, "measured");
  assert.ok(959 * 10 ** 9 - result.bytes < MiB, String(result.bytes));
  assert.equal(removed.length, 1);
});

test("allocation that stays slow falls back to the drive label", async () => {
  const {drive, clock} = fakeDrive({free: 500 * GiB, perCallMs: 400});
  const result = await withClock(clock, () => measureFreeSpace(drive));
  assert.equal(result.kind, "manual");
});

test("the search stops at its time budget", async () => {
  const {drive, clock} = fakeDrive({free: 500 * GiB, perCallMs: 100});
  const result = await withClock(clock, () => measureFreeSpace(drive, {budgetMs: 1_000}));
  assert.equal(result.kind, "manual");
});
