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
  document.body.classList.toggle("running", running);
  for (const id of ["strip-flight", "callsign-key", "phase-cell", "field"]) $(id).hidden = !running;
  if (!running) {
    $("next-com").hidden = true;
    text("st-com", "---.---");
    text("st-tuned", "No flight");
  }
  text("flight-callsign", running && p ? p.callsign : "MSFS ATC");
  text("flight-route", running && p ? `${p.departure} → ${p.destination || "----"}` : "");
  $("flight-route").title = running && p ? [p.aircraft, p.cruise_ft ? level(p.cruise_ft) : ""].filter(Boolean).join(" · ") : "";
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

function markRail(id) {  // the views at the foot of the stack show which one is open
  for (const item of document.querySelectorAll(".view-button")) item.setAttribute("aria-selected", String(item.id === id));
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
  text("st-tuned", s.tuned || (s.on_frequency === false ? "No station on this frequency" : ""));
  $("next-com").hidden = !s.next;
  if (s.next) { showFreq($("st-next"), s.next.khz); text("st-next-name", s.next.name); }
  else { text("st-next", "---.---"); text("st-next-name", ""); }
  text("st-squawk", s.squawk || "----");

  const a = s.airport;
  text("st-qnh", a.qnh || "----");
  text("ap-ident", a.ident);
  text("ap-name", a.name);
  text("ap-info", [a.runway && `Runway ${a.runway} in use`, s.atis && `ATIS ${s.atis}`,
                   a.wind && `wind ${a.wind}`].filter(Boolean).join(" · "));
  $("ap-freqs").replaceChildren(...a.frequencies.map((f) => {  // a ruled list: label | frequency
    const item = document.createElement("div");
    item.className = "freq" + (f.khz === s.com1_khz ? " tuned" : "");
    const key = document.createElement("span");
    key.className = "key";
    key.textContent = f.label;
    const value = document.createElement("span");
    showFreq(value, f.khz);
    item.append(key, value);
    stationKhz.set(f.station, f.khz);
    return item;
  }));
  if (s.tuned) stationKhz.set(s.tuned, s.com1_khz);
  if (s.com1_khz) stationKhz.set("You", s.com1_khz);  // for the pilot's lines written before the first status
  if (s.controller && s.controller_khz) stationKhz.set(s.controller, s.controller_khz);
  for (const label of document.querySelectorAll(".ls[data-station]")) {  // rows written before we knew the frequency
    const khz = stationKhz.get(label.dataset.station);
    if (khz) { label.parentElement.querySelector(".lf").textContent = freq(khz); delete label.dataset.station; }
  }

  text("st-phase", s.phase.replace("_", " ").replace(/^./, (c) => c.toUpperCase()));
  text("st-runway", s.runway || "--");
  text("st-sid", [s.flight.sid, s.flight.star].filter(Boolean).join(" / ") || "-");
  text("st-cleared", s.cleared || "-");

  $("copilot-button").setAttribute("aria-pressed", String(Boolean(s.copilot)));
  text("copilot-button", s.copilot ? "Co-pilot radio: on" : "Co-pilot radio: off");
  $("copilot-next").hidden = !s.copilot;
  $("ptt").className = "ptt " + (s.ptt || "") + (talking ? " talking" : "");
  $("overlay-button").hidden = s.overlay === null || s.overlay === undefined;  // only in the app window
  $("overlay-button").setAttribute("aria-pressed", String(Boolean(s.overlay)));
  text("overlay-button", s.overlay ? "Overlay: on" : "Overlay: off");
  showPtt();
  showBanner();
}

function showPtt() {  // "Transmitting" while push-to-talk is held, else which key it is
  const s = status;
  text("ptt-text", talking ? "Transmitting" : !s ? "PTT"
    : s.ptt === "ready" ? "PTT " + s.ptt_key.toUpperCase() : s.ptt === "off" ? "PTT off" : "PTT …");
}

let lastWarning = null;  // {text, time} of the last "stop immediately" / "go around"

function showBanner() {
  // Only for a warning, for 30 s; the readback that is due is the next call above the say bar
  const warning = lastWarning && Date.now() / 1000 - lastWarning.time < 30 ? lastWarning : null;
  $("banner").hidden = !warning;
  text("banner-title", "ATC");
  text("banner-text", warning ? warning.text : "");
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
  if (!next) return;
  text("next-title", next.title === "Read back" ? "Read back" : next.station ? `Next call · ${next.station}` : "Next call");
  if (next.text === suggested) return;
  suggested = next.text;
  text("next-text", next.text);
}

$("next").addEventListener("click", () => putInTextBox(suggested));

$("overlay-button").addEventListener("click", async () => {
  const on = $("overlay-button").getAttribute("aria-pressed") !== "true";
  await api("/api/overlay", { visible: on });
  if (status) { status.overlay = on; showStatus(status); }
});

// --- the words while push-to-talk is held (/api/live): shown in the text box until the full text is heard --------

const SAY_PLACEHOLDER = $("say-input").placeholder;
let talking = false;

function showLive(live) {
  talking = live.state !== "idle";
  $("ptt").classList.toggle("talking", talking);
  showPtt();
  $("say-input").placeholder = !talking ? SAY_PLACEHOLDER
    : (live.text || "Listening") + (live.state === "speaking" ? " …" : " (recognising)");
}

async function followLive() {
  let v = -1;
  for (;;) {
    try {
      const live = await (await fetch("/api/live?v=" + v)).json();
      v = live.v;
      showLive(live);
    } catch {
      await new Promise((ok) => setTimeout(ok, 2000));
    }
  }
}
followLive();

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

const VIEWS = { atc: "view-atc", map: "map", phrases: "phrases" };  // view button → the element it shows

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

