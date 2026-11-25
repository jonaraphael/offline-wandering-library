import {createNetwork, SourceError} from "./network.mjs";
import {diag} from "./diagnostics.mjs";
import {activateReaderPreview, publishReaderLink} from "./reader-preview.mjs";
import {libraryArchive, localLibrary, removeLocalLibrary, withLocalLibrary} from "./local-library.mjs";
import {browserSelection, buildOrder, compareLibrary, DrivePathConflict, inspectDrive, isKnowledgeFile,
  LARGE_FILE_MESSAGE, PART_BYTES, reconcile, recordPause} from "./builder.mjs";
import {DriveBusy, driveBusyElsewhere, getRememberedDrive, hasDrivePermission, keepScreenAwake, lockDrive,
  measureFreeSpace, pickDrive, rememberDrive, requestDrivePermission} from "./drive.mjs";
import {isSmallRelayRoute, RELAY_WAIT_MESSAGE, RELAY_WAIT_REASON} from "./relay-wait.mjs";

const INDEX_ALLOWANCE = 16 * 2 ** 20;
const GB = 1e9;
const GiB = 2 ** 30;
const RELAY_PIECE_BYTES = 4 * 2 ** 20;
const RELAY_REQUEST_WARNING = 80_000;
const READERS = "archive-readers";
const READER_PUBLICATION = new URL(import.meta.url).searchParams.get("v");
// Errors from the drive itself, after which recent writes may not have reached it.
const DRIVE_FAULT = /NotFoundError|disconnected|InvalidStateError|NotReadableError|UnknownError/i;
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

export async function prepareDownloadSources(assets, {routes, published, network, signal, read = get}) {
  const unavailableSupport = [];
  const ranged = assets.filter(asset => asset.format === "zim" && asset.size_bytes > RELAY_PIECE_BYTES &&
    routes[asset.id]?.length);
  const archivesWithoutMetadata = new Set();
  const [search, publisherPieces] = await Promise.all([
    network.retry(() => read("./search-build.json", signal)).catch(error => {
      signal?.throwIfAborted();
      unavailableSupport.push({kind: "search", title: "Search index", reason: error.message});
    }),
    ranged.length && network.retry(() => read("./kiwix-pieces.json", signal)).catch(error => {
      signal?.throwIfAborted();
      for (const {id, size_bytes} of ranged) {
        if (size_bytes > PART_BYTES && !published.chunks?.[id]) archivesWithoutMetadata.add(id);
      }
    })
  ]);
  return {search, publisherPieces: publisherPieces || undefined, unavailableSupport, archivesWithoutMetadata};
}

export const archiveDriveOptions = (driveFormat, split) => ({
  singleArchives: driveFormat === "large" && !split,
  fat32: driveFormat === "fat32" || driveFormat === "large" && split
});

export async function load() {
  const [catalog, published] = await Promise.all([get("./catalog.json"), get("./chunk-manifests.json")]);
  return {...catalog, published};
}

const DAY = 86_400_000;

// The relay's free daily limit resets at midnight UTC; show that in local time.
export function slowRouteMessage(now = Date.now()) {
  const reset = new Date(Math.floor(now / DAY) * DAY + DAY).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
  return "The download relay isn’t answering, possibly because it reached today’s free limit, which resets at " + reset +
    ". Until it answers, archives come from the slower Kiwix mirror. Sync switches back by itself.";
}

