// The device loop on the landing page. The drive stays put while a Mac, a Windows laptop, an iPhone and an
// Android phone slide in from the right in turn. Each takes the drive's connector, the drive's light comes on,
// a guide opens on the device's screen and scrolls, and the device slides away.
//
// Devices are drawn in landing.html in millimetres at 7.2 SVG units per mm, the scale at which the drive's
// connector is a USB-C plug 8.3 mm wide. Only the part of each device nearest the drive is ever in frame.
(() => {
const $ = id => document.getElementById(id);
const panel = document.querySelector(".devices-panel");
if (!panel) return;

const COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const SECTIONS = ["Health", "Food and farming", "Water, shelter and safety", "Repair and trades", "School",
  "Encyclopedias and maps", "College and technical", "Stories and culture"];
const clamp = x => Math.max(0, Math.min(1, x));
const smooth = x => x * x * (3 - 2 * x);
const f = n => n.toFixed(2);

// Keyboards: [row top in mm, row height, keys]. A key is a legend or [legend, width].
const wide = (legend, width) => [legend, width];
function keys(rows, left, keyWidth, gap, fill, ink, mac) {
  return rows.map(([y, h, row]) => {
    let x = left;
    return row.map(key => {
      const [legend, w] = Array.isArray(key) ? key : [key, keyWidth];
      const a = x;
      x += w + gap;
      const cap = `<rect x="${a}" y="${y}" width="${w}" height="${h}" rx="2.2" fill="${fill}"/>`;
      if (legend.length > 1) {
        const baseline = mac ? y + h - 2.5 : y + (h < 12 ? 5.8 : 5.4);
        return cap + `<text x="${a + 1.8}" y="${baseline}" font-size="${h < 12 ? 2.5 : 2.9}" fill="${ink}">${legend}</text>`;
      }
      return cap + (mac
        ? `<text x="${a + w / 2}" y="${y + 10.6}" font-size="6.2" text-anchor="middle" fill="${ink}">${legend}</text>`
        : `<text x="${a + 2.6}" y="${y + 7.6}" font-size="5.4" fill="${ink}">${legend}</text>`);
    }).join("");
  }).join("");
}
$("dv-keys0").innerHTML = keys([
  [15, 16.5, [wide("esc", 26.5), "F1", "F2", "F3", "F4", "F5", "F6", "F7"]],
  [34, 16.5, ["`", "1", "2", "3", "4", "5", "6", "7", "8"]],
  [53, 16.5, [wide("tab", 26), "Q", "W", "E", "R", "T", "Y", "U"]],
  [72, 16.5, [wide("caps lock", 31), "A", "S", "D", "F", "G", "H", "J"]],
  [91, 16.5, [wide("shift", 40.5), "Z", "X", "C", "V", "B", "N", "M"]],
], 22.5, 16.5, 2.5, "#27282c", "#dcdde0", true);
$("dv-keys1").innerHTML = keys([
  [12, 9, ["Esc", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9"]],
  [24, 16, ["`", "1", "2", "3", "4", "5", "6", "7", "8", "9"]],
  [43, 16, [wide("Tab", 25), "Q", "W", "E", "R", "T", "Y", "U", "I"]],
  [62, 16, [wide("Caps Lock", 30), "A", "S", "D", "F", "G", "H", "J"]],
  [81, 16, [wide("Shift", 39.5), "Z", "X", "C", "V", "B", "N", "M"]],
], 14, 16, 3, "#1c1d20", "#e3e4e7", false);

// Laptop screens: the library page, with its eight sections at the left and a column of guides that scrolls.
$("dv-dock").innerHTML = Array.from({length: 16}, (_, i) =>
  `<rect x="${60 + i * 15}" y="178.5" width="12" height="12" rx="2.8" fill="${["#fff", ...COLORS][i % 9]}"/>`).join("");
$("dv-task").innerHTML = [COLORS[3], COLORS[0], COLORS[2], COLORS[7], "#34373c", COLORS[6]].map((color, i) =>
  `<rect x="${167 + i * 11}" y="183.6" width="7.8" height="7.8" rx="1.6" fill="${color}"/>`).join("");
function libraryPage(device, top, selected, guides) {
  $("dv-side" + device).innerHTML =
    `<text x="6" y="${top + 6}" font-size="5.2" font-weight="700" letter-spacing=".8" fill="#15171a">OWL</text>` +
    SECTIONS.map((name, i) =>
      `<circle cx="7.6" cy="${top + 12.4 + i * 5.9}" r="1.8" fill="${COLORS[i]}"/>` +
      `<text x="12" y="${top + 13.7 + i * 5.9}" font-size="3.5" ` +
      (i === selected ? 'font-weight="700" fill="#15171a"' : 'fill="#565b61"') + `>${name}</text>`).join("");
  $("dv-s" + device).innerHTML =
    `<text x="70" y="${top + 7}" font-size="7" font-weight="700" fill="#15171a">${SECTIONS[selected]}</text>` +
    guides.map(([title, publisher], i) => {
      const x = 70 + i % 2 * 86, y = top + 13 + (i >> 1) * 44;
      return `<rect x="${x}" y="${y}" width="80" height="38" rx="3" fill="#fff" stroke="#e2dfd6" stroke-width=".5"/>` +
        `<rect x="${x + 4}" y="${y + 5}" width="2.4" height="28" rx="1.2" fill="${COLORS[selected]}"/>` +
        `<text x="${x + 11}" y="${y + 12.5}" font-size="4.4" font-weight="700" fill="#15171a">${title}</text>` +
        `<text x="${x + 11}" y="${y + 19.5}" font-size="3.3" fill="#84898f">${publisher}</text>` +
        `<rect x="${x + 11}" y="${y + 25}" width="60" height="1.8" rx=".9" fill="#dedbd3"/>` +
        `<rect x="${x + 11}" y="${y + 30}" width="42" height="1.8" rx=".9" fill="#dedbd3"/>`;
    }).join("");
}
libraryPage(0, 117.5, 0, [["Where There Is No Doctor", "Hesperian"], ["Clinical Guidelines", "Doctors Without Borders"],
  ["A Book for Midwives", "Hesperian"], ["MedlinePlus", "National Library of Medicine"],
  ["Basic Emergency Care", "World Health Organization"], ["Travelers’ Health", "CDC"],
  ["Where There Is No Dentist", "Hesperian"], ["WikiMed", "Medical encyclopedia"]]);
libraryPage(1, 121, 2, [["Are You Ready?", "FEMA"], ["Emergency Disinfection of Drinking Water", "EPA"],
  ["Sphere Handbook", "Sphere"], ["Shelter Projects", "Red Cross Red Crescent"],
  ["WASH in Emergencies", "World Health Organization"], ["Ready.gov guides", "Ready.gov"],
  ["Shelter Safety Handbook", "Red Cross Red Crescent"], ["Sanitation Systems", "Eawag"]]);

// Phone home screens: rounded squares on the iPhone, circles on the Android.
const ICONS = ["#fff", COLORS[0], COLORS[3], "#1f2226", COLORS[2], "#fff", COLORS[7], COLORS[6], COLORS[4], "#f2f2f4",
  COLORS[1], COLORS[5], "#34373c", COLORS[0], "#fff", COLORS[3], COLORS[2], COLORS[7], "#fff", COLORS[6]];
$("dv-ios-i").innerHTML = ICONS.map((color, i) => {
  const x = 5.85 + i % 4 * 15.9, y = 21 + (i / 4 | 0) * 18.6;
  return `<rect x="${f(x)}" y="${f(y)}" width="12.2" height="12.2" rx="2.9" fill="${color}"/>` +
    `<rect x="${f(x + 2.6)}" y="${f(y + 14)}" width="7" height="1.1" rx=".55" fill="#fff" opacity=".8"/>`;
}).join("");
$("dv-ios-d").innerHTML = [COLORS[2], "#fff", COLORS[0], "#1f2226"].map((color, i) =>
  `<rect x="${f(5.85 + i * 15.9)}" y="128.2" width="12.2" height="12.2" rx="2.9" fill="${color}"/>`).join("");
$("dv-and-i").innerHTML = [["#fff", COLORS[0], COLORS[7], COLORS[3]], ["#fff", COLORS[2], COLORS[1], COLORS[6], "#e8eaed"]]
  .map((row, j) => row.map((color, i) =>
    `<circle cx="${f(10.4 + i * 12.5)}" cy="${100.5 + j * 15.5}" r="5.3" fill="${color}"/>`).join("")).join("");

// Phone guides: a heading and a few lines of text for each part.
function guideParts(x, top, headings, color) {
  return headings.map((heading, i) => {
    const y = top + i * 26;
    return `<circle cx="${x + 1.6}" cy="${y - 1.5}" r="1.6" fill="${color}"/>` +
      `<text x="${x + 5.6}" y="${y}" font-size="4.3" font-weight="700" fill="#15171a">${heading}</text>` +
      [57, 54, 49, 30].map((w, j) =>
        `<rect x="${x}" y="${y + 4.4 + j * 4}" width="${w}" height="1.7" rx=".85" fill="#cfccc5"/>`).join("");
  }).join("");
}
$("dv-t2").innerHTML = guideParts(7, 107, ["Boil", "Disinfect with bleach", "If the water is cloudy", "Store it safely"], COLORS[2]);
$("dv-t3").innerHTML = guideParts(6.5, 101, ["Wounds", "Burns", "Broken bones", "Shock"], COLORS[0]);

// One turn per device: slide in until docked at IN, light on, guide opens from the drive's side and scrolls,
// light off, slide away from OUT. HIDDEN is where each guide waits off screen; SCROLL is how far it scrolls.
// ORDER lists the device groups in playing order: Mac (0), iPhone (2), Windows (1), Android (3).
const TURN = 3.25, IN = .7, OUT = 2.75, AWAY = 1330;
const ORDER = [0, 2, 1, 3];
const HIDDEN = ORDER.map(i => [[-310, 0], [-350, 0], [0, 146], [0, 150]][i]);
const SCROLL = ORDER.map(i => [44, 44, 30, 30][i]);
const LOOP = ORDER.length * TURN;
const devices = ORDER.map(i => [$("dv-" + i), $("dv-a" + i), $("dv-s" + i)]);
const stick = $("dv-stick"), led = $("dv-led"), halo = $("dv-halo");
const names = [...$("dv-n").children];
let now = 0;

function render(time) {
  now = (time % LOOP + LOOP) % LOOP;
  const turn = Math.min(devices.length - 1, now / TURN | 0);
  const u = now - turn * TURN;
  const arriving = clamp(u / IN), leaving = clamp((u - OUT) / (TURN - OUT));
  const x = AWAY * (Math.pow(1 - arriving, 3) + leaving * leaving * leaving);
  const lit = clamp((u - IN - .06) / .16) * (1 - clamp((u - OUT + .1) / .1));
  const nudge = u > IN ? Math.exp(-(u - IN) / .06) : 0;
  const open = 1 - Math.pow(1 - clamp((u - IN - .25) / .42), 3);
  const scrolled = smooth(clamp((u - IN - .85) / 1.05));
  devices.forEach(([device, guide, page], i) => {
    if (i !== turn) return device.setAttribute("display", "none");
    device.removeAttribute("display");
    device.setAttribute("transform", `translate(${f(884 + x)} 500)`);
    guide.setAttribute("transform", `translate(${f(HIDDEN[i][0] * (1 - open))} ${f(HIDDEN[i][1] * (1 - open))})`);
    page.setAttribute("transform", `translate(0 ${f(-SCROLL[i] * scrolled)})`);
  });
  stick.setAttribute("transform", `translate(${f(138 - 5 * nudge)} 366)`);
  led.setAttribute("opacity", f(.2 + .8 * lit));
  halo.setAttribute("opacity", f(lit * (.62 + .16 * Math.sin((u - IN) * 7))));
  names.forEach((name, i) => name.classList.toggle("on", i === turn && u > IN * .6 && u < OUT + .2));
}

// It runs only while the panel is on screen, and holds one still frame for readers who ask for less motion.
const motion = matchMedia("(prefers-reduced-motion: reduce)");
let frame = 0, visible = false;
function stop() {
  cancelAnimationFrame(frame);
  frame = 0;
}
function update() {
  stop();
  if (motion.matches) return render(2.3);
  if (!visible) return;
  const start = performance.now() - now * 1000;
  const step = stamp => {
    render((stamp - start) / 1000);
    frame = requestAnimationFrame(step);
  };
  frame = requestAnimationFrame(step);
}
panel.hidden = false;
$("dv-n").hidden = false;
render(0);
new IntersectionObserver(entries => {
  visible = entries[entries.length - 1].isIntersecting;
  update();
}, {threshold: .35}).observe(panel);
motion.addEventListener("change", update);
update();
})();
