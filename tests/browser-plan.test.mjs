import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {join} from "node:path";
import {test} from "node:test";
import {browserSelection, buildOrder, isKnowledgeFile, PART_BYTES} from "../web/builder.mjs";
import {completionState, essentialRouteMessage, recommendBrowser, removedEssentialMessage, selectBrowser,
  storageStops} from "../web/builder-ui.mjs";
import {assemblyReserve} from "../web/offline.mjs";
import "../src/owl/templates/selector.js";

const site = process.argv[2];
const priorities = [
  ["health", "water-sanitation", "food-preservation", "agriculture", "shelter"],
  ["hand-tools", "repair"], ["navigation"], ["general-reference"], ["school-math", "school-science"],
  ["languages"], ["culture", "advanced-study", "computing"]
];
const priority = new Map(priorities.flatMap((fields, rank) => fields.map(field => [field, rank])));

function publishedCatalog() {
  const {planner, routes, navigation} = JSON.parse(readFileSync(join(site, "catalog.json")));
  const lock = JSON.parse(readFileSync(new URL("../web/pages-mirrors.json", import.meta.url)));
  const published = {files: Object.fromEntries(Object.keys(lock).map(id => [id, [{}]]))};
  const files = new Map(planner.assets.map(asset => [asset.id, asset]));
  return {planner, routes, navigation, phone: navigation.phone, published, files};
}

test("storage limit stops end at the available space and omit unusable stops", () => {
  const inGB = (capacity, eligible) => storageStops(capacity * 1e9, eligible).map(stop => stop / 1e9);
  const oneTB = [1, 8, 16, 32, ...Array.from({length: 30}, (_, i) => 64 + 32 * i), 1000];
  assert.deepEqual(inGB(59.6), [1, 8, 16, 32, 59.6]);
  assert.deepEqual(inGB(959), [...oneTB.filter(stop => stop < 959), 959]);
  assert.deepEqual(inGB(1000), oneTB);
  assert.deepEqual(inGB(1500), oneTB);
  assert.deepEqual(inGB(32, stop => stop >= 8e9), [8, 16, 32]);
  assert.deepEqual(inGB(0.6), [0.6]);
});

test("the browser plan fits every storage stop, including reduced recommendations", {skip: !site}, t => {
  const {planner, routes, phone, published, files} = publishedCatalog();
  const options = retainedFiles => ({retainedFiles, phone});
  function plan(capacity, retainedFiles) {
    const profileId = planner.profiles[0].id;
    const state = recommendBrowser(planner, OWLPlanner.preset(planner, profileId, capacity, {browser: true}),
      routes, published, undefined, options(retainedFiles));
    const resolved = OWLPlanner.resolve(planner, state, {ignoreNativeCapacity: true});
    const profile = OWLPlanner.profileFor(planner, profileId, capacity, state);
    const result = selectBrowser(profile, resolved, {files, routes, published, phone, kept: () => false,
      minimum: planner.capacity_policy.min});
    assert.deepEqual(result.errors, [], capacity + " B");
    assert.ok(result.excluded.every(row => row.utility_tier === "CRITICAL" &&
      !routes[row.id]?.length && !published.files[row.id]?.length), capacity + " B only lacks essential routes");
    assert.ok(result.assets.some(isKnowledgeFile), capacity + " B has a useful library");
    assert.ok(result.used + result.reserve <= profile.capacity_bytes, capacity + " B includes search and reserve");
    assert.equal(result.over, 0);
    assert.equal(result.assets.some(asset => asset.destination.startsWith("SOFTWARE/")),
      result.assets.some(asset => asset.format === "zim"), capacity + " B bundles apps for encyclopedia files");
    return result.assets;
  }
  const standard = plan(16e9);
  const standardIds = new Set(standard.map(asset => asset.id));
  for (const stop of new Set([...storageStops(1e12), 59.6e9, 959e9])) {
    const assets = plan(stop);
    if (stop < 16e9) {
      assert.ok(assets.every(asset => standardIds.has(asset.id)), stop + " B is a subset of 16 GB");
      assert.ok(standard.filter(asset => asset.critical && asset.size_bytes < 10e6)
        .every(asset => assets.includes(asset)), stop + " B retains the small essentials");
      t.diagnostic(stop / 1e9 + " GB: " + assets.filter(isKnowledgeFile).length + " knowledge files, " +
        assets.reduce((sum, asset) => sum + asset.size_bytes, 0) + " content bytes");
    }
  }
  const installed = plan(128e9).map(asset => asset.id).sort();
  for (const stop of [1, 8, 16, 32, 64, 96]) {
    const retained = plan(stop * 1e9, installed);
    assert.ok(retained.length < installed.length && retained.every(asset => installed.includes(asset.id)),
      stop + " GB is removals only from 128 GB");
  }
});

