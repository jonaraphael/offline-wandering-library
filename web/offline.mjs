import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {isNoSpace, writeFile} from "./drive.mjs";
import {assembleSearch, canonical, locator, shareSearchSupport, transfer} from "./search-build.mjs";

const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const order = (a, b) => compare(a.title.toLowerCase(), b.title.toLowerCase()) || compare(a.id, b.id);
const encoder = new TextEncoder();
const render = (template, values) => template.replace(/\{\{([a-z_]+)\}\}/g, (_, slot) => values[slot] ?? "");
const data = (id, value) => "globalThis.OWLReaderData(" + canonical(id) + "," + canonical(value) + ");\n";
const hash = value => bytesToHex(sha256(encoder.encode(value)));
const firstResponse = new Set(["cert", "medical_bec"]);
const searchScripts = ["manifest.js", "rank.js", "shards.js", "rerank.js"];
const FORMATS = {pdf: "PDF", html: "Web page", htm: "Web page", epub: "EPUB book",
  zim: "Encyclopedia, opens in Kiwix", txt: "Text", zip: "ZIP"};

function emergencyRoutes(tasks, documents) {
  const rows = new Map(documents.map(row => [row.id, row]));
  return tasks.map(([task, keywords, candidates]) => {
    const match = candidates.find(([id]) => rows.has(id));
    if (!match) return {task, keywords};
    const [id, fragment = "", hint = "", entries = []] = match;
    const row = rows.get(id);
    return {...row, task, keywords, href: row.href + fragment, hint, articles: entries.map(([name]) => name),
      articlePaths: entries.map(([, path]) => path)};
  });
}

function grouped(rows, metadata, category) {
  const books = new Map(), output = [];
  for (const row of rows) {
    const entry = metadata[row.id];
    const book = entry?.book;
    const item = {...row, topics: entry?.topics || []};
    if (book && row.format !== "zim") {
      const folder = row.path.slice(0, row.path.lastIndexOf("/") + 1);
      const key = folder + "\n" + book.title;
      if (!books.has(key)) books.set(key, {folder, title: book.title, members: []});
      books.get(key).members.push(item);
    } else output.push(item);
  }
  for (const {folder, title, members} of books.values()) {
    if (members.length < 3) {
      output.push(...members);
      continue;
    }
    members.sort((a, b) => metadata[a.id].book.order - metadata[b.id].book.order);
    const chapters = members.map(row => ({...row, title: metadata[row.id].book.chapter, source: title}));
    const topics = [...new Map(members.flatMap(row => row.topics)).entries()].sort(([a], [b]) => compare(a, b));
    output.push({id: "book-" + members[0].id, title, path: folder, kind: "Book, " + members.length + " chapters",
      bytes: members.reduce((sum, row) => sum + row.bytes, 0), publisher: metadata[members[0].id].publisher || "",
      chapters, topics});
  }
  const importance = row => Math.min(...(row.chapters || [row]).map(member => metadata[member.id]?.importance ?? 3));
  const first = row => category !== "health" ? 2
    : firstResponse.has(row.id) ? 0 : row.chapters && row.title === "Where There Is No Doctor" ? 1 : 2;
  return output.sort((a, b) => first(a) - first(b) || importance(a) - importance(b) || order(a, b));
}

export function startPage(assets = [], missing = []) {
  const links = assets.map(asset => {
    const path = asset.parts[0].path;
    return '<li><a href="' + locator(path) + '">' + escape(asset.title) + "</a> · " + escape(path) +
      (asset.parts.length > 1 ? " · Keep all parts together and open the first in Kiwix." : "") + "</li>";
  });
  return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    "<title>Library · Offline Wandering Library</title><h1>Library</h1>" +
    '<p>Files on this drive are in the <a href="LIBRARY/">LIBRARY folder</a>, grouped by subject.</p>' +
    (links.length ? "<ul>" + links.join("") + "</ul>" : "") +
    (missing.length ? '<p>This library is incomplete. See the <a href="LIBRARY/BUILD_REPORT.html">build report</a>.</p>' : "");
}

