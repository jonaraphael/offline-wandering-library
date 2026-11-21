const READ_WRITE = {mode: "readwrite"};
const GiB = 2 ** 30;
const MiB = 2 ** 20;

function pathParts(path) {
  const parts = path.split("/");
  if (parts.some(part => !part || part === "." || part === ".." || /[\\:\u0000-\u001f]/.test(part))) {
    throw Error("Invalid drive path: " + path);
  }
  return parts;
}

async function parentOf(root, path, create) {
  const parts = pathParts(path);
  const name = parts.pop();
  let directory = root;
  for (const part of parts) directory = await directory.getDirectoryHandle(part, {create});
  return {directory, name};
}

export async function optional(operation) {
  try { return await operation(); }
  catch (error) {
    if (error.name !== "NotFoundError") throw error;
    return null;
  }
}

export async function fileHandle(root, path, create = false) {
  const {directory, name} = await parentOf(root, path, create);
  return directory.getFileHandle(name, {create});
}

export async function removeFile(root, path) {
  await optional(async () => {
    const {directory, name} = await parentOf(root, path, false);
    await directory.removeEntry(name);
  });
}

export async function writeFile(root, path, contents) {
  const handle = await fileHandle(root, path, true);
  const writable = await handle.createWritable({mode: "exclusive"});
  try {
    await writable.write(contents);
    await writable.close();
  } catch (error) {
    await writable.abort().catch(() => {});
    throw error;
  }
}

export function isNoSpace(error) {
  return error.name === "QuotaExceededError" || /ENOSPC|no space left|disk (?:is )?full/i.test(error.message);
}

export async function measureFreeSpace(drive, {upper = 2 * 1024 * GiB, resolution = MiB} = {}) {
  const filename = "OWL-capacity-" + globalThis.crypto.randomUUID() + ".tmp";
  const handle = await drive.getFileHandle(filename, {create: true});

  async function attempt(size) {
    const started = performance.now();
    const writable = await handle.createWritable({mode: "exclusive"});
    let result = "fits";
    try {
      await writable.truncate(size);
      await writable.truncate(0);
    } catch (error) {
      if (isNoSpace(error)) result = "full";
      else if (/EFBIG|file (?:is )?too large/i.test(error.message)) result = "file-limit";
      else if (error.name === "InvalidStateError") result = "undifferentiated";
      else throw error;
    } finally {
      // A failing truncate may already have errored and aborted the stream.
      await writable.abort().catch(() => {});
    }
    return {result, duration: performance.now() - started};
  }

  try {
    const seed = await attempt(64 * MiB);
    if (seed.result !== "fits" || seed.duration > 250) return {kind: "manual"};
    const largeFile = await attempt(4 * GiB + 1);
    if (largeFile.result === "file-limit") return {kind: "fat32"};
    if (largeFile.result !== "fits") return {kind: "limited"};
    const ceiling = await attempt(upper);
    if (ceiling.result === "fits") return {kind: "sparse-or-large"};
    if (ceiling.result === "file-limit") return {kind: "manual"};

    let lo = 4 * GiB + 1, hi = upper;
    while (hi - lo > resolution) {
      const mid = Math.floor((lo + hi) / 2);
      const trial = await attempt(mid);
      if (trial.result === "fits") lo = mid;
      else if (trial.result === "full" || trial.result === "undifferentiated") hi = mid;
      else return {kind: "manual"};
    }
    // Native truncate maps both ENOSPC and EFBIG to InvalidStateError. Check
    // both sides of the boundary again and describe the result as an estimate.
    if ((await attempt(lo)).result !== "fits" ||
        !["full", "undifferentiated"].includes((await attempt(hi)).result)) return {kind: "manual"};
    return {kind: "measured", bytes: lo};
  } finally {
    await removeFile(drive, filename);
  }
}

async function handleStore(mode, operation) {
  const db = await new Promise((resolve, reject) => {
    const request = indexedDB.open("owl-browser-builder", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("drive");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction("drive", mode);
      const request = operation(transaction.objectStore("drive"));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}

const driveKey = () => location.pathname.replace(/index\.html$/, "");
export const getRememberedDrive = () => handleStore("readonly", store => store.get(driveKey()));
export const rememberDrive = handle => handleStore("readwrite", store => store.put(handle, driveKey()));
export const requestDrivePermission = handle => handle.requestPermission(READ_WRITE);
export const hasDrivePermission = async handle => (await handle.queryPermission(READ_WRITE)) === "granted";
export const pickDrive = () => globalThis.showDirectoryPicker({id: "owl-drive", ...READ_WRITE});

export function keepScreenAwake() {
  let active = true;
  let pending = false;
  let lock;
  async function acquire() {
    if (!navigator.wakeLock || document.visibilityState !== "visible" || pending || (lock && !lock.released)) return;
    pending = true;
    try {
      lock = await navigator.wakeLock.request("screen");
      if (!active) await lock.release();
    } catch (_) {
      // Wake lock depends on browser, power and visibility settings.
    } finally {
      pending = false;
    }
  }
  document.addEventListener("visibilitychange", acquire);
  void acquire();
  return () => {
    active = false;
    document.removeEventListener("visibilitychange", acquire);
    lock?.release().catch(() => {});
  };
}
