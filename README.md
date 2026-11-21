# MSFS ATC

Voice ATC for Microsoft Flight Simulator 2020, running entirely on your own PC: no account, no subscription,
no cloud. You talk on push-to-talk; Clearance, Ground, Tower, Departure, Center and Approach answer in ICAO
phraseology, with a voice of their own for each controller.

> **Early test version (0.3.0).** Most of it has been flown in MSFS; the newest parts (VFR flights, the overlay,
> live speech text, co-pilot calls, GSX, cabin sound) so far only in practice mode and in the flight emulator.
> Reports are welcome in the Issues.

> **MSFS 2024: not tested yet.** It connects through SimConnect the same way, and MSFS ATC reads Little Navmap's
> MSFS 2024 database while MSFS 2024 runs (load the scenery library for MSFS 2024 in Little Navmap 3.0.14 or
> newer first). Whether that database has everything the taxi clearances need is still to be seen.

## What it does

- **The whole flight:** IFR clearance with SID and squawk, pushback, taxi with every named taxiway, holding point
  and runway crossings, takeoff, handoffs, Center sectors with direct-tos, the descent at the planned top of
  descent, STAR, radar vectors to the ILS, landing, taxi to the stand.
- **VFR flights:** from small fields with their Info station or none, the traffic circuit, through or across
  the control zone of a controlled field.
- **Arrival procedures** from Little Navmap: STAR and approach transition flown, descent by their constraints.
- **The app window:** a flight-strip console with your frequencies and what to say next, a map drawn like a
  chart (taxi diagram at the airport, frequencies of the area wherever you move it), the words while you speak,
  and a small overlay over the sim (windowed or borderless mode).
- **German airports** with their real stations from the VATGER datahub: Delivery, Apron East and West, a VFR
  Tower.
- **Readbacks are checked**, numbers spoken digit by digit; strict readbacks for training.
- **Real traffic** from LiveTraffic, FSLTL or MSFS: runway in use from the traffic, give way and follow on the
  ground, departure and wake turbulence spacing, the approach sequence, the other pilots on the frequency.
- **Ground watching:** wrong turns get a new route, "reduce taxi speed", progressive taxi on request.
- **A co-pilot** who takes the radio on request: reads back, tunes COM1, checks in and makes the calls of each
  phase.
- **Cabin announcements** in the airline's language and English, as heard through the cockpit door.
- **GSX Pro:** follows its boarding and pushback, requests the pushback after ATC's approval.
- **Practice mode** without MSFS: type or speak, move the aircraft with commands.
- **SimBrief:** loads your plan and shows a briefing before the flight.

Speech recognition is [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU; the voices are
[Piper](https://github.com/OHF-Voice/piper1-gpl). Airports, taxiways and frequencies come from your own
[Little Navmap](https://albar965.github.io/littlenavmap.html) database, so they match the scenery you fly.

## Download and start

Get `MSFS-ATC-<version>-win64.zip` from the [Releases](../../releases), unzip it anywhere and start
`MSFS ATC.exe`. The README.txt inside lists what you need:

- Windows 10 or 11, 64-bit, with the Microsoft Edge WebView2 Runtime
- MSFS 2020, and Little Navmap with its MSFS database built
- `SimConnect.dll`: found by itself in the MSFS SDK or with an add-on that brings one (GSX, or a program MSFS
  starts with itself); otherwise install the MSFS SDK or set its path in Settings > Simulator
- a microphone and a push-to-talk key or button

On the first start it downloads the speech models (about 0.6 GB) and the voices (about 140 MB).

## From source

```
start.bat
```

sets up a virtual environment with Python 3.12 or newer, installs `requirements.txt` and opens the app.
Without a window: `.venv\Scripts\python -m atc --text --nosim --from EDDH --to EDDM --callsign DLH4AB`.

Tests: `.venv\Scripts\python -m pip install -r requirements-dev.txt`, then `.venv\Scripts\python -m pytest`.
The tests that fly between Hamburg and Munich need those two airports exported from your own Little Navmap
database (see `data/airports/README.md`); without them they are skipped.

Building the release: see [BUILD.md](BUILD.md). The plan and the decisions behind it: [PLAN.md](PLAN.md).

## Licence

GPL-3.0-or-later (see [LICENSE](LICENSE)), because the voices use Piper and espeak-ng, which are GPL-3.0.
The release lists every library with its licence in THIRD_PARTY_LICENSES.txt.

Voices: Piper with the LibriTTS-R voice (CC BY 4.0) and the German Thorsten voice (CC0). Fonts: B612 and B612 Mono
by Airbus and Intactile (SIL Open Font License 1.1). Design values after
[unslop](https://github.com/heydamir/unslop) by Damir Sokolovsky (CC BY 4.0).

Center sectors without Little Navmap (Germany only): made from the
[VATSpy Data Project](https://github.com/vatsimnetwork/vatspy-data-project) and the
[VATGER datahub](https://github.com/VATGER-Nav/datahub), both CC BY-SA 4.0; `data/centers_vatsim.json` is CC BY-SA 4.0
too. The roles of the German airport frequencies (Delivery, Apron, VFR Tower) come from the VATGER datahub as well;
`data/stations_vatsim.json` is CC BY-SA 4.0. For the simulator only.

MSFS ATC is not made by or connected with Microsoft, Asobo Studio, FSDreamTeam (GSX), LiveTraffic or SimBrief.
