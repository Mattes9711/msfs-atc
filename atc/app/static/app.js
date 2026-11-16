// MSFS ATC app window: talks to the local server (atc/app/server.py).
"use strict";

const $ = (id) => document.getElementById(id);
const RADIO = new Set(["atc", "atis", "pilot", "copilot", "chatter", "cabin", "missed_call"]);  // shown as station label + message
const LABELS = { heard: "Heard", understood: "Parser", readback: "Readback", tuning: "COM1", position: "Position",
                 info: "Info", notice: "Note", system: "App" };
const WARNING = /stop immediately|go around|runway incursion/i;
let callsign = "You";  // "Lufthansa 4AB" once the status has it
let running = false;
let status = null;  // the last /api/status

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

// --- formatting: aviation conventions ---------------------------------------------------------------------

function utc(seconds) {  // 1452Z
  const d = seconds === undefined ? new Date() : new Date(seconds * 1000);
  return String(d.getUTCHours()).padStart(2, "0") + String(d.getUTCMinutes()).padStart(2, "0") + "Z";
}

function freq(khz) {  // 121.705
  return khz ? (khz / 1000).toFixed(3) : "---.---";
}

function showFreq(element, khz) {
  // In a monospace font the dot is a full character wide and reads like a gap ("121. 705"): narrow it
  const [whole, fraction] = freq(khz).split(".");
  const dot = document.createElement("span");
  dot.className = "sep";
  dot.textContent = ".";
  element.replaceChildren(whole, dot, fraction);
}

function level(ft) {  // FL350 above 10000 ft, else 5000 FT
  return ft >= 10000 ? "FL" + String(Math.round(ft / 100)).padStart(3, "0") : ft + " FT";
}

function text(id, value) {
  $(id).textContent = value;
}

// --- screens ------------------------------------------------------------------------------------------

function show(state) {
  running = state.state === "running";
  if ($("settings").hidden) {
    $("setup").hidden = running;
    $("flight").hidden = !running;
  } else {
    screenBeforeSettings = running ? "flight" : "setup";  // shown when the settings are closed
  }
  const p = state.plan;
  text("flight-callsign", running && p ? p.callsign : "MSFS ATC");
  text("flight-route", running && p ? [p.aircraft, `${p.departure} → ${p.destination || "----"}`,
    p.cruise_ft ? level(p.cruise_ft) : ""].filter(Boolean).join(" · ") : "");
  if (!running && state.config.simbrief_username && !$("start-form").simbrief.value) {
    $("start-form").simbrief.value = state.config.simbrief_username;
  }
  if (!running && setupShownFor !== state.session_from) {  // the start screen appears: brief the SimBrief plan
    setupShownFor = state.session_from;
    const user = $("start-form").simbrief.value.trim();
    $("manual").open = !user;
    if (user && $("briefing").hidden) loadBriefing();
  }
  if (running) {
    setupShownFor = null;
    $("say-input").focus();
  }
  for (const id of ["tab-map", "tab-phrases"]) $(id).disabled = !running;  // only with a flight
  if (!running && $("settings").hidden) markRail("tab-atc");
}

function markRail(id) {  // the rail shows which view is open
  for (const item of document.querySelectorAll(".rail-item")) item.setAttribute("aria-selected", String(item.id === id));
}
let setupShownFor = null;  // the session the start screen was last prepared after

async function refresh() {
  show(await api("/api/state"));
}

// --- status: radio box, airport, flight line, banner ------------------------------------------------------

const stationKhz = new Map();  // station name → frequency, for the labels in the log