// --- map: drawn by us on a canvas as a chart, no map tiles, so it works offline -----------------------------------
// Close in it is an airport diagram (taxiways as paved surfaces to their real width, runways filled, holding positions,
// stands); further out an enroute chart over land and sea (Natural Earth, static/world.json: airports with a data
// block and their stations as badges, control zones dashed, Center sectors with their frequency box, the one on COM1
// filled), with the traffic as aircraft symbols: click one for its card. The camera is free: drag or the arrow keys move it, the wheel zooms about the cursor, "Follow"
// brings it back to the aircraft. What lies around the camera comes from /api/map/area (Milestone 11 O4).

const MAP_MIN_NM = 0.4, MAP_MAX_NM = 1500;  // how many nautical miles the map is wide, at most and at least
const GROUND_NM = 2, AIR_NM = 40;  // on the ground and in the air, until the pilot zooms
const CHART_NM = 8;  // narrower than this the airports are drawn as diagrams
let widthNm = AIR_NM;
let zoomChosen = false;  // the pilot zoomed: keep it
let camera = null;  // {lat, lon}: the middle of the map
let follow = true;  // the camera stays on the aircraft until the pilot moves it
let mapData = null;  // airports, route, sectors: the same for the whole flight (/api/map)
let mapMoving = null;  // our aircraft and the traffic: with every status poll
let trafficSeen = "", trafficReadAt = 0;  // the traffic is read from the sim every 3 s: when it last changed
const DEAD_RECKON_S = 4;  // move aircraft on along their heading at most this long after a reading
let mapArea = null, areaBox = null, areaWidth = 0, areaTimer = 0, areaAsked = 0, areaPending = null;  // around the camera
const charts = new Map();  // ident → an airport in full (or null: none), for airports that are not the flight's
let bandShown = "";
let chartTheme = "paper";
try { chartTheme = localStorage.getItem("chart-theme") === "night" ? "night" : "paper"; } catch (error) { /* paper */ }
let world = null;  // land, lakes, borders (static/world.json): loaded once, "loading" meanwhile
const layers = { land: true, sectors: true, traffic: true };  // what the pilot shows: the chips under the map
try { Object.assign(layers, JSON.parse(localStorage.getItem("map-layers") || "{}")); } catch (error) { /* all on */ }
let picked = null;  // the callsign of the traffic whose card is open
let trafficShown = [];  // [{t, x, y}] where each traffic was drawn: what a click hits

function chartFreq(khz) {
  // As charts print them: a 25 kHz channel without its trailing zeros (118.2, 126.85, 123.125), an 8.33 kHz channel
  // with all three digits (121.705, 126.855), which is what a pilot dials
  if (!khz) return "";
  if (khz % 25) return (khz / 1000).toFixed(3);
  const mhz = String(khz / 1000);
  return mhz.includes(".") ? mhz : mhz + ".0";
}

function tokens() {  // the chart's colours (app.css, .map[data-chart]), read once per drawing
  const style = getComputedStyle($("map"));
  const out = {};
  for (const name of ["bg", "ink", "ink-2", "ink-3", "paved", "paved-edge", "apron", "runway", "runway-mark",
                      "tower", "field", "zone", "sector", "you", "water", "border", "traffic"]) {
    out[name] = style.getPropertyValue("--chart-" + name).trim();
  }
  return out;
}

async function loadMap() {
  if (!world) {
    world = "loading";
    fetch("/static/world.json").then((r) => (r.ok ? r.json() : null))
      .then((data) => { world = data; drawMap(); }).catch(() => { world = null; });
  }
  if (!mapData) {
    try { mapData = await api("/api/map"); } catch (error) { /* drawn without it; tried again next time */ }
  }
  drawMap();
}

function nmBetween(a, b) {  // flat, good enough for "which airport is nearest the camera"
  const dLat = (a.lat - b.lat) * 60, dLon = (a.lon - b.lon) * 60 * Math.cos(a.lat * Math.PI / 180);
  return Math.hypot(dLat, dLon);
}

function inside(lat, lon, polygon) {  // ray casting
  let hit = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [la1, lo1] = polygon[i], [la2, lo2] = polygon[j];
    if ((la1 > lat) !== (la2 > lat) && lon < (lo2 - lo1) * (lat - la1) / (la2 - la1) + lo1) hit = !hit;
  }
  return hit;
}

function view(w, h) {  // the box the map shows, in degrees
  const halfLat = h / 2 / (w / widthNm) / 60;
  const halfLon = halfLat * (w / h) / Math.cos(camera.lat * Math.PI / 180);
  return { s: camera.lat - halfLat, n: camera.lat + halfLat, w: camera.lon - halfLon, e: camera.lon + halfLon };
}

function askArea(box) {
  // Ask for a box half a view larger on every side; again once the view leaves it, or after zooming in a lot
  // (the server sends the biggest airports first, so a wide box has left the small fields out)
  const covers = (b, width) => b && box.s >= b.s && box.n <= b.n && box.w >= b.w && box.e <= b.e && widthNm > width / 3;
  if (covers(areaBox, areaWidth) || (areaPending && covers(areaPending, areaPending.width))) return;
  clearTimeout(areaTimer);
  areaTimer = setTimeout(async () => {
    const latPad = (box.n - box.s) / 2, lonPad = (box.e - box.w) / 2;
    const want = { s: Math.max(-90, box.s - latPad), n: Math.min(90, box.n + latPad),
                   w: Math.max(-180, box.w - lonPad), e: Math.min(180, box.e + lonPad) };
    const asked = ++areaAsked, width = widthNm;
    areaPending = { ...want, width };
    try {
      const data = await api(`/api/map/area?s=${want.s.toFixed(4)}&w=${want.w.toFixed(4)}` +
                             `&n=${want.n.toFixed(4)}&e=${want.e.toFixed(4)}`);
      if (asked !== areaAsked) return;  // the camera has moved on: a newer answer is coming
      mapArea = data; areaBox = want; areaWidth = width;
      drawMap();
    } catch (error) { /* asked again when the camera moves */ }
    if (asked === areaAsked) areaPending = null;
  }, 200);
}

