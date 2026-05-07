# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the LaboratoireSonore universal installer.
#
# Builds release/LaboratoireSonore-Installer.exe -- a single-file
# windowed Windows binary aimed at non-technical users who don't have
# Python installed. The bootstrap shim at installer/bootstrap/install.py
# remains the canonical install path for technical users.
#
# Equivalent CLI:
#   pyinstaller --name LaboratoireSonore-Installer \
#               --onefile \
#               --windowed \
#               --add-data "src/assets/heroes/*.png;assets/heroes" \
#               --hidden-import customtkinter \
#               --hidden-import PIL.Image \
#               --hidden-import PIL.ImageTk \
#               --collect-data customtkinter \
#               installer/src/lab_installer.py
#
# ASCII-only -- the parent project hit Windows-cp1252 console issues
# with Unicode em-dashes; keep "--" and "->" rather than fancy glyphs.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# When PyInstaller exec's this spec, __file__ is not always set on the
# spec itself; SPECPATH is the canonical "directory containing the spec"
# variable provided by PyInstaller. Fall back to cwd so a manual
# `python -m PyInstaller lab_installer.spec` from the installer/ dir
# also works.
try:
    HERE = Path(SPECPATH).resolve()  # noqa: F821 -- injected by PyInstaller
except NameError:
    HERE = Path(os.getcwd()).resolve()

# Path to the actual entry script we're freezing. lab_installer.py is
# the single front door: --list / --install for CLI, GUI fallback when
# called bare. Bundling installer/src/lab_installer.py (NOT the
# bootstrap shim) is what gives the .exe its full feature set offline.
ENTRY = HERE / "src" / "lab_installer.py"

# Hero PNGs ship inside the binary so the GUI looks polished even when
# the user runs the .exe from a USB stick with no internet. Source side
# is "src/assets/heroes/*.png"; in the bundle they land at
# "assets/heroes/<id>.png" so manifest.py / gui.py's runtime resolution
# (Path(__file__).parent / "assets" / "heroes") still finds them.
hero_assets = [
    (str(HERE / "src" / "assets" / "heroes" / "*.png"), "assets/heroes"),
]

# customtkinter ships theme JSON + asset files alongside its .py
# modules. PyInstaller doesn't pick those up automatically because they
# aren't .py imports -- collect_data_files walks the package and grabs
# the data files explicitly. Without this, the bundled .exe imports
# customtkinter cleanly but every theme call raises FileNotFoundError
# at runtime, taking the whole GUI down. gui.py would catch that and
# fall back to plain Tk, but the user would briefly see a half-rendered
# window before the fallback kicked in.
ctk_datas = []
try:
    ctk_datas = collect_data_files("customtkinter")
except Exception:
    # If customtkinter isn't installed in the build environment, fall
    # back gracefully -- gui.py already handles missing customtkinter
    # at runtime via try/except ImportError. The bundled .exe will then
    # use plain tkinter.ttk, which trims roughly 3 MB off the binary.
    ctk_datas = []

# Hidden imports: PyInstaller's static analysis won't follow lazy
# `from . import customtkinter` calls inside try/except blocks (gui.py
# imports both customtkinter and PIL conditionally). Listing them
# explicitly forces PyInstaller to bundle the modules it would
# otherwise skip.
hidden_imports = [
    "customtkinter",
    "PIL.Image",
    "PIL.ImageTk",
    # cryptography backend modules -- AESGCM pulls in a chain of
    # OpenSSL bindings via cryptography.hazmat; PyInstaller's hook for
    # cryptography catches the top level but occasionally misses the
    # backend module on minimal Python installs. Pinning it here is
    # cheap insurance.
    "cryptography.hazmat.backends.openssl",
    "cryptography.hazmat.bindings._rust",
]


a = Analysis(
    [str(ENTRY)],
    pathex=[str(HERE / "src")],
    binaries=[],
    datas=hero_assets + ctk_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Excludes: shave heft by dropping packages PyInstaller's analyzer
    # pulls in transitively but lab_installer.py never uses. numpy is
    # the big one -- PIL doesn't need it for the basic resize/convert
    # ops we do, but installs that have it on PYTHONPATH will pull
    # ~30 MB of NumPy + MKL into the bundle for nothing.
    excludes=[
        "numpy",
        "scipy",
        "pandas",
        "matplotlib",
        "pytest",
        "IPython",
        "jupyter",
        "tornado",
        # Test-only modules from our own tree -- tests/ is sibling to
        # src/, but the analyser sometimes grabs it via relative import
        # discovery. Excluding by name is safer than relying on path
        # exclusion since CI may check out the repo at different roots.
        "installer.tests",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LaboratoireSonore-Installer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX compression is appealing for a "<30 MB" goal but trips
    # Windows Defender / SmartScreen heuristics on unsigned binaries;
    # the user experience of an "untrusted publisher" warning is
    # strictly worse than a few extra megabytes. Leave UPX off until
    # we have an EV cert to sign with.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # --windowed: hide the cmd-prompt window when launched by
    # double-clicking the .exe. CLI users invoke via PowerShell /
    # cmd anyway, where stdout/stderr still bind correctly.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Optional: app icon. We don't ship a .ico yet -- when one lands at
    # installer/src/assets/icon.ico, drop it in here.
    # icon=str(HERE / "src" / "assets" / "icon.ico"),
)

# --onefile vs --onedir: presence of a COLLECT() step is what
# distinguishes the two. By passing a.binaries + a.datas directly into
# EXE() above (instead of into a separate COLLECT() at the end),
# PyInstaller produces a single self-extracting LaboratoireSonore-
# Installer.exe at dist/. Our GitHub Actions workflow then moves that
# file to release/ before uploading it as a release asset.