function showStatus(s) {
  status = s;
  if (!s) return;
  callsign = s.callsign || callsign;
  showFreq($("st-com"), s.com1_khz);
  if (s.next) { showFreq($("st-next"), s.next.khz); text("st-next-name", s.next.name); }
  else { text("st-next", "---.---"); text("st-next-name", ""); }
  text("st-squawk", s.squawk || "----");

  const a = s.airport;
  text("ap-ident", a.ident);
  text("ap-name", a.name);
  text("ap-info", [a.runway && `Runway ${a.runway} in use`, s.atis && `ATIS ${s.atis}`, a.qnh && `QNH ${a.qnh}`,
                   a.wind && `wind ${a.wind}`].filter(Boolean).join(" · "));
  $("ap-freqs").replaceChildren(...a.frequencies.map((f) => {
    const item = document.createElement("span");
    const key = document.createElement("span");
    key.className = "key";
    key.textContent = f.label;
    const value = document.createElement("span");
    showFreq(value, f.khz);
    if (f.khz === s.com1_khz) value.className = "tuned";
    item.append(key, value);
    stationKhz.set(f.station, f.khz);
    return item;
  }));
  if (s.tuned) stationKhz.set(s.tuned, s.com1_khz);
  if (s.com1_khz) stationKhz.set("You", s.com1_khz);  // for the pilot's lines written before the first status
  if (s.controller && s.controller_khz) stationKhz.set(s.controller, s.controller_khz);
  for (const label of document.querySelectorAll(".ls[data-station]")) {  // rows written before we knew the frequency
    const khz = stationKhz.get(label.dataset.station);
    if (khz) { label.previousElementSibling.textContent = freq(khz); delete label.dataset.station; }
  }

  text("st-phase", s.phase.replace("_", " ").replace(/^./, (c) => c.toUpperCase()));
  text("st-runway", s.runway || "--");
  text("st-sid", s.flight.sid || "-");
  text("st-cleared", s.cleared || "-");
  text("st-dest", s.flight.destination || "-");
  text("st-star", s.flight.star || "-");

  $("copilot-button").setAttribute("aria-pressed", String(Boolean(s.copilot)));
  text("copilot-button", s.copilot ? "Co-pilot radio: on" : "Co-pilot radio: off");
  $("copilot-next").hidden = !s.copilot;
  $("ptt").className = "ptt " + (s.ptt || "");
  text("ptt-text", s.ptt === "ready" ? "PTT " + s.ptt_key.toUpperCase() : s.ptt === "off" ? "PTT off" : "PTT …");
  showBanner(s);
}

let lastWarning = null;  // {text, time} of the last "stop immediately" / "go around"

function showBanner(s) {
  // Only when something is due: a warning (for 30 s), else a readback
  const warning = lastWarning && Date.now() / 1000 - lastWarning.time < 30 ? lastWarning : null;
  const readback = s.suggestion && s.suggestion.title === "Read back" ? s.suggestion.text : null;
  $("banner").hidden = !warning && !readback;
  $("banner").className = "banner" + (warning ? " warn" : "");
  text("banner-title", warning ? "ATC:" : "Read back:");
  text("banner-text", warning ? warning.text : readback || "");
}

// --- suggested next call --------------------------------------------------------------------------------------

let suggested = "";

function putInTextBox(value) {  // a suggestion is never sent by itself: the pilot says it, or sends it
  const input = $("say-input");
  input.value = value;
  input.focus();
}

function showSuggestion(s) {
  const next = s && s.suggestion;
  $("next").hidden = !next;
  if (!next || next.text === suggested) return;
  suggested = next.text;
  text("next-text", next.text);
}

$("next").addEventListener("click", () => putInTextBox(suggested));

for (const button of document.querySelectorAll("[data-call]")) {  // "Hamburg Ground, Lufthansa 4AB, say again"
  button.addEventListener("click", () => {
    const station = status && (status.tuned || status.controller);
    putInTextBox([station, callsign, button.dataset.call].filter(Boolean).join(", "));
  });
}

// --- phrases: one tab per group, the current phase's group first (R2) -------------------------------------------

let phraseBook = [];
let phraseGroup = null;  // the group the pilot picked; null = follow the flight's phase
let shownPhase = "";

async function loadPhrases() {
  try { phraseBook = await api("/api/phrases"); } catch (error) { return; }
  showPhrases();
}

