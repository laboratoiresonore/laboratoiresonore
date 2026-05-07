"""Pin the per-kind action contracts: dispatch, dry-run plans,
platform detection, and graceful failure on every error path."""

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from installer.src import actions
from installer.src.actions import InstallResult, run_install, detect_platform


# ── Platform detection ────────────────────────────────────────────────

class PlatformDetectionTests(unittest.TestCase):

    def test_windows(self):
        with mock.patch.object(actions.sys, "platform", "win32"):
            self.assertEqual(detect_platform(), "windows")

    def test_windows_cygwin(self):
        with mock.patch.object(actions.sys, "platform", "cygwin"):
            # cygwin is not "win32" but starts with "win"... actually it
            # doesn't. Cygwin reports "cygwin". We treat it as unsupported.
            with self.assertRaises(ValueError):
                detect_platform()

    def test_macos_arm64(self):
        with mock.patch.object(actions.sys, "platform", "darwin"), \
             mock.patch.object(actions._platform_module, "machine",
                               return_value="arm64"):
            self.assertEqual(detect_platform(), "macos-arm64")

    def test_macos_aarch64(self):
        with mock.patch.object(actions.sys, "platform", "darwin"), \
             mock.patch.object(actions._platform_module, "machine",
                               return_value="aarch64"):
            self.assertEqual(detect_platform(), "macos-arm64")

    def test_macos_x64(self):
        with mock.patch.object(actions.sys, "platform", "darwin"), \
             mock.patch.object(actions._platform_module, "machine",
                               return_value="x86_64"):
            self.assertEqual(detect_platform(), "macos-x64")

    def test_macos_amd64(self):
        with mock.patch.object(actions.sys, "platform", "darwin"), \
             mock.patch.object(actions._platform_module, "machine",
                               return_value="AMD64"):
            self.assertEqual(detect_platform(), "macos-x64")

    def test_macos_unknown_arch_raises(self):
        with mock.patch.object(actions.sys, "platform", "darwin"), \
             mock.patch.object(actions._platform_module, "machine",
                               return_value="ppc64"):
            with self.assertRaises(ValueError):
                detect_platform()

    def test_linux(self):
        with mock.patch.object(actions.sys, "platform", "linux"):
            self.assertEqual(detect_platform(), "linux")

    def test_linux2(self):
        with mock.patch.object(actions.sys, "platform", "linux2"):
            self.assertEqual(detect_platform(), "linux")

    def test_unknown_platform_raises(self):
        with mock.patch.object(actions.sys, "platform", "haiku"):
            with self.assertRaises(ValueError):
                detect_platform()


# ── Helpers ───────────────────────────────────────────────────────────

def _fake_release_response(tag, asset_names):
    """Build a urlopen-compatible context manager that yields a fake
    GitHub releases/latest JSON body."""
    body = json.dumps({
        "tag_name": tag,
        "assets": [
            {
                "name": name,
                "browser_download_url": f"https://example.invalid/{name}",
            }
            for name in asset_names
        ],
    }).encode("utf-8")
    cm = mock.MagicMock()
    cm.__enter__.return_value = io.BytesIO(body)
    cm.__exit__.return_value = False
    return cm


BEATWEAVER_ENTRY = {
    "id": "beatweaver",
    "name": "BeatWeaver",
    "summary": "DJ overlay tool",
    "repo": "laboratoiresonore/beatweaver",
    "installer": {
        "kind": "electron_release",
        "asset_pattern": {
            "windows":     "Beatweaver.Setup.{version}.exe",
            "macos-x64":   "Beatweaver-{version}-mac.zip",
            "macos-arm64": "Beatweaver-{version}-arm64-mac.zip",
            "linux":       "Beatweaver-{version}.AppImage",
        },
    },
}

SPELLCASTER_PY_ENTRY = {
    "id": "spellcaster",
    "name": "Spellcaster",
    "summary": "AI image gen",
    "repo": "laboratoiresonore/spellcaster",
    "installer": {"kind": "run_python_installer"},
}

COMFYUI_NODE_ENTRY = {
    "id": "comfyui-spellcaster",
    "name": "ComfyUI-Spellcaster",
    "summary": "custom nodes",
    "repo": "laboratoiresonore/ComfyUI-Spellcaster",
    "installer": {
        "kind": "git_clone",
        "target_dir": "{comfyui_root}/custom_nodes/ComfyUI-Spellcaster",
    },
}


# ── electron_release ──────────────────────────────────────────────────

