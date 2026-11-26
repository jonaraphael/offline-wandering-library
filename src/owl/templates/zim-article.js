/* Prepare an inert copy of an archived page for the reader's sandboxed iframe. */
(function (root) {
  "use strict";

  const policy = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src blob: data:; media-src blob:; font-src blob:; base-uri 'none'; form-action 'none'";
  const maxMarkup = 8 * 1024 * 1024;
  const maxResources = 96 * 1024 * 1024;
  const discarded = "script, iframe, frame, frameset, object, embed, meta, base, form, input, select, textarea, button, template, portal, fencedframe, applet, foreignObject, animate, set, animateMotion, animateTransform";
  const resourceType = /^(?:image|audio|video|font)\/|^application\/(?:font-|x-font-|vnd\.ms-fontobject|octet-stream)/i;
  const dataImage = /^data:image\/(?:png|gif|jpeg|webp|avif|svg\+xml);/i;
  const decode = value => {
    try { return decodeURIComponent(value); } catch (_) { return value; }
  };
  const quotePath = value => value.split("/").map(encodeURIComponent).join("/");
  const attr = value => value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");
  const text = value => attr(value).replaceAll(">", "&gt;");
  const normalize = value => value.normalize("NFKC").replace(/[\s_]+/g, " ").trim().toLowerCase();

  function locate(value, entry, legacy) {
    if (!value) return null;
    if (value.startsWith("#")) return {fragment: decode(value.slice(1))};
    try {
      const prefix = legacy ? entry.ns + "/" : "";
      const base = "zim://archive/" + prefix + quotePath(entry.path);
      const url = new URL(value, base);
      if (url.protocol !== "zim:" || url.host !== "archive") return null;
      let path = decode(url.pathname.slice(1));
      let ns = legacy ? entry.ns : "C";
      if (legacy && /^[AIJ-]\//.test(path)) {
        ns = path[0];
        path = path.slice(2);
      }
      return {path, ns, query: decode(url.search), fragment: decode(url.hash.slice(1))};
    } catch (_) {
      return null;
    }
  }

  async function replaceAll(source, pattern, render) {
    let output = "", start = 0;
    for (const match of source.matchAll(pattern)) {
      output += source.slice(start, match.index) + await render(match);
      start = match.index + match[0].length;
    }
    return output + source.slice(start);
  }

  const cssUnescape = value => value.replace(/\\([a-f0-9]{1,6})(?:\r\n|[ \t\r\n\f])?|\\([^\r\n\f])/gi,
    (_, hex, literal) => hex ? String.fromCodePoint(Math.min(parseInt(hex, 16), 0x10ffff)) : literal);
  const cssURL = /url\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|((?:\\.|[^)\\])*?))\s*\)/gi;

  // The article is printed on a light card, even when the library uses dark chrome.
  const paperMedia = value => value.replace(/\(\s*prefers-color-scheme\s*:\s*(dark|light)\s*\)/gi,
    (_, theme) => theme.toLowerCase() === "dark" ? "(max-width: 0px)" : "(min-width: 0px)");

  async function prepare(zim, entry, urls, signal) {
    if (!/^text\/html\b|^application\/xhtml\+xml\b/i.test(entry?.mime)) throw Error("Entry is not an article");
    const content = await zim.blob(entry);
    if (content.size > maxMarkup) throw Error("Article is too large");
    const html = await content.text();
    const template = document.createElement("template");
    template.innerHTML = html;
    const doc = template.content;
    const scripts = doc.querySelectorAll("script").length;
    const title = doc.querySelector("title")?.textContent.trim() || entry.title;
    // Template parsing keeps every archived resource inert, including the original head.
    for (const node of doc.querySelectorAll(discarded + ", title")) node.remove();
    for (const noscript of doc.querySelectorAll("noscript")) {
      const alternate = document.createElement("template");
      alternate.innerHTML = noscript.textContent;
      for (const node of alternate.content.querySelectorAll(discarded + ", noscript")) node.remove();
      noscript.replaceWith(alternate.content);
    }

    // A script-built shell can have a title and a short loading notice, but no
    // readable content. CSS illustrations count alongside embedded images.
    const readable = doc.cloneNode(true);
    for (const node of readable.querySelectorAll("style, svg, header, nav, footer")) node.remove();
    const textLength = readable.textContent.replace(/\s+/g, " ").trim().length;
    const illustrations = readable.querySelectorAll("img, picture, video, [style*='url(']").length;
    if (scripts && textLength < 120 && !illustrations) {
      throw Object.assign(Error("Archive requires scripts"), {code: "scripts", textLength, scripts, illustrations});
    }

    const resources = new Map(), links = new Map();
    let resourceBytes = 0, loaded = 0;
    async function find(target) {
      return (target.query && await zim.get(target.path + target.query, {ns: target.ns})) ||
        await zim.get(target.path, {ns: target.ns});
    }
    async function resource(value, from) {
      signal.throwIfAborted();
      if (dataImage.test(value)) return value.length <= maxMarkup ? value : "";
      const target = locate(value, from, zim.minor === 0);
      if (!target) return "";
      if (!target.path) return target.fragment ? "#" + target.fragment : "";
      const key = target.ns + "/" + target.path + (target.query || "");
      if (!resources.has(key)) {
        let url = "";
        try {
          const found = await find(target);
          if (resourceType.test(found?.mime || "")) {
            const blob = await zim.blob(found);
            if (resourceBytes + blob.size <= maxResources) {
              resourceBytes += blob.size;
              url = URL.createObjectURL(blob);
              urls.push(url);
              loaded++;
            }
          }
        } catch (_) { /* An unavailable illustration does not hide an article. */ }
        resources.set(key, url);
      }
      const url = resources.get(key);
      return url && url + (target.fragment ? "#" + encodeURIComponent(target.fragment) : "");
    }

    async function css(source, from, depth = 0) {
      signal.throwIfAborted();
      if (source.length > maxMarkup) return "";
      // CSS escapes in keywords must not conceal a URL token from rewriting.
      source = paperMedia(source).replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/(?:[-a-z]|\\[a-f0-9]{1,6}\s?|\\.)+\(/gi, token => cssUnescape(token));
      const imports = [];
      source = await replaceAll(source, /@import\s+(?:url\(\s*)?(?:"([^"]*)"|'([^']*)'|([^\s;)]+))\s*\)?\s*([^;{}]*);/gi,
        async ([, double, single, bare, media]) => {
          const target = locate(cssUnescape(double ?? single ?? bare), from, zim.minor === 0);
          if (depth < 4 && target?.path) {
            try {
              const sheet = await find(target);
              if (sheet?.mime === "text/css") {
                const content = await css(await (await zim.blob(sheet)).text(), sheet, depth + 1);
                imports.push(media ? "@media " + media + "{" + content + "}" : content);
              }
            } catch (_) { /* Ignore missing optional stylesheets. */ }
          }
          return "";
        });
      // Quoted image-set candidates can request URLs without using url().
      source = source.replace(/((?:-webkit-)?image-set\(\s*|,\s*)(["'])([^"'\n]+)\2(?=\s+(?:[\d.]+(?:x|dpi|dppx))\b)/gi,
        (_, prefix, quotes, value) => prefix + "url(" + quotes + value + quotes + ")");
      const body = await replaceAll(source, cssURL, async ([, double, single, bare]) => {
        const url = await resource(cssUnescape(double ?? single ?? bare), from);
        return url ? 'url("' + url.replace(/["\\\n\r\f]/g, char => "\\" + char.codePointAt(0).toString(16) + " ") + '")' : "none";
      });
      return [...imports, body.replace(/<\/style/gi, "\\3c /style")].join("\n");
    }

    async function srcset(value) {
      // URL tokens may contain commas (notably for data URLs). Descriptor tokens
      // and the final delimiter are separated from them by ASCII whitespace.
      const candidates = [];
      for (const match of value.matchAll(/(?:^|[\s,])([^\s]+?)(?:[\t\n\f\r ]+([\d.]+[wx]))?(?:\s*,\s*|\s*$)/g)) {
        const url = await resource(match[1], entry);
        if (url) candidates.push(url + (match[2] ? " " + match[2] : ""));
      }
      return candidates.join(", ");
    }

    const elements = [...doc.querySelectorAll("*")];
    for (const node of elements) {
      signal.throwIfAborted();
      if (!doc.contains(node)) continue;
      const tag = node.localName.toLowerCase();
      if (tag === "link") {
        const target = locate(node.getAttribute("href"), entry, zim.minor === 0);
        if (target?.path && node.relList?.contains("stylesheet")) {
          try {
            const found = await find(target);
            if (found?.mime === "text/css") {
              const style = document.createElement("style");
              if (node.media) style.media = paperMedia(node.media);
              style.textContent = await css(await (await zim.blob(found)).text(), found);
              node.replaceWith(style);
            }
          } catch (_) { /* Keep the article readable without an optional sheet. */ }
        }
        node.remove();
        continue;
      }
      if (tag === "style") {
        node.textContent = await css(node.textContent, entry);
        if (node.media) node.media = paperMedia(node.media);
      }
      const attributes = new Map([...node.attributes].map(attribute => [attribute.name.toLowerCase(), attribute.value]));
      for (const name of attributes.keys()) {
        if (/^on|^data-owl-/.test(name) || /^(?:src|href|xlink:href|srcset|imagesrcset|srcdoc|poster|background|ping|target|action|formaction|cite|longdesc|archive|codebase|data|code|profile|dynsrc|lowsrc|manifest|attributionsrc|is)$/.test(name)) {
          node.removeAttribute(name);
        } else if (name === "style" || /url\s*\(/i.test(attributes.get(name))) {
          node.setAttribute(name, await css(attributes.get(name), entry));
        }
      }
      if (["img", "source", "audio", "video", "track"].includes(tag)) {
        const url = await resource(attributes.get("src") || attributes.get("data-src") || "", entry);
        if (url && !url.startsWith("#")) node.setAttribute("src", url);
      }
      if (tag === "img" || tag === "source") {
        const set = await srcset(attributes.get("srcset") || attributes.get("data-srcset") || "");
        if (set) node.setAttribute("srcset", set);
        if (tag === "img") node.setAttribute("loading", "eager");
      }
      if (tag === "video") {
        const poster = await resource(attributes.get("poster") || "", entry);
        if (poster) node.setAttribute("poster", poster);
      }
      if (tag === "use" || tag === "image") {
        const value = attributes.get("href") || attributes.get("xlink:href") || "";
        const url = tag === "use" ? value.startsWith("#") && value : await resource(value, entry);
        if (url) node.setAttribute("href", url);
      }
      if (tag === "a" || tag === "area") {
        const target = locate(attributes.get("href") || attributes.get("xlink:href"), entry, zim.minor === 0);
        if (!target) continue;
        const key = String(links.size);
        links.set(key, target);
        node.setAttribute("data-owl-link", key);
        node.setAttribute("href", "#" + encodeURIComponent(target.fragment || ""));
      }
    }

    function wrapper(tag) {
      const match = html.match(new RegExp("<" + tag + "(?=[\\s>])(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>", "i"));
      if (!match) return "";
      const sample = document.createElement("template");
      sample.innerHTML = "<div" + match[0].slice(1 + tag.length);
      return ["class", "id", "lang", "dir"].map(name => {
        const value = sample.content.firstElementChild?.getAttribute(name);
        return value ? " " + name + '="' + attr(value) + '"' : "";
      }).join("");
    }
    const fallback = "html{color-scheme:light;background:#fff;color:#202122}body{margin:0;font:16px/1.55 system-ui,sans-serif}" +
      "img,video,canvas{max-width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}a:focus-visible{outline:2px solid #165da8}";
    const fit = "html{color-scheme:light!important;min-width:0!important;height:auto!important;overflow:hidden!important}body{height:auto!important;min-height:0!important;display:flow-root;overflow-wrap:break-word}";
    return {title, links, textLength, scripts, illustrations, loaded, html: "<!doctype html><html" + wrapper("html") +
      '><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + attr(policy) +
      '"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + text(title) +
      "</title><style>" + fallback + "</style></head><body" + wrapper("body") + ">" + template.innerHTML +
      "<style>" + fit + "</style></body></html>"};
  }

  function targetElement(doc, fragment, section) {
    const named = value => doc.getElementById(value) || doc.getElementsByName(value)[0];
    if (fragment) return named(fragment) || named(fragment.replaceAll(" ", "_"));
    if (!section) return null;
    return named(section) || named(section.replaceAll(" ", "_")) ||
      [...doc.querySelectorAll("h1, h2, h3, h4, h5, h6")].find(node => normalize(node.textContent) === normalize(section));
  }

  root.OWLZimArticle = {prepare, targetElement};
})(globalThis);
