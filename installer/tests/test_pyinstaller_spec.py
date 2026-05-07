"""Smoke tests for installer/lab_installer.spec.

Running PyInstaller for real would take minutes, so these tests just
parse the spec as Python and verify the load-bearing knobs are set
correctly. The CI workflow (.github/workflows/build-installer.yml) is
what actually executes PyInstaller end-to-end.

Why this matters: the spec file is the single source of truth for the
bundled binary -- name, hidden imports, and bundled assets all live
there. A regression like dropping the customtkinter hidden import
silently degrades the GUI without breaking any other test, so we pin
the contract here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


SPEC_PATH = Path(__file__).resolve().parents[1] / "lab_installer.spec"
WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "build-installer.yml"
)


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


def _find_call(tree: ast.Module, name: str) -> ast.Call | None:
    """Locate the first <name>(...) constructor call in the spec."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == name:
                return node
    return None


def _find_exe_call(tree: ast.Module) -> ast.Call:
    call = _find_call(tree, "EXE")
    if call is None:
        raise AssertionError("no EXE() call found in spec")
    return call


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
    # audience this binary targets. On macOS this is also what flags
    # the EXE as windowed for BUNDLE() to wrap.
    exe = _find_exe_call(_spec_ast())
    console_node = _kwarg(exe, "console")
    assert isinstance(console_node, ast.Constant)
    assert console_node.value is False


def test_hidden_imports_cover_optional_gui_deps():
    # gui.py imports customtkinter and PIL inside try/except, which
    # PyInstaller's static analyser skips. Without these in the
    # hidden_imports list the bundled binary imports both modules from
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


# ---------------------------------------------------------------------------
# Cross-platform packaging logic.
#
# The spec branches on sys.platform == 'darwin' to wrap the EXE in a
# BUNDLE(...) call so PyInstaller emits a proper .app on macOS. Linux
# and Windows fall through and ship the bare EXE as a single-file
# binary. These tests pin that contract structurally so a refactor that
# accidentally drops the BUNDLE step (or, conversely, makes BUNDLE
# unconditional and breaks Linux/Windows) gets caught.
# ---------------------------------------------------------------------------


def test_spec_has_bundle_call_for_macos():
    # On macOS PyInstaller emits a bare Mach-O by default; without
    # BUNDLE() the .exe equivalent is a Unix executable that opens
    # Terminal when double-clicked instead of launching the GUI.
    bundle = _find_call(_spec_ast(), "BUNDLE")
    assert bundle is not None, "spec must call BUNDLE() for macOS .app output"


def test_bundle_call_is_gated_on_darwin():
    # The BUNDLE() call must live inside an `if sys.platform == 'darwin':`
    # block. On Linux/Windows BUNDLE() is either a no-op (recent
    # PyInstaller) or an error -- either way running it unconditionally
    # is wrong, since Linux ships a bare ELF and Windows ships a .exe.
    src = _spec_source()
    assert "sys.platform" in src, "spec must inspect sys.platform"
    assert "darwin" in src, "spec must branch on 'darwin'"

    # Walk the AST and confirm BUNDLE() sits inside an `if` whose test
    # mentions sys.platform. This catches the "moved BUNDLE() out of
    # the guard" refactor regression.
    tree = _spec_ast()
    found_guarded = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Cheap check: the if's test source contains 'platform'.
        test_src = ast.unparse(node.test) if hasattr(ast, "unparse") else ""
        if "platform" not in test_src:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                fn = child.func
                if isinstance(fn, ast.Name) and fn.id == "BUNDLE":
                    found_guarded = True
                    break
        if found_guarded:
            break
    assert found_guarded, "BUNDLE() call must be guarded by sys.platform check"


def test_bundle_name_is_dot_app():
    # The .app suffix is what Finder / Launchpad use to recognise the
    # bundle as an application. Stripping it would produce a folder
    # called "LaboratoireSonore-Installer" that double-click opens in
    # Finder instead of launching.
    bundle = _find_call(_spec_ast(), "BUNDLE")
    assert bundle is not None
    name_node = _kwarg(bundle, "name")
    assert isinstance(name_node, ast.Constant)
    assert name_node.value == "LaboratoireSonore-Installer.app"


def test_bundle_has_bundle_identifier():
    # bundle_identifier is what macOS uses to disambiguate apps for
    # Launch Services + codesign. PyInstaller will synthesise a default
    # if missing, but pinning it here keeps releases consistent across
    # builds (otherwise the identifier could drift if PyInstaller's
    # default ever changes).
    bundle = _find_call(_spec_ast(), "BUNDLE")
    assert bundle is not None
    bid = _kwarg(bundle, "bundle_identifier")
    assert isinstance(bid, ast.Constant)
    assert bid.value.startswith("com."), "use reverse-DNS bundle id"


def test_spec_uses_portable_data_tuples_not_pathsep():
    # PyInstaller's CLI form is "src;dest" on Windows and "src:dest"
    # on macOS/Linux, but specs accept (src, dest) tuples directly --
    # which is what we use in `hero_assets`. This test guards against
    # someone "helpfully" rewriting the data list to use a hardcoded
    # ';' separator string, which would silently break the macOS +
    # Linux builds.
    src = _spec_source()
    # The CLI-form string only appears inside the comment header as
    # documentation; outside that we should never see "*.png;assets"
    # as a literal in actual code.
    code_only = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "*.png;assets" not in code_only, (
        "spec uses Windows-only ';' add-data separator -- "
        "switch to (src, dest) tuples for cross-platform builds"
    )


# ---------------------------------------------------------------------------
# CI workflow file.
# ---------------------------------------------------------------------------


def test_workflow_file_parses_as_yaml():
    # Catches indentation / quoting regressions before push: a malformed
    # workflow yields an "invalid workflow file" GitHub Actions error
    # that's only visible after committing + pushing a tag, by which
    # point the broken release is half-cut.
    yaml = pytest.importorskip("yaml")
    with WORKFLOW_PATH.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict)
    assert "jobs" in loaded


def test_workflow_has_three_platform_matrix():
    # Pin the matrix shape -- if someone drops macos-latest or
    # ubuntu-latest by accident the release will silently regress to
    # Windows-only. PyYAML returns the matrix as nested dicts/lists,
    # so we walk into jobs.build.strategy.matrix.include and check.
    yaml = pytest.importorskip("yaml")
    with WORKFLOW_PATH.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    include = loaded["jobs"]["build"]["strategy"]["matrix"]["include"]
    oses = {entry["os"] for entry in include}
    assert oses == {"windows-latest", "macos-latest", "ubuntu-latest"}


def test_workflow_release_job_scoped_permissions():
    # The release job needs `contents: write` to publish; the build
    # jobs do not. Workflow-wide write permissions are an unnecessary
    # blast radius (any compromised step could push a tag). Pin the
    # least-privilege scoping here.
    yaml = pytest.importorskip("yaml")
    with WORKFLOW_PATH.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    # Workflow-level permissions should not exist (or should be empty).
    assert "permissions" not in loaded or not loaded.get("permissions")
    # Release-job permissions should grant contents: write.
    rel_perms = loaded["jobs"]["release"].get("permissions", {})
    assert rel_perms.get("contents") == "write"