// 42 -> "0:42", 3725 -> "1:02:05".
export function clock(seconds) {
  const total = Math.ceil(seconds), hours = Math.floor(total / 3600), minutes = Math.floor(total % 3600 / 60);
  const pad = value => String(value).padStart(2, "0");
  return (hours ? hours + ":" + pad(minutes) : minutes) + ":" + pad(total % 60);
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

const sumBytes = assets => assets.reduce((sum, asset) => sum + asset.size_bytes, 0);
const hasRoute = (id, routes, published) => Boolean(routes[id]?.length || published.files?.[id]?.length);
const isEssential = asset => asset?.status === "resolved" && asset.utility_tier === "CRITICAL";
const membersOf = (resource, edition) => (resource.editions?.[edition] || resource).asset_ids;

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
    const editions = new Map(profile.default_resources.filter(id => resources.has(id))
      .map(id => [id, profile.default_editions[id] || "published"]));
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

const isEncyclopedia = asset => asset.format.toLowerCase() === "zim";
const phoneSpace = (asset, phone) => asset.id === phone?.source_id && asset.sha256 === phone.source_sha256 ?
  phone.volumes.reduce((total, volume) => total + volume.bytes, 0) : 0;

export function selectBrowser(profile, resolved, {files, routes, published, kept, phone, minimum}) {
  const selected = resolved.selectedAssetIds.map(id => files.get(id));
  const {assets, excluded} = browserSelection(selected, routes, published);
  // A verified copy can stay even after its download route disappears.
  const keptIds = new Set(excluded.filter(row => kept(row.id)).map(row => row.id));
  for (const asset of selected) if (keptIds.has(asset.id)) assets.push(asset);
  const extraPhone = profile.nominal_capacity_bytes < minimum && phone ?
    assets.reduce((sum, asset) => sum + phoneSpace(asset, phone), 0) : 0;
  const searchBudget = profile.discovery_budget_bytes + extraPhone;
  const reserve = Math.max(INDEX_ALLOWANCE, profile.reserve_bytes) + searchBudget;
  const limit = planCeiling(profile) - extraPhone;
  const used = sumBytes(assets);
  const essentials = new Set(selected.filter(isEssential).map(asset => asset.id));
  return {assets, excluded: excluded.filter(row => !keptIds.has(row.id)), used, reserve, searchBudget,
    essentials, limit, over: Math.max(0, used - limit), errors: resolved.errors};
}

export function storageStops(capacity, canPlan = () => true) {
  const last = Math.min(capacity, 1000 * GB);
  const regular = [1, 8, 16, 32, ...Array.from({length: 30}, (_, index) => 64 + 32 * index)];
  return [...regular.map(gb => gb * GB).filter(stop => stop < last), last].filter(canPlan);
}

function reduceBrowser(planner, state, reachable, retained, phone) {
  const assets = new Map(planner.assets.map(asset => [asset.id, asset]));
  const available = id => assets.get(id)?.status === "resolved" && reachable(id) && (!retained || retained.has(id));
  const profile = globalThis.OWLPlanner.profileFor(planner, state.profile, state.capacityBytes, state);
  const room = planCeiling(profile);
  const readerIds = planner.resources.find(resource => resource.id === READERS)?.asset_ids || [];
  const readersAvailable = readerIds.length > 0 && readerIds.every(available);
  const readersBytes = readersAvailable ? sumBytes(readerIds.map(id => assets.get(id))) : 0;
  const collections = new Map();
  for (const resource of planner.resources) {
    if (resource.id === READERS) continue;
    const item = state.items[resource.id];
    if (!item.included && !retained) continue;
    const variant = edition => membersOf(resource, edition).filter(available);
    let ids = variant(item.edition);
    // A lower limit on a synced drive keeps the editions already present.
    if (retained) for (const edition of ["published", ...Object.keys(resource.editions || {})]) {
      const existing = variant(edition);
      if (existing.length <= ids.length) continue;
      ids = existing;
      item.edition = edition;
    }
    collections.set(resource.id, ids);
  }
  const chosen = new Set();
  const candidates = new Map([...new Set([...collections.values()].flat())].map(id => [id, assets.get(id)]));
  let used = 0, needsReaders = false;
  for (const asset of buildOrder(candidates.values(), {transfer: false})) {
    if (chosen.has(asset.id) || asset.generation) continue;
    const sourceId = asset.archive_member?.source_asset_id;
    const source = candidates.get(sourceId);
    if (sourceId && !source) continue;
    // A dependent file pays for its ZIP source or reader apps on first use.
    const encyclopedia = isEncyclopedia(asset);
    const cost = asset.size_bytes + (encyclopedia && !needsReaders ? readersBytes : 0) +
      (source && !chosen.has(source.id) ? source.size_bytes : 0) +
      (state.capacityBytes < planner.capacity_policy.min ? phoneSpace(asset, phone) : 0);
    if (used + cost > room || (encyclopedia && !readersAvailable)) continue;
    chosen.add(asset.id);
    if (source) chosen.add(source.id);
    used += cost;
    needsReaders ||= encyclopedia;
  }
  for (const [id, ids] of collections) {
    const item = state.items[id];
    item.assetIds = ids.filter(id => chosen.has(id));
    item.included = item.assetIds.length > 0;
  }
  return state;
}

export function recommendBrowser(planner, state, routes, published, kept = () => false, {retainedFiles, phone} = {}) {
  const reachable = id => hasRoute(id, routes, published) || kept(id);
  const unreachable = new Set(planner.assets.filter(asset => isEssential(asset) && !reachable(asset.id)).map(asset => asset.id));
  if (state.browser && (retainedFiles || state.capacityBytes < planner.capacity_policy.min)) {
    const retained = retainedFiles && new Set(retainedFiles);
    const intended = unreachable.size && reduceBrowser(planner, structuredClone(state), () => true, retained, phone);
    reduceBrowser(planner, state, reachable, retained, phone);
    // Keep the intended essentials in the selection even though they consume no download space.
    if (intended) for (const resource of planner.resources) {
      const wanted = intended.items[resource.id];
      if (!wanted.included) continue;
      const missing = (wanted.assetIds || membersOf(resource, wanted.edition)).filter(id => unreachable.has(id));
      if (!missing.length) continue;
      const item = state.items[resource.id];
      if (!item.included) state.items[resource.id] = {...wanted, assetIds: missing};
      else if (item.edition === wanted.edition) item.assetIds = [...new Set([...item.assetIds, ...missing])];
    }
    return state;
  }
  for (const resource of planner.resources) {
    const item = state.items[resource.id];
    if (!item.included) continue;
    const members = membersOf(resource, item.edition);
    const found = members.filter(id => reachable(id) || unreachable.has(id));
    if (found.length === 0) item.included = false;
    else if (found.length < members.length) item.assetIds = found;
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
// users enter free space or confirm the label size for an estimate.
export function probesCapacity(platform, agent = "") {
  if (/linux|android/i.test(platform || agent)) return false;
  return /^(mac|win)/i.test(platform || "") || /Macintosh|Windows/i.test(agent);
}

export const estimateLabelCapacity = labelBytes => Math.floor(labelBytes * 0.9);

export function reportedDriveCapacity(free, unit, heldBytes) {
  const bytes = Math.floor(free * (unit === "GiB" ? GiB : GB)) + heldBytes;
  if (free >= 0 && Number.isSafeInteger(bytes)) return bytes;
}

export function relayLimitMessage(adds, routes, published) {
  let requests = 0;
  for (const {asset, bytes} of adds) {
    if (!bytes) continue;
    if (asset.format === "zim") {
      if (published.archiveRelay?.[asset.id]?.length) requests += Math.ceil(bytes / RELAY_PIECE_BYTES);
    } else if (routes[asset.id]?.some(url => isSmallRelayRoute(url, asset.id))) {
      // Pages publishes each smaller relay file at /assets/<id>.
      requests++;
    }
  }
  return requests > RELAY_REQUEST_WARNING ?
    "Large libraries can take more than a day through the download relay, and the command-line builder has no daily download limit." : "";
}

const WELCOME = "Any USB drive or SD card with 16 GB to 1 TB free. Files already on it stay.";
const rememberedKey = () => "owl-last-sync:" + location.pathname.replace(/(?:index|builder)\.html$/, "");
const driveName = handle => handle?.name || "Your drive";
const dateOf = value => value ? new Date(value).toLocaleDateString("en-GB", {day: "numeric", month: "long", year: "numeric"}) : "";
const countOf = (count, noun) => count.toLocaleString() + " " + noun + (count === 1 ? "" : "s");
const partsMessage = rows => rows?.length ? countOf(rows.length, "encyclopedia") + " kept in parts." : "";
export function essentialRouteMessage(excluded) {
  const count = excluded.filter(row => row.utility_tier === "CRITICAL").length;
  return count ? "This browser can’t download " + countOf(count, "essential file") + ". Use the Python builder to get " +
    (count === 1 ? "it." : "them.") : "";
}

export function removedEssentialMessage(previous, selected) {
  const count = [...previous].filter(id => !selected.has(id)).length;
  return count ? "You removed " + countOf(count, "essential file") + "." : "";
}

export function warnBeforeLeaving(target = globalThis) {
  const warn = event => {
    event.preventDefault();
    event.returnValue = true;
  };
  target.addEventListener("beforeunload", warn);
  return () => target.removeEventListener("beforeunload", warn);
}

export function completionState({state, completed, missing, searchWarnings, supportMissing, keptInParts, keptPublished}) {
  const files = completed.filter(isKnowledgeFile).length;
  const apps = supportMissing?.filter(row => row.kind === "app").length || 0;
  const unavailable = missing.length + apps;
  const essential = missing.filter(row => row.utility_tier === "CRITICAL").length;
  const summary = [countOf(files, "file") + " arrived. " + countOf(essential, "essential file") + " missing.",
    essentialRouteMessage(state.excluded || [])].filter(Boolean).join(" ");
  const generalSupport = (supportMissing ? supportMissing.some(row => row.kind !== "phone" && row.kind !== "app") : searchWarnings.length) ?
    keptPublished ? " Some reader or search files are missing from this update. The previous library is still on the drive." :
      " Some reader or search files are missing." : "";
  const phoneSupport = supportMissing?.some(row => row.kind === "phone") ? " Some WikiMed phone files are missing." : "";
  const appSupport = apps ? " Kiwix opens the encyclopedias on this drive." : "";
  const deferred = state.relayDeferred?.length;
  const relaySupport = deferred ? " " + countOf(deferred, "file") +
    (deferred === 1 ? " is " : " are ") + RELAY_WAIT_REASON + "." : "";
  const support = appSupport + generalSupport + phoneSupport + relaySupport;
  if (!files) return {mode: "failed", title: "Sync could not finish", message: summary + support};
  const splitMessage = state.largeFileLimited && keptInParts.length ? LARGE_FILE_MESSAGE : partsMessage(keptInParts);
  if (state.finished && !unavailable) return {mode: "done", extra: splitMessage};
  return {mode: "done-gaps", title: unavailable ? "Ready, with " + countOf(unavailable, "item") + " missing" :
    "Ready, with some files missing", message: [summary + support, splitMessage].filter(Boolean).join(" ")};
}

const canTryLibrary = mode => mode === "done" || mode === "done-gaps";
const ratio = (done, total) => total ? Math.max(0, Math.min(1, done / total)) : 0;
const readerTitles = new Map([
  ["kiwix_android", "Kiwix reader app for Android"], ["kiwix_linux", "Kiwix reader app for Linux"],
  ["kiwix_macos", "Kiwix reader app for Mac"], ["kiwix_windows", "Kiwix reader app for Windows"]
]);

export function mount({catalog: supplied} = {}) {
  const {create, meter, bytes, sizesInto, title, link, element, how} = globalThis.OWLManage;
  const stage = byId("sync-stage"), headline = byId("sync-title"), status = byId("sync-status");
  const announcement = byId("sync-announcement");
  const primary = byId("sync-primary"), secondary = byId("sync-secondary"), ring = byId("sync-ring");
  const freeForm = byId("drive-free-form"), freeField = byId("drive-free-space"), freeUnit = byId("drive-free-unit");
  const formatQuestion = byId("drive-format-question"), formatField = byId("drive-format");
  const tryLink = element("a", "primary", "Try it");
  tryLink.target = "_blank";
  tryLink.rel = "noopener";
  // Diagnostics for debugging, out of the way in the page's bottom corner.
  byId("debug-corner")?.addEventListener("click", () => debug());
  const platform = navigator.userAgentData?.platform || navigator.platform || "";
  const agent = navigator.userAgent || "";
  const desktop = !/android|iphone|ipad|ipod|mobile/i.test(agent) &&
    !(navigator.maxTouchPoints > 1 && /^mac/i.test(platform));
  const direct = desktop && typeof globalThis.showDirectoryPicker === "function";
  const local = desktop && !direct && typeof navigator.storage?.getDirectory === "function" &&
    typeof navigator.storage.estimate === "function" && typeof navigator.locks?.request === "function" &&
    typeof globalThis.FileSystemFileHandle?.prototype.createWritable === "function";
  let exportFrom;
  if (local) {
    tryLink.textContent = "Download library (.tar)";
    tryLink.download = "Offline Wandering Library.tar";
    tryLink.removeAttribute("target");
    byId("sync-rail").firstElementChild.textContent = "Build locally";
    byId("sync-rail").lastElementChild.textContent = "Download";
    byId("keep-card").textContent = "Keep this tab open while OWL saves files on this computer.";
  }
  let catalog, manage, catalogRequest, drive, remembered, snapshot, inspection, comparison, plan, pendingCompare;
  const collectionTitles = new Map();
  const essentialStatus = element("p", "field-help");
  essentialStatus.setAttribute("role", "status");
  essentialStatus.hidden = true;
  byId("collection-search").before(essentialStatus);
  let managePlan, manageBudget, manageEssentials;
  let measured, reported = false, minimum, capacity, driveFormat = "unknown", detectedFormat, size, mode, previousMode, problem, result,
    controller, opened = 0;
  let operation = 0, picker = false, preview = false, fullCheck = false, selectedReplacement = new Set();
  let slowCheck = false, slowTimer, checkProgress, checkStarted;
  // Time left in a long check, from its average speed so far.
  const checkLeft = () => {
    const seconds = (performance.now() - checkStarted.at) / 1000;
    const done = checkProgress.checked - checkStarted.checked;
    return seconds > 10 && done > 0 ? duration((checkProgress.total - checkProgress.checked) / (done / seconds)) + " left" : "estimating time";
  };
  let active = new Map(), transferTotal = 0, transferStarted, rateStart, rateBytes, rate = 0, nowTitle = "", lastPaint = 0;
  let dirty = false, finishing = false, driveChoice, relayTryNow, manageAfterPause = false;
  // Archive id -> whether its pieces come through the relay or the fastest route.
  let routeFast = new Map(), currentAsset;
  // Pause stops new downloads at once (drain) and pauses at the next save
  // point, so nothing downloaded is lost. While it waits, the button fills as
  // the download in progress is saved and reads "Pause immediately (lose …)",
  // which stops at once.
  // saving: what the download in progress would lose and still needs to arrive.
  // pauseBatch: its bytes when Pause was clicked; pauseFill: the share saved.
  // discarded: the bytes "Pause immediately" threw away, for the paused message.
  let drainController, pausing = false, pauseTick, pauseBatch, pauseFill = 0, saving, discarded = 0;
  how();
  try { snapshot = JSON.parse(localStorage.getItem(rememberedKey())); } catch {}

  function init() {
    if (catalogRequest) return catalogRequest;
    catalogRequest = (supplied ? Promise.resolve(supplied) : load()).then(data => {
      catalog = data;
      const {planner, routes, published} = catalog;
      const files = new Map(planner.assets.map(asset => [asset.id, asset]));
      for (const resource of planner.resources) {
        const name = title(planner, resource);
        if (name === resource.id) continue;
        for (const edition of [resource, ...Object.values(resource.editions || {})]) {
          for (const id of edition.asset_ids) {
            const file = files.get(id);
            if (!file || collectionTitles.has(id)) continue;
            if (!file.title || file.title === id || (edition.asset_ids.length === 1 && planner.collection_copy?.[resource.id])) {
              collectionTitles.set(id, name);
            }
          }
        }
      }
      const kept = id => Boolean(inspection?.availableInstalled.has(id) || inspection?.candidates?.has(id));
      const phone = catalog.navigation?.phone;
      const sources = {files, routes, published, kept, phone, minimum: planner.capacity_policy.min};
      manage = create(planner, {
        browser: true,
        // Manage must allow a selected essential to be removed even when its route is unavailable.
        download: id => isEssential(files.get(id)) || hasRoute(id, routes, published) || kept(id),
        recommend: (state, retainedFiles) => recommendBrowser(planner, state, routes, published, kept, {retainedFiles, phone}),
        stops: storageStops,
        useful: selection => selection.assets.some(isKnowledgeFile),
        select: (profile, _state, resolved) => selectBrowser(profile, resolved, sources),
        onChange(value, {live = false} = {}) {
          managePlan = value;
          if (!byId("manage").hidden) showEssentialStatus();
          if (preview) return;
          plan = value;
          dirty = JSON.stringify(value.choice) !== driveChoice;
          if (live) {
            ++operation;
            pendingCompare = undefined;
            byId("manage-changes").textContent = value.over ? bytes(value.over) + " over" : dirty ? "Your changes" : "No changes";
            return;
          }
          if (value.over) {
            ++operation;
            pendingCompare = undefined;
            byId("manage-changes").textContent = bytes(value.over) + " over";
            return;
          }
          const pending = updateComparison();
          pendingCompare = pending;
          void pending.then(() => {
            if (pending !== pendingCompare) return;
            byId("manage-changes").textContent = dirty ? changeLine("Your changes") : "No changes";
            showHeld();
          }).catch(showProblem);
        },
        onSize: value => { capacity = value * 1e9; size = value; configure(true); showManage(); },
        onDiagnostics: debug
      });
      return data;
    }).catch(error => { catalogRequest = null; throw error; });
    return catalogRequest;
  }

  const capacityForPlan = () => capacity ?? 64e9;
  const effectiveFree = () => Math.max(0, capacityForPlan() - (inspection?.heldBytes || 0));
  const catalogVersion = () => catalog.version || [catalog.planner.catalog_sha256, catalog.planner.resources_sha256].join(":");
  const name = () => local ? "Local library" : driveName(drive || remembered);
  const available = () => plan && !plan.over && !plan.errors.length && plan.assets.some(isKnowledgeFile);
  const comparisonOptions = () => ({assets: plan.assets, choice: plan.choice, catalogVersion: catalogVersion(),
    navigation: catalog.navigation, readerPublication: READER_PUBLICATION,
    ...archiveDriveOptions(driveFormat, plan.choice.split), freeBytes: effectiveFree(), archiveSpace: plan.capacity - plan.reserve});
  const totalDone = () => [...active.values()].reduce((sum, count) => sum + count, 0);
  // A side with nothing to do is left out: "removes 3.57 GB", not "adds 0 B, removes 3.57 GB".
  const changeLine = prefix => {
    const adds = comparison?.addBytes || 0, removes = comparison?.removeBytes || 0;
    const parts = [adds && "adds " + bytes(adds), removes && "removes " + bytes(removes)].filter(Boolean);
    return prefix + ": " + (parts.join(", ") || "nothing to add or remove") + ".";
  };
  const percent = value => Math.floor(value * 100) + "%";
  const changeDrive = local ? openLocal : () => void choose(pickDrive);
  const reconnect = () => void choose(async () => {
    if (await requestDrivePermission(remembered) !== "granted") throw new DOMException("Permission was refused", "NotAllowedError");
    return remembered;
  });
  const openManage = () => void enterManage().catch(showProblem);
  const verify = () => void run(true);
  const sync = () => void run();
  function clearPause() {
    clearInterval(pauseTick);
    pausing = false;
    pauseTick = pauseBatch = undefined;
    pauseFill = 0;
  }
  const pauseNow = () => { clearPause(); controller?.abort(); };
  // Seconds until the download in progress reaches a save point, from the
  // builder's last estimate; undefined while its speed is unknown.
  function secondsToSave() {
    if (!saving?.toSave) return 0;
    if (saving.seconds === undefined) return undefined;
    return Math.max(0, saving.seconds - (performance.now() - saving.at) / 1000);
  }
  // Share of the download in progress at the Pause click that is saved. Once
  // drained, its bytes still to arrive only shrink; the share never goes back.
  function savedShare() {
    if (saving && pauseBatch) pauseFill = Math.max(pauseFill, Math.min(1, 1 - saving.toSave / pauseBatch));
    return pauseFill;
  }
  function pauseMessage() {
    const seconds = secondsToSave();
    return "Pausing " + (seconds >= 1 ? "in about " + clock(seconds) + ", " : "") + "once the download in progress is saved.";
  }
  function pause() {
    if (!controller) return;
    if (pausing) discarded = saving?.lost || 0;
    if (pausing || mode !== "syncing" || !saving?.lost) return pauseNow();
    drainController?.abort();
    pausing = true;
    pauseBatch = saving.lost + saving.toSave;
    pauseFill = 0;
    pauseTick = setInterval(() => { if (mode === "syncing") render("syncing"); }, 500);
    render("syncing");
    announcement.textContent = pauseMessage();
    diag("pause", {lost: saving.lost, toSave: saving.toSave, seconds: secondsToSave()});
  }
  const pauseToManage = () => { manageAfterPause = true; pauseNow(); };
  const enterFreeSpace = () => { render("needs-free-space"); freeField.focus(); };
  const showOpenInstructions = () => {
    byId("open-library-instructions").textContent = "In Files or Finder, open " + name() + ", then open START_HERE.html.";
    byId("open-library").showModal();
  };
  const manageLink = ["Manage what goes on it", openManage];
  const checkLink = ["Check every file", verify];
  const seeLink = ["See what goes on a drive", openManage];
  const cli = ["Build with the command line", null, byId("how").querySelector("a").href];
  const installKiwix = ["Install Kiwix while online", null, "https://kiwix.org/"];
  const freeSpaceLink = ["This drive already has files", enterFreeSpace];

  function releaseArchive() {
    if (local && tryLink.hasAttribute("href")) URL.revokeObjectURL(tryLink.href);
    tryLink.removeAttribute("href");
  }

  async function prepareArchive() {
    exportFrom = mode;
    releaseArchive();
    render("preparing-download");
    try {
      const archive = await withLocalLibrary(() => libraryArchive(drive));
      tryLink.href = URL.createObjectURL(archive);
      render("download");
    } catch (error) { showProblem(error); }
  }

  async function clearLocal() {
    if (!confirm("Delete the library stored in this browser, including any unfinished downloads?")) return;
    render("clearing");
    try {
      await withLocalLibrary(() => removeLocalLibrary(drive));
      releaseArchive();
      drive = remembered = inspection = comparison = plan = result = snapshot = undefined;
      render("empty");
    } catch (error) { showProblem(error); }
  }

  freeField.oninput = freeUnit.onchange = () => freeField.setCustomValidity("");
  freeForm.onsubmit = event => {
    event.preventDefault();
    const value = reportedDriveCapacity(freeField.valueAsNumber, freeUnit.value, inspection.heldBytes);
    if (value === undefined) {
      freeField.setCustomValidity("Enter the free space shown for this drive.");
      freeField.reportValidity();
      return;
    }
    reported = true;
    size = undefined;
    driveFormat = detectedFormat || formatField.value;
    render("measuring");
    void planDrive(value).catch(showProblem);
  };

  function debug() {
    byId("technical-detail").textContent = problem?.detail || "";
    diag("view-diagnostics", {drive: drive?.name, state: mode});
    byId("technical").showModal();
  }

  function render(next = mode) {
    if (next === "measuring" && mode !== "measuring") {
      clearTimeout(slowTimer);
      slowCheck = false;
      slowTimer = setTimeout(() => { if (mode === "measuring") { slowCheck = true; render(); } }, 8000);
    } else if (next !== "measuring") clearTimeout(slowTimer);
    mode = next;
    const readyFraction = ratio(comparison?.presentBytes || 0, plan?.used || 0);
    const syncFraction = ratio(totalDone(), transferTotal) || (transferTotal ? 0 : readyFraction);
    const lastDate = dateOf(inspection?.state?.syncedAt || snapshot?.syncedAt);
    const item = {step: 1, fraction: 0, title: name(), message: "", links: [], chart: true};
    const pick = ["Choose another drive", changeDrive];
    const different = ["Choose a different drive", changeDrive];
    const reconnectButton = ["Reconnect " + name(), reconnect];
    const syncButton = ["Sync", sync];
    switch (mode) {
      case "empty":
        Object.assign(item, local ? {title: "Build a library on this computer", chart: false,
          action: ["Open local builder", changeDrive], links: [seeLink, cli],
          message: "Sync saves files in this browser. Download the finished library, then extract it onto your drive."} :
          {title: "Plug in a drive", chart: false, action: ["Choose drive", changeDrive], links: [seeLink],
            message: WELCOME + (picker ? " In the window that opens, click the drive’s name, then Open." : "")});
        break;
      case "remembered":
        Object.assign(item, {message: lastDate ? "Last synced " + lastDate + "." : "Reconnect to see what is on this drive.",
          chart: Boolean(snapshot?.amounts), action: reconnectButton, links: [["Use a different drive", changeDrive]]});
        break;
      case "measuring":
        Object.assign(item, {message: checkProgress || slowCheck ? "Checking the files already on the drive…" : "Measuring free space…",
          extra: checkProgress ? "Checked " + bytes(checkProgress.checked) + " of " + bytes(checkProgress.total) +
            (checkProgress.checked && checkStarted ? " · " + checkLeft() : "") + ". Nothing on the drive changes." :
            slowCheck ? "A large drive can take several minutes. Nothing on it changes." : undefined, links: [different]});
        break;
      case "needs-size":
        Object.assign(item, {message: "For a new or empty drive, use the number printed on it.",
          chart: false, links: [freeSpaceLink, different]});
        break;
      case "needs-free-space":
        Object.assign(item, {message: "In Files or Finder, select the drive and choose Get Info or Properties to see how much space is free.",
          chart: false, links: [["Use the printed drive size", () => render("needs-size")], different]});
        break;
      case "ready":
        Object.assign(item, {step: 2, action: syncButton, links: [manageLink, different],
          message: (measured !== undefined && plan.budget === plan.capacity ? bytes(effectiveFree()) + " free. " : "") +
            "The recommended library uses " + bytes(plan.used) + ": " +
            plan.assets.filter(isKnowledgeFile).length.toLocaleString() + " books, manuals and courses."});
        break;
      case "behind":
        Object.assign(item, {step: 2, fraction: readyFraction, action: syncButton, links: [manageLink, different],
          message: comparison?.adoption ? "A library is already on this drive. Sync keeps files that match." :
            comparison?.changedChoice || dirty ? changeLine("Your changes") :
            comparison?.state?.syncedAt ? (comparison.workCount ?
              changeLine(countOf(comparison.workCount, "update")) : comparison.joins.length ?
                "Sync joins the files kept in parts." : "Sync refreshes the start page.") +
              (lastDate ? " Last synced " + lastDate + "." : "") :
            "Unfinished: " + bytes(comparison?.addBytes || 0) + " to go."});
        break;
      case "current":
        Object.assign(item, {step: 3, fraction: 1, title: "Up to date", links: [manageLink, checkLink, different],
          message: (lastDate ? "Synced " + lastDate + ". " : "") + countOf(plan.assets.length, "item") + ", " + bytes(plan.used) + ".",
          extra: partsMessage(inspection.state?.keptInParts)});
        break;
      case "syncing": {
        Object.assign(item, {step: 2, fraction: syncFraction, title: percent(syncFraction),
          action: pausing ? ["Pause immediately" + (saving?.lost ? " (lose " + bytes(saving.lost) + " progress)" : ""), pause, true] :
            ["Pause", pause, true],
          fill: pausing ? savedShare() : undefined,
          message: pausing ? pauseMessage() : bytes(totalDone()) + " of " + bytes(transferTotal || plan.used) +
            (rate && transferTotal > totalDone() ? " · " + duration((transferTotal - totalDone()) / rate) + " left" : "") +
            (rate ? " · " + bytes(rate) + "/s" : ""),
          extra: nowTitle && "Now: " + nowTitle, route: currentAsset && routeFast.get(currentAsset)});
        break;
      }
      case "waiting":
        Object.assign(item, {step: 2, fraction: syncFraction, title: percent(syncFraction), action: ["Pause", pause, true],
          message: "Waiting for the internet. Sync continues by itself."});
        break;
      case "waiting-relay":
        Object.assign(item, {step: 2, fraction: syncFraction, title: "Waiting for the download relay",
          action: ["Pause", pause, true], links: [["Try now", () => relayTryNow?.()], ["Manage what goes on it", pauseToManage]],
          message: RELAY_WAIT_MESSAGE});
        break;
      case "finishing":
        Object.assign(item, {step: 2, fraction: 1, title: "Finishing", message: "Building the search index and the start page."});
        break;
      case "paused":
        Object.assign(item, {step: 2, fraction: readyFraction, title: "Paused at " + percent(readyFraction), action: syncButton,
          message: inspection?.state?.relayDeferred?.length ?
            "Files are waiting for the download relay. Choose Sync to continue." :
            discarded ? "Sync continues from the last saved point." : "Nothing is lost. Sync continues where it stopped.", links: [manageLink, different]});
        break;
      case "done":
        Object.assign(item, {step: 3, fraction: 1, title: "Ready",
          message: tryLink.hasAttribute("href") ? "Open your library on " + name() + "." : "Open START_HERE.html on " + name() + ".",
          extra: completionState(result).extra || undefined,
          links: [checkLink, ...(result.keptInParts.length ? [["Show files kept in parts", showMissing]] : []),
            ["Sync another drive", changeDrive]]});
        break;
      case "failed":
      case "done-gaps": {
        const outcome = completionState(result);
        const appsMissing = result.supportMissing.some(row => row.kind === "app");
        Object.assign(item, {step: mode === "failed" ? 2 : 3, fraction: mode === "failed" ? 0 : 1,
          title: outcome.title, message: outcome.message, action: mode === "failed" ? ["Try those again", sync] : undefined,
          links: [...(mode === "done-gaps" ? [["Try those again", sync]] : []),
            ...(appsMissing ? [installKiwix] : []), ["Show details", showMissing], checkLink, ["Sync another drive", changeDrive]]});
        break;
      }
      case "problem":
        Object.assign(item, {step: 2, fraction: syncFraction, title: problem.title, message: problem.message,
          chart: Boolean(plan), action: problem.action, links: [
            ...(problem.full && inspection && measured === undefined ? [["Update free space", enterFreeSpace]] : []),
            ...(problem.action?.[1] === changeDrive ? [] : [different])]});
        break;
      case "too-small":
        Object.assign(item, {title: "Not enough room", chart: false, action: pick,
          message: "OWL needs at least " + bytes(minimum) + " free. " +
            (measured !== undefined ? "This drive has " + bytes(measured) + "." :
              (reported ? "You entered " : "This plan estimates ") + bytes(effectiveFree()) + " free.")});
        break;
      case "unsupported":
        Object.assign(item, {chart: false, title: "Build your library on a computer",
          message: "Use a desktop browser with writable storage, or build with the command line.",
          action: ["Copy link", copyLink], links: [seeLink, cli]});
        break;
      case "preparing-download":
      case "clearing":
        Object.assign(item, {step: 3, chart: false,
          title: mode === "clearing" ? "Clearing the local copy…" : "Preparing your download…"});
        break;
      case "download":
        Object.assign(item, {step: 3, fraction: 1, chart: false, title: "Copy your library to a drive",
          message: "Save the archive on your computer. Extract it into an empty folder on your drive, then open START_HERE.html.",
          links: [["Back to library", () => { releaseArchive(); render(exportFrom); }]]});
        break;
    }
    if (["ready", "behind", "paused"].includes(mode) && !available()) {
      item.action = null;
      item.message = plan.over ? bytes(plan.over) + " over. Make it fit in Manage before syncing." :
        plan.errors.length ? "Review the selection in Manage before syncing." : "Choose at least one available collection in Manage.";
    }
    if (["ready", "behind", "current", "paused"].includes(mode)) {
      if (plan?.budget < plan?.capacity) {
        item.message = (measured === undefined ? "Estimated space for OWL is " : "") +
          bytes(plan.capacity) + (measured === undefined ? ", limited to " : " free, limited to ") + bytes(plan.budget) + ". " + item.message;
      } else if (reported) {
        item.message = "This plan uses the free space you entered. " + item.message;
      } else if (measured === undefined) {
        item.message = "This plan uses an estimate of " + bytes(plan.capacity) + " for the drive. " + item.message;
      }
    }
    if (measured === undefined && ["ready", "behind", "current", "paused", "too-small"].includes(mode)) {
      item.links.push(["Update free space", enterFreeSpace]);
    }
    if (["ready", "behind", "paused"].includes(mode)) {
      const relay = relayLimitMessage(comparison?.adds || [], catalog.routes, catalog.published);
      item.extra = [essentialRouteMessage(plan.excluded), relay].filter(Boolean).join(" ");
    }
    if (!local && canTryLibrary(mode) && !tryLink.hasAttribute("href")) item.action = ["Try it", showOpenInstructions];
    if (canTryLibrary(mode) || mode === "failed") {
      const repaired = result.repairedPages.map(({path, copy, retired}) =>
        (retired ? "Replaced " + path + " in the new library. " : "Rebuilt and checked " + path + ". ") +
        "The changed copy is at " + copy + ".");
      item.extra = [item.extra, ...repaired].filter(Boolean).join(" ");
    }
    if (local) {
      item.links = item.links.filter(([, action]) => action !== changeDrive);
      if (mode === "ready" && available()) item.message = "Sync will save about " + bytes(plan.used) + " in this browser. " +
        "Allow the same space again for the download. You can change the size in Manage.";
      if (mode === "problem") item.links.push(cli);
      if (mode === "too-small") Object.assign(item, {action: ["Check available space", changeDrive],
        message: "OWL needs at least " + bytes(minimum) + " of browser storage. Free space on your computer and try again."});
      if (mode === "measuring") item.message = "Checking local storage…";
      const canExport = (canTryLibrary(mode) && !result.state.pending) || mode === "current";
      if (canExport) {
        item.action = ["Prepare download", prepareArchive];
        if (mode === "done") item.message = "Your library is ready to download and extract onto your drive.";
      } else if (mode === "behind" && inspection?.state?.syncedAt && !inspection.state.pending) {
        item.links.push(["Download last build", prepareArchive]);
      }
      if (drive && ["ready", "behind", "paused", "current", "done", "done-gaps", "download", "failed", "problem", "too-small"].includes(mode)) {
        item.links.push(["Clear local copy", clearLocal]);
      }
    }
    stage.dataset.state = mode;
    stage.style.setProperty("--p", String(item.fraction));
    if (headline.textContent !== item.title) {
      headline.textContent = item.title;
      headline.title = item.title;
    }
    const route = typeof item.route === "boolean" ? item.route : undefined;
    const messageKey = item.message + "\n" + (item.extra || "") + "\n" + route;
    if (status.dataset.message !== messageKey) {
      status.dataset.message = messageKey;
      const extra = item.extra ? element("span", "now", item.extra) : null;
      if (extra && mode === "syncing") extra.title = nowTitle;
      if (extra && route !== undefined) {
        extra.append(" ", element("span", route ? "route fast" : "route slow", route ? "Fast route" : "Slow route"));
      }
      status.replaceChildren(item.message, ...(extra ? [extra] : []));
    }
    if (previousMode !== mode) announcement.textContent = [item.title, item.message, item.extra].filter(Boolean).join(" ");
    ring.setAttribute("aria-valuetext", item.title);
    ring.setAttribute("aria-valuenow", String(Math.floor(item.fraction * 100)));
    const chart = byId("sync-meter");
    chart.hidden = !item.chart;
    if (item.chart && mode === "measuring") {
      byId("sync-track").replaceChildren();
      byId("sync-legend").replaceChildren();
    } else if (item.chart && (plan || snapshot)) {
      const solid = ["syncing", "waiting", "waiting-relay", "finishing"].includes(mode) ? active : mode === "ready" ? new Map() : savedAmounts();
      const amounts = mode === "remembered" ? snapshot.amounts : manage.amounts(plan, solid);
      meter(byId("sync-track"), byId("sync-legend"), manage?.groups || snapshot.groups, amounts,
        mode === "remembered" ? snapshot.capacity : plan.capacity, mode === "behind" ? plan.over : 0);
    }
    byId("drive-sizes").hidden = mode !== "needs-size";
    freeForm.hidden = mode !== "needs-free-space";
    formatQuestion.hidden = !["needs-free-space", "needs-size"].includes(mode) || Boolean(detectedFormat);
    if ((local ? mode === "download" : canTryLibrary(mode)) && tryLink.hasAttribute("href")) primary.replaceWith(tryLink);
    else tryLink.replaceWith(primary);
    primary.hidden = !item.action;
    primary.classList.toggle("quiet", Boolean(item.action?.[2]));
    primary.classList.toggle("pausing", item.fill !== undefined);
    if (item.fill !== undefined) primary.style.setProperty("--done", item.fill.toFixed(4));
    else primary.style.removeProperty("--done");
    primary.disabled = picker;
    if (item.action) {
      if (primary.textContent !== item.action[0]) primary.textContent = item.action[0];
      primary.onclick = item.action[1];
    }
    secondary.hidden = !item.links.length;
    if (previousMode !== mode || secondary.dataset.links !== item.links.map(row => row[0]).join("|")) {
      secondary.dataset.links = item.links.map(row => row[0]).join("|");
      secondary.replaceChildren(...item.links.map(([label, action, href]) => {
        if (action) return link(label, action);
        const node = element("a", "", label);
        node.href = href;
        return node;
      }));
    }
    // A phone does nothing when the drive is plugged in, so a finished drive says where to tap.
    const finished = ["done", "done-gaps", "current"].includes(mode);
    byId("sync-cards").hidden = mode !== "syncing" && !finished;
    byId("keep-card").hidden = mode !== "syncing";
    const routeCard = byId("route-card");
    routeCard.hidden = mode !== "syncing" || route !== false;
    if (!routeCard.hidden) byId("route-detail").textContent = slowRouteMessage();
    byId("phone-card").hidden = mode !== "syncing" || performance.now() - opened < 20_000;
    byId("open-card").hidden = local || !finished;
    [...byId("sync-rail").children].forEach((node, index) => {
      node.classList.toggle("past", index + 1 < item.step);
      if (index + 1 === item.step) node.setAttribute("aria-current", "step"); else node.removeAttribute("aria-current");
    });
    previousMode = mode;
  }

  function savedAmounts() {
    if (["done", "done-gaps", "failed"].includes(mode)) return new Map(result.completed.map(asset => [asset.id, asset.size_bytes]));
    return new Map([...(comparison?.present || []).map(row => [row.asset.id, row.asset.size_bytes]),
      ...(comparison?.adds || []).map(row => [row.asset.id, row.savedBytes])]);
  }

  function storeSnapshot() {
    if (local || !plan) return;
    snapshot = {name: name(), capacity: plan.capacity, syncedAt: inspection.state?.syncedAt,
      groups: manage.groups, amounts: manage.amounts(plan, savedAmounts())};
    try { localStorage.setItem(rememberedKey(), JSON.stringify(snapshot)); } catch {}
  }

  function showProblem(error) {
    const detail = error.name + ": " + error.message;
    const disconnected = /NotFoundError|disconnected|InvalidStateError/i.test(detail);
    const access = /NotAllowedError|SecurityError|NoModificationAllowedError|read.only/i.test(detail);
    const full = /QuotaExceededError|ENOSPC|no space|disk full/i.test(detail);
    if (local) {
      problem = {title: "Could not open the local library", message: "Allow site storage in a regular browser window and try again.",
        action: ["Reopen local builder", changeDrive]};
      if (error instanceof DriveBusy) Object.assign(problem, {title: "Local library in use",
        message: "Another tab is using this local library. Try again when it finishes."});
      else if (full) Object.assign(problem, {title: "Browser storage is full",
        message: "Free space on your computer, then reopen the local builder and choose a smaller library in Manage."});
      else if (!access && !disconnected) Object.assign(problem, {title: "Could not finish this step", message: error.message});
    } else problem = error instanceof DriveBusy ? {title: "This drive is syncing in another window",
      message: "Switch to that window to follow it, or choose a different drive or folder here.",
      action: ["Choose another drive", changeDrive]} :
      error instanceof DrivePathConflict ? {title: "There’s already " + error.entry + " on this drive",
      message: "Choose another drive or folder for your library.", action: ["Choose another drive", changeDrive]} :
      disconnected ? {title: "The drive was disconnected",
      message: remembered ? "Plug it back in and choose Reconnect. Nothing is lost." : "Plug it back in, then choose its folder again.",
      action: remembered ? ["Reconnect " + name(), reconnect] : ["Choose another drive", changeDrive]} :
      access ? {title: "OWL could not write to the drive", message: "Allow access to this drive or choose a drive you can write to.",
        action: remembered ? ["Reconnect " + name(), reconnect] : ["Choose another drive", changeDrive]} :
      full ? {title: "The drive ran out of space", message: "Free some space on the drive, then choose Sync.",
        action: ["Sync", sync], full: true} :
      {title: "OWL could not finish this step", message: "Check the connection and try again, or choose another drive.",
        action: drive && plan ? ["Sync", sync] : ["Choose another drive", changeDrive]};
    problem.detail = detail;
    diag("problem", {detail});
    render("problem");
  }

  function showMissing() {
    textList(byId("missing-list"), [...result.missing.map(item => item.title + " — " + item.reason), ...result.searchWarnings,
      ...result.keptInParts.map(item => item.title + " — Kept in " + item.parts + " parts.")]);
    byId("missing-items").showModal();
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(location.href);
      status.textContent = "Link copied.";
    } catch { status.textContent = "Copy the address from the browser’s address bar."; }
  }

  function configure(isPreview = false) {
    const saved = isPreview ? undefined : inspection?.state;
    const installed = saved?.syncedAt ? {
      budget: Math.min(saved.choice?.limitBytes || Infinity, saved.capacityBytes || capacity, catalog.planner.capacity_policy.limit),
      files: Object.keys(saved.installed).sort()
    } : undefined;
    const forceSplit = !isPreview && driveFormat !== "large";
    const savedChoice = saved?.choice && driveFormat === "large" && saved.driveFormat && saved.driveFormat !== "large" ?
      {...saved.choice, split: false} : saved?.choice;
    const choice = savedChoice || (local && !isPreview ? {kind: "recommended", split: true, limitBytes: GB} : undefined);
    const current = manage.configure({capacityBytes: Math.max(1, capacity), size, savedChoice: choice,
      split: local || forceSplit, forceSplit, connected: !isPreview, installed});
    managePlan = current;
    if (!isPreview) {
      plan = current;
      driveChoice = JSON.stringify(plan.choice);
    }
  }

  async function updateComparison() {
    const token = ++operation;
    let painted = 0;
    const value = await compareLibrary(drive, {...comparisonOptions(), inspection, onCheck: progress => {
      if (token !== operation) return;
      if (!checkProgress) checkStarted = {at: performance.now(), checked: progress.checked};
      checkProgress = progress;
      const now = performance.now();
      if (mode === "measuring" && now - painted > 500) { painted = now; render(); }
    }});
    if (token === operation) { comparison = value; checkProgress = checkStarted = undefined; }
  }

  function stageForDrive() {
    if (plan.over) return "behind";
    if (comparison.current && !dirty) return "current";
    if (inspection.state?.pending && !dirty) return "paused";
    if (inspection.state || comparison.adoption || dirty) return "behind";
    return "ready";
  }

  async function planDrive(value) {
    const handle = drive;
    capacity = value;
    configure();
    if (value < catalog.planner.capacity_policy.min && !manage.hasRecommendation && !available()) {
      minimum = manage.minimumCapacity();
      render("too-small");
      return;
    }
    await updateComparison();
    if (handle !== drive) return;
    render(stageForDrive());
    storeSnapshot();
  }

  async function identify(handle) {
    const openedDrive = ++operation;
    drive = handle;
    remembered = handle;
    inspection = comparison = plan = result = undefined;
    measured = capacity = size = undefined;
    freeField.value = "";
    freeField.setCustomValidity("");
    freeUnit.value = "GB";
    driveFormat = formatField.value = "unknown";
    detectedFormat = undefined;
    reported = false;
    active = new Map();
    transferTotal = 0;
    dirty = false;
    selectedReplacement.clear();
    render("measuring");
    const hasPermission = local || await hasDrivePermission(handle);
    if (openedDrive !== operation) return;
    if (!hasPermission) { drive = null; render("remembered"); return; }
    const inspected = await inspectDrive(handle);
    if (openedDrive !== operation) return;
    inspection = inspected;
    driveFormat = formatField.value = inspected.state?.driveFormat || "unknown";
    await init();
    if (openedDrive !== operation) return;
    if (local) {
      const {quota, usage} = await navigator.storage.estimate();
      if (!Number.isFinite(quota) || !Number.isFinite(usage)) throw Error("The browser could not estimate local storage.");
      measured = Math.max(0, Math.floor(quota - usage));
      driveFormat = "large";
      await planDrive(measured + inspection.heldBytes);
      return;
    }
    if (probesCapacity(platform, agent)) {
      const outcome = await lockDrive(handle, () => measureFreeSpace(handle, {onAttempt: value => diag("capacity", value)}));
      if (openedDrive !== operation) return;
      diag("capacity-result", outcome);
      detectedFormat = outcome.largeFiles ? "large" : outcome.splitArchives ? "fat32" : undefined;
      if (detectedFormat) driveFormat = formatField.value = detectedFormat;
      if (outcome.kind === "measured") {
        measured = outcome.bytes;
        const total = measured + inspection.heldBytes;
        await planDrive(total);
        return;
      }
    }
    sizesInto(byId("drive-sizes"), undefined, value => {
      reported = false;
      size = value;
      driveFormat = detectedFormat || formatField.value;
      render("measuring");
      void planDrive(estimateLabelCapacity(value * GB)).catch(showProblem);
    });
    if (inspection.state?.capacityBytes) {
      const saved = inspection.state;
      await planDrive(saved.capacityEstimated === undefined ? estimateLabelCapacity(saved.capacityBytes) : saved.capacityBytes);
      return;
    }
    render("needs-size");
  }

  async function openLocal() {
    render("measuring");
    try { await withLocalLibrary(async () => identify(await localLibrary())); }
    catch (error) { showProblem(error); }
  }

  async function choose(getHandle) {
    if (picker || controller) return;
    picker = true;
    render();
    try {
      const handle = await getHandle();
      picker = false;
      if (!handle) { render(); return; }
      if (await driveBusyElsewhere(handle)) { showProblem(new DriveBusy()); return; }
      if (!remembered || !await handle.isSameEntry?.(remembered)) snapshot = null;
      void rememberDrive(handle).catch(() => {});
      await identify(handle);
    } catch (error) {
      picker = false;
      if (error.name === "AbortError") render(); else showProblem(error);
    }
  }

  function showHeld() {
    manage.held((comparison?.held || []).map(row => ({
      name: title(catalog.planner, row.asset),
      replace: row.old.protected ? undefined : () => {
        if (!confirm("Replace " + title(catalog.planner, row.asset) + "? The existing copy may be unavailable until the download finishes.")) return;
        selectedReplacement.add(row.asset.id);
        void leaveManage().then(sync).catch(showProblem);
      }
    })));
  }

  function showEssentialStatus() {
    if (manageBudget !== managePlan.budget) {
      manageBudget = managePlan.budget;
      manageEssentials = new Set();
    }
    for (const id of managePlan.essentials) manageEssentials.add(id);
    const message = [removedEssentialMessage(manageEssentials, managePlan.essentials),
      essentialRouteMessage(managePlan.excluded)].filter(Boolean).join(" ");
    if (essentialStatus.textContent !== message) essentialStatus.textContent = message;
    essentialStatus.hidden = !message;
  }

  function showManage() {
    if (!preview) showHeld();
    showEssentialStatus();
    manage.show({name: preview ? undefined : name(), onBack: () => void leaveManage().catch(showProblem),
      onDone: () => void leaveManage().catch(showProblem), changes: dirty ? changeLine("Your changes") : "No changes"});
  }

  async function enterManage() {
    await init();
    preview = !drive;
    if (preview) {
      size = 64;
      capacity = size * 1e9;
      configure(true);
    }
    stage.hidden = true;
    byId("sync-rail").hidden = true;
    manageBudget = undefined;
    showManage();
  }

  async function leaveManage() {
    manage.commitLimit();
    await pendingCompare;
    manage.hide();
    stage.hidden = false;
    byId("sync-rail").hidden = false;
    render(preview ? mode : stageForDrive());
    headline.focus({preventScroll: true});
    preview = false;
  }

  // A display error must not stop a sync; the event and error go to the diagnostics.
  function onProgress(event) {
    try { showProgress(event); }
    catch (error) {
      diag("progress-display", {kind: event.kind, detail: error.name + ": " + error.message,
        at: String(error.stack || "").split("\n").slice(1, 3).map(line => line.trim()).join(" < ")});
    }
  }

  function showProgress(event) {
    if (event.kind === "plan") {
      relayTryNow = undefined;
      finishing = false;
      active = new Map(event.files.map(row => [row.id, row.done ? row.bytes : row.savedBytes || 0]));
      transferTotal = event.files.reduce((sum, row) => sum + row.bytes, 0);
      render("syncing");
      return;
    }
    if (event.kind === "waiting-network") { render("waiting"); return; }
    if (event.kind === "waiting-relay") {
      // Nothing downloads during the relay wait, so a requested pause happens now.
      if (pausing) { pauseNow(); return; }
      relayTryNow = event.tryNow;
      render("waiting-relay");
      return;
    }
    if (event.kind === "save-point") { pauseNow(); return; }
    if (event.kind === "assembling") { clearPause(); finishing = true; render("finishing"); return; }
    if (event.kind === "route") {
      const changed = routeFast.get(event.asset.id) !== event.fast;
      routeFast.set(event.asset.id, event.fast);
      if (changed && !event.fast) announcement.textContent = "Slow route. " + slowRouteMessage();
      if (mode === "syncing" && event.asset.id === currentAsset) render("syncing");
      return;
    }
    // The check of files already on the drive reports totals. A resumed
    // download also reports "checking" while it rereads its saved parts.
    if (event.kind === "checking" && event.total !== undefined) {
      currentAsset = saving = undefined;
      nowTitle = "checking files already on the drive, " + bytes(event.checked) + " of " + bytes(event.total);
      render("syncing");
      return;
    }
    if (mode === "finishing" || !event.asset) return;
    const fileTitle = title(catalog.planner, event.asset);
    const assetTitle = readerTitles.get(event.asset.id) || collectionTitles.get(event.asset.id) ||
      (fileTitle !== event.asset.id ? fileTitle : "Library file");
    if (event.kind === "checking") {
      currentAsset = event.asset.id;
      saving = undefined;
      nowTitle = "checking saved parts of " + assetTitle + (event.count ? ", " + (event.index + 1) + " of " + event.count : "");
    } else if (event.kind === "joining") {
      currentAsset = event.asset.id;
      saving = undefined;
      nowTitle = "combining " + assetTitle + (event.count ? ", " + (event.index + 1) + " of " + event.count + " parts" : "");
    } else if (event.kind === "downloading") {
      currentAsset = event.asset.id;
      saving = {lost: event.lost || 0, toSave: event.toSave || 0, seconds: event.seconds, at: performance.now()};
      active.set(event.asset.id, Math.min(event.asset.size_bytes, event.index * PART_BYTES + event.received));
      nowTitle = assetTitle;
      const now = performance.now(), done = totalDone();
      transferStarted ??= now;
      if (rateStart === undefined || done < rateBytes) { rateStart = now; rateBytes = done; }
      if (now - transferStarted >= 30_000 && now - rateStart >= 1000) {
        rate = (done - rateBytes) / ((now - rateStart) / 1000);
        if (now - rateStart > 30_000) { rateStart = now; rateBytes = done; }
      }
      if (mode === "syncing" && now - lastPaint < 150 && event.received < event.bytes) return;
      lastPaint = now;
    } else if (event.kind === "verified") {
      if (event.asset.id === currentAsset) saving = undefined;
      active.set(event.asset.id, event.asset.size_bytes);
      return;
    }
    render("syncing");
  }

  async function run(check = false) {
    if (!drive || controller || !available()) return;
    fullCheck = check || mode === "paused" && fullCheck;
    controller = new AbortController();
    const {signal} = controller;
    let failure;
    const release = keepScreenAwake();
    // Load the worker while online so opening the completed library needs only the drive.
    const previewError = error => { diag("reader-preview", {detail: error.message}); };
    const readerScope = local ? undefined : activateReaderPreview().catch(previewError);
    releaseArchive();
    opened = performance.now();
    transferStarted = rateStart = undefined;
    rate = 0;
    finishing = false;
    relayTryNow = undefined;
    nowTitle = "";
    routeFast = new Map();
    currentAsset = saving = undefined;
    drainController = new AbortController();
    discarded = 0;
    active = savedAmounts();
    transferTotal = plan.used;
    render("syncing");
    const phoneTimer = setTimeout(() => { if (mode === "syncing") render(); }, 20_000);
    const unbindWarning = warnBeforeLeaving();
    try {
      if (!local && await requestDrivePermission(drive) !== "granted") throw new DOMException("Permission was refused", "NotAllowedError");
      const network = createNetwork({signal, probeURL: "./.nojekyll", onWaiting: () => onProgress({kind: "waiting-network"}),
        onRestored: () => render(relayTryNow ? "waiting-relay" : finishing ? "finishing" : "syncing")});
      const prepareSources = assets => prepareDownloadSources(assets, {
        routes: catalog.routes, published: catalog.published, network, signal
      });
      let publishedFiles;
      const lock = local ? withLocalLibrary : operation => lockDrive(drive, operation);
      result = await lock(() => reconcile(drive, {...comparisonOptions(), excluded: plan.excluded,
        routes: catalog.routes, published: catalog.published, navigation: catalog.navigation,
        catalogAssets: catalog.planner.assets,
        searchBudget: plan.searchBudget, capacityBytes: capacity, capacityEstimated: measured === undefined, driveFormat,
        replaceInPlace: [...selectedReplacement], fullVerify: fullCheck, prepareSources, signal, network, onProgress,
        drain: drainController.signal,
        onPublished: files => { publishedFiles = files; }}).catch(async error => {
        if (signal.aborted) throw error;
        // Stop downloads still running and, unless the drive failed, record a
        // clean stop so the next Sync starts without rereading files.
        failure = error;
        controller.abort();
        const detail = error.name + ": " + error.message;
        if (!DRIVE_FAULT.test(detail)) {
          await recordPause(drive, detail).catch(pauseError => diag("record-pause", {detail: pauseError.message}));
        }
        throw error;
      }));
      inspection = await inspectDrive(drive);
      dirty = false;
      driveChoice = JSON.stringify(plan.choice);
      selectedReplacement.clear();
      await updateComparison();
      const outcome = completionState(result).mode;
      if (!local && canTryLibrary(outcome) && publishedFiles) {
        const scope = await readerScope;
        const url = scope && await publishReaderLink(scope, drive, publishedFiles).catch(previewError);
        if (url) tryLink.href = url;
      }
      render(outcome);
      storeSnapshot();
    } catch (error) {
      if (failure || !signal.aborted) { showProblem(failure || error); return; }
      try {
        await recordPause(drive).catch(pauseError => diag("record-pause", {detail: pauseError.message}));
        inspection = await inspectDrive(drive);
        await updateComparison();
        render("paused");
      } catch (readError) { showProblem(readError); }
    } finally {
      clearPause();
      saving = undefined;
      unbindWarning();
      clearTimeout(phoneTimer);
      release();
      controller = null;
      if (manageAfterPause) {
        manageAfterPause = false;
        openManage();
      }
    }
  }

  render(direct || local ? "empty" : "unsupported");
  if (direct) void getRememberedDrive().then(async handle => {
    if (!handle || picker || drive || mode !== "empty") return;
    // Another window is syncing the drive chosen last; this window starts fresh.
    if (await driveBusyElsewhere(handle)) return;
    remembered = handle;
    if (await hasDrivePermission(handle)) await identify(handle);
    else render("remembered");
  }).catch(error => { if (drive) showProblem(error); });
}