function attribution(assets) {
  const fields = new Map();
  for (const {size_bytes: size, selection} of assets.filter(isKnowledgeFile)) {
    const weights = selection.domain_weights || {[selection.domain]: 100};
    const total = Object.values(weights).reduce((sum, weight) => sum + weight, 0);
    const shares = Object.keys(weights).sort().map(field => [field, Math.floor(size * weights[field] / total)]);
    let remainder = size - shares.reduce((sum, [, bytes]) => sum + bytes, 0);
    for (const [field, bytes] of shares) fields.set(field, (fields.get(field) || 0) + bytes + Number(remainder-- > 0));
  }
  return fields;
}

test("published browser defaults retain every field across the half-GB sweep", {skip: !site}, t => {
  const {planner, routes, published, files: catalog, navigation} = publishedCatalog();
  const pins = JSON.parse(readFileSync(new URL("../web/kiwix-pieces.json", import.meta.url)));
  const partCount = asset => asset.format === "zim" ? Math.ceil(asset.size_bytes / PART_BYTES) : 1;
  const {field_core: core, protected_fields: protectedFields} = planner.capacity_policy;
  const coreFiles = browserSelection([...new Set(Object.values(core).flat())].map(id => catalog.get(id)), routes, published).assets;
  const peaks = new Map();
  let prior = new Map(), previousIds = new Set(), above90 = 0, minimum = 1, minimumAt;
  for (let gb = 16; gb <= 1000; gb += 0.5) {
    const capacity = gb * 1e9;
    const profile = OWLPlanner.profileFor(planner, "flash-16gb", capacity);
    const state = recommendBrowser(planner, OWLPlanner.preset(planner, profile.id, capacity, {browser: true}), routes, published);
    const result = OWLPlanner.resolve(planner, state, {ignoreNativeCapacity: true});
    assert.deepEqual(result.errors, [], gb + " GB");
    const chosen = result.selectedAssetIds.map(id => catalog.get(id));
    const selection = browserSelection(chosen, routes, published);
    assert.ok(selection.excluded.every(row => row.utility_tier === "CRITICAL" &&
      !routes[row.id]?.length && !published.files[row.id]?.length), gb + " GB only lacks essential routes");
    const used = selection.assets.reduce((total, asset) => total + asset.size_bytes, 0);
    const reserve = Math.max(16 * 2 ** 20, profile.reserve_bytes) + profile.discovery_budget_bytes;
    assert.ok(used + reserve <= profile.capacity_bytes, gb + " GB must fit the budget");
    const workspace = assemblyReserve({assets: selection.assets, excluded: [], navigation, search: true,
      searchBudget: profile.discovery_budget_bytes, partCount});
    let written = 0;
    for (const asset of buildOrder(selection.assets)) {
      if (pins.archives[asset.id] && asset.size_bytes > pins.piece_bytes) {
        for (let offset = 0; offset < asset.size_bytes; offset += PART_BYTES) {
          const bytes = Math.min(PART_BYTES, asset.size_bytes - offset);
          assert.ok(written + offset + 2 * bytes + workspace <= capacity, gb + " GB fits transfer of " + asset.id);
        }
      }
      written += asset.size_bytes;
    }
    if (used / capacity >= 0.90) above90++;
    if (used / capacity < minimum) { minimum = used / capacity; minimumAt = gb; }
    const fields = attribution(selection.assets);
    const ids = new Set(result.selectedAssetIds);
    assert.equal(fields.size, priority.size, gb + " GB has all fields");
    assert.ok(coreFiles.every(asset => ids.has(asset.id)), gb + " GB has every reachable core file");
    for (const field of protectedFields) {
      assert.ok(fields.get(field) >= (prior.get(field) || 0), gb + " GB reduced protected " + field);
    }
    const losses = [];
    for (const [field, bytes] of fields) {
      assert.ok(bytes * 2 >= (peaks.get(field) || 0), gb + " GB lost over half of " + field);
      peaks.set(field, Math.max(peaks.get(field) || 0, bytes));
      if (bytes < (prior.get(field) || 0)) losses.push(field);
    }
    if (losses.length) {
      assert.ok(selection.assets.some(asset => !previousIds.has(asset.id) && asset.size_bytes * 10 >= capacity &&
        losses.every(field => priority.get(asset.selection.domain) < priority.get(field))), gb + " GB displaced " + losses);
    }
    prior = fields;
    previousIds = ids;
  }
  t.diagnostic(above90 + " of 1969 plans reached 90% fill. Minimum " +
    (100 * minimum).toFixed(2) + "% at " + minimumAt + " GB.");
});

