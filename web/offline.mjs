import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {writeFile} from "./drive.mjs";
import {assembleSearch, transfer} from "./search-build.mjs";

const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);
const href = path => path.split("/").map(encodeURIComponent).join("/");
const link = (path, text) => '<a href="' + href(path) + '">' + escape(text) + "</a>";
const titleOrder = (a, b) => a.title.localeCompare(b.title, "en");

const size = bytes => {
  const [scale, unit] = bytes >= 1e9 ? [1e9, "GB"] : bytes >= 1e6 ? [1e6, "MB"] : [1e3, "kB"];
  const value = bytes / scale;
  return (value >= 10 ? Math.round(value) : Math.round(value * 10) / 10) + " " + unit;
};
const count = (number, one, many = one + "s") => number + " " + (number === 1 ? one : many);
const FORMATS = {pdf: "PDF", html: "Web page", htm: "Web page", epub: "EPUB book", zim: "Kiwix archive", txt: "Text", zip: "ZIP"};

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
    const row = {task: escape(task), title: escape(title), path: escape(path), icon: layout.task_icons?.[index] || "",
      href: href(path) + escape(fragment), hint: hint ? " · " + escape(hint) : ""};
    if (entries.length) {
      const anchor = "emergency-" + (index + 1);
      archiveTasks.push(template(layout, "archive_task", {...row, anchor, href: href("../../" + path),
        entries: entries.map(([label, locator]) => template(layout, "archive_task_entry",
          {title: escape(label), path: escape(locator)})).join("")}));
      row.href = "LIBRARY/INDEX/sections.html#" + anchor;
      row.title = escape(title + ": " + entries.map(([label]) => label).join(" / "));
      row.hint = " · opens in the Kiwix app";
    }
    return template(layout, "task_link", row);
  });
  return {directory: template(layout, "emergency", {rows: rows.join("")}), archiveTasks: archiveTasks.join("")};
}

