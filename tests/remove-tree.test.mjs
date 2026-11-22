import assert from "node:assert/strict";
import {test} from "node:test";
import {removeTree} from "../web/drive.mjs";

// A directory that behaves like exFAT on macOS: every file "N" has an
// AppleDouble companion "._N" that disappears when "N" is removed, and a
// recursive delete that meets a vanished entry fails with NotFoundError.
class AppleDoubleDirectory {
  constructor(names = []) {
    this.kind = "directory";
    this.entries = new Map();
    for (const name of names) this.add(name);
  }
  add(name, entry = {kind: "file", name}) {
    this.entries.set(name, entry);
    if (entry.kind === "file") this.entries.set("._" + name, {kind: "file", name: "._" + name});
  }
  async getDirectoryHandle(name) {
    const entry = this.entries.get(name);
    if (!entry || entry.kind !== "directory") throw new DOMException("missing", "NotFoundError");
    return entry;
  }
  async *values() { yield* [...this.entries.values()]; }
  async removeEntry(name, {recursive = false} = {}) {
    const entry = this.entries.get(name);
    if (!entry) throw new DOMException("A requested file or directory could not be found", "NotFoundError");
    if (entry.kind === "directory" && recursive) {
      // Like Chromium on exFAT: deleting "N" also removes "._N", then the
      // listed "._N" is gone when its turn comes.
      for (const child of [...entry.entries.keys()]) await entry.removeEntry(child);
    }
    this.entries.delete(name);
    if (entry.kind === "file") this.entries.delete("._" + name);
  }
}

test("a piece folder with AppleDouble companions is removed without NotFoundError", async () => {
  const parent = new AppleDoubleDirectory();
  const pieces = new AppleDoubleDirectory(Array.from({length: 256}, (_, i) => String(i)));
  parent.add("0", pieces);
  await assert.rejects(new AppleDoubleDirectory().removeEntry.call(parent, "0", {recursive: true}), {name: "NotFoundError"});
  const again = new AppleDoubleDirectory();
  again.add("0", new AppleDoubleDirectory(Array.from({length: 256}, (_, i) => String(i))));
  await removeTree(again, "0");
  assert.equal(again.entries.has("0"), false);
});
