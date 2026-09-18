/* Offline selection arithmetic. Python/Node parity tests bind this to the CLI. */
(function (root) {
  "use strict";
  const READERS = "archive-readers", OVERHEAD = 16 * 1024 * 1024;
  const DIRECT = new Set(["html", "htm", "pdf", "txt", "md", "png", "jpg", "jpeg"]);
  const isSoftware = asset => asset.destination.split("/")[0] === "SOFTWARE";
  const isDirect = asset => DIRECT.has(asset.format.toLowerCase()) && !asset.reader_required &&
    !["SOFTWARE", "ZIM"].includes(asset.destination.split("/")[0]) && !isSoftware(asset);
  const mapById = rows => Object.fromEntries(rows.map(row => [row.id, row]));
  const sum = values => values.reduce((total, value) => total + value, 0);
  function profileFor(model, id) {
    const profile = model.profiles.find(row => row.id === id);
    if (!profile) throw Error("Unknown profile: " + id);
    return profile;
  }
  function preset(model, id) {
    const profile = profileFor(model, id), defaults = new Set(profile.preset_resource_ids);
    return {profile: id, allowIncomplete: false, atlas: model.atlas_available !== false, items: Object.fromEntries(model.resources.map(row =>
      [row.id, {included: defaults.has(row.id), edition: !profile.default_resources && defaults.has(row.id) ? "preset" :
        (profile.default_editions?.[row.id] || "published")}]))};
  }
  function selectionArgs(model, state) {
    const profile = profileFor(model, state.profile), defaults = new Set(profile.preset_resource_ids);
    const include = [], exclude = [], editions = {};
    for (const row of model.resources) {
      const item = state.items[row.id];
      if (!item) throw Error("Missing resource selection: " + row.id);
      if (!item.included && defaults.has(row.id)) exclude.push(row.id);
      if (item.included) {
        if (!defaults.has(row.id) || (!profile.default_resources && item.edition !== "preset")) include.push(row.id);
        const defaultEdition = profile.default_editions?.[row.id] || "published";
        if (item.edition !== "preset" && item.edition !== defaultEdition) editions[row.id] = item.edition;
      }
    }
    return {include, exclude, editions};
  }
  function resolve(model, state) {
    const profile = profileFor(model, state.profile), resources = mapById(model.resources), assets = mapById(model.assets);
    const args = selectionArgs(model, state), selected = new Set(profile.default_resources || []);
    const errors = [], warnings = [], overrides = profile.resource_overrides || {};
    args.include.forEach(id => selected.add(id)); args.exclude.forEach(id => selected.delete(id));
    const variants = {}, members = {}, credits = {}, replaced = new Set();
    for (const id of selected) {
      const resource = resources[id], mode = args.editions[id] || profile.default_editions?.[id] || "published";
      if (!resource) throw Error("Unknown resource: " + id);
      if (mode !== "published" && !resource.editions?.[mode]) {
        errors.push(resource.title + ": no verified " + mode + " edition is available.");
      }
      variants[id] = mode === "published" ? resource : {...resource, ...(resource.editions?.[mode] || {})};
      const removed = new Set(overrides[id]?.exclude_asset_ids || []);
      members[id] = variants[id].asset_ids.filter(asset => !removed.has(asset));
      credits[id] = 0;
    }
    const rawMembers = new Set(Object.values(members).flat());
    for (const id of model.resources.map(row => row.id).filter(id => selected.has(id))) {
      const row = resources[id], removed = (row.replaces_asset_ids || []).filter(asset => rawMembers.has(asset));
      for (const asset of removed) {
        if (replaced.has(asset)) errors.push("Several collections replace " + asset);
        replaced.add(asset);
      }
      const credit = row.replacement_credit;
      if (credit && selected.has(credit.resource_id) && removed.some(asset => members[credit.resource_id].includes(asset)))
        credits[credit.resource_id] += credit.target_bytes;
    }
    for (const id of selected) members[id] = members[id].filter(asset => !replaced.has(asset));
    let candidateIds = new Set(Object.values(members).flat());
    const needsReaders = [...candidateIds].some(id => assets[id].status === "resolved" && assets[id].format.toLowerCase() === "zim");
    const autoIncluded = new Set();
    if (needsReaders && !selected.has(READERS)) {
      if (args.exclude.includes(READERS)) errors.push("Selected ZIM archives require bundled readers.");
      if (!resources[READERS]) errors.push("The catalog has no bundled reader resource.");
      else {
        selected.add(READERS); autoIncluded.add(READERS); variants[READERS] = resources[READERS]; credits[READERS] = 0;
        members[READERS] = resources[READERS].asset_ids.filter(id => !(overrides[READERS]?.exclude_asset_ids || []).includes(id));
        members[READERS].forEach(id => candidateIds.add(id));
      }
    }
    if (needsReaders && !(members[READERS] || []).some(id => assets[id].status === "resolved" && assets[id].destination.startsWith("SOFTWARE/")))
      errors.push("Selected ZIM archives require a verified bundled reader.");
    const rowsById = {}, incomplete = [];
    for (const id of selected) {
      const resource = variants[id], group = members[id], pinned = group.filter(id => assets[id].status === "resolved");
      const known = sum(pinned.map(id => assets[id].size_bytes));
      const edition = args.editions[id] || profile.default_editions?.[id] || "published";
      const target = edition === "published" ? (overrides[id]?.target_bytes ?? resource.target_bytes) : resource.target_bytes;
      const adjusted = target - credits[id];
      if (adjusted < 0) errors.push(resource.title + ": replacement credit exceeds target.");
      let status = resource.status, reason = resource.reason || "";
      if (!group.length) {status = "unresolved"; reason += "; No selected source files remain after overrides or replacements.";}
      else if (pinned.length !== group.length && status === "ready") {status = pinned.length ? "partial" : "unresolved"; reason = "Selected source files are unresolved.";}
      const row = {status, reason, knownBytes: known, targetBytes: Math.max(adjusted, known), assetCount: pinned.length};
      rowsById[id] = row;
      if (status !== "ready") incomplete.push({id, title: resource.title, reason});
    }
    // Fixed small presets are exact source files. Expanding a row selects its
    // full intended collection explicitly; a checkbox never silently expands it.
    let baseline = [];
    if (!profile.default_resources) {
      const removed = new Set(args.exclude.flatMap(id => [resources[id].asset_ids,
        ...Object.values(resources[id].editions || {}).map(row => row.asset_ids)].flat()));
      for (const id of selected) {
        (resources[id].replaces_asset_ids || []).forEach(asset => removed.add(asset));
        if (args.editions[id]) [resources[id].asset_ids, ...Object.values(resources[id].editions || {}).map(edition => edition.asset_ids)]
          .flat().forEach(asset => removed.add(asset));
      }
      baseline = profile.baseline_asset_ids.filter(id => !removed.has(id) && !candidateIds.has(id));
      baseline.forEach(id => candidateIds.add(id));
    }
    const pinnedIds = [...candidateIds].filter(id => assets[id].status === "resolved");
    if (pinnedIds.some(id => assets[id].format.toLowerCase() === "zim") &&
        !pinnedIds.some(id => assets[id].destination.startsWith("SOFTWARE/")))
      errors.push("The selected files contain ZIM archives without a verified bundled reader.");
    const missingRequired = [...candidateIds].filter(id => assets[id].status !== "resolved" && assets[id].required);
    if (missingRequired.length) errors.push("Required source files are unresolved: " + missingRequired.join(", "));
    const knownBytes = sum(pinnedIds.map(id => assets[id].size_bytes));
    const baselineBytes = sum(baseline.filter(id => assets[id].status === "resolved").map(id => assets[id].size_bytes));
    const contentTargetBytes = sum(Object.entries(rowsById).filter(([id]) => id !== READERS).map(([, row]) => row.targetBytes)) + baselineBytes;
    const readerBytes = rowsById[READERS] ? Math.max(profile.readers_budget_bytes || 0, rowsById[READERS].targetBytes) : 0;
    const intendedBytes = Math.max(knownBytes, contentTargetBytes + readerBytes);
    const finalBytes = intendedBytes + profile.search_budget_bytes + OVERHEAD;
    const actualFinalBytes = knownBytes + profile.search_budget_bytes + OVERHEAD;
    const scratchBytes = profile.index_scratch_budget_bytes ?? 2 * profile.search_budget_bytes;
    const peakBytes = finalBytes + scratchBytes + profile.reserve_bytes;
    const actualPeakBytes = actualFinalBytes + scratchBytes + profile.reserve_bytes;
    if (finalBytes + profile.reserve_bytes > profile.capacity_bytes) errors.push("Selected content plus search and reserve exceeds this drive size.");
    if (!pinnedIds.length) errors.push("No verified downloadable files are selected.");
    if (actualPeakBytes > profile.capacity_bytes) errors.push("Even the verified files exceed the conservative in-place build budget. Select less content or a larger drive.");
    if (peakBytes > profile.capacity_bytes) warnings.push("The complete intended collection exceeds the in-place build budget, including temporary search files. It does not fit as a complete in-place build at these allowances.");
    if (incomplete.length) warnings.push(incomplete.length + " selected collections need source selection, permissions, or verified files. A partial build contains only currently pinned files.");
    // Count actual cataloged files exactly once, independently of collection planning budgets.
    const pinnedAssets = pinnedIds.map(id => assets[id]);
    const knowledge = pinnedAssets.filter(asset => !isSoftware(asset));
    const directAssets = knowledge.filter(isDirect);
    const knowledgeBytes = sum(knowledge.map(asset => asset.size_bytes));
    const softwareBytes = knownBytes - knowledgeBytes;
    const baselineSoftwareBytes = sum(baseline.map(id => assets[id]).filter(asset => asset.status === "resolved" && isSoftware(asset)).map(asset => asset.size_bytes));
    const knowledgeTargetBytes = Math.max(knowledgeBytes, contentTargetBytes - baselineSoftwareBytes);
    const unmetContentBytes = Math.max(0, knowledgeTargetBytes - knowledgeBytes);
    const unchangedPreset = !args.include.length && !args.exclude.length && !Object.keys(args.editions).length;
    const presetBelowTarget = unchangedPreset && knowledgeBytes < (profile.content_target_min_bytes || 0);
    if (presetBelowTarget && !state.allowIncomplete)
      errors.push("This preset is below its pinned knowledge minimum. Resolve source gaps, customize the selection, or explicitly accept a partial library.");
    const underfilled = presetBelowTarget || (unmetContentBytes >= 250 * 10**6 && knowledgeBytes < knowledgeTargetBytes * .8);
    const categories = new Map();
    for (const asset of knowledge) {
      const id = asset.category || "uncategorized";
      if (!categories.has(id)) categories.set(id, {id, assetCount:0, directCount:0, bytes:0});
      const row = categories.get(id);
      row.assetCount++; row.bytes += asset.size_bytes;
      if (isDirect(asset)) row.directCount++;
    }
    const coverage = {knowledgeBytes, softwareBytes, knowledgeTargetBytes, unmetContentBytes,
      assetCount:pinnedAssets.length, knowledgeCount:knowledge.length, softwareCount:pinnedAssets.length - knowledge.length,
      directBytes:sum(directAssets.map(asset => asset.size_bytes)), directCount:directAssets.length,
      archiveBytes:sum(knowledge.filter(asset => asset.format.toLowerCase() === "zim").map(asset => asset.size_bytes)),
      archiveCount:knowledge.filter(asset => asset.format.toLowerCase() === "zim").length,
      textbookCount:directAssets.filter(asset => asset.resource_type === "textbook").length,
      illustratedCount:directAssets.filter(asset => asset.illustrated && ["textbook", "guide"].includes(asset.resource_type)).length,
      categories:[...categories.values()].sort((a,b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
      capacityFraction:profile.capacity_bytes ? knownBytes / profile.capacity_bytes : 0,
      targetFraction:knowledgeTargetBytes ? knowledgeBytes / knowledgeTargetBytes : 0,
      presetTargetMinBytes:profile.content_target_min_bytes || 0, presetTargetMaxBytes:profile.content_target_max_bytes || 0,
      presetBelowTarget, underfilled};
    const criticalCount = pinnedIds.filter(id => assets[id].critical).length;
    if (!criticalCount) warnings.push("No directly readable critical core is selected.");
    if (unchangedPreset) {
      const eligible = pinnedIds.map(id => assets[id]).filter(asset => asset.required && asset.critical &&
        isDirect(asset));
      const counts = {textbooks:eligible.filter(asset => asset.resource_type === "textbook").length,
        "illustrated-guides":eligible.filter(asset => asset.illustrated && ["textbook", "guide"].includes(asset.resource_type)).length};
      for (const [shelf, floor] of Object.entries(profile.minimum_coverage || {}))
        if (counts[shelf] < floor) errors.push("This preset requires at least " + floor + " critical " + shelf + "; found " + counts[shelf] + ".");
    }
    const rows = model.resources.map(resource => {
      const allMembers = new Set([...resource.asset_ids, ...Object.values(resource.editions || {}).flatMap(edition => edition.asset_ids)]);
      const item = state.items[resource.id], subset = baseline.filter(id => allMembers.has(id) && assets[id].status === "resolved");
      const hasPreset = !profile.default_resources && profile.preset_resource_ids.includes(resource.id);
      const options = [];
      if (hasPreset) options.push({value:"preset", label:"Preset files only", available:true, reason:"Only verified source files in this preset; formats are listed below."});
      options.push({value:"published", label:"Published collection", available:true, reason:"Uses the catalog's published formats and collection scope."});
      for (const mode of ["direct", "compact"]) options.push({value:mode, label:mode === "direct" ? "Alternate direct-readable edition" : "Alternate compact archive edition",
        available:Boolean(resource.editions?.[mode]), reason:resource.editions?.[mode] ? "Verified catalog edition; original critical files are retained." : "No verified alternate edition and size are cataloged. No conversion or compression ratio is assumed."});
      const chosen = selected.has(resource.id), subsetOnly = !chosen && item.included && item.edition === "preset";
      const row = rowsById[resource.id] || (subsetOnly ? {knownBytes:sum(subset.map(id=>assets[id].size_bytes)), targetBytes:sum(subset.map(id=>assets[id].size_bytes)),
        assetCount:subset.length, status:"ready", reason:"Verified preset files only; the broader collection is not included."} :
        {knownBytes:sum(resource.asset_ids.filter(id=>assets[id].status === "resolved").map(id=>assets[id].size_bytes)),
         targetBytes:overrides[resource.id]?.target_bytes ?? resource.target_bytes, assetCount:resource.asset_ids.filter(id=>assets[id].status === "resolved").length,
         status:resource.status, reason:resource.reason || ""});
      return {id:resource.id, number:resource.number, title:resource.title, included:item.included || autoIncluded.has(resource.id),
        autoIncluded:autoIncluded.has(resource.id), edition:item.edition, options, ...row,
        scope:subsetOnly ? "Preset subset" : "Full intended collection", include:resource.include || [], preferredFormats:resource.preferred_formats || []};
    });
    const canBuild = errors.length === 0 && (!incomplete.length || state.allowIncomplete);
    return {rows, estimates:{contentTargetBytes, knownBytes, readerBytes, searchBytes:profile.search_budget_bytes, scratchBytes,
      metadataBytes:OVERHEAD, reserveBytes:profile.reserve_bytes, finalBytes, peakBytes, actualPeakBytes, capacityBytes:profile.capacity_bytes},
      coverage, errors, warnings, incomplete, canBuild, selectedAssetIds:pinnedIds.sort(), selectionArgs:args};
  }
  function quote(value, shell) {
    if (typeof value !== "string" || /[\x00-\x1f\x7f]/.test(value)) throw Error("Paths and arguments must be single-line text without control characters.");
    if (/^[a-zA-Z0-9_./:=,-]+$/.test(value) && value.length && !value.startsWith("-")) return value;
    return shell === "powershell" ? "'" + value.replace(/'/g, "''") + "'" : "'" + value.replace(/'/g, "'\"'\"'") + "'";
  }
  function command(model, state, options) {
    const report = resolve(model, state);
    if (!options.plan && !report.canBuild) return "";
    const target = options.target || "";
    if (!target.trim() || target.startsWith("-") || /[\x00-\x1f\x7f]/.test(target)) return "";
    if (!["posix", "powershell"].includes(options.shell)) throw Error("Choose POSIX or PowerShell");
    const args = ["python", "scripts/build_drive.py", target, "--profile", state.profile];
    for (const [flag, value] of Object.entries(model.cli || {})) {
      args.push(flag); if (value !== null) args.push(value);
    }
    const chosen = report.selectionArgs;
    if (chosen.include.length) args.push("--include", chosen.include.join(","));
    if (chosen.exclude.length) args.push("--exclude", chosen.exclude.join(","));
    for (const [id, edition] of Object.entries(chosen.editions)) args.push("--edition", id + "=" + edition);
    if (state.atlas) args.push("--navigation-dir", "catalog/navigation");
    if (state.allowIncomplete) args.push("--allow-incomplete");
    if (options.plan) args.push("--plan");
    return args.map(arg => arg.startsWith("--") && /^[a-z-]+$/.test(arg.slice(2)) ? arg : quote(arg, options.shell)).join(" ");
  }
  root.OWLPlanner = {preset, resolve, command, selectionArgs};
})(globalThis);
