import {createNetwork, SourceError} from "./network.mjs";
import {browserSelection, buildLibrary, isKnowledgeFile, PART_BYTES, readBuild} from "./builder.mjs";
import {getRememberedDrive, hasDrivePermission, keepScreenAwake, measureFreeSpace,
  pickDrive, rememberDrive, requestDrivePermission} from "./drive.mjs";

const INDEX_ALLOWANCE = 16 * 2 ** 20;
const byId = id => document.getElementById(id);

async function get(url, signal) {
  let response;
  const timeout = AbortSignal.timeout(120_000);
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
  try { response = await fetch(url, {cache: "no-cache", signal: requestSignal}); }
  catch (_) {
    signal?.throwIfAborted();
    throw new SourceError("Could not connect to the library website", {connection: true});
  }
  if (!response.ok) throw new SourceError("Could not load " + url);
  try { return await response.json(); }
  catch (error) {
    if (error instanceof TypeError || timeout.aborted) throw new SourceError("Connection interrupted", {connection: true});
    throw error;
  }
}

export async function load() {
  const [catalog, published] = await Promise.all([get("./catalog.json"), get("./chunk-manifests.json")]);
  return {...catalog, published};
}

function format(bytes) {
  const [scale, unit] = bytes >= 1e12 ? [1e12, "TB"] : bytes >= 1e9 ? [1e9, "GB"] : [1e6, "MB"];
  const value = bytes / scale;
  return value.toLocaleString(undefined, {maximumFractionDigits: value >= 100 ? 0 : value >= 10 ? 1 : 2}) + " " + unit;
}

