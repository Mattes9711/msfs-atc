# PyInstaller build of MSFS ATC: one folder, "MSFS ATC.exe" without a console (see BUILD.md).
# Build: .venv\Scripts\python packaging\build.py   (it runs this spec, then writes the licences and the zip)
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "atc" / "app" / "static"), "atc/app/static"),  # the page, its fonts and icon
    (str(ROOT / "data" / "centers.json"), "data"),  # the (empty) corrections file; NOT data/airports (licences)
    (str(ROOT / "data" / "centers_vatsim.json"), "data"),  # German Center sectors, CC BY-SA 4.0 (VATSIM data)
    (str(ROOT / "data" / "stations_vatsim.json"), "data"),  # German airport station roles, CC BY-SA 4.0
    (str(ROOT / "packaging" / "README.txt"), "."),
]
binaries = []
hiddenimports = []

datas += collect_data_files("faster_whisper")  # the voice-activity model (assets/silero_vad_*.onnx)
binaries += collect_dynamic_libs("ctranslate2")  # whisper's DLLs
for package in ("piper", "webview"):  # piper: espeak-ng data and espeakbridge; webview: the WebView2 DLLs
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "packaging" / "msfs_atc.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "yaml", "tkinter"],  # test tools: never in the app
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MSFS ATC",
    icon=str(ROOT / "packaging" / "icon.ico"),
    console=False,
    upx=False,  # UPX-packed files are flagged by virus scanners more often
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MSFS ATC")