function askCharts(box) {  // the diagrams of the airports in view that are not the flight's own
  const own = new Set(((mapData && mapData.airports) || []).map((a) => a.ident));
  for (const a of (mapArea && mapArea.airports) || []) {
    if (own.has(a.ident) || charts.has(a.ident)) continue;
    if (a.lat < box.s || a.lat > box.n || a.lon < box.w || a.lon > box.e) continue;
    charts.set(a.ident, null);  // asked: not again
    api("/api/map/airport?ident=" + encodeURIComponent(a.ident))
      .then((chart) => { charts.set(a.ident, chart); drawMap(); })
      .catch(() => charts.delete(a.ident));
  }
}

function drawMap() {
  const canvas = $("map-canvas");
  const box = $("map");
  if (box.hidden || !box.clientWidth) return;
  const ratio = window.devicePixelRatio || 1;
  const w = box.clientWidth, h = box.clientHeight;
  if (canvas.width !== w * ratio || canvas.height !== h * ratio) {
    canvas.width = w * ratio; canvas.height = h * ratio;
    canvas.style.width = w + "px"; canvas.style.height = h + "px";
  }
  const g = canvas.getContext("2d");
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  const c = tokens();
  g.fillStyle = c.bg;
  g.fillRect(0, 0, w, h);

  const own = mapMoving && mapMoving.own;
  const first = mapData && mapData.airports[0];
  if (follow && (own || first)) camera = { lat: (own || first).lat, lon: (own || first).lon };
  $("map-follow").hidden = follow || !own;
  if (!camera) return;
  if (!zoomChosen) widthNm = own && !own.on_ground ? AIR_NM : GROUND_NM;
  const bounds = view(w, h);
  askArea(bounds);
  const chart = widthNm <= CHART_NM;
  if (chart) askCharts(bounds);

  // Flat projection around the camera: 1 degree of latitude = 60 NM, longitude shrinks with cos(latitude)
  const perNm = w / widthNm;
  const cosLat = Math.cos(camera.lat * Math.PI / 180);
  const xy = (lat, lon) => [w / 2 + (lon - camera.lon) * cosLat * 60 * perNm, h / 2 - (lat - camera.lat) * 60 * perNm];
  const seen = (x, y, margin = 40) => x > -margin && y > -margin && x < w + margin && y < h + margin;
  const band = $("map-band");
  const placed = [[0, 0, w, band.hidden ? 0 : band.offsetHeight + 4],  // labels keep clear of the band,
                  [0, h - 36, 200, h], [w - 210, h - 100, w, h]];       // the scale bar and the buttons
  const m = { g, c, w, h, xy, seen, perNm, placed };
  g.textBaseline = "middle";
  g.lineJoin = "round";

  const flight = (mapData && mapData.airports) || [];
  const sectors = (mapArea && mapArea.sectors) || (mapData && mapData.sectors) || [];
  if (layers.land && !chart) drawWorld(m, bounds);
  if (layers.sectors && widthNm >= 10) drawSectors(m, sectors, own);
  if (mapArea && widthNm >= 4) drawZones(m, mapArea.zones);
  if (chart) {
    const diagrams = [...flight, ...[...charts.values()].filter(Boolean)];
    for (const a of diagrams) drawDiagram(m, a);
  }
  if (!chart) drawRoute(m);
  if (!chart || widthNm > 3) drawAirports(m, flight, chart);
  drawTaxiRoute(m);
  trafficShown = [];
  if (layers.traffic) drawTraffic(m, cosLat);
  if (own) { const [x, y] = xy(own.lat, own.lon); plane(g, x, y, own.heading, 13, c.you, c.bg); }
  drawScale(m);
  showBand(flight, sectors);
  showCard();
}

function drawWorld(m, box) {
  // The sea is the background, the land is the chart's paper, lakes are sea again, borders a fine rule. A line is
  // only followed where it moves a pixel: from afar most of a coast's points fall on the same few pixels
  if (!world || world === "loading") return;
  const { g, c } = m;
  const lines = (items, close) => {
    g.beginPath();
    for (const { box: [s, w, n, e], line } of items) {
      if (n < box.s || s > box.n || e < box.w || w > box.e) continue;
      let lastX = null, lastY = null;
      for (let i = 0; i < line.length; i += 2) {
        const [x, y] = m.xy(line[i], line[i + 1]);
        if (lastX === null) g.moveTo(x, y);
        else if (Math.abs(x - lastX) + Math.abs(y - lastY) >= 1 || i === line.length - 2) g.lineTo(x, y);
        else continue;
        lastX = x; lastY = y;
      }
      if (close) g.closePath();
    }
  };
  g.fillStyle = c.water;
  g.fillRect(0, 0, m.w, m.h);
  lines(world.land, true);
  g.fillStyle = c.bg;
  g.fill("evenodd");
  lines(world.lakes, true);
  g.fillStyle = c.water;
  g.fill("evenodd");
  lines(world.borders, false);
  g.strokeStyle = c.border;
  g.lineWidth = 1;
  g.setLineDash([]);
  g.stroke();
}

function path(m, points) {  // a polyline through [lat, lon] points
  points.forEach(([lat, lon], i) => { const [x, y] = m.xy(lat, lon); i ? m.g.lineTo(x, y) : m.g.moveTo(x, y); });
}

function free(m, x, y, width, height) {  // a label's box does not touch one already placed: then it is placed
  const box = [x - 2, y - 2, x + width + 2, y + height + 2];
  if (m.placed.some((p) => box[0] < p[2] && box[2] > p[0] && box[1] < p[3] && box[3] > p[1])) return false;
  m.placed.push(box);
  return true;
}