function showPhrases() {
  const current = phraseBook.find((g) => g.current);
  const selected = phraseBook.find((g) => g.group === phraseGroup) || current || phraseBook[0];
  if (!selected) return;
  $("phrase-groups").replaceChildren(...phraseBook.map((g) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "tab" + (g.current ? " now" : "");
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(g === selected));
    tab.title = g.current ? "The calls of this phase" : "";
    tab.textContent = g.group;
    tab.addEventListener("click", () => { phraseGroup = g.group; showPhrases(); });
    return tab;
  }));
  $("phrase-list").replaceChildren(...selected.phrases.map((p) => {
    const item = document.createElement("div");
    item.className = "phrase";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = p.title;
    const pilot = document.createElement("button");
    pilot.type = "button";
    pilot.className = "pilot";
    pilot.textContent = p.pilot;
    pilot.title = "Put it in the text box";
    pilot.addEventListener("click", () => putInTextBox(p.pilot));
    const atc = document.createElement("div");
    atc.className = "atc";
    atc.textContent = "ATC: " + p.atc;
    item.append(title, pilot, atc);
    if (p.note) {
      const note = document.createElement("div");
      note.className = "note";
      note.textContent = p.note;
      item.append(note);
    }
    return item;
  }));
}

// --- views ---------------------------------------------------------------------------------------------------

const VIEWS = { atc: "view-atc", map: "map", phrases: "phrases" };  // rail item → the element it shows

function showView(name) {
  if (!$("settings").hidden) closeSettings();
  markRail("tab-" + name);
  if (!running) return;  // "Flight" before a flight is the New flight screen
  for (const [tab, element] of Object.entries(VIEWS)) $(element).hidden = tab !== name;
  if (name === "phrases") loadPhrases();
  else if (name === "map") loadMap();
  else toEnd();
}

for (const tab of Object.keys(VIEWS)) $("tab-" + tab).addEventListener("click", () => showView(tab));

// --- map: drawn by us on a canvas, no map tiles, so it works offline --------------------------------------------

const ZOOMS_NM = [1, 2, 5, 10, 20, 40, 80, 160, 320, 640];  // how many nautical miles the map is wide
const GROUND_ZOOM = 1, AIR_ZOOM = 5;  // 2 NM on the ground, 40 NM in the air, until the pilot zooms
let zoom = AIR_ZOOM;
let zoomChosen = false;  // the pilot zoomed: keep it
let mapData = null;  // airports, route, sectors: the same for the whole flight (/api/map)
let mapMoving = null;  // our aircraft and the traffic: with every status poll
let trafficSeen = "", trafficReadAt = 0;  // the traffic is read from the sim every 3 s: when it last changed
const DEAD_RECKON_S = 4;  // move aircraft on along their heading at most this long after a reading