export function assemblyReserve({assets, excluded, navigation, search, searchBudget, partCount}) {
  const {reader, verify} = navigation;
  const size = value => encoder.encode(value || "").length;
  // Include the root page, both documents with embedded CSS, reader scripts,
  // inventory, checksums and the browser record's swap file.
  const fixed = reader ? 3 * size(reader.css) + size(reader.reader) + 2 * size(reader.document) +
    2 * size(reader.bootstrap) + size(reader.runtime) + size(reader.readme) + size(reader.redirect) : 0;
  const metadata = assets.reduce((sum, asset) => sum + 1400 + 4 * size(JSON.stringify([
    asset.id, asset.title, asset.destination, asset.license, asset.attribution, asset.source_url, asset.version,
    reader?.assets?.[asset.id]?.topics
  ])) + 600 * partCount(asset), 0);
  // The planner already accounts for the optional search payload. Limit
  // the on-drive placeholder so probing an estimated drive costs a small write.
  const searchReserve = search ? Math.min(searchBudget, 16 * 2 ** 20) : 0;
  return fixed + metadata + size(verify) + 4096 + excluded.length * 512 + searchReserve;
}

function reportBody(missing, keptInParts) {
  const omissions = missing.length ? "<h2>Missing files</h2><ul>" + missing.map(row =>
    "<li>" + escape(row.title) + " · " + escape(row.reason) + "</li>").join("") + "</ul>"
    : "<p>Every requested file available to this build is listed in the inventory.</p>";
  return omissions + (keptInParts.length ? "<h2>Kept in parts</h2><ul>" + keptInParts.map(row =>
    "<li>" + escape(row.title) + " · " + row.parts + " parts</li>").join("") + "</ul>" : "");
}