function drawSectors(m, sectors, own) {
  // The boundary as a thin rule; name and frequency in an outlined box, as an enroute chart's frequency box. The
  // sector the aircraft is in is tinted; the one on COM1 filled in the stations' colour, its rule bolder
  const { g, c } = m;
  const com1 = status && status.com1_khz;
  for (const s of sectors) {
    const tuned = com1 && s.khz === com1;
    if (!tuned && !(own && inside(own.lat, own.lon, s.polygon))) continue;
    g.beginPath(); path(m, s.polygon); g.closePath();
    g.globalAlpha = tuned ? 0.14 : 0.07;
    g.fillStyle = tuned ? c.tower : c.sector;
    g.fill();
    g.globalAlpha = 1;
  }
  g.lineWidth = 1;
  g.setLineDash([]);
  for (const s of sectors) {
    const tuned = com1 && s.khz === com1;
    g.strokeStyle = tuned ? c.tower : c.sector;
    g.lineWidth = tuned ? 2 : 1;
    g.beginPath(); path(m, s.polygon); g.closePath(); g.stroke();
  }
  g.strokeStyle = c.sector;
  g.lineWidth = 1;
  const labelled = new Set();
  for (const s of sectors) {
    const key = s.name + s.khz;
    if (labelled.has(key)) continue;
    const [x, y] = m.xy(s.polygon.reduce((a, p) => a + p[0], 0) / s.polygon.length,
                        s.polygon.reduce((a, p) => a + p[1], 0) / s.polygon.length);
    if (x < 40 || y < 60 || x > m.w - 40 || y > m.h - 40) continue;
    const lines = [s.name.toUpperCase(), chartFreq(s.khz)].filter(Boolean);
    g.font = "10px B612, sans-serif";
    const width = Math.max(...lines.map((l) => g.measureText(l).width)) + 12, height = lines.length * 13 + 6;
    if (!free(m, x - width / 2, y - height / 2, width, height)) continue;
    labelled.add(key);
    g.strokeStyle = com1 && s.khz === com1 ? c.tower : c.sector;
    g.fillStyle = c.bg;
    g.fillRect(x - width / 2, y - height / 2, width, height);
    g.strokeRect(x - width / 2 + 0.5, y - height / 2 + 0.5, width - 1, height - 1);
    g.textAlign = "center";
    g.fillStyle = c["ink-2"];
    g.fillText(lines[0], x, y - height / 2 + 9.5);
    if (lines[1]) { g.font = "11px B612, sans-serif"; g.fillStyle = c.ink; g.fillText(lines[1], x, y + 6); }
    g.textAlign = "left";
  }
}

function drawZones(m, zones) {  // control zones: dashed, in the colour of a towered field, the name at the top
  const { g, c } = m;
  g.strokeStyle = c.zone;
  g.lineWidth = 1.5;
  g.setLineDash([7, 4]);
  const drawn = new Set();
  g.beginPath();
  for (const z of zones) {
    z.polygon.forEach((p, i) => {
      const q = z.polygon[(i + 1) % z.polygon.length];
      const key = [p, q].map(([lat, lon]) => lat.toFixed(4) + "," + lon.toFixed(4)).sort().join(" ");
      if (drawn.has(key)) return;
      drawn.add(key);
      g.moveTo(...m.xy(...p)); g.lineTo(...m.xy(...q));
    });
  }
  g.stroke();
  g.setLineDash([]);
  if (widthNm > 120) return;
  g.font = "10px B612, sans-serif";
  g.fillStyle = c.zone;
  for (const z of zones) {
    const top = z.polygon.reduce((a, p) => (p[0] > a[0] ? p : a));
    const [x, y] = m.xy(top[0], top[1]);
    const label = z.name.toUpperCase() + (z.ceiling_ft ? "  " + z.ceiling_ft : "");
    const width = g.measureText(label).width;
    if (m.seen(x, y, 0) && free(m, x - width / 2, y - 18, width, 12)) {
      g.textAlign = "center"; g.fillText(label, x, y - 12); g.textAlign = "left";
    }
  }
}

function drawDiagram(m, a) {
  const { g, c, xy, perNm } = m;
  const [ax, ay] = xy(a.lat, a.lon);
  if (!m.seen(ax, ay, perNm * 4)) return;  // an airport is at most a few miles across
  const px = (metres) => metres / 1852 * perNm;
  // The paved surface in two passes, the edge then the fill, so crossing taxiways merge into one outline
  g.lineCap = "round";
  for (const [colour, extra] of [[c["paved-edge"], 2], [c.paved, 0]]) {
    g.strokeStyle = colour;
    g.fillStyle = colour === c.paved ? c.apron : colour;
    for (const apron of a.aprons || []) {
      g.beginPath(); path(m, apron); g.closePath();
      if (extra) { g.lineWidth = extra; g.stroke(); } else g.fill();
    }
    for (const [la1, lo1, la2, lo2, width] of a.surfaces || []) {
      g.lineWidth = Math.max(1.5, px(width)) + extra;
      g.beginPath(); g.moveTo(...xy(la1, lo1)); g.lineTo(...xy(la2, lo2)); g.stroke();
    }
  }
  g.lineCap = "butt";
  drawRunways(m, a);
  // Holding positions: a double bar across the taxiway
  if (widthNm <= 4) {
    g.strokeStyle = c.ink;
    g.lineWidth = 1.5;
    const half = Math.max(5, px(14));
    for (const [lat, lon, bearing] of a.holds || []) {
      const [x, y] = xy(lat, lon);
      if (!m.seen(x, y, 0)) continue;
      const t = bearing * Math.PI / 180, ux = Math.sin(t), uy = -Math.cos(t);  // along the taxiway
      for (const off of [-1.5, 1.5]) {
        g.beginPath();
        g.moveTo(x + ux * off - uy * half, y + uy * off + ux * half);
        g.lineTo(x + ux * off + uy * half, y + uy * off - ux * half);
        g.stroke();
      }
    }
  }
  // Taxiway names on the taxiway, one every ~160 px along it, never on top of another label
  g.font = "11px B612, sans-serif";
  g.textAlign = "center";
  const named = [];
  for (const [la1, lo1, la2, lo2, name, toStand] of a.taxiways || []) {
    if (!name || toStand) continue;
    const [x, y] = xy((la1 + la2) / 2, (lo1 + lo2) / 2);
    if (!m.seen(x, y, -8)) continue;
    if (named.some((p) => p.name === name && Math.hypot(p.x - x, p.y - y) < 160)) continue;
    const width = g.measureText(name).width + 6;
    if (!free(m, x - width / 2, y - 8, width, 16)) continue;
    named.push({ name, x, y });
    g.fillStyle = c.bg;
    g.fillRect(x - width / 2, y - 7, width, 14);
    g.fillStyle = c.ink;
    g.fillText(name, x, y + 0.5);
  }
  // Stands: their numbers, close in only
  if (widthNm <= 1.6) {
    g.font = "9px 'B612 Mono', monospace";
    g.fillStyle = c["ink-2"];
    for (const p of a.parking || []) {
      const [x, y] = xy(p.lat, p.lon);
      if (!m.seen(x, y, -4)) continue;
      const name = p.name.replace(/^\D+\s(?=\d)/, "");  // "G 51A" → "51A", as a chart numbers its stands
      const width = g.measureText(name).width;
      if (free(m, x - width / 2, y - 5, width, 10)) g.fillText(name, x, y);
    }
  }
  g.textAlign = "left";
}

