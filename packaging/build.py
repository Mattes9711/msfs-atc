"""Build the release: "MSFS ATC.exe" in a folder, with its licences, packed as a zip to download.

    .venv\\Scripts\\python packaging\\build.py [--source-url URL] [--simconnect PATH]

1. PyInstaller with packaging/msfs_atc.spec → dist/MSFS ATC/
2. LICENSE.txt (GPL-3.0), README.txt (with where the source code is), THIRD_PARTY_LICENSES.txt (every library in
   the build with its licence text, read from the installed packages)
3. dist/MSFS-ATC-<version>-win64.zip

--simconnect copies SimConnect.dll next to the .exe. Only once it is clear that the MSFS SDK's licence allows
shipping it (BUILD.md, licences); without it, users point Settings > Simulator at their SDK.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APP = DIST / "MSFS ATC"
NOT_PUBLISHED = "(not published yet: ask whoever gave you this build)"


def version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def runtime_packages() -> list[str]:
    """The packages in requirements.txt and everything they need, by distribution name."""
    names = [line.split("==")[0].strip() for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
             if line.split("#")[0].strip()]
    seen: dict[str, metadata.Distribution] = {}
    todo = list(names)
    while todo:
        name = re.split(r"[\s;\[<>=!~]", todo.pop(), maxsplit=1)[0]
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[key] = dist
        for requirement in dist.requires or []:
            if "extra ==" not in requirement:  # optional extras are not installed for the app
                todo.append(requirement)
    return sorted(seen)


def licence_texts(name: str) -> tuple[str, list[tuple[str, str]]]:
    """(licence as declared, [(file name, text)]) of an installed distribution."""
    dist = metadata.distribution(name)
    meta = dist.metadata
    declared = meta.get("License-Expression") or meta.get("License") or ""
    if not declared or len(declared) > 80:  # some put the whole text in the field
        declared = next((c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if "License ::" in c), "")
    texts = []
    for file in dist.files or []:
        if re.search(r"(licen[cs]e|copying|notice)", file.name, re.I) and "dist-info" in str(file.parent).lower():
            try:
                texts.append((file.name, Path(dist.locate_file(file)).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                pass
    return declared, texts


def third_party_licences() -> str:
    parts = ["Libraries in MSFS ATC and their licences (from the installed packages the build was made with).\n"]
    for name in runtime_packages():
        dist = metadata.distribution(name)
        declared, texts = licence_texts(name)
        parts.append("=" * 100 + f"\n{dist.metadata['Name']} {dist.version}  -  {declared or 'see below'}\n" + "=" * 100)
        parts += [f"--- {file} ---\n{text.strip()}\n" for file, text in texts] or ["(no licence file in the package)\n"]
    parts.append("=" * 100 + "\nFonts B612 and B612 Mono: SIL Open Font License 1.1, see atc/app/static/fonts/OFL.txt "
                 "inside _internal.\n")
    return "\n".join(parts)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source-url", default=NOT_PUBLISHED, help="where the source code is published (GPL)")
    p.add_argument("--simconnect", type=Path, help="SimConnect.dll to put next to the .exe")
    args = p.parse_args()

    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
                    "--workpath", str(ROOT / "build"), str(ROOT / "packaging" / "msfs_atc.spec")], check=True)
    internal_readme = APP / "_internal" / "README.txt"
    readme = internal_readme.read_text(encoding="utf-8").replace("SOURCE_URL", args.source_url)
    internal_readme.unlink()
    (APP / "README.txt").write_text(readme, encoding="utf-8")
    shutil.copyfile(ROOT / "LICENSE", APP / "LICENSE.txt")
    (APP / "THIRD_PARTY_LICENSES.txt").write_text(third_party_licences(), encoding="utf-8")
    if args.simconnect:
        shutil.copyfile(args.simconnect, APP / "SimConnect.dll")

    archive = DIST / f"MSFS-ATC-{version()}-win64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for file in sorted(APP.rglob("*")):
            if file.is_file():
                z.write(file, Path("MSFS ATC") / file.relative_to(APP))
    size = sum(f.stat().st_size for f in APP.rglob("*") if f.is_file())
    print(f"{APP}  ({size / 1e6:.0f} MB)\n{archive}  ({archive.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
