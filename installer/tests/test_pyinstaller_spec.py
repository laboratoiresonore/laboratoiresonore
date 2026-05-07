"""Smoke tests for installer/lab_installer.spec.

Running PyInstaller for real would take minutes, so these tests just
parse the spec as Python and verify the load-bearing knobs are set
correctly. The CI workflow (.github/workflows/build-installer.yml) is
what actually executes PyInstaller end-to-end.

Why this matters: the spec file is the single source of truth for the
bundled .exe -- name, hidden imports, and bundled assets all live
there. A regression like dropping the customtkinter hidden import
silently degrades the GUI without breaking any other test, so we pin
the contract here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


SPEC_PATH = Path(__file__).resolve().parents[1] / "lab_installer.spec"


def _spec_source() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def _spec_ast() -> ast.Module:
    return ast.parse(_spec_source())


def test_spec_file_exists():
    assert SPEC_PATH.is_file(), f"missing: {SPEC_PATH}"


def test_spec_parses_as_python():
    # The spec is exec'd by PyInstaller; if it's not even valid Python
    # the build will fail with a parse error rather than something
    # actionable.
    _spec_ast()


def test_spec_is_ascii_only():
    # ASCII-only constraint -- the parent project hit Windows-cp1252
    # console decoding errors on Unicode em-dashes / arrows. Keep "--"
    # and "->" instead.
    src = _spec_source()
    src.encode("ascii")  # raises UnicodeEncodeError if any non-ASCII char


def _find_exe_call(tree: ast.Module) -> ast.Call:
    """Locate the EXE(...) constructor call in the spec."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "EXE":
                return node
    raise AssertionError("no EXE() call found in spec")


def _kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def test_exe_name_is_pinned():
    # The bundled binary's filename is part of the public contract --
    # the workflow's "Stage release artifact" step expects exactly
    # this name. Renaming requires updating both files.
    exe = _find_exe_call(_spec_ast())
    name_node = _kwarg(exe, "name")
    assert isinstance(name_node, ast.Constant)
    assert name_node.value == "LaboratoireSonore-Installer"


def test_exe_is_windowed():
    # console=False (= --windowed) hides the cmd-prompt window when the
    # user double-clicks the .exe. Critical for the non-technical
    # audience this binary targets.
    exe = _find_exe_call(_spec_ast())
    console_node = _kwarg(exe, "console")
    assert isinstance(console_node, ast.Constant)
    assert console_node.value is False


def test_hidden_imports_cover_optional_gui_deps():
    # gui.py imports customtkinter and PIL inside try/except, which
    # PyInstaller's static analyser skips. Without these in the
    # hidden_imports list the bundled .exe imports both modules from
    # the .pyz at runtime and falls back to plain Tk -- silently
    # degrading the GUI.
    src = _spec_source()
    for needed in ("customtkinter", "PIL.Image", "PIL.ImageTk"):
        assert needed in src, f"hidden import missing: {needed}"


def test_hero_assets_are_bundled():
    # Hero PNGs need to land at assets/heroes/ in the bundle so
    # gui.hero_path_for() finds them via _MEIPASS resolution.
    src = _spec_source()
    assert "assets/heroes" in src
    assert "src/assets/heroes" in src or "src\\assets\\heroes" in src


def test_no_collect_step():
    # --onefile is implemented by NOT having a COLLECT(...) call --
    # all binaries/datas go straight into EXE(). If somebody adds a
    # COLLECT step the build silently switches to --onedir and the
    # release workflow's Move-Item path breaks.
    tree = _spec_ast()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "COLLECT":
                pytest.fail("COLLECT() call found -- spec must stay --onefile")


def test_excludes_drop_heavy_packages():
    # numpy / scipy / pandas don't belong in a bundled installer; they
    # bloat the binary by tens of MB if they happen to be on the
    # build runner's PYTHONPATH. The exclude list pins them out.
    src = _spec_source()
    for excluded in ("numpy", "scipy", "pandas"):
        assert excluded in src, f"missing exclude: {excluded}"