function drawRunways(m, a) {
  // Filled to scale, a dashed centreline, the number and magnetic heading beyond each end, the length alongside
  const { g, c, xy, perNm } = m;
  for (const r of a.runways) {
    const [[la1, lo1], [la2, lo2]] = r.ends;
    const [x1, y1] = xy(la1, lo1), [x2, y2] = xy(la2, lo2);
    const len = Math.hypot(x2 - x1, y2 - y1) || 1, ux = (x2 - x1) / len, uy = (y2 - y1) / len;
    const width = Math.max(4, r.width_m / 1852 * perNm);
    g.strokeStyle = c.runway;
    g.lineWidth = width;
    g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
    if (width >= 7) {
      g.strokeStyle = c["runway-mark"];
      g.lineWidth = 1;
      g.setLineDash([8, 6]);
      g.beginPath(); g.moveTo(x1 + ux * 10, y1 + uy * 10); g.lineTo(x2 - ux * 10, y2 - uy * 10); g.stroke();
      g.setLineDash([]);
      for (const [x, y, s] of [[x1, y1, 1], [x2, y2, -1]]) {  // threshold bars
        g.lineWidth = 2;
        g.beginPath();
        g.moveTo(x + ux * s * 3 - uy * width * 0.35, y + uy * s * 3 + ux * width * 0.35);
        g.lineTo(x + ux * s * 3 + uy * width * 0.35, y + uy * s * 3 - ux * width * 0.35);
        g.stroke();
      }
    }
    g.textAlign = "center";
    r.ends.forEach((_, i) => {
      const s = i ? 1 : -1, [ex, ey] = i ? [x2, y2] : [x1, y1];
      const tx = ex + ux * s * 18, ty = ey + uy * s * 18;
      g.font = "12px B612, sans-serif";
      g.fillStyle = c.ink;
      if (!free(m, tx - 14, ty - 8, 28, 26)) return;
      g.fillText(r.names[i], tx, ty);
      if (r.headings_mag) {
        g.font = "10px 'B612 Mono', monospace";
        g.fillStyle = c["ink-2"];
        g.fillText(String(r.headings_mag[i]).padStart(3, "0") + "°", tx, ty + 12);
      }
    });
    if (r.length_ft && len > 220) {  // 10,666' 3251 m along the runway, just beside it
      const label = r.length_ft.toLocaleString("en-US") + "'  " + Math.round(r.length_ft * 0.3048) + " m";
      let angle = Math.atan2(uy, ux);
      if (angle > Math.PI / 2 || angle < -Math.PI / 2) angle += Math.PI;
      g.save();
      g.translate((x1 + x2) / 2 - Math.sin(angle) * (width / 2 + 9), (y1 + y2) / 2 + Math.cos(angle) * (width / 2 + 9));
      g.rotate(angle);
      g.font = "10px 'B612 Mono', monospace";
      g.fillStyle = c["ink-2"];
      g.fillText(label, 0, 0);
      g.restore();
    }
    g.textAlign = "left";
  }
}

function drawRoute(m) {  // SimBrief's waypoints, else straight from origin to destination; waypoints as triangles
  if (!mapData || !mapData.airports.length) return;
  const { g, c, xy } = m;
  const [from, to] = [mapData.airports[0], mapData.airports[mapData.airports.length - 1]];
  const points = [from, ...mapData.route, ...(to && to !== from ? [to] : [])].map((p) => [p.lat, p.lon]);
  g.strokeStyle = c["ink-2"];
  g.lineWidth = 1.5;
  g.beginPath(); path(m, points); g.stroke();
  if (widthNm > 300) return;
  g.font = "10px 'B612 Mono', monospace";
  for (const p of mapData.route) {
    const [x, y] = xy(p.lat, p.lon);
    if (!m.seen(x, y, 0)) continue;
    g.fillStyle = c.bg;
    g.beginPath(); g.moveTo(x, y - 5); g.lineTo(x + 4.5, y + 3.5); g.lineTo(x - 4.5, y + 3.5); g.closePath();
    g.fill(); g.lineWidth = 1.2; g.stroke();
    const width = g.measureText(p.ident).width;
    if (free(m, x + 7, y - 6, width, 12)) { g.fillStyle = c.ink; g.fillText(p.ident, x + 7, y); }
  }
}