test("only selected essentials without routes count as missing", {skip: !site}, t => {
  const {planner, routes, files, phone} = publishedCatalog();
  const published = {files: {}};
  const direct = Object.fromEntries(Object.entries(routes).map(([id, urls]) => [id,
    urls.filter(url => !new URL(url).host.includes(".workers.dev"))]));
  const base = OWLPlanner.preset(planner, planner.profiles[0].id, 16e9, {browser: true});
  const required = OWLPlanner.resolve(planner, base, {ignoreNativeCapacity: true}).selectedAssetIds
    .filter(id => files.get(id).utility_tier === "CRITICAL");
  const state = recommendBrowser(planner, base, direct, published, undefined, {phone});
  const select = state => selectBrowser(OWLPlanner.profileFor(planner, state.profile, state.capacityBytes, state),
    OWLPlanner.resolve(planner, state, {ignoreNativeCapacity: true}),
    {files, routes: direct, published, phone, kept: () => false, minimum: planner.capacity_policy.min});
  const plan = select(state);
  const reachable = plan.assets.filter(asset => asset.utility_tier === "CRITICAL");
  assert.ok(reachable.length > 0 && reachable.length < required.length);
  assert.equal(plan.excluded.filter(row => row.utility_tier === "CRITICAL").length, required.length - reachable.length);
  const message = essentialRouteMessage(plan.excluded);
  assert.match(message, /This browser can’t download [\d,]+ essential files\. Use the Python builder to get them\./);
  t.diagnostic(message);
  const result = completionState({state: {finished: false, excluded: plan.excluded}, completed: plan.assets,
    missing: plan.excluded, searchWarnings: []});
  assert.ok(result.message.includes(message));

  const unavailable = plan.excluded.find(row => row.utility_tier === "CRITICAL");
  const resource = planner.resources.find(row => {
    const item = state.items[row.id];
    return item.included && (item.assetIds || (row.editions?.[item.edition] || row).asset_ids).includes(unavailable.id);
  });
  const file = reachable.find(asset => asset.format === "pdf");
  const single = planner.resources.find(row => {
    const item = state.items[row.id];
    return item.included && (item.assetIds || (row.editions?.[item.edition] || row).asset_ids).includes(file.id);
  });
  const item = state.items[resource.id];
  const members = item.assetIds || (resource.editions?.[item.edition] || resource).asset_ids;
  const modified = structuredClone(state);
  modified.items[resource.id].assetIds = members.filter(id => id !== unavailable.id);
  const oneRemoved = select(modified);
  assert.ok(!oneRemoved.excluded.some(row => row.id === unavailable.id));
  assert.equal(removedEssentialMessage(plan.essentials, oneRemoved.essentials), "You removed 1 essential file.");

  for (const item of Object.values(modified.items)) item.included = false;
  Object.assign(modified.items[single.id], {included: true, assetIds: [file.id]});
  const edited = select(modified);
  assert.deepEqual(edited.errors, []);
  assert.deepEqual(edited.assets.map(asset => asset.id), [file.id]);
  assert.deepEqual(edited.excluded, []);
  assert.equal(essentialRouteMessage(edited.excluded), "");
  t.diagnostic(removedEssentialMessage(plan.essentials, edited.essentials));
  const outcome = completionState({state: {finished: true, excluded: edited.excluded}, completed: edited.assets,
    missing: edited.excluded, searchWarnings: []});
  assert.equal(outcome.mode, "done");
  t.diagnostic("Ready with 0 items missing");
});