function readerFiles(config, inventory, phone, missing, keptInParts, indexed, shared, syncedAt) {
  const {layout, css, assets: metadata, categories} = config;
  const files = inventory.map(asset => {
    const path = asset.parts[0].path;
    return {id: asset.id, title: asset.title, path, href: locator(path), kind: metadata[asset.id]?.kind ||
      FORMATS[asset.format] || asset.format.toUpperCase(), format: asset.format, bytes: asset.bytes,
      ...(asset.parts.length > 1 ? {parts: asset.parts.length} : {})};
  });
  const documents = files.filter(row => metadata[row.id]?.document !== false && !row.path.startsWith("LIBRARY/SOFTWARE/"));
  const readers = layout.readers.flatMap(([folder, label]) => [...files].sort(order)
    .filter(row => row.path.startsWith("LIBRARY/" + folder)).map(({path, href}) => ({label, path, href})));
  const tasks = emergencyRoutes(layout.tasks, documents);
  const home = {version: 1, tasks, readers, devices: layout.devices, phone, stats: {count: files.length,
    bytes: files.reduce((sum, row) => sum + row.bytes, 0), missing: missing.length},
    search: indexed.pages.has("LIBRARY/SEARCH/manifest.js"), searchCount: documents.length, categories: [],
    searchPriority: Object.fromEntries(documents.flatMap(({id}) => {
      const row = metadata[id];
      return row?.first_aid || row?.importance === 0 ? [[id, row.first_aid ? 2 : 1]] : [];
    })), ...(syncedAt ? {syncedAt} : {})};
  const pages = new Map([["LIBRARY/INDEX/reader.js", config.runtime], ["LIBRARY/README.txt", config.readme]]);
  const section = (title, items) => render(layout.static_section, {title: escape(title), body: "<ul>" + items.join("") + "</ul>"});
  const staticRow = (title, path, detail) => render(layout.static_row,
    {title: escape(title), path: escape(path), detail: detail ? " · " + escape(detail) : ""});
  const staticSections = [section("Urgent", tasks.map(row => row.path
    ? staticRow(row.task, row.path, [row.hint, row.articles.length ? "Look up " + row.articles.join(" / ") + " in Kiwix" : ""]
      .filter(Boolean).join(" · "))
    : "<li><b>" + escape(row.task) + "</b> · No guide on this drive.</li>"))];
  for (const category of categories) {
    const {id, name} = category;
    const members = documents.filter(row => (metadata[row.id]?.category || "other") === id);
    if (id === "health") members.push(...phone);
    const rows = grouped(members, metadata, id);
    home.categories.push({...category, count: rows.length});
    pages.set("LIBRARY/INDEX/c-" + id + ".js", data(id, rows));
    if (rows.length) staticSections.push(section(name, rows.map(row =>
      staticRow(row.title, row.path, row.format === "zim" ? "opens in the Kiwix app" : row.kind))));
  }
  const devices = ["iphone", "android", "windows", "mac", "linux"].map(device => {
    const instructions = layout.devices[device];
    const folder = device === "mac" ? "MACOS" : device.toUpperCase();
    const install = device === "iphone" || readers.some(row => row.path.startsWith("LIBRARY/SOFTWARE/" + folder + "/"))
      ? instructions.install : "Install Kiwix while you have internet.";
    return render(layout.static_device, {name: escape(instructions.label), install: escape(install),
      open: escape(instructions.open), pick: escape(instructions.pick)});
  });
  const software = readers.length ? "<ul>" + readers.map(row => staticRow(row.label, row.path, "")).join("") + "</ul>" : "";
  staticSections.push(render(layout.static_section, {title: "Opening files",
    body: "<p>Open books and guides in your device’s file viewer. If a link does not open, " +
      "close this preview and follow its location in your file manager. Encyclopedias need " +
      "the free Kiwix app. Keep split files together and open the first part.</p>" + devices.join("") + software}));
  if (missing.length) {
    staticSections.push('<p>This library is incomplete. See the <a href="LIBRARY/BUILD_REPORT.html">build report</a>.</p>');
  }
  pages.set("LIBRARY/INDEX/home.js", data("home", home));

  const document = (title, body) => render(config.document, {title: escape(title), body, css, home: "../START_HERE.html"});
  const inventoryRows = [...inventory].sort(order).map(row => {
    const path = row.parts[0].path;
    const link = render(layout.location_link, {href: escape(locator(path.slice("LIBRARY/".length))), text: escape(row.title)});
    const detail = [row.license, row.attribution, row.parts.length > 1
      ? row.parts.length + " parts. Keep them together and open the first." : ""].filter(Boolean).map(escape).join(" · ");
    return render(layout.inventory_row, {link, path: escape(path), detail: detail ? "<small>" + detail + "</small>" : ""});
  });
  pages.set("LIBRARY/INVENTORY.html", document("Every file, with its location",
    '<p>See <a href="INVENTORY.json">file details, sources and checksums</a>.</p><ul>' + inventoryRows.join("") + "</ul>"));
  pages.set("LIBRARY/BUILD_REPORT.html", document("Build report",
    reportBody(missing, keptInParts) + '<p><a href="INVENTORY.html">Every file, with its location</a></p>'));
  const colors = ":root{" + categories.filter(({id}) => !["trades", "school"].includes(id))
    .map(({id, light}) => "--c-" + id + ":" + light + ";").join("") + "}\n" +
    "@media(prefers-color-scheme:dark){:root{" + categories.map(({id, dark}) => "--c-" + id + ":" + dark + ";").join("") + "}}";
  const scripts = new Map();
  for (const [path, text] of pages) {
    if (!path.startsWith("LIBRARY/INDEX/")) continue;
    scripts.set(path.slice("LIBRARY/INDEX/".length), text);
    pages.delete(path);
  }
  for (const name of searchScripts) {
    const contents = indexed.pages.get("LIBRARY/SEARCH/" + name);
    if (contents) scripts.set(name, contents);
  }
  scripts.set("search.js", config.bootstrap);
  scripts.set("search-paths.js", "globalThis.OWLSearchPaths(" + canonical(shared) + ");\n");
  const hashes = [...scripts].sort(([a], [b]) => compare(a, b)).map(([path, text]) => [path, hash(text)]);
  const generation = "INDEX/" + hash(canonical(hashes)).slice(0, 12);
  for (const [name, text] of scripts) pages.set("LIBRARY/" + generation + "/" + name, text);
  pages.set("START_HERE.html", render(config.reader,
    {css, colors, static: staticSections.join("\n"), policy: escape(config.csp), generation}));
  return pages;
}