class ElectronReleaseTests(unittest.TestCase):

    def test_dry_run_picks_correct_asset_for_windows(self):
        fake = _fake_release_response(
            "v1.2.3",
            ["Beatweaver.Setup.1.2.3.exe",
             "Beatweaver-1.2.3-mac.zip",
             "Beatweaver-1.2.3-arm64-mac.zip",
             "Beatweaver-1.2.3.AppImage"],
        )
        with mock.patch.object(actions.urllib.request, "urlopen",
                               return_value=fake):
            result = run_install(
                BEATWEAVER_ENTRY, platform="windows", dry_run=True)
        self.assertTrue(result.success, msg=result.message)
        self.assertIn("Beatweaver.Setup.1.2.3.exe", result.message)
        self.assertIsNotNone(result.artifact_path)
        self.assertTrue(
            str(result.artifact_path).endswith("Beatweaver.Setup.1.2.3.exe"))

    def test_dry_run_strips_v_prefix_from_tag(self):
        fake = _fake_release_response(
            "v0.9.0", ["Beatweaver-0.9.0.AppImage"])
        with mock.patch.object(actions.urllib.request, "urlopen",
                               return_value=fake):
            result = run_install(
                BEATWEAVER_ENTRY, platform="linux", dry_run=True)
        self.assertTrue(result.success, msg=result.message)
        self.assertIn("Beatweaver-0.9.0.AppImage", result.message)

    def test_dry_run_handles_tag_without_v_prefix(self):
        fake = _fake_release_response(
            "1.2.3", ["Beatweaver-1.2.3-arm64-mac.zip"])
        with mock.patch.object(actions.urllib.request, "urlopen",
                               return_value=fake):
            result = run_install(
                BEATWEAVER_ENTRY, platform="macos-arm64", dry_run=True)
        self.assertTrue(result.success, msg=result.message)
        self.assertIn("Beatweaver-1.2.3-arm64-mac.zip", result.message)

    def test_platform_mismatch_returns_clear_failure(self):
        # Pattern dict doesn't have a key for the runtime platform.
        entry = dict(BEATWEAVER_ENTRY)
        entry["installer"] = {
            "kind": "electron_release",
            "asset_pattern": {"linux": "Foo-{version}.AppImage"},
        }
        result = run_install(entry, platform="windows", dry_run=True)
        self.assertFalse(result.success)
        self.assertIn("no asset_pattern", result.message)
        self.assertIn("windows", result.message)
        self.assertIsNone(result.artifact_path)

    def test_no_matching_asset_in_release(self):
        # Release exists but doesn't carry the file we expect -- likely
        # a release-rename or pattern drift; surface the available
        # names so the operator can fix the manifest.
        fake = _fake_release_response(
            "v2.0.0", ["something-else.zip"])
        with mock.patch.object(actions.urllib.request, "urlopen",
                               return_value=fake):
            result = run_install(
                BEATWEAVER_ENTRY, platform="linux", dry_run=True)
        self.assertFalse(result.success)
        self.assertIn("no asset named", result.message)
        self.assertIn("something-else.zip", result.message)

    def test_url_error_returns_failure_no_files_left(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(
                actions.urllib.request, "urlopen",
                side_effect=urllib.error.URLError("network down"),
            ), mock.patch.object(
                actions, "_download_dir",
                return_value=Path(td) / "beatweaver",
            ):
                result = run_install(
                    BEATWEAVER_ENTRY, platform="linux", dry_run=False)
        self.assertFalse(result.success)
        self.assertIn("could not reach GitHub API", result.message)
        # No file should have been written: the failure is at API
        # resolution time, before any download could begin.
        self.assertIsNone(result.artifact_path)

    def test_download_url_error_cleans_up_partial(self):
        # API call succeeds; the download itself fails. The .part
        # file must NOT remain on disk masquerading as a real
        # installer.
        fake_release = _fake_release_response(
            "v1.0.0", ["Beatweaver-1.0.0.AppImage"])

        def urlopen_side_effect(url, *args, **kwargs):
            # First call (API) succeeds; second (download) fails.
            target = url
            if hasattr(url, "full_url"):
                target = url.full_url
            if "api.github.com" in str(target):
                return fake_release
            raise urllib.error.URLError("download blocked")

        with tempfile.TemporaryDirectory() as td:
            target_dir = Path(td) / "beatweaver"
            with mock.patch.object(
                actions.urllib.request, "urlopen",
                side_effect=urlopen_side_effect,
            ), mock.patch.object(
                actions, "_download_dir", return_value=target_dir,
            ):
                result = run_install(
                    BEATWEAVER_ENTRY, platform="linux", dry_run=False)

            self.assertFalse(result.success)
            self.assertIn("download failed", result.message)
            # No leftover .part or final file in target dir.
            if target_dir.exists():
                leftovers = list(target_dir.iterdir())
                self.assertEqual(leftovers, [],
                                 f"unexpected leftovers: {leftovers}")

    def test_invalid_json_response_returns_failure(self):
        cm = mock.MagicMock()
        cm.__enter__.return_value = io.BytesIO(b"<html>not json</html>")
        cm.__exit__.return_value = False
        with mock.patch.object(actions.urllib.request, "urlopen",
                               return_value=cm):
            result = run_install(
                BEATWEAVER_ENTRY, platform="linux", dry_run=True)
        self.assertFalse(result.success)
        self.assertIn("non-JSON", result.message)

    def test_release_missing_tag_name(self):
        body = json.dumps({"assets": []}).encode("utf-8")
        cm = mock.MagicMock()
        cm.__enter__.return_value = io.BytesIO(body)
        cm.__exit__.return_value = False
        with mock.patch.object(actions.urllib.request, "urlopen",
                               return_value=cm):
            result = run_install(
                BEATWEAVER_ENTRY, platform="linux", dry_run=True)
        self.assertFalse(result.success)
        self.assertIn("no tag_name", result.message)


# ── run_python_installer ──────────────────────────────────────────────

class RunPythonInstallerTests(unittest.TestCase):

    def test_dry_run_plans_clone_when_no_checkout(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "spellcaster"
            with mock.patch.object(actions, "_source_dir", return_value=dest):
                result = run_install(SPELLCASTER_PY_ENTRY, dry_run=True)
        self.assertTrue(result.success, msg=result.message)
        self.assertIn("git clone", result.message)
        self.assertIn("https://github.com/laboratoiresonore/spellcaster.git",
                      result.message)
        self.assertIn("install.py --yes", result.message)
        self.assertEqual(result.artifact_path, dest)

    def test_dry_run_plans_pull_when_checkout_exists(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "spellcaster"
            (dest / ".git").mkdir(parents=True)
            with mock.patch.object(actions, "_source_dir", return_value=dest):
                result = run_install(SPELLCASTER_PY_ENTRY, dry_run=True)
        self.assertTrue(result.success, msg=result.message)
        self.assertIn("git", result.message)
        self.assertIn("pull", result.message)
        self.assertNotIn("clone", result.message)

    def test_dry_run_does_not_invoke_subprocess(self):
        # The dry-run path must never shell out -- that's the point.
        with mock.patch.object(actions.subprocess, "run") as sub_run:
            run_install(SPELLCASTER_PY_ENTRY, dry_run=True)
        sub_run.assert_not_called()


# ── git_clone ─────────────────────────────────────────────────────────

class GitCloneTests(unittest.TestCase):

    def test_dry_run_substitutes_comfyui_root_from_env(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(actions.os.environ,
                                 {"COMFYUI_ROOT": td}, clear=False):
                result = run_install(COMFYUI_NODE_ENTRY, dry_run=True)
        self.assertTrue(result.success, msg=result.message)
        self.assertIn(td, result.message)
        self.assertIn("custom_nodes", result.message)
        self.assertIn("ComfyUI-Spellcaster", str(result.artifact_path))

    def test_dry_run_falls_back_to_home_when_no_env(self):
        env = {k: v for k, v in actions.os.environ.items()
               if k != "COMFYUI_ROOT"}
        with mock.patch.object(actions.os, "environ", env):
            result = run_install(COMFYUI_NODE_ENTRY, dry_run=True)
        self.assertTrue(result.success, msg=result.message)
        # Default fallback path.
        self.assertIn("ComfyUI", str(result.artifact_path))
        self.assertIn("custom_nodes", str(result.artifact_path))

    def test_dry_run_does_not_invoke_subprocess(self):
        with mock.patch.object(actions.subprocess, "run") as sub_run:
            run_install(COMFYUI_NODE_ENTRY, dry_run=True)
        sub_run.assert_not_called()

    def test_missing_target_dir_returns_failure(self):
        entry = {
            "id": "broken",
            "name": "broken",
            "repo": "x/y",
            "installer": {"kind": "git_clone"},
        }
        result = run_install(entry, dry_run=True)
        self.assertFalse(result.success)
        self.assertIn("no target_dir", result.message)


# ── Dispatch ──────────────────────────────────────────────────────────

class DispatchTests(unittest.TestCase):

    def test_unknown_kind_returns_failure(self):
        entry = {
            "id": "weird",
            "name": "weird",
            "repo": "x/y",
            "installer": {"kind": "totally_made_up"},
        }
        result = run_install(entry, dry_run=True)
        self.assertFalse(result.success)
        self.assertIn("unknown installer kind", result.message)
        self.assertIn("totally_made_up", result.message)

    def test_missing_installer_block_returns_failure(self):
        entry = {"id": "bare", "name": "bare", "repo": "x/y"}
        result = run_install(entry, dry_run=True)
        self.assertFalse(result.success)
        self.assertIn("installer block", result.message)

    def test_non_dict_app_entry_returns_failure(self):
        # run_install must NEVER raise.
        result = run_install("not a dict", dry_run=True)  # type: ignore[arg-type]
        self.assertFalse(result.success)
        self.assertIn("must be a dict", result.message)

    def test_run_install_never_raises_on_internal_error(self):
        # Force an internal exception from a dependency to confirm
        # the catch-all wrapper holds.
        with mock.patch.object(actions, "_install_git_clone",
                               side_effect=RuntimeError("kaboom")):
            result = run_install(COMFYUI_NODE_ENTRY, dry_run=True)
        self.assertFalse(result.success)
        self.assertIn("kaboom", result.message)
        self.assertEqual(result.app_id, "comfyui-spellcaster")

    def test_install_result_is_dataclass_with_all_fields(self):
        r = InstallResult(
            success=True, message="ok", app_id="x",
            artifact_path=Path("/tmp/x"))
        self.assertTrue(r.success)
        self.assertEqual(r.message, "ok")
        self.assertEqual(r.app_id, "x")
        self.assertEqual(r.artifact_path, Path("/tmp/x"))


if __name__ == "__main__":
    unittest.main()
