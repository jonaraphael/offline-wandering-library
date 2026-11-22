import assert from "node:assert/strict";
import {test} from "node:test";
import {webcrypto} from "node:crypto";
import {measureFreeSpace} from "../web/drive.mjs";

globalThis.crypto ||= webcrypto;
const MiB = 2 ** 20;
const GiB = 2 ** 30;

// A fake drive whose truncate allocates instantly up to `free` bytes, after an
// optional one-time delay on the first allocation (a sleeping USB drive).
function fakeDrive({free, coldMs = 0, perCallMs = 0, shrinkAfterCalls = Infinity, shrinkBytes = 0}) {
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
            const available = calls > shrinkAfterCalls ? free - shrinkBytes : free;
            if (size > available) throw new DOMException("No space left", "QuotaExceededError");
          },
          async abort() {}
        };
      }};
    },
    async removeEntry(name) { removed.push(name); }
  };
  return {drive, removed, clock, calls: () => calls};
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

test("free space that shrinks during the search backs off instead of failing", async () => {
  // The volume loses 1 MB (indexing and event logs on a mounted drive) just
  // before the boundary recheck, so the recheck misses and the probe backs off.
  const free = 959_050_285_056;
  const steady = fakeDrive({free});
  await withClock(steady.clock, () => measureFreeSpace(steady.drive));
  const beforeRecheck = steady.calls() - 2;
  const {drive, clock} = fakeDrive({free, shrinkAfterCalls: beforeRecheck, shrinkBytes: 1_048_576});
  const result = await withClock(clock, () => measureFreeSpace(drive));
  assert.equal(result.kind, "measured");
  assert.ok(free - result.bytes > 64 * MiB && free - result.bytes < 128 * MiB, String(result.bytes));
});