export async function assembleLibrary(drive, {completed, missing, keptInParts = [], selectedCount = completed.length + missing.length,
    navigation, layouts, parts, signal, search, searchBudget, fetchFile, network, syncedAt, compact = false,
    unavailableSupport = [], searchMissing = false, onPublished}) {
  const {verify} = navigation;
  const {reader, phone} = compact ? {} : navigation;
  const phoneVolumes = [], phoneChecksums = [], supportMissing = [...unavailableSupport];
  let phoneBytes = 0;
  const phoneConfig = navigation.phone;
  if (phoneConfig && completed.some(asset => asset.id === phoneConfig.source_id && asset.sha256 === phoneConfig.source_sha256)) {
    for (const volume of phoneConfig.volumes) {
      const id = "wikimed-phone-" + volume.file;
      const title = "WikiMed phone volume " + volume.title;
      if (!phone) {
        supportMissing.push({kind: "phone", id, title, reason: "The drive ran out of space."});
        continue;
      }
      try {
        const path = "LIBRARY/" + phone.destination + volume.file;
        phoneBytes += volume.bytes;
        phoneChecksums.push(await transfer(drive, phone.base, volume.file, volume, fetchFile, signal, network, path, 8_000_000));
        phoneVolumes.push({path, id, title: "WikiMed: " + volume.title,
          href: locator(path), kind: "PDF", format: "pdf", bytes: volume.bytes});
      } catch (error) {
        signal?.throwIfAborted();
        if (isNoSpace(error)) throw error;
        supportMissing.push({kind: "phone", id, title, reason: error.message});
      }
    }
  }
  const assets = completed.map(asset => {
    const meta = navigation.reader?.assets?.[asset.id];
    return {id: asset.id, title: asset.title, destination: layouts.get(asset.id)[0].path.slice("LIBRARY/".length),
      format: asset.format, license: asset.license, attribution: meta?.attribution ?? asset.attribution,
      publisher: meta?.publisher ?? asset.publisher, bytes: asset.size_bytes, sha256: asset.sha256,
      source_url: asset.source_url ?? null, version: asset.version ?? null, redistributable: asset.redistributable ?? null,
      parts: layouts.get(asset.id).map((part, index) => ({...part, sha256: parts[asset.id][index].sha256}))};
  });
  let indexed = {pages: new Map(), checksums: [], missing: []};
  let shared = {}, sharedChecksums = [];
  if (search) {
    try {
      const result = await assembleSearch(drive, {completed, layouts, config: search, fetchFile, signal, network,
        budget: searchBudget - phoneBytes, versioned: Boolean(reader)});
      if (reader && result.pages.has("LIBRARY/SEARCH/rank.js")) {
        ({paths: shared, checksums: sharedChecksums} = await shareSearchSupport(drive, result.checksums, signal));
      }
      indexed = result;
    } catch (error) {
      signal?.throwIfAborted();
      if (isNoSpace(error) || error instanceof DOMException) throw error;
      supportMissing.push({kind: "search", title: "Search index", reason: error.message});
    }
  }
  supportMissing.push(...indexed.missing);
  if (compact && navigation.reader) {
    supportMissing.push({kind: "reader", title: "Full reader", reason: "The drive ran out of space."});
  }
  if (searchMissing) supportMissing.push({kind: "search", title: "Search index", reason: "The drive ran out of space."});
  const omissions = missing.map(row => ({id: row.id || "", title: row.title || row.id || "",
    utility_tier: row.utility_tier ?? null, reason: row.reason || row.unresolved_reason || ""})).sort(order);
  let pages;
  if (reader) {
    try { pages = readerFiles(reader, assets, phoneVolumes, omissions, keptInParts, indexed, shared, syncedAt); }
    catch (error) {
      supportMissing.push({kind: "reader", title: "Full reader", reason: error.message});
    }
  }
  pages ||= new Map([
    ["START_HERE.html", startPage(assets, omissions)],
    ["LIBRARY/BUILD_REPORT.html", '<!doctype html><meta charset="utf-8"><title>Build report</title><h1>Build report</h1>' +
      reportBody(omissions, keptInParts) + '<p><a href="INVENTORY.json">Every file, with its location</a></p>']
  ]);
  const start = pages.get("START_HERE.html");
  pages.delete("START_HERE.html");
  for (const [path, contents] of indexed.pages) pages.set(path, contents);
  if (reader && !supportMissing.some(row => row.kind === "reader")) {
    pages.set("LIBRARY/SEARCH.html", reader.redirect);
    if (!search) pages.set("LIBRARY/SEARCH/search.js", reader.bootstrap);
  }
  if (reader && navigation.atlas) {
    const included_topic_ids = [...new Set(assets.flatMap(row => reader.assets?.[row.id]?.topics?.map(([id]) => id) || []))].sort();
    pages.set("LIBRARY/INDEX/navigation-report.json", JSON.stringify({schema_version: 1, included_topic_ids,
      input_hashes: navigation.input_hashes}, null, 2) + "\n");
  }
  if (verify) pages.set("LIBRARY/VERIFY.py", verify);
  pages.set("LIBRARY/INVENTORY.json", JSON.stringify({schema_version: 1, assets, unresolved: missing,
    content_complete: !missing.length}, null, 2) + "\n");
  pages.set("LIBRARY/SOURCE_NOTES.txt", assets.map(file => [file.title, file.license, file.attribution,
    ...file.parts.map(part => part.path)].filter(Boolean).join("\n")).join("\n\n") + "\n");
  pages.set("LIBRARY/BUILD_INFO.json", JSON.stringify({schema_version: 1, asset_count: assets.length,
    selected_count: selectedCount, missing: omissions, kept_in_parts: keptInParts,
    content_complete: !missing.length && assets.length > 0,
    support_complete: supportMissing.length === 0, support_missing: supportMissing,
    layout: {entry_page: "START_HERE.html", content_directory: "LIBRARY"}}, null, 2) + "\n");

  const checksums = [...assets.flatMap(file => file.parts.map(part => part.sha256 + "  " + part.path)),
    ...indexed.checksums, ...sharedChecksums, ...phoneChecksums];
  for (const [path, contents] of pages) {
    signal?.throwIfAborted();
    await writeFile(drive, path, contents);
    checksums.push(hash(contents) + "  " + path);
  }
  checksums.push(hash(start) + "  START_HERE.html");
  // Keep the previous reader openable until its complete replacement exists.
  // Reconcile journals both versions of the affected files before each write
  // so that a pending Sync can rebuild the list and start page together.
  signal?.throwIfAborted();
  await writeFile(drive, "LIBRARY/SHA256SUMS.txt", checksums.sort().join("\n") + "\n");
  signal?.throwIfAborted();
  await writeFile(drive, "START_HERE.html", start);
  // SHA256SUMS lines contain a 64-character digest, two spaces and the full path.
  onPublished?.(new Map(checksums.map(line => [line.slice(66), line.slice(0, 64)])));
  return {supportMissing, warnings: supportMissing.map(({title, reason}) => title + " — " + reason)};
}