function color(name) {  // the page's colour tokens, so the map follows the design
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

async function loadMap() {
  if (!mapData) {
    try { mapData = await api("/api/map"); } catch (error) { /* drawn without it; tried again next time */ }
  }
  drawMap();
}

function drawMap() {
  const canvas = $("map-canvas");
  const box = $("map");
  if (box.hidden || !box.clientWidth) return;
  const ratio = window.devicePixelRatio || 1;
  const w = box.clientWidth, h = box.clientHeight;
  canvas.width = w * ratio; canvas.height = h * ratio;
  canvas.style.width = w + "px"; canvas.style.height = h + "px";
  const g = canvas.getContext("2d");
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  g.clearRect(0, 0, w, h);
  text("map-scale", ZOOMS_NM[zoom] + " NM");

  const own = mapMoving && mapMoving.own;
  const first = mapData && mapData.airports[0];
  const center = own || first;
  if (!center) return;
  if (!zoomChosen) zoom = own && !own.on_ground ? AIR_ZOOM : GROUND_ZOOM;
  text("map-scale", ZOOMS_NM[zoom] + " NM");
  // Flat projection around the centre: 1 degree of latitude = 60 NM, longitude shrinks with cos(latitude)
  const perNm = w / ZOOMS_NM[zoom];
  const cosLat = Math.cos(center.lat * Math.PI / 180);
  const xy = (lat, lon) => [w / 2 + (lon - center.lon) * cosLat * 60 * perNm, h / 2 - (lat - center.lat) * 60 * perNm];
  g.font = "11px B612, sans-serif";
  g.textBaseline = "middle";

  if (mapData) {
    // Center sectors: thin lines, name and frequency in the middle
    for (const s of mapData.sectors) {
      g.strokeStyle = color("--line");
      g.lineWidth = 1;
      g.beginPath();
      s.polygon.forEach(([lat, lon], i) => { const [x, y] = xy(lat, lon); i ? g.lineTo(x, y) : g.moveTo(x, y); });
      g.closePath();
      g.stroke();
      const [cx, cy] = xy(s.polygon.reduce((a, p) => a + p[0], 0) / s.polygon.length,
                          s.polygon.reduce((a, p) => a + p[1], 0) / s.polygon.length);
      if (cx > 0 && cx < w && cy > 0 && cy < h) {
        g.fillStyle = color("--label");
        g.fillText(s.name.toUpperCase() + (s.khz ? " " + freq(s.khz) : ""), cx, cy);
      }
    }
    // The route: SimBrief's waypoints, else straight from origin to destination
    const [from, to] = [mapData.airports[0], mapData.airports[mapData.airports.length - 1]];
    const points = [from, ...mapData.route, ...(to && to !== from ? [to] : [])];
    g.strokeStyle = color("--soft");
    g.lineWidth = 1.5;
    g.beginPath();
    points.forEach((p, i) => { const [x, y] = xy(p.lat, p.lon); i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.stroke();
    if (ZOOMS_NM[zoom] <= 160) {
      g.fillStyle = color("--label");
      for (const p of mapData.route) {
        const [x, y] = xy(p.lat, p.lon);
        g.fillRect(x - 2, y - 2, 4, 4);
        g.fillText(p.ident, x + 6, y);
      }
    }
    // Airports: taxiways with their names and stands when zoomed in, the runways, the ICAO code
    const close = ZOOMS_NM[zoom] <= 5;
    for (const a of mapData.airports) {
      if (close) drawTaxiways(g, a, xy, w, h, perNm);
      for (const r of a.runways) {
        const [[la1, lo1], [la2, lo2]] = r.ends;
        g.strokeStyle = color("--line-strong");
        g.lineWidth = close ? Math.max(3, r.width_m / 1852 * perNm) : 3;  // to scale when close
        g.beginPath(); g.moveTo(...xy(la1, lo1)); g.lineTo(...xy(la2, lo2)); g.stroke();
        if (close) {  // the runway numbers just beyond each end
          g.fillStyle = color("--soft");
          r.ends.forEach(([lat, lon], i) => {
            const [ox, oy] = xy(...r.ends[1 - i]);
            const [ex, ey] = xy(lat, lon);
            const len = Math.hypot(ex - ox, ey - oy) || 1;
            g.fillText(r.names[i], ex + (ex - ox) / len * 14 - 6, ey + (ey - oy) / len * 14);
          });
        }
      }
      if (!close || ZOOMS_NM[zoom] > 2) {
        const [x, y] = xy(a.lat, a.lon);
        g.fillStyle = color("--text");
        g.fillText(a.ident, x + 10, y - 10);
      }
    }
  }
  // The taxi route ATC gave: green, on top of the taxiways
  const route = (mapMoving && mapMoving.taxi_route) || [];
  if (route.length > 1 && ZOOMS_NM[zoom] <= 10) {
    g.strokeStyle = color("--green");
    g.lineWidth = 3;
    g.beginPath();
    route.forEach(([lat, lon], i) => { const [x, y] = xy(lat, lon); i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.stroke();
  }
  // Traffic: small arrows with the callsign (aircraft on the ground only when zoomed in close)
  const since = Math.min((performance.now() - trafficReadAt) / 1000, DEAD_RECKON_S);
  for (const t of (mapMoving && mapMoving.traffic) || []) {
    if (t.on_ground && ZOOMS_NM[zoom] > 10) continue;
    const nm = (t.gs || 0) * since / 3600, rad = t.heading * Math.PI / 180;  // where it is now, roughly
    const [x, y] = xy(t.lat + nm * Math.cos(rad) / 60, t.lon + nm * Math.sin(rad) / 60 / cosLat);
    arrow(g, x, y, t.heading, 6, color("--label"));
    g.fillStyle = color("--label");
    g.fillText(t.callsign + (t.on_ground ? "" : " " + level(t.alt_ft)), x + 9, y);
  }
  if (own) arrow(g, w / 2, h / 2, own.heading, 9, color("--green"));  // us: green, in the middle
}

function drawTaxiways(g, airport, xy, w, h, perNm) {
  // Segments: taxiways a bit brighter than the lead-in lines to the stands
  for (const [la1, lo1, la2, lo2, , toStand] of airport.taxiways) {
    g.strokeStyle = color(toStand ? "--line" : "--line-strong");
    g.lineWidth = toStand ? 1 : 2;
    g.beginPath(); g.moveTo(...xy(la1, lo1)); g.lineTo(...xy(la2, lo2)); g.stroke();
  }
  // Names: one label per taxiway every ~150 px, so a long taxiway is named along its length without clutter
  g.fillStyle = color("--label");
  const placed = [];
  for (const [la1, lo1, la2, lo2, name, toStand] of airport.taxiways) {
    if (!name || toStand) continue;
    const [x, y] = xy((la1 + la2) / 2, (lo1 + lo2) / 2);
    if (x < 0 || y < 0 || x > w || y > h) continue;
    if (placed.some((p) => p.name === name && Math.hypot(p.x - x, p.y - y) < 150)) continue;
    if (placed.some((p) => Math.hypot(p.x - x, p.y - y) < 18)) continue;  // never on top of another label
    placed.push({ name, x, y });
    g.fillText(name, x + 3, y - 6);
  }
  if (ZOOMS_NM[zoom] <= 1) {  // stand names only very close
    g.fillStyle = color("--label");
    for (const p of airport.parking) {
      const [x, y] = xy(p.lat, p.lon);
      if (x > 0 && y > 0 && x < w && y < h) g.fillText(p.name, x + 3, y + 8);
    }
  }
}

function arrow(g, x, y, heading, size, fill) {  // a triangle pointing along the heading (0 = north, up)
  const a = heading * Math.PI / 180;
  const tip = [x + Math.sin(a) * size, y - Math.cos(a) * size];
  const left = [x + Math.sin(a + 2.5) * size * 0.8, y - Math.cos(a + 2.5) * size * 0.8];
  const right = [x + Math.sin(a - 2.5) * size * 0.8, y - Math.cos(a - 2.5) * size * 0.8];
  g.fillStyle = fill;
  g.beginPath(); g.moveTo(...tip); g.lineTo(...left); g.lineTo(...right); g.closePath(); g.fill();
}

function setZoom(step) {
  zoomChosen = true;
  zoom = Math.max(0, Math.min(ZOOMS_NM.length - 1, zoom + step));
  drawMap();
}

$("zoom-in").addEventListener("click", () => setZoom(-1));
$("zoom-out").addEventListener("click", () => setZoom(1));
$("map").addEventListener("wheel", (event) => { event.preventDefault(); setZoom(event.deltaY > 0 ? 1 : -1); },
                          { passive: false });
new ResizeObserver(drawMap).observe($("map"));

async function pollStatus() {
  if (!running) return;
  try {
    const s = await api("/api/status");
    showStatus(s);
    showSuggestion(s);
    mapMoving = s && s.map;
    const traffic = JSON.stringify((mapMoving && mapMoving.traffic) || []);
    if (traffic !== trafficSeen) { trafficSeen = traffic; trafficReadAt = performance.now(); }
    drawMap();
    if (s && s.phase !== shownPhase) {  // a new phase: its group becomes the current one
      shownPhase = s.phase;
      phraseGroup = null;
      if (!$("phrases").hidden) loadPhrases();
    }
  } catch (error) { /* the next poll tries again */ }
}

// --- radio log ----------------------------------------------------------------------------------------------

function isWarning(e) {
  return (e.kind === "atc" || e.kind === "notice") && WARNING.test(e.text);
}

function badge(e) {  // ["121.705", "Hamburg Ground"], ["121.705", "You"]; no frequency yet: ""
  if (e.kind === "pilot") return [status && status.com1_khz ? freq(status.com1_khz) : "", "You"];
  if (e.kind === "copilot") return [status && status.com1_khz ? freq(status.com1_khz) : "", "Co-pilot"];
  if (e.kind === "cabin") return ["", e.station || "Cabin"];  // in the cabin, not on the radio
  const khz = stationKhz.get(e.station);
  return [khz ? freq(khz) : "", e.station || "ATC"];
}

function row(e) {
  const li = document.createElement("li");
  li.className = (RADIO.has(e.kind) ? "" : "note ") + e.kind + (isWarning(e) ? " warn" : "");
  if (!RADIO.has(e.kind)) {
    li.textContent = `${LABELS[e.kind] || e.kind}: ${e.text}`;
    return li;
  }
  const [khz, who] = badge(e);
  const frequency = element("span", "lf", khz);
  const label = element("span", "ls", who);
  if (!["pilot", "cabin", "copilot"].includes(e.kind) && e.station && !stationKhz.has(e.station)) {
    label.dataset.station = e.station;  // its frequency is filled in later
  }
  if (e.kind === "pilot" && !(status && status.com1_khz)) label.dataset.station = "You";
  const msg = document.createElement("span");
  msg.className = "msg";
  const time = document.createElement("span");
  time.className = "time";
  time.textContent = utc(e.time);
  msg.append(time, e.text);
  li.append(frequency, label, msg);
  return li;
}

// The log sticks to its newest line unless the pilot scrolled up to read. A ResizeObserver keeps it there when the
// log gets smaller (panels above it grow) or its rows get taller (fonts loaded, a scrollbar makes lines wrap).
let stickToEnd = true;
let ownScroll = false;  // scroll events we caused ourselves don't mean "the pilot scrolled up"
const log = $("log");

function toEnd() {
  if (!stickToEnd) return;
  ownScroll = true;
  log.scrollTop = log.scrollHeight;
}

const keepAtEnd = new ResizeObserver(toEnd);
log.addEventListener("scroll", () => {
  if (ownScroll) { ownScroll = false; return; }
  stickToEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
});
keepAtEnd.observe(log);

const HIDDEN = new Set(["understood"]);  // the parser's view: in the flight log file, not on the screen

function addEvent(e) {
  if (HIDDEN.has(e.kind)) return;
  if (e.kind === "readback") {  // a tick behind the pilot's own transmission instead of a line of its own
    const mine = [...log.querySelectorAll("li.pilot .msg")].pop();
    if (mine) {
      const tick = document.createElement("span");
      tick.className = "tick";
      tick.textContent = " ✓";
      tick.title = "Readback correct";
      mine.append(tick);
      return;
    }
  }
  const li = row(e);
  log.append(li);
  keepAtEnd.observe(li);
  if (isWarning(e)) { lastWarning = { text: e.text, time: e.time }; if (status) showBanner(status); }
  toEnd();
}

function clearLog(first) {
  keepAtEnd.disconnect();
  keepAtEnd.observe(log);
  log.replaceChildren(row(first));
  stickToEnd = true;
  lastWarning = null;
}

function connect(from) {
  const stream = new EventSource("/api/events?from=" + from);
  const link = $("link");
  stream.onopen = () => { link.className = "link ok"; text("link-text", "Connected"); };
  stream.onerror = () => { link.className = "link down"; text("link-text", "No link"); };
  stream.onmessage = (message) => {
    const e = JSON.parse(message.data);
    if (e.kind === "system" && e.text.startsWith("session started")) { clearLog(e); mapData = null; }
    else addEvent(e);
    if (e.kind === "system" && (e.text.startsWith("session started") || e.text === "session ended")) refresh();
  };
}

// --- actions ------------------------------------------------------------------------------------------

function startBody() {  // the plan and options, the same for the briefing and the start
  const form = $("start-form");
  return {
    simbrief: form.simbrief.value.trim() || null,
    callsign: form.callsign.value, departure: form.departure.value, destination: form.destination.value,
    cruise: form.cruise.value, route: form.route.value,
    nosim: form.nosim.checked, weather: form.weather.value, strict_freq: form.strict_freq.checked,
  };
}

function setupError(message) {
  $("start-error").textContent = message || "";
  $("start-error").hidden = !message;
}

$("start-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("start-button").disabled = true;
  $("start-button").textContent = "Starting";  // loading airports and weather takes a few seconds
  setupError(null);
  try {
    show(await api("/api/start", startBody()));
  } catch (error) {
    setupError(error.message);
  } finally {
    $("start-button").disabled = false;
    $("start-button").textContent = "Start flight";
  }
});

// --- start screen: the briefing (Milestone 7) -------------------------------------------------

function element(tag, className, content) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (content !== undefined) e.textContent = content;
  return e;
}

function briefAirport(box, a, role) {  // one airport of the briefing: ident, name, runway and wind, METAR
  box.replaceChildren(element("span", "key", role));
  if (!a) {
    box.append(element("span", "brief-ident num", "----"), element("span", "soft", "no destination"));
    return;
  }
  box.append(element("span", "brief-ident num", a.ident), element("span", "", a.name || "unknown airport"));
  if (a.runway) {
    const runway = element("span", "brief-runway");
    runway.append(element("span", "key", "Runway "), element("span", "num live", a.runway));
    if (a.wind) runway.append(element("span", "soft", " " + a.wind.replace(/^\S+\s*\(?|\)$/g, "")));  // "15 (…)"
    box.append(runway);
  }
  if (a.metar) box.append(element("span", "brief-metar num", a.metar));
  if (a.note) box.append(element("span", "hint", a.note));
}

function showBriefing(b) {
  text("b-callsign", b.callsign);
  text("b-spoken", b.spoken_callsign);
  text("b-meta", [b.aircraft, b.cruise_ft ? level(b.cruise_ft) : "", b.source].filter(Boolean).join(" · "));
  briefAirport($("b-dep"), b.departure, "From");
  briefAirport($("b-dest"), b.destination, "To");
  const procedures = [b.sid && `SID ${b.sid}`, b.star && `STAR ${b.star}`].filter(Boolean).join(" · ");
  text("b-route", (b.route || "direct") + (procedures ? `  (${procedures})` : ""));
  $("b-notes").replaceChildren(...b.notes.map((n) => element("li", "", n)));
  $("briefing").hidden = false;
  // A loaded plan fills the fields, so a change by hand starts from it
  const form = $("start-form");
  for (const [field, value] of [["callsign", b.callsign], ["departure", b.departure && b.departure.ident],
    ["destination", b.destination && b.destination.ident]]) {
    if (!form[field].value && value) form[field].placeholder = value;
  }
}

async function loadBriefing() {
  const button = $("load-button");
  button.disabled = true;
  button.textContent = "Loading";
  setupError(null);
  try {
    showBriefing(await api("/api/briefing", startBody()));
  } catch (error) {
    $("briefing").hidden = true;
    setupError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Load flight";
  }
}

$("load-button").addEventListener("click", loadBriefing);
$("start-form").simbrief.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {  // Enter in the username loads the flight, it doesn't start it
    event.preventDefault();
    loadBriefing();
  }
});

$("say-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("say-input");
  const value = input.value.trim();
  if (!value) return;
  input.value = "";
  try {
    await api("/api/say", { text: value });
  } catch (error) {
    addEvent({ kind: "system", text: error.message, time: Date.now() / 1000 });
  }
});

