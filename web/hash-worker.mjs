// Checksums for files already on the drive, off the page's thread. A check of
// a large drive otherwise holds the page, and other OWL tabs in the same
// process, at full CPU for the whole check.
import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";

const REPORT_BYTES = 32 * 2 ** 20;
const cancelled = new Set();

self.onmessage = async ({data}) => {
  if (data.cancel) { cancelled.add(data.cancel); return; }
  const {id, files} = data;
  try {
    const whole = sha256.create(), parts = [];
    let unreported = 0;
    for (const file of files) {
      // A single file's own checksum is the whole checksum: hash it once.
      const hash = files.length > 1 ? sha256.create() : whole;
      for await (const chunk of file.stream()) {
        if (cancelled.has(id)) { cancelled.delete(id); return; }
        hash.update(chunk);
        if (hash !== whole) whole.update(chunk);
        unreported += chunk.byteLength;
        if (unreported >= REPORT_BYTES) { self.postMessage({id, bytes: unreported}); unreported = 0; }
      }
      parts.push(hash === whole ? null : bytesToHex(hash.digest()));
    }
    const digest = bytesToHex(whole.digest());
    self.postMessage({id, bytes: unreported, digest, parts: parts.map(part => part ?? digest)});
  } catch (error) {
    self.postMessage({id, error: error.name + ": " + error.message});
  }
};
