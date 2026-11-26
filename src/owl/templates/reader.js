/* The reader shell starts only after its local Home data loads. */
(function (root) {
  "use strict";

  const engine = root.OWLDiscovery;
  const view = document.querySelector("#reader-view");
  const tabs = document.querySelector(".tabs");
  const sheet = document.querySelector(".sheet");
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
  const icon = name => '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><use href="#i-' + name + '"/></svg>';
  const count = (value, unit = "item") => value.toLocaleString() + " " + unit + (value === 1 ? "" : "s");
  const size = bytes => {
    const [scale, unit] = bytes >= 1e9 ? [1e9, "GB"] : bytes >= 1e6 ? [1e6, "MB"] :
      bytes >= 1e3 ? [1e3, "kB"] : [1, "B"];
    return (bytes / scale).toLocaleString(undefined, {maximumFractionDigits: bytes / scale < 100 ? 1 : 0}) + " " + unit;
  };
  function details(row) {
    const kind = row.format === "zim" ? kiwixLabel(row) || archiveKind(row) : row.kind;
    return [row.source, kind, row.bytes ? size(row.bytes) : ""].filter(Boolean).join(" · ");
  }
  const allTitle = "Everything, A to Z";
  const loaded = new Map(), pending = new Map();
  const positions = new Map(), filters = new Map();
  let home, device, helpPhone, activeRoute, pageEpoch = 0;
  let storage, libraryId, saved = [], recent = [];
  let links = new Map(), linkNumber = 0;
  let searchMarkup, searchCount, refreshSearch;
  let moveFocus = false;
  const picker = document.createElement("input");
  picker.id = "zim-folder";
  picker.type = "file";
  picker.setAttribute("webkitdirectory", "");
  picker.hidden = true;
  const readOnly = {mode: "read"};
  const clickProbe = 250;
  const chromiumPicker = typeof root.showDirectoryPicker === "function";
  const firefox = /Firefox\//.test(navigator.userAgent);
  const chromium = /(?:Chrome|Chromium)\//.test(navigator.userAgent);
  const webkit = /AppleWebKit\//.test(navigator.userAgent) && !chromium;
  let drive, archives = new Map(), folderStore, folderHandle, source;
  let useFolderInput = !chromiumPicker;
  let pickerResult, driveAccess, cachedZim, article, returnFocus;
  const scriptArchives = new Set();
  const needsKiwix = row => row.format === "zim" && (archives.get(row.id)?.kiwixKind || scriptArchives.has(row.id));
  const archiveKind = row => archives.get(row.id)?.kiwixKind || row.kind?.split(",")[0] || "Encyclopedia";
  const kiwixLabel = row => row && needsKiwix(row) ? archiveKind(row) + " · Opens in the Kiwix app" : "";
  const archiveName = row => row.title.split(/: | — | \(/, 1)[0];
  const generation = engine.local("home.js").replace(/\/home\.js$/, "");
  const archiveRoute = (row, path, fragment, title, section) =>
    drive?.readRoute(row.id, path, fragment, title, section) || "#/read/" + encodeURIComponent(row.id) + "/@main";
  const taskRoute = row => archiveRoute(row, row.articlePaths?.[0], "", row.articles?.[0]);

  root.OWLReaderData = (id, value) => loaded.set(id, value);
  function data(id) {
    if (loaded.has(id)) return Promise.resolve(loaded.get(id));
    if (!pending.has(id)) {
      const name = id === "home" ? "home" : "c-" + id;
      pending.set(id, engine.script(engine.local(name + ".js")).then(() => {
        if (!loaded.has(id)) throw Error("Could not read the list from this drive.");
        return loaded.get(id);
      }).finally(() => pending.delete(id)));
    }
    return pending.get(id);
  }

  function storedRows(values) {
    if (!Array.isArray(values)) return [];
    return values.filter(row => row && typeof row.id === "string" && typeof row.title === "string" &&
      (row.href?.startsWith("LIBRARY/") && engine.safeHref(row.href) ||
       row.route?.startsWith("#/c/") && typeof row.route === "string"));
  }
  function openStorage() {
    try {
      storage = localStorage;
      // The entry file's URL identifies this library within the current browser.
      libraryId = "owl.reader.v1:" + new URL(location.pathname, location.href).href;
      const probe = libraryId + ".probe";
      storage.setItem(probe, "1");
      storage.removeItem(probe);
      const record = JSON.parse(storage.getItem(libraryId) || "{}");
      saved = storedRows(record.saved);
      recent = storedRows(record.recent);
    } catch (_) {
      storage = undefined;
    }
  }

  function persist() {
    try {
      storage?.setItem(libraryId, JSON.stringify({saved, recent}));
    } catch (_) {
      storage = undefined;
      saved = [];
      recent = [];
      renderTabs();
      if (activeRoute === "#/saved") navigate("#/");
      else for (const star of view.querySelectorAll(".star")) star.remove();
    }
  }

  function attachment(row, label) {
    const key = String(++linkNumber);
    links.set(key, row);
    const archive = row.format === "zim";
    const destination = archive ? row.route || taskRoute(row) : row.route || row.href;
    return '<a href="' + escape(destination) + '" data-open="' + key + '">' + label + "</a>";
  }
  function button(id, row) {
    return '<button type="button" class="star" data-star="' + id + '" aria-label="' +
      escape("Save " + row.title) + '" aria-pressed="' + saved.some(item => item.id === row.id) + '">' + icon("star") + "</button>";
  }

  function list(rows, {go = false, stars = true} = {}) {
    return '<div class="list">' + rows.map(row => {
      const description = needsKiwix(row) ? details(row) : row.summary || details(row);
      const label = "<b>" + escape(row.title) + "</b>" + (description ? "<small>" + escape(description) + "</small>" : "");
      const archive = row.format === "zim";
      return '<div class="row' + (go ? " go" : "") + (archive ? " archive-row" : "") + '">' + attachment(row, label) +
        (storage && stars ? button(String(linkNumber), row) : "") + "</div>";
    }).join("") + "</div>";
  }

  const heading = (title, subtitle = "") => "<h1>" + escape(title) + "</h1>" +
    (subtitle ? '<p class="sub">' + escape(subtitle) + "</p>" : "");
  const back = (href, name) => '<a class="back" href="' + href + '">‹ ' + escape(name) + "</a>";
  const label = (title, kind = "") => '<h2 class="label' + (kind ? " " + kind : "") + '">' + escape(title) + "</h2>";

  function homeView() {
    const urgent = home.tasks.map(task => task.path
      ? task.format === "zim" ? '<span class="urgent-archive">' + escape(task.task) + attachment(task, "Open") + "</span>"
        : attachment(task, escape(task.task))
      : "").join("");
    const unavailable = home.tasks.filter(task => !task.path).map(task => task.task);
    const recentRows = storage ? recent.slice(0, 3) : [];
    const tiles = home.categories.filter(cat => cat.count && cat.id !== "other").map(cat =>
      '<a class="tile" href="#/c/' + cat.id + '" style="--c:var(--c-' + cat.id + ')">' +
      '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><path d="' + escape(cat.icon) + '"/></svg>' +
      escape(cat.name) + "<small>" + count(cat.count, cat.unit) + "</small></a>").join("");
    return heading("Library", "Works without internet") +
      '<a class="search" id="home-search" href="#/search">' + icon("search") + "Search " +
      searchCount + "</a>" +
      label("Urgent", "urgent") + (urgent ? '<div class="chips">' + urgent + "</div>" : "") +
      (unavailable.length ? "<p class=\"note\">No guide on this drive for " + escape(unavailable.join(", ")) + ".</p>" : "") +
      (recentRows.length ? label("Recently opened") + list(recentRows, {go: true, stars: false}) : "") +
      (tiles ? label("Everything on this drive") + '<div class="tiles">' + tiles + "</div>" : "") +
      '<div class="all-items">' + list([{id: "all", title: allTitle, route: "#/all"}], {go: true, stars: false}) + "</div>";
  }

  function bookRoutes(rows, category) {
    return rows.map(row => row.chapters ? {...row, route: "#/c/" + category + "/b/" + encodeURIComponent(row.id)} : row);
  }
  function subjectChips(rows, filter) {
    const subjects = new Map();
    for (const row of rows) {
      for (const [id, title] of row.topics) {
        const entry = subjects.get(id) || {title, count: 0};
        entry.count++;
        subjects.set(id, entry);
      }
    }
    const choices = [...subjects.entries()].filter(([, entry]) => entry.count < rows.length)
      .sort((a, b) => b[1].count - a[1].count || a[1].title.localeCompare(b[1].title)).slice(0, 5);
    if (!choices.length) return "";
    return '<div class="chips plain category-filters" aria-label="Filter by subject">' +
      [["", {title: "All"}], ...choices].map(([id, {title}]) =>
        '<button type="button" data-subject="' + escape(id) + '" aria-pressed="' + (id === filter) + '">' +
        escape(title) + "</button>").join("") + "</div>";
  }
  function categoryView(cat, rows, filter) {
    const visible = filter ? rows.filter(row => row.topics.some(([id]) => id === filter)) : rows;
    return back("#/", "Library") + '<h2 tabindex="-1"><span class="dot" aria-hidden="true" style="--c:var(--c-' + cat.id + ')"></span>' +
      escape(cat.name) + '</h2><p class="sub">' + count(rows.length, cat.unit) + " · " +
      escape(cat.blurb) + "</p>" + (rows.length > 30 ? subjectChips(rows, filter) : "") +
      (visible.length ? list(bookRoutes(visible, cat.id)) : '<p class="note">No items in this category.</p>');
  }
  function bookView(cat, book) {
    return back("#/c/" + cat.id, cat.name) + "<h2>" + escape(book.title) + '</h2><p class="sub">' +
      escape([book.publisher, details(book)].filter(Boolean).join(" · ")) + "</p>" +
      list(book.chapters.map(chapter => ({...chapter, summary: details({...chapter, source: ""})})));
  }
  async function allView(topic) {
    const categories = home.categories.filter(cat => cat.count);
    const groups = await Promise.all(categories.map(cat => data(cat.id)));
    let title = allTitle;
    const rows = groups.flatMap((members, index) => bookRoutes(members.filter(row => {
      if (!topic) return true;
      const match = row.topics.find(([id]) => id === topic);
      if (match) title = match[1];
      return Boolean(match);
    }), categories[index].id)).sort((a, b) => a.title.localeCompare(b.title));
    return back(topic ? "#/search" : "#/", topic ? "Search" : "Library") + heading(title) +
      (rows.length ? list(rows) : '<p class="note">No items here in this library.</p>');
  }

  function savedView() {
    if (!saved.length && !recent.length) {
      return heading("Saved") + '<div class="empty">' + icon("star") +
        "<p>Tap the star beside any item to keep it here.</p></div>";
    }
    return heading("Saved", "Kept in this browser on this device") + (saved.length ? list(saved) : "") +
      (recent.length ? label("Recently opened") + list(recent) : "");
  }
  function remember(row) {
    if (!storage || row.id === "all") return;
    const {id, title, route, href, path, format, kind, bytes, articles, articlePaths, source, summary, parts} = row;
    const entry = {id, title, route, href, path, format, kind, bytes, articles, articlePaths, source, summary, parts};
    recent = [entry, ...recent.filter(previous => previous.id !== id)];
    persist();
  }

  function detectedDevice() {
    const platform = navigator.userAgentData?.platform || navigator.platform || "";
    const ua = navigator.userAgent;
    if (/iPhone|iPad|iPod/i.test(ua) || /Mac/i.test(platform) && navigator.maxTouchPoints > 1) return "iphone";
    if (/Android/i.test(ua)) return "android";
    if (/Win/i.test(platform)) return "windows";
    return /Mac/i.test(platform) ? "mac" : "linux";
  }
  function bundledReader(platform = device) {
    const folder = platform === "mac" ? "MACOS" : platform.toUpperCase();
    return home.readers.find(reader => reader.path.startsWith("LIBRARY/SOFTWARE/" + folder + "/"));
  }
  function steps(texts) {
    return '<ol class="steps">' + texts.map(text => "<li><span>" + text + "</span></li>").join("") + "</ol>";
  }
  function showSheet(title, body, action = "") {
    sheet.innerHTML = '<h2 id="sheet-title">' + title + "</h2>" + body + action;
    if (!sheet.open) {
      returnFocus = document.activeElement;
      sheet.showModal();
    } else (sheet.querySelector("button") || sheet).focus();
  }

  function kiwixView(row, reason) {
    const installer = bundledReader();
    const downloadsInstaller = chromium && installer && device !== "android";
    const label = installer ? "Get " + installer.label : device === "iphone" ? "Get Kiwix for iPhone" : "";
    const action = installer || label ? '<a class="button" href="' +
      escape(installer?.href || "https://apps.apple.com/us/app/kiwix/id997079563") + '"' +
      (downloadsInstaller ? " download" : "") + ">" + escape(label) + "</a>"
      : '<a class="button" href="https://kiwix.org/en/applications/">Get Kiwix</a>';
    const downloadNote = downloadsInstaller ?
      '<p class="note">Saves the installer to Downloads. Open it there to install Kiwix.</p>' : "";
    const [name, ...folders] = row.path.split("/").reverse();
    const trail = '<span class="trail">' + escape(folders.reverse().join(" › ")) + " › <b>" + escape(name) + "</b></span>";
    const message = reason === "scripts" ? "Open this file in the Kiwix app." :
      reason === "file" ? "This file is missing or has changed." : "This page could not open this file.";
    return '<div class="panel article-fallback" data-reason="' + escape(reason) + '"><p class="sub">' +
      escape(archiveKind(row)) + '</p><p>' + message + (reason === "scripts" ? "" : " Open it in the Kiwix app.") +
      '</p><p class="article-trail">' + trail + "</p>" +
      (drive.archiveParts(row).length > 1 ? '<p class="note">Keep all parts together and open the first.</p>' : "") +
      action + downloadNote + "</div>";
  }

  function showKiwix(row, hash, reason, stats = {}) {
    if (reason === "scripts" && !needsKiwix(row)) {
      scriptArchives.add(row.id);
      refreshSearch?.(true);
    }
    remember({...row, route: hash});
    const content = document.querySelector("#article-content");
    content.innerHTML = kiwixView(row, reason);
    document.querySelector("#article-title").focus({preventScroll: true});
    content.dispatchEvent(new CustomEvent("owl:archive", {detail: {id: row.id, reason, ...stats}}));
  }

  function accessSheet(state, {input = useFolderInput, retry, startIn, alternate = false} = {}) {
    const folder = escape(drive.folderName(location.pathname));
    const mark = value => "<mark>" + value + "</mark>";
    const confirm = mark(escape(drive.pickerLabel(device, !input, firefox, chromium)));
    const instruction = "In the folder window, " + (input ? "open " + mark(folder) + ", then " + mark("LIBRARY") +
      ", then " + mark("ZIM") + ". Click " + confirm + "." : startIn ? "click " + confirm + " to use " +
      mark(escape(startIn.name)) + "." : "click " + mark(folder) + ", then " + confirm + ".");
    const note = input && firefox ? 'In Firefox’s Confirm Upload window, click ' + mark("Upload") + '. Nothing leaves this computer.' :
      input && chromium ? 'If the browser asks to upload files, click ' + mark("Upload") + '. Nothing leaves this computer.' :
        "This page only reads the drive. Nothing is copied or sent.";
    const caption = '<p class="picker-instruction">' + instruction + '</p><p class="note">' + note + "</p>";
    const states = {
      picking: ["Open from this drive", caption],
      wrong: ["Choose the library folder", '<p>That folder is not this library.</p>' + caption],
      disconnected: ["Reconnect this drive", '<p class="picker-instruction">' + mark(folder) +
        ' is not connected. Plug it in, then click Try again.</p>'],
      stalled: ["Drive access was denied", '<p role="status">The browser blocked this page from reading ' + mark(folder) + "." +
        (alternate ? " Choose the " + mark("ZIM") + " folder to open it another way." : "") + "</p>"],
    };
    const [title, body] = states[state];
    sheet.dataset.reason = state;
    const action = alternate ? "Choose the ZIM folder" : "Try again";
    showSheet(title, body, retry ? '<button type="button" class="button">' + action + "</button>" : "");
    if (retry) sheet.querySelector("button").onclick = retry;
  }

  function saveHandle(handle) {
    folderHandle = handle;
    folderStore?.(new URL(location.pathname, location.href).href, handle).catch(() => {});
  }

  function archiveAccess() {
    return Boolean(source);
  }

  function reconnectSheet(row, hash, fromRoute) {
    source = cachedZim = null;
    accessSheet("disconnected", {retry: () => readFromArchive(row, hash, fromRoute, {reconnecting: true})});
  }

  function readingState() {
    const origin = activeRoute?.startsWith("#/read/") ? history.state?.owlReadTab || history.state?.owlReadFrom : activeRoute;
    return {owlReadFrom: activeRoute, owlReadTab: origin};
  }

  function withinProbe(operation, delay) {
    let timer;
    const limit = new Promise(resolve => { timer = setTimeout(resolve, delay); });
    return Promise.race([operation, limit]).finally(() => clearTimeout(timer));
  }

  function waitForPicker(open, signal, afterReturn) {
    return new Promise((resolve, reject) => {
      const listeners = new AbortController();
      const options = {signal: listeners.signal};
      let hint;
      const away = () => {
        clearTimeout(hint);
        hint = undefined;
      };
      const finish = (settle, value) => {
        away();
        listeners.abort();
        settle(value);
      };
      const returned = () => {
        if (!document.hidden && document.hasFocus() && hint === undefined) {
          hint = setTimeout(afterReturn, 1000);
        }
      };
      // Chromium can show a separate permission prompt when the folder window closes.
      if (afterReturn) {
        root.addEventListener("blur", away, options);
        root.addEventListener("focus", returned, options);
        document.addEventListener("visibilitychange", () => document.hidden ? away() : returned(), options);
        document.addEventListener("pointerdown", returned, options);
        document.addEventListener("pointermove", returned, options);
        document.addEventListener("keydown", returned, options);
      }
      signal.addEventListener("abort", () => finish(reject, signal.reason), options);
      try { open().then(value => finish(resolve, value), error => finish(reject, error)); }
      catch (error) { finish(reject, error); }
    });
  }

  function stalledSheet(row, hash, fromRoute, input) {
    const alternate = !input && "webkitdirectory" in picker;
    accessSheet("stalled", {alternate, retry: () =>
      readFromArchive(row, hash, fromRoute, {forcePicker: true, input: input || alternate})});
  }

  function dismissAccess() {
    driveAccess?.abort();
    sheet.close();
  }

  async function readFromArchive(row, hash, fromRoute = false,
    {forcePicker = false, reconnecting = false, input = useFolderInput} = {}) {
    driveAccess?.abort();
    const attempt = driveAccess = new AbortController();
    const valid = () => !attempt.signal.aborted;
    const retry = () => readFromArchive(row, hash, fromRoute, {forcePicker: true, input});
    const done = (reason = "", options) => {
      const state = {...(fromRoute ? history.state : readingState()), owlFallback: reason};
      if (fromRoute) {
        history.replaceState(state, "");
        render(options);
      } else navigate(hash, true, state, options);
    };
    const accept = ({candidate, parts}, handle, choosing) => {
      if (choosing || !cachedZim || cachedZim.id !== row.id) cachedZim = {id: row.id, parts};
      source = candidate;
      if (choosing) useFolderInput = input;
      if (handle && handle !== folderHandle) saveHandle(handle);
      done();
    };
    const fromHandle = handle => drive.handleSource(handle, generation, archives.values());
    async function inspect(candidate, choosing) {
      const selected = await candidate;
      if (!valid()) return;
      return {candidate: selected, parts: await drive.openParts(selected, row, choosing)};
    }
    function failed(error) {
      if (!valid()) return;
      if (drive.accessDenied(error)) {
        attempt.abort();
        stalledSheet(row, hash, fromRoute, input);
      } else if (error.code === "folder") accessSheet("wrong", {input, retry});
      else if (error.code === "disconnected") reconnectSheet(row, hash, fromRoute);
      else done("file");
    }

    if (!forcePicker) {
      const handle = input ? null : folderHandle;
      // Bound the probe so a prompt, removed drive or stalled browser call
      // still leaves the user's activation available for the folder picker.
      const deadline = performance.now() + clickProbe;
      const remaining = () => Math.max(0, deadline - performance.now());
      let permission;
      if (handle) {
        try {
          permission = await withinProbe(handle.queryPermission(readOnly), remaining());
        } catch (_) { /* Open the picker if permission cannot be checked. */ }
      }
      if (!valid()) return;
      if (permission === "prompt" || permission === "denied") source = cachedZim = null;
      if (handle ? permission === "granted" : source) {
        if (source && !reconnecting) return done("", {checkParts: true});
        try {
          const selection = await withinProbe(inspect(source || fromHandle(handle), false), remaining());
          if (valid() && selection) {
            accept(selection, null, false);
            return;
          }
        } catch (_) {
          // A granted handle can point to a drive at its old location.
        }
        if (!valid()) return;
      }
    }

    if (input && !("webkitdirectory" in picker)) return done("unsupported");
    const startIn = input ? null : folderHandle;
    accessSheet("picking", {input, startIn});
    let permissionHint;
    const hint = chromium && !input ? () => {
      if (permissionHint) return;
      permissionHint = document.createElement("p");
      permissionHint.className = "note";
      permissionHint.setAttribute("role", "status");
      permissionHint.innerHTML = 'If you see “Allow this site to view and copy files?”, click <mark>Allow</mark>.';
      sheet.append(permissionHint);
    } : undefined;
    let selection;
    try {
      selection = await waitForPicker(() => input ? new Promise(resolve => {
        pickerResult = resolve;
        picker.value = "";
        picker.click();
      }) : root.showDirectoryPicker({...readOnly, id: "owl-library", ...(startIn && {startIn})}), attempt.signal, hint);
    } catch (error) {
      if (!valid()) return;
      if (error.name === "AbortError") dismissAccess();
      else if (drive.accessDenied(error)) failed(error);
      else done("unreadable");
      return;
    } finally {
      permissionHint?.remove();
      if (driveAccess === attempt) pickerResult = null;
    }
    if (!valid()) return;
    if (!selection) return dismissAccess();
    try {
      const candidate = input ? drive.fileSource(selection, generation, [...archives.values()]) : fromHandle(selection);
      const inspected = await inspect(candidate, true);
      if (valid()) accept(inspected, input ? null : selection, true);
    } catch (error) {
      failed(error);
    }
  }

  async function restoreFolder() {
    if (!chromiumPicker) return;
    try {
      folderStore = await drive.handleStore();
      const handle = await folderStore(new URL(location.pathname, location.href).href);
      if (folderHandle) return saveHandle(folderHandle);
      folderHandle = handle;
      if (!handle || driveAccess || await handle.queryPermission(readOnly) !== "granted") return;
      const candidate = await drive.handleSource(handle, generation, archives.values());
      if (driveAccess || source || handle !== folderHandle) return;
      source = candidate;
      if (activeRoute?.startsWith("#/read/")) render({keepFocus: true});
      else refreshSearch?.(true);
    } catch (_) {
      // A saved handle may have been revoked or the drive may have moved.
    }
  }

  function stopArticle() {
    if (!article) return;
    article.controller.abort();
    article.resize?.disconnect();
    for (const url of article.urls) URL.revokeObjectURL(url);
    article = null;
  }

  function parsedArticle(frame, signal) {
    // The iframe's load event also waits for images and other resources.
    return new Promise((resolve, reject) => {
      let nextFrame;
      const cancel = () => {
        cancelAnimationFrame(nextFrame);
        reject(signal.reason);
      };
      function check() {
        const doc = frame.contentDocument;
        if (doc?.URL === "about:srcdoc" && doc.readyState !== "loading") {
          signal.removeEventListener("abort", cancel);
          resolve(doc);
        } else nextFrame = requestAnimationFrame(check);
      }
      signal.addEventListener("abort", cancel, {once: true});
      check();
    });
  }

  function articleOpen(row, hash) {
    // After a reload or a lost drive, name the article that Open will show.
    const {path, title} = drive.parseRoute(hash);
    const name = title || (path === "@main" ? "" : path.split("/").pop().replace(/_/g, " "));
    // The browser needs a fresh click before a page may ask for the folder again.
    const folder = escape(drive.folderName(location.pathname));
    return '<div class="panel article-start">' + (name ? "<p>" + escape(name) + "</p>" : "") +
      '<p class="note">The browser needs one click to read <mark>' + folder + "</mark> again.</p>" +
      attachment({...row, route: hash}, "Open").replace("<a ", '<a class="button" ') + "</div>";
  }

  function articleView(row, hash, path) {
    const from = history.state?.owlReadFrom || "#/";
    const safeFrom = /^#\/(?:[a-zA-Z0-9_/%-]+)?$/.test(from) ? from : "#/";
    const title = from.startsWith("#/read/") ? "Previous article" :
      safeFrom === "#/search" ? "Search" : safeFrom === "#/saved" ? "Saved" :
      home.categories.find(cat => safeFrom === "#/c/" + cat.id)?.name || "Library";
    links.set(String(++linkNumber), {...row, route: hash});
    const name = path === "@main" ? archiveName(row) : row.title;
    return '<div class="article-bar"><a class="back" data-read-back href="' + safeFrom + '">‹ ' + escape(title) +
      '</a><div class="article-heading"><h1 id="article-title" tabindex="-1">' + escape(name) + '</h1>' +
      (storage ? button(String(linkNumber), row) : "") + '</div><p class="article-source" hidden>' +
      escape(row.title) + ' <span>· on this drive</span></p></div><div id="article-content">' +
      (needsKiwix(row) || history.state?.owlFallback ? "" : source ?
        '<p class="note" id="article-status" role="status">Opening…</p><div id="article-paper" class="article-paper" hidden></div>' :
        articleOpen(row, hash)) + '</div>';
  }

  async function loadArticle(row, path, fragment, title, section, savedScroll, hash, checkParts) {
    const controller = new AbortController();
    const current = article = {controller, urls: []};
    const active = () => article === current;
    const started = performance.now();
    const status = document.querySelector("#article-status");
    const slow = setTimeout(() => {
      status.innerHTML = "Still reading from <mark>" + escape(drive.folderName(location.pathname)) + "</mark>…";
    }, 4000);
    controller.signal.addEventListener("abort", () => clearTimeout(slow), {once: true});
    let zim, initialBytes = 0;
    try {
      if (checkParts || cachedZim?.id !== row.id) {
        const parts = await drive.openParts(source, row);
        if (!active()) return;
        if (cachedZim?.id !== row.id) cachedZim = {id: row.id, parts};
      }
      const cache = cachedZim;
      if (!cache.reader) {
        cache.reader = new root.OWLZim.Zim(cache.parts);
        cache.ready = cache.reader.init();
      } else initialBytes = cache.reader.bytesRead;
      zim = cache.reader;
      await cache.ready;
      controller.signal.throwIfAborted();
      const namespaced = zim.minor === 0 && /^[AIJ-]\//.test(path);
      const entry = await zim.get(namespaced ? path.slice(2) : path, {title, ns: namespaced ? path[0] : undefined});
      const page = await root.OWLZimArticle.prepare(zim, entry, current.urls, controller.signal);
      if (!active()) return;
      const isMain = path === "@main";
      const displayTitle = isMain ? archiveName(row) : page.title;
      const paper = document.querySelector("#article-paper");
      const titleElement = document.querySelector("#article-title");
      const frame = document.createElement("iframe");
      frame.title = displayTitle;
      frame.tabIndex = 0;
      // WebKit blocks the parent's event listeners in a script-sandboxed frame.
      // The trusted srcdoc head applies script-src 'none' before the article markup.
      frame.setAttribute("sandbox", webkit ? "allow-same-origin allow-scripts" : "allow-same-origin");
      frame.setAttribute("scrolling", "no");
      frame.srcdoc = page.html;
      paper.append(frame);
      const doc = await parsedArticle(frame, controller.signal);
      if (!active()) return;
      paper.hidden = false;
      status.remove();
      if (isMain) root.OWLZimArticle.hideMainHeading(doc);
      function resize() {
        const height = Math.ceil(Math.max(doc.body.scrollHeight, doc.body.getBoundingClientRect().height));
        frame.style.height = height + "px";
        return height;
      }
      function jump(at, heading, focus = false) {
        const target = root.OWLZimArticle.targetElement(doc, at, heading);
        if (!target) return;
        resize();
        const top = scrollY + frame.getBoundingClientRect().top + target.getBoundingClientRect().top;
        scrollTo(0, Math.max(0, top - (parseFloat(getComputedStyle(frame).getPropertyValue("--article-scroll-offset")) || 12)));
        if (focus) {
          target.tabIndex = -1;
          target.focus({preventScroll: true});
        }
      }
      function followLink(event) {
        const target = event.target.closest("[data-owl-link]");
        if (!target) return;
        const destination = page.links.get(target.getAttribute("data-owl-link"));
        if (!destination) return;
        event.preventDefault();
        if (destination.external) {
          if (event.button <= 1) root.open(destination.external, "_blank", "noopener");
          return;
        }
        if (event.button !== 0) return;
        const {path: next, fragment: at, ns} = destination;
        if (!next || next === entry.path && ns === entry.ns && at) jump(at, "", true);
        else {
          const fullPath = zim.minor === 0 ? ns + "/" + next : next;
          navigate(archiveRoute(row, fullPath, at), true, readingState());
        }
      }
      doc.addEventListener("click", followLink);
      doc.addEventListener("auxclick", followLink);
      const images = [...doc.images].filter(img => img.hasAttribute("src") || img.hasAttribute("srcset"));
      const recoverLayout = () => root.OWLZimArticle.recoverLayout(doc, page, resize);
      const loadingImages = images.some(img => !img.complete);
      if (loadingImages) resize();
      else recoverLayout();
      titleElement.textContent = displayTitle;
      const sourceLabel = view.querySelector(".article-source");
      if (isMain || displayTitle === row.title) sourceLabel.textContent = "On this drive";
      sourceLabel.hidden = false;
      // The article prints its own heading; keep this one for focus and screen readers only.
      if (!isMain && doc.querySelector("h1")) {
        titleElement.classList.add("visually-hidden");
        titleElement.after(sourceLabel);
      }
      titleElement.focus({preventScroll: true});
      const place = () => {
        if (fragment || section) jump(fragment, section);
        else scrollTo(0, savedScroll);
      };
      place();
      // Pictures can change the height of a section or make a saved position reachable.
      let restorePosition = Boolean(savedScroll || fragment || section);
      const fit = () => {
        resize();
        if (restorePosition) place();
      };
      if (restorePosition) {
        const leavePosition = () => { restorePosition = false; };
        const options = {once: true, passive: true, signal: controller.signal};
        for (const event of ["wheel", "touchstart", "pointerdown", "keydown"]) {
          root.addEventListener(event, leavePosition, options);
          doc.addEventListener(event, leavePosition, options);
        }
      }
      // Resize the frame to its content so the outer reader owns scrolling.
      current.resize = new ResizeObserver(fit);
      current.resize.observe(doc.body);
      if (loadingImages) frame.addEventListener("load", () => {
        recoverLayout();
        fit();
      }, {once: true, signal: controller.signal});
      paper.dataset.ready = "true";
      remember({...row, route: hash});
      // Record image counts when decoding finishes, after the article is ready to read.
      const metrics = {id: row.id, path: entry.path, ms: performance.now() - started, bytes: zim.bytesRead - initialBytes,
        images: images.length, resources: page.loaded, textLength: page.textLength, scripts: page.scripts,
        illustrations: page.illustrations};
      Promise.all(images.map(img => img.decode().catch(() => {}))).then(() => {
        if (!active()) return;
        fit();
        restorePosition = false;
        paper.dispatchEvent(new CustomEvent("owl:archive", {detail: {...metrics,
          shown: images.filter(image => image.naturalWidth > 0).length}}));
      });
    } catch (error) {
      if (!active()) return;
      cachedZim = null;
      stopArticle();
      if (drive.accessDenied(error) || drive.accessDenied(error.cause)) {
        source = null;
        document.querySelector("#article-content").innerHTML = articleOpen(row, hash);
        stalledSheet(row, hash, true, useFolderInput);
        return;
      }
      if (error.code === "disconnected" || ["NotFoundError", "NotReadableError"].includes(error.name)) {
        document.querySelector("#article-content").innerHTML = articleOpen(row, hash);
        reconnectSheet(row, hash, true);
        return;
      }
      const reason = ["scripts", "file", "unsupported"].includes(error.code) ? error.code : "unreadable";
      showKiwix(row, hash, reason, {path, ms: performance.now() - started,
        bytes: (zim?.bytesRead || 0) - initialBytes, scripts: error.scripts, textLength: error.textLength,
        illustrations: error.illustrations});
    } finally {
      clearTimeout(slow);
    }
  }

  function helpView() {
    const instructions = home.devices[helpPhone], reader = bundledReader(helpPhone);
    const instructionsText = [helpPhone === "iphone" || reader ? instructions.install : "Install Kiwix while you have internet.",
      instructions.open, instructions.pick];
    const choose = '<label>Phone <select id="device">' + ["iphone", "android"].map(id => '<option value="' + id + '"' +
      (id === helpPhone ? " selected" : "") + ">" + escape(home.devices[id].label) + "</option>").join("") + "</select></label>";
    const apps = home.readers.length ? '<div class="panel"><h3>Reader apps on this drive</h3><ul>' +
      home.readers.map(row => '<li><a href="' + escape(row.href) + '">' + escape(row.label) +
        '</a><span class="where">' + escape(row.path) + "</span></li>").join("") + "</ul></div>" : "";
    const phone = home.phone.length ? '<div class="panel"><h3>WikiMed PDFs</h3><p>Read these without Kiwix.</p>' +
      list(home.phone) + "</div>" : "";
    const recorded = new Date(home.syncedAt || "");
    const fromRecord = !Number.isNaN(recorded.getTime());
    const stamp = fromRecord ? recorded : new Date(document.lastModified);
    const date = !Number.isNaN(stamp.getTime()) ? new Intl.DateTimeFormat("en-GB",
      {day: "numeric", month: "long", year: "numeric", ...(fromRecord ? {timeZone: "UTC"} : {})}).format(stamp) : "Unknown";
    const phoneHelp = '<details class="device-choice"' + (device === "iphone" || device === "android" ? " open" : "") +
      '><summary>Using this drive on a phone</summary>' + choose + steps(instructionsText.map(escape)) + "</details>";
    return heading("Help") + '<div class="panel"><p>Books, guides and encyclopedias open right here.</p>' +
      phoneHelp + "</div>" +
      '<div class="panel"><h3>About this drive</h3><dl class="facts">' +
      "<div><dt>Last synced</dt><dd>" + date + "</dd></div><div><dt>Holds</dt><dd>" +
      count(home.stats.count) + ", " + size(home.stats.bytes) + "</dd></div>" +
      "<div><dt>Could not be downloaded</dt><dd>" + (home.stats.missing || "None") + "</dd></div></dl>" +
      '<p><a href="LIBRARY/INVENTORY.html">Every file, with its location</a> · <a href="LIBRARY/BUILD_REPORT.html">Build report</a></p></div>' +
      '<div class="panel"><h3>Make another drive</h3><p>On a computer with internet, open the library builder below.</p>' +
      '<a class="where" href="https://jonaraphael.com/offline-wandering-library/">jonaraphael.com/offline-wandering-library</a></div>' +
      apps + phone;
  }

  function searchView() {
    const container = document.createElement("div");
    container.className = "reader-screen";
    container.innerHTML = heading("Search", "Looks inside " + searchCount) +
      '<form id="search-form"><label class="search">' + icon("search") +
      '<input type="search" id="query" aria-label="Search" placeholder="Search" autocomplete="off" enterkeyhint="search">' +
      '</label><button type="submit" hidden>Search</button>' +
      '<details class="search-options"><summary>Options</summary><label>Category <select id="search-category">' +
      '<option value="">All categories</option>' + home.categories.filter(cat => cat.count)
        .map(cat => '<option value="' + cat.id + '">' + escape(cat.name) + "</option>").join("") +
      '</select></label></details><div id="search-examples">' +
      label("Try searching for") + '<div class="chips plain">' +
      ["Burns", "Safe drinking water", "Food canning", "Fix a bicycle", "First aid", "Find shelter"]
        .map(query => '<button type="button" data-query="' + escape(query) + '">' + escape(query) + "</button>").join("") +
      '</div></div></form><p class="note" id="search-status" role="status" hidden></p><div id="search-results"></div>';
    if (home.search) {
      refreshSearch = engine.mount(container, {open: openResult, tasks: home.tasks, priority: home.searchPriority,
        archiveAccess, archiveHref: resultRoute, urgentHref: taskRoute,
        archiveLabel: id => kiwixLabel(archives.get(id)),
        openUrgent: (task, event) => {
          if (task.format === "zim") {
            event.preventDefault();
            openArchive(task, taskRoute(task));
          } else remember(task);
        },
        categoryIds: async id => new Set((await data(id))
        .flatMap(row => (row.chapters || [row]).map(item => item.id)))});
    } else {
      container.querySelector("#search-form").hidden = true;
      const status = container.querySelector("#search-status");
      status.hidden = false;
      status.textContent = "Search data is unavailable on this drive. Browse the books and guides from Home.";
    }
    return container;
  }

  function resultRoute(record, name) {
    const id = record.asset_id || record.id;
    const locator = record.archivePath || String(record.location || "").match(/^Archive (?:path|article): (.+?)(?: · |$)/)?.[1];
    const [path, anchor] = (locator || "").split("#");
    const section = record.archiveSection || "";
    const title = record.articleTitle || (["article", "section"].includes(record.kind) && !path ? name : "");
    return archiveRoute({id}, path || (title ? title.replaceAll(" ", "_") : "@main"), anchor, title, section);
  }

  function openArchive(row, hash) {
    const target = archives.get(row.id);
    if (target && !needsKiwix(target)) readFromArchive(target, hash, activeRoute === hash);
    else if (target) navigate(hash, true, readingState());
    else navigate(hash);
  }

  function openResult(record, name, event) {
    if (record.kind === "topic") {
      event.preventDefault();
      navigate("#/topic/" + encodeURIComponent(record.id.slice("topic:".length)));
      return;
    }
    if (engine.isArchive(record)) {
      event.preventDefault();
      openArchive({id: record.asset_id || record.id}, resultRoute(record, name));
      return;
    }
    const path = "LIBRARY/" + record.href.split("#")[0].split("/").map(decodeURIComponent).join("/");
    remember({id: record.asset_id || record.id, title: record.source_title || name, path,
      href: "LIBRARY/" + record.href, summary: record.location || ""});
  }

  function renderTabs() {
    const route = activeRoute?.startsWith("#/read/") ? history.state?.owlReadTab || history.state?.owlReadFrom : activeRoute;
    const here = route?.split("/")[1];
    const current = here === "topic" ? "search" : ["search", "saved", "help"].includes(here) ? here : "home";
    tabs.innerHTML = [["home", "Home", "#/"], ["search", "Search", "#/search"], ["saved", "Saved", "#/saved"],
      ["help", "Help", "#/help"]].filter(([id]) => id !== "saved" || storage).map(([id, title, href]) =>
      '<a href="' + href + '"' + (id === current ? ' aria-current="page"' : "") + ">" + icon(id === "saved" ? "star" : id) +
      title + "</a>").join("");
  }

  function position() {
    if (!activeRoute) return;
    positions.set(activeRoute, scrollY);
    if (location.hash === activeRoute) history.replaceState({...history.state, owlScroll: scrollY}, "");
  }

  function navigate(hash, focus = true, state = null, options) {
    position();
    moveFocus = focus;
    if (location.hash === hash) {
      render(options);
      return;
    }
    history.pushState(state, "", hash);
    render(options);
  }

  async function render({keepFocus = false, checkParts = false} = {}) {
    const mine = ++pageEpoch;
    driveAccess?.abort();
    pickerResult = null;
    stopArticle();
    if (sheet.open) sheet.close();
    const hash = location.hash || "#/";
    const [, name, id, , bookId] = hash.split("/");
    activeRoute = hash;
    const focus = moveFocus;
    moveFocus = false;
    const savedScroll = history.state?.owlScroll ?? positions.get(hash) ?? 0;
    const useSearch = name === "search";
    const update = () => {
      links = new Map();
      linkNumber = 0;
    };
    let content, reading, archive;
    try {
      update();
      if (name === "c") {
        const cat = home.categories.find(category => category.id === id);
        if (!cat) throw Error("This category is unavailable on this drive.");
        const rows = await data(id);
        if (mine !== pageEpoch) return;
        if (bookId) {
          const book = rows.find(row => row.id === decodeURIComponent(bookId) && row.chapters);
          if (!book) throw Error("This book is unavailable on this drive.");
          content = bookView(cat, book);
        } else content = categoryView(cat, rows, filters.get(hash) || "");
      } else if (name === "all" || name === "topic") {
        content = await allView(name === "topic" ? id : "");
      } else if (name === "read" && drive) {
        reading = drive.parseRoute(hash);
        archive = archives.get(reading.id);
        content = archive ? articleView(archive, hash, reading.path) :
          back("#/", "Library") + heading("This encyclopedia is unavailable on this drive.");
      } else if (useSearch) {
        searchMarkup ||= searchView();
        refreshSearch?.();
      } else if (name === "saved" && storage) content = savedView();
      else if (name === "help") content = helpView();
      else content = homeView();
    } catch (error) {
      content = back("#/", "Library") + heading("Could not open this list") +
        '<p role="status">' + escape(error.message) + "</p>";
    }
    if (mine !== pageEpoch) return;
    view.classList.toggle("narrow", Boolean(name) && name !== "read");
    view.classList.toggle("reading", name === "read");
    if (useSearch && searchMarkup) view.replaceChildren(searchMarkup);
    else view.innerHTML = '<div class="reader-screen">' + content + "</div>";
    renderTabs();
    view.hidden = tabs.hidden = false;
    document.documentElement.classList.add("live");
    scrollTo(0, savedScroll);
    const fallback = archive && (needsKiwix(archive) ? "scripts" : history.state?.owlFallback);
    if (fallback) showKiwix(archive, hash, fallback, {path: reading.path});
    else if (archive && source) {
      loadArticle(archive, reading.path, reading.fragment, reading.title, reading.section, savedScroll, hash, checkParts);
    }
    if (focus && !keepFocus && !(archive && (source || fallback))) {
      const target = view.querySelector(useSearch ? "#query:not([hidden])" : "h1, h2");
      if (target) {
        if (!useSearch) target.tabIndex = -1;
        target.focus({preventScroll: true});
      }
    }
  }

  function follow(event) {
    const anchor = event.target.closest("a");
    if (event.defaultPrevented || !anchor || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const row = links.get(anchor.dataset.open);
    const href = anchor.getAttribute("href");
    if (row && row.format !== "zim") remember(row);
    if (row?.format === "zim") {
      event.preventDefault();
      openArchive(row, href);
    } else if (anchor.hasAttribute("data-read-back") && history.state?.owlReadFrom) {
      event.preventDefault();
      history.back();
    } else if (href?.startsWith("#/")) {
      event.preventDefault();
      navigate(href);
    } else position();
  }

  function clickButton(event) {
    const star = event.target.closest("button[data-star]");
    if (star && storage) {
      const row = links.get(star.dataset.star);
      if (!row) return;
      const held = saved.some(item => item.id === row.id);
      saved = held ? saved.filter(item => item.id !== row.id) : [row, ...saved];
      persist();
      if (activeRoute === "#/saved") {
        position();
        render().then(() => {
          const target = view.querySelector(".star") || view.querySelector("h1");
          if (target?.tagName === "H1") target.tabIndex = -1;
          target?.focus({preventScroll: true});
        });
      } else star.setAttribute("aria-pressed", String(!held));
    }
    const chip = event.target.closest("button[data-subject]");
    if (chip) {
      const subject = chip.dataset.subject;
      filters.set(activeRoute, subject);
      positions.delete(activeRoute);
      history.replaceState(null, "");
      render({keepFocus: true}).then(() => {
        [...view.querySelectorAll("[data-subject]")].find(item => item.dataset.subject === subject)?.focus();
      });
    }
  }

  data("home").then(async result => {
    if (result.version !== 1 || !Array.isArray(result.categories)) return;
    home = result;
    device = detectedDevice();
    helpPhone = device === "android" ? "android" : "iphone";
    searchCount = home.searchCount.toLocaleString() + (home.searchCount === 1 ? " book or guide" : " books and guides");
    openStorage();
    if (home.archives?.length) {
      archives = new Map(home.archives.map(row => [row.id, row]));
      await Promise.all(["fzstd.js", "zim.js", "zim-drive.js", "zim-article.js"].map(name => engine.script(engine.local(name))));
      drive = root.OWLZimDrive;
      // Give a remembered handle a head start without delaying the library while a drive wakes up.
      await withinProbe(restoreFolder(), 2 * clickProbe);
    }
    if (drive) document.body.append(picker);
    picker.addEventListener("change", () => pickerResult?.(picker.files.length ? picker.files : null));
    picker.addEventListener("cancel", () => pickerResult?.(null));
    sheet.addEventListener("click", event => {
      if (event.target === sheet && (event.offsetX < 0 || event.offsetY < 0 ||
          event.offsetX > sheet.clientWidth || event.offsetY > sheet.clientHeight)) dismissAccess();
    });
    sheet.addEventListener("cancel", () => driveAccess?.abort());
    sheet.addEventListener("close", () => {
      if (!sheet.open) returnFocus?.focus({preventScroll: true});
    });
    history.scrollRestoration = "manual";
    if (!location.hash || location.hash === "#help") history.replaceState(history.state, "", location.hash === "#help" ? "#/help" : "#/");
    view.addEventListener("click", clickButton);
    view.addEventListener("focusin", event => {
      if (event.target.id === "home-search") navigate("#/search");
    });
    view.addEventListener("change", async event => {
      if (event.target.id !== "device") return;
      helpPhone = event.target.value;
      position();
      await render();
      const select = view.querySelector("#device");
      select.closest("details").open = true;
      select.focus({preventScroll: true});
    });
    document.addEventListener("click", follow);
    addEventListener("hashchange", () => render());
    addEventListener("scroll", () => {
      if (activeRoute) positions.set(activeRoute, scrollY);
    }, {passive: true});
    addEventListener("pagehide", event => {
      position();
      if (!event.persisted) stopArticle();
    });
    await render();
  }).catch(() => {
    // Keep the complete static page if the runtime or its local data cannot load.
  });
})(globalThis);