function drawAirports(m, flight, chart) {
  // An enroute chart's airport: towered fields in blue, the others in brown. From afar a ring; nearer the runway
  // pattern; and a data block: NAME (ICAO), the tower and ATIS frequencies, elevation and longest runway in 100 ft
  const { g, c, xy } = m;
  const known = new Map();
  for (const a of (mapArea && mapArea.airports) || []) known.set(a.ident, a);
  for (const a of flight) {
    if (!known.has(a.ident)) {
      known.set(a.ident, { ...a, controlled: a.frequencies.some((f) => ["TWR", "GND", "APP"].includes(f.label)),
                           runways: a.runways.map((r) => [...r.ends[0], ...r.ends[1]]),
                           longest_ft: Math.max(0, ...a.runways.map((r) => r.length_ft || 0)) });
    }
  }
  const mine = new Set(flight.map((a) => a.ident));
  const order = [...known.values()].sort((p, q) => mine.has(q.ident) - mine.has(p.ident));
  for (const a of order) {
    const [x, y] = xy(a.lat, a.lon);
    if (!m.seen(x, y)) continue;
    const colour = a.controlled ? c.tower : c.field;
    g.strokeStyle = colour; g.fillStyle = colour;
    if (!chart) {
      if (widthNm <= 60 && a.runways.length) {
        g.lineWidth = 3;
        g.lineCap = "butt";
        for (const [la1, lo1, la2, lo2] of a.runways) {
          const [x1, y1] = xy(la1, lo1), [x2, y2] = xy(la2, lo2);
          const len = Math.hypot(x2 - x1, y2 - y1) || 1, k = len < 8 ? 4 / len : 0;  // at least 8 px long
          g.beginPath(); g.moveTo(x1 - (x2 - x1) * k, y1 - (y2 - y1) * k); g.lineTo(x2 + (x2 - x1) * k, y2 + (y2 - y1) * k);
          g.stroke();
        }
      } else {
        g.lineWidth = 1.5;
        g.beginPath(); g.arc(x, y, a.controlled ? 5 : 3.5, 0, Math.PI * 2); g.stroke();
      }
    }
    const big = a.controlled || (a.longest_ft || 0) >= 5000;
    const block = mine.has(a.ident) || (widthNm <= 150 && a.controlled) || widthNm <= 50;
    const lines = [];
    if (block || widthNm > 150 && big) lines.push(block ? `${a.name.toUpperCase()} (${a.ident})` : a.ident);
    if (block) {
      const pick = (label) => a.frequencies.find((f) => f.label === label);
      const main = a.controlled ? pick("TWR") : pick("INFO") || pick("UNICOM") || pick("MULTICOM");
      const atis = pick("ATIS");
      const radio = [main && (a.controlled ? "CT " : main.label + " ") + chartFreq(main.khz),
                     atis && "ATIS " + chartFreq(atis.khz)].filter(Boolean).join("  ");
      if (radio) lines.push(radio);
      lines.push(`${a.elevation_ft}  ${Math.round((a.longest_ft || 0) / 100)}`);
    }
    if (!lines.length) continue;
    g.font = "11px B612, sans-serif";
    const badges = stations(a), first = g.measureText(lines[0]).width + (badges.length ? 4 + badges.length * 13 : 0);
    const width = Math.max(first, ...lines.slice(1).map((l) => g.measureText(l).width)), height = lines.length * 13;
    const lx = x + 10, ly = y - 8 - height / 2;
    if (!free(m, lx, ly, width, height) && !mine.has(a.ident)) continue;
    lines.forEach((line, i) => {
      g.font = i ? "10px B612, sans-serif" : "11px B612, sans-serif";
      g.fillStyle = i ? c.ink : colour;
      g.fillText(line, lx, ly + 6 + i * 13);
    });
    g.font = "11px B612, sans-serif";
    let bx = lx + g.measureText(lines[0]).width + 4;
    g.font = "bold 9px B612, sans-serif";
    g.textAlign = "center";
    for (const b of badges) {  // filled: the station tuned on COM1
      g.fillStyle = b.tuned ? c.you : colour;
      g.globalAlpha = b.tuned ? 1 : 0.85;
      g.fillRect(bx, ly, 11, 11);
      g.globalAlpha = 1;
      g.fillStyle = c.bg;
      g.fillText(b.letter, bx + 5.5, ly + 6);
      bx += 13;
    }
    g.textAlign = "left";
  }
}

// Which stations an airport has, as on VATSIM maps: Delivery, Ground, Tower, Approach (ATIS left out)
const BADGES = [["D", ["DEL", "CLD"]], ["G", ["GND", "APRON", "RAMP"]], ["T", ["TWR"]], ["A", ["APP", "DEP"]]];

function stations(a) {
  const tuned = status && status.com1_khz;
  return BADGES.map(([letter, labels]) => {
    const found = (a.frequencies || []).filter((f) => labels.some((l) => (f.label || "").startsWith(l)));
    return found.length ? { letter, tuned: found.some((f) => f.khz === tuned) } : null;
  }).filter(Boolean);
}

function drawTaxiRoute(m) {  // the taxi route ATC gave: the colour of "you", on top of the taxiways
  const route = (mapMoving && mapMoving.taxi_route) || [];
  if (route.length < 2 || widthNm > 10) return;
  m.g.strokeStyle = m.c.you;
  m.g.lineWidth = 3;
  m.g.lineCap = "round";
  m.g.beginPath(); path(m, route); m.g.stroke();
  m.g.lineCap = "butt";
}

function drawTraffic(m, cosLat) {
  // Aircraft symbols with the callsign and level (on the ground only when zoomed in close, and greyed); the one whose
  // card is open ringed in amber
  const { g, c, xy } = m;
  const since = Math.min((performance.now() - trafficReadAt) / 1000, DEAD_RECKON_S);
  g.font = "10px 'B612 Mono', monospace";
  for (const t of (mapMoving && mapMoving.traffic) || []) {
    if (t.on_ground && widthNm > 10) continue;
    const nm = (t.gs || 0) * since / 3600, rad = t.heading * Math.PI / 180;  // where it is now, roughly
    const [x, y] = xy(t.lat + nm * Math.cos(rad) / 60, t.lon + nm * Math.sin(rad) / 60 / cosLat);
    if (!m.seen(x, y)) continue;
    const colour = t.on_ground ? c["ink-3"] : c.traffic;
    if (t.callsign === picked) {
      g.strokeStyle = c.you; g.lineWidth = 2;
      g.beginPath(); g.arc(x, y, 13, 0, Math.PI * 2); g.stroke();
    }
    plane(g, x, y, t.heading, t.on_ground ? 8 : 10, colour, c.bg);
    g.fillStyle = colour;
    g.fillText(t.callsign + (t.on_ground ? "" : " " + level(t.alt_ft)), x + 13, y);
    trafficShown.push({ t, x, y });
  }
}

