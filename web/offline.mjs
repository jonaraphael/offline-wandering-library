import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {phoneCatalog, savedPhoneDrive} from "./phone-catalog.mjs";
import {fileHandle, isNoSpace, optional, writeFile} from "./drive.mjs";
import {assembleSearch, canonical, locator, shareSearchSupport, transfer} from "./search-build.mjs";

export const phoneCatalogName = "START_HERE_FOR_IPHONES.pdf";

const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const order = (a, b) => compare(a.title.toLowerCase(), b.title.toLowerCase()) || compare(a.id, b.id);
const encoder = new TextEncoder();
const render = (template, values) => template.replace(/\{\{([a-z_]+)\}\}/g, (_, slot) => values[slot] ?? "");
const data = (id, value) => "globalThis.OWLReaderData(" + canonical(id) + "," + canonical(value) + ");\n";
const hash = value => bytesToHex(sha256(typeof value === "string" ? encoder.encode(value) : value));
const firstResponse = new Set(["cert", "medical_bec"]);
const searchScripts = ["manifest.js", "rank.js", "shards.js", "rerank.js"];
const FORMATS = {pdf: "PDF", html: "Web page", htm: "Web page", epub: "EPUB book",
  zim: "Encyclopedia", txt: "Text", zip: "ZIP"};

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
    2 * size(reader.bootstrap) + size(reader.runtime) + size(reader.readme) + size(reader.redirect) +
    Object.values(reader.zim || {}).reduce((sum, script) => sum + size(script), 0) : 0;
  const metadata = assets.reduce((sum, asset) => sum + 1400 + 4 * size(JSON.stringify([
    asset.id, asset.title, asset.destination, asset.license, asset.attribution, asset.source_url, asset.version,
    reader?.assets?.[asset.id]?.topics
  ])) + 600 * partCount(asset), 0);
  // The planner already accounts for the optional search payload. Limit
  // the on-drive placeholder so probing an estimated drive costs a small write.
  const searchReserve = search ? Math.min(searchBudget, 16 * 2 ** 20) : 0;
  return fixed + metadata + (reader ? 64 * 1024 + assets.length * 512 : 0) + size(verify) + 4096 + excluded.length * 512 + searchReserve;
}

function reportBody(missing, keptInParts) {
  const omissions = missing.length ? "<h2>Missing files</h2><ul>" + missing.map(row =>
    "<li>" + escape(row.title) + " · " + escape(row.reason) + "</li>").join("") + "</ul>"
    : "<p>Every requested file available to this build is listed in the inventory.</p>";
  return omissions + (keptInParts.length ? "<h2>Kept in parts</h2><ul>" + keptInParts.map(row =>
    "<li>" + escape(row.title) + " · " + row.parts + " parts</li>").join("") + "</ul>" : "");
}

