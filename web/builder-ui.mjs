import {createNetwork, SourceError} from "./network.mjs";
import {diag} from "./diagnostics.mjs";
import {browserSelection, compareLibrary, inspectDrive, isKnowledgeFile, PART_BYTES, reconcile} from "./builder.mjs";
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

export function recommendBrowser(planner, state, routes, published, kept = () => false) {
  for (const resource of planner.resources) {
    const item = state.items[resource.id];
    if (!item.included) continue;
    const members = (resource.editions?.[item.edition] || resource).asset_ids;
    const reachable = members.filter(id => hasRoute(id, routes, published) || kept(id));
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


const WELCOME = "Any USB drive or SD card with 16 GB to 1 TB free. Files already on it stay.";
const rememberedKey = () => "owl-last-sync:" + location.pathname.replace(/index\.html$/, "");
const driveName = handle => handle?.name || "Your drive";
const dateOf = value => value ? new Date(value).toLocaleDateString("en-GB", {day: "numeric", month: "long", year: "numeric"}) : "";
const countOf = (count, noun) => count.toLocaleString() + " " + noun + (count === 1 ? "" : "s");
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
  const platform = navigator.userAgentData?.platform || navigator.platform || "";
  const agent = navigator.userAgent || "";
  const supported = typeof globalThis.showDirectoryPicker === "function" &&
    !/android|iphone|ipad|ipod|mobile|firefox|fxios/i.test(agent) &&
    !(navigator.maxTouchPoints > 1 && /^mac/i.test(platform));
  let catalog, manage, catalogRequest, drive, remembered, snapshot, inspection, comparison, plan, pendingCompare;
  const collectionTitles = new Map();
  let measured, minimum, capacity, forceSplit = false, size, mode, previousMode, problem, result, controller, opened = 0;
  let operation = 0, picker = false, preview = false, fullCheck = false, selectedReplacement = new Set();
  let active = new Map(), transferTotal = 0, transferStarted, rateStart, rateBytes, rate = 0, nowTitle = "", lastPaint = 0;
  let dirty = false, finishing = false, driveChoice;
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
      const readers = planner.resources.find(row => row.id === "archive-readers")?.asset_ids || [];
      const kept = id => Boolean(inspection?.state?.installed[id] || inspection?.candidates?.has(id));
      manage = create(planner, {
        browser: true,
        download: id => hasRoute(id, routes, published) || kept(id),
        recommend: state => recommendBrowser(planner, state, routes, published, kept),
        select(profile, state, resolved) {
          const all = [...new Set([...resolved.selectedAssetIds, ...readers])].map(id => files.get(id));
          const selection = browserSelection(all, routes, published);
          // The drive may already have verified files whose routes disappeared.
          const keptIds = new Set(selection.excluded.filter(row => kept(row.id)).map(row => row.id));
          for (const asset of all) if (keptIds.has(asset.id)) selection.assets.push(asset);
          selection.excluded = selection.excluded.filter(row => !keptIds.has(row.id));
          const reserve = Math.max(INDEX_ALLOWANCE, profile.reserve_bytes) + profile.discovery_budget_bytes;
          const limit = Math.min(capacityForPlan(), profile.capacity_bytes) - reserve;
          const used = sumBytes(selection.assets);
          return {...selection, used, reserve, limit, over: Math.max(0, used - limit), errors: resolved.errors};
        },
        onChange(value) {
          if (preview) return;
          plan = value;
          dirty = JSON.stringify(value.choice) !== driveChoice;
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
            byId("manage-changes").textContent = changeLine("Your changes");
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
  const effectiveFree = () => measured ?? Math.max(0, capacityForPlan() - (inspection?.heldBytes || 0));
  const catalogVersion = () => catalog.version || [catalog.planner.catalog_sha256, catalog.planner.resources_sha256].join(":");
  const name = () => driveName(drive || remembered);
  const available = () => plan && !plan.over && !plan.errors.length && plan.assets.some(isKnowledgeFile);
  const comparisonOptions = () => ({assets: plan.assets, choice: plan.choice, catalogVersion: catalogVersion(),
    singleArchives: !plan.choice.split, freeBytes: effectiveFree()});
  const totalDone = () => [...active.values()].reduce((sum, count) => sum + count, 0);
  // A side with nothing to do is left out: "removes 3.57 GB", not "adds 0 B, removes 3.57 GB".
  const changeLine = prefix => {
    const adds = comparison?.addBytes || 0, removes = comparison?.removeBytes || 0;
    const parts = [adds && "adds " + bytes(adds), removes && "removes " + bytes(removes)].filter(Boolean);
    return prefix + ": " + (parts.join(", ") || "nothing to add or remove") + ".";
  };
  const percent = value => Math.floor(value * 100) + "%";
  const changeDrive = () => void choose(pickDrive);
  const reconnect = () => void choose(async () => {
    if (await requestDrivePermission(remembered) !== "granted") throw new DOMException("Permission was refused", "NotAllowedError");
    return remembered;
  });
  const openManage = () => void enterManage().catch(showProblem);
  const verify = () => void run(true);
  const sync = () => void run();
  const pause = () => controller?.abort();
  const manageLink = ["Manage what goes on it", openManage];
  const checkLink = ["Check every file", verify];
  const seeLink = ["See what goes on a drive", openManage];
  const cli = ["Build with the command line", null, byId("how").querySelector("a").href];

  function debug() {
    byId("technical-detail").textContent = problem?.detail || "";
    diag("view-diagnostics", {drive: drive?.name, state: mode});
    byId("technical").showModal();
  }

  function render(next = mode) {
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
        Object.assign(item, {title: "Plug in a drive", chart: false, action: ["Choose drive", changeDrive], links: [seeLink],
          message: WELCOME + (picker ? " In the window that opens, click the drive’s name, then Open." : "")});
        break;
      case "remembered":
        Object.assign(item, {message: lastDate ? "Last synced " + lastDate + "." : "Reconnect to see what is on this drive.",
          chart: Boolean(snapshot?.amounts), action: reconnectButton, links: [["Use a different drive", changeDrive]]});
        break;
      case "measuring":
        Object.assign(item, {message: "Measuring free space…", links: [different]});
        break;
      case "needs-size":
        Object.assign(item, {message: "How much space does this drive have? Use the number printed on it.", chart: false, links: [different]});
        break;
      case "ready":
        Object.assign(item, {step: 2, action: syncButton, links: [manageLink],
          message: (measured !== undefined ? bytes(measured) + " free. " : "") +
            "The recommended library uses " + bytes(plan.used) + ": " +
            plan.assets.filter(isKnowledgeFile).length.toLocaleString() + " books, manuals and courses."});
        break;
      case "behind":
        Object.assign(item, {step: 2, fraction: readyFraction, action: syncButton, links: [manageLink],
          message: comparison?.adoption ? "A library is already on this drive. Sync keeps files that match." :
            comparison?.changedChoice || dirty ? changeLine("Your changes") :
            comparison?.state?.syncedAt ? (comparison.workCount ?
              changeLine(countOf(comparison.workCount, "update")) : "Sync refreshes the start page.") +
              (lastDate ? " Last synced " + lastDate + "." : "") :
            "Unfinished: " + bytes(comparison?.addBytes || 0) + " to go."});
        break;
      case "current":
        Object.assign(item, {step: 3, fraction: 1, title: "Up to date", links: [manageLink, checkLink],
          message: (lastDate ? "Synced " + lastDate + ". " : "") + countOf(plan.assets.length, "item") + ", " + bytes(plan.used) + "."});
        break;
      case "syncing":
        Object.assign(item, {step: 2, fraction: syncFraction, title: percent(syncFraction), action: ["Pause", pause, true],
          message: bytes(totalDone()) + " of " + bytes(transferTotal || plan.used) +
            (rate && transferTotal > totalDone() ? " · " + duration((transferTotal - totalDone()) / rate) + " left" : ""),
          extra: nowTitle && "Now: " + nowTitle});
        break;
      case "waiting":
        Object.assign(item, {step: 2, fraction: syncFraction, title: percent(syncFraction), action: ["Pause", pause, true],
          message: "Waiting for the internet. Sync continues by itself."});
        break;
      case "finishing":
        Object.assign(item, {step: 2, fraction: 1, title: "Finishing", message: "Building the search index and the start page."});
        break;
      case "paused":
        Object.assign(item, {step: 2, fraction: readyFraction, title: "Paused at " + percent(readyFraction), action: syncButton,
          message: "Nothing is lost. Sync continues where it stopped.", links: [manageLink]});
        break;
      case "done": {
        const eject = /^mac/i.test(platform) ? "In Finder, click ⏏ beside " + name() + "." :
          /^win/i.test(platform) ? "Click Safely Remove Hardware in the taskbar, then " + name() + "." : "Eject it in your file manager.";
        Object.assign(item, {step: 3, fraction: 1, title: "Ready", action: ["Sync another drive", changeDrive, true],
          message: "Eject " + name() + ", then unplug it. " + eject, extra: "Open START_HERE on any computer or phone.", links: [checkLink]});
        break;
      }
      case "done-gaps": {
        const missing = result.missing.length + result.searchWarnings.length + Number(!result.missing.length && !result.searchWarnings.length);
        Object.assign(item, {step: 3, fraction: 1, title: "Ready, with " + countOf(missing, "item") + " missing",
          message: "The library works. " + countOf(missing, "item") + " could not be downloaded.",
          action: ["Try those again", sync], links: [["Show the " + countOf(missing, "item"), showMissing], ["Sync another drive", changeDrive]]});
        break;
      }
      case "problem":
        Object.assign(item, {step: 2, fraction: syncFraction, title: problem.title, message: problem.message,
          chart: Boolean(plan), action: problem.action, links: [["Technical details", debug]]});
        break;
      case "too-small":
        Object.assign(item, {title: "Not enough room", chart: false, action: pick,
          message: "OWL needs at least " + bytes(minimum) + " free. This drive has " + bytes(measured) + "."});
        break;
      case "unsupported":
        Object.assign(item, {chart: false, title: "Open this page in Chrome, Edge or Arc on a computer",
          message: "Those browsers can write straight to a drive. This one cannot.", action: ["Copy link", copyLink], links: [seeLink, cli]});
        break;
    }
    if (["ready", "behind", "paused"].includes(mode) && !available()) {
      item.action = null;
      item.message = plan.over ? bytes(plan.over) + " over. Make it fit in Manage before syncing." :
        plan.errors.length ? "Review the selection in Manage before syncing." : "Choose at least one available collection in Manage.";
    }
    stage.dataset.state = mode;
    stage.style.setProperty("--p", String(item.fraction));
    if (headline.textContent !== item.title) {
      headline.textContent = item.title;
      headline.title = item.title;
    }
    const messageKey = item.message + "\n" + (item.extra || "");
    if (status.dataset.message !== messageKey) {
      status.dataset.message = messageKey;
      const extra = item.extra ? element("span", "now", item.extra) : null;
      if (extra && mode === "syncing") extra.title = nowTitle;
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
      const solid = ["syncing", "waiting", "finishing"].includes(mode) ? active : mode === "ready" ? new Map() : savedAmounts();
      const amounts = mode === "remembered" ? snapshot.amounts : manage.amounts(plan, solid);
      meter(byId("sync-track"), byId("sync-legend"), manage?.groups || snapshot.groups, amounts,
        mode === "remembered" ? snapshot.capacity : plan.capacity, mode === "behind" ? plan.over : 0);
    }
    byId("drive-sizes").hidden = mode !== "needs-size";
    primary.hidden = !item.action;
    primary.classList.toggle("quiet", Boolean(item.action?.[2]));
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
    byId("sync-cards").hidden = mode !== "syncing";
    byId("phone-card").hidden = mode !== "syncing" || performance.now() - opened < 20_000;
    [...byId("sync-rail").children].forEach((node, index) => {
      node.classList.toggle("past", index + 1 < item.step);
      if (index + 1 === item.step) node.setAttribute("aria-current", "step"); else node.removeAttribute("aria-current");
    });
    previousMode = mode;
  }

  function savedAmounts() {
    if (mode === "done" || mode === "done-gaps") return new Map(result.completed.map(asset => [asset.id, asset.size_bytes]));
    return new Map([...(comparison?.present || []).map(row => [row.asset.id, row.asset.size_bytes]),
      ...(comparison?.adds || []).map(row => [row.asset.id, row.savedBytes])]);
  }

  function storeSnapshot() {
    if (!plan) return;
    snapshot = {name: name(), capacity: plan.capacity, syncedAt: inspection.state?.syncedAt,
      groups: manage.groups, amounts: manage.amounts(plan, savedAmounts())};
    try { localStorage.setItem(rememberedKey(), JSON.stringify(snapshot)); } catch {}
  }

  function showProblem(error) {
    const detail = error.name + ": " + error.message;
    const disconnected = /NotFoundError|disconnected|InvalidStateError/i.test(detail);
    const access = /NotAllowedError|SecurityError|NoModificationAllowedError|read.only/i.test(detail);
    const full = /QuotaExceededError|ENOSPC|no space|disk full/i.test(detail);
    problem = disconnected ? {title: "The drive was disconnected",
      message: remembered ? "Plug it back in and choose Reconnect. Nothing is lost." : "Plug it back in, then choose its folder again.",
      action: remembered ? ["Reconnect " + name(), reconnect] : ["Choose another drive", changeDrive]} :
      access ? {title: "OWL could not write to the drive", message: "Allow access to this drive or choose a drive you can write to.",
        action: remembered ? ["Reconnect " + name(), reconnect] : ["Choose another drive", changeDrive]} :
      full ? {title: "The drive ran out of space", message: "Free some space on the drive, then choose Sync.",
        action: ["Sync", sync]} :
      {title: "OWL could not finish this step", message: "Check the connection and try again, or choose another drive.",
        action: drive && plan ? ["Sync", sync] : ["Choose another drive", changeDrive]};
    problem.detail = detail;
    diag("problem", {detail});
    render("problem");
  }

  function showMissing() {
    textList(byId("missing-list"), [...result.missing.map(item => item.title + " — " + item.reason), ...result.searchWarnings,
      ...(!result.missing.length && !result.searchWarnings.length ? ["Some large files still need to be joined."] : [])]);
    byId("missing-items").showModal();
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(location.href);
      status.textContent = "Link copied.";
    } catch { status.textContent = "Copy the address from the browser’s address bar."; }
  }

  function configure(isPreview = false) {
    const savedChoice = isPreview ? undefined : inspection?.state?.choice;
    const current = manage.configure({capacityBytes: capacity, size, savedChoice, split: forceSplit, forceSplit});
    if (!isPreview) {
      plan = current;
      driveChoice = JSON.stringify(plan.choice);
    }
  }

  async function updateComparison() {
    const token = ++operation;
    const value = await compareLibrary(drive, {...comparisonOptions(), inspection});
    if (token === operation) comparison = value;
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
    active = new Map();
    transferTotal = 0;
    dirty = forceSplit = false;
    selectedReplacement.clear();
    render("measuring");
    await init();
    if (openedDrive !== operation) return;
    if (!await hasDrivePermission(handle)) { drive = null; render("remembered"); return; }
    inspection = await inspectDrive(handle);
    if (openedDrive !== operation) return;
    if (probesCapacity(platform)) {
      const outcome = await lockDrive(() => measureFreeSpace(handle, {onAttempt: value => diag("capacity", value)}));
      if (openedDrive !== operation) return;
      diag("capacity-result", outcome);
      forceSplit = outcome.kind === "fat32" || outcome.kind === "limited";
      if (outcome.kind === "measured") {
        measured = outcome.bytes;
        const total = measured + inspection.heldBytes;
        if (total < catalog.planner.capacity_policy.min) {
          capacity = total;
          configure();
          minimum = plan.used + plan.reserve;
          if (total < minimum) { render("too-small"); return; }
        }
        await planDrive(total);
        return;
      }
    }
    if (inspection.state?.capacityBytes) { await planDrive(inspection.state.capacityBytes); return; }
    sizesInto(byId("drive-sizes"), undefined, value => {
      size = value;
      render("measuring");
      void planDrive(value * 1e9).catch(showProblem);
    });
    render("needs-size");
  }

  async function choose(getHandle) {
    if (picker || controller) return;
    picker = true;
    render();
    try {
      const handle = await getHandle();
      picker = false;
      if (!handle) { render(); return; }
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

  function showManage() {
    if (!preview) showHeld();
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
    showManage();
  }

  async function leaveManage() {
    await pendingCompare;
    manage.hide();
    stage.hidden = false;
    byId("sync-rail").hidden = false;
    render(preview ? mode : stageForDrive());
    headline.focus({preventScroll: true});
    preview = false;
  }

  function onProgress(event) {
    if (event.kind === "plan") {
      active = new Map(event.files.map(row => [row.id, row.done ? row.bytes : row.savedBytes || 0]));
      transferTotal = event.files.reduce((sum, row) => sum + row.bytes, 0);
      render("syncing");
      return;
    }
    if (event.kind === "waiting-network") { render("waiting"); return; }
    if (event.kind === "assembling") { finishing = true; render("finishing"); return; }
    if (mode === "finishing" || !event.asset) return;
    if (event.kind === "downloading") {
      active.set(event.asset.id, Math.min(event.asset.size_bytes, event.index * PART_BYTES + event.received));
      const fileTitle = title(catalog.planner, event.asset);
      nowTitle = readerTitles.get(event.asset.id) || collectionTitles.get(event.asset.id) ||
        (fileTitle !== event.asset.id ? fileTitle : "Library file");
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
    const release = keepScreenAwake();
    opened = performance.now();
    transferStarted = rateStart = undefined;
    rate = 0;
    finishing = false;
    nowTitle = "";
    active = savedAmounts();
    transferTotal = plan.used;
    render("syncing");
    const phoneTimer = setTimeout(() => { if (mode === "syncing") render(); }, 20_000);
    try {
      if (await requestDrivePermission(drive) !== "granted") throw new DOMException("Permission was refused", "NotAllowedError");
      const network = createNetwork({signal, probeURL: "./.nojekyll", onWaiting: () => onProgress({kind: "waiting-network"}),
        onRestored: () => render(finishing ? "finishing" : "syncing")});
      const prepareSources = async () => {
        const [search, publisherPieces] = await Promise.all([
          network.retry(() => get("./search-build.json", signal)),
          network.retry(() => get("./kiwix-pieces.json", signal))
        ]);
        return {search, publisherPieces};
      };
      result = await lockDrive(() => reconcile(drive, {...comparisonOptions(), excluded: plan.excluded,
        routes: catalog.routes, published: catalog.published, navigation: catalog.navigation,
        archiveSpace: plan.limit, searchBudget: plan.profile.discovery_budget_bytes, capacityBytes: capacity,
        replaceInPlace: [...selectedReplacement], fullVerify: fullCheck, prepareSources, signal, network, onProgress}));
      inspection = await inspectDrive(drive);
      dirty = false;
      driveChoice = JSON.stringify(plan.choice);
      selectedReplacement.clear();
      await updateComparison();
      render(result.state.finished && !result.missing.length ? "done" : "done-gaps");
      storeSnapshot();
    } catch (error) {
      if (!signal.aborted) { showProblem(error); return; }
      try {
        inspection = await inspectDrive(drive);
        await updateComparison();
        render("paused");
      } catch (readError) { showProblem(readError); }
    } finally {
      clearTimeout(phoneTimer);
      release();
      controller = null;
    }
  }

  render(supported ? "empty" : "unsupported");
  if (supported) void getRememberedDrive().then(async handle => {
    if (!handle || picker || drive || mode !== "empty") return;
    remembered = handle;
    if (await hasDrivePermission(handle)) await identify(handle);
    else render("remembered");
  }).catch(error => { if (drive) showProblem(error); });
}
