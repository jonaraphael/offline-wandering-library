import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {join} from "node:path";
import {test} from "node:test";
import {browserSelection} from "../web/builder.mjs";
import {recommendBrowser} from "../web/builder-ui.mjs";
import "../src/owl/templates/selector.js";

const site = process.argv[2];
test("the published browser recommendation fills at least 90% at every integer GB", {skip: !site}, () => {
  const {planner, routes} = JSON.parse(readFileSync(join(site, "catalog.json")));
  const lock = JSON.parse(readFileSync(new URL("../web/pages-mirrors.json", import.meta.url)));
  const published = {files: Object.fromEntries(Object.keys(lock).map(id => [id, [{}]]))};
  const assets = new Map(planner.assets.map(asset => [asset.id, asset]));
  for (let gb = 16; gb <= 1000; gb++) {
    const capacity = gb * 1e9;
    const profile = OWLPlanner.profileFor(planner, "flash-16gb", capacity);
    const state = recommendBrowser(planner, OWLPlanner.preset(planner, profile.id, capacity), routes, published);
    const result = OWLPlanner.resolve(planner, state, {ignoreNativeCapacity: true});
    assert.deepEqual(result.errors, [], gb + " GB");
    const chosen = result.selectedAssetIds.map(id => assets.get(id));
    const selection = browserSelection(chosen, routes, published);
    assert.deepEqual(selection.excluded, [], gb + " GB");
    const used = selection.assets.reduce((total, asset) => total + asset.size_bytes, 0);
    const reserve = Math.max(16 * 2 ** 20, profile.reserve_bytes) + profile.discovery_budget_bytes;
    assert.ok(used >= capacity * 0.90, gb + " GB must select at least 90% of the label");
    assert.ok(used + reserve <= profile.capacity_bytes, gb + " GB must fit the budget");
  }
});
