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

// Remove a directory entry by entry. On exFAT, macOS keeps "._name"
// AppleDouble files beside files and deletes them together, so Chromium's
// recursive removeEntry failed with NotFoundError partway through a 1 GiB
// piece folder on the owner's drive (2026-11-22). Skip "._" entries and
// ignore entries that are already gone.
export async function removeTree(parent, name) {
  const directory = await optional(() => parent.getDirectoryHandle(name));
  if (directory) {
    const entries = [];
    for await (const entry of directory.values()) entries.push(entry);
    for (const entry of entries) {
      if (entry.name.startsWith("._")) continue;
      if (entry.kind === "directory") await removeTree(directory, entry.name);
      else await optional(() => directory.removeEntry(entry.name));
    }
  }
  await optional(() => parent.removeEntry(name, {recursive: true}));
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

export async function measureFreeSpace(drive, {upper = 2 * 1024 * GiB, resolution = MiB, onAttempt = () => {},
  budgetMs = 120_000, maxFiles = 4} = {}) {
  const deadline = performance.now() + budgetMs;
  const prefix = "OWL-capacity-" + globalThis.crypto.randomUUID();
  const created = [], held = [];
  let attempts = 0;

  async function cleanup(name) {
    await removeFile(drive, name);
    await removeFile(drive, name + ".crswap");
  }

  // Grow a fresh file to `size`. Each step uses its own file in the default
  // (siloed) mode: after a deliberate out-of-space failure Chromium can keep a
  // writer's lock and swap file, so reusing one file made the next step fail.
  // With `hold`, a file that fits stays allocated until the measurement ends.
  async function attempt(size, {hold = false} = {}) {
    const started = performance.now();
    const filename = prefix + "-" + (++attempts) + ".tmp";
    created.push(filename);
    const handle = await drive.getFileHandle(filename, {create: true});
    const writable = await handle.createWritable();
    // Time only the extension. Opening and discarding the swap file costs
    // tens to hundreds of ms on a USB drive and says nothing about zero-fill.
    const opened = performance.now();
    let result = "fits", grown;
    try {
      await writable.truncate(size);
      grown = performance.now();
      if (hold) held.push(writable);
      else await writable.truncate(0);
    } catch (error) {
      if (isNoSpace(error)) result = "full";
      else if ((error.code === "EFBIG" || /EFBIG|file (?:is )?too large/i.test(error.message))) result = "file-limit";
      else if (error.name === "InvalidStateError") result = "undifferentiated";
      else throw error;
    } finally {
      if (!(hold && result === "fits")) {
        // A failing truncate may already have errored and aborted the stream.
        await writable.abort().catch(() => {});
        await cleanup(filename);
      }
    }
    const finished = performance.now();
    const outcome = {size, result, duration: (grown ?? finished) - opened, total: finished - started};
    onAttempt(outcome);
    return outcome;
  }

  // Largest size in [low, high) that a fresh file accepts, or null.
  async function boundary(low, high, step) {
    let lo = low, hi = high;
    while (hi - lo > step) {
      if (performance.now() > deadline) return null;
      const mid = Math.floor((lo + hi) / 2);
      const trial = await attempt(mid);
      if (trial.result === "fits") lo = mid;
      else if (trial.result === "full" || trial.result === "undifferentiated") hi = mid;
      else return null;
    }
    return lo;
  }

  // Keep `size` allocated. A mounted volume changes by small amounts while we
  // search (macOS indexing and event logs took about 1 MB on a physical exFAT
  // drive), so a miss at the boundary backs off by 64 MiB.
  async function holdAt(size, floor) {
    if ((await attempt(size, {hold: true})).result === "fits") return size;
    const margin = Math.max(floor, size - 64 * MiB);
    return (await attempt(margin, {hold: true})).result === "fits" ? margin : null;
  }

  try {
    let seed = await attempt(64 * MiB);
    // A sleeping USB drive can take seconds on its first allocation (0.4-6 s on
    // a physical exFAT drive, then 0.01 s natively; a browser adds fixed per-call
    // latency). Time a second, warm attempt before judging the drive.
    if (seed.result === "fits" && seed.duration > 250) seed = await attempt(64 * MiB);
    if (seed.result !== "fits" || seed.duration > 5_000) return {kind: "manual"};
    // A filesystem that writes zeros on extension takes about 16x longer for
    // 1 GiB than for 64 MiB; one that only allocates takes about the same time.
    // Only the first kind would make the search slow, so only it stops here.
    const gig = await attempt(GiB);
    if (gig.result !== "fits") return {kind: "limited"};
    if (gig.duration > 2_000 && gig.duration > 6 * Math.max(seed.duration, 1)) return {kind: "manual"};
    const largeFile = await attempt(4 * GiB + 1);
    if (largeFile.result === "file-limit") return {kind: "fat32"};
    if (largeFile.result !== "fits") return {kind: "limited"};
    const ceiling = await attempt(upper);
    if (ceiling.result === "fits") return {kind: "sparse-or-large"};
    if (ceiling.result === "file-limit") return {kind: "manual"};

    // Native truncate maps both ENOSPC and EFBIG to InvalidStateError, so the
    // result is an estimate.
    const first = await boundary(4 * GiB + 1, upper, resolution);
    if (first === null) return {kind: "manual"};
    let total = await holdAt(first, 4 * GiB + 1);
    if (total === null) return {kind: "manual"};
    // Chromium refused to grow one file past 793.02 GB on a physical exFAT
    // partition with 959.05 GB free, while native truncate reached 959 GB. With
    // earlier files still allocated, measure what another file can take and add
    // it, so a per-file limit does not hide free space.
    for (let files = 1; files < maxFiles; files++) {
      if ((await attempt(GiB)).result !== "fits") break;
      const more = await boundary(GiB, upper, 64 * MiB);
      if (more === null) break;
      const kept = await holdAt(more, GiB);
      if (kept === null) break;
      total += kept;
    }
    return {kind: "measured", bytes: total, files: held.length};
  } finally {
    for (const writable of held) await writable.abort().catch(() => {});
    for (const name of created) await cleanup(name);
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
// Keep the latest published reader for each hosted builder. Its worker can
// reopen the drive after the builder tab closes or the worker restarts.
export const saveReaderPreview = (scope, preview) => handleStore("readwrite", store => store.put(preview, ["reader", scope]));
export const getReaderPreview = scope => handleStore("readonly", store => store.get(["reader", scope]));
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