export async function assembleLibrary(drive, {completed, missing, navigation, layouts, parts, signal, search, searchBudget, fetchFile, network}) {
  const {css = "", layout, groups = [], letters = [], collections = [], assets: metadata = {}, sections = {},
    locators = {}, topics = {}, entrances = {}, assignments = [], input_hashes = {}, verify = "", phone} = navigation;
  const phoneVolumes = [];
  const phoneWarnings = [];
  let phoneBytes = 0;
  if (phone && completed.some(asset => asset.id === phone.source_id && asset.sha256 === phone.source_sha256)) {
    for (const volume of phone.volumes) {
      try {
        const path = "LIBRARY/" + phone.destination + volume.file;
        phoneBytes += volume.bytes;
        const checksum = await transfer(drive, phone.base, volume.file, volume, fetchFile, signal, network, path, 8_000_000);
        phoneVolumes.push({path, title: volume.title, checksum});
      } catch (error) {
        signal?.throwIfAborted();
        phoneWarnings.push("WikiMed phone volume " + volume.title + " — " + error.message);
      }
    }
  }
  const index = "LIBRARY/INDEX/";
  const hasTopics = Object.keys(topics).length > 0;
  const tabs = [["START_HERE.html", "Home", true], ["LIBRARY/SEARCH.html", "Search", Boolean(search)],
    [index + "critical.html", "Essentials", true], [index + "topics.html", "Subjects", hasTopics],
    [index + "books.html", "Books", true], [index + "categories.html", "All files", true],
    ["START_HERE.html#help", "Help", Boolean(layout?.help)]];
  const tabBar = (prefix, current) => tabs.filter(([, , shown]) => shown).map(([path, label]) => {
    const [file, fragment] = path.split("#");
    return '<a href="' + href(prefix + file) + (fragment ? "#" + fragment : "") + '"' +
      (path === current ? ' aria-current="page"' : "") + ">" + label + "</a>";
  }).join("");
  const strict = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'";
  function document(title, body, prefix = "", current = "", {heading, csp = strict} = {}) {
    const policy = '<meta http-equiv="Content-Security-Policy" content="' + escape(csp) + '">';
    heading ??= "<h1>" + escape(title) + "</h1>";
    if (!layout) return "<!doctype html><title>" + escape(title) + "</title>" + heading + body;
    return template(layout, "page", {title: escape(title), css, heading, nav: tabBar(prefix, current), body, policy,
      footer: "Offline Wandering Library. Every page here works without internet."});
  }

  // A book published as one file per chapter is shown once, with its chapters inside.
  // On the start page a book opens expanded so it reads in viewers that cannot
  // unfold it; the search script folds it again where links and scripts work.
  function assetList(assets, prefix, unfolded = false) {
    if (!assets.length) return '<p class="meta">Nothing here in this library.</p>';
    const books = new Map();
    for (const asset of assets) {
      const book = metadata[asset.id]?.book;
      if (!book) continue;
      const key = layouts.get(asset.id)[0].path.replace(/[^/]+$/, "") + "\n" + book.title;
      if (!books.has(key)) books.set(key, []);
      books.get(key).push(asset);
    }
    const shown = new Set();
    const rows = [];
    for (const asset of assets) {
      const layoutParts = layouts.get(asset.id);
      const path = layoutParts[0].path;
      const book = metadata[asset.id]?.book;
      const key = book && path.replace(/[^/]+$/, "") + "\n" + book.title;
      const members = key ? books.get(key) : [];
      if (members.length >= 3) {
        if (shown.has(key)) continue;
        shown.add(key);
        members.sort((a, b) => metadata[a.id].book.order - metadata[b.id].book.order);
        const numbered = members.filter(member => /^\d/.test(metadata[member.id].book.chapter)).length * 2 > members.length;
        const kind = numbered ? "chapters" : asset.format === "zim" ? "archives" : "files";
        rows.push("<li><details" + (unfolded ? " open" : "") + "><summary>" + escape(book.title) + ' <span class="meta">' + members.length + " " + kind +
          " · " + (FORMATS[asset.format] || asset.format.toUpperCase()) + (metadata[asset.id]?.publisher ? " · " + escape(metadata[asset.id].publisher) : "") +
          "</span></summary><ol>" + members.map(member => "<li>" + link(prefix + layouts.get(member.id)[0].path, metadata[member.id].book.chapter) +
            "</li>").join("") + '</ol><span class="where">' + escape(path.replace(/[^/]+$/, "")) + "</span></details></li>");
        continue;
      }
      const notes = [FORMATS[asset.format] || asset.format.toUpperCase(), size(asset.size_bytes)];
      if (metadata[asset.id]?.publisher) notes.push(escape(metadata[asset.id].publisher));
      if (layoutParts.length > 1) notes.push("in " + layoutParts.length + " parts; keep them together and open the first");
      rows.push("<li>" + link(prefix + path, asset.title) +
        (asset.format === "zim" ? ' <span class="badge">Opens with Kiwix</span>' : "") +
        '<span class="meta">' + notes.join(" · ") + '</span><span class="where">' + escape(path) + "</span></li>");
    }
    return '<ul class="assets">' + rows.join("") + "</ul>";
  }
  const byGroup = (assets, prefix) => {
    const present = groups.filter(([id]) => assets.some(asset => metadata[asset.id]?.group === id));
    const rest = assets.filter(asset => !groups.some(([id]) => metadata[asset.id]?.group === id));
    if (!present.length) return assetList(assets, prefix);
    return (present.length > 1 ? '<ul class="chips">' + present.map(([id, title]) =>
      '<li><a href="#' + escape(id) + '">' + escape(title) + "</a></li>").join("") + "</ul>" : "") +
      present.map(([id, title]) => {
        const members = assets.filter(asset => metadata[asset.id]?.group === id);
        return '<section id="' + escape(id) + '"><h2>' + escape(title) + ' <span class="badge">' + members.length +
          "</span></h2>" + assetList(members, prefix) + "</section>";
      }).join("") + (rest.length ? "<h2>More</h2>" + assetList(rest, prefix) : "");
  };

  const documents = completed.filter(asset => metadata[asset.id]?.document !== false).sort(titleOrder);
  const inventory = completed.map(asset => ({
    id: asset.id, title: asset.title, destination: layouts.get(asset.id)[0].path.slice("LIBRARY/".length), format: asset.format, license: asset.license, attribution: metadata[asset.id]?.attribution,
    publisher: metadata[asset.id]?.publisher, bytes: asset.size_bytes, sha256: asset.sha256,
    parts: layouts.get(asset.id).map((part, index) => ({path: part.path, bytes: part.bytes, sha256: parts[asset.id][index].sha256}))
  }));
  const pages = new Map();
  const critical = documents.filter(asset => asset.critical);
  const direct = critical.filter(asset => ["pdf", "epub", "html", "htm"].includes(asset.format));
  const handbooks = phoneVolumes.length ? '<h2>WikiMed medical handbooks</h2><p class="meta">The medical encyclopedia as ' +
    'PDFs, for devices without the Kiwix app.</p><ul class="assets">' + phoneVolumes.map(({path, title}) => "<li>" +
    link("../../" + path, "WikiMed: " + title) + '<span class="where">' + escape(path) + "</span></li>").join("") + "</ul>" : "";
  pages.set(index + "critical.html", document("Essentials",
    '<p class="lede">First aid, medical care, safe water, food and shelter. Start here when it matters.</p>' +
    (direct.length ? "<p>" + link("phone.html", "Show only what opens without any app") + "</p>" : "") +
    byGroup(critical, "../../"), "../../", index + "critical.html"));
  pages.set(index + "phone.html", document("Essentials that open without an app",
    '<p class="lede">These are ordinary PDFs and web pages. A phone’s Files app opens them directly.</p>' + handbooks +
    byGroup(direct, "../../"), "../../", index + "critical.html"));
  const shelves = [
    ["critical", "Essentials", "First aid, medical care, water, food and shelter.", critical],
    ["textbooks", "Textbooks", "Complete school and college textbooks.",
      documents.filter(asset => metadata[asset.id]?.shelves?.includes("textbooks"))],
    ["illustrated-guides", "Illustrated guides", "Practical guides with diagrams and photographs.",
      documents.filter(asset => metadata[asset.id]?.shelves?.includes("illustrated-guides"))],
    ...collections.map(([id, title]) => [id, title, "A reading collection.",
      documents.filter(asset => metadata[asset.id]?.collections?.includes(id))])
  ];
  for (const [id, title, note, assets] of shelves.slice(1)) {
    pages.set(index + id + ".html", document(title, '<p class="lede">' + note + "</p>" + assetList(assets, "../../"),
      "../../", index + "books.html"));
  }
  pages.set(index + "categories.html", document("All files",
    '<p class="lede">' + count(documents.length, "book, guide or archive", "books, guides and archives") + ", by category.</p>" +
    byGroup(documents, "../../"), "../../", index + "categories.html"));
  const alphabet = '<ul class="chips">' + letters.map(letter => "<li>" + link(letter + ".html", letter) + "</li>").join("") + "</ul>";
  for (const letter of letters) {
    pages.set(index + letter + ".html", document("Titles: " + letter,
      alphabet + assetList(documents.filter(asset => metadata[asset.id]?.letter === letter), "../../"), "../../",
      index + "categories.html"));
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
  const topicCards = (ids, prefix) => '<ul class="cards">' + ids.map(id => '<li><a href="' + href(prefix + id + ".html") +
    '"><strong>' + escape(topics[id].title) + "</strong><span>" + escape(topics[id].description || "") + "</span>" +
    '<span>' + count(topicAssets.get(id).size, "document") + "</span></a></li>").join("") + "</ul>";
  const entranceOrder = ["subjects", "tasks", "learn", ...Object.keys(entrances)].filter((key, at, all) =>
    entrances[key] && all.indexOf(key) === at);
  const entranceTitle = key => layout?.entrances?.[key] || key;
  pages.set(index + "topics.html", document("Subjects",
    '<p class="lede">Pick a subject to see everything this library holds on it.</p>' +
    entranceOrder.map(key => [key, entrances[key].filter(visible)]).filter(([, ids]) => ids.length).map(([key, ids]) =>
      '<section id="' + escape(key) + '"><h2>' + escape(entranceTitle(key)) + "</h2>" + topicCards(ids, "topics/") + "</section>").join("") +
    (letters.length ? "<p>" + link("topic-a-z/A.html", "All topic names, A to Z") + "</p>" : ""),
    "../../", index + "topics.html"));
  for (const [id, topic] of Object.entries(topics)) {
    const children = Object.values(topics).filter(child => child.parents.includes(id) && visible(child.id)).sort(titleOrder);
    const parents = topic.parents.filter(visible);
    const trail = '<p class="breadcrumb">' + link("../topics.html", "Subjects") + parents.map(parent =>
      " › " + link(parent + ".html", topics[parent].title)).join("") + "</p>";
    pages.set(index + "topics/" + id + ".html", document(topic.title, trail + "<h1>" + escape(topic.title) + "</h1>" +
      '<p class="lede">' + escape(topic.description) + "</p>" +
      (children.length ? "<h2>Narrower subjects</h2>" + topicCards(children.map(child => child.id), "") : "") +
      "<h2>" + count(topicAssets.get(id).size, "document") + "</h2>" +
      assetList([...topicAssets.get(id).values()].sort(titleOrder), "../../../"), "../../../", index + "topics.html", {heading: ""}));
  }

  const omitted = missing.length ? '<h2>Could not be added</h2><ul class="assets">' + missing.map(row =>
    "<li><strong>" + escape(row.title) + '</strong><span class="meta">' + escape(row.reason) + "</span></li>").join("") + "</ul>" +
    '<p class="meta">Build again on the library website with this drive attached to retry them.</p>' :
    '<p class="notice">Every requested file was downloaded and checked.</p>';
  pages.set(index + "build-report.html", document("Build report", omitted +
    "<p>" + link("../INVENTORY.html", "Inventory, sources and licenses") + "</p>", "../../"));
  pages.set("LIBRARY/INVENTORY.json", JSON.stringify({schema_version:1, assets:inventory, unresolved:missing,
    content_complete:!missing.length}, null, 2) + "\n");
  pages.set("LIBRARY/INVENTORY.html", document("Inventory, sources and licenses",
    '<p class="lede">Every file on this drive, with its license and credit.</p><ul class="assets">' + inventory.map(row =>
      "<li>" + link(row.destination, row.title) + '<span class="meta">' + escape(row.license) +
      (row.attribution ? " · " + escape(row.attribution) : "") + "</span></li>").join("") + "</ul>", "../"));
  if (verify) pages.set("LIBRARY/VERIFY.py", verify);
  pages.set("LIBRARY/SOURCE_NOTES.txt", inventory.map(file => [
    file.title, file.license, file.attribution, ...file.parts.map(part => part.path)
  ].filter(Boolean).join("\n")).join("\n\n") + "\n");
  pages.set("LIBRARY/README.txt", "Open ../START_HERE.html on this drive. Use INDEX/phone.html for directly readable critical files.\n");
  pages.set("LIBRARY/BUILD_INFO.json", JSON.stringify({schema_version:1, asset_count:inventory.length,
    content_complete:!missing.length, layout:{entry_page:"START_HERE.html", content_directory:"LIBRARY"}}, null, 2) + "\n");

  const indexed = search ? await assembleSearch(drive, {completed, layouts,
    config: search, fetchFile, signal, network, budget: searchBudget - phoneBytes}) : {pages: [], checksums: [], warnings: []};
  for (const [path, contents] of indexed.pages) {
    // The search page shares the tab bar of the other pages in this build.
    pages.set(path, path === "LIBRARY/SEARCH.html" && layout ? contents.replace(/<!-- OWL_NAV -->[\s\S]*?<!-- \/OWL_NAV -->/,
      () => '<nav aria-label="Library navigation">' + tabBar("../", "LIBRARY/SEARCH.html") + "</nav>") : contents);
  }
  // Headings found in each document, without bare page numbers or repeats.
  const entrypoints = documents.flatMap(asset => {
    const source = locators[asset.id];
    if (!source) return [];
    const path = "../../" + layouts.get(asset.id)[0].path;
    const seen = new Set();
    const marks = (source.entrypoints || []).flatMap(([value, title]) => {
      const heading = String(title).replace(/\s*·\s*Pages? \d+(?:–\d+)?$/, "");
      if (/^Pages? \d+(?:–\d+)?$/.test(heading) || seen.has(heading)) return [];
      seen.add(heading);
      return [typeof value === "number"
        ? '<li><a href="' + href(path) + '#page=' + value + '">' + escape(heading) + '</a> <span class="meta">page ' + value + "</span></li>"
        : "<li>" + escape(heading) + " · <code>" + escape(value) + "</code></li>"];
    });
    if (source.main) marks.unshift("<li>Archive start · <code>" + escape(source.main) + "</code></li>");
    return marks.length ? ['<details class="fold"><summary>' + escape(asset.title) + "</summary><div><p>" +
      link(path, "Open the document") + "</p><ul>" + marks.join("") + "</ul></div></details>"] : [];
  });
  const emergency = emergencyRoutes(layout, byId, layouts);
  pages.set(index + "sections.html", document("Find a place inside a document",
    emergency.archiveTasks + (entrypoints.length ? "<h2>Headings inside each document</h2>" + entrypoints.join("") : "") ||
    "<p>Browse the files through the subjects or categories.</p>", "../../"));
  const books = documents.filter(asset => sections[asset.id]?.source_sha256 === asset.sha256 ||
    metadata[asset.id]?.shelves?.includes("textbooks"));
  const chaptered = documents.filter(asset => metadata[asset.id]?.book && asset.format !== "zim");
  const chapterBooks = assetList(chaptered, "../../");
  pages.set(index + "books.html", document("Books",
    '<p class="lede">Whole books to read from cover to cover.</p>' +
    (chaptered.length && chapterBooks.includes("<details>") ? "<h2>Handbooks, chapter by chapter</h2>" + chapterBooks : "") +
    (books.length ? "<h2>Textbooks</h2>" + '<ul class="assets">' + books.map(asset => "<li>" +
      link("../../" + layouts.get(asset.id)[0].path, asset.title) + '<span class="meta">' +
      [FORMATS[asset.format] || asset.format.toUpperCase(), size(asset.size_bytes), metadata[asset.id]?.publisher && escape(metadata[asset.id].publisher)].filter(Boolean).join(" · ") +
      " · " + link("books/" + asset.id + ".html", sections[asset.id]?.source_sha256 === asset.sha256 ? "Contents" : "Details") +
      '</span><span class="where">' + escape(layouts.get(asset.id)[0].path) + "</span></li>").join("") + "</ul>" : "") +
    (!books.length && !chaptered.length ? '<p class="meta">No whole books are in this library.</p>' : ""),
    "../../", index + "books.html"));
  for (const asset of books) {
    const reference = "../../../" + layouts.get(asset.id)[0].path;
    const reviewed = sections[asset.id]?.source_sha256 === asset.sha256 ? sections[asset.id].sections : [];
    const entries = reviewed.map(({title, locator}) => {
      const fragment = {"pdf-page": "page=" + locator.page, "html-anchor": encodeURIComponent(locator.id),
        "media-time": "t=" + locator.seconds}[locator.type];
      return "<li>" + (fragment ? '<a href="' + href(reference) + "#" + fragment + '">' + escape(title) + "</a>" :
        escape(title) + (locator.path ? " · <code>" + escape(locator.path) + "</code>" : "")) + "</li>";
    });
    const body = '<p class="breadcrumb">' + link("../books.html", "Books") + "</p><h1>" + escape(asset.title) + "</h1>" +
      '<ul class="cards"><li>' + '<a href="' + href(reference) + '"><strong>Open the book</strong><span>' +
      [FORMATS[asset.format] || asset.format.toUpperCase(), size(asset.size_bytes)].join(" · ") + "</span></a></li></ul>" +
      '<p><span class="where">' + escape(layouts.get(asset.id)[0].path) + "</span></p>" +
      (metadata[asset.id]?.attribution ? '<p class="meta">' + escape(metadata[asset.id].attribution) + "</p>" : "") +
      (entries.length ? "<h2>Contents</h2><ul>" + entries.join("") + "</ul>" : "");
    pages.set(index + "books/" + asset.id + ".html", document(asset.title, body, "../../../", index + "books.html", {heading: ""}));
  }
  if (letters.length) {
    const choices = Object.values(topics).filter(topic => visible(topic.id)).flatMap(topic =>
      [topic.title, ...(topic.aliases || [])].map(label => [label, topic.id]));
    const topicAlphabet = '<ul class="chips">' + letters.map(letter => "<li>" + link(letter + ".html", letter) + "</li>").join("") + "</ul>";
    for (const letter of letters) {
      const list = choices.filter(([label]) => {
        const first = label.trim()[0]?.normalize("NFD")[0].toUpperCase() || "";
        const bucket = /^[A-Z]$/.test(first) ? first : /^\d$/.test(first) ? "0-9" : "other";
        return bucket === letter;
      }).sort(([a], [b]) => a.localeCompare(b, "en"));
      pages.set(index + "topic-a-z/" + letter + ".html", document("Topic names: " + letter,
        topicAlphabet + (list.length ? '<ul class="assets">' + list.map(([label, id]) => "<li>" + link("../topics/" + id + ".html", label) + "</li>").join("") +
        "</ul>" : '<p class="meta">No topic names start with this letter.</p>'), "../../../", index + "topics.html"));
    }
  }
  if (Object.keys(topics).length) {
    const included_topic_ids = Object.keys(topics).filter(visible).sort();
    const source_maps = Object.fromEntries(books.filter(asset => sections[asset.id]?.source_sha256 === asset.sha256)
      .map(asset => [asset.id, {source_sha256: asset.sha256, section_count: sections[asset.id].sections.length}]));
    pages.set(index + "navigation-report.json", JSON.stringify({schema_version: 1,
      selected_asset_count: documents.length, included_topic_ids, input_hashes, source_maps}, null, 2) + "\n");
  }

  // The start page.
  const widget = search?.widget && layout ? search.widget : "";
  const subjects = (entrances.subjects || []).filter(visible), tasks = (entrances.tasks || []).filter(visible);
  const readerLinks = kind => (layout?.readers || []).filter(([, , device]) => device === kind).flatMap(([folder, label]) =>
    completed.filter(asset => layouts.get(asset.id)[0].path.startsWith("LIBRARY/" + folder)).map(asset =>
      "<li>" + link(layouts.get(asset.id)[0].path, label) + '<span class="where">' + escape(layouts.get(asset.id)[0].path) + "</span></li>"));
  const readerHelp = kind => readerLinks(kind).length ? template(layout, "help_readers", {links: readerLinks(kind).join("")}) :
    completed.some(asset => asset.format === "zim") ? layout.help_no_readers : "";
  const shelfCard = (path, title, note, number) => '<li><a href="' + href(path) + '"><strong>' + escape(title) +
    (number === undefined ? "" : ' <span class="badge">' + number + "</span>") + "</strong><span>" + escape(note) + "</span></a></li>";
  const shelfCards = [
    ...shelves.filter(([, , , assets]) => assets.length).map(([id, title, note, assets]) => shelfCard(index + id + ".html", title, note, assets.length)),
    shelfCard(index + "books.html", "Books", "Handbooks chapter by chapter, and whole textbooks."),
    shelfCard(index + "categories.html", "All files", "Everything on this drive, by category.", documents.length),
    ...(letters.length ? [shelfCard(index + "A.html", "Titles A to Z", "Look a title up by its first letter.")] : [])
  ];
  const fileCatalog = groups.filter(([id]) => documents.some(asset => metadata[asset.id]?.group === id)).map(([id, title]) => {
    const members = documents.filter(asset => metadata[asset.id]?.group === id);
    return '<details class="fold" open><summary>' + escape(title) + ' <span class="badge">' + members.length + "</span></summary>" +
      assetList(members, "", true) + "</details>";
  }).join("") || assetList(documents, "", true);
  const hero = '<p class="kicker">Works without internet</p><h1>What do you need to know?</h1><p class="lede">' +
    count(documents.length, "book, guide or archive is", "books, guides and archives are") + " stored on this drive." +
    (widget ? " Search them, or start with one of the paths below." : "") + "</p>" +
    (widget || (search ? "<p>" + link("LIBRARY/SEARCH.html", "Search offline") + "</p>" : ""));
  const start = document("Offline Wandering Library",
    (missing.length ? '<p class="notice warn">Some files could not be added to this library. ' +
      link(index + "build-report.html", "See which") + ".</p>" : "") +
    emergency.directory +
    (subjects.length ? '<section id="subjects"><h2>Browse by subject</h2>' + topicCards(subjects, index + "topics/") +
      (tasks.length ? "<h3>Practical guides</h3>" + '<ul class="chips">' + tasks.map(id => "<li>" +
        link(index + "topics/" + id + ".html", topics[id].title) + "</li>").join("") + "</ul>" : "") + "</section>" : "") +
    '<section id="shelves"><h2>Shelves</h2><ul class="cards">' + shelfCards.join("") + "</ul></section>" +
    (layout?.help ? template(layout, "help", {desktop: readerHelp("desktop"), android: readerHelp("android")}) : "") +
    '<section id="file-catalog"><h2>Everything on this drive</h2><p class="meta">Every file and the folder it is in, for ' +
    "devices that cannot follow links.</p>" + fileCatalog + "</section>" +
    '<p class="meta">' + link(index + "build-report.html", "Build report" + (missing.length ? " (" + missing.length + " not added)" : "")) +
    " · " + link("LIBRARY/INVENTORY.html", "Sources and licenses") + " · " + link(index + "sections.html", "Find a place inside a document") + "</p>",
    "", "START_HERE.html", {heading: hero, csp: widget ? search.csp || strict : strict});

  const checksums = [...inventory.flatMap(file => file.parts.map(part => part.sha256 + "  " + part.path)),
    ...indexed.checksums, ...phoneVolumes.map(({checksum}) => checksum)];
  const encode = new TextEncoder();
  for (const [path, contents] of pages) {
    signal?.throwIfAborted();
    await writeFile(drive, path, contents);
    checksums.push(bytesToHex(sha256(encode.encode(contents))) + "  " + path);
  }
  checksums.push(bytesToHex(sha256(encode.encode(start))) + "  START_HERE.html");
  await writeFile(drive, "LIBRARY/SHA256SUMS.txt", checksums.sort().join("\n") + "\n");
  await writeFile(drive, "START_HERE.html", start);
  return [...phoneWarnings, ...indexed.warnings];
}
