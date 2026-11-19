# Building a release

**Built 2026-11-16 (version 0.1.4):** `MSFS ATC.exe` in a folder (PyInstaller 6.22, Python 3.14), 316 MB, as a
zip of 140 MB. Read the **licences** section before publishing anything.

```
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python packaging\build.py [--source-url URL] [--simconnect PATH]
```

`packaging/build.py` runs `packaging/msfs_atc.spec` and writes `dist/MSFS ATC/` with `README.txt` (for users;
the source URL goes in), `LICENSE.txt` (GPL-3.0) and `THIRD_PARTY_LICENSES.txt` (every library of the build
with its licence text, read from the installed packages), then `dist/MSFS-ATC-<version>-win64.zip`.
`packaging/make_icon.py` draws `packaging/icon.ico` from the icon's shapes (numpy only).

**Tested on the developer's PC (2026-11-16):** started without a window, the page, the fonts (gzip) and the API
answer; a practice flight runs; the Piper voice loads (espeak-ng data is in the build); the whisper model is
downloaded on the first start with progress and loads; push-to-talk gets ready; ATC answers.
**Not tested yet:** the app window (WebView2) from the .exe, a flight with MSFS, a clean PC without Python.

**Open before publishing:**
- **Where to publish:** the GPL needs the source code with it (a public repository, the release next to it).
  `--source-url` puts its address into README.txt.