$("stop-button").addEventListener("click", async () => show(await api("/api/stop", {})));
for (const [id, command] of [["copilot-button", "/copilot"], ["copilot-next", "/copilot next"]]) {
  $(id).addEventListener("click", () => api("/api/say", { text: command }).catch(() => {}));
}

// --- settings (R4): sections on the left, saved to settings.toml, used from the next flight ------------------------

let screenBeforeSettings = null;

function showSection(name) {
  for (const tab of document.querySelectorAll(".side .tab")) tab.setAttribute("aria-selected", String(tab.dataset.section === name));
  for (const card of document.querySelectorAll("#settings-form [data-section]")) card.hidden = card.dataset.section !== name;
}

function option(value, label) {
  const o = document.createElement("option");
  o.value = value;
  o.textContent = label;
  return o;
}

function fillSettings(data) {
  const form = $("settings-form");
  $("mic-select").replaceChildren(option("", "Windows default"), ...data.microphones.map((m) => option(String(m.index), m.name)));
  for (const [slot, name] of Object.entries(data.ptt_names)) text("ptt-name-" + slot, name || "none");
  for (const [name, value] of Object.entries(data.values)) {
    const field = form.elements[name];
    if (!field) continue;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value === null || value === undefined ? "" : String(value);
  }
  showMixer();
  text("settings-file", "Saved in " + data.file + " · used from the next flight");
  const folders = $("about-folders");
  folders.replaceChildren(...Object.entries(data.folders).flatMap(([what, where]) => {
    const dt = document.createElement("dt");
    dt.textContent = what[0].toUpperCase() + what.slice(1);
    const dd = document.createElement("dd");
    dd.textContent = where;
    return [dt, dd];
  }));
}

