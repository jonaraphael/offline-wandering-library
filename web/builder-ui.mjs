import {browserSelection, buildLibrary, readBuild} from "./builder.mjs";
import {getRememberedDrive, hasDrivePermission, keepScreenAwake, measureFreeSpace,
  pickDrive, rememberDrive, requestDrivePermission} from "./drive.mjs";

const INDEX_ALLOWANCE = 16 * 2 ** 20;
const byId = id => document.getElementById(id);

async function get(url, signal) {
  const response = await fetch(url, {cache: "no-cache", signal});
  if (!response.ok) throw Error("Could not load " + url);
  return response.json();
}

export async function load() {
  const [catalog, published] = await Promise.all([get("./catalog.json"), get("./chunk-manifests.json")]);
  return {...catalog, published};
}

function format(bytes) {
  const [scale, unit] = bytes >= 1e9 ? [1e9, "GB"] : [1e6, "MB"];
  return (bytes / scale).toLocaleString(undefined, {maximumFractionDigits: 2}) + " " + unit;
}

function textList(node, rows) {
  node.replaceChildren(...rows.map(text => {
    const item = document.createElement("li");
    item.textContent = text;
    return item;
  }));
}

function lockDrive(operation) {
  if (!navigator.locks) return operation();
  return navigator.locks.request("offline-wandering-library-drive", {ifAvailable: true}, lock => {
    if (!lock) throw Error("A library operation is already running in another tab.");
    return operation();
  });
}

