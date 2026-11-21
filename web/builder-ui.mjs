import {createNetwork, SourceError} from "./network.mjs";
import {browserSelection, buildLibrary, isKnowledgeFile, readBuild} from "./builder.mjs";
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

const sumBytes = assets => assets.reduce((sum, asset) => sum + asset.size_bytes, 0);
const hasRoute = (id, routes, published) => Boolean(routes[id]?.length || published.files?.[id]?.length);

function attributedShares(asset) {
  if (!isKnowledgeFile(asset)) return [];
  const {domain, domain_weights: weights} = asset.selection;
  if (!weights) return [[domain, asset.size_bytes]];
  const weight = Object.values(weights).reduce((total, part) => total + part, 0);
  const shares = Object.keys(weights).sort().map(field => [field, Math.floor(asset.size_bytes * weights[field] / weight)]);
  const remainder = asset.size_bytes - shares.reduce((total, [, bytes]) => total + bytes, 0);
  for (let i = 0; i < remainder; i++) shares[i][1]++;
  return shares;
}

function attribute(ids, shares) {
  const totals = {};
  for (const id of ids) for (const [field, bytes] of shares.get(id)) {
    totals[field] = (totals[field] || 0) + bytes;
  }
  return totals;
}

const retentionCache = new WeakMap();

function browserRetention(planner, routes, published) {
  const cached = retentionCache.get(planner);
  if (cached?.routes === routes && cached.published === published) return cached;
  const {transitions, fillers, expansion, field_core: core} = planner.capacity_policy;
  const bounds = [...new Set([...transitions, ...fillers, ...expansion].map(row => row[0]))].sort((a, b) => a - b);
  const resources = new Map(planner.resources.map(row => [row.id, row]));
  const shares = new Map(planner.assets.map(asset => [asset.id, attributedShares(asset)]));
  const limits = new Map();
  const floors = Object.fromEntries(Object.keys(core).map(field => [field, Infinity]));
  for (const capacity of [...bounds].reverse()) {
    const profile = globalThis.OWLPlanner.profileFor(planner, planner.profiles[0].id, capacity);
    const ids = new Set(profile.default_resources.flatMap(id => {
      const resource = resources.get(id);
      return (resource.editions?.[profile.default_editions[id]] || resource).asset_ids;
    }).filter(id => hasRoute(id, routes, published)));
    const current = attribute(ids, shares);
    for (const field of Object.keys(core)) floors[field] = Math.min(floors[field], current[field] || 0);
    limits.set(capacity, {...floors});
  }
  const result = {routes, published, shares, bounds, limits};
  retentionCache.set(planner, result);
  return result;
}

