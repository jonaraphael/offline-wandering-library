import {getReaderPreview} from "./drive.mjs";
import {readPreviewFile} from "./reader-preview.mjs";

let preview;
async function serve(url, scope) {
  try {
    const relative = new URL(url).pathname.slice(new URL(scope).pathname.length);
    const [id, ...parts] = relative.split("/");
    const path = parts.map(decodeURIComponent).join("/");
    // A search loads many shards. Read the drive handle and file list once per preview.
    if (preview?.id !== id) preview = await getReaderPreview(scope);
    return readPreviewFile(preview, id, path);
  } catch {
    return new Response("Open START_HERE.html on the connected drive.", {status: 404});
  }
}

self.addEventListener("fetch", event => {
  const scope = self.registration.scope;
  if (event.request.url.startsWith(scope)) event.respondWith(serve(event.request.url, scope));
});