function showMixer() {
  for (const slider of document.querySelectorAll(".mixer input[type=range]")) {
    slider.nextElementSibling.textContent = slider.value + " %";
  }
}
document.addEventListener("input", (event) => {
  if (event.target.matches(".mixer input[type=range]")) showMixer();
});

async function openSettings() {
  if (!$("settings").hidden) return;
  screenBeforeSettings = $("flight").hidden ? "setup" : "flight";
  for (const id of ["setup", "flight"]) $(id).hidden = true;
  $("settings").hidden = false;
  markRail("settings-button");
  text("settings-status", "");
  showSection("general");
  try { fillSettings(await api("/api/settings")); }
  catch (error) { text("settings-status", error.message); }
}

function closeSettings() {
  $("settings").hidden = true;
  $(screenBeforeSettings || "setup").hidden = false;
  const open = Object.keys(VIEWS).find((tab) => !$(VIEWS[tab]).hidden);
  markRail(screenBeforeSettings === "flight" && open ? "tab-" + open : "tab-atc");
}

async function saveSettings() {
  const form = $("settings-form");
  const values = {};
  for (const field of form.elements) {
    if (!field.name) continue;
    values[field.name] = field.type === "checkbox" ? field.checked : field.value;
  }
  $("settings-status").className = "soft";
  try {
    fillSettings(await api("/api/settings", { values }));
    text("settings-status", "Saved. Used from the next flight; the sound mixer at once.");
  } catch (error) {
    $("settings-status").className = "error";
    text("settings-status", error.message);
  }
}

