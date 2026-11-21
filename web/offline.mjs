import {sha256} from "./vendor/noble-hashes/sha2.js";
import {bytesToHex} from "./vendor/noble-hashes/utils.js";
import {writeFile} from "./drive.mjs";

const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);
const href = path => path.split("/").map(encodeURIComponent).join("/");
const link = (path, text) => '<a href="' + href(path) + '">' + escape(text) + "</a>";
const titleOrder = (a, b) => a.title.localeCompare(b.title, "en");

function document(title, css, body) {
  return '<!doctype html><html lang="en"><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">' +
    "<title>" + escape(title) + "</title><style>" + css + "</style><main><h1>" + escape(title) + "</h1>" + body + "</main></html>\n";
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

export async function assembleLibrary(drive, {completed, missing, navigation, layouts, parts, signal, writeSearch}) {
  const {css = "", groups = [], assets: metadata = {}, topics = {}, entrances = {}, assignments = [], verify = ""} = navigation;
  const documents = completed.filter(asset => metadata[asset.id]?.document !== false).sort(titleOrder);
  const inventory = completed.map(asset => ({
    id: asset.id, title: asset.title, license: asset.license, attribution: metadata[asset.id]?.attribution,
    publisher: metadata[asset.id]?.publisher, bytes: asset.size_bytes, sha256: asset.sha256,
    parts: layouts.get(asset.id).map((part, index) => ({path: part.path, bytes: part.bytes, sha256: parts[asset.id][index].sha256}))
  }));
  const index = "LIBRARY/INDEX/";
  const pages = new Map();
  const shelfLinks = [];
  const shelves = [
    ["critical", "Critical references", documents.filter(asset => asset.critical)],
    ["textbooks", "Textbooks", documents.filter(asset => metadata[asset.id]?.shelves.includes("textbooks"))],
    ["illustrated-guides", "Illustrated guides", documents.filter(asset => metadata[asset.id]?.shelves.includes("illustrated-guides"))],
    ...groups.map(([id, title]) => [id, title, documents.filter(asset => metadata[asset.id]?.group === id)])
  ];
  for (const [id, title, assets] of shelves) {
    const path = index + "shelf-" + id + ".html";
    if (assets.length) shelfLinks.push("<li>" + link(path, title + " (" + assets.length + ")") + "</li>");
    pages.set(path, document(title, css, "<nav>" + link("../../START_HERE.html", "Start here") +
      "</nav>" + assetList(assets, layouts, "../../")));
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
  pages.set(index + "topics.html", document("Topic atlas", css,
    "<nav>" + link("../../START_HERE.html", "Start here") + "</nav>" + topicGroups.join("")));
  for (const [id, topic] of Object.entries(topics)) {
    const children = Object.values(topics).filter(child => child.parents.includes(id) && visible(child.id)).sort(titleOrder);
    const list = children.map(child => "<li>" + link(child.id + ".html", child.title) + "</li>").join("");
    pages.set(index + "topics/" + id + ".html", document(topic.title, css, "<nav>" +
      link("../../../START_HERE.html", "Start here") + " " + link("../topics.html", "Topic atlas") + "</nav><p>" +
      escape(topic.description) + "</p>" + (list ? "<h2>Subtopics</h2><ul>" + list + "</ul>" : "") +
      assetList([...topicAssets.get(id).values()].sort(titleOrder), layouts, "../../../")));
  }

  const omitted = missing.length ? '<section class="notice"><h2>Files missing from this build</h2><ul>' + missing.map(row =>
    "<li>" + escape(row.title) + " — " + escape(row.reason) + "</li>").join("") + "</ul></section>" : "";
  pages.set("LIBRARY/INVENTORY.json", JSON.stringify({files: inventory, missing}, null, 2) + "\n");
  if (verify) pages.set("LIBRARY/VERIFY.py", verify);
  pages.set("LIBRARY/SOURCE_NOTES.txt", inventory.map(file => [
    file.title, file.license, file.attribution, ...file.parts.map(part => part.path)
  ].filter(Boolean).join("\n")).join("\n\n") + "\n");

  // Future precomputed per-resource search files can join the same verified output.
  const searchFiles = writeSearch ? await writeSearch(completed) : [];
  for (const [path, contents] of searchFiles) pages.set(path, contents);
  const start = document("Offline Wandering Library", css,
    '<nav>' + link(index + "topics.html", "Topic atlas") + ' <a href="#shelves">Shelves</a> <a href="#files">All files</a></nav>' +
    '<p class="notice">On a phone, open this page in Files. If a link does not open, find the printed path on this drive. ' +
    'Install Kiwix on your phone while you have internet. For a split archive, keep all parts in one folder.</p>' +
    omitted + '<h2 id="shelves">Shelves</h2><ul class="cards">' + shelfLinks.join("") + '</ul>' +
    '<h2 id="files">All files (' + documents.length + ")</h2>" + assetList(documents, layouts, ""));

  const checksums = inventory.flatMap(file => file.parts.map(part => part.sha256 + "  " + part.path));
  const encode = new TextEncoder();
  for (const [path, contents] of pages) {
    signal?.throwIfAborted();
    await writeFile(drive, path, contents);
    checksums.push(bytesToHex(sha256(encode.encode(contents))) + "  " + path);
  }
  checksums.push(bytesToHex(sha256(encode.encode(start))) + "  START_HERE.html");
  await writeFile(drive, "LIBRARY/SHA256SUMS.txt", checksums.sort().join("\n") + "\n");
  await writeFile(drive, "START_HERE.html", start);
}
