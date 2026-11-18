// The overlay over the sim (atc/app/overlay.py): the status every second, the last call from ATC from the event
// stream, and the words while push-to-talk is held from /api/live.
"use strict";

const $ = (id) => document.getElementById(id);
let suggestion = "—";
let hearing = false;

function freq(khz) {
  return khz ? (khz / 1000).toFixed(3) : "---.---";
}

function text(id, value) {
  if ($(id).textContent !== value) $(id).textContent = value;
}

function setFreq(id, value) {
  // In a monospace font the dot is a full character wide and reads like a gap ("121. 705"): narrow it, as in app.js
  if ($(id).textContent === value) return;
  const at = value.lastIndexOf(".");
  const dot = document.createElement("span");
  dot.className = "sep";
  dot.textContent = ".";
  $(id).replaceChildren(value.slice(0, at), dot, value.slice(at + 1));
}

function showStatus(s) {
  if (!s) return;
  setFreq("com", freq(s.com1_khz));
  text("tuned", s.tuned || (s.on_frequency === false ? "no station" : ""));
  $("next").hidden = !s.next;
  if (s.next) setFreq("next", "→ " + freq(s.next.khz));
  $("next").title = s.next ? s.next.name : "";
  text("cleared", s.cleared || "-");
  text("squawk", s.squawk || "----");
  text("qnh", (s.airport && s.airport.qnh) ? String(s.airport.qnh) : "----");
  suggestion = s.suggestion ? s.suggestion.text : "—";
  if (!hearing) text("say", suggestion);
}

async function pollStatus() {
  try {
    showStatus(await (await fetch("/api/status")).json());
  } catch { /* the app is closing */ }
  setTimeout(pollStatus, 1000);
}

function showLive(live) {
  hearing = live.state !== "idle";
  $("say-row").classList.toggle("hearing", hearing);
  text("say-key", hearing ? "Heard" : "Say");
  text("say", hearing ? (live.text || "…") + (live.state === "speaking" ? " …" : "") : suggestion);
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

async function followEvents() {
  const state = await (await fetch("/api/state")).json();
  const stream = new EventSource("/api/events?from=" + (state.session_from || 0));
  stream.onmessage = (message) => {
    const e = JSON.parse(message.data);
    if (e.kind === "system" && e.text.startsWith("session started")) text("atc", "—");
    if (e.kind === "atc") text("atc", e.text);
  };
}

$("close").addEventListener("mousedown", (e) => e.stopPropagation());  // a click, not a drag of the window
$("close").addEventListener("click", () => fetch("/api/overlay", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ visible: false }) }));

pollStatus();
followLive();
followEvents();
