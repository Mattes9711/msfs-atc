# ATC for MSFS2020 — Plan

A voice ATC for Microsoft Flight Simulator 2020, written in Python on Windows, in the spirit of BeyondATC / SayIntentions.

## Ground rules

- **ATC decisions are deterministic.** The controller never reads the real clock or unseeded randomness; time and randomness are injected.
- **The LLM only turns spoken English into a structured intent.** It never makes or invents clearances.
- **Phraseology is English, ICAO style**, digits spoken one by one ("one one eight decimal seven", "niner", "flight level one two zero").
- **`--text --nosim` always works**: no sim, no mic, no speakers, no internet, no LLM required.
- Everything external (sim, mic, speakers, internet, LLM, clock) sits behind a small interface with a fake implementation.

## Decisions

| Topic | Decision | Later version |
|---|---|---|
| Structure | `atc/` package split by responsibility, `tests/` with pytest | — |
| Airport data | `AirportData` interface: hand-made JSON (tests) + Little Navmap SQLite | SimConnect Facilities API |
| Airport detection | On ground at start: nearest airport within ~3 km; `--airport` in `--nosim` | — |
| Missing positions | Duty folds upward: Clearance → Ground → Tower | — |
| Wrong frequency | `--strict-freq`: silence. Default: silence + on-screen hint | — |
| COM1 in text mode | `/com 121.900` command | — |
| Taxi routing | Dijkstra, distance + penalty per taxiway-name change, runway crossings become hold-shorts, fallback to route-less taxi | — |
| Taxi monitoring | Safety only: hold-short / runway entry without clearance → "stop immediately", holding point detection; runway crossings: the pilot reports holding short, ATC clears (F2) | Full conformance (wrong turns, progressive taxi, speed) |
| Runway choice | Max headwind, tailwind ≤ 5 kt, calm (< 5 kt) → longest, hysteresis | — |
| Wind source | `--weather live\|sim`, default `live`; offline → cached METAR / fixture | — |
| Readbacks | Full ICAO list, compared by normalised values, not words | — |
| Go-around | Pilot-called, detected (climb after < ~300 ft AGL near runway), ATC-called (no landing clearance within ~2 nm); simple instructions, back to Approach | Published missed approach |
| Flight plan | Manual (CLI/prompt) + SimBrief, both fill one `FlightPlan` | `.PLN` import |
| Flight rules | IFR only; controller picks phase sequence from flight rules | VFR |
| Intent parsing | Rule parser only; what it can't read → "say again" (decided in step 24 after measuring the LLM) | LLM fallback, if a model fits next to MSFS |
| LLM backend | None for now: prototype parked in `spikes/s24_llm_fallback.py` | Local (Ollama) or cloud |
| Approach | Direct to 10 nm final fix, descend, cleared ILS/RNAV; from P5: STAR from the plan, step descents, radar vectors to the ILS, speeds | Published missed approach |
| Departure / Center | "Radar contact, climb, direct first waypoint"; handoffs at fixed distances; descent at 3° top-of-descent; Center sectors imported from the user's Little Navmap data (F3), `centers.json` as override, handoff at each sector boundary | SIDs |
| ATIS | In v1, letter advances on METAR or runway change | — |
| Traffic | AI/FSLTL traffic read from MSFS (Milestone 4, package 5): runway and taxiway checks, traffic information, AI chatter | Sequencing |
| Tests | Unit, controller, full-flight golden scenario tests; run `pytest` locally | GitHub Actions CI |

## Module layout

```
atc/
  main.py            # CLI, config, wires real or fake parts together
  config.py          # TOML config: whisper model/device, TTS voice, SimBrief user, LNM db path, Center sectors
  sim/               # SimSource interface, SimConnectSource, FakeSim (scripted positions)
  audio/             # push-to-talk, WhisperInput / TextInput, Pyttsx3Output / PrintOutput
  weather/           # METAR fetch, parse, cache; wind components
  airport/           # AirportData interface, JSON + Little Navmap backends, taxi graph, router
  airspace/          # Center sectors from centers.json, sector lookup
  flightplan/        # FlightPlan dataclass, manual + SimBrief sources
  intent/            # intent schema, rule parser, number normaliser
  controller/        # deterministic state machine, phases, readback checker, safety monitor, ATIS;
                     # controller.py with its parts ground.py, tower.py, air.py, traffic_calls.py, common.py
  events.py          # Event + sinks: everything shown, as data (console and app)
  session.py         # building a session: plan, airports, sim, weather, controller
  runtime.py         # live loop, /commands, COM1 tuning
  phraseology/       # decisions -> ICAO text
tests/
  unit/
  controller/
  scenarios/         # YAML flight scripts + golden transcripts (run by tests/test_scenarios.py)
  fixtures/          # JSON airport, METARs, SimBrief XML
spikes/              # throwaway feasibility scripts (milestone 0)
```

## Steps

### Milestone 0 — Prove each external piece works (throwaway scripts in `spikes/`)