async function readerFiles(config, inventory, phone, missing, keptInParts, indexed, shared, syncedAt, iphone) {
  const {layout, css, assets: metadata, categories} = config;
  const files = inventory.map(asset => {
    const path = asset.parts[0].path;
    return {id: asset.id, title: asset.title, path, href: locator(path), kind: metadata[asset.id]?.kind ||
      FORMATS[asset.format] || asset.format.toUpperCase(), format: asset.format, bytes: asset.bytes,
      ...(asset.parts.length > 1 ? {parts: asset.parts.length} : {}),
      ...(metadata[asset.id]?.kiwixKind ? {kiwixKind: metadata[asset.id].kiwixKind} : {})};
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
  const parts = new Map(inventory.map(asset => [asset.id, asset.parts]));
  home.archives = documents.filter(row => row.format === "zim").map(row => ({...row,
    files: parts.get(row.id).map(({path, bytes}) => ({path, bytes}))}));
  const pages = new Map([["LIBRARY/INDEX/reader.js", config.runtime], ["LIBRARY/README.txt", config.readme],
    ...Object.entries(config.zim || {}).map(([name, text]) => ["LIBRARY/INDEX/" + name, text])]);
  // The static page is all a phone's file preview shows: no scripts, and often no working links.
  const link = (href, text) => render(layout.static_link, {href: escape(href), text: escape(text)});
  const filename = path => render(layout.static_file, {name: escape(path.slice(path.lastIndexOf("/") + 1))});
  const trail = path => {
    const split = path.lastIndexOf("/");
    return render(layout.static_trail, {folders: escape(path.slice(0, split).replaceAll("/", " › ")),
      file: path.endsWith("/") ? "" : filename(path)});
  };
  const amount = (value, unit) => String(value).replace(/\B(?=(\d{3})+$)/g, ",") + " " + unit + (value === 1 ? "" : "s");
  const staticRow = (title, detail, path, chapters = "") => render(layout.static_row,
    {title, detail: escape(detail), trail: path ? trail(path) : "", chapters});
  const staticSections = [render(layout.static_urgent, {rows: tasks.map(row => {
    if (!row.path) return staticRow(escape(row.task), "No guide on this drive.");
    const page = /#page=(\d+)$/.exec(row.href)?.[1];
    return staticRow(row.format === "zim" ? escape(row.task) : link(row.href, row.task), [row.title, page ? "page " + page : "",
      row.hint, row.articles.length ? "Look up " + row.articles.join(" / ") + " in Kiwix" : ""].filter(Boolean).join(" · "), row.path);
  }).join("")})];
  const shelves = [], catalogGroups = [];
  for (const category of categories) {
    const {id, name} = category;
    const members = documents.filter(row => (metadata[row.id]?.category || "other") === id);
    if (id === "health") members.push(...phone);
    const rows = grouped(members, metadata, id);
    home.categories.push({...category, count: rows.length});
    pages.set("LIBRARY/INDEX/c-" + id + ".js", data(id, rows));
    if (!rows.length) continue;
    catalogGroups.push({name, rows: members.sort(order)});
    const count = amount(rows.length, category.unit);
    const icon = category.icon ? render(layout.static_icon, {icon: escape(category.icon)}) : "";
    shelves.push(render(layout.static_section, {id, icon, name: escape(name), count, blurb: escape(category.blurb),
      rows: rows.map(row => staticRow(row.chapters || row.format === "zim" ? escape(row.title) : link(row.href, row.title),
        row.kind === "PDF" ? "" : row.kind, row.path, row.chapters ? render(layout.static_chapters, {items: row.chapters.map(chapter =>
          render(layout.static_chapter, {title: link(chapter.href, chapter.title),
            file: filename(chapter.path)})).join("")}) : "")).join("")}));
  }
  pages.set(phoneCatalogName, await phoneCatalog(catalogGroups, layout.phone_catalog, iphone?.path));
  if (shelves.length) staticSections.push(render(layout.static_shelves, {shelves: shelves.join("")}));
  if (documents.some(row => row.format === "zim")) {
    const devices = ["iphone", "android", "windows", "mac", "linux"].map(device => {
      const instructions = layout.devices[device];
      const folder = device === "mac" ? "MACOS" : device.toUpperCase();
      const install = device === "iphone" || readers.some(row => row.path.startsWith("LIBRARY/SOFTWARE/" + folder + "/"))
        ? instructions.install : "Install Kiwix while you have internet.";
      return render(layout.static_device, {id: device, name: escape(instructions.label), install: escape(install),
        open: escape(instructions.open), pick: escape(instructions.pick)});
    });
    staticSections.push(render(layout.static_archives, {devices: devices.join(""), software: readers.length
      ? render(layout.static_software, {rows: readers.map(row => staticRow(link(row.href, row.label), "", row.path)).join("")}) : ""}));
  }
  if (missing.length) {
    staticSections.push('<p class="note">This library is incomplete. See the <a href="LIBRARY/BUILD_REPORT.html">build report</a>.</p>');
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

// Keep the iPhone location a previous build saved; see savedPhoneDrive. name: the picked folder's name.
async function previousPhoneDrive(drive, name) {
  try {
    const file = await (await fileHandle(drive, "LIBRARY/BUILD_INFO.json")).getFile();
    return file.size <= 4 * 2 ** 20 ? savedPhoneDrive(JSON.parse(await file.text()).iphone_drive, name) : null;
  } catch {
    return null;
  }
}

export async function assembleLibrary(drive, {completed, missing, keptInParts = [], selectedCount = completed.length + missing.length,
    navigation, layouts, parts, signal, search, searchBudget, fetchFile, network, syncedAt, compact = false,
    unavailableSupport = [], searchMissing = false, publishReplacement, onPublished, driveName = drive.name}) {
  // Prepare new files alongside the active reader. Defer changes to existing
  // files, including fixed search model names, until assembly has succeeded.
  const staged = new Map();
  const output = publishReplacement ? {...drive,
    stagedFile(path) {
      if (staged.has(path)) return new Blob([staged.get(path)]);
    },
    async prepareWrite(path, contents) {
      if (!await optional(() => fileHandle(drive, path))) return drive.prepareWrite?.(path, contents);
      staged.set(path, contents);
      return false;
    }
  } : drive;
  const {verify} = navigation;
  const iphone = await previousPhoneDrive(drive, driveName);
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
        phoneChecksums.push(await transfer(output, phone.base, volume.file, volume, fetchFile, signal, network, path, 8_000_000));
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
      utility_tier: asset.utility_tier ?? null,
      parts: layouts.get(asset.id).map((part, index) => ({...part, sha256: parts[asset.id][index].sha256}))};
  });
  let indexed = {pages: new Map(), checksums: [], missing: []};
  let shared = {}, sharedChecksums = [];
  if (search) {
    try {
      const result = await assembleSearch(output, {completed, layouts, config: search, fetchFile, signal, network,
        budget: searchBudget - phoneBytes, versioned: Boolean(reader)});
      if (reader && result.pages.has("LIBRARY/SEARCH/rank.js")) {
        ({paths: shared, checksums: sharedChecksums} = await shareSearchSupport(output, result.checksums, signal));
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
  const reportOmissions = [...omissions, ...supportMissing].sort(order);
  let pages;
  if (reader) {
    try { pages = await readerFiles(reader, assets, phoneVolumes, reportOmissions, keptInParts, indexed, shared, syncedAt,
      iphone); }
    catch (error) {
      const issue = {kind: "reader", title: "Full reader", reason: error.message};
      supportMissing.push(issue);
      reportOmissions.push(issue);
    }
  }
  const result = {supportMissing, warnings: supportMissing.map(({title, reason}) => title + " — " + reason)};
  if (publishReplacement && supportMissing.some(row => row.kind === "reader" || row.kind === "search")) {
    return {...result, keptPublished: true};
  }
  pages ||= new Map([
    ["START_HERE.html", startPage(assets, reportOmissions)],
    ["LIBRARY/BUILD_REPORT.html", '<!doctype html><meta charset="utf-8"><title>Build report</title><h1>Build report</h1>' +
      reportBody(reportOmissions, keptInParts) + '<p><a href="INVENTORY.json">Every file, with its location</a></p>']
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
    layout: {entry_page: "START_HERE.html", content_directory: "LIBRARY"}, ...(iphone && {iphone_drive: iphone})}, null, 2) + "\n");

  const checksums = [...assets.flatMap(file => file.parts.map(part => part.sha256 + "  " + part.path)),
    ...indexed.checksums, ...sharedChecksums, ...phoneChecksums];
  for (const [path, contents] of pages) {
    signal?.throwIfAborted();
    await writeFile(output, path, contents);
    checksums.push(hash(contents) + "  " + path);
  }
  checksums.push(hash(start) + "  START_HERE.html");
  staged.set("LIBRARY/SHA256SUMS.txt", checksums.sort().join("\n") + "\n");
  staged.set("START_HERE.html", start);
  // Pause can stop preparation. Once publication begins, finish switching the reader.
  signal?.throwIfAborted();
  if (publishReplacement) await publishReplacement(staged);
  else for (const [path, contents] of staged) {
    signal?.throwIfAborted();
    await writeFile(drive, path, contents);
  }
  // SHA256SUMS lines contain a 64-character digest, two spaces and the full path.
  onPublished?.(new Map(checksums.map(line => [line.slice(66), line.slice(0, 64)])));
  return result;
}