- **SimConnect.dll:** not in the build: whether the MSFS SDK licence allows shipping it is unclear (developers
  asked on Microsoft's own forum without an answer; an old ACES answer was no). Since 2026-11-16 `find_dll()` also
  uses a 64-bit copy another add-on already put on the PC: the folders of the programs in MSFS's EXE.xml, GSX's
  Couatl, the SDK's default folders.
- **Installer** (Inno Setup, outline below) or the zip only; **code signing** against virus-scanner warnings.
- **FFmpeg's licence text** (LGPL, its DLLs come with PyAV in `_internal/av.libs`) is not in
  THIRD_PARTY_LICENSES.txt yet.

## What is ready in the code

- **Read-only files** are found through `atc/paths.py` → `resources()`. That is the project folder while
  developing, and `sys._MEIPASS` (the `_internal` folder next to the .exe) in a build. They are:
  - the page, `atc/app/static/` (index.html, app.css, app.js, icon.svg, `fonts/` with B612);
  - `data/centers.json`, `data/centers_vatsim.json` and `data/stations_vatsim.json`.
- **Everything the app writes** goes to the user's folders, never next to the .exe (an install under
  `C:\Program Files` may not write there):
  - `%APPDATA%\MSFS ATC\settings.toml`: user settings (airport defaults, push-to-talk key, SimBrief username,
    API keys if a feature ever needs one);
  - `%LOCALAPPDATA%\MSFS ATC\`: `cache\`, `models\` (the whisper model), `logs\app.log`, `recordings\` and
    `window.json`.
- **No console:** in a windowed build there is no console, so `atc/app/__main__.py` sends messages to
  `logs\app.log` (the same happens under `pythonw`).
- **The whisper model is not bundled.** It is downloaded on the first start with progress messages
  (`atc/audio/setup.py`).
- **No API keys in the code.** None are needed today. If one is ever needed, it goes into `settings.toml`.

## Build steps (PyInstaller, one folder): how packaging/ does it

1. **Clean build environment:** a fresh venv with `pip install -r requirements.txt pyinstaller`.
2. **Entry script:** a small file (e.g. `packaging/msfs_atc.py`) that only calls
   `atc.app.__main__.main()`. PyInstaller needs a script file and can't start from `-m atc.app`.
3. **Icon:** convert `atc/app/static/icon.svg` to `packaging/icon.ico` (16, 32, 48, 256 px).
4. **Build with a `.spec` file** (better than a long command line, and it can be kept in git):
   - `--windowed` (no console) and `--name "MSFS ATC"`, `--icon packaging/icon.ico`;
   - data: `atc/app/static` → `atc/app/static`, `data/centers.json`, `data/centers_vatsim.json` and `data/stations_vatsim.json` → `data`.
     **Not** `data/airports` (see licences);
   - `--collect-data faster_whisper` (the voice-activity model `assets/silero_vad_v6.onnx`; without it every
     transcription fails);
   - `--collect-binaries ctranslate2` (whisper's DLLs);
   - `SimConnect.dll` next to the .exe: copy it from the MSFS SDK (`%MSFS_SDK%\SimConnect SDK\lib\SimConnect.dll`)
     into the build folder. `atc/sim/native.py` `find_dll()` looks there first (after the setting);
   - `--collect-all piper` (espeak-ng data and `espeakbridge.pyd`; without them Piper can't speak);
   - pywebview brings its own PyInstaller hook (`webview/__pyinstaller`), which includes
     `Microsoft.Web.WebView2.Core.dll`, `…WinForms.dll` and `WebBrowserInterop.x64.dll`. Check that
     pythonnet's `Python.Runtime.dll` and clr_loader's DLLs are in the build too
     (pyinstaller-hooks-contrib should cover them).
   - sounddevice needs `_sounddevice_data/portaudio-binaries` (covered by hooks-contrib; check).
5. **Test the build on a clean Windows machine or VM** (no Python, no Hugging Face cache):
   - first start: model download with progress, settings folder created;
   - with MSFS: SimConnect connects, COM1 is noticed, push-to-talk works and Zira speaks every transmission;
   - without MSFS: the clear message appears and practice mode works;
   - closing the window leaves no `MSFS ATC.exe` in Task Manager.

## Things to watch

| Topic | What can go wrong | What to do |
|---|---|---|
| **WebView2 runtime** | Windows 11 has it, older Windows 10 may not. Without it the window can't open (the app then falls back to the browser). | The installer checks the registry key `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` (value `pv`) and, if it is missing, runs Microsoft's *Evergreen Bootstrapper* (`MicrosoftEdgeWebview2Setup.exe /silent /install`), which Microsoft allows to be redistributed. |
| **SimConnect.dll** | Missing: "SimConnect.dll was not found" with what to do. Wrong bitness: MSFS is 64-bit, so the build must be 64-bit Python. | Copy it from the MSFS SDK next to the .exe, and test on a machine with MSFS. Licence: see below. |
| **comtypes (ATC voice)** | comtypes normally writes generated code to `comtypes\gen`, which is read-only inside a build. | `atc/audio/tts.py` uses SAPI with `dynamic=True` (IDispatch), so no code is generated. Still test the voice in the build. |
| **Bundled static files** | Missing `atc/app/static`: a blank window or 404s. Missing `data/centers_vatsim.json`: no Center sectors without Little Navmap. Missing `data/stations_vatsim.json`: German airports with the sim's roles only (no Delivery at EDDH). | The data entries above; `tests/test_paths.py` checks the files exist next to the code. |
| **Whisper model download** | No internet on the first start: no voice. Firewalls block huggingface.co. | Typing still works and the message says so. Optional for the installer: let the user pick a model folder or download it during setup. |
| **First-start time** | ~0.5 GB download plus ~3 s model load. | Already shown as progress in the radio log. |
| **Antivirus** | PyInstaller builds are often flagged as false positives. | Sign the .exe and the installer with a code-signing certificate; submit false positives to the vendors. |
| **Install location** | Per-machine installs need admin rights. | Prefer a per-user install (`PrivilegesRequired=lowest`, `{localappdata}\Programs\MSFS ATC`). The app never writes to its own folder, so both work. |
| **Uninstall** | User data in `%APPDATA%` / `%LOCALAPPDATA%` would stay. | The uninstaller asks whether to delete settings and the model (~0.5 GB). |

## Inno Setup (outline)

- `[Setup]`: AppName `MSFS ATC`, version from `pyproject.toml`, `DefaultDirName={autopf}\MSFS ATC`,
  `PrivilegesRequired=lowest`, `SetupIconFile=packaging\icon.ico`, `LicenseFile` (see licences).
- `[Files]`: everything in `dist\MSFS ATC\`, plus `MicrosoftEdgeWebview2Setup.exe` in `{tmp}`.
- `[Icons]`: Start menu entry, and an optional desktop icon.
- `[Run]`: the WebView2 bootstrapper with `Check: not WebView2Installed`; "Start MSFS ATC" at the end.
- `[UninstallDelete]` / `[Code]`: ask before deleting `{userappdata}\MSFS ATC` and `{localappdata}\MSFS ATC`.

## Licences and data sources (decide before publishing)

### Data: never ship

| Data | Why | In the code |
|---|---|---|
| The user's **Little Navmap database** | Built on the user's machine from the scenery they installed, payware add-ons included, and from MSFS's own airspace data. | `atc/airport/littlenavmap.py` (airports) and `atc/airspace/littlenavmap.py` (Center sectors and frequencies) read it in place. |
| **`data/airports/*.json`** | Exported from the developer's Little Navmap database; EDDH comes from the payware **simwings** add-on. Test data only. | `data/airports/README.md`, `atc/airport/export.py`, `atc/config.py` |
| **Navigraph data** (e.g. Little Navmap's `little_navmap_navigraph.sqlite`) | Licensed per user. | Not used anywhere; it must stay that way. |

### Data that is fine, with notes

| Data | Notes |
|---|---|
| `data/centers.json` | Our own file, empty: users can add corrections with real frequencies; those win over the other sectors. |
| `data/centers_vatsim.json` | German Center sectors (Bremen, Langen, Munich Radar), used without a Little Navmap database. Built by `python -m atc.airspace.vatsim` from the [VATSpy Data Project](https://github.com/vatsimnetwork/vatspy-data-project) (outlines) and the [VATGER datahub](https://github.com/VATGER-Nav/datahub) (frequencies), both **CC BY-SA 4.0**: one-way compatible with the GPL-3.0, needs attribution (README, README.txt, the file's `licence`) and the file stays CC BY-SA 4.0. **Not** vatglasses-data or vacs-data: CC BY-NC-SA (non-commercial), not compatible. |
| `data/stations_vatsim.json` | The roles of German airport frequencies: which one is Delivery, Apron (and which part of the field) or the VFR Tower, where the sim's data types them all Ground or Tower. Built by `python -m atc.airspace.vatsim --only stations` from the [VATGER datahub](https://github.com/VATGER-Nav/datahub) (`del.json`, `gnd.json`, `twr.json`), **CC BY-SA 4.0** like the Center file: attribution in README, README.txt and the file's `licence`. |
| METAR from aviationweather.gov | US government (NWS), public data, no key (`atc/weather/source.py`). |
| SimBrief | The user's own plan via their username (`atc/flightplan/simbrief.py`). Check SimBrief's API terms for a public app. |
| Whisper model | Downloaded at runtime from huggingface.co (Systran's CTranslate2 conversion of OpenAI whisper, MIT). Not bundled. |
| Windows voices (Zira) | Part of Windows, used through SAPI, not bundled. The fallback voice. |
| Piper voice `en_US-libritts_r-medium` | Downloaded at runtime from huggingface.co/rhasspy/piper-voices into `models\piper\`, not bundled. Trained on **LibriTTS-R, CC BY 4.0**: credit it on an About / credits page (Koizumi et al., "LibriTTS-R", Google; based on LibriTTS / LibriSpeech). Don't switch to voices with non-commercial data (`ryan`, `hfc_male`: CC BY-NC-SA) or `lessac` (Blizzard 2013 licence). |

### Libraries in the build

| Package | Licence | Note |
|---|---|---|
| **piper-tts** (contains **espeak-ng**) | **GPL-3.0-or-later** | **Decided by the user (2026-11-14): Piper is used directly**, so a public build is released as open source under the GPL-3.0, with its source code. The ATC voice sits behind `QueuedSpeech`, so it could be swapped later. Ships `espeakbridge.pyd` and `espeak-ng-data`: check that PyInstaller collects them (`--collect-all piper`). |
| ~~Python-SimConnect~~ | AGPL-3.0 | **Removed in step S1:** replaced by our own `ctypes` client, `atc/sim/native.py`. Old installs may still have the package; `find_dll()` only borrows its DLL as a fallback and never imports its code. |
| `SimConnect.dll` | Microsoft, part of the MSFS SDK | Not in the repository. Search order: `simconnect_dll` in settings.toml, next to the app, the MSFS SDK (`MSFS_SDK` / `MSFS2024_SDK`), an old Python-SimConnect package. **Before a public build:** check the MSFS SDK licence on shipping the DLL (many free tools, e.g. Little Navmap, ship it); otherwise users point the setting at their SDK. |
| tqdm | MPL-2.0 | Fine unmodified; keep the licence texts. |
| PyAV (`av`, needed by faster-whisper) | BSD-3; its wheels bundle FFmpeg (LGPL) | Keep it as separate DLLs (the default) and include the FFmpeg licence. |
| faster-whisper, ctranslate2, onnxruntime, pythonnet, comtypes, sounddevice (PortAudio), bottle, proxy_tools | MIT | Include the licence texts. |
| pywebview, numpy, httpx2, PyAV | BSD | Include the licence texts. |
| huggingface_hub, hf-xet, tokenizers | Apache-2.0 | Include the licence texts and NOTICE files. |
| pywin32 | PSF | Include the licence text. |
| Fonts B612 and B612 Mono (Airbus / Intactile, in `atc/app/static/fonts`) | SIL Open Font License 1.1 | Bundled so the app works offline; keep `fonts/OFL.txt` next to them. The fonts may be bundled and redistributed, but not sold on their own. |
| UI design values from [unslop](https://github.com/heydamir/unslop) | CC BY 4.0 | Credit to Damir Sokolovsky (@heydamir) is in `atc/app/static/app.css`; keep it, and add it to an About / credits page. |

A `THIRD_PARTY_LICENSES.txt` should be generated for every build, e.g. with `pip-licenses --with-license-file`
in the build venv, and shipped next to the .exe.