function showCard() {  // the card of the traffic clicked on the map, kept up to date; hidden while the aircraft
  const card = $("map-card");  // is missing (back when it is: a traffic list can miss one for a moment)
  const t = picked && ((mapMoving && mapMoving.traffic) || []).find((a) => a.callsign === picked);
  if (!t) { card.hidden = true; return; }
  card.hidden = false;
  text("card-callsign", t.callsign);
  text("card-type", [t.type, t.reg].filter(Boolean).join(" · ") || "unknown type");
  text("card-alt", t.on_ground ? "on the ground" : level(t.alt_ft));
  text("card-gs", Math.round(t.gs || 0) + " KT");
  text("card-hdg", String(Math.round(t.heading) % 360 || 360).padStart(3, "0") + "°");
}

function pickAt(x, y) {  // a click on the map: the nearest traffic within reach opens its card, elsewhere closes it
  let best = null, reach = 16;
  for (const s of trafficShown) {
    const d = Math.hypot(s.x - x, s.y - y);
    if (d < reach) { reach = d; best = s.t; }
  }
  picked = best && best.callsign;
  drawMap();
}

function drawScale(m) {  // a chart's scale bar, bottom left: a round number of miles, 60 to 160 px long
  const { g, c, h, perNm } = m;
  const steps = [100 / 1852, 200 / 1852, 500 / 1852, 1, 2, 5, 10, 20, 50, 100, 200, 500];
  const nm = steps.find((s) => s * perNm >= 60) || 500;
  const length = nm * perNm, x = 16, y = h - 20;
  g.strokeStyle = c.ink;
  g.lineWidth = 1.5;
  g.beginPath(); g.moveTo(x, y - 4); g.lineTo(x, y); g.lineTo(x + length, y); g.lineTo(x + length, y - 4); g.stroke();
  g.font = "10px 'B612 Mono', monospace";
  g.fillStyle = c.ink;
  g.fillText(nm < 1 ? Math.round(nm * 1852) + " M" : nm + " NM", x + length + 6, y - 1);
}

function showBand(flight, sectors) {
  // The frequencies near the camera, as along the top of an airport chart: the nearest airport's, in the order
  // they are used, then the Center sector the camera is in
  let nearest = null, best = Math.max(12, widthNm * 0.75);
  for (const a of [...flight, ...((mapArea && mapArea.airports) || [])]) {
    const d = nmBetween(a, camera) - (flight.includes(a) ? 0.5 : 0);  // the flight's own wins a tie
    if (d < best && a.frequencies.length) { best = d; nearest = a; }
  }
  const above = [];
  for (const s of sectors) {
    if (s.khz && !above.some((o) => o.khz === s.khz) && inside(camera.lat, camera.lon, s.polygon)) above.push(s);
  }
  const key = JSON.stringify([nearest && nearest.ident, nearest && nearest.frequencies, above.map((s) => s.khz)]);
  if (key === bandShown) return;
  bandShown = key;
  const band = $("map-band");
  band.replaceChildren();
  band.hidden = !nearest && !above.length;
  if (nearest) {
    const place = element("div", "band-place");
    place.append(element("span", "band-ident num", nearest.ident), element("span", "band-name", nearest.name));
    band.append(place);
    for (const f of nearest.frequencies.slice(0, 10)) band.append(bandCell(f.label, f.khz, f.station));
  }
  for (const s of above.slice(0, 2)) band.append(bandCell(s.name.toUpperCase(), s.khz, s.name));
}

function bandCell(label, khz, title) {
  const cell = element("div", "band-cell");
  cell.title = title || label;
  const value = element("span", "band-freq num");
  const [whole, fraction] = chartFreq(khz).split(".");
  value.append(whole, element("span", "sep", "."), fraction);
  cell.append(element("span", "band-label", label), value);
  return cell;
}

// An airliner seen from above, nose up, half of it (x >= 0) from the nose to the tail; mirrored for the other half
const PLANE_HALF = [[0, -1], [0.09, -0.88], [0.1, -0.3], [0.95, 0.14], [0.95, 0.28], [0.1, 0.08], [0.08, 0.6],
                    [0.36, 0.8], [0.36, 0.92], [0, 0.84]];
const PLANE = new Path2D();
[...PLANE_HALF, ...PLANE_HALF.slice(1, -1).reverse().map(([x, y]) => [-x, y])]
  .forEach(([x, y], i) => (i ? PLANE.lineTo(x, y) : PLANE.moveTo(x, y)));
PLANE.closePath();

function plane(g, x, y, heading, size, fill, edge) {  // the aircraft symbol along the heading (0 = north, up)
  g.save();
  g.translate(x, y);
  g.rotate(heading * Math.PI / 180);
  g.scale(size, size);
  if (edge) { g.strokeStyle = edge; g.lineWidth = 3 / size; g.stroke(PLANE); }
  g.fillStyle = fill;
  g.fill(PLANE);
  g.restore();
}

function zoomBy(factor, x, y) {  // zoom about a point on the map (the cursor), the middle if none
  const box = $("map");
  if (!camera || !box.clientWidth) return;
  const w = box.clientWidth, h = box.clientHeight;
  const next = Math.max(MAP_MIN_NM, Math.min(MAP_MAX_NM, widthNm * factor));
  if (x !== undefined && !follow) {  // the point under the cursor stays under it (following: the aircraft does)
    const perNm = w / widthNm, nextPerNm = w / next, cosLat = Math.cos(camera.lat * Math.PI / 180);
    const dx = x - w / 2, dy = y - h / 2;
    camera = { lat: camera.lat - dy / 60 * (1 / perNm - 1 / nextPerNm),
               lon: camera.lon + dx / 60 / cosLat * (1 / perNm - 1 / nextPerNm) };
  }
  widthNm = next;
  zoomChosen = true;
  drawMap();
}

