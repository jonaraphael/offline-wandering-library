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
  const details = row => [row.source, row.kind, row.bytes ? size(row.bytes) : ""].filter(Boolean).join(" · ");
  const allTitle = "Everything, A to Z";
  const loaded = new Map(), pending = new Map();
  const positions = new Map(), filters = new Map();
  let home, device, activeRoute, pageEpoch = 0;
  let storage, libraryId, saved = [], recent = [];
  let links = new Map(), linkNumber = 0;
  let searchMarkup, searchCount;
  let moveFocus = false;

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
    const destination = archive ? "#open-encyclopedia" : row.route || row.href;
    return '<a href="' + escape(destination) + '" data-open="' + key + '"' +
      (archive ? ' aria-haspopup="dialog"' : "") +
      ">" + label + "</a>";
  }
  function button(id, row) {
    return '<button type="button" class="star" data-star="' + id + '" aria-label="' +
      escape("Save " + row.title) + '" aria-pressed="' + saved.some(item => item.id === row.id) + '">' + icon("star") + "</button>";
  }

  function list(rows, {go = false, stars = true} = {}) {
    return '<div class="list">' + rows.map(row => {
      const description = row.summary || details(row);
      const label = "<b>" + escape(row.title) + "</b>" + (description ? "<small>" + escape(description) + "</small>" : "");
      const anchor = attachment(row, label);
      return '<div class="row' + (go ? " go" : "") + '">' + anchor +
        (storage && stars ? button(String(linkNumber), row) : "") + "</div>";
    }).join("") + "</div>";
  }

  const heading = (title, subtitle = "") => "<h1>" + escape(title) + "</h1>" +
    (subtitle ? '<p class="sub">' + escape(subtitle) + "</p>" : "");
  const back = (href, name) => '<a class="back" href="' + href + '">‹ ' + escape(name) + "</a>";
  const label = (title, kind = "") => '<h2 class="label' + (kind ? " " + kind : "") + '">' + escape(title) + "</h2>";

  function homeView() {
    const urgent = home.tasks.map(task => task.path
      ? attachment(task, escape(task.task))
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
        "<p>Tap the star beside any book or guide to keep it here.</p></div>";
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
  function bundledReader() {
    const folder = device === "mac" ? "MACOS" : device.toUpperCase();
    return home.readers.find(reader => reader.path.startsWith("LIBRARY/SOFTWARE/" + folder + "/"));
  }
  function steps(texts) {
    return '<ol class="steps">' + texts.map(text => "<li><span>" + text + "</span></li>").join("") + "</ol>";
  }
  function openSheet(row) {
    const instructions = home.devices[device], reader = bundledReader();
    const install = device === "iphone" ? instructions.install : reader
      ? "Open the Kiwix app. On this device it is on the drive, in " + reader.path.replace(/\/[^/]+$/, "") + "."
      : "Open the Kiwix app. Install it while you have internet if you need it.";
    const articles = row.articles || [];
    const articlePaths = (row.articlePaths || []).filter((path, index) => path !== articles[index]);
    const multipart = row.parts > 1 || /\.zim[a-z]{2}$/i.test(row.path);
    const pick = "Pick the file below." + (multipart ? " Keep all parts in the same folder and open the first." : "") +
      '<span class="where">' + escape(row.path) + "</span>" +
      (articles.length ? "<p>In Kiwix, look up <b>" + articles.map(escape).join(" or ") + "</b>.</p>" : "") +
      (articlePaths.length ? '<span class="where">' + articlePaths.map(escape).join(" · ") + "</span>" : "");
    sheet.innerHTML = '<h2 id="sheet-title">' + escape(row.source || row.title) +
      '</h2><p class="sub">This one opens in the free Kiwix app.</p>' +
      steps([escape(install), escape(instructions.open), pick]) +
      '<form method="dialog"><button class="button" autofocus>Done</button></form>';
    sheet.showModal();
  }

  function helpView() {
    const instructions = home.devices[device], reader = bundledReader();
    const instructionsText = [device === "iphone" || reader ? instructions.install : "Install Kiwix while you have internet.",
      instructions.open, instructions.pick];
    const choose = '<details class="device-choice"><summary>' +
      (device === "iphone" ? "This is not an iPhone" : "Choose a different device") + '</summary><label>Device <select id="device">' +
      ["iphone", "android", "windows", "mac", "linux"].map(id => '<option value="' + id + '"' +
        (id === device ? " selected" : "") + ">" + escape(home.devices[id].label) + "</option>").join("") + "</select></label></details>";
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
    return heading("Help") + '<div class="panel"><h3>Opening files on this ' + escape(instructions.label) + "</h3>" +
      "<p>Books and guides open by themselves. Encyclopedias need the free Kiwix app.</p>" +
      steps(instructionsText.map(escape)) + choose + "</div>" +
      '<div class="panel"><h3>About this drive</h3><dl class="facts">' +
      "<div><dt>Last synced</dt><dd>" + date + "</dd></div><div><dt>Holds</dt><dd>" +
      count(home.stats.count) + ", " + size(home.stats.bytes) + "</dd></div>" +
      "<div><dt>Could not be downloaded</dt><dd>" + (home.stats.missing || "None") + "</dd></div></dl>" +
      '<p><a href="LIBRARY/INVENTORY.html">Every file, with its location</a> · <a href="LIBRARY/BUILD_REPORT.html">Build report</a></p></div>' +
      '<div class="panel"><h3>Make another drive</h3><p>On a computer with internet, open the page below in Chrome, Edge or Arc.</p>' +
      '<a class="where" href="https://jonaraphael.github.io/offline-wandering-library/">jonaraphael.github.io/offline-wandering-library</a></div>' +
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
      engine.mount(container, {open: openResult, tasks: home.tasks, priority: home.searchPriority,
        openUrgent: (task, event) => {
          remember(task);
          if (task.format === "zim") {
            event.preventDefault();
            openSheet(task);
          }
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

  function openResult(record, name, event) {
    if (record.kind === "topic") {
      event.preventDefault();
      navigate("#/topic/" + encodeURIComponent(record.id.slice("topic:".length)));
      return;
    }
    const path = "LIBRARY/" + record.href.split("#")[0].split("/").map(decodeURIComponent).join("/");
    const archive = engine.isArchive(record);
    const article = String(record.location || "").match(/^Archive (?:path|article): (.+?)(?: · |$)/)?.[1];
    const row = {id: record.asset_id || record.id, title: record.source_title || name, path,
      href: "LIBRARY/" + record.href, summary: record.location || "",
      ...(archive ? {format: "zim", articles: ["article", "section"].includes(record.kind) ? [record.articleTitle || name] : [],
        articlePaths: article ? [article] : []} : {})};
    remember(row);
    if (archive) {
      event.preventDefault();
      openSheet(row);
    }
  }

  function renderTabs() {
    const here = activeRoute?.split("/")[1];
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

  function navigate(hash, focus = true) {
    position();
    moveFocus = focus;
    if (location.hash === hash) {
      render();
      return;
    }
    history.pushState(null, "", hash);
    render();
  }

  async function render({keepFocus = false} = {}) {
    const mine = ++pageEpoch;
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
    let content;
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
      } else if (useSearch) {
        searchMarkup ||= searchView();
      } else if (name === "saved" && storage) content = savedView();
      else if (name === "help") content = helpView();
      else content = homeView();
    } catch (error) {
      content = back("#/", "Library") + heading("Could not open this list") +
        '<p role="status">' + escape(error.message) + "</p>";
    }
    if (mine !== pageEpoch) return;
    view.classList.toggle("narrow", Boolean(name));
    if (useSearch && searchMarkup) view.replaceChildren(searchMarkup);
    else view.innerHTML = '<div class="reader-screen">' + content + "</div>";
    renderTabs();
    view.hidden = tabs.hidden = false;
    document.documentElement.classList.add("live");
    scrollTo(0, savedScroll);
    if (focus && !keepFocus) {
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
    if (row) remember(row);
    if (row?.format === "zim") {
      event.preventDefault();
      openSheet(row);
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
    searchCount = home.searchCount.toLocaleString() + (home.searchCount === 1 ? " book or guide" : " books and guides");
    openStorage();
    history.scrollRestoration = "manual";
    if (!location.hash || location.hash === "#help") history.replaceState(history.state, "", location.hash === "#help" ? "#/help" : "#/");
    view.addEventListener("click", clickButton);
    view.addEventListener("focusin", event => {
      if (event.target.id === "home-search") navigate("#/search");
    });
    view.addEventListener("change", async event => {
      if (event.target.id !== "device") return;
      device = event.target.value;
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
    addEventListener("pagehide", position);
    await render();
  }).catch(() => {
    // Keep the complete static page if the runtime or its local data cannot load.
  });
})(globalThis);
