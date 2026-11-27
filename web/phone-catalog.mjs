// Build the Preview document from final reader rows, after downloads and WikiMed volumes settle.
import {PDFDocument, PDFString, rgb} from "./vendor/pdf-lib/pdf-lib.mjs";
import fontkit from "./vendor/pdf-lib/fontkit.mjs";
import vera from "./vendor/pdf-lib/vera.mjs";

// A Files app link that opens the PDF in place on an iPhone; Preview asks once before leaving.
export function filesLink(spec, drive, path) {
  const encode = part => encodeURIComponent(part).replace(/[!'()*]/g, char => "%" + char.charCodeAt(0).toString(16).toUpperCase());
  return "shareddocuments://" + (spec.files_root + drive + "/" + path).split("/").map(encode).join("/") + "?open";
}

// A volume UUID, then any folders below the drive's top.
const phonePath = /^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?:\/(?!\.\.?(?:\/|$))[^/]+)*$/;

// The iPhone location a builder that could read the drive's volume UUID saved in BUILD_INFO.json, or null.
// A browser cannot read the UUID, so the saved path is kept while the picked folder keeps its name.
// A Windows drive root has no name to compare.
export function savedPhoneDrive(saved, folder) {
  if (!saved || typeof saved.path !== "string" || !phonePath.test(saved.path)) return null;
  return !folder || /^[A-Za-z]:[\\/]?$/.test(folder) || saved.folder === folder ? {path: saved.path, folder: saved.folder} : null;
}

// drive: the library root as an iPhone names it, the drive's volume UUID and any folders below its top.
export async function phoneCatalog(groups, spec, drive = null) {
  const pdf = await PDFDocument.create({updateMetadata: false});
  pdf.setTitle(spec.title);
  pdf.setAuthor("Offline Wandering Library");
  pdf.registerFontkit(fontkit);
  const font = await pdf.embedFont(vera, {subset: true, features: {liga: false}});
  const [width, height, margin] = spec.page;
  const usable = width - margin * 2;
  const color = key => rgb(...spec[key].slice(1).match(/../g).map(channel => parseInt(channel, 16) / 255));
  const contents = pdf.addPage([width, height]);
  let page = contents;
  function text(value, y, size, ink = "ink") {
    const natural = font.widthOfTextAtSize(value, size);
    page.drawText(value, {x: margin, y: height - y, font, color: color(ink),
      size: natural > usable ? size * usable / natural : size});
  }
  function lines(value, size) {
    const result = [];
    for (const word of value.split(/\s+/u).filter(Boolean)) {
      const joined = result.at(-1) + " " + word;
      if (result.length && font.widthOfTextAtSize(joined, size) <= usable) result[result.length - 1] = joined;
      else result.push(word);
    }
    return result;
  }
  function rule(y) {
    page.drawLine({start: {x: margin, y: height - y}, end: {x: width - margin, y: height - y},
      thickness: 1, color: color("line")});
  }
  function link(source, top, bottom, action) {
    const annotation = pdf.context.obj({Type: "Annot", Subtype: "Link", Border: [0, 0, 0],
      Rect: [margin, height - bottom, width - margin, height - top], A: action});
    source.node.addAnnot(pdf.context.register(annotation));
  }
  // Without the drive's volume UUID, the title opens Files at its last folder.
  const fileAction = path => ({S: "URI", URI: PDFString.of(drive ? filesLink(spec, drive, path) : spec.files_app)});
  const goTo = target => ({S: "GoTo", D: [target.ref, "Fit"]});
  text(spec.brand, 36, 11, "muted");
  text(spec.title, 78, 29);
  let y = 110;
  for (const paragraph of [...spec.intro, drive ? spec.open_book : spec.open_files]) {
    for (const line of lines(paragraph, 13)) {
      text(line, y, 13);
      y += 18;
    }
    y += 6;
  }
  // Record each contents hit area until its category page has been created.
  const buttons = groups.map(({name, rows}) => {
    rule(y);
    text(name + "  (" + rows.length + ")", y + 23, 16, "accent");
    y += 36;
    return y - 36;
  });
  if (!groups.length) text(spec.empty, y + 20, 14);
  function section(name) {
    page = pdf.addPage([width, height]);
    text(spec.contents, 33, 12, "accent");
    link(page, 12, 47, goTo(contents));
    text(name, 76, 23);
    return 100;
  }
  for (const [index, {name, rows}] of groups.entries()) {
    y = section(name);
    link(contents, buttons[index], buttons[index] + 36, goTo(page));
    for (const row of rows) {
      const title = lines(row.title, 16);
      const split = row.path.lastIndexOf("/");
      const folders = lines(row.path.slice(0, split).replaceAll("/", " › "), 11);
      const rowHeight = 20 * title.length + 14 * folders.length + 42;
      if (y + rowHeight > height - 32 && y > 100) y = section(name);
      const top = y;
      rule(y);
      y += 22;
      const isPdf = row.format === "pdf";
      for (const line of title) {
        text(line, y, 16, isPdf ? "accent" : "ink");
        y += 20;
      }
      if (isPdf) link(page, top, y - 10, fileAction(row.path));
      text(row.path.slice(split + 1), y, 13);
      y += 17;
      for (const line of folders) {
        text(line, y, 11, "muted");
        y += 14;
      }
      y += 3;
    }
  }
  for (const [index, sheet] of pdf.getPages().entries()) {
    page = sheet;
    text(String(index + 1), height - 16, 10, "muted");
  }
  return pdf.save();
}
