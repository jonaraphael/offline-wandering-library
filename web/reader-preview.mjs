import {fileHandle, saveReaderPreview} from "./drive.mjs";
import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";

export async function activateReaderPreview() {
  const scope = new URL("./read/", import.meta.url).href;
  const registration = await navigator.serviceWorker.register(new URL("./reader-worker.mjs", import.meta.url),
    {type: "module", scope});
  const worker = registration.active || registration.waiting || registration.installing;
  if (worker.state !== "activated") await new Promise((resolve, reject) => {
    function changed() {
      if (!["activated", "redundant"].includes(worker.state)) return;
      worker.removeEventListener("statechange", changed);
      if (worker.state === "activated") resolve();
      else reject(Error("The library preview could not start."));
    }
    worker.addEventListener("statechange", changed);
    changed();
  });
  return scope;
}

export async function publishReaderLink(scope, drive, files) {
  const id = crypto.randomUUID();
  await saveReaderPreview(scope, {id, drive, files});
  return scope + id + "/START_HERE.html";
}

const missing = () => new Response("Open START_HERE.html on the connected drive.", {status: 404});
const documentTypes = new Map([
  ["html", "text/html; charset=utf-8"], ["htm", "text/html; charset=utf-8"],
  ["pdf", "application/pdf"], ["txt", "text/plain; charset=utf-8"]
]);

export async function readPreviewFile(preview, id, path) {
  if (!preview || preview.id !== id || !preview.files.has(path)) return missing();
  try {
    const file = await (await fileHandle(preview.drive, path)).getFile();
    const entry = path === "START_HERE.html";
    const script = /^LIBRARY\/(?:INDEX|SEARCH)\/.+\.js$/.test(path);
    const headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"};
    if (entry || script) {
      // These files execute in the builder's origin. Use only the exact bytes
      // pinned by the build, even if a file has since changed on the drive.
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (bytesToHex(sha256(bytes)) !== preview.files.get(path)) return missing();
      headers["Content-Type"] = entry ? "text/html; charset=utf-8" : "text/javascript; charset=utf-8";
      return new Response(bytes, {headers});
    }
    // Published documents may contain their own scripts. Isolate them from
    // the builder and its drive permissions. Stream large books from disk.
    headers["Content-Type"] = documentTypes.get(path.split(".").pop().toLowerCase()) || file.type || "application/octet-stream";
    if (headers["Content-Type"] !== "application/pdf") headers["Content-Security-Policy"] = "sandbox allow-scripts allow-downloads";
    return new Response(file, {headers});
  } catch {
    return missing();
  }
}