// Push-to-talk (R5): "Set", then the pilot presses the key or button; the app reads it from Windows directly
for (const button of document.querySelectorAll("[data-bind]")) {
  button.addEventListener("click", async () => {
    const slot = button.dataset.bind;
    const hint = $("bind-hint").textContent;
    button.disabled = true;
    text("ptt-name-" + slot, "press it now…");
    try {
      const found = await api("/api/ptt/capture", {});
      $("settings-form").elements["whisper." + slot].value = found.binding;
      text("ptt-name-" + slot, found.name);
      text("settings-status", "Not saved yet: press Save.");
    } catch (error) {
      text("ptt-name-" + slot, "not changed");
      text("settings-status", error.message);
    } finally {
      button.disabled = false;
      text("bind-hint", hint);
    }
  });
}
for (const button of document.querySelectorAll("[data-clear]")) {
  button.addEventListener("click", () => {
    $("settings-form").elements["whisper." + button.dataset.clear].value = "";
    text("ptt-name-" + button.dataset.clear, "none");
    text("settings-status", "Not saved yet: press Save.");
  });
}

for (const tab of document.querySelectorAll(".side .tab")) tab.addEventListener("click", () => showSection(tab.dataset.section));
$("settings-button").addEventListener("click", openSettings);
$("settings-close").addEventListener("click", closeSettings);
$("settings-save").addEventListener("click", saveSettings);

setInterval(() => { text("utc", utc()); }, 1000);
setInterval(pollStatus, 1000);
setInterval(() => { if (running && !$("map").hidden) drawMap(); }, 250);  // traffic rolls smoothly between polls
text("utc", utc());
api("/api/state").then((state) => { show(state); connect(state.session_from); });
document.fonts.ready.then(toEnd);