function duration(seconds) {
  if (seconds < 90) return "about a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return "about " + minutes + " min";
  const hours = Math.floor(minutes / 60), rest = Math.round((minutes % 60) / 5) * 5;
  if (hours >= 48) return "about " + Math.round(hours / 24) + " days";
  return "about " + hours + " h" + (rest && hours < 10 ? " " + rest + " min" : "");
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

const sumBytes = assets => assets.reduce((sum, asset) => sum + asset.size_bytes, 0);
const hasRoute = (id, routes, published) => Boolean(routes[id]?.length || published.files?.[id]?.length);

const retentionCache = new WeakMap();
const planCeiling = profile => profile.capacity_bytes -
  Math.max(INDEX_ALLOWANCE, profile.reserve_bytes) - profile.discovery_budget_bytes;

function browserRetention(planner, routes, published) {
  const cached = retentionCache.get(planner);
  if (cached?.routes === routes && cached.published === published) return cached;
  const {transitions, fillers, expansion} = planner.capacity_policy;
  const bounds = [...new Set([...transitions, ...fillers, ...expansion].map(row => row[0]))].sort((a, b) => a - b);
  const profileAt = capacity => globalThis.OWLPlanner.profileFor(planner, planner.profiles[0].id, capacity);
  const assets = new Map(planner.assets.map(row => [row.id, row]));
  const resources = new Map(planner.resources.map(row => [row.id, row]));
  const members = (id, edition) => {
    const resource = resources.get(id);
    return (resource.editions?.[edition] || resource).asset_ids.filter(id => hasRoute(id, routes, published));
  };
  const rows = bounds.map(capacity => {
    const profile = profileAt(capacity);
    const editions = new Map(profile.default_resources.map(id => [id, profile.default_editions[id] || "published"]));
    const ids = new Set([...editions].flatMap(([id, edition]) => members(id, edition)));
    return {capacity, editions, ids, used: sumBytes([...ids].map(id => assets.get(id))), advanced: new Set(), extraBytes: 0};
  });
  const advances = [];
  const surveyed = new Set();
  for (const [index, row] of rows.entries()) {
    for (const [id, edition] of row.editions) {
      if (surveyed.has(id)) continue;
      surveyed.add(id);
      const resource = resources.get(id);
      const variant = resource.editions?.[edition] || resource;
      if (!index || resource.opt_in || resource.replaces_asset_ids?.length || variant.status !== "ready" ||
          rows.slice(index).some(later => later.editions.get(id) !== edition)) continue;
      const assetIds = members(id, edition);
      if (!assetIds.length || assetIds.some(id => assets.get(id).status !== "resolved" || assets.get(id).generation)) continue;
      const bytes = sumBytes(assetIds.map(id => assets.get(id)));
      let first = index;
      let capacity = row.capacity;
      // Admit an upcoming collection early only while every intervening
      // reviewed plan can keep it until its ordinary entry point.
      for (let i = index - 1; i >= 0; i--) {
        const earlier = rows[i];
        if (assetIds.some(id => earlier.ids.has(id) || earlier.advanced.has(id))) break;
        // Allow for one-byte discontinuities in the capacity allowances.
        const required = earlier.used + earlier.extraBytes + bytes + 8;
        let low = earlier.capacity, high = rows[i + 1].capacity;
        if (planCeiling(profileAt(high - 1)) < required) break;
        if (planCeiling(profileAt(low)) < required) {
          while (low < high) {
            const mid = low + Math.floor((high - low) / 2);
            if (planCeiling(profileAt(mid)) < required) low = mid + 1;
            else high = mid;
          }
        }
        first = i;
        capacity = low;
        if (capacity > earlier.capacity) break;
      }
      if (first === index) continue;
      advances.push({id, edition, assetIds, capacity, until: row.capacity});
      for (const earlier of rows.slice(first, index)) {
        earlier.extraBytes += bytes;
        for (const id of assetIds) earlier.advanced.add(id);
      }
    }
  }
  const result = {routes, published, advances};
  retentionCache.set(planner, result);
  return result;
}

export function recommendBrowser(planner, state, routes, published) {
  for (const resource of planner.resources) {
    const item = state.items[resource.id];
    if (!item.included) continue;
    const members = (resource.editions?.[item.edition] || resource).asset_ids;
    const reachable = members.filter(id => hasRoute(id, routes, published));
    if (reachable.length === 0) item.included = false;
    else if (reachable.length < members.length) item.assetIds = reachable;
  }
  const {advances} = browserRetention(planner, routes, published);
  const capacity = state.capacityBytes ??
    globalThis.OWLPlanner.profileFor(planner, state.profile).nominal_capacity_bytes;
  for (const {id, edition, assetIds, capacity: start, until} of advances) {
    if (start <= capacity && capacity < until) state.items[id] = {included: true, edition, assetIds};
  }
  return state;
}

// Platforms where extending a probe file allocates real clusters and fails past
// free space (docs/capacity-probe.md): macOS and Windows on exFAT or NTFS.
// Linux exFAT rejects the extension and ntfs-3g allocates sparsely, so Linux
// users confirm the label size instead.
export function probesCapacity(platform) {
  return /^(mac|win)/i.test(platform || "");
}


// Overall progress in bytes. The builder reports its file order once ("plan");
// later events carry a position in that order.
function progressTracker() {
  let files = [], total = 0, settled = 0, current = 0, position = -1;
  const samples = [];
  return {
    plan(rows) {
      files = rows;
      total = rows.reduce((sum, row) => sum + row.bytes, 0);
      settled = 0; current = 0; position = -1;
      samples.length = 0;
    },
    at(event, partBytes) {
      if (!files.length || event.position === undefined) return;
      if (event.position !== position) {
        settled = files.slice(0, event.position).reduce((sum, row) => sum + (row.skipped ? 0 : row.bytes), 0);
        position = event.position;
        current = files[position]?.done ? files[position].bytes : 0;
      }
      const row = files[position];
      if (!row) return;
      if (event.kind === "failed" || event.kind === "dropped") { row.skipped = true; current = 0; }
      else if (event.kind === "downloading") {
        current = Math.min(row.bytes, (event.count > 1 ? event.index * partBytes : 0) + event.received);
      }
      const now = performance.now();
      samples.push([now, settled + current]);
      while (samples.length > 2 && now - samples[0][0] > 45_000) samples.shift();
    },
    get total() { return total; },
    get done() { return Math.min(total, settled + current); },
    // Bytes per second over the last 45 seconds, once 8 seconds have been seen.
    get rate() {
      if (samples.length < 2) return 0;
      const [startTime, startBytes] = samples[0], [endTime, endBytes] = samples[samples.length - 1];
      return endTime - startTime < 8_000 ? 0 : Math.max(0, (endBytes - startBytes) / ((endTime - startTime) / 1000));
    }
  };
}

export function mount({catalog, recommend, ui}) {
  const {planner, routes, published, navigation} = catalog;
  const assets = new Map(planner.assets.map(asset => [asset.id, asset]));
  const readers = planner.resources.find(row => row.id === "archive-readers").asset_ids;
  const platform = navigator.userAgentData?.platform || navigator.platform;
  const android = /android/i.test(platform) || /android/i.test(navigator.userAgent);
  const supported = typeof globalThis.showDirectoryPicker === "function" && !android;
  const probeCapacity = probesCapacity(platform);
  const pick = byId("pick-drive"), pickInline = byId("pick-drive-inline"), change = byId("change-drive");
  const reconnect = byId("reconnect-drive");
  const start = byId("start-build"), resume = byId("resume-build"), pause = byId("pause-build");
  const verify = byId("verify-build"), verifyDone = byId("verify-build-done"), retry = byId("retry-build");
  const join = byId("join-archives"), consent = byId("accept-browser-files");
  const status = byId("drive-status"), feedback = byId("browser-build-status"), meter = byId("build-progress");
  const note = byId("build-note"), errors = byId("browser-build-errors");
  const WELCOME = status.textContent;
  const tracker = progressTracker();
  let drive, saved, measured, selection, latest, busy = false, cancel, remembered;
  let sizeSet = false, stage = "welcome";

  function go(next) {
    stage = next;
    ui.setStage(next);
    byId("build-stage").hidden = next !== "build";
    byId("done-stage").hidden = next !== "done";
    byId("phone-card").hidden = next !== "build" && next !== "done";
    globalThis.scrollTo?.({top: 0, behavior: "smooth"});
  }

  function describeDrive(detail, working = false) {
    byId("drive-card").hidden = !drive;
    if (!drive) return;
    byId("drive-name").textContent = drive.name;
    const dot = document.createElement("span");
    dot.className = "busy-dot";
    byId("drive-detail").replaceChildren(...(working ? [dot] : []), detail);
  }

  function refresh() {
    const preview = !drive;
    const needsConsent = Boolean(selection?.excluded.length || latest?.result.incomplete.length);
    for (const button of [pick, pickInline, change, reconnect]) button.disabled = !supported || busy;
    pickInline.hidden = !preview || !supported;
    start.hidden = preview;
    start.disabled = !supported || busy || preview || !sizeSet || Boolean(saved) || !(selection?.knowledgeBytes > 0) ||
      Boolean(selection?.over) || Boolean(latest?.result.errors.length) || (needsConsent && !consent.checked);
    // Say why Build is unavailable, or exactly what it will do.
    let message = "", attention = true;
    if (!supported) message = android ? "Building needs a computer. This page shows what a drive would hold." :
      "To build, open this page in Chrome, Edge or Arc on a computer.";
    else if (preview) { message = "This is a preview. Plug in a drive and choose it to build."; attention = false; }
    else if (!sizeSet) message = "Pick the size printed on your drive, above.";
    else if (selection?.over) message = "This is " + format(selection.over) + " more than the drive holds. Remove a collection or two.";
    else if (!(selection?.knowledgeBytes > 0)) message = "Add at least one collection.";
    else if (latest?.result.errors.length) message = "Fix the points above to continue.";
    else if (needsConsent && !consent.checked) message = "Tick “Build without them” to continue.";
    else {
      message = "Downloads " + format(selection.used) + " straight onto " + drive.name + ". Other files on the drive are left alone.";
      attention = false;
    }
    note.textContent = message;
    note.classList.toggle("attention", attention);
    pause.hidden = !cancel;
    resume.hidden = busy || !drive || !saved || saved.finished === true;
    verify.hidden = busy || !saved;
    byId("leave-build").hidden = busy;
    byId("keep-open").hidden = !busy;
    for (const button of [resume, verify, verifyDone, retry]) button.disabled = busy || !drive;
    join.disabled = busy || Boolean(saved);
    for (const id of ["presets", "custom-capacity"]) byId(id).inert = busy;
  }

  function update(result, state) {
    latest = {result, state};
    const allSelected = [...new Set([...result.selectedAssetIds, ...readers])].map(id => assets.get(id));
    const next = browserSelection(allSelected, routes, published);
    const profile = globalThis.OWLPlanner.profileFor(planner, state.profile, state.capacityBytes);
    const label = profile.nominal_capacity_bytes;
    const available = Math.min(measured ?? Infinity, profile.capacity_bytes);
    const reserve = Math.max(INDEX_ALLOWANCE, profile.reserve_bytes) + profile.discovery_budget_bytes;
    // If a marketed 16 GB drive has less than 16 GB free, apply the minimum
    // ladder then fit its ranked, untouched recommendation to measured bytes.
    const adjustedDefault = measured < planner.capacity_policy.min && !state.edited;
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
    const knowledge = next.assets.filter(isKnowledgeFile);
    const knowledgeBytes = sumBytes(knowledge);
    selection = {...next, over, used, knowledgeBytes, archiveSpace: available - reserve, searchBudget: profile.discovery_budget_bytes};
    const capacity = measured ?? label;
    ui.paintSummary({assets: next.assets, capacityBytes: capacity, over,
      driveLabel: measured !== undefined ? "free on " + drive.name : drive ? "on " + drive.name : "drive",
      countLabel: ui.plural(knowledge.length, "book, guide or archive", "books, guides and archives") +
        ", plus the Kiwix reader apps"});
    byId("browser-exclusions").hidden = !next.excluded.length && !result.incomplete.length;
    byId("browser-exclusions-title").textContent = next.excluded.length ?
      ui.plural(next.excluded.length, "selected file") + " cannot be downloaded in a browser" : "Some collections are incomplete";
    textList(byId("browser-exclusions-list"), next.excluded.map(row => row.title + " — " + row.reason));
    textList(byId("browser-plan-errors"), result.errors);
    byId("browser-plan-errors").hidden = result.errors.length === 0;
    refresh();
  }

  // Choosing a size is the confirmation when the drive could not be measured,
  // and opens a preview when no drive is attached.
  function sizeChosen() {
    sizeSet = true;
    byId("planner").classList.toggle("awaiting-size", false);
    if (drive && measured === undefined) describeDrive("Using the size you picked.");
    if (stage !== "welcome") return;
    ui.placeSizePicker(true, "Previewing a drive of:");
    go("plan");
  }

  function askForSize(reason) {
    sizeSet = false;
    describeDrive("Free space not measured." + reason);
    byId("planner").classList.toggle("awaiting-size", true);
    byId("size-slot").classList.toggle("needs-size", true);
    ui.placeSizePicker(true, "What size is this drive? Pick the size printed on it.");
    go("plan");
  }

  function showSaved() {
    go("build");
    tracker.plan(saved.plan.map(pin => ({id: pin.id, bytes: pin.bytes, done: Boolean(saved.verified[pin.id])})));
    // Finished files, plus the saved parts of the file that was in progress.
    const kept = saved.plan.reduce((sum, pin) => sum + (saved.verified[pin.id] ? pin.bytes :
      (saved.parts[pin.id] || []).reduce((bytes, part) => bytes + (part.bytes || 0), 0)), 0);
    byId("build-eyebrow").textContent = "Unfinished library";
    byId("build-heading").textContent = "Pick up where you left off on " + drive.name;
    paintProgress(kept, tracker.total, false);
    feedback.textContent = "This drive holds an unfinished library. Resume to download the rest; finished files are kept.";
    refresh();
  }

  function showDone({completed, missing = [], searchWarnings = [], existing = false} = {}) {
    go("done");
    const finished = saved?.finished === true;
    const outOfSpace = Object.keys(saved?.dropped || {}).length > 0;
    const pendingJoin = Object.keys(saved?.stagedArchives || {}).some(id => saved.verified[id]);
    const count = completed ?? saved.plan.filter(pin => saved.verified[pin.id]).length;
    const size = saved.plan.reduce((sum, pin) => sum + (saved.verified[pin.id] ? pin.bytes : 0), 0);
    byId("done-mark").classList.toggle("partial", !finished);
    byId("done-heading").textContent = existing ? "This drive already holds a library." :
      finished ? "Your library is ready." : "Your library works, with a few gaps.";
    byId("done-summary").textContent = ui.plural(count, "file") + ", " + format(size) +
      ", each one checked against its published fingerprint. It needs no internet from here on.";
    const problems = [...missing.map(row => row.title + " — " + row.reason), ...searchWarnings];
    byId("done-problem").hidden = finished;
    byId("done-problem-title").textContent = outOfSpace ? "The drive ran out of space" : pendingJoin ?
      "Some large archives are still in parts" : ui.plural(Math.max(problems.length, 1), "item") + " could not be finished";
    byId("done-problem-text").textContent = outOfSpace ? "Free some space on the drive, then try again for the files that did not fit." :
      pendingJoin ? "They are readable as they are. Free some space and try again to join each one into a single file." :
      "Everything else is on the drive and ready. Trying again only downloads what is missing.";
    textList(byId("done-issues"), problems);
    refresh();
  }

  async function identify(handle, probe) {
    drive = handle;
    saved = null;
    join.checked = true;
    measured = undefined;
    sizeSet = false;
    byId("returning").hidden = true;
    byId("probe-steps").hidden = true;
    byId("planner").classList.toggle("awaiting-size", false);
    byId("size-slot").classList.toggle("needs-size", false);
    status.textContent = "Reading " + handle.name + "…";
    try {
      if (!await hasDrivePermission(handle)) {
        drive = null;
        offerRemembered(handle);
        return;
      }
      saved = await readBuild(handle);
      if (saved) {
        describeDrive("Saved library");
        if (saved.finished) showDone({existing: true}); else showSaved();
        return;
      }
      let reason = "";
      if (probe && probeCapacity) {
        status.textContent = "Measuring free space on " + handle.name + "…";
        let capacity;
        // Each probe step is logged so a failed measurement can be diagnosed
        // from the browser console without extra tooling.
        const steps = byId("probe-list");
        steps.replaceChildren();
        const step = text => { const item = document.createElement("li"); item.textContent = text; steps.append(item); };
        const onAttempt = outcome => {
          console.info("[OWL capacity probe]", JSON.stringify(outcome));
          step(format(outcome.size) + ": " + (outcome.result === "fits" ? "fits" : outcome.result === "full" ? "too big" :
            outcome.result) + " (" + Math.round(outcome.duration) + " ms)");
        };
        try { capacity = await lockDrive(() => measureFreeSpace(handle, {onAttempt})); }
        catch (error) {
          console.warn("[OWL capacity probe] stopped:", error?.name, error?.message);
          step("Stopped: " + (error?.name || "error") + " " + (error?.message || ""));
          capacity = {kind: "manual"};
        }
        console.info("[OWL capacity probe] result", JSON.stringify(capacity));
        step("Result: " + (capacity.kind === "measured" ? format(capacity.bytes) + " free" : capacity.kind));
        byId("probe-steps").hidden = false;
        if (capacity.kind === "measured") {
          measured = capacity.bytes;
          sizeSet = true;
          describeDrive(format(measured) + " free, measured just now");
          ui.placeSizePicker(false);
          go("plan");
          recommend(Math.max(measured, planner.capacity_policy.min));
          return;
        }
        if (["fat32", "limited"].includes(capacity.kind)) join.checked = false;
        reason = capacity.kind === "fat32" ? " It looks like a FAT32 drive, so large archives will be saved in parts." :
          capacity.kind === "limited" ? " It may be a FAT32 drive or have less than 4 GB free." :
          capacity.kind === "sparse-or-large" ? " This drive reports more space than it can be checked for." : "";
      }
      askForSize(reason);
    } catch (error) {
      drive = null;
      describeDrive("");
      status.textContent = error.message + " Choose a folder on the attached drive.";
    }
    if (latest) update(latest.result, latest.state);
  }

  function offerRemembered(handle) {
    remembered = handle;
    byId("returning-text").textContent = "Welcome back. Last time you used the drive “" + handle.name + "”.";
    byId("returning").hidden = false;
  }

  async function choose(getHandle) {
    busy = true;
    consent.checked = false;
    refresh();
    try {
      const handle = await getHandle();
      if (!handle) return;
      feedback.textContent = "";
      await identify(handle, true);
      if (drive) void rememberDrive(handle).catch(() => {});
    } catch (error) {
      if (error.name !== "AbortError") status.textContent = error.message;
      else if (!drive) status.textContent = WELCOME;
    } finally {
      busy = false;
      refresh();
    }
  }
  for (const button of [pick, pickInline, change]) button.addEventListener("click", () => void choose(pickDrive));
  reconnect.addEventListener("click", () => void choose(async () =>
    await requestDrivePermission(remembered) === "granted" ? remembered : null));
  consent.addEventListener("change", refresh);

  function paintProgress(done, total, running = true) {
    const fraction = total ? done / total : 0;
    meter.max = 1;
    meter.value = fraction;
    byId("build-percent").textContent = Math.floor(fraction * 100) + "%";
    const rate = running ? tracker.rate : 0;
    byId("build-amount").textContent = format(done) + " of " + format(total) + (rate ? " · " + format(rate) + "/s" : "");
    byId("build-eta").textContent = rate && total > done ? duration((total - done) / rate) + " left" : "";
  }

  function phase(current) {
    const order = ["phase-download", "phase-index", "phase-ready"];
    for (const [index, id] of order.entries()) {
      byId(id).classList.toggle("is-current", index === current);
      byId(id).classList.toggle("is-done", index < current);
    }
  }

  const issues = new Map();
  let lastProgress = 0;
  function progress(event) {
    if (event.kind === "plan") { tracker.plan(event.files); paintProgress(tracker.done, tracker.total); return; }
    tracker.at(event, saved?.partBytes || PART_BYTES);
    if (event.kind === "waiting-network") {
      feedback.textContent = "Waiting for the internet connection. The build carries on by itself when it returns.";
    } else if (event.kind === "assembling") {
      phase(1);
      meter.removeAttribute("value");
      byId("build-percent").textContent = "Almost there";
      byId("build-amount").textContent = "";
      byId("build-eta").textContent = "";
      feedback.textContent = "Adding offline search and the start page…";
    } else if (event.kind === "downloading") {
      const now = performance.now();
      if (event.received && event.received < event.bytes && now - lastProgress < 250) return;
      lastProgress = now;
      paintProgress(tracker.done, tracker.total);
      feedback.textContent = "Downloading " + event.asset.title + " · file " + (event.position + 1).toLocaleString() +
        " of " + event.total.toLocaleString() + (event.count > 1 ? " · part " + (event.index + 1) + " of " + event.count : "");
    } else if (event.kind === "joining") {
      feedback.textContent = "Joining " + event.asset.title + " into one file…";
    } else if (event.kind === "checking") {
      feedback.textContent = "Checking the saved part of " + event.asset.title + "…";
    } else if (event.kind === "retrying") {
      feedback.textContent = "Trying another source for " + event.asset.title + "…";
    } else {
      issues.set(event.asset.id, event.asset.title + " — " + event.message);
      textList(errors, [...issues.values()]);
      byId("build-issues").hidden = false;
      byId("build-issues-title").textContent = ui.plural(issues.size, "file") + " skipped so far. The build continues.";
    }
  }

  async function run(isResume, fullVerify = false) {
    busy = true;
    go("build");
    phase(0);
    byId("build-eyebrow").textContent = "Step 3 of 3";
    byId("build-heading").textContent = (fullVerify ? "Checking every file on " : "Building your library on ") + drive.name;
    byId("build-issues").hidden = true;
    refresh();
    let releaseWakeLock;
    try {
      if (await requestDrivePermission(drive) !== "granted") throw Error("Allow this page to write to the drive, or choose the drive again.");
      cancel = new AbortController();
      refresh();
      releaseWakeLock = keepScreenAwake();
      feedback.textContent = isResume ? "Opening the saved library…" : "Getting started…";
      issues.clear();
      textList(errors, []);
      if (!isResume) tracker.plan(selection.assets.map(asset => ({id: asset.id, bytes: asset.size_bytes})));
      paintProgress(tracker.done, tracker.total);
      const network = createNetwork({signal: cancel.signal, probeURL: "./.nojekyll",
        onWaiting: () => progress({kind: "waiting-network"})});
      const [search, publisherPieces] = await Promise.all([
        network.retry(() => get("./search-build.json", cancel.signal)),
        network.retry(() => get("./kiwix-pieces.json", cancel.signal))
      ]);
      const result = await lockDrive(() => buildLibrary(drive, {...selection, catalogAssets: planner.assets,
        routes, published: {...published, publisherPieces}, navigation, search, network, resume: isResume, fullVerify, singleArchives: join.checked, signal: cancel.signal, onProgress: progress}));
      saved = result.state;
      phase(3);
      showDone({completed: result.completed.length, missing: result.missing, searchWarnings: result.searchWarnings});
    } catch (error) {
      byId("build-eyebrow").textContent = cancel?.signal.aborted ? "Paused" : "Stopped";
      if (tracker.total) paintProgress(tracker.done, tracker.total, false);
      feedback.textContent = cancel?.signal.aborted ? "Paused. Everything downloaded so far is saved on the drive." :
        error.message + " Reconnect the same drive if needed, then resume.";
      if (drive) {
        try { saved = await readBuild(drive); }
        catch (_) { /* Keep the handle so Resume can restore permission or report disconnection. */ }
      }
    } finally {
      releaseWakeLock?.();
      cancel?.abort();
      cancel = null;
      busy = false;
      refresh();
    }
  }

  start.addEventListener("click", () => void run(false));
  for (const button of [resume, retry]) button.addEventListener("click", () => void run(true));
  for (const button of [verify, verifyDone]) button.addEventListener("click", () => void run(true, true));
  pause.addEventListener("click", () => cancel?.abort());
  for (const id of ["leave-build", "build-another"]) byId(id).addEventListener("click", () => {
    drive = null; saved = null; measured = undefined; sizeSet = false;
    byId("planner").classList.toggle("awaiting-size", false);
    byId("size-slot").classList.toggle("needs-size", false);
    status.textContent = WELCOME;
    describeDrive("");
    ui.placeSizePicker(false, "No drive handy? See what fits on:");
    go("welcome");
    if (latest) update(latest.result, latest.state);
  });

  function ready() {
    if (!supported) {
      status.textContent = android ? "Building needs a computer. You can read a finished library on this device." :
        "To build onto a drive, open this page in Chrome, Edge or Arc on a computer. You can still see what fits below.";
      refresh();
      return;
    }
    void getRememberedDrive().then(async handle => {
      if (!handle || drive || busy) return;
      // A drive that is still authorized and holds an unfinished library goes
      // straight to Resume; anything else waits for the user to choose.
      const unfinished = await hasDrivePermission(handle) && await readBuild(handle).catch(() => null);
      if (drive || busy) return;
      if (unfinished && !unfinished.finished) { drive = handle; saved = unfinished; describeDrive("Saved library"); showSaved(); }
      else offerRemembered(handle);
    }).catch(() => {});
    refresh();
  }

  return {update, ready, sizeChosen, sizeIsSet: () => sizeSet, canDownload: id => hasRoute(id, routes, published),
    recommend: state => recommendBrowser(planner, state, routes, published)};
}
