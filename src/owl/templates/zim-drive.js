/* Locate the archives in a folder granted by the browser. */
(function (root) {
  "use strict";

  const startPage = "START_HERE.html";
  const relativeZim = "LIBRARY/ZIM/";
  const wrongFolder = () => Object.assign(new Error("Wrong library folder"), {code: "folder"});
  const decoded = value => {
    try { return decodeURIComponent(value); } catch (_) { return value; }
  };

  function folderName(pathname) {
    const folders = pathname.split("/").slice(0, -1).filter(Boolean);
    const name = decoded(folders.at(-1) || "");
    return /^[a-z]:$/i.test(name) ? "the " + name.toUpperCase() + " drive" : name || "the library folder";
  }

  function pickerLabel(device, chromium, firefox) {
    if (chromium) return device === "windows" ? "Select Folder" : device === "mac" ? "Select" : "Open";
    if (firefox) return device === "windows" ? "Select Folder" : "Open";
    return device === "mac" ? "Upload" : "Open";
  }

  function archiveParts(row) {
    return row.files || [{path: row.path, bytes: row.bytes}];
  }

  async function handleSource(handle, generation) {
    async function file(path) {
      const parts = path.split("/");
      const name = parts.pop();
      let dir = handle;
      for (const folder of parts) dir = await dir.getDirectoryHandle(folder);
      return dir.getFileHandle(name);
    }
    const prefix = handle.name === "LIBRARY" ? "LIBRARY/" : "";
    try {
      if (!prefix) await file(startPage);
      await file(("LIBRARY/" + generation + "/home.js").slice(prefix.length));
    } catch (_) {
      throw wrongFolder();
    }
    return {get: async path => (await file(path.slice(prefix.length))).getFile()};
  }

  function fileSource(files, generation, rows) {
    const map = new Map();
    let folder, marker;
    for (const file of files) {
      const path = file.webkitRelativePath;
      const slash = path.indexOf("/");
      if (slash < 0) continue;
      folder ??= path.slice(0, slash);
      if (folder !== path.slice(0, slash)) throw wrongFolder();
      map.set(path.slice(slash + 1), file);
    }
    const prefix = folder === "ZIM" ? relativeZim : folder === "LIBRARY" ? "LIBRARY/" : "";
    const get = path => map.get(path.slice(prefix.length));
    if (folder === "ZIM") {
      marker = rows.some(row => archiveParts(row).every(({path, bytes}) => get(path)?.size === bytes));
    } else {
      marker = (prefix || map.has(startPage)) && get("LIBRARY/" + generation + "/home.js");
    }
    if (!marker) throw wrongFolder();
    return {get};
  }

  async function openParts(source, row, choosing = false) {
    const parts = [];
    for (const {path, bytes} of archiveParts(row)) {
      const file = await Promise.resolve().then(() => source.get(path)).catch(() => null);
      if (!file || file.size !== bytes) {
        if (choosing && file) throw wrongFolder();
        throw Object.assign(new Error("Missing or changed ZIM part"), {code: "file"});
      }
      parts.push(file);
    }
    return parts;
  }

  function readRoute(id, path = "@main", fragment = "", title = "", section = "") {
    const entry = path.split("/").map(encodeURIComponent).join("/");
    const query = new URLSearchParams();
    if (fragment) query.set("at", fragment);
    if (title) query.set("title", title);
    if (section) query.set("section", section);
    return "#/read/" + encodeURIComponent(id) + "/" + entry + (query.size ? "?" + query : "");
  }

  function parseRoute(hash) {
    const tail = hash.slice("#/read/".length);
    const slash = tail.indexOf("/");
    const [entry, query] = tail.slice(slash + 1).split("?");
    const options = new URLSearchParams(query);
    return {id: decoded(tail.slice(0, slash)), path: entry.split("/").map(decoded).join("/"),
      fragment: options.get("at") || "", title: options.get("title") || "", section: options.get("section") || ""};
  }

  async function handleStore() {
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open("owl-reader", 1);
      request.onupgradeneeded = () => request.result.createObjectStore("folders");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("Could not open folder storage"));
    });
    return (key, ...values) => new Promise((resolve, reject) => {
      const tx = db.transaction("folders", values.length ? "readwrite" : "readonly");
      const store = tx.objectStore("folders");
      const request = !values.length ? store.get(key) : values[0] ? store.put(values[0], key) : store.delete(key);
      tx.oncomplete = () => resolve(request.result);
      tx.onabort = tx.onerror = () => reject(tx.error || request.error);
    });
  }

  const api = {folderName, pickerLabel, archiveParts, handleSource, fileSource, openParts, readRoute, parseRoute, handleStore};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.OWLZimDrive = api;
})(globalThis);
