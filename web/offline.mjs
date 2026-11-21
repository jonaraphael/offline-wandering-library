import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {writeFile} from "./drive.mjs";
import {assembleSearch} from "./search-build.mjs";

const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);
const href = path => path.split("/").map(encodeURIComponent).join("/");
const link = (path, text) => '<a href="' + href(path) + '">' + escape(text) + "</a>";
const titleOrder = (a, b) => a.title.localeCompare(b.title, "en");

function template(layout, name, values) {
  return layout[name].replace(/\{\{([a-z_]+)\}\}/g, (_, slot) => values[slot] ?? "");
}

function emergencyRoutes(layout, assets, layouts) {
  if (!layout) return {directory: "", archiveTasks: ""};
  const archiveTasks = [];
  const rows = layout.tasks.map(([task, candidates], index) => {
    const match = candidates.find(([id]) => assets.has(id));
    if (!match) return template(layout, "task_missing", {task: escape(task)});
    const [id, fragment = "", hint = "", entries = []] = match;
    const path = layouts.get(id)[0].path;
    const title = assets.get(id).title;
    const row = {task: escape(task), title: escape(title), path: escape(path),
      href: href(path) + escape(fragment), hint: hint ? " · " + escape(hint) : ""};
    if (entries.length) {
      const anchor = "emergency-" + (index + 1);
      archiveTasks.push(template(layout, "archive_task", {...row, anchor, href: href("../../" + path),
        entries: entries.map(([label, locator]) => template(layout, "archive_task_entry",
          {title: escape(label), path: escape(locator)})).join("")}));
      row.href = "LIBRARY/INDEX/sections.html#" + anchor;
      row.title = escape(entries.map(([label]) => label).join(" / "));
      row.hint = " · " + escape(entries.map(([, locator]) => locator).join(", ")) + " in Kiwix";
    }
    return template(layout, "task_link", row);
  });
  return {directory: template(layout, "emergency", {rows: rows.join("")}), archiveTasks: archiveTasks.join("")};
}

function assetList(assets, layouts, prefix) {
  if (!assets.length) return "<p>No files in this build.</p>";
  return '<ul class="assets">' + assets.map(asset => {
    const parts = layouts.get(asset.id);
    const description = parts.length > 1 ? parts.length + " parts. Open the first part in Kiwix and keep all parts together." :
      asset.format === "zim" ? "Open in Kiwix." : "";
    return "<li>" + link(prefix + parts[0].path, asset.title) + (description ? "<br>" + escape(description) : "") +
      "<br><code>" + escape(parts[0].path) + "</code></li>";
  }).join("") + "</ul>";
}

