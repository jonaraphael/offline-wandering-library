// Download diagnostics: a bounded log of transfer events with an on-page panel
// and a copy button, so a slow or stalled build can be reported in one paste.
const MAX_EVENTS = 3000;
const SHOWN_LINES = 400;
const events = [];
const routeStats = new Map();
const started = Date.now();
let panel, summaryBox, logBox, pending = false;

export function routeLabel(url) {
  try {
    const parsed = new URL(url, "https://owl.invalid/");
    const asset = /\/assets\/([^/?#]+)/.exec(parsed.pathname)?.[1];
    if (asset) {
      const peer = asset.includes("--") ? asset.split("--").pop() : "primary";
      return "relay:" + peer;
    }
    return "direct:" + parsed.hostname;
  } catch (_) {
    return String(url).slice(0, 60);
  }
}

function stats(route) {
  if (!routeStats.has(route)) routeStats.set(route, {requests: 0, ok: 0, failed: 0, bytes: 0, ms: 0, last: ""});
  return routeStats.get(route);
}

export function diag(type, data = {}) {
  const entry = {t: Date.now() - started, type, ...data};
  events.push(entry);
  if (events.length > MAX_EVENTS) events.splice(0, events.length - MAX_EVENTS);
  if (type === "request" && entry.route) {
    const row = stats(entry.route);
    row.requests++;
    if (entry.ok) {
      row.ok++;
      row.bytes += entry.bytes || 0;
      row.ms += entry.ms || 0;
    } else {
      row.failed++;
      row.last = (entry.status ? "HTTP " + entry.status + " " : "") + (entry.error || "");
    }
  }
  schedule();
}

function seconds(ms) {
  return (ms / 1000).toFixed(1) + "s";
}

function line(entry) {
  const fields = Object.entries(entry).filter(([key]) => key !== "t" && key !== "type")
    .map(([key, value]) => key + "=" + (typeof value === "object" ? JSON.stringify(value) : value));
  return "+" + seconds(entry.t) + " " + entry.type + " " + fields.join(" ");
}

function recentRate(windowMs = 10_000) {
  const now = Date.now() - started;
  let bytes = 0;
  for (let index = events.length - 1; index >= 0; index--) {
    const entry = events[index];
    if (now - entry.t > windowMs) break;
    if (entry.type === "request" && entry.ok) bytes += entry.bytes || 0;
  }
  return bytes / (windowMs / 1000) / 1e6;
}

export function diagnosticsSummary() {
  const rows = [...routeStats].map(([route, row]) =>
    route + ": " + row.ok + "/" + row.requests + " ok, " + (row.bytes / 1e6).toFixed(1) + " MB, " +
    (row.ms ? (row.bytes / 1e6 / (row.ms / 1000)).toFixed(2) : "0") + " MB/s per request" +
    (row.failed ? ", " + row.failed + " failed (last: " + row.last + ")" : ""));
  const last = events[events.length - 1];
  return ["Download diagnostics · " + new Date().toISOString(),
    "Browser: " + (globalThis.navigator?.userAgent || "unknown"),
    "Last 10 s: " + recentRate().toFixed(2) + " MB/s verified · events: " + events.length +
      " · last event " + (last ? seconds(Date.now() - started - last.t) + " ago (" + last.type + ")" : "none"),
    ...rows].join("\n");
}

export function diagnosticsText() {
  return diagnosticsSummary() + "\n\n" + events.map(line).join("\n");
}

function mount() {
  if (panel || typeof document === "undefined") return;
  const anchor = document.getElementById("build-progress") || document.getElementById("start-build")?.parentElement;
  if (!anchor) return;
  panel = document.createElement("details");
  panel.id = "download-diagnostics";
  panel.open = true;
  panel.style.cssText = "margin:1rem 0;padding:.6rem .8rem;border:1px solid currentColor;border-radius:8px;font-size:.78rem";
  const summary = document.createElement("summary");
  summary.textContent = "Download diagnostics";
  summary.style.cursor = "pointer";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.textContent = "Copy diagnostics";
  copy.style.margin = ".5rem 0";
  copy.addEventListener("click", async () => {
    const text = diagnosticsText();
    try {
      await navigator.clipboard.writeText(text);
      copy.textContent = "Copied " + text.length.toLocaleString() + " characters";
    } catch (_) {
      const area = document.createElement("textarea");
      area.value = text;
      area.rows = 8;
      area.style.width = "100%";
      panel.append(area);
      area.select();
      copy.textContent = "Select the text below and copy it";
    }
    setTimeout(() => { copy.textContent = "Copy diagnostics"; }, 4000);
  });
  summaryBox = document.createElement("pre");
  logBox = document.createElement("pre");
  for (const box of [summaryBox, logBox]) box.style.cssText = "white-space:pre-wrap;margin:.4rem 0;font:11px/1.35 ui-monospace,monospace";
  logBox.style.maxHeight = "22rem";
  logBox.style.overflow = "auto";
  panel.append(summary, copy, summaryBox, logBox);
  anchor.after(panel);
}

function render() {
  pending = false;
  mount();
  if (!panel) return;
  summaryBox.textContent = diagnosticsSummary();
  const atBottom = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 20;
  logBox.textContent = events.slice(-SHOWN_LINES).map(line).join("\n");
  if (atBottom) logBox.scrollTop = logBox.scrollHeight;
}

function schedule() {
  if (pending || typeof document === "undefined") return;
  pending = true;
  setTimeout(render, 500);
}

// The summary keeps ticking during a stall so "last event N s ago" stays current.
if (typeof document !== "undefined") setInterval(() => { if (panel) summaryBox.textContent = diagnosticsSummary(); }, 2000);