export function recommendBrowser(planner, state, routes, published) {
  const {profileFor, resolve} = globalThis.OWLPlanner;
  const profile = profileFor(planner, state.profile, state.capacityBytes);
  const resolved = resolve(planner, state, {ignoreNativeCapacity: true});
  if (resolved.errors.length) return state;
  const selected = new Set(resolved.selectedAssetIds);
  const assets = new Map(planner.assets.map(asset => [asset.id, asset]));
  const available = [...selected].map(id => assets.get(id)).filter(asset => hasRoute(asset.id, routes, published));
  const ceiling = profile.capacity_bytes - Math.max(INDEX_ALLOWANCE, profile.reserve_bytes) - profile.discovery_budget_bytes;
  const target = Math.min(ceiling, Math.max(Math.floor(profile.nominal_capacity_bytes * 0.90),
    sumBytes([...selected].map(id => assets.get(id)))));
  let used = sumBytes(available);
  for (const resource of planner.resources) {
    const item = state.items[resource.id];
    if (!item.included) continue;
    const members = (resource.editions?.[item.edition] || resource).asset_ids;
    const reachable = members.filter(id => hasRoute(id, routes, published));
    if (reachable.length === 0) item.included = false;
    else if (reachable.length < members.length) item.assetIds = reachable;
  }
  if (used >= target) return state;
  const retention = browserRetention(planner, routes, published);
  const floors = retention.limits.get(retention.bounds.findLast(bound => bound <= profile.nominal_capacity_bytes));
  const fields = attribute(available.map(asset => asset.id), retention.shares);
  const candidates = planner.resources.flatMap(resource => {
    if (state.items[resource.id].included || resource.opt_in || resource.replaces_asset_ids?.length) return [];
    const variants = [["published", resource], ...Object.entries(resource.editions || {})];
    return variants.flatMap(([edition, variant]) => {
      if (variant.status !== "ready") return [];
      const members = variant.asset_ids.map(id => assets.get(id)).filter(asset =>
        asset.status === "resolved" && !asset.generation && hasRoute(asset.id, routes, published));
      return members.length ? [{id: resource.id, edition, members, bytes: sumBytes(members),
        ...(members.length < variant.asset_ids.length && {assetIds: members.map(asset => asset.id)})}] : [];
    });
  });
  const priority = new Map(planner.capacity_policy.transitions.map(([, id], index) => [id, index]));
  candidates.sort((a, b) => (priority.get(a.id) ?? Infinity) - (priority.get(b.id) ?? Infinity) ||
    a.bytes - b.bytes || a.id.localeCompare(b.id));
  function fits(candidate, limit = ceiling) {
    return !state.items[candidate.id].included && used + candidate.bytes <= limit &&
      !candidate.members.some(asset => selected.has(asset.id));
  }
  function add(candidate, additions) {
    for (const [field, bytes] of Object.entries(additions)) fields[field] = (fields[field] || 0) + bytes;
    state.items[candidate.id] = {included: true, edition: candidate.edition,
      ...(candidate.assetIds && {assetIds: candidate.assetIds})};
    for (const asset of candidate.members) selected.add(asset.id);
    used += candidate.bytes;
  }
  function fill(limit, stopAt, allowPartial) {
    for (const candidate of candidates) {
      if (used >= stopAt) break;
      if ((!allowPartial && candidate.assetIds) || !fits(candidate, limit)) continue;
      const additions = attribute(candidate.members.map(asset => asset.id), retention.shares);
      if (Object.entries(additions).some(([field, bytes]) => (fields[field] || 0) + bytes > 2 * floors[field])) continue;
      add(candidate, additions);
    }
  }
  // Keep the reviewed recommendation when its existing fillers reach 90%.
  const minimum = Math.floor(profile.nominal_capacity_bytes * 0.90);
  fill(target, target, false);
  if (used < minimum) fill(ceiling, minimum, true);
  if (used < minimum) {
    // Small title selections can be removed at the next edition step. Keep
    // the six protected fields on the reviewed capacity ladder in this pass.
    const protectedFields = new Set(planner.capacity_policy.protected_fields);
    const extras = candidates.filter(candidate => fits(candidate)).map(candidate => ({
      candidate, additions: attribute(candidate.members.map(asset => asset.id), retention.shares)
    })).filter(({additions}) => Object.keys(additions).every(field => !protectedFields.has(field)));
    extras.sort((a, b) => a.candidate.bytes - b.candidate.bytes);
    while (used < minimum) {
      const extra = extras.find(({candidate}) => fits(candidate) && used + candidate.bytes >= minimum)
        || extras.findLast(({candidate}) => fits(candidate));
      if (!extra) break;
      add(extra.candidate, extra.additions);
    }
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

export function mount({catalog, recommend}) {
  const {planner, routes, published, navigation} = catalog;
  const assets = new Map(planner.assets.map(asset => [asset.id, asset]));
  const readers = planner.resources.find(row => row.id === "archive-readers").asset_ids;
  const platform = navigator.userAgentData?.platform || navigator.platform;
  const android = /android/i.test(platform) || /android/i.test(navigator.userAgent);
  const supported = typeof globalThis.showDirectoryPicker === "function" && !android;
  const probeCapacity = probesCapacity(platform);
  const pick = byId("pick-drive");
  const confirmSize = byId("confirm-drive-size");
  const start = byId("start-build");
  const resume = byId("resume-build");
  const pause = byId("pause-build");
  const verify = byId("verify-build");
  const join = byId("join-archives");
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
    "Open this page in Chrome or Edge on a computer to choose a drive.";
  consent.addEventListener("change", () => refresh());

  function refresh() {
    pick.disabled = !supported || busy;
    start.disabled = !supported || busy || !drive || !confirmed || Boolean(saved) || !(selection?.knowledgeBytes > 0) ||
      Boolean(selection?.over) || Boolean(latest?.result.errors.length) ||
      Boolean((selection?.excluded.length || latest?.result.incomplete.length) && !consent.checked);
    pause.hidden = !cancel;
    verify.hidden = !saved || busy;
    verify.disabled = !drive || busy;
    join.disabled = busy || Boolean(saved);
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
    selection = {...next, over, knowledgeBytes, archiveSpace: available - reserve, searchBudget: profile.discovery_budget_bytes};
    const usedPercent = Math.min(100, 100 * used / available);
    byId("storage-fill").style.width = usedPercent + "%";
    byId("reserve-fill").style.width = "0%";
    byId("storage-meter").classList.toggle("over", over > 0);
    byId("capacity").textContent = format(available) + " available for planning";
    byId("knowledge-bytes").textContent = format(used);
    byId("browser-file-total").textContent = knowledge.length + " books, guides and collections";
    byId("status-title").textContent = result.errors.length ? "This selection needs changes" :
      knowledgeBytes ? "Browser selection ready" : "Choose a file the browser can download";
    byId("status-description").textContent = knowledgeBytes ? "Check the storage estimate before starting the build." :
      "The library needs at least one document or archive.";
    byId("meter-caption").textContent = over ? "Over by " + format(over) :
      (100 * used / label).toFixed(1) + "% of the drive label";
    byId("mobile-content").textContent = format(used);
    byId("mobile-status").textContent = over ? "Over budget" : "Fits";
    byId("mobile-budget").classList.toggle("has-errors", over > 0);
    byId("browser-exclusions").hidden = !next.excluded.length && !result.incomplete.length;
    byId("browser-exclusions-title").textContent = next.excluded.length ?
      next.excluded.length + " selected files unavailable in this browser" : "Some collections are incomplete";
    textList(byId("browser-exclusions-list"), next.excluded.map(row => row.title + " — " + row.reason));
    textList(byId("browser-plan-errors"), result.errors);
    byId("browser-plan-errors").hidden = result.errors.length === 0;
    refresh();
  }

  async function identify(handle, probe) {
    drive = handle;
    saved = null;
    join.checked = true;
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
        } else if (probe && probeCapacity) {
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
            if (["fat32", "limited"].includes(capacity.kind)) join.checked = false;
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
    if (event.kind === "waiting-network") {
      feedback.textContent = "Waiting for the internet connection. The build will resume automatically.";
    } else if (event.kind === "assembling") {
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
    } else if (event.kind === "joining") {
      feedback.textContent = "Joining " + event.asset.title + " into one archive…";
    } else if (event.kind === "checking") {
      feedback.textContent = "Checking saved parts of " + event.asset.title + "…";
    } else if (event.kind === "retrying") {
      feedback.textContent = "Retrying " + event.asset.title + ". " + event.message;
    } else {
      issues.set(event.asset.id, event.asset.title + " — " + event.message);
      textList(errors, [...issues.values()]);
    }
  }

  async function run(isResume, fullVerify = false) {
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
      const network = createNetwork({signal: cancel.signal, probeURL: "./.nojekyll",
        onWaiting: () => progress({kind: "waiting-network"})});
      const [search, publisherPieces] = await Promise.all([
        network.retry(() => get("./search-build.json", cancel.signal)),
        network.retry(() => get("./kiwix-pieces.json", cancel.signal))
      ]);
      const result = await lockDrive(() => buildLibrary(drive, {...selection, catalogAssets: planner.assets,
        routes, published: {...published, publisherPieces}, navigation, search, network, resume: isResume, fullVerify, singleArchives: join.checked, signal: cancel.signal, onProgress: progress}));
      saved = result.state;
      meter.max = 1;
      meter.value = 1;
      textList(errors, [...result.missing.map(row => row.title + " — " + row.reason), ...result.searchWarnings]);
      const ranOutOfSpace = Object.keys(saved.dropped).length > 0;
      feedback.textContent = ranOutOfSpace ?
        result.completed.length + " files verified. Free space on the drive and choose Resume to retry omitted files." : !saved.finished ?
        result.completed.length + " files verified. Open START_HERE.html on the drive. Choose Resume to retry failed downloads, or use the desktop tool." :
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
      cancel?.abort();
      cancel = null;
      busy = false;
      refresh();
    }
  }

  start.addEventListener("click", () => void run(false));
  resume.addEventListener("click", () => void run(true));
  verify.addEventListener("click", () => void run(true, true));
  pause.addEventListener("click", () => cancel?.abort());
  if (supported) {
    void getRememberedDrive().then(handle => {
      if (handle && !drive && !busy) return identify(handle, true);
    }).catch(() => {});
  }
  refresh();
  return {update, canDownload: id => hasRoute(id, routes, published),
    recommend: state => recommendBrowser(planner, state, routes, published)};
}
