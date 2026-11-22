import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {join} from "node:path";
import {test} from "node:test";
import {browserSelection, isKnowledgeFile} from "../web/builder.mjs";
import {recommendBrowser} from "../web/builder-ui.mjs";
import "../src/owl/templates/selector.js";

const site = process.argv[2];
const priorities = [
  ["health", "water-sanitation", "food-preservation", "agriculture", "shelter"],
  ["hand-tools", "repair"], ["navigation"], ["general-reference"], ["school-math", "school-science"],
  ["languages"], ["culture", "advanced-study", "computing"]
];
const priority = new Map(priorities.flatMap((fields, rank) => fields.map(field => [field, rank])));

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
  const {planner, routes} = JSON.parse(readFileSync(join(site, "catalog.json")));
  const lock = JSON.parse(readFileSync(new URL("../web/pages-mirrors.json", import.meta.url)));
  const published = {files: Object.fromEntries(Object.keys(lock).map(id => [id, [{}]]))};
  const catalog = new Map(planner.assets.map(asset => [asset.id, asset]));
  const {field_core: core, protected_fields: protectedFields} = planner.capacity_policy;
  const coreFiles = browserSelection([...new Set(Object.values(core).flat())].map(id => catalog.get(id)), routes, published).assets;
  const peaks = new Map();
  let prior = new Map(), previousIds = new Set(), above90 = 0, minimum = 1, minimumAt;
  for (let gb = 16; gb <= 1000; gb += 0.5) {
    const capacity = gb * 1e9;
    const profile = OWLPlanner.profileFor(planner, "flash-16gb", capacity);
    const state = recommendBrowser(planner, OWLPlanner.preset(planner, profile.id, capacity), routes, published);
    const result = OWLPlanner.resolve(planner, state, {ignoreNativeCapacity: true});
    assert.deepEqual(result.errors, [], gb + " GB");
    const chosen = result.selectedAssetIds.map(id => catalog.get(id));
    const selection = browserSelection(chosen, routes, published);
    assert.deepEqual(selection.excluded, [], gb + " GB");
    const used = selection.assets.reduce((total, asset) => total + asset.size_bytes, 0);
    const reserve = Math.max(16 * 2 ** 20, profile.reserve_bytes) + profile.discovery_budget_bytes;
    assert.ok(used + reserve <= profile.capacity_bytes, gb + " GB must fit the budget");
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
