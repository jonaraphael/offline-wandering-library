/* Locate the archives in a folder granted by the browser. */
(function (root) {
  "use strict";

  const startPage = "START_HERE.html";
  const relativeZim = "LIBRARY/ZIM/";
  const wrongFolder = () => Object.assign(new Error("Wrong library folder"), {code: "folder"});
  const disconnected = cause => Object.assign(new Error("Could not read the ZIM file", {cause}), {code: "disconnected"});
  const accessDenied = error => ["NotAllowedError", "SecurityError"].includes(error?.name);
  const decoded = value => {
    try { return decodeURIComponent(value); } catch (_) { return value; }
  };

  function folderName(pathname) {
    const folders = pathname.split("/").slice(0, -1).filter(Boolean);
    const name = decoded(folders.at(-1) || "");
    return /^[a-z]:$/i.test(name) ? "the " + name.toUpperCase() + " drive" : name || "the library folder";
  }

  function pickerLabel(device, handles, firefox, chromium) {
    if (handles) return device === "windows" ? "Select Folder" : device === "mac" ? "Select" : "Open";
    if (firefox) return device === "windows" ? "Select Folder" : "Open";
    return chromium || device === "mac" ? "Upload" : "Open";
  }

  function archiveParts(row) {
    return row.files || [{path: row.path, bytes: row.bytes}];
  }

  async function handleSource(handle, generation, rows) {
    async function file(path) {
      const parts = path.split("/");
      const name = parts.pop();
      let dir = handle;
      for (const folder of parts) dir = await dir.getDirectoryHandle(folder);
      return dir.getFileHandle(name);
    }
    for (const prefix of ["", ...(handle.name === "LIBRARY" ? ["LIBRARY/"] : [])]) {
      try {
        if (!prefix) await file(startPage);
        await file(("LIBRARY/" + generation + "/home.js").slice(prefix.length));
        return {get: async path => (await file(path.slice(prefix.length))).getFile()};
      } catch (error) {
        if (accessDenied(error)) throw error;
        // The selected folder may be inside the drive.
      }
    }
    if (handle.name === "ZIM") {
      const source = {get: async path => (await file(path.slice(relativeZim.length))).getFile()};
      for (const row of rows) {
        try {
          await openParts(source, row, true);
          return source;
        } catch (error) {
          if (accessDenied(error)) throw error;
          // Look for a complete archive with the recorded sizes.
        }
      }
    }
    throw wrongFolder();
  }

  function fileSource(files, generation, rows) {
    const map = new Map();
    let folder, marker;
    for (const file of files) {
      const path = file.webkitRelativePath;
      const slash = path.indexOf("/");
      if (slash < 0) continue;
      const relative = path.slice(slash + 1);
      if (relative.split("/").some(name => name.startsWith("._"))) continue;
      folder ??= path.slice(0, slash);
      if (folder !== path.slice(0, slash)) throw wrongFolder();
      map.set(relative, file);
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
      let file;
      try { file = await source.get(path); } catch (error) {
        if (accessDenied(error)) throw error;
        throw disconnected(error);
      }
      if (!file) throw disconnected();
      if (file.size !== bytes) {
        if (choosing) throw wrongFolder();
        throw Object.assign(new Error("Changed ZIM part"), {code: "file"});
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

  const api = {folderName, pickerLabel, archiveParts, handleSource, fileSource, openParts, readRoute, parseRoute, handleStore, accessDenied};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.OWLZimDrive = api;
})(globalThis);
