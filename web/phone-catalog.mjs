// Build the iPhone start page from final reader rows, after downloads and WikiMed volumes settle.
// The layout mirrors src/owl/phone_catalog.py line for line; a parity test compares the text of every page.
import {LineCapStyle, LineJoinStyle, PDFDocument, PDFHexString, PDFName, PDFString, rgb, setLineJoin} from "./vendor/pdf-lib/pdf-lib.mjs";
import fontkit from "./vendor/pdf-lib/fontkit.mjs";
import vera from "./vendor/pdf-lib/vera.mjs";
import veraBold from "./vendor/pdf-lib/vera-bold.mjs";

const encode = part => encodeURIComponent(part).replace(/[!'()*]/g, char => "%" + char.charCodeAt(0).toString(16).toUpperCase());

// A Files app link. Opened, it shows the PDF in place on an iPhone after one prompt; otherwise it shows a folder.
export function filesLink(spec, drive, path, opened = true) {
  return "shareddocuments://" + (spec.files_root + drive + "/" + path).split("/").map(encode).join("/") + (opened ? "?open" : "");
}

// A volume UUID, then any folders below the drive's top.
const phonePath = /^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?:\/(?!\.\.?(?:\/|$))[^/]+)*$/;

// The iPhone location a builder that could read the drive's volume UUID saved in LIBRARY/.owl/iphone-drive.json, or null.
// A browser cannot read the UUID, so the saved path is kept while the picked folder keeps its name.
// A Windows drive root has no name to compare.
export function savedPhoneDrive(saved, folder) {
  if (!saved || typeof saved.path !== "string" || !phonePath.test(saved.path)) return null;
  return !folder || /^[A-Za-z]:[\\/]?$/.test(folder) || saved.folder === folder ? {path: saved.path, folder: saved.folder} : null;
}

const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const byName = (a, b) => compare(a.toLowerCase(), b.toLowerCase()) || compare(a, b);
const number = value => String(value).replace(/\B(?=(\d{3})+$)/g, ",");
function size(value) {
  for (const [unit, name] of [[10 ** 9, "GB"], [10 ** 6, "MB"], [10 ** 3, "KB"]]) {
    if (value < unit) continue;
    const tenths = Math.floor((value * 10 + unit / 2) / unit);
    return (tenths >= 100 ? String(Math.floor((value + unit / 2) / unit)) : Math.floor(tenths / 10) + "." + tenths % 10) + " " + name;
  }
  return "";
}

// sections: categories with their rows. tasks: urgent tasks with every guide present. articles: WikiMed titles.
// drive: the library root as an iPhone names it, the drive's volume UUID and any folders below its top.
export async function phoneCatalog(sections, spec, drive = null, tasks = [], articles = []) {
  const pdf = await PDFDocument.create({updateMetadata: false});
  pdf.setTitle(spec.brand);
  pdf.setAuthor("Offline Wandering Library");
  pdf.registerFontkit(fontkit);
  const regular = await pdf.embedFont(vera, {subset: true, features: {liga: false}});
  const strong = await pdf.embedFont(veraBold, {subset: true, features: {liga: false}});
  const [width, height, margin] = spec.page;
  const usable = width - margin * 2;
  const color = key => rgb(...(spec[key] ?? key).slice(1).match(/../g).map(channel => parseInt(channel, 16) / 255));
  const marks = new Map(), jumps = [], outline = [];
  let page, pageNumber = 0, y = 0;
  function newPage() {
    page = pdf.addPage([width, height]);
    page.pushOperators(setLineJoin(LineJoinStyle.Round));
    pageNumber++;
  }
  const measure = (value, size, bold = false) => (bold ? strong : regular).widthOfTextAtSize(value, size);
  function text(value, x, top, size, ink = "ink", bold = false, fit = 0) {
    if (!value) return;
    // A long name shrinks instead of wrapping, so it stays one selectable run.
    const measured = measure(value, size, bold);
    page.drawText(value, {x, y: height - top, font: bold ? strong : regular, color: color(ink),
      size: fit && measured > fit ? size * fit / measured : size});
  }
  function clip(value, size, limit, bold = false, more = false) {
    if (!more && measure(value, size, bold) <= limit) return value;
    while (value && measure(value + "…", size, bold) > limit) value = value.slice(0, -1);
    return value.trimEnd() + "…";
  }
  function wrap(value, size, limit, bold = false, most = 0) {
    let result = [];
    for (const word of value.split(/\s+/u).filter(Boolean)) {
      const joined = result.at(-1) + " " + word;
      if (result.length && measure(joined, size, bold) <= limit) result[result.length - 1] = joined;
      else result.push(word);
    }
    if (most && result.length > most) result = [...result.slice(0, most - 1), clip(result[most - 1], size, limit, bold, true)];
    return result;
  }
  function box(x, top, wide, high, ink, radius = 0) {
    const r = radius, arc = "A" + r + " " + r + " 0 0 1 ";
    page.drawSvgPath("M" + r + " 0H" + (wide - r) + arc + wide + " " + r + "V" + (high - r) + arc + (wide - r) + " " + high +
      "H" + r + arc + "0 " + (high - r) + "V" + r + arc + r + " 0Z", {x, y: height - top, color: color(ink), borderWidth: 0});
  }
  function rule(top) {
    page.drawLine({start: {x: margin, y: height - top}, end: {x: width - margin, y: height - top},
      thickness: 1, color: color("line")});
  }
  function icon(d, x, top, size, ink, stroke = 2) {
    page.drawSvgPath(d, {x, y: height - top, scale: size / 24, borderColor: color(ink), borderWidth: stroke,
      borderLineCap: LineCapStyle.Round});
  }
  function annotate(x, top, wide, high, action) {
    const annotation = pdf.context.obj({Type: "Annot", Subtype: "Link", Border: [0, 0, 0],
      Rect: [x, height - top - high, x + wide, height - top], ...action});
    page.node.addAnnot(pdf.context.register(annotation));
    return annotation;
  }
  // A jump may point at a page that does not exist yet; its destination is filled in at the end.
  const jump = (name, x, top, wide, high) => jumps.push([annotate(x, top, wide, high, {}), name]);
  const leave = (url, x, top, wide, high) => annotate(x, top, wide, high, {A: {S: "URI", URI: PDFString.of(url)}});
  function mark(name, title) {
    marks.set(name, page.ref);
    if (title) outline.push([title, page.ref]);
  }
  const filled = (template, value) => template.replace("{count}", value).replace("{name}", value).replace("{names}", value);
  // Where a title leads: the PDF itself, the folder of any other file, or Files when the drive is unknown.
  function target(path, kind) {
    if (!drive) return spec.files_app;
    return kind === "pdf" ? filesLink(spec, drive, path) : filesLink(spec, drive, path.slice(0, path.lastIndexOf("/")), false);
  }
  function footer() {
    text(String(pageNumber), margin, height - 12, 9, "muted");
    newPage();
  }

  // The section being written, redrawn at the top of each page it continues onto.
  const section = {};
  function start(title, back, blurb = "", badge) {
    Object.assign(section, {title, back: back || ["home", spec.home], first: true});
    return heading(blurb, badge);
  }
  function heading(blurb = "", badge) {
    const [name, label] = section.back;
    text(label, margin, 30, 12.5, "accent", false, usable * 0.6);
    jump(name, 0, 4, width * 0.7, 40);
    if (!section.first) {
      const title = clip(section.title, 10.5, usable * 0.5);
      text(title, width - margin - measure(title, 10.5), 30, 10.5, "muted");
      return 50;
    }
    section.first = false;
    let indent = 0;
    if (badge) {
      box(margin, 50, 40, 40, badge[0], 11);
      if (badge[1]) icon(badge[1], margin + 9, 59, 22, "white");
      indent = 52;
    }
    let top = 50;
    for (const line of wrap(section.title, 21, usable - indent, true, 3)) {
      top += 25;
      text(line, margin + indent, top - 4, 21, "ink", true);
    }
    for (const line of wrap(blurb, 11, usable - indent, false, 3)) {
      top += 14;
      text(line, margin + indent, top, 11, "muted");
    }
    return Math.max(top, badge ? 90 : 0) + 16;
  }
  function need(high) {
    if (y + high > height - 28) {
      footer();
      y = heading();
    }
  }
  // A file's folder and name; a multi-part book's path is its folder.
  function parts(path) {
    if (path.endsWith("/")) return [path.slice(0, -1), ""];
    const split = path.lastIndexOf("/");
    return [path.slice(0, Math.max(split, 0)), path.slice(split + 1)];
  }
  // Where the file is. Loud, the filename stands alone above its folders, because following them is the only way
  // to the file; otherwise one quiet line serves when a link fails.
  function trailLines(path, limit, loud) {
    const [folder, name] = parts(path);
    const folders = folder.replaceAll("/", " › ");
    if (loud || !name) return [name ? [name] : [], wrap(folders, 9.5, limit)];
    return [[], wrap(folders + " › " + name, 9.5, limit)];
  }
  function trail(path, x, top, limit, loud) {
    const [names, folders] = trailLines(path, limit, loud);
    for (const name of names) {
      text(name, x, top, 11.5, "ink", false, limit);
      top += 15;
    }
    for (const line of folders) {
      text(line, x, top, 9.5, "muted");
      top += 12.5;
    }
    return top;
  }
  function trailHeight(path, limit, loud) {
    const [names, folders] = trailLines(path, limit, loud);
    return 15 * names.length + 12.5 * folders.length;
  }

  const loud = !drive;
  // A drive without a single urgent guide shows no urgent block, rather than eight empty tiles.
  if (!tasks.some(task => task.guides.length)) tasks = [];
  const count = sections.reduce((sum, group) => sum + group.rows.length, 0);
  const topics = new Map();
  for (const group of sections) {
    for (const row of group.rows) {
      for (const topic of row.topics || []) topics.set(topic, [...(topics.get(topic) || []), row]);
    }
  }
  const topicNames = [...topics.keys()].sort(byName);
  const seen = new Set();
  articles = articles.filter(row => !seen.has(row.title) && seen.add(row.title)).sort((a, b) => byName(a.title, b.title));
  const volumes = new Map(articles.map(row => [row.title, row]));
  const books = sections.flatMap(group => group.rows.filter(row => row.chapters?.length));
  const bookNames = new Map(books.map((row, index) => [row, "book-" + index]));
  const hasZim = sections.some(group => group.rows.some(row => row.format === "zim"));
  function openRow(row, x, top, wide, high) {
    if (row.chapters?.length) jump(bookNames.get(row), x, top, wide, high);
    else leave(target(row.path, row.format), x, top, wide, high);
  }

  // Home: search, the urgent tasks and the ways into the library, on one screen.
  newPage();
  mark("home", spec.title);
  text(spec.brand.toUpperCase(), margin, 30, 9.5, "muted", true);
  text(spec.title, margin, 62, 26, "ink", true);
  box(margin, 78, usable, 58, "field", 14);
  box(margin + 11, 89, 36, 36, "white", 18);
  icon(spec.search_icon, margin + 19, 97, 20, "accent", 2.4);
  text(spec.search[0], margin + 58, 101, 14, "ink", true);
  for (const [index, line] of wrap(spec.search[1], 10.5, usable - 70, false, 2).entries()) {
    text(line, margin + 58, 116 + 13 * index, 10.5, "muted");
  }
  jump("help", margin, 78, usable, 58);
  y = 160;
  if (tasks.length) {
    text(spec.urgent.toUpperCase(), margin, y, 10, "urgent_color", true);
    y += 10;
    const tile = (usable - 10) / 2, tall = 52;
    for (const [index, task] of tasks.entries()) {
      const x = margin + (index % 2) * (tile + 10), top = y + Math.floor(index / 2) * (tall + 8);
      const guide = task.guides[0];
      box(x, top, tile, tall, guide ? "urgent_color" : "field", 10);
      const ink = guide ? "white" : "muted";
      const lines = wrap(task.task, 12.5, tile - 20, true, 2);
      const detail = guide ? guide.short + (guide.page ? " · " + filled(spec.page_number, guide.page) : "") : spec.no_guide;
      let first = top + (lines.length === 1 ? 21 : 16);
      for (const line of lines) {
        text(line, x + 10, first, 12.5, ink, true);
        first += 14;
      }
      text(clip(detail, 9.5, tile - 20), x + 10, top + tall - (lines.length === 1 ? 11 : 7), 9.5, ink);
      if (guide && drive) leave(target(guide.path, guide.format), x, top, tile, tall);
      else if (guide) jump("task-" + index, x, top, tile, tall);
    }
    y += Math.floor((tasks.length + 1) / 2) * (tall + 8);
  }
  text(spec.library.toUpperCase(), margin, y + 18, 10, "muted", true);
  y += 26;
  const doors = sections.length ? [["browse", spec.browse, count]] : [];
  if (topicNames.length) doors.push(["topics", spec.topics, topicNames.length]);
  if (articles.length) doors.push(["articles", spec.articles, articles.length]);
  doors.push(["help", spec.help, 0]);
  if (!sections.length) {
    text(spec.empty, margin, y + 18, 12.5);
    y += 30;
  }
  for (const [name, [title, detail], amount] of doors) {
    rule(y);
    text(title, margin, y + 19, 13.5, "ink", true);
    text(filled(detail, number(amount)), margin, y + 34, 10.5, "muted");
    text("›", width - margin - 10, y + 28, 20, "muted");
    jump(name, margin, y, usable, 44);
    y += 44;
  }
  rule(y);
  for (const line of wrap(loud ? spec.hint_files : spec.hint_book, 10, usable)) {
    y += 15;
    text(line, margin, y + 4, 10, "muted");
  }
  footer();

  // Browse: one row for each subject.
  if (sections.length) {
    mark("browse", spec.browse[0]);
    y = start(spec.browse[0]);
    for (const group of sections) {
      need(54);
      rule(y);
      box(margin, y + 9, 36, 36, group.color, 10);
      if (group.icon) icon(group.icon, margin + 7, y + 16, 22, "white");
      text(group.name, margin + 48, y + 24, 14, "ink", true);
      const detail = number(group.rows.length) + " " + group.unit + (group.rows.length === 1 ? "" : "s");
      text(clip(detail + " · " + group.blurb, 10.5, usable - 70), margin + 48, y + 39, 10.5, "muted");
      text("›", width - margin - 10, y + 33, 20, "muted");
      jump("cat-" + group.id, margin, y, usable, 54);
      y += 54;
    }
    rule(y);
    footer();
  }

  // Urgent help: every guide for each task, with the words a person might search for.
  if (tasks.length) {
    mark("urgent", spec.urgent_title);
    y = start(spec.urgent_title, null, spec.urgent_blurb);
    for (const [index, task] of tasks.entries()) {
      const words = wrap(spec.search_words + task.keywords.join(", "), 9.5, usable, false, 2);
      need(40 + 12.5 * words.length + 60);
      mark("task-" + index);
      rule(y);
      text(task.task, margin, y + 22, 15, "ink", true);
      y += 26;
      for (const line of words) {
        y += 12.5;
        text(line, margin, y, 9.5, "muted");
      }
      y += 6;
      if (!task.guides.length) {
        text(spec.no_guide + ".", margin, y + 14, 11.5, "muted");
        y += 20;
      }
      for (const guide of task.guides) {
        const title = wrap(guide.title, 13, usable, false, 2);
        let detail = [guide.page ? filled(spec.go_to_page, guide.page) : "", guide.hint].filter(Boolean).join(" · ");
        if (guide.format === "zim") detail = guide.articles.length ? filled(spec.zim_lookup, guide.articles.join(" / ")) : spec.zim;
        need(17 * title.length + (detail ? 14 : 0) + trailHeight(guide.path, usable, loud) + 12);
        const top = y;
        for (const line of title) {
          y += 17;
          text(line, margin, y, 13, "accent");
        }
        if (detail) {
          y += 14;
          text(clip(detail, 10.5, usable), margin, y, 10.5, "ink");
        }
        leave(target(guide.path, guide.format), margin, top, usable, y - top + 5);
        y = trail(guide.path, margin, y + 13.5, usable, loud) - 2;
      }
      for (const name of new Set(task.lookups)) {
        const volume = volumes.get(name);
        if (!volume) continue;
        need(46);
        const top = y;
        text("WikiMed: " + name, margin, y + 17, 13, "accent", false, usable);
        text(clip(filled(spec.volume, volume.volume), 10.5, usable), margin, y + 31, 10.5, "ink");
        leave(target(volume.path, "pdf"), margin, top, usable, 36);
        y += 40;
      }
      y += 8;
    }
    footer();
  }

  // Topics: finer than the subjects, each leading straight to its books.
  if (topicNames.length) {
    mark("topics", spec.topics[0]);
    y = start(spec.topics[0]);
    for (const name of topicNames) {
      const rows = topics.get(name), shown = rows.slice(0, 6);
      need(32 + 22 * shown.length + (rows.length > shown.length ? 15 : 0));
      rule(y);
      text(name, margin, y + 20, 13.5, "ink", true, usable);
      y += 26;
      for (const row of shown) {
        text(clip(row.title, 12.5, usable - 8), margin + 8, y + 15, 12.5, "accent");
        openRow(row, margin, y, usable, 22);
        y += 22;
      }
      if (rows.length > shown.length) {
        text(filled(spec.more, rows.length - shown.length), margin + 8, y + 11, 10.5, "muted");
        y += 15;
      }
      y += 6;
    }
    footer();
  }

  // Subjects: each book with what it covers, then the chapter lists of its multi-part books.
  for (const group of sections) {
    mark("cat-" + group.id, group.name);
    y = start(group.name, null, group.blurb, [group.color, group.icon]);
    for (const row of group.rows) {
      const chapters = row.chapters?.length;
      const title = wrap(row.title, 15, usable - (chapters ? 18 : 0), true, 3);
      const detail = clip([row.kind, size(row.bytes), row.publisher].filter(Boolean).join(" · "), 10.5, usable);
      const summary = wrap(row.summary || "", 11.5, usable, false, 3);
      const labels = row.labels?.length ? wrap(spec.covers + row.labels.join(" · "), 10.5, usable, false, 2) : [];
      if (row.terms?.length) labels.push(...wrap(spec.inside + row.terms.join(" · "), 10.5, usable, false, 2));
      const note = row.format === "zim" ? [spec.zim] : [];
      need(20 + 19 * title.length + 15 + 15 * (summary.length + note.length) + 13.5 * labels.length +
        trailHeight(row.path, usable, loud) + 12);
      if (chapters) mark("row-" + bookNames.get(row));
      rule(y);
      const top = y;
      y += 4;
      for (const line of title) {
        y += 19;
        text(line, margin, y, 15, "accent", true);
      }
      if (chapters) text("›", width - margin - 10, top + 25, 20, "muted");
      y += 15;
      text(detail, margin, y, 10.5, "muted");
      openRow(row, margin, top, usable, y - top + 5);
      for (const line of [...summary, ...note]) {
        y += 15;
        text(line, margin, y, 11.5);
      }
      for (const line of labels) {
        y += 13.5;
        text(line, margin, y, 10.5, "muted");
      }
      y = trail(row.path, margin, y + 15, usable, loud) - 3;
    }
    footer();
    for (const row of group.rows) {
      if (!row.chapters?.length) continue;
      const name = bookNames.get(row);
      mark(name);
      y = start(row.title, ["row-" + name, filled(spec.back, group.name)], [row.kind, row.publisher].filter(Boolean).join(" · "));
      y = trail(row.path, margin, y - 2, usable, false) + 4;
      for (const chapter of row.chapters) {
        const title = wrap(chapter.title, 13.5, usable, false, 3);
        const inside = chapter.terms?.length ? wrap(chapter.terms.join(" · "), 9.5, usable, false, 2) : [];
        const high = 9 + 17 * title.length + 12.5 * inside.length + (loud ? 14 : 0) + 7;
        need(high);
        rule(y);
        const top = y;
        y += 6;
        for (const line of title) {
          y += 17;
          text(line, margin, y, 13.5, "accent");
        }
        for (const line of inside) {
          y += 12.5;
          text(line, margin, y, 9.5, "muted");
        }
        if (loud) {
          y += 14;
          text(chapter.path.slice(chapter.path.lastIndexOf("/") + 1), margin, y, 10.5, "ink", false, usable);
        }
        leave(target(chapter.path, chapter.format), margin, top, usable, high);
        y += 10;
      }
      footer();
    }
  }

  // Medical articles: every WikiMed title, so a search for a condition lands on the volume that holds it.
  if (articles.length) {
    mark("articles", spec.articles[0]);
    y = start(spec.articles[0], null, spec.articles_blurb);
    const letters = [...new Set(articles.map(row => row.title.slice(0, 1).toUpperCase()))];
    const cell = usable / 13;
    for (const [index, letter] of letters.entries()) {
      const x = margin + (index % 13) * cell, top = y + Math.floor(index / 13) * 30;
      text(letter, x + (cell - measure(letter, 14, true)) / 2, top + 20, 14, "accent", true);
      jump("letter-" + letter, x, top, cell, 30);
    }
    y += Math.floor((letters.length + 12) / 13) * 30 + 8;
    let current = "";
    for (const row of articles) {
      const letter = row.title.slice(0, 1).toUpperCase();
      if (letter !== current) {
        current = letter;
        need(34 + 20);
        mark("letter-" + letter);
        rule(y);
        text(letter, margin, y + 22, 15, "ink", true);
        y += 30;
      }
      need(20);
      text(clip(row.title, 12, usable * 0.62), margin, y + 13, 12, "accent");
      const volume = clip(row.volume, 9.5, usable * 0.36);
      text(volume, width - margin - measure(volume, 9.5), y + 13, 9.5, "muted");
      leave(target(row.path, "pdf"), margin, y, usable, 20);
      y += 20;
    }
    footer();
  }

  // Help: the things a reader needs to know, in order.
  mark("help", spec.help[0]);
  y = start(spec.help[0]);
  const steps = [spec.steps[0], loud ? spec.open_files : spec.open_book, ...spec.steps.slice(1), ...(hasZim ? [spec.kiwix] : [])];
  for (const [index, [lead, body]] of steps.entries()) {
    const lines = wrap(body, 12, usable - 34);
    need(34 + 16 * lines.length);
    rule(y);
    box(margin, y + 12, 22, 22, "field", 11);
    const digit = String(index + 1);
    text(digit, margin + 11 - measure(digit, 11, true) / 2, y + 27, 11, "ink", true);
    text(lead, margin + 34, y + 27, 13.5, "ink", true);
    y += 32;
    for (const line of lines) {
      y += 16;
      text(line, margin + 34, y, 12);
    }
    y += 12;
  }
  text(String(pageNumber), margin, height - 12, 9, "muted");

  for (const [annotation, name] of jumps) annotation.set(PDFName.of("Dest"), pdf.context.obj([marks.get(name), "Fit"]));
  const root = pdf.context.nextRef(), entries = outline.map(() => pdf.context.nextRef());
  for (const [index, [title, ref]] of outline.entries()) {
    pdf.context.assign(entries[index], pdf.context.obj({Title: PDFHexString.fromText(title), Parent: root, Dest: [ref, "Fit"],
      ...(index && {Prev: entries[index - 1]}), ...(index < outline.length - 1 && {Next: entries[index + 1]})}));
  }
  pdf.context.assign(root, pdf.context.obj({Type: "Outlines", First: entries[0], Last: entries.at(-1), Count: outline.length}));
  pdf.catalog.set(PDFName.of("Outlines"), root);
  return pdf.save();
}
