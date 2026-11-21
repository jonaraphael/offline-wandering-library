/* Use the browser's search algorithm with one native truncate per test point. */
import {open, statfs, unlink} from "node:fs/promises";
import {join} from "node:path";
import {webcrypto} from "node:crypto";
import {measureFreeSpace} from "../web/drive.mjs";

globalThis.crypto ||= webcrypto;
const [volume, filesystem] = process.argv.slice(2);
if (!volume || !filesystem) throw Error("Specify a disposable volume path and its filesystem name.");
const free = async () => {
  const stat = await statfs(volume);
  return stat.bsize * stat.bavail;
};
const attempts = [];
let attempt;
const drive = {
  async getFileHandle(name) {
    const path = join(volume, name);
    return {async createWritable() {
      const stream = await open(path, "w");
      return {async truncate(size) {
        if (!size) return stream.truncate(0);
        const before = await free();
        const start = performance.now();
        let errno;
        try { await stream.truncate(size); }
        catch (error) {
          errno = error.code;
          if (errno === "ENOSPC" || errno === "EFBIG") throw error;
          throw new DOMException(error.message, "InvalidStateError");
        }
        finally {
          attempt = {size, milliseconds: performance.now() - start, errno, allocated_bytes: before - await free(),
            logical_bytes: (await stream.stat()).size};
        }
      }, abort: () => stream.close()};
    }};
  },
  removeEntry: name => unlink(join(volume, name))
};
const before = await free();
const start = performance.now();
const result = await measureFreeSpace(drive, {onAttempt: outcome => attempts.push({...attempt, ...outcome})});
console.log(JSON.stringify({os:process.platform, filesystem, initial_free_bytes:before,
  final_free_bytes:await free(), milliseconds:performance.now() - start, result, attempts}, null, 2));