1. **Project setup:** folder, `git init`, virtualenv, `pyproject.toml`, pytest installed, `.gitignore`.
2. **SimConnect spike:** with `Python-SimConnect`, read lat/lon, altitude AGL, on-ground flag, heading, ground speed, COM1 active frequency, ambient wind.
3. **Whisper spike:** push-to-talk record + faster-whisper transcription. Measure latency for model sizes on `cuda` vs `cpu`, and the frame-rate cost in MSFS. Try an aviation `initial_prompt`.
4. **TTS spike:** pyttsx3 voices, speaking ICAO numbers, speaking without blocking the main loop.
5. **Little Navmap spike:** find the MSFS SQLite database (usually under `%APPDATA%\ABarthel\little_navmap_db\` — verify), query one airport's runways, COM frequencies, ILS, taxi paths with names, parking. Write down the tables and columns used.
6. **SimBrief spike:** fetch the latest flight plan XML by username; save one as a test fixture.
7. **FSLTL spike:** check whether FSLTL-injected aircraft show up in SimConnect's AI object list (may need raw `ctypes`; this is only a yes/no check for the later traffic version).

### Milestone 1 — Skeleton that runs offline ✅ done 2026-11-14

8. ✅ Package layout and TOML config (`atc.toml`, git-ignored; `atc.example.toml` documents every key). Unknown keys are an error, so typos don't fail silently.
9. ✅ Interfaces and fakes that something already uses: `SimSource`/`FakeSim`, `SpeechInput`/`TextInput`, `SpeechOutput`/`PrintOutput`, `AirportData`/`JsonAirportData` (with `data/airports/EDDH.json` exported from Little Navmap). **Deviation:** `WeatherSource`, `IntentLLM`, `Clock` and `Random` get added in the step that first uses them (12, 24, 19). An interface with no caller is dead code that can't be tested. For randomness, the controller will take a `random.Random(seed)` directly.
10. ✅ CLI `python -m atc --text --nosim --from EDDH --callsign DLH4AB [--to --cruise --route --aircraft --strict-freq --config]`, plus `/com <MHz>`, `/help`, `/quit`. The controller checks COM1 against the airport's frequencies (hint or silence) and answers "<station>, roger." as a placeholder. Running without `--text`/`--nosim` stops with a message naming the step that builds it. `--weather` and `--simbrief` arrive with steps 12 and 15. 31 tests.

### Milestone 2 — Core logic (pure Python, fully tested, no sim needed)

11. ✅ **Phraseology** (`atc/phraseology/spoken.py`): digits with strict ICAO pronunciation ("tree", "fife", "niner"), ICAO spelling "Alfa"/"Juliett", flight levels (whole hundreds said as "flight level one hundred"), altitudes ("tree thousand fife hundred feet"), three-digit headings with north = 360, frequencies (six digits, four if the last two are zero), squawk (octal check), QNH, runways ("zero eight left"), wind (calm, variable, gusting), callsigns via a telephony table (`airlines.py`: DLH → Lufthansa, BAW → Speedbird, …; unknown airlines and registrations are spelled). "Thousand" is kept as written rather than ICAO's "tousand". Zira's output was transcribed by whisper without a single error.
12. ✅ **Weather** (`atc/weather/`):
    - **METAR parser:** wind incl. gusts, VRB and MPS; visibility incl. CAVOK and SM; clouds incl. CB/TCU; weather phenomena; temperature and dewpoint; QNH from Q or A (inHg). Parsing stops at TEMPO/BECMG/NOSIG/RMK. A missing wind group is "unknown", not calm.
    - **Runway choice:** most headwind wins. Calm (< 5 kt, VRB or no METAR) keeps the current runway, else takes the longest, using the better end if there's any wind direction. **Hysteresis:** keep the current runway while the tailwind, gusts included, is ≤ 5 kt.
    - **Weather source:** `LiveWeather` uses aviationweather.gov (`/api/data/metar?ids=…`, plain text) with a 5 s timeout and a per-airport cache in `cache/metar/`, so the last METAR survives going offline. `StaticWeather` is for tests. `main()` takes the source as a parameter, so tests never touch the network.
    - The startup banner shows the METAR and the runway in use with head/tail- and crosswind.
    - `--weather live|sim` moves to step 22, since "sim" needs the real MSFS connection. 98 tests.
13. ✅ **Airport model + Little Navmap backend** (`atc/airport/littlenavmap.py`): runways, thresholds, true headings, frequencies (Hz → kHz), ILS (joined by runway name), parking (`G 12A`, airline codes; `default_parking()` prefers gates). `main` tries Little Navmap first, then JSON, and the banner says which one was used. The fake sim now starts at a real parking spot. `python -m atc.airport.export EDDH …` writes the JSON files, so LNM → JSON is a single code path. Tests use a tiny hand-built database with the real LNM column names, plus one test that compares the real DB with `EDDH.json` (skipped without Little Navmap). Tried EDDH, EDDM, EGLL, KJFK, EDHI. 105 tests.
    - **Open point for step 19, COM names are messy:** concatenated words (`NEWYORK`, `MUNICHAPRON2`, `TERMINAL7RAMP`), and apron/ramp frequencies are typed `G` like Ground. Before handing off to "Ground", skip names containing APRON/RAMP, and prefer the airport name for the spoken station name. Parking names repeat (two "G 1" spots: `GS` and `GM` sizes at the same gate).
    - **Taxiway name coverage varies wildly by scenery** (share of named non-parking segments): EDDF 93 %, EGLL 93 %, EDDB 85 %, KLAX 71 %, KJFK 70 %, LOWW 62 %, EDHI 47 %, EDDM 46 %, EDDH 18 %, **LSZH 0 %**. **Consequence for step 14:** name propagation along unnamed chains is worth doing, and the fallback "taxi to holding point runway X" without a route is a must, not an edge case. Some airports will never get named routes from this data.
14. ✅ **Taxi graph and router** (`atc/airport/taxi.py`, `atc/airport/geo.py`, `atc/phraseology/taxi.py`):
    - Taxi paths are part of the airport model (LNM + JSON, one compact line per path). Nodes are coordinates rounded to 7 decimals. Hold-short nodes come from `HSND`. Runway crossings are found geometrically (segment vs runway centreline). The designator is the runway's first end, e.g. "hold short runway 05".
    - **Name propagation** (decision (a) from step 5): a chain of unnamed segments gets a name only when both ends touch exactly one and the same named taxiway.
    - **Dijkstra** over (node, taxiway arrived on): distance + 150 m per name change + 1500 m per runway crossing. The goal is the cheapest of the hold-short nodes within 200 m of the departure runway's centreline and within 300 m of the one nearest its threshold.
    - **Clearance** (decision (c)): "taxi to holding point runway X via A, B, hold short runway Y". Plain "taxi to holding point runway X" when there's no route, no names, or > 30 % of the taxiway length (parking lead-in excluded) is unnamed.
    - `/taxi` in text mode shows what Ground would say plus the route details.
    - Results: EDDF "via N5, N, Y, Y1, M29" (4.5 km), EDDM "via E1, C5, S6, S, B3", EGLL "via K, B, L21, L23", KJFK "via G, Z, hold short runway 04L". EDDH and LSZH fall back (100 % unnamed). EDDF takes 38 ms to build and 15 ms to route.
    - Also fixed: PowerShell pipes start stdin with a UTF-8 BOM, which hid the "/" of a first-line command. 119 tests.
    - **Not verified yet:** that these routes match what you see in the sim. Worth a look in Little Navmap's airport diagram.
15. ✅ **FlightPlan + SimBrief** (`atc/flightplan/simbrief.py`): `--simbrief USER`, or plain `--simbrief` with `simbrief_username` from `atc.toml`, loads the latest OFP: callsign, departure, destination, cruise, route, aircraft, flight rules (I/V → IFR/VFR). Command-line values override it, e.g. `--simbrief --callsign DLH4AB`. Without `--simbrief`, `--callsign` and `--from` are required. SimBrief's own error text is shown ("Unknown UserID", "No flight plan on file"). The last OFP is cached in `cache/simbrief/` (it contains personal data, so it stays git-ignored) and is used offline, labelled "cached copy". Usernames are sanitised before becoming file names. The banner shows the plan. SimBrief's *planned* runway is ignored on purpose, since ATC picks the runway from the wind. Tried with the real account: online, offline and unknown user. 134 tests.
16. ✅ **Rule-based intent parser** (`atc/intent/`):
    - **Schema** (`schema.py`): `Intent(kind, callsign, addressed_to_us, items, text)` with a fixed list of 14 kinds and typed items (runway, hold_short, taxiways, flight_level, altitude_ft, heading, speed_kt, squawk, frequency_khz, qnh, atis, cleared_takeoff, cleared_land, line_up). It validates itself, so any future LLM fallback can't produce anything outside it.
    - **Normaliser:** number words incl. tree/fife/niner become digits; "1-2-0", "1, 2, 0" and "one two zero" all become `120`; "3,500" becomes `3500`; "119 or decimal 875" becomes `119.875` (split "niner"); "QNH101 Tree" becomes QNH 1013.
    - **Callsign finder:** airline telephony (fuzzy, similar length only, so "speed" ≠ Speedbird), ICAO code forms ("DLH4AB", "DLH, 4AB", "glh4ab"), "for" → 4 inside a flight number. With several candidates, the one closest to our callsign wins ("via delta 1" is a taxiway, not airline Delta). "Ours" means similarity ≥ 0.6.
    - **Items and kinds** come from keyword rules. Check-ins need "with you"/"passing"; otherwise anything with items is a `readback`, and the controller (step 19) decides with context.
    - Text mode shows `(understood: …)` for every transmission.
    - **Real end-to-end check:** whisper + parser on recordings 001–008 gave the correct kind, items and "yours" for all 8.
    - Known limitation: a taxiway letter suffix after a number ("Z5B") is read as two taxiways (Z5, B). 182 tests.
17. ✅ **Readback checker** (`atc/controller/readback.py`):
    - An instruction is a list of `Item(key, value, phrase)`, made only through builders (`level`, `altitude`, `heading`, `speed`, `squawk`, `contact`, `qnh`, `taxi`, `line_up`, `cleared_takeoff`, `cleared_land`), so value and ICAO wording can't disagree.
    - `check_readback()` compares values from the parsed readback, never wording. Wrong items get "negative, I say again, <original phrase>", missing ones "read back squawk and QNH". Extra items are ignored, and "wilco" alone counts as missing everything.
    - Covers the full ICAO list we have items for: runway, hold short, taxi route, level/altitude, heading, speed, squawk, frequency, QNH, take-off/landing/line-up clearances.
    - The parser now also reads "climb 5000" / "descending to 3000" as altitudes.
    - Real readbacks (recordings 002, 005, 006) pass. 198 tests.
    - **Deferred to step 19:** route-clearance items (destination, SID/route) only exist once Clearance Delivery builds clearances. A missing callsign in the readback is the controller's decision, since the checker only sees items.
18. ✅ **ATIS** (`atc/controller/atis.py`, `atc/phraseology/weather.py`):
    - ICAO order: "<Airport> information <letter>, time hhmm. Runway in use X. Wind, visibility (km ≥ 5 km, metres below, '10 km or more' for 9999), weather (light/heavy, showers, thunderstorm with …, freezing, in the vicinity), clouds (few/scattered/broken/overcast + height, cumulonimbus), temperature/dew point (minus), QNH. Advise on initial contact you have information <letter>." CAVOK is spoken "cav okay" so TTS doesn't spell it out.
    - The letter advances when the METAR text or the runway in use changes, and wraps Z → A. It starts at A, since the starting letter isn't important.
    - **Refactor:** the controller now owns the METAR, the runway in use (chosen in its constructor) and the ATIS. Tuning COM1 to the ATIS frequency with `/com` plays the ATIS, and the banner shows the current letter.
    - Listen check: Zira's live EDDH ATIS was transcribed by whisper word for word. 219 tests.
    - **Still to do in step 19:** the controller re-reads the METAR periodically and calls `atis.update` (and `choose_runway` with `current=`). An outdated letter in "with information X" gets "information Y is now current".
19. **Controller (IFR)**, split in two parts:
    - **19a ✅ Ground departure** (`atc/controller/controller.py`). Phases `clearance → cleared → pushback → taxi → takeoff`.
      - **Clearance:** "cleared to <destination name> via <SID> departure | flight planned route, runway X, climb altitude 5000 feet (or cruise if lower), squawk NNNN". The SID is spoken from the SimBrief route (`AMLU2G AMLUH` → "Amluh two Golf departure", `atc/flightplan/route.py`). With a missing or outdated ATIS letter, "information B is (now) current, QNH …" is added, and QNH joins the readback. Squawks are random octal, never 7xxx/1000/1200/2000, from an injected `random.Random`.
      - **Then:** "readback correct" (+ "contact Ground …" if a separate Delivery exists; switching without reading the frequency back is accepted) → "push and start approved" → taxi clearance (route items + hold short + QNH if not given yet) → at Tower "wind …, runway X, cleared for takeoff".
      - **Each issued instruction stays pending until correctly read back.** Wrong or missing items get corrected, and a new request on that frequency counts as a missing readback.
      - **Stations:** fold-up Delivery → Ground → Tower; apron/ramp frequencies are never used as Ground. A request on the wrong station gets "contact <station> <freq>", and requests out of order get "request IFR clearance first" or "contact Ground … for taxi".
      - **Always:** no or another callsign gets "station calling X, say again your callsign"; "say again" repeats the last transmission on that frequency; "radio check" gets "read you fife".
      - **Normaliser fix found here:** "runway 23, 5000 feet" became 235000. Now only single written digits join each other ("1, 2, 0"), spoken digits extend a number ("101 tree"), and multi-digit numbers never grow.
      - Played a full departure with real data (LNM EDDH, SimBrief DLH759, live METAR). 237 tests.
      - **Not yet:** SID/destination readback isn't checked (the parser doesn't extract them), no pushback direction, Ground doesn't hand off to Tower by itself (needs the holding-point detection from step 20), no crossing clearance for hold-shorts (step 20), no periodic METAR refresh (step 22).
    - **19b ✅ Air phases and arrival.** Phases `airborne → climb → arrival → approach → final → landing → vacating → taxi_in`.
      - **New concept, `Controller.tick(state)`:** ATC calls the pilot by itself when the position says so. Tower → Departure above 500 ft AGL. Descent at the top of descent (3 nm per 1000 ft from the *planned* cruise level down to 5000 ft, plus 15 nm). Departure → destination Approach at 40 nm. Approach → Tower at 12 nm from the threshold. "Vacate runway, contact Ground" when on the ground below 40 kt. A call on a frequency the pilot isn't tuned to is only a hint ("Hamburg Tower is calling you on 121.280: …"), and nothing new is issued while a readback is outstanding.
      - **Pilot calls:**
        - Check-in with Departure: "radar contact, climb flight level <cruise>, proceed direct <first fix>" (end of the SID).
        - Check-in with Approach: "proceed direct to one zero miles final runway X, descend altitude <elevation + 3000 ft>, cleared ILS|RNAV approach runway X".
        - Check-in with Tower: "wind …, runway X, cleared to land".
        - At Ground: "taxi to stand <gate of our airline if the scenery assigns one, else any gate> via …".
        - Also handled: "request descent" (early descent), "runway vacated", and the wrong controller in the air ("contact Hamburg Approach …").
      - **Data:** the controller gets the destination airport and its METAR, and picks the arrival runway by wind. `data/airports/EDDM.json` was exported as test data. `AircraftState` gained `alt_msl_ft`. Great-circle helpers live in `geo.py`.
      - **Text mode:** `/fly <nm>` (along the great circle, on the same climb/cruise/descent profile ATC plans with), `/final <nm>`, `/landed`. `tick()` runs after every command and transmission.
      - **Fixed along the way:** the descent point was computed from the *current* altitude, so an aircraft already descending kept pushing it back and never got a clearance. The parser didn't read "runway 08R" (glued side letter).
      - Played EDDH → EDDM gate to gate with real data (LNM, SimBrief DLH759, live METARs); the arrival ends at Lufthansa gate G 201. 250 tests.
      - **Simplifications to know:**
        - No Center: the departure airport's Departure/Approach keeps the aircraft until the destination's Approach. (Center sectors came in step 20b.)
        - No transition level: the descent goes straight to an altitude with QNH.
        - No speed control.
        - "Established" isn't checked, and the pilot must call Tower to get a landing clearance (go-around without one is step 20).
        - No destination ATIS.
        - The METAR isn't refreshed during the flight (done in step 22).
20. ✅ **Safety monitor** (`atc/controller/safety.py` + `Controller.tick`). Safety calls come before everything else in `tick()` and don't wait for outstanding readbacks.
    - **Runway protection:** each runway's protected distance is the median distance of the scenery's own hold-short points from its centreline, minus 5 m (real data: 72–139 m, e.g. EDDH 85 m, EDDM 103 m, EGLL 132–139 m). Without hold-short points it is half the width + 30 m. Standing within 15 m of a hold-short node never counts, because beyond a runway end the distance is measured to the end. On the ground inside a runway's area without a clearance for it: "stop immediately, stop immediately", once per entry. Clearances come from the takeoff clearance, a crossing clearance and the landing clearance; the landing runway stays cleared until the aircraft has actually left it.
    - **Holding point:** within 30 m of the route's last node, Ground says "contact Tower …" (if Ground ≠ Tower).
    - **Crossings:** at the last hold-short node *before* a crossing, Ground says "cross runway X" (read back). Found on KJFK real data: a crossing spans several segments and only the one over the centreline is marked, so holding at its start would already have been an incursion.
    - **Go-around**, three triggers, each followed by a simple missed approach: "fly heading <runway heading, magnetic>, climb altitude <elevation + 3000 ft, rounded up to 1000>, contact Approach …", then a new approach clearance when the pilot calls Approach.
      - Pilot reports "going around": "roger, …".
      - ATC-initiated within 2 nm without a landing clearance: "go around, I say again, go around, …".
      - Detected: below 300 ft AGL on final, then 200 ft higher.
    - **New in `_respond`:** a pending instruction that sends the pilot to another station is satisfied as soon as the pilot calls that station.
    - Text mode: `/goto holding|crossing|runway`.
    - **Real-data check:** following the taxi route gate → holding point at EDDH (23, 33), EDDM, EDDF, KJFK, EGLL, LSZH raises no false alarm (KJFK only after the fix above). 259 tests.
    - **Not covered (taxi conformance, the agreed later version C):** wrong turns, taxi speed, stopping short of the holding point, no "hold position" for non-runway problems, no line-up-and-wait, and the runway exit isn't checked.
20b. ✅ **En-route Center sectors** (`atc/airspace/centers.py`, `data/centers.json`, `Controller._center_progress`). An added requirement.
    - **`centers.json`:** each sector has `name` (the station as spoken, e.g. "Bremen Radar"), `fir`, `frequency` (MHz, or exactly `"PLACEHOLDER"`), `lower_ft`/`upper_ft` (MSL, lower inclusive, upper exclusive), a `[lat, lon]` polygon and an optional `note`. Bad entries stop the start with a message naming the sector. A wrongly cased "placeholder" is an error too, so a marker can't slip through as a frequency. Config key `centers_file`; a missing file means no sectors (the old behaviour).
    - **Lookup:** point-in-polygon (ray casting on lat/lon; fine for sectors that don't cross the antimeridian) plus the altitude band. Where sectors overlap, the first in the file wins.
    - **Flow:** new phase `enroute` between `climb` and `arrival`.
      - Passing FL100 or 30 nm from the origin, Departure hands off to the sector that contains the aircraft ("contact <station> <frequency>").
      - Each `tick()` checks the sector (the sim loop in step 22 runs it every second). A new sector, by position *or* altitude band, gets a handoff from the Center in charge.
      - The Center in charge gives the descent at top of descent, and at 40 nm hands off to the destination's Approach.
      - On check-in Center answers "<station>, identified".
      - Outside every sector: "radar service terminated, squawk seven zero zero zero, frequency change approved". Approach is then only a hint at 40 nm. Re-entering a sector gives a hint whom to call.
    - **Never invented frequencies:** a `PLACEHOLDER` sector is found by position, but never gets a handoff. The pilot gets a one-time hint per sector asking to fill it in, and the current controller keeps the aircraft. The banner lists all placeholder sectors.
    - **The shipped `data/centers.json`** has rough boxes for Bremen, Rhein (FL245+), Langen and Munich Radar. All frequencies are `PLACEHOLDER`, and the polygons are not the real boundaries.
    - **Sim data checked (Little Navmap MSFS DB, before relying on it):**
      - The `boundary` table has 4201 Center polygons (type `C`) with name and frequency (kHz), 19 of them over Germany with 6 frequencies.
      - Every polygon is GND–unlimited, with no altitude bands, and the polygons are MSFS's own pieces of each FIR (e.g. "BREMEN", "LANGEN RADAR", "MUNICH").
      - The airport `com` table has 2488 `CTR` frequencies (Hz) at 2270 airports, almost all in the US/Canada and none at German airports.
      - Not used yet; an importer into `centers.json` would be a later step.
    - **Also changed:** `Station` holds an `ident` instead of an `Airport`, so a Center is a station like any other. `station_at()` is public (`/com` shows Center names). 282 tests.
21. ✅ **Scenario tests** (`tests/test_scenarios.py`, `tests/scenarios/*.yaml` + `*.golden.txt`).
    - **Format:** a scenario is the plan, METARs, seed, optional inline Center sectors, and the lines you would type in text mode (transmissions and `/commands`). On top of that come `{fly_until_call: [from, to]}` (1 nm steps with a tick, like the sim loop every second, until ATC speaks) and `{comment: …}`. Transmissions can use `{squawk}`, `{runway}` and `{arrival_runway}`. The transcript looks like a text-mode session, so a golden file reads like a radio log.
    - **Golden files:** a mismatch fails with a unified diff. `pytest tests/test_scenarios.py --update-golden` rewrites them, and the diff must be read before committing. A new scenario writes its golden file and fails once, so it gets read. `pyyaml` is a dev dependency.
    - **Scenarios:** `normal_flight` (gate to gate with ATIS), `wrong_readback`, `go_around` (pilot-reported, then ATC-initiated, then landing), `wrong_frequency` (not tuned, ATIS, empty frequency, wrong controller, an ATC call missed on Ground), `center_sectors` (incl. a PLACEHOLDER sector and the altitude band).
    - **Found by reading the transcripts, and fixed:**
      - After "negative, I say again" only the corrected items count now. Before, items already read back correctly were asked for again ("read back runway and altitude").
      - A pilot who calls the old controller again after a handoff hears the handoff repeated, instead of "read back frequency".
      - Missed-approach headings are rounded to 5° ("zero eight zero" instead of "zero seven niner" for 08R).
      - "established" counts as a check-in.
      - Corrections are joined with commas, and three missing items read "runway, altitude and squawk".
    - 292 tests.

### Milestone 3 — Real sim, real voice

22. ✅ **SimConnectSource** (`atc/sim/simconnect.py`, `atc/weather/sim_weather.py`, `run_live` in `main.py`).
    - **Connection:** without `--nosim`, `main` connects to MSFS. A sim that isn't running stops with a message. `state_from_simvars` is a pure function: radians → degrees, MHz float → kHz (126.85499… → 126855), `SIM_ON_GROUND` → bool, COM1 outside the band → "not tuned". Missing data (loading, pause menu, a closed pipe) keeps the last state and sets `stale`, and the loop shows it once.
    - **Airport detection:** `AirportData.nearest()` for Little Navmap (bounding-box query, airports with a runway) and JSON. On the ground, the airport within 5 nm is the departure, even if the plan says otherwise (with a notice). `--from` is only required with `--nosim`.
    - **Live loop:** input runs in a thread and hands lines over through a queue. The main loop ticks about once per second (the ~0.3 s for reading the sim is subtracted). Every handoff, safety call and sector check works without a transmission. COM1 changes made in the cockpit show the station and play the ATIS. `/fly` and the other sim commands are refused with MSFS. `LiveSession.step()` holds the logic and is tested step by step without threads.
    - **`--weather live|sim`:** `sim` builds a METAR line from MSFS at the aircraft and sends it through the normal parser. The wind is a vector average (6 samples at startup, then the last minute), visibility in 100 m steps, and QNH comes from sea-level pressure. Clouds and dew point aren't simvars, so the ATIS leaves them out. The destination always uses the live METAR.
    - **Weather refresh:** every 30 min `Controller.update_weather()` takes new METARs. The ATIS letter advances, the departure runway can only change before the clearance, and the arrival runway only before the approach clearance.
    - **Tests never touch a running MSFS:** an autouse fixture replaces `SimConnectSource`. Found because a test hung on the real sim.
    - **Live check against MSFS (2026-11-14, EDDH):**
      - Detection, sim weather (`20009KT 6500 Q1018`), COM1 126.855 = Hamburg Tower, radio check, "contact Ground" for the clearance, `/taxi` and `/quit` all worked.
      - **Found:** the flight was loaded *on* runway 23, and ATC shouted "stop immediately" at startup. Now the first tick only gives a hint, and the alarm comes only when the aircraft drives back onto the runway.
    - **Not covered yet:** the text prompt and ATC output can mix on the screen, a disconnect isn't reconnected, there is no destination weather from the sim, and the callsign doesn't come from the sim's `ATC ID`. 322 tests.
23. ✅ **Voice** (`atc/audio/voice.py`, `atc/audio/tts.py`). Without `--text`, the pilot talks and ATC speaks. The keyboard stays open for `/commands`, so `/quit`, `/taxi` and, with `--nosim`, `/com` and `/fly` still work.
    - **Push-to-talk:** `MicRecorder` polls `GetAsyncKeyState` (key from `[whisper] ptt_key`, checked at startup) and records 16 kHz mono while the key is held.
    - **What gets dropped:** a tap under 0.3 s is ignored. A nearly silent recording hints at the wrong microphone (`python -m atc --list-mics`).
    - **Whisper:** `small.en`, beam 5, CPU int8, `vad_filter=True`, a generic prompt with the ICAO alphabet and no names (a test makes sure of that). A warm-up transcription at startup, so a broken CUDA setup fails before the first call, with a hint what to do.
    - **On screen:** `(heard in 3.3 s: …)`, then the parser's `(understood: …)`. An empty result means "say again". A result made only of prompt words is ignored, because that is what whisper invents from noise. `[whisper] save_recordings = true` keeps each transmission in `recordings/`.
    - **Text-to-speech:** pyttsx3 in its own thread with a queue and its own COM init, so `say()` returns at once and the 1-second tick keeps running while ATC talks. The voice is chosen by name and must be English (the Windows default here is German Hedda). The text is printed as well. `[tts] rate` is optional.
    - **Inputs:** `run_live` takes several inputs, each in its own thread (push-to-talk + keyboard). The session ends when the keyboard input ends or on `/quit`.
    - **Tests** use fakes for microphone, model and SAPI engine. An autouse fixture keeps tests from loading whisper or opening the microphone (found because a test hung on the push-to-talk key).
    - **Real check (2026-11-14):**
      - The 8 real recordings from Milestone 0 went through `WhisperTranscriber` + parser. All 8 intents and callsigns were right ("Hammer ground", "4L for Bravo" and "Lufthansa for Alpha Bravo" included), at 3.0–4.0 s each.
      - Zira speaks without blocking (`say()` returns at once). The app starts in voice mode and quits via `/quit`.
      - Push-to-talk with the real microphone inside the app is left for the user to try.
    - **Not covered:** no blocked transmission while ATC is talking, no radio effect, one voice for all controllers. 337 tests.
24. ✅ **LLM fallback: measured, parked, and the rule parser strengthened instead.**
    - **Choice of backend:** the user chose local Ollama over a paid cloud API. `llama3.2` (3.2B, Q4) was already installed.
    - **Prototype** (`spikes/s24_llm_fallback.py`): Ollama `/api/chat` with a JSON schema as `format`, temperature 0, phase/station/pending-readback context in the prompt. Then deterministic checks:
      - **schema:** kind, items, types;
      - **values:** runway exists, squawk octal, COM channel, ranges;
      - **grounding:** every number must appear in the transcript, so a value can't be invented;
      - **callsign:** the rule parser's callsign wins, and the LLM's counts only if its digits were said.
    - **Measured next to a running MSFS** (RTX 3060 Ti 8 GB, MSFS already using 7.4 GB):
      - 76 s to load and 2.1 GB of extra VRAM;
      - 1.4–3.2 s per call, on top of whisper's ~3 s;
      - 3 of 6 free-form transmissions useful;
      - the checks caught a squawk copied from the prompt's example ("0421 was not said") and "Golf One" as a runway;
      - a heading/altitude readback came back without its values.
    - **Decision (user):** no LLM. Standard phraseology is what a student should practise anyway, and "say again" is real ATC behaviour. The `--text --nosim` rule ("no LLM required") holds trivially.
    - **Rule parser learned the phrasings the test found:**
      - "would like", "can/could/may we get/have", "like to get" count as a request;
      - "ready to copy" is a clearance request;
      - "start (the) engines" / "engine start" is a pushback/start request;
      - "ready … holding point" means ready for departure.
    - **Normaliser fix:** before "thousand"/"hundred" at most two digits are said, so "heading zero eight zero, three thousand five hundred" is 080 + 3500, not 0803 + …, while "one one thousand" stays 11000. 350 tests.

### Milestone 3b — App window (added 2026-11-14, before the first real flight)

The user wants a real app like BeyondATC or SayIntentions instead of a console. Decisions from the interview:
- **Technology:** a local web UI, because it is the closest to the look of those apps. Python's standard library serves HTML/CSS/JS on `localhost` and pushes live updates with Server-Sent Events. It opens in **Edge app mode** (`msedge --app=…`), so it gets its own window without an address bar, and falls back to the default browser. No new dependencies.
- **Two screens:** a start screen (flight plan, checks, settings, Start), then the flight screen.
- **Extras on the flight screen:** a suggested next call, text input with fake-sim buttons, a map, and a saved flight log.
- **The map is drawn by us** (route, aircraft, airports, Center sectors) without map tiles, so it works offline.
- **UI language English**, like the controller's hints. Radio stays ICAO English.
- The console (`python -m atc --text --nosim`) keeps working unchanged, golden files included.
- **Design rules from [unslop](https://github.com/heydamir/unslop)** (CC BY 4.0, credit in the CSS). The user asked for it. Its values are taken over directly; the skill itself isn't installed.
  - **Spacing and colour:** a 4 px spacing grid; one neutral dark ramp ("ink", cool) for backgrounds, surfaces, hairline borders and three text roles; one accent used sparingly, taken from the product's world.
  - **Type:** one interface family plus one mono for frequencies and figures, weights 400/500, sentence case.
  - **Motion:** one easing curve, transitions only on colour, opacity and transform.
  - **Banned:** gradients, glows, emoji, uppercase tracked labels, looping animations.
  - **Direction for this app:** "instruments and night shifts". The accent is cockpit amber, positive/negative are toned-down green/red, and frequencies and squawks are in mono.

A1. ✅ **Events instead of print strings:**
    - Everything the user sees becomes a structured event: pilot transmission, heard, understood, ATC transmission, hint, status. The console renders events exactly as today, so the golden files stay byte for byte the same.
    - `main`'s setup (plan, airports, weather, controller, sim, voice) moves into one builder that the CLI and the app share.
    - **Done:**
      - `atc/events.py`: `Event(kind, text, station, time)` with 11 kinds (atc, atis, pilot, heard, understood, readback, missed_call, notice, tuning, position, info). `ConsoleSink` prints them as before; `Collector` keeps them.
      - **Controller:** `Response` got `kind` and `station`, so the window knows who spoke and what was a readback result.
      - **`atc/session.py`:** `PlanRequest` + `SessionOptions` → `build_session()` → `Session` (plan, airports, sim, weather, controller, `banner()`, `refresh_weather()`). Problems are `SetupError`s.
      - **`atc/runtime.py`:** `run`, `LiveSession`, `run_live` (now with a `stop` event for the app), `handle_command`, `describe_tuning`, all writing to a Sink. Push-to-talk gets the sink through `attach()`.
      - `atc/main.py` is only the command line.
    - All golden files byte for byte unchanged. 362 tests.
A2. ✅ **Local server + launcher:**
    - `python -m atc.app` serves `atc/app/static/` and offers a small JSON API (config, SimBrief load, checks, start/stop, commands, transmissions) and an SSE stream of events.
    - It opens the Edge app window. `ATC.bat` and an optional desktop shortcut start it with a double-click.
    - Closing the window stops the session.
    - **Done:**
      - **Server** (`atc/app/server.py`, standard library only):
        - `/api/state`, `/api/start`, `/api/say`, `/api/stop` and an SSE stream `/api/events?from=N` (history from the current session's first event, `Last-Event-ID` on reconnect, a heartbeat every 5 s).
        - One session at a time runs `run_live` in a thread with a stop event. The window's text box is its input.
        - Setup problems come back as `{"error": …}` and are shown on the start screen.
      - **Safety:** only 127.0.0.1 is served; POSTs must be JSON and same-origin, so another website can't send transmissions; static files can't escape `static/`.
      - **Launcher** (`python -m atc.app`, `ATC.bat` with `pythonw`):
        - Edge in app mode with its own profile in `cache/edge-app`, otherwise the default browser. Port 8350, or a free one if it is taken.
        - 15 s without a connected window ends the app.
      - **Page:** `static/index.html`, `app.css` (unslop tokens: ink ramp, amber accent, Segoe UI Variable + Cascadia Mono from Windows, so nothing is downloaded) and `app.js` (start form, radio log by event kind, text box, End flight).
      - **Found and fixed:**
        - `HTTPServer` turns `SO_REUSEADDR` on, and on Windows that lets a second copy bind the same port silently. It is now off, so the second copy picks a free port.
        - `/com` in the live loop announced the station twice: the command did, and then the next tick saw the change again.
      - **Checked in a browser** at 555 px and 1440 × 900: start, tuning, clearance from Hamburg Ground, End flight.
      - **Not tried yet:** the real Edge window with its close detection (left for the user via `ATC.bat`). The banner still shows as App lines in the log until A4 gives it panels. 375 tests.
A3. **Start screen:**
    - **Flight plan:** SimBrief (username, Load) or manual fields.
    - **Checks** with a coloured dot each: MSFS connected, Little Navmap database, microphone, whisper model, TTS voice.
    - **Settings:** PTT key, mic, voice, weather live/sim, with MSFS / without sim, strict frequency. Saved to
      `settings.toml`.
    - **Own push-to-talk binding (user's wish, 2026-11-15):** in the settings the pilot sets the key by pressing it
      ("press the key you want…"), any keyboard key or a joystick / yoke button, not only the fixed list in
      `PTT_KEYS`. A second binding as a spare. Joystick buttons need a new input source (e.g. Windows' joystick API).
    - A Start button.
A4. **Flight screen:**
    - **Radio log:** pilot and ATC with time and station; understood/readback marks; hints in grey.
    - **Status:** COM1 + station, phase, runway, ATIS letter, squawk, cleared level, the station to call next.
    - **More panels:** weather, frequencies of the current airport, push-to-talk state (idle / recording / transcribing).
    - **Text input**, and without a sim the /goto, /fly, /final, /landed buttons.
A5. **Suggested call:**
    - `Controller.suggestion()` is computed deterministically from the state: the next expected call in standard phraseology ("Hamburg Ground, Lufthansa 4AB, information Alfa, request IFR clearance to Munich").
    - After an instruction it is the readback with exactly the values to read back.
    - Tested for every phase.
A6. ✅ **Map:** a canvas with the aircraft (position, heading), the great-circle route, origin/destination and the Center sectors with names. Offline.
    - **Layout (user's choice):** a third tab, RADIO | PHRASES | MAP, in place of the log.
    - **Done:** `atc/controller/mapdata.py`: `map_data()` once per flight via `GET /api/map` (airports with runways,
      the SimBrief waypoints, the Center sectors whose box comes within 2 degrees of the route); `moving()` with every
      status poll (our position and true heading, the traffic). The page draws on a canvas with a flat projection
      around the aircraft (60 NM per degree of latitude, longitude times cos(latitude)), no map tiles, offline: sectors
      as thin lines with name and frequency, the route white (straight from origin to destination for a manual plan),
      waypoints with idents up to 160 NM, runways, us as a green arrow in the middle, traffic as grey arrows with
      callsign and level (on the ground only when zoomed to 5–10 NM). Zoom 5–640 NM with the wheel or +/−. Colours
      come from the design tokens. Checked in the browser after `/fly 40`. 591 tests.
A7. **Flight log:** `logs/<date>_<callsign>.txt`, written as the flight goes in the transcript format, git-ignored.

UI code (JS/CSS) isn't unit-tested. It is checked in a browser against `--nosim`, while the Python side (events, API handlers, suggestion, log) gets tests.

### Milestone 3c — Desktop app (added 2026-11-14, user request)

The window becomes a real desktop app, prepared for a later public release. The HTML/CSS/JS stays as it is: the user
is happy with it, and every UI change needs their OK. Decisions:
- **pywebview** (6.2.1 with pythonnet 3.2.1, which supports Python 3.14) shows the existing page from the local server in its own window (WebView2). It replaces the Edge app mode.
- **A3–A7 come after the design pass** below, so new UI parts are designed only once.
- **Voice in the window runs automatically:** push-to-talk + whisper start with a flight, and the text box stays. Without a microphone or model, a message appears and typing still works.
- **Data with a licence is never shipped:**
  - the user's Little Navmap database (built from their installed scenery);
  - anything exported from it — `data/airports/*.json` are test data only, and EDDH comes from the payware simwings add-on;
  - Navigraph data, which isn't used anyway.

D1. ✅ **Paths:** read-only resources (page, `data/centers.json`) are found next to the code, or inside a PyInstaller build. User settings live in `%APPDATA%\MSFS ATC\settings.toml`; cache, models, logs, recordings and the window state in `%LOCALAPPDATA%\MSFS ATC\`. No absolute paths in the code. Licensed data sources are marked in the code.
    - **Done:**
      - `atc/paths.py` has `resources()` (the project folder, or `sys._MEIPASS` in a PyInstaller build), `config_dir()` = `%APPDATA%\MSFS ATC` (`settings.toml`) and `data_dir()` = `%LOCALAPPDATA%\MSFS ATC` (`cache/metar`, `cache/simbrief`, `models`, `recordings`, `logs`). `MSFS_ATC_HOME` moves both, e.g. for a portable copy.
      - `atc.example.toml` became `settings.example.toml`, and messages say `settings.toml`.
      - **Tests:** an autouse fixture sends all user folders to a temp folder; another test makes sure no `C:/Users` path is in the code.
      - **Licence notes** in `littlenavmap.py`, `export.py`, `config.py`, `simbrief.py`, `weather/source.py` and `data/airports/README.md` (test data, not to be shipped). 380 tests.
D2. ✅ **pywebview window:**
    - Remembers size and position, and checks the position is still on a connected screen (second monitor unplugged).
    - Backend and window start together. Closing the window stops the session and the server, so no process is left behind.
    - `--browser` opens the normal browser for debugging.
    - **Done:**
      - **`python -m atc.app` order:** server thread first, then `webview.create_window` (dark background, so no white flash; minimum 420 × 400), and `webview.start()` blocks. After closing: `shutdown()` stops the session (and with it SimConnect and the input threads), then the server.
      - **Geometry:** `GeometryTracker` follows `moved`/`resized`, ignoring minimised (-32000) and maximised states. It is saved to `window.json` in the data folder. `window_state.initial()` checks the saved position against `webview.screens`: at least 80 px with the title bar must be on a connected screen, otherwise the default 1100 × 760 is used.
      - **Fallbacks:** `--browser` opens the normal browser and `--no-window` only prints the address. If pywebview or WebView2 is missing, the browser opens with a hint. Started without a console (pythonw), messages go to `logs/app.log`.
      - **Removed:** Edge app mode and the "15 s without a stream" shutdown; pywebview knows when the window closes.
      - **Real check:** the window opened with pywebview 6.2.1/pythonnet 3.2.1 on Python 3.14, the page loaded in WebView2 with the stream connected, and the backend stopped 0.38 s after closing. No WebView2 process was left (6 before, 6 after). 390 tests.
D3. ✅ **Voice in the window:**
    - Push-to-talk + whisper with every flight.
    - The whisper model is downloaded on the first start into the models folder, with progress messages in the radio log.
    - A clear message if MSFS/SimConnect isn't reachable.
    - **Done:**
      - **Shared setup** (`atc/audio/setup.py`) for the console and the app: model, push-to-talk, ATC voice.
      - **Model lookup order:** our `models/<name>/` folder (complete only with its `.complete` marker), then the default Hugging Face cache (the developer's model from the spikes, so no second download), then a download.
      - **Download:** our own, small and readable. The file list comes from `huggingface.co/api/models/…`, then config/model/tokenizer/vocabulary are streamed in 1 MB pieces (`.part`, renamed when complete) with "Speech model: 120 of 464 MB" every 3 s. Without internet: "check the internet connection, typing still works".
      - **In the window:**
        - A `DeferredInput` lets the flight start at once; speech loads in the background (`Loading speech recognition…`, then `Push-to-talk ready: hold [right ctrl]…`). The model is loaded once per app and reused for every flight.
        - ATC speaks through Zira, and the window shows the text.
        - Without a microphone or model: "Voice is off: … Typing still works."
        - A microphone error during the flight becomes a message and listening goes on.
        - At the end of a flight the push-to-talk recorder is closed, so no old recorder listens next to a new one.
      - **MSFS:** one clear message ("MSFS is not running or SimConnect can't connect: start MSFS and load a flight, then try again…") for the console and the window, and also if SimConnect.dll can't be loaded.
      - **Server:** reads a POST body before answering, even an error, because Windows otherwise resets the connection and the page saw a reset instead of the error message. Bodies are capped at 64 KB.
      - **Found in the real checks:**
        - Polling the folder size didn't show progress, because huggingface_hub writes elsewhere first; hence the own download.
        - The cache lookup without a file list called the cached `small.en` "incomplete" (README missing) and started a second 464 MB download. Fixed, with a test.
      - **Real:** small.en is found in the HF cache and push-to-talk is ready 3.3 s after Start; tiny.en downloaded with progress 15 → 42 → 60 → 75 MB and recognised a recording. 403 tests.
D4. ✅ **`requirements.txt` + `start.bat`:** checks Python, creates/uses `.venv`, installs, starts the app, with readable errors.
    - **Done:**
      - **`requirements.txt`** pins the tested versions of the direct dependencies, so every install gets the known-good set; `pyproject.toml` keeps the minimums, and a test checks the two agree. `requirements-dev.txt` adds pytest and PyYAML.
      - **`start.bat`** (CRLF line endings, kept by `.gitattributes`):
        - **Python:** finds 3.12+ via `py -3`, then `python`. A candidate only counts if it reports its version, because `python` can be the Microsoft Store alias.
        - **Setup:** creates `.venv` and installs `requirements.txt`, and again only when the file changed (a copy in `.venv` remembers it).
        - **MSFS:** notes when it isn't running.
        - **Start:** the app without a console (`pythonw`), or in the console with options (`--browser`); `--setup-only` only sets up.
        - **Errors** each get a message and a `pause`: no Python, venv not created, broken `.venv` ("delete it, it is created again"), pip failed.
      - `ATC.bat` was replaced by `start.bat`.
      - **Tried in a fresh copy of the project:** setup took 36 s (pip cache), a second run 0.1 s, offline mode ran in the new `.venv`, and a broken `.venv` showed its message. 405 tests.
D5. ✅ **`BUILD.md`:**
    - PyInstaller one-folder build with an icon, and Inno Setup.
    - Things to watch: WebView2 runtime, SimConnect.dll, bundled static files, model download, data licences.
    - **Done:** [BUILD.md](BUILD.md) has:
      - what is ready in the code, the PyInstaller steps (`.spec`, `--windowed`, data and collect options), a table of things to watch, and an Inno Setup outline;
      - all data sources and library licences, from the installed packages' metadata.
    - **Findings for the user's decision before a public build:**
      - **Python-SimConnect is AGPL-3.0.** Shipping it means releasing the app AGPL-compatible with source, or replacing it with our own `ctypes` wrapper (step 26).
      - The redistribution terms of `SimConnect.dll` (MSFS SDK) and SimBrief's API terms still need checking.
      - faster-whisper needs its bundled `silero_vad_v6.onnx`, and comtypes needs a writable `gen` folder in a build.
D6. ✅ **Design pass:** first 2–3 short directions in words for the user to choose from, only then restyle (look only, no functional changes).
    - **Choice:** the user picked **A, "glass cockpit (ECAM)"** over "ATC strip board" and "FMS/MCDU amber", and asked for the at-a-glance status block in the same pass.
    - **Look:**
      - Colours after the Airbus convention, used sparingly: green = live values, amber = calls to notice, red = warnings only ("stop immediately", "go around", incursion), white/grey = text and labels. Background `#0a0e13`.
      - Fonts: **B612 / B612 Mono** (Airbus cockpit font, OFL 1.1), bundled in `static/fonts` so the app works offline.
      - Flat: 1 px lines instead of cards, square corners (inputs 2 px), a 4 px grid.
    - **Layout of the flight screen:**
      - An ECAM status strip: COM1 large in green with the tuned station; CALL = the controller to talk to, green when tuned, amber when not; PHASE; then SQK, CLR, RWY, ATIS, ALT (GND / FL / FT), GS.
      - The **last ATC message** large below it, then the radio log with UTC times (`1452Z`) and upper-case stations.
      - The setup screen uses the same style.
    - **Backend for the status (part of A4):**
      - `Controller.status()` returns phase, COM1 and tuned station, the controller to call (the handoff target if one is pending), runway, ATIS, squawk, cleared level (`5000 FT` / `FL350`), altitude, ground and speed.
      - `GET /api/status`, polled every second by the page.
    - **Found while checking in the browser and a real window:**
      - The form row overflowed (inputs' built-in minimum width).
      - "121. 705": a monospace dot is a full cell wide, so it is narrowed in the large frequencies.
      - The log lost its newest line when panels above it grew. A `ResizeObserver` now keeps it at the end unless the pilot scrolled up, with the browser's own scroll anchoring off.
    - **Checked** at 1100 × 760 and 480 × 720 (a small window next to MSFS) and in the real pywebview window. 410 tests.

### Milestone 3 continued

25. ✅ **First real flight end to end** (2026-11-14, the user, EDDH → EDDM with SimBrief and the app window).
    - **Worked well:** clearance and taxi.
    - **Missing, from the user's feedback:**
      - "Holding short runway 05" at a runway crossing (Hamburg) is not understood: today ATC crosses the pilot automatically, but the pilot expects to report and ask.
      - No Center/Radar frequencies ("EDWW has no frequency": EDWW is the Bremen FIR, not an airport; all sectors in `centers.json` are `PLACEHOLDER`).
      - The ATC voice was not heard at all in the app, and it sounds robotic without a radio sound.
      - ATC knows too few calls; the user wants a reference of all calls it understands.
      - FSLTL traffic is ignored.
    - The previous flight's radio log was lost when the app restarted (that is what A7, the flight log, is for).

### Milestone 4 — More ATC (added 2026-11-14, after the first flight)

Decisions from the interview (grill-me, 2026-11-14):
- **Runway crossings:** the pilot reports ("holding short runway 05"), ATC answers ("cross runway 05" or "hold short").
  ATC doesn't cross anyone on its own any more.
- **Center frequencies:** taken from the user's MSFS data through Little Navmap (`boundary` table, e.g. Bremen
  Radar 119.825 / 125.100, Langen Radar 118.750), never shipped. `centers.json` stays for manual overrides.
- **Voice:** Piper (local neural TTS), one voice per controller, and a radio effect. The "no sound at all" bug comes
  first.
- **FSLTL:** read the AI traffic from MSFS (that is how FSLTL traffic appears; nothing of FSLTL is bundled). Use it for
  the runway and taxiways, for traffic information in the air, and for AI radio chatter.
- **New calls:** all four packages (ground, tower, en route + approach, general), researched on VATSIM Germany pages
  and other phraseology sources. Those pages are DFS/VATSIM material: we write our own phrases and don't copy text.
- **Apron:** a separate Apron station where the MSFS data has one (a Ground frequency whose name contains "APRON",
  e.g. EDDM `MUNICHAPRON1..3`); otherwise Ground does it all, as today. Hamburg has none in MSFS.
- **In the air:** step climbs and descents, direct-to on route waypoints, the STAR from the SimBrief plan, radar
  vectors to the ILS, speed instructions. This replaces the "direct to the 10 nm final fix" approach.
- **Reference of calls:** a "Phrases" tab in the app, sorted by phase (pilot says / ATC answers / readback), with the
  current phase on top, plus the suggested next call above the text box (A5). Both come from one catalogue in the
  code, which the tests check against the parser, so the help never promises a call the parser can't read.
- **Order:** fix what bothered the user in the flight first, then the voice, the calls, native SimConnect, FSLTL.
- **Working mode:** `/loop`, step by step: tests + offline mode after each step, one commit per step. **Stop after
  each package** with a short "how to test it in MSFS" note. Big decisions are still asked first.

#### Package 1 — Fixes from the first flight

F1. ✅ **ATC voice: find why nothing is heard in the app.**
    - pyttsx3/SAPI runs in a thread under pywebview (and `pythonw` without a console). It was only ever checked in
      the console; the app tests switch TTS off. Reproduce it in the real window, find the cause (COM apartment,
      the engine's event loop, the output device), fix it.
    - A failed `say()` must become a visible "ATC voice failed: …" note instead of silence.
    - Test with a fake engine, plus a real check in the window.
    - **Done:**
      - **Cause:** pyttsx3 2.99 spoke only the *first* transmission. From the second on, `runAndWait()` returned
        after 0.1 s without a sound, in the console as well as in the window. Step 23's check had spoken one
        sentence only. Measured with the volume at 0: 4.2 s, then 0.1 s, 0.1 s.
      - **Fix:** `atc/audio/tts.py` talks to SAPI directly through comtypes (`SAPI.SpVoice`, `Speak(text, 0)`
        blocks until spoken) in the speech thread. `dynamic=True` means comtypes generates no wrapper code, which
        also solves the read-only `comtypes\gen` problem of a build. pyttsx3 is no longer a dependency. `[tts] rate`
        stays words per minute and is converted to SAPI's -10..10.
      - **Second bug in the app:** the voice was only made after the whisper model had loaded, so without speech
        recognition there was no ATC voice either. Now the voice starts first ("ATC voice: Microsoft Zira…") and
        doesn't depend on whisper.
      - A failing transmission becomes a note "ATC voice failed: …" in the radio log, and the next one is tried
        again.
      - **Real check:** three transmissions in a row took 5.3 / 2.7 / 4.5 s each in the console and in a pywebview
        window under `pythonw`. 413 tests.
F2. **"Holding short runway X"** at a runway crossing:
    - The parser understands "holding short (of) runway 05", "holding short 05", "ready to cross runway 05",
      "request crossing runway 05".
    - At a crossing hold-short, Ground answers "cross runway 05", the pilot reads back "crossing runway 05", and the
      taxi route continues. The automatic crossing goes away. Before the departure runway, the same call is answered
      by "contact Tower …" (or by Tower when tuned).
    - If the pilot stands silent at the hold-short for 15 s, a hint shows the call to make. It is a hint, not an ATC
      transmission: the pilot should learn to report.
    - The safety check stays: entering the runway without a crossing clearance → "stop immediately".
    - Scenario tests for EDDH (crossing) and for the departure holding point.
    - **Done:**
      - **Parser:** a new intent `holding_short` for "holding short (of) (runway) 05", "ready to cross runway 05"
        and "request crossing runway 05". "crossing runway 05" stays a readback, and so does a taxi readback that
        ends in "holding short …" (it has taxiways in it).
      - **Controller:** ATC no longer clears a crossing on its own. The report gets "cross runway 05" (readback
        "crossing runway 05"), also for a runway that isn't on our route, because the pilot may have taxied
        another way. Without a runway in the call, the next crossing on the route is meant. The departure runway
        means "ready": Ground hands off to Tower, Tower clears for takeoff. An unknown runway: "say again the
        runway".
      - **Hint after 15 s:** stopped (≤ 2 kt) at the hold short without a call, the log shows once what to say.
        The controller doesn't read a clock: the live loop passes its time into `tick(state, now)`. Text mode and
        the scenario tests pass none and get no hint, so they stay deterministic.
      - **Found on the way:** the old crossing test's "on the runway" position was beside the runway, so "no
        incursion after the clearance" proved nothing. Both crossing tests now stand on the centreline.
      - **Tests:** the report variants, the hint (once, not while rolling, not without a clock), the departure
        runway, an unknown runway, and the scenario `runway_crossing` (EDDH runway 15 across 05/23, as in the
        user's flight). 424 tests.
F3. **Center frequencies from Little Navmap:**
    - Read the Center/FIR rows of `boundary` (name, frequency, polygon: big-endian int32 count + float lon/lat pairs)
      once per session, near the route only. The data has no altitude bands (all GND–UNL), so where sectors overlap
      the smallest polygon wins.
    - The spoken name comes from the data ("BREMEN" → "Bremen Radar", "LANGEN" → "Langen Radar"). The handoff says
      the frequency. A sector without a frequency is still "whose airspace", without a handoff (no made-up values).
    - `centers.json` entries win over the import, for corrections. Without Little Navmap (tests, `--nosim`) the JSON
      file is used as today.
    - Licence note in the code and BUILD.md: user data, never shipped. Also fix the misplaced comment on
      `CenterSector.khz`.
    - **Done:**
      - **`atc/airspace/littlenavmap.py`** reads the 4201 Center rows (type `C`, `com_frequency` in kHz here) in
        0.04 s. Names: "BREMEN" → "Bremen Radar", "LANGEN RADAR" stays, "FRANKFURT 1" → "Frankfurt Radar"; German
        and Dutch ACCs say "Radar", others "Control". Sorted smallest first, so overlaps go to the smaller sector.
      - **Lookup stays fast** with a bounding-box test before the polygon test: under 1 ms per tick.
      - **centers.json:** sectors with a real frequency come first and win (corrections, e.g. a wrong MSFS name);
        its PLACEHOLDER boxes are dropped when the database is there, and used as before without it.
      - **Found:** Bremen Radar has two sectors (125.100 and 119.825). The station key was name + FIR, so moving
        from one to the other was no handoff. The frequency is now part of a Center's key.
      - **Real check** (fake sim along EDDH → EDDM, the user's database): Hamburg Approach → Bremen Radar 125.100
        (18 nm) → Bremen Radar 119.825 (27 nm) → Berlin Radar 125.800 (126 nm) → Frankfurt Radar 127.600
        (182 nm) → descent. MSFS's data still uses old names in places (EDFF "Frankfurt" is today's Langen Radar).
      - Tests use a small database made in the test; an autouse fixture keeps the developer's real database out
        of all other tests. 436 tests.
F4. **Flight log (A7):** `logs/<date>_<callsign>.txt`, written line by line as the flight goes, in the transcript
    format, so a flight's history survives a restart and can be sent along with a bug report.
    - **Done:** `atc/flightlog.py` writes `logs/2026-11-14_2145Z_DLH4AB.txt` (UTC; `_2` instead of overwriting).
      The banner comes first as `#` lines, then one line per event with UTC time and who spoke
      (`21:45:21Z  ATC    Hamburg Ground: …`), flushed at once so a crash loses nothing. The console and the
      app (one file per flight) both use it through a `Tee` sink, and the path is shown at the start
      ("Flight log: …"). A callsign can't make a path. 441 tests.

**Stop: the user tests F1–F4 in MSFS.**

#### Package 2 — Voice

V1. **Piper TTS** as a second `TextToSpeech` backend; SAPI stays the fallback.
    - **Licence check first, then ask the user:** current `piper-tts` releases are GPL-3.0 and use espeak-ng
      (GPL-3.0). That matters for a public build just like the AGPL SimConnect package does.
    - Voices are downloaded on first use with progress, like the whisper model, never bundled. Each voice's own
      licence is checked and listed in BUILD.md.
    - One fixed voice per station (Clearance, Ground, Tower, Approach, each Center), chosen deterministically from the
      station name, so the same controller always sounds the same.
    - **Done:**
      - **Licence (user's decision):** piper-tts 1.8 is GPL-3.0-or-later with espeak-ng inside. The user chose to
        use it directly, so a public build will be open source under the GPL-3.0 (BUILD.md).
      - **Voice:** `en_US-libritts_r-medium` (LibriTTS-R, CC BY 4.0): one 79 MB model with 904 speakers. Voices
        with non-commercial or restricted data (ryan, hfc_male, lessac) are left out on purpose. It is downloaded
        on the first start into `models/piper/` with progress ("ATC voice: 43 of 79 MB"), through the same
        `setup.fetch()` as the whisper model.
      - **A speaker per controller:** `crc32(station name) % 904` (not `hash()`, which changes per start). Hamburg
        Ground is speaker 894, Hamburg Tower 611. The station travels with the event: `say(text, station)`.
      - **`QueuedSpeech`** is the speech thread both voices share; `SapiOutput` and `PiperOutput` only say how to
        start and how to speak. Playback through sounddevice.
      - **Fallback:** if Piper can't start (no internet on the first start, …) the log says so and the Windows
        voice speaks. `[tts] engine = "sapi"` chooses it; `[tts] rate` works for both.
      - **Found:** a test really downloaded the 79 MB voice, because `http=setup._http` as a default is bound
        when the function is defined, so the monkeypatch missed it. Fixed (looked up at call time, also for
        whisper), and an autouse fixture now blocks every download in the tests.
      - **Real check:** model start 0.7 s, then 3.4–4.5 s per transmission (synthesis ~0.3 s, the rest is the
        playback, of silence for the check) in the console and in a pywebview window under `pythonw`. 447 tests.
V2. **Radio effect:** band-pass about 300–3400 Hz, light compression and clipping, a little noise, a squelch click at
    the start and end. numpy + sounddevice, in our own code. `[tts] radio_effect = true` can switch it off.
    - **Done:** `atc/audio/radio.py`, numpy only. Key click (60 ms of fading noise), the voice through `tanh`
      soft clipping (drive 4: loud and a little rough, like the radio's gain), a little hiss, the squelch tail
      (120 ms) when the button is let go, then band-pass 300–3400 Hz in the frequency domain with soft cosine
      edges (after the noise, so the hiss is narrow-band too), normalised to 0.8. The noise is seeded from the
      text, so a transmission always sounds the same. 35–50 ms per transmission. Piper only: SAPI speaks straight
      to the sound card. Tests check the band (100 Hz and 6 kHz at least 26 dB down), the level, the squelch and
      the seed. Listening samples were sent to the user. 453 tests.
V3. **ATC says more:**
    - Speak every ATC transmission, including the short ones ("readback correct", "roger", "good day").
    - Don't talk over the pilot: an ATC answer waits until push-to-talk is released.
    - Check against a full scenario that nothing ATC "says" in the log is silent.
    - **Done:**
      - **Every transmission is spoken:** only `atc` and `atis` events are transmissions, and each reaches the
        voice with its station (test). "(readback correct)" stays a silent note: real controllers say nothing
        after a correct readback (except for the clearance, where "readback correct" is spoken). The main reason
        ATC "said too little" was the F1 bug.
      - **Where ATC stayed silent or said "say again"** (found by calling the right controller in every phase):
        - a first call with nothing in it ("Hamburg Ground, Lufthansa 4AB") → "…, Hamburg Ground, go ahead";
        - "pushback complete" → "roger, report ready for taxi";
        - Tower check-in at the holding point ("with you", "holding point runway 23") → "report when ready for
          departure";
        - a position report ("maintaining flight level 350") → "roger";
        - "established" to Approach → the handoff to Tower at once, instead of waiting for 12 nm;
        - calling Ground after landing → the taxi instruction.
        - Plain calls now go to the phase's controller on the ground too (`PHASE_ROLE`), so a call to the
          wrong one gets "contact …" instead of "say again". "roger"/"wilco" still need no answer.
      - **No talking over the pilot:** the speech thread waits while the push-to-talk key is down
        (`QueuedSpeech.hold`, the key polled like the recorder does), in the console's voice mode and the app.
      - 462 tests.

**Stop: the user listens in MSFS.**

#### Package 3 — New calls and the Phrases tab

P1. **Phrase catalogue** (`atc/phraseology/catalog.py`): every call per phase with the pilot's example, ATC's answer
    and the readback. Tests parse every example and check the intent and values, so catalogue and parser can't drift.
    - **Done:** 29 phrases in 7 groups (Clearance, Ground, Tower, Departure and Center, Approach, Arrival Tower and
      Ground, Any time), each with the pilot's call (placeholders filled from the flight, or from `EXAMPLE`), ATC's
      answer in words, the intent and the values the parser must find, and a note. Our own wording, nothing copied
      from DFS/VATSIM pages. `tests/test_catalog.py` parses every example. Found: "passing 3000 feet climbing 5000
      feet" reads as 3000 ft (the first altitude); harmless for a check-in, so the catalogue doesn't promise the
      climb value. 494 tests.
P2. **Phrases tab + suggested call (A5)** in the app. This is a UI change: first show the user the layout in words,
    then build it in the ECAM style.
    - **Layout (user's choice):** tabs RADIO | PHRASES in the radio section, and an amber NEXT row above the text box
      (a click puts the call into the text box; it is never sent by itself).
    - **Done:**
      - **`atc/controller/suggest.py`:** `suggestion()` = the readback with exactly the pending values, written as
        a pilot says them ("runway 15, climb 5000 feet, squawk 4502, Lufthansa 4AB"), addressed to the controller
        waiting for it, or the next call of the flight (clearance, pushback, taxi, holding short at a crossing,
        ready for departure, check-ins after each handoff, request taxi after landing), or nothing while taxiing
        or cruising. It comes with `/api/status`. `phrase_book()` = the catalogue with the flight's stations,
        runway, ATIS letter, squawk; the current phase's group first (`GET /api/phrases`).
      - **Controller:** `expected_station()` (the CALL display), `readback_station()`, `call_next` (handed over,
        not called yet), `next_crossing_here()`, `at_departure_holding_point()`.
      - **Main test:** EDDH → EDDM gate to gate saying only the suggestions: every one is understood and every
        readback is correct. It found that a "contact …" readback must go to the *old* controller, while CALL
        already shows the new one.
      - **Found in the browser check:** the app crashed (access violation) with a `[tts] voice` that doesn't exist:
        SAPI's COM object was freed by the garbage collector in another thread. Fixed in its own commit: the speech
        thread releases its engine itself.
      - **Checked in the browser** at 555 px and 1100 × 760: tabs, phrase book, NEXT → text box → Enter → the
        clearance, then NEXT shows the readback with the real squawk. 501 tests.
P3. **Ground:**
    - the Apron station (see decisions): pushback and taxi on the apron, handoff to Ground at the end of the apron
      part of the taxi route;
    - pushback "facing east/west" / "tail north…";
    - "hold position", "continue taxi", "give way to…" (the traffic parts arrive with T2);
    - "request taxi via…", "request startup".
    - **Done** (without traffic, "hold position" and "give way" have no reason yet: they come with T2; "request
      taxi via …" left out, "startup" already means push and start):
      - **Apron:** `Frequency.role` is "APRON" for a Ground-typed frequency whose name says APRON/RAMP, and the
        station key uses the role (before, Apron and Ground were *one* controller, because both are typed "G"). Spoken
        "Munich Apron" instead of "Munichapron1 Ground". At EDDM: Delivery → Apron (push, taxi) → Ground when the
        aircraft is more than 150 m from every parking position → Tower. Arriving: Ground → Apron within 150 m of a
        stand, "continue to stand …". Where the data has no Apron (EDDH), Ground does it all, as before.
      - **Pushback "facing east/…":** the direction of the taxi route's first segment after the stand's lead-in,
        so the nose points the way to taxi. EDDH G 1: "facing west" (both golden files changed by this line).
      - **Check-in with Ground while taxiing:** "continue taxi to holding point runway …".
      - **Found:** "push and start approved, Lufthansa 4AB" (and "continue taxi", "pushing back") got "say again":
        a readback without values. Now an acknowledgement.
      - 513 tests.
P4. **Tower:** "line up and wait", "report ready", departure from an intersection, "wind check", "cancel takeoff
    clearance" and "continue approach" (ATC-initiated ones become useful with traffic in T2).
    - **Done:**
      - **"request line up (runway 23)"** → "runway two tree, line up and wait" (readback runway + line up); the
        runway counts as cleared, so standing on it is no incursion; then "ready" gets the takeoff clearance, and
        the NEXT row suggests it.
      - **Intersection departure:** "ready for departure from intersection Alfa 4" → "runway two tree from
        intersection Alfa four, cleared for takeoff", but only if a taxiway of that name ends on the departure
        runway (within its half width + 60 m). EDDH 23: A1–A6, D1–D9; "Bravo 4" (runway 15/33) gets "is not an
        intersection of runway two tree, say again". New intent item `intersection`.
      - **"wind check"** on any frequency, at the current airport (origin, or the destination once airborne).
      - ATC-initiated "line up and wait", "cancel takeoff clearance", "continue approach" wait for traffic (T2).
      - 521 tests.
P5. **En route and approach:**
    - Departure: radar contact, climb in steps, direct to the next route waypoint.
    - Center: handoffs from F3, pilot requests ("request higher / lower / direct …", "request descent"), step
      descents.
    - Arrival: the STAR from the SimBrief plan ("descend via…" or "cleared … arrival"), radar vectors to the ILS
      ("turn left heading 230, descend 4000 feet, … cleared ILS approach runway 26R"), speed instructions.
    - All values are computed from geometry and the plan, deterministically.
    - **P5a done:** `FlightPlan.waypoints` from SimBrief's navlog (position, and "sid" / "route" / "star" by the
      `via_airway`), plus `sid` and `star`. TOC/TOD and airports left out. A manual plan has none.
    - **P5b done:**
      - **Step climb:** with Center sectors, Departure climbs to FL240 at most; the first Center's check-in gives
        "identified, climb flight level 350" (without sectors Departure still gives the cruise level).
      - **Direct-to:** a route clearance, so a readback item now (`direct`, "read back direct-to"). Departure:
        direct to the first fix after the SID, as before. First Center: the farthest SimBrief route point ahead
        within 150 nm (a shortcut).
      - **Requests:** "request higher" (to the cruise level), "request flight level 370" (climb or descend, up to
        FL410), "request direct LULAR" (only a plan point still ahead; with a manual plan, any fix written in the
        route). New intents `request_level`, `request_direct`.
      - Golden files: Departure's FL240 in `center_sectors` (its script reads back the step climb now), and
        `direct=AMLUH` in the parser lines. 533 tests.
    - **P5c done:**
      - **Descent in steps:** at the top of descent the en-route controller gives "descend flight level one hundred"
        (above FL110; lower aircraft get the altitude with the QNH as before), and Approach's clearance now brings
        the QNH (below the German transition altitude of 5000 ft altitudes are on QNH).
      - **STAR:** with a SimBrief plan (or a STAR as the last route token) the descent says "cleared Landu two Alfa
        arrival" (`spoken_star`). Not a readback item yet: whisper writes procedure names too differently to
        compare them reliably; a later step could match them fuzzily.
      - Golden files: FL100 instead of 5000 ft at the top of descent, the QNH in the approach clearance. 534 tests.
    - **P5d done (radar vectors and speeds):**
      - **First call to Approach:** "descend altitude 4500 feet, QNH 1019, speed 220 knots, fly heading 185,
        vectors ILS approach runway 08R". The heading points at a spot 14 nm out on the extended centreline
        (magnetic, in 5-degree steps).
      - **The turn onto the localizer** within 3 nm of that spot (or once inside the final cone, 15 degrees / 18 nm):
        "turn left heading 110, maintain 4500 feet until established, cleared ILS approach runway 08R, speed 180
        knots": course + 30 degrees from the left side, course - 30 from the right, the turn the shorter way. Already
        on the centreline (within 3 degrees, e.g. after `/final 10`): only "cleared ILS approach …, speed 180 knots".
        Already in the cone at the first call: the old direct clearance. Then "established" → Tower, as before.
      - Scenario scripts get `{heading}` (the vector waiting for its readback); `normal_flight` and `go_around` fly
        the vectors now. A shared test helper `cleared_ils()`.
      - **Not covered:** the fake sim doesn't fly headings, so in practice mode the vectors are read back and then
        `/final 10` jumps onto final; with MSFS you fly them.
      - Once in about 30 runs, `test_app.py` timed out after 5 s under load; not reproducible (8 × green).
      - 535 tests.
P6. **General:**
    - "say again" from the pilot: ATC repeats its last transmission;
    - "standby", "unable", "wilco/roger";
    - "request QNH", "request weather at destination";
    - "squawk ident", "confirm …".
    - **Done:**
      - "say again" (repeat the last transmission) and "wilco/roger" already worked; "confirm" alone does the same.
      - **"standby"** and "squawking ident" are acknowledgements (before: "say again"; before the clearance even
        "request IFR clearance first").
      - **"unable (…)"** withdraws the instruction waiting for its readback: "roger, maintain present heading and
        level, standby", and a note to say what is possible ("request flight level 330"). Before, "unable" counted
        as a readback and ATC kept asking for the values.
      - **"request QNH"** → the current airport's QNH, read back like every altimeter setting.
      - **"request weather (at Munich)"** → the destination's METAR as spoken (the ATIS text builder): wind, CAVOK
        or visibility/weather/clouds, temperatures, QNH.
      - **"confirm cleared ILS runway 08R"** → "affirm" if it matches the last instruction, "negative, runway two
        tree" with the right value, "negative, say again" for something not given. A pending readback stays due.
      - ATC-initiated "squawk ident" has no reason without traffic or a radar problem; left out.
      - 546 tests.

**Stop: the user flies with the new calls.**

#### Package 4 — Native SimConnect

S1. **Our own `ctypes` SimConnect wrapper** (old step 26) instead of Python-SimConnect (AGPL-3.0). Same `SimState` as
    today, so the controller doesn't notice. Removes the licence problem in BUILD.md. **Ask the user before starting**
    (big change to the sim layer).
    - **DLL (user's choice):** search for SimConnect.dll; a release build copies it from the MSFS SDK.
    - **Done:**
      - **`atc/sim/native.py`:** `Dll` is the only code that calls SimConnect.dll (Open, AddToDataDefinition,
        RequestDataOnSimObject, GetNextDispatch, Close, and RequestDataOnSimObjectType for S2). `NativeSimConnect`
        builds one data definition per group (aircraft state, weather) with the same simvars and units Python-SimConnect
        used, so `state_from_simvars` didn't change. A tick asks once for the whole group and keeps it 0.2 s; no answer
        within 1 s = `None` (stale, last state kept); MSFS quitting = an error the source also treats as stale.
      - **`find_dll()`:** `simconnect_dll` in settings.toml, next to the app, the MSFS SDK (`MSFS_SDK` /
        `MSFS2024_SDK`, set by its installer; no fixed paths in the code), then an old Python-SimConnect package (its
        DLL only). Not found: a message how to get it.
      - Python-SimConnect (AGPL-3.0) is out of the requirements and BUILD.md.
      - **Tests:** a fake DLL answering with real `SIMCONNECT_RECV_SIMOBJECT_DATA` bytes (also foreign and empty
        messages in between), the timeout, quitting, strings, the search order.
      - **Real check without MSFS:** the real DLL loads through ctypes, Open fails, the usual message in 0.44 s.
        **With MSFS: not checked yet (the user).**
      - On a fresh PC (new `.venv`) without the MSFS SDK there is no DLL now; this PC still has the old package's.
      - 555 tests.
S2. **AI aircraft list:** all aircraft within ~40 nm (position, altitude, ground speed, heading, on ground, ATC ID,
    type) through `RequestDataOnSimObjectType`. A fake traffic source for tests.
    - **Done:**
      - `atc/sim/traffic.py`: `Traffic` (object ID, position, altitude, ground speed, true heading, on ground,
        registration, airline, flight number, model; `callsign` = "Lufthansa 123", else the registration),
        `TrafficSource`, and `FakeTraffic` for tests and practice mode.
      - `NativeSimConnect.objects()` collects the `SIMOBJECT_DATA_BYTYPE` answers ("entry n of m"; "of 0" = nobody
        around), `SimConnectSource.traffic()` reads 40 nm around us and drops our own aircraft (`IS USER SIM`).
        No answer or MSFS gone: an empty list, never an error.
      - **`python -m atc.sim.check`:** connects, prints the aircraft state three times with the time per read, the
        weather, and the aircraft around. For the user's test with MSFS (and FSLTL).
      - Tests: real BYTYPE layouts with numbers and strings, our own aircraft left out, nobody around, a missing
        answer, the check command with a fake sim. 562 tests.
      - **Not checked with MSFS yet:** whether MSFS really packs the strings without gaps and what FSLTL puts into
        ATC AIRLINE / ATC MODEL; the check command shows it.

**Stop: the user checks the connection in MSFS.**

#### Package 5 — FSLTL traffic

T1. **Traffic model:** each AI aircraft gets a state (parked, taxiing, on the runway, departing, on final, en route)
    from its position and the airport data. FSLTL and default AI traffic look the same through SimConnect.
    - **Done:** `atc/controller/traffic.py`. Each aircraft is judged against the nearer of origin and destination:
      parked / taxiing (> 3 kt) / on_runway (inside a runway's protected area, the same zones as the incursion
      check) on the ground; in the air "final" (within 10 nm and 4000 ft AGL, 10 degrees of the extended centreline,
      heading within 30 degrees of the runway), "departing" (within 5 nm and low, right after a runway), else
      "airborne". `TrafficPicture` keeps the states and reports the changes as transitions (final → on_runway =
      landed), and answers "who is on runway 05" / "who is on final for 05/23 within 4 nm". The live loop reads the
      traffic every 3 s and hands it to `Controller.update_traffic()`. 567 tests.
T2. **Runway and taxiways:** runway occupied → "line up and wait" or no takeoff clearance yet; traffic on final →
    "hold short"; landing clearance only when the runway is free, else "go around, runway occupied"; a crossing
    clearance only when nothing lands or departs; "give way to…" on taxiways.
    - **Done:** a runway is busy with an aircraft on it or one on final within 4 nm. Departure: landing traffic or
      someone standing on it → "hold short runway 23, landing traffic, I will call you"; a departure rolling ahead
      → "behind the departing traffic, line up and wait"; once free ATC gives the takeoff clearance by itself.
      Landing: "continue approach, traffic on the runway, I will call you", the clearance comes by itself; still
      occupied at 2 nm (or at 1 nm after the clearance) → "go around …, runway occupied". Crossing: "hold short
      runway 05, landing traffic", then "cross runway 05" by itself. "Give way" on taxiways is left out (it needs
      a guess where the AI taxis). 574 tests. **Not checked with MSFS/FSLTL yet.**
T3. **Traffic information in the air:** "traffic, two o'clock, five miles, opposite direction, one thousand feet
    above", with fixed thresholds.
    - **Done:** in the air, an aircraft closer than 5 nm and within 1500 ft gets "traffic, two o'clock, four miles,
      opposite direction, one thousand feet above" from the controller we talk to (the clock from our true heading,
      "twelve o'clock" as a whole number; same / opposite direction within 45 degrees, else crossing left to right
      or right to left; "same level" within 300 ft). Once per aircraft, again only after it was beyond 8 nm. "traffic
      in sight", "looking out", "negative contact" are acknowledgements. 582 tests.
T4. **AI chatter:** radio calls for AI aircraft on the same frequency, derived from what they really do (taking off,
    landing, handoffs), with other Piper voices. Seeded, so tests are repeatable. Never during the pilot's own
    transmission, and `[traffic] chatter = false` switches it off.
    - **Done:** on the Tower or Ground (Apron) frequency the pilot is tuned to, the AI's exchanges with that
      controller, from their transitions since the last update, one exchange per update (every 3 s):
      - Tower: an aircraft turning onto final → "Hamburg Tower, Lufthansa one two three, established ILS runway two
        tree" / "…, wind …, runway two tree, cleared to land" ("continue approach" with another one on the runway);
        an aircraft rolling onto a runway from a taxiway → "…, runway two tree, cleared for takeoff" and its readback
        (the runway end it points at).
      - Ground: an aircraft starting to taxi from parking → "request taxi" / "taxi to holding point runway …".
      - Callsigns: "Lufthansa one two three" (FSLTL's airline name, or its ICAO code through the telephony list),
        else the registration spelled. Nothing is made up: only what the aircraft really did is said, so no seed is
        needed. A new event kind `chatter`: grey in the window, `[Lufthansa 123] …` in the console, `RADIO` in the
        flight log, spoken with Piper (the AI pilot gets a speaker of its own, the controller keeps its voice) and,
        like ATC, never while push-to-talk is held. `[traffic] chatter = false` switches it off.
      - 588 tests. **Not checked with MSFS/FSLTL yet.**

**Stop: the user flies with FSLTL.**

### Milestone 5 — Calmer app design (added 2026-11-15, user request)

The user looked at BeyondATC and SayIntentions and picked a draft on a design canvas: one column like SayIntentions,
but clearer, and calmer colours (muted sage green instead of the bright ECAM green, a sand tone for "do something").
Layout of the flight screen, top to bottom: radio box (COM1 · NEXT · XPDR), tabs ATC / Map / Phrases, the airport
with its frequencies, the flight in one line, a banner only when something is due, the radio log with a station
label on the left, then the suggested call, push-to-talk, text box and a few big buttons. Settings like SayIntentions:
sections in a sidebar.

R1. ✅ **Flight screen** in the new layout and palette (the setup screen too).
    - **Done:** new `index.html` / `app.css` / `app.js`. Status gains `airport` (one frequency per job in flight order,
      runway, QNH, wind; the origin until airborne, then the destination), `next` (the controller to call if not
      tuned, else the next one in the flight, skipping one already tuned: EDDH Ground does Delivery, so NEXT is
      Tower), `flight` (SID, STAR, destination), `callsign`, and from the app `ptt` (loading / ready / off).
      Log rows: a station label with its frequency (filled in once the status knows it), the message with the
      time; the parser's "understood" lines stay in the flight log file only, "readback correct" is a ✓ behind
      the pilot's line. The banner shows a due readback, or a warning for 30 s. Quick buttons fill the text box
      ("Hamburg Ground, Lufthansa 4AB, say again"). Checked in the browser.
R2. ✅ **Phrases** split into group tabs (Clearance, Ground, Tower, …) to click through; the current phase's group open.
    - **Done:** one tab per group, a dot on the groups of the current phase, the first of them open until the pilot
      picks another; a new phase opens its group again. 595 tests.
R3. ✅ **Map with the real taxiways** (from the airport data we already have, no new Little Navmap work) and the taxi
    route; closer zoom levels.
    - **Done:** `map_data()` gives each airport its taxi segments from the taxi graph (names carried along the
      taxiways, as in ATC's taxi instructions; most raw MSFS segments are unnamed: EDDH 100 of 630), the stands, and
      the runways with names and width; `moving()` adds the taxi route while it is being taxied (out or in) and
      whether we are on the ground. The page draws taxiways and their names (one label per taxiway every ~150 px,
      never on top of another) at 5 NM and closer, runways to scale with their numbers, stand names at 1 NM, and the
      route in green. Zoom 1–640 NM; 2 NM on the ground and 40 NM in the air until the pilot zooms. EDDH's map data
      is 177 KB, fetched once per flight. Checked in the browser after a taxi clearance. 597 tests.
R4. ✅ **Settings page:** sections (General, Audio, Controls, Traffic, Simulator, About) in a sidebar, saved to
    settings.toml.
    - **Done:** `atc/settings_file.py`: the editable settings (SimBrief name, voice engine / Windows voice / rate /
      radio effect, microphone, push-to-talk key, AI chatter, SimConnect.dll and Little Navmap paths), each checked
      (a wrong value names the setting), written as TOML with only what differs from the defaults, read back by the
      normal `load_config`. `GET/POST /api/settings`; the app saves where it loaded from (`--config`, else
      `%APPDATA%\MSFS ATC\settings.toml`); a changed voice or speech model is loaded again with the next flight.
      The page: the gear opens it from any screen, sections on the left, one card at a time, Save with a status
      line; About shows the folders and the credits. Checked in the browser (a wrong rate is refused, a good one
      saved). 606 tests.
R5. ✅ **Own push-to-talk binding:** press the key or joystick button to bind it, plus a spare (see A3).
    - **Done:** `atc/audio/ptt.py`. A binding is text in settings.toml: an old name ("right ctrl"), "key:0xA3" (any
      Windows virtual key, side mouse buttons included; never left/right/middle click) or "joy:0:5" (winmm
      joyGetPosEx: up to 16 devices, 32 buttons each). `[whisper] ptt_key2` is a spare; the recorder and "ATC waits
      while you transmit" listen to both. Settings › Controls: "Set", then press it within 10 s (`POST
      /api/ptt/capture`), "Clear" for the spare; names like "Right Ctrl", "Joystick 2 button 5".
    - **Found on the user's PC:** two joysticks, with buttons Windows reports as held all the time (switch positions:
      joystick 1 button 17, joystick 2 buttons 3, 4, 14, 20, 25, 30), and winmm answers 0 for the first ~0.1 s. The
      first capture took "Joystick 2 button 3" without anyone pressing anything. Now capture learns for 0.3 s what
      is down already and only takes a new press. Checked: 3 s with nothing pressed gives nothing. 624 tests.
    - **Not checked:** binding by really pressing a key or button (only the user can).

R6. ✅ **Strict readbacks** (user's wish, 2026-11-15: "always read back"). Setting `[atc] strict_readback`, on by
    default, in Settings › General › Training. Before, a readback was checked only when the pilot answered the same
    controller, so three things slipped through: switching frequency without reading back "contact …", the pushback
    approval, and saying nothing. Now: calling the new controller first gets a hint "read back first to Hamburg
    Ground on 121.705: …" and no answer; the pushback approval is a readback item (`pushback`, parsed from "push and
    start approved" / "pushing back"); after 20 s of silence ATC asks "read back" once (live clock). Without the
    setting nothing changes (a pushback readback still gets no answer). The STAR stays unchecked (see P5c). 628 tests.

R7. ✅ **Spoken confirmations** (user's wish, 2026-11-15). Every correct readback gets "readback correct" aloud (in
    the same transmission when ATC has more to say). A readback of a frequency change gets the controller's goodbye
    in the country's language from the ICAO prefix ("tschüss" / "schönen Tag noch" in Germany, "servus" in Austria,
    "au revoir" in France, "good day" elsewhere; `atc/phraseology/farewell.py`), one phrase per controller. Piper
    speaks just these words with their own language's sounds (raw phonemes from espeak). Accents in the voices: asked
    for, then dropped by the user. 652 tests.

### Milestone 6 — LiveTraffic (added 2026-11-15, user decision)

The user moves from FSLTL to **LiveTraffic MSFS** (flightsim.to addon 116297, by AVAILOFF, MSFS 2020 and 2024): real
aircraft from public ADS-B feeds (adsb.fi, adsb.lol), replayed ~60 s behind real time as sim objects that push back,
taxi, take off and land. Nothing of it is used or shipped: we read what the sim reports, as before. The traffic
**doesn't listen to ATC**: on the ground it stops behind the user, in the air it doesn't avoid. So our ATC works
"1:1 like the real thing, but the others always have priority" (the user's words): it moves the user around the
real traffic. All four situations below were picked by the user.

L1. **See LiveTraffic:** with MSFS and LiveTraffic running, `python -m atc.sim.check` lists the aircraft: check they
    come as AIRCRAFT objects, which callsign / airline / flight number / type simvars they carry, ground speed and on
    ground. ADS-B drops out for 40–90 s on the ground, so an aircraft missing from one reading is kept for a while
    instead of disappearing (no false "request taxi" when it comes back). Texts that say FSLTL say "traffic
    (LiveTraffic, FSLTL or MSFS)".
    - **Checked with MSFS at EDDH (2026-11-15):** 160 aircraft within 40 nm, all AIRCRAFT objects, in 0.05 s.
      LiveTraffic's airliners (FSLTL models, title "FSLTL_FAIB_A319_EJU-EasyJet Europe") carry the real ADS-B
      callsign in ATC ID ("EJU93KF", "DLH1AL"), the airline name in ATC AIRLINE ("Lufthansa", "Scandinavian",
      "Klm") and **no flight number**. MSFS's own AI was running too: fictional airlines ("TopSky 2278",
      "MORNINGSTAR 5061") and "Asobo AirTraffic" Cessnas with made-up D-A… registrations.
    - **Found:** MSFS's parked AI reports SIM ON GROUND = 0 (0 kt at 55 ft at EDDH, 74 aircraft "in the air"). Now
      anything slower than 30 kt is on the ground. LiveTraffic's callsigns were spelled ("Alfa Foxtrot Romeo four
      niner Kilo Papa"); now "Airfrans four niner Kilo Papa" through the telephony list, which gained 15 airlines
      (SAS, Wizz Air, Norwegian NAX, Transavia, Qatari, …); unknown ones are still spelled. The check shows each
      model title and a summary line (on the ground / moving / in the air, with airline, FSLTL models). Chatter
      remembers what was said per callsign, not per sim object (LiveTraffic may re-create one). 663 tests.
    - **Open:** keeping an aircraft through an ADS-B drop-out; wait for a flight to see whether objects really
      vanish.
L2. ✅ **Runway in use from the real traffic:** real aircraft land and depart on the real runway, so ATC must use it
    too, or it sends the user head-on into them. The runway end used by the last landings and departures (and by
    aircraft on final) wins over the METAR choice; without such traffic the METAR choice stays. ATIS follows. A
    change only before the taxi clearance (a change later is a separate step if needed).
    - **Done:** `atc/controller/runway_use.py`. Each traffic update records landings (final → on the runway) and
      takeoffs (on the runway → departing, the end it pointed at), the last 6 per airport. The departure runway is
      the end most departures used, the arrival runway the end most landings and aircraft on final used (a tie: the
      latest); at least 2 aircraft must agree. With only the other kind seen, just its direction counts: our runway
      if it points that way, else its other end, else the traffic's end (EDDM: departures on 26R turn our 08R into
      26L, not onto the departure runway). Same limits as a new METAR: departure runway only before the clearance
      (it names the runway), arrival runway only before the approach clearance; a new METAR doesn't undo it. A
      change is a line in the log ("EDDH runway in use now 05, as the traffic uses it (ATIS information B)") and a
      new ATIS letter. 661 tests. **Open:** a change after the STAR was given keeps the STAR as it was (the same
      already happens with a new METAR); check in a flight whether that matters.
L3. ✅ **Pushback:** no "push and start approved" while an aircraft taxis behind the stand: "hold position, traffic
    passing behind, I will call you", then the approval comes by itself when it has passed.
    - **Done:** "behind" is an aircraft in the taxiing state (over 3 kt, so pushing back too) within 150 m and more
      than 90 degrees off our nose. Then "Lufthansa four Alfa Bravo, hold position, traffic passing behind, I will
      call you"; asking again gets the same. Once nothing is behind any more, ATC calls with "push and start
      approved, facing west" by itself (only heard on its frequency; a readback item with strict readbacks).
      "Holding position" is an acknowledgement now (it got "say again"); the Phrases tab has it. 670 tests.
    - **Not covered:** an aircraft standing still behind us (LiveTraffic stops behind the user) doesn't hold the
      push; check in a flight whether that is needed. No "stop pushback" once pushing.
L4. ✅ **Taxi:** along the next part of the cleared route, an aircraft that will cross it → "give way to the Condor
    A320 crossing left to right"; one ahead going the same way → "follow the …"; one coming the other way or
    standing in the way → "hold position, traffic …", then "continue taxi" by itself.
    - **Done:** `atc/controller/give_way.py` (flat geometry in the taxi graph's metres). ATC watches the next 300 m
      of our cleared route, taxiing out and in. For each taxiing aircraft there: within 30 m of the route and going
      our way (45°) → "follow the Lufthansa Airbus" (only within 200 m); coming towards us (135°) → "hold position,
      the Lufthansa Airbus coming towards you", then "continue taxi" once it isn't; across the route, or heading
      to cross it within 30 s at its speed (400 m at most) → "give way to the Airfrans Airbus crossing left to
      right" (the side seen from us). The nearest first, each once per aircraft, from the Ground or Apron
      frequency we are on, only heard there. The name: the airline (telephony from the ADS-B callsign, else the
      sim's airline name) and the maker from the type (Airbus, Boeing, Embraer; "the Skyhawk"; else "the
      traffic"). "Giving way", "following", "continue taxi" are acknowledgements; the Phrases tab has them.
      684 tests.
    - **Not covered:** an aircraft standing still in the way (LiveTraffic stops behind us, so it rarely blocks
      the route ahead); not read back with strict readbacks (ICAO wants a "hold" read back: add if wanted).
L5. ✅ **Departure spacing:** after a departure, the next takeoff clearance only with wake turbulence separation
    (ICAO categories from the aircraft type: 2 minutes behind a heavy or super, else when the one ahead is airborne
    and far enough), with "line up and wait" and "behind the departing …" meanwhile.
    - **Done:** `atc/controller/wake.py`: ICAO categories J/H/M/L from the type designator (also MSFS text keys and
      names like "Skyhawk"; unknown = medium; ours from the flight plan's aircraft) and the Doc 4444 departure times
      (behind J: H 2 min, M/L 3 min; behind H: M/L 2 min; behind M: L 2 min; +1 min from an intersection). Each
      takeoff at our airport is kept with the live clock. Our takeoff waits for (1) the wake time on the same runway,
      then (2) ICAO runway separation: the one ahead has passed the far end of the runway or turned more than 30°.
      Rolling ahead: "behind the departing Emirates Boeing, runway two tree, line up and wait". Wake time:
      "runway two tree, line up and wait, expect departure in two minutes, wake turbulence" (also called by itself
      once while lined up). The clearance then says "caution wake turbulence from the departing Emirates Boeing"
      (up to 5 minutes after it). An intersection asked for is kept while waiting. Without a clock (fake sim,
      `--nosim`) there is no wake time, only the runway end. 704 tests.
    - **Not covered:** close parallel runways (under 760 m apart count as one runway for wake in ICAO), a departure
      after a landing heavy on the same runway.
L6. ✅ **Approach sequence:** traffic ahead on the same final or approach gives a number in the sequence: "number two,
    traffic to follow, Lufthansa A320 on six mile final"; speed control to keep the distance (3 NM, more behind a
    heavy); the landing clearance stays as it is (only when the runway is free).
    - **Done:** "ahead" = aircraft in the final state for our landing runway end, closer to the threshold than we
      are. The approach clearance starts with "number tree, traffic to follow Lufthansa Airbus on six mile final".
      Tower on the first call: "continue approach, number two, traffic to follow …", and the landing clearance
      comes by itself once nobody is ahead on final and the runway is free (one still there at 2 NM: go-around, as
      before). Speed control from Approach or Tower, outside 4 NM, when closer than the ICAO radar spacing (3 NM;
      behind a heavy 4/5/6 NM for H/M/L, behind the A380 6/7/8, a light behind a medium 5; `wake.py`) and faster
      than the one ahead: "reduce speed one six zero knots, traffic ahead" (read back), and if the gap still
      shrinks by half a mile, "reduce to final approach speed, traffic ahead". Behind a heavier aircraft the
      landing clearance starts with "caution wake turbulence from the landing Emirates Boeing". 710 tests.
    - **Not covered:** traffic still on the downwind or base (not yet in the final state) doesn't count; no
      "extend downwind" or vectors for spacing; a go-around for spacing only when the runway is still occupied.

L7. ✅ **Real callsigns:** `atc/phraseology/airlines.py` has about 140 airlines (Europe, the big ones elsewhere,
    cargo and business jets) with their ICAO telephony: "EJU93KF" is "Alpine niner tree Kilo Foxtrot", "BAW12"
    "Speedbird one two", "TOM5XY" "Tomson …". Unknown ones are still spelled. The pilot's own callsign can use them
    too, two-word ones included ("Air Canada 123", "Wizz Air 4AB"). A misheard word only counts as our own airline
    now (with 140 names, instruction words would otherwise look like airlines). 726 tests.

Each step: tests first with fake traffic, then `--text --nosim`, then a flight with LiveTraffic.

### Milestone 7 — Real taxi clearances and the open gaps (reworked 2026-11-15)

The user's order: first the technical gaps and "richtige Taxi-Vorschriften, also alle Taxi-Namen". The UI wishes wait
(Part C). Each step: tests, `--text --nosim`, a commit; then a flight.

**Part A — Taxi clearances as a real controller gives them.** Checked on 2026-11-15 with the user's scenery: at
Munich, Frankfurt and Heathrow the route is named in full ("via Echo two, November four, November, Alfa one tree"),
but at Hamburg 65–100 % of the taxiway pieces have no name in the scenery data, so ATC drops the whole "via" list
(above 30 % unnamed) and says only "taxi to holding point runway two tree".

A1. ❌ **Fill the missing names** (not possible: at EDDH 530 of 630 taxi paths have no name in the scenery, and
    OpenStreetMap leaves the same ways unnamed; names are not made up. The rule "an unnamed piece between two pieces
    of the same taxiway gets its name" already existed.) Planned: an unnamed piece between two pieces of the same taxiway gets that name; an unnamed
    piece that carries on a named one (straight on, no other named way at the junction) gets its name too; the lead-in
    from the stand stays unnamed. Measure first what is unnamed at EDDH and why (Little Navmap data vs. scenery).
A2. ✅ **Always the whole route:** every named taxiway in order, never dropped silently; what is still unnamed is
    left out of the list but the route stays the same. The 30 % rule goes.
A3. ✅ **Holding point by name** (the stub the route ends on, "A13", "L4"; not repeated in the "via" list; a
    readback that says it again at the end still counts) when the data has it: "taxi to holding point Alfa one tree runway two six right via …"
    (ICAO: TAXI TO HOLDING POINT [name] RUNWAY [number] VIA …).
A4. ✅ **Every runway crossing** (each crossing clearance adds "hold short runway …" for the next one): "hold short runway …" for each runway on the way, in order (today only the first),
    each crossed only with its own clearance; taxiing in the same.
A5. ✅ **Taxi in** to the stand with the same names and holding points; readback of the "via" list in order (strict).

**Part B — The gaps left open in Milestone 6.**

B1. ✅ "Hold position" / "hold short" read back with strict readbacks (ICAO wants holds read back; L4).
B2. ✅ An aircraft standing still (on the route: "follow" when it points our way, the queue at the holding point;
    else "hold position, … stopped ahead", then "continue taxi"; behind the push within 80 m; never one parked at a
    stand, LiveTraffic fills them) in the way of the taxi route or behind the stand (LiveTraffic stops behind us; L3/L4).
B3. ✅ ("runway change, expect vectors ILS approach runway …", once, when the runway changes after the descent
    clearance) The STAR after the arrival runway changed with the traffic (L2): give the new one, or "expect vectors".
B4. ✅ (an aircraft the sim re-creates under a new ID keeps its state by its ADS-B callsign; LiveTraffic itself keeps
    aircraft through drop-outs) ADS-B drop-outs: keep an aircraft for a short while instead of losing it from the picture (L1).
B5. ✅ (close parallels, EDDF 25C/25L; behind a heavier landing on our runway, either direction or a close parallel,
    within 2 minutes: "caution wake turbulence from the landing Emirates Boeing" in the takeoff clearance. ICAO has no
    time spacing for it, so no wait) Wake turbulence: close parallel runways (under 760 m apart) count as one; a
    departure behind a landing heavy (L5).
B6. ✅ ("traffic to follow … on downwind / on base": low arrivals within 12 NM, by estimated track miles; departures
    climbing out never count) Approach sequence: traffic on the downwind or base, not only on final (L6).

**Part C — Cabin, co-pilot, GSX** (user's answers 2026-11-15: GSX read *and* control; cabin in the airline's language
then English; the co-pilot takes over the radio on request). GSX Pro 3.0 is installed on the user's PC.

C1. ✅ **Cabin announcements** by the purser at the moments of a flight: boarding, doors closed, take-off, climbing
    through 10000 ft, descent, landing, arrival at the destination. First in the airline's home language (German
    for Lufthansa, Eurowings, Condor, …), then English; other airlines English only until their texts exist. A
    chime first, no radio effect, a voice of its own (German: Piper thorsten, CC0, downloaded like the ATC voice).
C2. ✅ **Co-pilot on the radio** (COM1 tuning still to be checked in MSFS): switched on and off in the window or by saying "copilot, you have the radio" / "I have
    the radio". Then the co-pilot reads back, checks in after a handoff and tunes COM1 (needs SimConnect events),
    with a voice of its own; requests (clearance, push, taxi, ready) still come from the pilot with one click.
C3. ✅ **Read GSX** (built against a fake GSX; still to be checked in MSFS): its L-vars (FSDT_GSX_BOARDING_STATE, …_DEBOARDING_STATE, …_DEPARTURE_STATE, …_COUATL_STARTED;
    1 available … 5 performing, 6 completed). Boarding completed → the doors-closed announcement; pushback
    performing → ATC knows the push has started. **Must be checked at the PC:** whether plain SimConnect reads
    L-vars in MSFS 2020 (other tools use the MobiFlight WASM module for it) and which values GSX really sets.
C4. ✅ **Control GSX** (built against a fake GSX; still to be checked in MSFS; a GSX question after the choice,
    e.g. the push direction, is left to the pilot in GSX's window): after "push and start approved" the app requests the GSX pushback; at the stand after
    arrival it requests deboarding. Through the GSX menu (FSDT_GSX_MENU_OPEN, FSDT_GSX_MENU_CHOICE and the menu
    text GSX writes to %APPDATA%\Virtuali\GSX\menu). **Must be checked at the PC.**

**To check at the PC** (MSFS with GSX running, parked at a gate):
`.venv\Scripts\python -m atc.sim.check --gsx-menu --tune 121.705` prints GSX's L-vars, opens the GSX menu and
prints it, and sets COM1. Then a flight: cabin voices and volume, the co-pilot's tuning and readbacks, the GSX
pushback after "push and start approved".

**Part D — Sound and the co-pilot** (user's wishes 2026-11-16):

D1. ✅ LiveTraffic no longer starts with the app by default (Settings, Traffic switches it on).
D2. ✅ **Sound mixer:** Settings, Audio: all voices, ATC and ATIS, other aircraft, co-pilot, cabin, in percent.
    Each transmission carries its event kind to the voice; Piper scales its samples, the Windows voice sets its
    volume. Saved, it applies at once, also during a flight.
D3. ✅ **Cabin sound** (`atc/audio/cabin_sound.py`): the PA's ceiling loudspeakers along the aisle, a short soft
    echo, the air conditioning, and the cockpit door between: quiet and muffled (highs fade above 600 Hz).
D4. ✅ **Cabin timing:** never right on top of the radio: each announcement waits 6 s after it is due and for
    10 s of quiet radio (the crew calls less). With GSX, the welcome and the doors wait for its boarding.
D5. ✅ **The co-pilot makes the requests** of each phase by himself while he has the radio: the clearance at once
    (tuning Delivery or Ground himself), the pushback once the beacon is on (new: `LIGHT BEACON` is read) or GSX's
    boarding is done, taxi when the push is over and the aircraft has stood still 5 s (or GSX's push is
    completed), "holding short" and "ready for departure" when standing at the crossing or the holding point, taxi
    to the gate after vacating; each on 4 s of quiet radio. In text mode (`/beacon on|off`) he does what is due
    after each line.
    - **To check in MSFS:** the beacon simvar, and whether 5 s still after the push is right.
D6. ✅ **Descent at the top of descent** (`atc/flightplan/track.py`): the user was always sent down too early. The
    descent came at a straight-line distance (3 nm per 1000 ft + 15 nm: 105 nm from FL350), but the STAR leads
    around the field: Hamburg → Munich, SimBrief's TOD is 59 nm from Munich in a straight line and ~80 nm along
    the route, so the call came ~45 nm early. Now track miles to go along the route are compared with SimBrief's
    TOD (read from the navlog), 5 nm before it, moved 3 nm per 1000 ft cruised above or below the plan. Without
    SimBrief's TOD the 3-in-1 rule, but along the route too.
    ✅ **Fix after flight 2026-11-17** (Hamburg → Munich, FL350): the descent came only after the TOD. SimBrief
    planned a step descent (FL310 from Urona, FL300 at its TOD); the shift was measured from the cruise level, so
    5000 ft "above the plan" were missing (15 nm). Now from the altitude SimBrief plans at its TOD (`tod_ft`).
    And "request decent" (whisper's spelling) is heard as a descent request.
D7. ✅ **Tuning away cuts the old frequency:** the moment COM1 changes, a transmission still playing from ATC, the
    ATIS or other traffic stops, and those still waiting are dropped; cabin and co-pilot go on. Piper stops its
    sound; the Windows voice can only drop the waiting ones (its COM object belongs to the speech thread).

D8. ✅ **Redesign** (user: the layout of SayIntentions' desktop window, all in one app, own colours, unslop rules,
    no new functions): a rail on the left (Flight, Map, Phrases, Settings), the radio bar on top (COM1 and the
    transponder green, the next frequency cyan); on the flight view a row of calls (the next call, say again, wind
    and radio check, the co-pilot), the board with the airport's frequencies beside the flight, and the radio log as
    rows of frequency, station and message. Settings are a page with their sections on the left. Colours after
    cockpit displays: green active, cyan standby and what you can press, amber to do, red warning, on graphite.
    Their look, logo and names are not copied: the app will be published.

D9. ✅ **Released** on GitHub (public, GPL-3.0): 0.1.0, 0.1.1 (the window from a downloaded zip: "MSFS ATC.exe.config"
    with loadFromRemoteSources), 0.1.2 (SimConnect.dll found where other add-ons put one: GSX, EXE.xml programs,
    the SDKs' default folders; shipping it is unclear by licence).
D10. ✅ **MSFS 2024 (first step, untested):** a friend on MSFS 2024 got "SimConnect.dll was not found" and "unknown
    airport". The Little Navmap database is now found by itself (`atc/airport/lnm_files.py`): the one of the MSFS
    that runs (FlightSimulator.exe / FlightSimulator2024.exe), else the one loaded last; a path in Settings wins.
    The banner names it ("Little Navmap (MSFS 2024)"). SimConnect: the MSFS 2024 SDK's default folder is searched;
    the message names the SDK of either sim. **To check with MSFS 2024:** everything.

Next: test flights with MSFS 2020 (TESTFLUG.md) and MSFS 2024 (a friend). Proposed, not started: airports straight
from MSFS (SimConnect Facilities API, cached), so Little Navmap becomes optional. Still later: onboarding at the
flight start (only flight information, "like VATSIM"; paused by the user).

W1. 🔶 **Start screen** (user picked: briefing, dark look; the start check was dropped again: "egal").
    - **Done:** "Load flight" (`atc/preflight.py`, POST /api/briefing) shows the plan before starting: callsign with
      how to say it ("Say Lufthansa two four one"), aircraft, cruise, both airports with name, runway in use, wind
      and METAR, the route with SID and STAR. A SimBrief username loads by itself when the screen appears; typing
      the plan by hand is folded away. The app was already dark (R1).
    - **Done:** LiveTraffic starts with the app (`atc/sim/livetraffic.py`): its program from Settings, else from
      LiveTraffic's entry in MSFS's EXE.xml; "app" opens its window; a second copy closes by itself. Settings,
      Traffic: on by default, path optional.
    - **Open:** an onboarding at the flight start "like SayIntentions": what exactly is still to be agreed.

### Milestone 8 — Fixes from the first full test flight (planned 2026-11-16, not started)

The flight: EDDH → EDDM in MSFS 2020 with LiveTraffic, GSX Pro and the Fenix A320 (start.bat, strict readbacks),
log `2026-11-16_1216Z_DLH758.txt`, the user's answers in TESTFLUG.md. The user: "fix every error, no new features",
plus one thing: "in the air you hardly hear other aircraft". Each step: first a test that reproduces it (from the
log), then the fix, tests, `--text --nosim`, a commit. Answers to the open questions (❓) come first.

**Part A — Descent and directs** (the user: "it crashes most with the descent; far too many directs")
A1. ✅ **No descent at all.** Every Center gave a direct-to (Zucka, Lular, Landu), and the descent check still measured
    the track miles along the original route, via the points the direct skips: it never reached the top of descent.
    At 13:27 the pilot asked, already descending through FL270. Fix: remember the cleared direct-to; track miles to
    go = straight to that fix, then the route from it.
A2. ✅ **A direct at every Center check-in, the same one twice:** Zucka by both Bremen sectors, Landu by Frankfurt and
    by Munich Radar. Fix: a direct only when it is a real shortcut beyond the one already given, never the same
    fix again, none into the STAR. **User: 1–2 real shortcuts a flight.**
    The descent itself stays "descend flight level 100" (start now), just before the FMC's TOD (user).
A3. ✅ **An instruction from a Center the pilot hasn't called yet:** reproduced while looking at the co-pilot. Right
    after a sector handoff the next sector's controller gave the descent on its frequency before the check-in: not
    heard, and the readback it waits for blocks everything. Fix: a controller instructs only after the check-in.

**Part B — The runway at the destination** (go-around, "number six", the incursion after landing)
B1. ✅ **EDDM landing runway 26L while the traffic landed on 26R and departed from 26L.** The runway came from the
    METAR; the traffic is only seen within 40 nm of our aircraft, and the landing runway froze at the first call to
    Approach. Result: "go around, runway occupied" by a departure, and in the go-around 26R → 26L → back in 7 s.
    Fix: change it until the ILS clearance (with "expect ILS 26R"); for arrivals the landings count, departures
    only without landings; on a tie keep the current one (no flipping).
B2. ✅ **"number six" / "number four":** the sequence counted the arrivals for the other, independent parallel 26R.
    Fix: only our runway and close parallels (under 760 m).
B3. ✅ **"traffic to follow traffic on downwind"** when the aircraft has no name: say it without the name.
B4. ✅ **Traffic information on final:** three calls in 20 s, also traffic behind ("six o'clock") and on the parallel
    approach. Fix: on final, no traffic information about aircraft landing or departing at the airport or behind
    us; at most one call a minute.
B5. ✅ **After landing: "stop immediately, runway incursion 08L/26R", and one second later "vacate runway, contact
    Ground".** **The user landed on 26R**, with the traffic: B1 is the cause. Also: never "vacate" right after
    "stop"; "stopping immediately" understood as an acknowledgement (it got "say again").

**Part C — On the ground**
C1. ✅ **"On holding point (runway 33)" not understood** (twice "say again"): a holding point report, like "holding
    short runway 33".
C2. ✅ **Ground ↔ Tower ping-pong at the holding point.** Ground's "contact Tower" (after "holding short runway 33")
    was a plain redirect: the readback wasn't recognised ("continue taxi"), Tower sent the check-in back to Ground,
    and two minutes later Ground handed over again. Fix: that redirect is a handoff with a readback, and Tower
    accepts a check-in from an aircraft at or near the holding point.
C3. ✅ **"request ground services" got no answer** (ATC always answers): "say again".
C4. ✅ **A wrong turn right after the pushback got no reaction** (user). The watch only starts once the aircraft
    has been on its route; turning away before that is never noticed. Fix: also off the route when it moves away
    from the route's start without ever joining it.
C5. ✅ **The holding point "didn't exist"** (user: it was on a taxiway that crosses runway 33). The departure holding
    point was picked among all hold-short points near the threshold, crossing ones included. Fix: only a holding
    point whose taxiway leads onto the runway (not across it).
C6. ✅ **At the gate nothing more came** (user: "just a bye from ATC"). Fix: parked at the stand, Apron or Ground says
    goodbye.

**Part D — Co-pilot** ("macht gar nichts")
D1. ✅ He had the radio from 13:14 and didn't read back Berlin's "contact Frankfurt" in 45 s. One cause found (A3);
    the Berlin → Frankfurt case itself still to be reproduced. Fix A3, then a test of the whole flight in the live
    loop, gate to gate, with the co-pilot on. Reproduced there (`tests/test_copilot_flight.py`): at a Center →
    Center handoff the new sector was already "the Center", so the old one, waiting for the readback, was nobody;
    the co-pilot saw only a check-in due on a frequency he hadn't tuned, and waited for good. The previous Center
    is now kept.

**Part E — GSX**
E1. ✅ **"GSX: its menu did not open"** for the pushback (12:35) and the deboarding (14:04), although the check
    command opened it. Suspects: the menu is written from a second thread while the live loop reads SimConnect,
    and 3 s may be too short. Fix: the menu clicks go through the live loop (one SimConnect user at a time), wait
    up to 10 s, try once more, close the menu again after a failure, log what the menu file said.
    Done: `GsxMenu.start/poll`, stepped once per live-loop step (no thread, never blocking).
E2. ✅ **Deboarding while the engines still ran:** GSX started it by itself (its own automatic deboarding, user),
    not the app. Still, the app's own request waits for the engines off and the parking brake set, at a stand
    (any stand). Needs two more simvars (engine combustion, parking brake).
    Done: `GENERAL ENG COMBUSTION:1/2` and `BRAKE PARKING POSITION` read; any stand of the destination counts.

**Part F — Small things**
F1. ✅ Cabin announcements too loud next to ATC: mixer default 70 % → 50 %.
F2. ✅ "no data from MSFS" flickered 8 times in the first minute and twice on the approach: say it only after 5 s
    without data.
F3. ✅ Microphone hints say "python -m atc --list-mics", which an .exe user can't run: "Settings → Audio → Microphone".

**Part G — Other aircraft in the air** ✅ (`atc/controller/air_chatter.py`; to check in MSFS) (the user's one addition)
Today the other aircraft are only heard on Ground, Apron and Tower (taxi, takeoff, landing). On Departure, Approach
and Center nobody else talks. Plan, from what the real LiveTraffic aircraft in our controller's area really do,
nothing made up:
G1. ✅ Center and Departure: an aircraft entering the sector checks in with its level; climbing or descending, the
    controller clears it; leaving, it is handed over.
G2. ✅ Approach: arrivals check in, get the descent, vectors and the ILS clearance as they really turn and descend.
    Done: check-in with "expect vectors ILS approach runway …", descents in steps (not below 3000 ft above the
    airport), handed to the Tower on final. Not done: single headings per turn (we can't tell a vector from a turn
    the pilot flies on his own).
G3. ✅ Rules for all: never on top of a call to us or our readback, a pause after each exchange, the same voice
    per callsign. **User: medium to busy.**

**Part H — Approach, redone** ✅ (`atc/controller/vectors.py`; to check in MSFS) (user: "it gives a heading several times, doesn't resolve it or give a new one; the
whole approach phase must be redone"). Today: one heading towards a point 14 NM out, then nothing until within 3 NM
of it; missed (wind, after the go-around) means no more instructions: 8 minutes on heading 075 after the go-around.
Wanted: **radar vectors** (user): downwind, base, intercept, each leg with its own heading and altitude, watched
every few seconds, with a correction when the aircraft drifts or overshoots the localizer, re-vectored after a
go-around, until established. The descent on the way down to the approach altitude in steps.

**Part I — Center without Little Navmap** (user: his friend on MSFS 2024 saw "Radar PLACEHOLDER" and stayed with
Approach, "mine didn't either": a new solution, from VATSIM). Today the sectors come only from Little Navmap.
Found: VATSIM's vatspy-data-project has the FIR boundaries and names worldwide (CC BY-SA 4.0, fits the GPL with
attribution), but no frequencies. ❓ Before starting: where the Center frequencies come from (a table we write from
public sources, or a VATSIM dataset whose licence allows it). Never show "PLACEHOLDER" to the user.
✅ **User (2026-11-16): a VATSIM dataset** — only if its licence allows shipping or downloading it with a GPL app;
check the licence first, and if it doesn't, come back to the user (no own table without asking).
✅ **Done:** VATSpy (outlines) + VATGER datahub (frequencies), both CC BY-SA 4.0, joined by
`atc/airspace/vatsim.py` into the shipped `data/centers_vatsim.json`: 32 sectors, Bremen, Langen and Munich Radar,
"High" positions from FL245, the smallest sector first. Used when Little Navmap has no sectors; corrections in
centers.json still win. vatglasses-data and vacs-data are CC BY-NC-SA: not usable. **Only Germany:** outside it
radar service is terminated as before (no frequencies to be had under a compatible licence). PLACEHOLDER is gone
from everything the user sees: the shipped centers.json is empty, unknown frequencies are dropped silently.

**Order:** A and B first (they broke the flight), then H, C, D, E, F, G; I once its data source is settled. **To check afterwards:** the same flight
again, with TESTFLUG.md.

### Milestone 9 — VFR from small airfields (planned 2026-11-16; parts A, B, C and E done 2026-11-17)

The user: "can we fly ultralights from small fields like Uetersen yet?" Not yet: tried `--from EDHE --to EDHL
--callsign DMABC` offline. The app starts there, but no station at Uetersen ("Frequencies:" empty, its Info is not a
controller type), the flight is IFR (clearance, SID, squawk, pushback, Departure, Center, vectors, ILS), a cabin
announcement in an ultralight, the stand is "NONE 27", no METAR at the field so "calm wind".

What the data already has (Little Navmap, the user's scenery), checked at EDHE, EDHL, EDHF, EDXM, EDHI, EDDH:
- the small field's own station: com type `FSS` ("UETERSEN" 122.705, "ITZEHOE" 127.110) = "Uetersen Info";
- `UC` "LANGEN" 125.100 at every German field = Langen Information (FIS). One frequency for all of Germany, not
  the real FIS sectors: ❓ see below;
- runways with surface (grass "G") and the circuit side per runway end (`runway_end.is_pattern` "L"/"R"); GA ramps
  and taxi paths (EDHE: 36 parking, 118 paths);
- airspaces with floor and ceiling: control zones (class D, `CD`: "HAMBURG CTR 1 HAMBURG", 0–2500 ft), airspace C
  (`CC`: "HAMBURG A (C)" 2500–10000 ft …), E; restricted areas (`R`);
- VFR reporting points (`waypoint.type = 'VFR'`, by airport): EDDH has N1, N2, S1, S2, T1, T2, P1, P2, W1, DELTA —
  spoken "November one", "Delta".

**Part A — The basis** (nothing new on the radio yet)
A1. ✅ Flight rules VFR: from SimBrief (already read, `atc/flight_rules` "V"), `--rules VFR` on the command line and
    in the app (Rules field in the flight plan card, OK'd by the user). A VFR flight starts "cleared" with squawk
    7000; "request clearance" gets "VFR, no clearance required". IFR stays exactly as it is.
A2. ✅ Registration callsigns: "D-MABC" spoken "Delta Mike Alfa Bravo Charlie"; the short form "Delta Bravo Charlie"
    only after that controller used it first (ICAO), then by both; each controller starts in full. The parser
    hears it spelled, phonetic, as "DMABC" or "d m a b c", short, or with one letter misheard.
A3. ✅ Small aircraft: no cabin announcements, no pushback ("no pushback required, report ready to taxi"), no GSX
    for a VFR flight; the aircraft type in the first call ("C172, VFR to Munich, information alfa, request taxi").
    Not done: the type comes only from the flight plan (`--aircraft`, SimBrief), not yet from the sim's `ATC MODEL`.
A4. ✅ Weather at a field without a METAR: the nearest METAR within 25 NM (aviationweather.gov by bounding box,
    cached for offline) for the QNH, marked "RMK FROM EDHI"; with MSFS the wind is the sim's at the field
    ("WIND MSFS"). Beyond 25 NM: no METAR, as before.
A5. ✅ Stands: GA ramps get a plain name ("parking two seven", "the apron" without a number), never "NONE 27";
    a VFR flight is sent to a GA ramp, not an airliner's gate, and the fake sim starts it there.

**Part B — The small field's Info station** (e.g. "Uetersen Info": information only, never a clearance)
B0. ✅ The Info station: the field's `FSS` frequency, spoken "Uetersen Info". A field without a controller
    (`Airport.controlled`: no Delivery, Ground, Tower, Approach or Departure) is handled by `atc/controller/info.py`;
    at a controlled field an Info frequency stays a frequency like any other. The circuit side per runway end is now
    read from Little Navmap (`is_pattern`) and kept in the airport JSON. No runway incursion watch and no go-around
    at an uncontrolled field: nobody clears the runway there. The phases follow the aircraft (taxiing, airborne,
    landed, off the runway, parked).
B1. ✅ Radio check and taxi information: "Uetersen Info, Delta Mike Alfa Bravo Charlie, ultralight, at the apron, VFR
    to Lübeck, request taxi information" → runway in use, wind, QNH, circuit side. Read back runway and QNH.
B2. ✅ Ready for departure: wind and "runway free" / the traffic on the runway or on final (LiveTraffic); leaving the
    circuit: "leaving the frequency" → the farewell.
B3. ✅ Arrival: the inbound call ("10 miles north, 1500 feet, for landing", from 15 NM out) → runway, wind, QNH,
    circuit side, traffic in the circuit (aircraft within 3 NM and below 2500 ft AGL); "on final 27" → wind,
    "runway free"; "runway vacated". A controller in charge before (Departure, Center) says "radar service
    terminated, Itzehoe Info on …" at 40 NM.
B4. ✅ A field with no Info station: blind calls "Uetersen traffic, …" are logged, nobody answers. **Finding:** the
    German data has no frequency of the field's own for these (its `UC` is Langen FIS 125.100 at every field), so a
    blind call is any call on a frequency without a station while the flight is at such a field. UNICOM is not
    shown in the frequency list for the same reason.
    Also: **a VFR flight no longer gets Center** (Langen Information is part D).
    Tests: `tests/test_info.py`. Smoke test EDHE → EDHF (Uetersen Info → Itzehoe Info) offline: all calls answered.

**Part C — The circuit**
C1. ✅ Where the aircraft is in the circuit (upwind, crosswind, downwind, base, final) from its position relative to
    the runway in use and the circuit side, and its heading (`atc/controller/circuit.py`): within 3 NM and below
    2500 ft AGL, final up to 4 NM out, a leg only if the heading fits within 45°. The pilot's "left downwind runway
    27" / "left base" (new kind `circuit_report`) → "roger", or the traffic in the circuit. Flying onto a leg
    without a call also puts the flight in the circuit.
C2. ✅ Traffic in the circuit by leg: "one aircraft on left downwind runway two seven", "two aircraft in the circuit,
    one on final, one on left downwind" (in the inbound answer and the answer to a position report). The other
    aircraft's own reports as chatter on the Info frequency when they turn onto downwind, base or final, with the
    same quiet-radio rules as Milestone 8 G.
C3. ✅ "on final runway 27, touch and go" / "full stop". Touching down fast and climbing away again (above 500 ft AGL),
    or "going around", or turning crosswind after the final call → back in the circuit, the reports due again; a
    slow roll-out → vacating. **A local flight** (`--from EDHE --to EDHE`) stays with the field's Info after takeoff
    (no "leaving the circuit", no release to Info); the suggestions follow the leg (downwind, base, final "touch and
    go"). The Phrases tab has a new group "Small field (Info)", current at such a field.
    Text mode: `/circuit upwind|crosswind|downwind|base|final` and `/landed go` (a touch-and-go).
    Tests: `tests/test_circuit.py`. Smoke test EDHE → EDHE offline: two circuits, touch-and-go, full stop, vacated.

**Part D — On the way: Langen Information (FIS)** (optional for the pilot, as in reality)
D1. Initial call with position, level and destination → "identified" with a squawk, QNH; "squawk 7000" and "leaving
    the frequency" at the end.
D2. Traffic information from LiveTraffic within a few miles and 1000 ft.
D3. Airspace watch (a notice, and FIS says it): heading into a control zone or airspace C without a clearance, into
    a restricted area. Floors and ceilings from the `boundary` table.

**Part E — Controlled airports** (e.g. Lübeck, Hamburg: Tower and Ground give VFR clearances)
E1. ✅ Departure: Ground "taxi to holding point runway 25"; Tower with the takeoff clearance "leave the control zone
    via November, one thousand five hundred feet or below, squawk 7000, … cleared for takeoff, report November".
    Over the point (came within 2 NM and flies away again), out of the zone (sideways or over the top) or on the
    pilot's "November" → "leaving the control zone, frequency change approved". No Departure. The reporting points
    are the field's VFR waypoints from Little Navmap (`waypoint` type VFR, "NOVMR" → "November", "S1" → "Sierra
    one"), the zone its CD boundary (`boundary`); the point is the outermost one of each route toward the
    destination; without points a direction ("to the north"), without a zone 5 NM / 2500 ft. The limit is 1000 ft
    below the ceiling in 500 ft steps (Lübeck: 1500 ft). Above it by more than 300 ft: "check altitude" (once).
E2. ✅ Arrival: within 15 NM the call is for the destination's Tower; "… 12 miles south, 2500 feet, information
    alpha, for landing" → "enter the control zone via Sierra, one thousand five hundred feet or below, report
    Sierra" (with runway and QNH if the ATIS letter is missing or old). At Sierra (reported or passed) or on a leg
    → "join right downwind runway 25, report downwind" (with the circuit traffic) → "report final" → on final
    (called or seen) the landing clearance or "continue approach". Without points straight "join … downwind". No
    Approach, no descent, no vectors ("roger, report Sierra"); a go-around rejoins downwind; the go-around without
    a landing clearance only on short final (0.5 NM), since downwind passes the threshold. The Phrases tab has a
    new group "Control zone (VFR)". Tests: `tests/test_vfr_controlled.py`. Smoke tests EDHL → EDHE (out via
    Whiskey) and EDHE → EDHL (in via Whiskey, downwind, final, landed) offline.
E3. Crossing a control zone ("request crossing of the control zone from November to Sierra").

**Open questions (❓, answers first):**
1. Language: English only, as today (BZF I phraseology), or German too (BZF II, what most ultralight pilots use at
   small fields)? German needs German voices, German speech recognition and a German parser: a big step of its
   own. Proposal: English first, German maybe later.
   ✅ **User (2026-11-16): English first.** German stays a later step of its own.
2. Which parts and in which order: proposal A → B → C first (Uetersen to another uncontrolled field, e.g. Itzehoe),
   then E (Lübeck), D last.
   ✅ **User: A → B → C, then E, D last.**
3. Langen Information: the MSFS data has 125.100 for every German field, the real FIS has sectors with their own
   frequencies. Use the data as it is, or a small table of our own?
   ✅ **User: the data as it is** (125.100, what the sim has).
4. Which aircraft you will test with in MSFS (an ultralight add-on or a default type), for A3 and the speeds in C1.
5. The flight plan field for VFR in the app (A1): OK?
   ✅ **User: yes, an IFR/VFR field in the flight plan card** (set by SimBrief when it has one).

### Milestone 10 — Realistic IFR arrival: descent and approach (planned 2026-11-17, before E3)

From the test flight 2026-11-17 (Hamburg → Munich, log `2026-11-17_1249Z_DLH7M_2.txt`). The user: "Wir müssen
ganz ganz dolle den approach und descent überarbeiten … mehr Realismus und bessere Approach." What went wrong:
- Frankfurt Radar gave "direct LANDU": it skipped the airway T105 and SimBrief's TOD.
- The descent came late (fixed in fdea143: SimBrief's TOD altitude).
- The runway changed only 30 NM out (26L → 26R).
- Munich Approach took the aircraft off the STAR LAND2B with "heading 215", 45° straight at the final from 8 NM
  beside it. The approach clearance would have come only ~4 NM before the threshold, at 4500 ft.
- Nobody noticed that the aircraft stayed at 6700 ft although cleared to 4500 ft.

The user's decisions (2026-11-17):
- No direct off the planned route: neither the Center's shortcut nor Approach's headings on the STAR.
- Fly STAR and transition, with vectors only at its end.
- Descent by the procedure's constraints.

The data: Little Navmap's MSFS database (the user's own, read at runtime, never shipped) has the STARs, approaches
and transitions with their legs, altitude and speed constraints. Munich ILS 26R: "LANDU" transition LANDU, DM411,
DM422, DM429 (downwind), then "FM" = vectors, CF DM438 at or above 5000 ft, GUDEG (FAF, 5000 ft), threshold. STAR
LAND2B: LANDU at or below FL100 and 250 kt, MIQ. Without that data: the improved vectors (F) as a fallback.

A. ✅ **Procedure data** (2026-11-17, `atc/airport/procedures.py`, `AirportData.procedures()`): STARs, approaches and their transitions for an airport from
   the Little Navmap database. Legs with position, kind (fix, "vectors" for FM/VM legs, the FAF), altitude
   constraint (at, at or above, at or below, between) and speed limit. Never the Navigraph database. Tests with
   procedures built in code, no real data in the repo. Checked on the user's EDDM: LAND2B (26R) LANDU to MIQ,
   LANDU to 08R gives LAND2A, ILS 26R with FAF GUDEG at 5000 ft, transition LANDU vectors from DM429. The FAF is
   not marked in the database: the fix after the approach's first fix (IF). Exported JSON files have no procedures.
B. ✅ **The landing runway before the TOD** (2026-11-17, `atc/controller/arrival.py`): fixed when the descent is given (ATIS, wind, traffic), with the STAR that
   fits it ("LAND2A" for 08, "LAND2B" for 26) and the transition from the STAR's last fix: "descend flight level one
   hundred, cleared LANDU two Bravo arrival, expect ILS approach runway two six right". A later runway change only
   when the wind really turns, then with the new STAR/transition named.
   Done: the STAR from the filed STAR's first fix (else the route's last fix) for the runway, the approach (ILS
   first), the transition from the STAR's last fix; "expect ILS approach runway …" always. After the descent the
   traffic moves the runway only to the other direction, never to the parallel. **Open for E:** with the real EDDM
   data LAND2B ends at MIQ, and the MIQ transition has no vectors; the LANDU transition (vectors from DM429) starts
   at the STAR's first fix. Which transition to choose must be decided in E.
C. ✅ **No direct off the route** (2026-11-18, `atc/controller/air.py`): the Center's shortcut only en route, before the TOD, never past the first fix of
   the STAR, and only when the track left still leaves room for the descent. A pilot's "request direct" on the
   arrival only to a fix ahead on the STAR/transition.
   Done: the shortcut picks among the route points up to the STAR's first fix, none after the descent, and only
   when the track left after it is at least the top-of-descent distance. The pilot's direct en route: route points
   up to the STAR's first fix ("unable direct Miq, not ahead on your route"); after the descent only the fixes ahead
   on the STAR and transition cleared (Little Navmap), else the plan's STAR points ("unable direct Vesix, not
   ahead on your arrival"). On the test route a direct to LANDU is still possible from ALOSO to TIPAM (116–170 nm
   left, the descent at 98 nm).
D. **Descent by the constraints**: the Center's descent planned so the aircraft meets the STAR's first constraint
   (LANDU FL100 or below, 250 kt). Approach then gives the transition's altitudes step by step ("descend altitude
   five thousand feet") and speeds ("reduce speed two two zero knots") in time before each fix. And it notices
   when the aircraft doesn't leave its level: "Lufthansa 7M, confirm descending altitude four thousand five
   hundred feet".
E. **Transition + vectors**: Approach's first call names the transition ("radar contact, descend altitude 5000
   feet, QNH 993, transition LANDU, ILS approach runway 26R"). The pilot flies it in the FMC; ATC follows the
   position along the legs. At the vectors leg (after DM429) Approach turns base by heading, so the intercept is
   at 10–12 NM at the FAF altitude: "turn right heading 170", then "turn right heading 230, cleared ILS approach
   runway 26R". With traffic ahead the downwind gets longer (trombone). With traffic far behind the base turn
   may come earlier, but never a direct off the transition.
F. **Better vectors without data**: never 45° straight at the final from far beside it, but a downwind and a base,
   the intercept at 30° 8–12 NM out at the approach altitude. Vectors only after the STAR's last fix.
G. **Tests and a replay**: the 2026-11-17 flight's geometry as a test (Munich-like procedures built in code), and
   the smoke test.

Order: A → B → C → D → E → F → G, each part with tests and its own commit. Milestone 9 E3 after it.

### Later versions (agreed, in rough order)

26. *(Moved into Milestone 4: native SimConnect is S1–S2, the traffic parts T1–T4.)* Still later: the Facilities API
    as a second `AirportData` backend.
27. ✅ **Taxi conformance** (2026-11-15, `atc/controller/taxi_watch.py`), taxiing out and in:
    - **Off the cleared route** (more than 50 m from it, after having been on it, moving, not near its end, not on a
      runway): "you appear to be on Bravo, new route, taxi to …" with a new route from there, read back like the first.
    - **Taxi speed:** over 30 kt off the runways "reduce taxi speed"; again only after slowing below 20 kt.
    - **Progressive taxi:** "request progressive taxi" (instead of "request taxi", or while taxiing): each turn onto
      the next named taxiway 120 m before it, "turn left onto Alfa" / "continue straight ahead onto Bravo". No
      readback. Unnamed pieces between two parts of one taxiway are no turn; routes the scenery leaves unnamed get
      no turns (most of EDDH).
    - Past a holding position without a clearance was already the runway incursion check ("stop immediately").
    - **To check in MSFS:** whether 50 m off the route is right with real taxiing (wide aprons, cut corners).
28. *(Radar vectors moved into P5.)*
29. **Procedures:** SIDs, published missed approaches (STARs are in P5).
30. *(VFR moved into Milestone 9.)*
31. **LLM fallback** (parked in step 24): revisit if a small model fits next to MSFS, or with a cloud API. Reuse the spike's checks.
32. **`.PLN` import.**
33. **GitHub Actions CI.**

## Milestone 0 findings (2026-11-14)

- **Machine:** Python 3.14, RTX 3060 Ti 8 GB, MSFS2020 (Microsoft Store). All dependencies install on 3.14.
- **TTS:** the Windows default voice is German (Hedda). Config must select an English voice; only Zira (en-US) is installed. More English SAPI voices (one per controller) can be added via Windows language/speech settings.
- **PyAV 19 breaks faster-whisper 1.2.1 file decoding** (`metadata_errors` argument). Not a problem for the app: always pass whisper a 16 kHz float32 numpy array, never a file path.
- **Whisper on CPU is viable:** on clean TTS audio, `small.en` int8 transcribed 17 s of speech in ~2.9 s, `tiny.en` in ~0.6 s. CPU avoids competing with MSFS for VRAM. Real mic audio still to be measured, and CUDA not yet tested.
- **Numbers come out in every format:** "1-2-0", "120", "4721", "4-7-2-1". "Niner" became "9 or" / "or", "tree" stayed "tree", "fife" became "5". The normaliser (step 16) must map tree→3, fife→5, niner→9 and handle "9 or". The aviation prompt helped `small.en` slightly ("wind" recognised).

- **The `keyboard` package does not work on Python 3.14** (its hook never fires, even for injected key presses). It has been removed. Push-to-talk polls `GetAsyncKeyState` via `ctypes` instead, which works system-wide, including when MSFS has focus.
- **Always use `vad_filter=True`.** Without it, whisper hallucinated "Clearance, ground," (words from the `initial_prompt`) from 2 s of room noise. With it, silence returns `''` in 0.1 s. An empty result must be ignored, never parsed.
- **Real mic (fifine, `small.en`, CPU):** about 2.0 s per transmission regardless of length (whisper pads to 30 s windows). Acceptable for v1. Numbers were perfect ("120", "4721"). Names were not: "Hamburg" → "Humble"/"Hammer", "DLH4AB" → "DLH4HB" / "DLH, 4AB" / "glh4ab".
  - **Tried and rejected: putting names into the prompt.** Adding "Hamburg Ground, Lufthansa 4AB, DLH4AB" to the `initial_prompt` worked on clean TTS audio. On a quiet real transmission (peak 0.058), though, whisper returned the context text word for word while the pilot had said "Deutsche Lufthansa 4AB". `hotwords` is no fix, because faster-whisper injects it as previous text the same way. **Consequence for step 23:** the prompt contains only generic aviation vocabulary, never expected names or phrases. As a safety net, discard any result whose words are all contained in the prompt.
  - **Consequence for step 16:** names are corrected *after* transcription, deterministically: match callsign and station fuzzily (edit distance, phonetic similarity) against the expected values. Never require an exact string match. The station name is optional anyway, since COM1 already says who you're talking to.
  - **The generic prompt is essential and must include the ICAO alphabet.** On recording 001, no prompt gave "I'm a ground love tons of forever Bravo", the vocabulary prompt gave "Lufthansa 4L for Bravo", and vocabulary + alphabet gave "Lufthansa 4, Alpha, Bravo". "Two tree" was correctly transcribed as "23".
  - **Model comparison on 8 real recordings (CPU, prompt with alphabet):**

    | Setting | Avg time | Quality |
    |---|---|---|
    | `small.en`, beam 5 | 3.1 s | best: callsign right in 6/8, all numbers right |
    | `small.en`, beam 1 | 2.4 s | dangerous errors: "Lufthansa 5, Bravo", "Luft and so forth" |
    | `base.en`, beam 5 | 1.1 s | many errors: "Foxtrot" for "four alpha", "1190" |

    **Decision: `small.en`, beam 5 on CPU.** ~3 s is within normal ATC response delay. A GPU would cut this to well under a second, so that's the first thing to try if latency becomes a problem.
  - **Error patterns the normaliser (step 16) must handle:** "for" → 4 next to callsigns ("Lufthansa for Alpha Bravo"), "4L for Bravo" / "F4, Alpha" → 4 A, "fife" transcribed as "five", numbers coming as digits *or* comma-separated words ("one, two, zero"), "Hammer"/"Humble" for "Hamburg".
  - The whisper spike saves every recording to `recordings/`, so prompt/model variants can be compared offline on the same real voice samples (`--file recordings`).
  - **Telephony designators:** pilots say "Lufthansa four alpha bravo", not "DLH". We need a small table mapping ICAO airline codes to their spoken names (DLH → Lufthansa, BAW → Speedbird, …) for both parsing and phraseology.
- **SimBrief works:** username → latest plan (`DLH759`, A20N, EDDH rwy 33 → EDDM rwy 08L, FL350, rules `I`). The API returns HTTP 400 with a readable reason (e.g. "No flight plan on file"), which must be shown to the user. The raw response (800 KB) contains user ID, crew names and personal links. Only a trimmed copy (`general`, `origin`, `destination`, `alternate`, `navlog`, `atc`, `aircraft`, no NOTAMs) goes into `tests/fixtures/`. The raw copy stays in the git-ignored `cache/`.
  - **Open point for step 19:** SimBrief routes include SID and STAR names (`AMLU2G … LAND2A`). Even without modelling procedures, the clearance can name them ("cleared to Munich via AMLUH two golf departure"). The pilot's FMS flies them. Departure must then not say "direct first waypoint" while the pilot is still on the SID. To decide when we get to step 19.
- **FSLTL traffic is visible via raw `ctypes` SimConnect** (`RequestDataOnSimObjectType`, type AIRCRAFT). That's the yes for step 26. Details:
  - FSLTL injects gradually. A query right after starting the injector returned only the own aircraft, and a few minutes later 16 FSLTL aircraft were parked at EDDH.
  - Titles start with `FSLTL` (e.g. `FSLTL_FAIB_A21N_DLH-Lufthansa`). `ATC ID` is synthetic (`sDLH28`), not a real callsign.
  - The own aircraft is object ID 1 and must be filtered out. Type ALL also returns ground crew objects (`Tarmac_Male_…`), so always query type AIRCRAFT.
  - Each object arrives as its own message (`entry N of M`, counted from 1), so a full list needs all M messages collected.
- **Little Navmap schema** (`%APPDATA%\ABarthel\little_navmap_db\little_navmap_msfs.sqlite`). All needed tables exist: `airport` (incl. `mag_var`, `transition_altitude`, `tower_frequency`, `is_addon`), `runway`, `runway_end` (incl. `ils_ident`, `heading`, threshold position), `com` (`type`, `frequency`, `name`), `ils`, `taxi_path`, `parking` (`name`, `number`, `airline_codes`, `heading`), `start`.
  - **`taxi_path` has no node IDs**, only `start_lonx/laty` and `end_lonx/laty` plus `name`, `type` and `start_type`/`end_type`. The graph (step 14) must create nodes by merging identical (rounded) coordinates.
  - The database must include add-on scenery, otherwise taxiway names and parking won't match what the pilot sees in the sim. Checked: EDDH comes from the user's `simwings-eddh` add-on (`is_addon = 1`), and the full DB is ~805 MB.
  - **Units are mixed:** `com.frequency` is in **Hz** (126855000), while `airport.tower_frequency` and `ils.frequency` are in **kHz** (121280, 110500). Convert everything to integer kHz at load time.
  - **Headings are true:** runway 05 is 50.25°, which matches the ILS localizer (50.3°). `airport.mag_var` (+3.94° at EDDH) converts to magnetic for phraseology.
  - **COM types at EDDH:** `A` (118.205), `ATIS` (124.325), three `G`, two `T` (121.280, 126.855, the one the sim was tuned to), `UC`. There's **no clearance delivery entry**, so the Clearance → Ground → Tower fold-up is needed right at the first airport.
  - **ILS:** `runway_end.ils_ident` is empty. Join `ils` on `loc_airport_ident` + `loc_runway_name` instead.
  - **Taxi graph:** merging coordinates rounded to 7 decimals gives 582 nodes / 630 edges: one main component of 576 nodes plus one isolated 6-node area. Node merging works.
  - **Hold-short points are marked:** `start_type`/`end_type` = `HSND` (56 at EDDH).
  - **No runway segments in `taxi_path`** (no type `R`). Runway crossings (step 14) and runway entry checks (step 20) must therefore use runway geometry from `runway` (centreline ends + width), not taxi path types.
  - **⚠ Most taxi segments are unnamed:** at EDDH, 445 of 545 `PT` segments have `name = ''`. Only connectors like A1, B4, D1, Z5 are named. EDDF and EDDM look similar (mostly `PT`, a few `T`). **Open point for step 14:** decide between (a) propagating names along unnamed chains between two segments of the same name, (b) naming only the named parts of a route ("via D1, Z5"), or (c) falling back to "taxi to holding point runway X" when too much of the route is unnamed. Check how other airports look before deciding.
- **CUDA needs extra NVIDIA DLLs** (`cublas64_12.dll`, cuDNN 9) that aren't part of the driver (~1 GB via pip). Staying on CPU for now. Revisit only if real-mic latency is too slow.
- **SimConnect works** (parked at EDDH, Hamburg):
  - Heading comes in **radians** (3.948 → 226°), so convert to degrees.
  - COM1 comes in **MHz as a float** (`126.85499999999999`). Compare frequencies as integer kHz (`round(f * 1000)`), never with `==` on floats.
  - `PLANE_ALT_ABOVE_GROUND` is ~8.8 ft while parked (aircraft reference point, not the wheels). Use `SIM_ON_GROUND` for "on the ground", AGL only for thresholds like the go-around check.
  - `GROUND_VELOCITY` jitters around 0.01 kt while standing still. "Moving" needs a threshold (about 1 kt).
  - `AMBIENT_WIND_DIRECTION` is degrees **true**, heading is magnetic. Runway choice must compare wind and runway headings in the same reference (true).
  - Sim wind speed varied 8–13 kt within a minute, so average it before using it with `--weather sim`.

## Out of scope for now

- Controlling the other traffic (it never listens: LiveTraffic is real-world ADS-B). Moving the user around it is Milestone 6.
- VATSIM / IVAO, multiplayer
- MSFS 2024
- Emergencies (MAYDAY / PAN PAN), weather deviations, holding patterns
- Untowered airports outside Germany's Info stations, CTAF / UNICOM (German Info stations: Milestone 9)
- FAA phraseology (ICAO only)