export function mount({catalog, recommend}) {
  const {planner, routes, published, navigation} = catalog;
  const assets = new Map(planner.assets.map(asset => [asset.id, asset]));
  const readers = planner.resources.find(row => row.id === "archive-readers").asset_ids;
  const platform = navigator.userAgentData?.platform || navigator.platform;
  const android = /android/i.test(platform) || /android/i.test(navigator.userAgent);
  const supported = typeof globalThis.showDirectoryPicker === "function" && !android;
  const isMac = /^mac/i.test(platform);
  const pick = byId("pick-drive");
  const confirmSize = byId("confirm-drive-size");
  const start = byId("start-build");
  const resume = byId("resume-build");
  const pause = byId("pause-build");
  const consent = byId("accept-browser-files");
  const status = byId("drive-status");
  const feedback = byId("browser-build-status");
  const meter = byId("build-progress");
  const errors = byId("browser-build-errors");
  let drive, saved, measured, selection, latest, busy = false, cancel;
  let confirmed = false, mayResume = false, confirmedCapacity;

  pick.disabled = !supported;
  if (!supported) status.textContent = android ?
    "Use a computer to build directly to the drive. You can read the finished library on this device." :
    "Use desktop Chrome or Edge to choose a drive, or use the Python build.";
  consent.addEventListener("change", () => refresh());

  function refresh() {
    pick.disabled = !supported || busy;
    start.disabled = !supported || busy || !drive || !confirmed || Boolean(saved) || !selection?.assets.length ||
      Boolean(selection?.over) || !(latest?.result.coverage.knowledgeBytes > 0) || Boolean(latest?.result.errors.length) ||
      Boolean((selection?.excluded.length || latest?.result.incomplete.length) && !consent.checked);
    pause.hidden = !cancel;
    resume.disabled = !supported || busy || !drive;
    resume.hidden = !drive || !mayResume || (saved?.finished === true);
    confirmSize.hidden = !drive || confirmed || mayResume;
    confirmSize.disabled = busy;
    byId("resources-heading").closest("section").inert = Boolean(cancel);
    byId("presets").inert = busy || Boolean(saved);
    byId("custom-capacity").inert = busy || Boolean(saved);
    byId("reset-preset").disabled = busy || Boolean(saved);
  }

  function update(result, state) {
    latest = {result, state};
    const allSelected = [...new Set([...result.selectedAssetIds, ...readers])].map(id => assets.get(id));
    const next = browserSelection(allSelected, routes, published);
    const profile = globalThis.OWLPlanner.profileFor(planner, state.profile, state.capacityBytes);
    const label = profile.nominal_capacity_bytes;
    if (measured === undefined && confirmedCapacity !== label) confirmed = false;
    confirmSize.textContent = "Use " + format(label) + " drive size";
    const available = Math.min(measured ?? Infinity, profile.capacity_bytes);
    const reserve = Math.max(INDEX_ALLOWANCE, profile.reserve_bytes) + profile.discovery_budget_bytes;
    // If a marketed 16 GB drive has less than 16 GB free, apply the minimum
    // ladder then fit its ranked, untouched recommendation to measured bytes.
    const args = result.selectionArgs;
    const adjustedDefault = measured < planner.capacity_policy.min && !args.include.length && !args.exclude.length &&
      !Object.keys(args.editions).length && !Object.keys(args.resourceAssets).length;
    let used = 0;
    next.assets = next.assets.filter(asset => {
      if (adjustedDefault && used + asset.size_bytes > available - reserve && !readers.includes(asset.id)) {
        next.excluded.push({id: asset.id, title: asset.title, reason: "Outside the measured drive budget"});
        return false;
      }
      used += asset.size_bytes;
      return true;
    });
    const over = Math.max(0, used + reserve - available);
    selection = {...next, over, searchBudget: profile.discovery_budget_bytes};
    const usedPercent = Math.min(100, 100 * used / available);
    byId("storage-fill").style.width = usedPercent + "%";
    byId("reserve-fill").style.width = "0%";
    byId("storage-meter").classList.toggle("over", over > 0);
    byId("capacity").textContent = format(available) + " available for planning";
    byId("knowledge-bytes").textContent = format(used);
    byId("meter-caption").textContent = over ? "Over by " + format(over) : "Fits";
    byId("mobile-content").textContent = format(used);
    byId("mobile-status").textContent = over ? "Over budget" : "Fits";
    byId("mobile-budget").classList.toggle("has-errors", over > 0);
    byId("browser-exclusions").hidden = !next.excluded.length && !result.incomplete.length;
    byId("browser-exclusions-title").textContent = next.excluded.length ?
      next.excluded.length + " selected files will be omitted" : "Some collections are incomplete";
    textList(byId("browser-exclusions-list"), next.excluded.map(row => row.title + " — " + row.reason));
    textList(byId("browser-plan-errors"), result.errors);
    byId("browser-plan-errors").hidden = result.errors.length === 0;
    refresh();
  }

  async function identify(handle, probe) {
    drive = handle;
    saved = null;
    measured = undefined;
    confirmed = false;
    mayResume = false;
    confirmedCapacity = undefined;
    status.textContent = "Selected " + handle.name + ".";
    try {
      if (await hasDrivePermission(handle)) {
        saved = await readBuild(handle);
        if (saved) {
          mayResume = !saved.finished;
          status.textContent = "Saved build on " + handle.name + ".";
          if (saved.finished) feedback.textContent = "Open START_HERE.html on this drive.";
        } else if (probe && isMac) {
          status.textContent = "Measuring free space on " + handle.name + "…";
          let capacity;
          try { capacity = await lockDrive(() => measureFreeSpace(handle)); }
          catch (_) { capacity = {kind: "manual"}; }
          if (capacity.kind === "measured") {
            measured = capacity.bytes;
            confirmed = true;
            status.textContent = "About " + format(measured) + " free on " + handle.name + ".";
            recommend(Math.max(measured, planner.capacity_policy.min));
          } else {
            const note = capacity.kind === "fat32" ? " This drive appears to use FAT32." :
              capacity.kind === "limited" ? " The drive may use FAT32 or have less than 4 GB free." :
              capacity.kind === "sparse-or-large" ? " The filesystem accepted an oversized probe." : "";
            status.textContent = "Choose the size on the drive label." + note;
          }
        } else if (probe) status.textContent = "Choose the size on the drive label for " + handle.name + ".";
      } else {
        mayResume = true;
        status.textContent = "Remembered " + handle.name + ". Choose Resume to restore access.";
      }
    } catch (error) {
      drive = null;
      status.textContent = error.message + " Choose a folder on the attached drive.";
    }
    if (latest) update(latest.result, latest.state);
  }

  confirmSize.addEventListener("click", () => {
    confirmedCapacity = globalThis.OWLPlanner.profileFor(planner, latest.state.profile, latest.state.capacityBytes).nominal_capacity_bytes;
    confirmed = true;
    status.textContent = "Using " + format(confirmedCapacity) + " for " + drive.name + ".";
    refresh();
  });

  pick.addEventListener("click", async () => {
    busy = true;
    consent.checked = false;
    refresh();
    try {
      const handle = await pickDrive();
      feedback.textContent = "";
      await identify(handle, true);
      if (drive) void rememberDrive(handle).catch(() => {});
    } catch (error) {
      if (error.name !== "AbortError") status.textContent = error.message;
    } finally {
      busy = false;
      refresh();
    }
  });

  const issues = new Map();
  let lastProgress = 0;
  function progress(event) {
    if (event.kind === "assembling") {
      meter.removeAttribute("value");
      feedback.textContent = "Writing the offline indexes and start page…";
    } else if (event.kind === "downloading") {
      const now = performance.now();
      if (event.received && event.received < event.bytes && now - lastProgress < 200) return;
      lastProgress = now;
      meter.max = event.total;
      meter.value = event.position + event.index / event.count + event.received / event.bytes / event.count;
      feedback.textContent = event.asset.title + " · file " + (event.position + 1) + " of " + event.total +
        " · part " + (event.index + 1) + " of " + event.count + " · " + format(event.received) + " of " + format(event.bytes);
    } else if (event.kind === "checking") {
      feedback.textContent = "Checking saved parts of " + event.asset.title + "…";
    } else if (event.kind === "retrying") {
      feedback.textContent = "Retrying " + event.asset.title + ". " + event.message;
    } else {
      issues.set(event.asset.id, event.asset.title + " — " + event.message);
      textList(errors, [...issues.values()]);
    }
  }

  async function run(isResume) {
    busy = true;
    mayResume = true;
    refresh();
    let releaseWakeLock;
    try {
      if (await requestDrivePermission(drive) !== "granted") throw Error("Allow write access to the drive or choose it again.");
      cancel = new AbortController();
      refresh();
      releaseWakeLock = keepScreenAwake();
      feedback.textContent = isResume ? "Opening the saved build…" : "Starting the build…";
      issues.clear();
      textList(errors, []);
      const search = await get("./search-build.json", cancel.signal);
      const result = await lockDrive(() => buildLibrary(drive, {...selection, catalogAssets: planner.assets,
        routes, published, navigation, search, resume: isResume, signal: cancel.signal, onProgress: progress}));
      saved = result.state;
      meter.max = 1;
      meter.value = 1;
      textList(errors, [...result.missing.map(row => row.title + " — " + row.reason), ...result.searchWarnings]);
      const ranOutOfSpace = Object.keys(saved.dropped).length > 0;
      feedback.textContent = ranOutOfSpace ?
        result.completed.length + " files verified. Free space on the drive and choose Resume to retry omitted files." : !saved.finished ?
        result.completed.length + " files verified. Open START_HERE.html on the drive. Choose Resume to retry failed downloads, or use the Python build." :
        result.completed.length + " files verified" + (result.missing.length ? ", " + result.missing.length + " omitted" : "") +
        ". Open START_HERE.html on the drive.";
    } catch (error) {
      feedback.textContent = cancel?.signal.aborted ? "Paused. Choose Resume to continue." :
        error.message + " Reconnect the same drive if needed, then choose Resume.";
      if (drive) {
        try { saved = await readBuild(drive); }
        catch (_) { /* Keep the handle so Resume can restore permission or report disconnection. */ }
      }
    } finally {
      releaseWakeLock?.();
      cancel = null;
      busy = false;
      refresh();
    }
  }

  start.addEventListener("click", () => void run(false));
  resume.addEventListener("click", () => void run(true));
  pause.addEventListener("click", () => cancel?.abort());
  if (supported) {
    void getRememberedDrive().then(handle => {
      if (handle && !drive && !busy) return identify(handle, true);
    }).catch(() => {});
  }
  refresh();
  return {update};
}