export async function assembleLibrary(drive, {completed, missing, navigation, layouts, parts, signal, search, searchBudget, fetchFile, network}) {
  const {css = "", layout, groups = [], letters = [], collections = [], assets: metadata = {}, sections = {},
    locators = {}, topics = {}, entrances = {}, assignments = [], input_hashes = {}, verify = ""} = navigation;
  function document(title, body, prefix = "") {
    const policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">';
    const heading = "<h1>" + escape(title) + "</h1>";
    const nav = [["START_HERE.html", "Start here"], ["LIBRARY/SEARCH.html", "Search"],
      ["LIBRARY/INDEX/categories.html", "Categories"], ["LIBRARY/INDEX/topics.html", "Topic atlas"],
      ["LIBRARY/INDEX/critical.html", "Critical content"], ["LIBRARY/INDEX/books.html", "Book contents"]]
      .filter(([, label]) => search || label !== "Search").map(([path, label]) => link(prefix + path, label)).join(" ");
    if (!layout) return "<!doctype html><title>" + escape(title) + "</title>" + heading + body;
    return template(layout, "page", {title:escape(title), css, heading, nav, body, policy,
      footer:"Catalog text is readable without JavaScript or internet. Opening links depends on your viewer."});
  }
  const documents = completed.filter(asset => metadata[asset.id]?.document !== false).sort(titleOrder);
  const inventory = completed.map(asset => ({
    id: asset.id, title: asset.title, destination: layouts.get(asset.id)[0].path.slice("LIBRARY/".length), format: asset.format, license: asset.license, attribution: metadata[asset.id]?.attribution,
    publisher: metadata[asset.id]?.publisher, bytes: asset.size_bytes, sha256: asset.sha256,
    parts: layouts.get(asset.id).map((part, index) => ({path: part.path, bytes: part.bytes, sha256: parts[asset.id][index].sha256}))
  }));
  const index = "LIBRARY/INDEX/";
  const pages = new Map();
  const shelfLinks = [];
  const shelves = [
    ["critical", "Critical references", documents.filter(asset => asset.critical)],
    ["phone", "Critical files for Files and PDF viewers", documents.filter(asset =>
      asset.critical && ["pdf", "epub", "html", "htm"].includes(asset.format))],
    ["textbooks", "Textbooks", documents.filter(asset => metadata[asset.id]?.shelves?.includes("textbooks"))],
    ["illustrated-guides", "Illustrated guides", documents.filter(asset => metadata[asset.id]?.shelves?.includes("illustrated-guides"))],
    ...collections.map(([id, title]) => [id, title, documents.filter(asset => metadata[asset.id]?.collections?.includes(id))])
  ];
  for (const [id, title, assets] of shelves) {
    const path = index + id + ".html";
    if (assets.length) shelfLinks.push("<li>" + link(path, title + " (" + assets.length + ")") + "</li>");
    pages.set(path, document(title, assetList(assets, layouts, "../../"), "../../"));
  }

  const categories = groups.map(([id, title]) => '<section id="' + escape(id) + '"><h2>' + escape(title) +
    "</h2>" + assetList(documents.filter(asset => metadata[asset.id]?.group === id), layouts, "../../") + "</section>");
  pages.set(index + "categories.html", document("Browse by category", categories.join(""), "../../"));
  const alphabet = "<p>" + letters.map(letter => link(letter + ".html", letter)).join(" ") + "</p>";
  for (const letter of letters) {
    pages.set(index + letter + ".html", document("Titles: " + letter,
      alphabet + assetList(documents.filter(asset => metadata[asset.id]?.letter === letter), layouts, "../../"), "../../"));
  }

  const byId = new Map(documents.map(asset => [asset.id, asset]));
  const topicAssets = new Map(Object.keys(topics).map(id => [id, new Map()]));
  for (const assignment of assignments) {
    if (!byId.has(assignment.asset_id)) continue;
    const pending = [assignment.topic_id], visited = new Set();
    for (const id of pending) {
      if (!topicAssets.has(id) || visited.has(id)) continue;
      visited.add(id);
      topicAssets.get(id).set(assignment.asset_id, byId.get(assignment.asset_id));
      pending.push(...topics[id].parents);
    }
  }
  const visible = id => topicAssets.get(id)?.size > 0;
  const topicGroups = Object.entries(entrances).map(([label, ids]) => "<h2>" + escape(label) +
    "</h2><ul>" + ids.filter(visible).map(id => "<li>" + link("topics/" + id + ".html", topics[id].title) + "</li>").join("") + "</ul>");
  pages.set(index + "topics.html", document("Topic atlas",
    topicGroups.join(""), "../../"));
  for (const [id, topic] of Object.entries(topics)) {
    const children = Object.values(topics).filter(child => child.parents.includes(id) && visible(child.id)).sort(titleOrder);
    const list = children.map(child => "<li>" + link(child.id + ".html", child.title) + "</li>").join("");
    pages.set(index + "topics/" + id + ".html", document(topic.title, "<p>" +
      escape(topic.description) + "</p>" + (list ? "<h2>Subtopics</h2><ul>" + list + "</ul>" : "") +
      assetList([...topicAssets.get(id).values()].sort(titleOrder), layouts, "../../../"), "../../../"));
  }

  const omitted = missing.length ? '<h2>Unavailable files</h2><ul>' + missing.map(row =>
    "<li>" + escape(row.title) + " — " + escape(row.reason) + "</li>").join("") + "</ul>" :
    "<p>All requested files were verified.</p>";
  pages.set(index + "build-report.html", document("Build report", omitted +
    "<p>" + link("../INVENTORY.html", "Inventory and sources") + "</p>", "../../"));
  pages.set("LIBRARY/INVENTORY.json", JSON.stringify({schema_version:1, assets:inventory, unresolved:missing,
    content_complete:!missing.length}, null, 2) + "\n");
  pages.set("LIBRARY/INVENTORY.html", document("Inventory, sources and licenses",
    "<ul>" + inventory.map(row => "<li>" + link(row.destination, row.title) + " · " + escape(row.license) +
      (row.attribution ? " · " + escape(row.attribution) : "") + "</li>").join("") + "</ul>", "../"));
  if (verify) pages.set("LIBRARY/VERIFY.py", verify);
  pages.set("LIBRARY/SOURCE_NOTES.txt", inventory.map(file => [
    file.title, file.license, file.attribution, ...file.parts.map(part => part.path)
  ].filter(Boolean).join("\n")).join("\n\n") + "\n");
  pages.set("LIBRARY/README.txt", "Open ../START_HERE.html on this drive. Use INDEX/phone.html for directly readable critical files.\n");
  pages.set("LIBRARY/BUILD_INFO.json", JSON.stringify({schema_version:1, asset_count:inventory.length,
    content_complete:!missing.length, layout:{entry_page:"START_HERE.html", content_directory:"LIBRARY"}}, null, 2) + "\n");

  const indexed = search ? await assembleSearch(drive, {completed, layouts,
    config: search, fetchFile, signal, network, budget: searchBudget}) : {pages: [], checksums: [], warnings: []};
  for (const [path, contents] of indexed.pages) pages.set(path, contents);
  const entrypoints = documents.flatMap(asset => {
    const source = locators[asset.id];
    if (!source) return [];
    const path = "../../" + layouts.get(asset.id)[0].path;
    const marks = (source.entrypoints || []).map(([value, title]) => typeof value === "number"
      ? '<li><a href="' + href(path) + '#page=' + value + '">' + escape(title) + '</a></li>'
      : "<li>" + escape(title) + " · <code>" + escape(value) + "</code></li>");
    if (source.main) marks.unshift("<li>Archive start · <code>" + escape(source.main) + "</code></li>");
    return marks.length ? ["<h2>" + link(path, asset.title) + "</h2><ul>" + marks.join("") + "</ul>"] : [];
  });
  const emergency = emergencyRoutes(layout, byId, layouts);
  pages.set(index + "sections.html", document("Sections and archive entry points",
    emergency.archiveTasks + entrypoints.join("") || "<p>Browse the included files through the topic atlas or categories.</p>", "../../"));
  const books = documents.filter(asset => sections[asset.id]?.source_sha256 === asset.sha256 ||
    metadata[asset.id]?.shelves?.includes("textbooks"));
  pages.set(index + "books.html", document("Book and source contents",
    "<ul>" + books.map(asset => "<li>" + link("books/" + asset.id + ".html", asset.title) + "</li>").join("") + "</ul>", "../../"));
  for (const asset of books) {
    const reference = "../../../" + layouts.get(asset.id)[0].path;
    const reviewed = sections[asset.id]?.source_sha256 === asset.sha256 ? sections[asset.id].sections : [];
    const entries = reviewed.map(({title, locator}) => {
      const fragment = {"pdf-page": "page=" + locator.page, "html-anchor": encodeURIComponent(locator.id),
        "media-time": "t=" + locator.seconds}[locator.type];
      return "<li>" + (fragment ? '<a href="' + href(reference) + "#" + fragment + '">' + escape(title) + "</a>" :
        escape(title) + (locator.path ? " · <code>" + escape(locator.path) + "</code>" : "")) + "</li>";
    });
    const body = "<p>" + link(reference, "Open complete document") + "</p>" +
      (entries.length ? "<ul>" + entries.join("") + "</ul>" :
        "<p>No verified source contents are available. See the original contents pages.</p>");
    pages.set(index + "books/" + asset.id + ".html", document(asset.title + ": source contents", body, "../../../"));
  }
  if (letters.length) {
    const choices = Object.values(topics).filter(topic => visible(topic.id)).flatMap(topic =>
      [topic.title, ...(topic.aliases || [])].map(label => [label, topic.id]));
    for (const letter of letters) {
      const list = choices.filter(([label]) => {
        const first = label.trim()[0]?.normalize("NFD")[0].toUpperCase() || "";
        const bucket = /^[A-Z]$/.test(first) ? first : /^\d$/.test(first) ? "0-9" : "other";
        return bucket === letter;
      }).sort(([a], [b]) => a.localeCompare(b, "en"));
      pages.set(index + "topic-a-z/" + letter + ".html", document("Topic names: " + letter,
        alphabet + "<ul>" + list.map(([label, id]) => "<li>" + link("../topics/" + id + ".html", label) + "</li>").join("") +
        "</ul>", "../../../"));
    }
  }
  if (Object.keys(topics).length) {
    const included_topic_ids = Object.keys(topics).filter(visible).sort();
    const source_maps = Object.fromEntries(books.filter(asset => sections[asset.id]?.source_sha256 === asset.sha256)
      .map(asset => [asset.id, {source_sha256: asset.sha256, section_count: sections[asset.id].sections.length}]));
    pages.set(index + "navigation-report.json", JSON.stringify({schema_version: 1,
      selected_asset_count: documents.length, included_topic_ids, input_hashes, source_maps}, null, 2) + "\n");
  }
  const readers = completed.filter(asset => layouts.get(asset.id)[0].path.startsWith("LIBRARY/SOFTWARE/"));
  const readerIndex = readers.length ? '<h2 id="readers">Archive readers</h2>' +
    assetList(readers, layouts, "") : "";
  const start = document("Offline Wandering Library",
    emergency.directory + '<p>' + (search ? link("LIBRARY/SEARCH.html", "Search offline") + ' ' : '') +
    link(index + "topics.html", "Topic atlas") + (letters.length ? " · " +
      link(index + "topic-a-z/A.html", "Topics A–Z") : "") + ' <a href="#shelves">Shelves</a> <a href="#file-catalog">All files</a></p>' +
    (missing.length ? '<p class="notice">Some files are missing. ' +
      link(index + "build-report.html", "See the build report") + ".</p>" : "") +
    '<p class="notice">On a phone, open this page in Files. If a link does not open, find the printed path on this drive. ' +
    'Install Kiwix on your phone while you have internet. For a split archive, keep all parts in one folder.</p>' +
    '<p>' + link(index + "phone.html", "Open critical files with Files or a PDF viewer") + '</p>' +
    '<p>' + link(index + "sections.html", "Sections and archive entry points") + " · " +
    link(index + "books.html", "Book contents") + " · " +
    link(index + "build-report.html", "Build report" + (missing.length ? " (" + missing.length + " unavailable)" : "")) + "</p>" +
    readerIndex + '<h2 id="shelves">Shelves</h2><ul class="cards">' + shelfLinks.join("") + '</ul>' +
    '<h2 id="file-catalog">All files (' + documents.length + ")</h2>" + assetList(documents, layouts, ""));

  const checksums = [...inventory.flatMap(file => file.parts.map(part => part.sha256 + "  " + part.path)),
    ...indexed.checksums];
  const encode = new TextEncoder();
  for (const [path, contents] of pages) {
    signal?.throwIfAborted();
    await writeFile(drive, path, contents);
    checksums.push(bytesToHex(sha256(encode.encode(contents))) + "  " + path);
  }
  checksums.push(bytesToHex(sha256(encode.encode(start))) + "  START_HERE.html");
  await writeFile(drive, "LIBRARY/SHA256SUMS.txt", checksums.sort().join("\n") + "\n");
  await writeFile(drive, "START_HERE.html", start);
  return indexed.warnings;
}
