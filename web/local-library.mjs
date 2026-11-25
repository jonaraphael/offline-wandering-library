import {DriveBusy, fileHandle} from "./drive.mjs";
import {publishedReaderFiles, readBuild} from "./builder.mjs";

// Pages projects can share an origin. Keep this builder's files and lock together.
const folder = "owl-local-" + encodeURIComponent(new URL("./", import.meta.url).pathname);
export async function localLibrary() {
  return (await navigator.storage.getDirectory()).getDirectoryHandle(folder, {create: true});
}

export function withLocalLibrary(operation) {
  return navigator.locks.request(folder, {ifAvailable: true}, lock => {
    if (!lock) throw new DriveBusy();
    return operation();
  });
}

export async function removeLocalLibrary(drive) {
  const root = await navigator.storage.getDirectory();
  if (await drive.isSameEntry(await root.getDirectoryHandle(folder))) {
    await root.removeEntry(folder, {recursive: true});
  }
}

const encoder = new TextEncoder();
const block = 512;
const padding = new Uint8Array(block);
const maxOctalSize = 8 ** 11 - 1;

// POSIX tar lets the download Blob reference disk-backed Files directly.
// Only headers and padding are built in memory, even for multi-GB archives.
function header(name, size, type, modified) {
  const bytes = new Uint8Array(block);
  const text = (offset, value) => bytes.set(encoder.encode(value), offset);
  const octal = (offset, length, value) => text(offset, value.toString(8).padStart(length - 1, "0"));
  text(0, name);
  octal(100, 8, 0o644);
  octal(108, 8, 0);
  octal(116, 8, 0);
  octal(124, 12, size);
  octal(136, 12, modified);
  text(148, "        ");
  text(156, type);
  text(257, "ustar");
  text(263, "00");
  const checksum = bytes.reduce((sum, byte) => sum + byte, 0);
  text(148, checksum.toString(8).padStart(6, "0") + "\0 ");
  return bytes;
}

function paxRecord(key, value) {
  const field = " " + key + "=" + value + "\n";
  const bytes = encoder.encode(field).length;
  let length = bytes + 1;
  while (length !== bytes + String(length).length) length = bytes + String(length).length;
  return String(length) + field;
}

export async function libraryArchive(drive) {
  const state = await readBuild(drive);
  if (!state?.syncedAt || state.pending) throw Error("Finish syncing this local library before downloading it.");
  const files = await publishedReaderFiles(drive);
  if (!files.size) throw Error("Sync the local library before downloading it.");
  const parts = [];
  function append(name, contents, size, type, modified) {
    parts.push(header(name, size > maxOctalSize ? 0 : size, type, modified), contents);
    if (size % block) parts.push(padding.subarray(0, block - size % block));
  }
  for (const path of files.keys()) {
    const file = await (await fileHandle(drive, path)).getFile();
    const modified = Math.floor(file.lastModified / 1000);
    const longPath = path.length > 100 || /[^\x20-\x7e]/.test(path);
    const extra = (longPath ? paxRecord("path", path) : "") +
      (file.size > maxOctalSize ? paxRecord("size", file.size) : "");
    if (extra) {
      const data = encoder.encode(extra);
      append("PaxHeader", data, data.length, "x", modified);
    }
    append(longPath ? "PaxFile" : path, file, file.size, "0", modified);
  }
  parts.push(padding, padding);
  return new Blob(parts, {type: "application/x-tar"});
}