function pan(dx, dy) {  // move the camera by pixels on the map
  const box = $("map");
  if (!camera) return;
  const perNm = box.clientWidth / widthNm, cosLat = Math.cos(camera.lat * Math.PI / 180);
  camera = { lat: Math.max(-85, Math.min(85, camera.lat + dy / perNm / 60)),
             lon: ((camera.lon - dx / perNm / 60 / cosLat + 540) % 360) - 180 };
  follow = false;
  drawMap();
}

function setChartTheme(theme) {
  chartTheme = theme;
  $("map").dataset.chart = theme;
  $("map-theme").setAttribute("aria-pressed", String(theme === "night"));
  try { localStorage.setItem("chart-theme", theme); } catch (error) { /* only for this window */ }
  drawMap();
}

$("zoom-in").addEventListener("click", () => zoomBy(0.5));
$("zoom-out").addEventListener("click", () => zoomBy(2));
$("map-follow").addEventListener("click", () => { follow = true; drawMap(); });
$("map-theme").addEventListener("click", () => setChartTheme(chartTheme === "night" ? "paper" : "night"));
for (const chip of document.querySelectorAll(".map-tools .layer")) {  // the layers shown, kept for the next start
  const name = chip.dataset.layer;
  chip.setAttribute("aria-pressed", String(layers[name]));
  chip.addEventListener("click", () => {
    layers[name] = !layers[name];
    chip.setAttribute("aria-pressed", String(layers[name]));
    try { localStorage.setItem("map-layers", JSON.stringify(layers)); } catch (error) { /* only for this window */ }
    drawMap();
  });
}
setChartTheme(chartTheme);
$("map-canvas").addEventListener("wheel", (event) => {
  event.preventDefault();
  const r = event.currentTarget.getBoundingClientRect();
  zoomBy(event.deltaY > 0 ? 1.25 : 0.8, event.clientX - r.left, event.clientY - r.top);
}, { passive: false });
let dragFrom = null, dragged = 0;  // dragged: pixels moved since the button went down (little: a click)
$("map-canvas").addEventListener("pointerdown", (event) => {
  dragFrom = [event.clientX, event.clientY];
  dragged = 0;
  event.currentTarget.setPointerCapture(event.pointerId);
  $("map").focus({ preventScroll: true });
});
$("map-canvas").addEventListener("pointermove", (event) => {
  if (!dragFrom) return;
  const dx = event.clientX - dragFrom[0], dy = event.clientY - dragFrom[1];
  if (!dx && !dy) return;
  dragged = Math.max(dragged, Math.abs(dx) + Math.abs(dy));
  if (dragged < 5) return;  // still a click; once a drag, the map follows from where the button went down
  dragFrom = [event.clientX, event.clientY];
  pan(dx, dy);
});
$("map-canvas").addEventListener("pointerup", (event) => {
  if (dragFrom && dragged < 5) {
    const r = event.currentTarget.getBoundingClientRect();
    pickAt(event.clientX - r.left, event.clientY - r.top);
  }
  dragFrom = null;
});
$("map-canvas").addEventListener("pointercancel", () => { dragFrom = null; });
$("card-close").addEventListener("click", () => { picked = null; drawMap(); });
$("map").addEventListener("keydown", (event) => {
  const step = $("map").clientWidth / 6;
  const moves = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
  if (moves[event.key]) pan(...moves[event.key]);
  else if (event.key === "+" || event.key === "=") zoomBy(0.5);
  else if (event.key === "-") zoomBy(2);
  else return;
  event.preventDefault();
});
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
  // A script: who, on which frequency, when; then what was said
  const meta = element("div", "meta");
  meta.append(label, frequency, element("span", "time", utc(e.time)));
  li.append(meta, element("div", "msg", e.text));
  return li;
}

let lastRadioTime = 0, lastRadioKind = "";  // a pause on the radio starts a new exchange: more air above it
const MINE = new Set(["pilot", "copilot"]);

function markExchange(li, e) {
  if (!RADIO.has(e.kind)) return;
  const answer = !MINE.has(e.kind) && MINE.has(lastRadioKind);  // ATC answering us
  const readback = MINE.has(e.kind) && status && status.suggestion && status.suggestion.title === "Read back";
  if (lastRadioTime && e.time - lastRadioTime > 15 && !answer && !readback) li.classList.add("gap");
  lastRadioTime = e.time;
  lastRadioKind = e.kind;
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
  if (e.kind === "readback") {  // a quiet line under the pilot's own transmission instead of a row of its own
    const mine = [...log.querySelectorAll("li.pilot, li.copilot")].pop();
    if (mine && !mine.querySelector(".meta.ok")) {
      mine.classList.remove("gap");  // a readback belongs to the exchange it answers
      mine.append(element("div", "meta ok", " Readback correct"));
      toEnd();
      return;
    }
  }
  const li = row(e);
  markExchange(li, e);
  log.append(li);
  keepAtEnd.observe(li);
  if (isWarning(e)) { lastWarning = { text: e.text, time: e.time }; showBanner(); }
  toEnd();
}

function clearLog(first) {
  keepAtEnd.disconnect();
  keepAtEnd.observe(log);
  log.replaceChildren(row(first));
  stickToEnd = true;
  lastWarning = null;
  lastRadioTime = 0;
  lastRadioKind = "";
}

function connect(from) {
  const stream = new EventSource("/api/events?from=" + from);
  const link = $("link");
  stream.onopen = () => { link.className = "link ok"; text("link-text", "Connected"); };
  stream.onerror = () => { link.className = "link down"; text("link-text", "No link"); };
  stream.onmessage = (message) => {
    const e = JSON.parse(message.data);
    if (e.kind === "system" && e.text.startsWith("session started")) { clearLog(e); mapData = null; follow = true; zoomChosen = false; }
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
    cruise: form.cruise.value, route: form.route.value, rules: form.rules.value,
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
  text("b-meta", [b.aircraft, b.rules, b.cruise_ft ? level(b.cruise_ft) : "", b.source].filter(Boolean).join(" · "));
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
