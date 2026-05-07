"""Pin the bootstrap shim's contract -- URL construction + cache TTL +
fallback semantics. The shim is identical across every LaboratoireSonore
repo; if any of these break, every repo's installer breaks at once.

We don't actually hit the network here -- every urllib call is mocked.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
BOOTSTRAP = HERE.parents[1] / "installer" / "bootstrap" / "install.py"

# Load the bootstrap module by file path so we can test it in
# isolation. Requires Python 3.4+ (importlib.util.spec_from_file_location).
import importlib.util
spec = importlib.util.spec_from_file_location("lab_bootstrap", BOOTSTRAP)
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class ProtocolUrlsTests(unittest.TestCase):

    def test_master_base_points_at_main(self):
        # Anyone changing this is touching the protocol -- bump VERSION
        # major + re-sync every repo's shim.
        self.assertEqual(boot.MASTER_REPO, "laboratoiresonore/laboratoiresonore")
        self.assertEqual(boot.MASTER_BRANCH, "main")
        self.assertTrue(boot.MASTER_BASE.startswith("https://"))
        self.assertIn("laboratoiresonore/laboratoiresonore/main/installer",
                       boot.MASTER_BASE)

    def test_protocol_files_are_minimal(self):
        # Don't grow this list lightly -- every entry is a required
        # download. New stuff goes in PROTOCOL_OPTIONAL or stays in the
        # master's local-only state.
        self.assertIn("src/lab_installer.py", boot.PROTOCOL_FILES)
        self.assertIn("src/manifest.py", boot.PROTOCOL_FILES)
        self.assertLessEqual(len(boot.PROTOCOL_FILES), 6,
                              "PROTOCOL_FILES growing -- review carefully")


class CacheTTLTests(unittest.TestCase):
    """Cache TTL keeps the bootstrap quiet on repeated launches."""

    def test_ttl_is_24_hours(self):
        self.assertEqual(boot.CACHE_TTL_SEC, 24 * 60 * 60)

    def test_cache_root_lives_in_user_home(self):
        # Not in CWD (would clutter every repo) and not in /tmp
        # (would lose between sessions). User home is the right place.
        self.assertIn(".lab-installer",
                      str(boot.CACHE_ROOT))
        self.assertEqual(boot.CACHE_ROOT.parent.parent, Path.home())


class CacheCompletenessTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._orig_root = boot.CACHE_ROOT
        boot.CACHE_ROOT = self.tmpdir

    def tearDown(self):
        boot.CACHE_ROOT = self._orig_root
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cache_complete_false_when_empty(self):
        self.assertFalse(boot._cache_complete())

    def test_cache_complete_true_when_all_required_files_present(self):
        for rel in boot.PROTOCOL_FILES:
            p = boot._local_path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# stub\n")
        self.assertTrue(boot._cache_complete())

    def test_cache_complete_false_when_one_required_missing(self):
        for rel in boot.PROTOCOL_FILES[:-1]:  # all but last
            p = boot._local_path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# stub\n")
        self.assertFalse(boot._cache_complete())


class EnsureCacheTests(unittest.TestCase):
    """The hot path. Cache fresh -> no network. Cache stale + network ->
    refresh. No network -> use cache silently."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._orig_root = boot.CACHE_ROOT
        boot.CACHE_ROOT = self.tmpdir

    def tearDown(self):
        boot.CACHE_ROOT = self._orig_root
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed_complete_cache(self, mtime_offset=0):
        """Populate the cache with all required files. Optionally
        rewind their mtime to simulate a stale cache."""
        for rel in boot.PROTOCOL_FILES:
            f = boot._local_path(rel)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# stub\n")
            if mtime_offset:
                ts = time.time() + mtime_offset
                os.utime(f, (ts, ts))

    def test_skip_update_uses_cache_directly(self):
        # --no-update path: don't touch network even if cache is stale.
        self._seed_complete_cache(mtime_offset=-86400 * 30)  # 30 days old
        with mock.patch.object(boot, "_refresh_cache") as refresh, \
             mock.patch.object(boot, "_read_remote_version") as remote:
            ok = boot._ensure_cache(skip_update=True)
        self.assertTrue(ok)
        refresh.assert_not_called()
        remote.assert_not_called()

    def test_fresh_cache_no_network_calls(self):
        # Cache exists + is fresh -> don't even check the remote VERSION.
        self._seed_complete_cache()  # mtime = now -> fresh
        with mock.patch.object(boot, "_read_remote_version") as remote:
            ok = boot._ensure_cache(skip_update=False)
        self.assertTrue(ok)
        remote.assert_not_called()

    def test_stale_same_version_just_touches_mtime(self):
        # Cache complete + remote version matches cached -> no re-download,
        # just touch mtime so we don't re-check next launch.
        self._seed_complete_cache(mtime_offset=-86400 * 2)  # 2 days old
        (self.tmpdir / "VERSION").write_text("0.1.0")
        with mock.patch.object(boot, "_read_remote_version", return_value="0.1.0"), \
             mock.patch.object(boot, "_refresh_cache") as refresh:
            ok = boot._ensure_cache(skip_update=False)
        self.assertTrue(ok)
        refresh.assert_not_called()

    def test_stale_version_triggers_refresh(self):
        self._seed_complete_cache(mtime_offset=-86400 * 2)
        (self.tmpdir / "VERSION").write_text("0.1.0")
        with mock.patch.object(boot, "_read_remote_version", return_value="0.2.0"), \
             mock.patch.object(boot, "_refresh_cache", return_value=True) as refresh:
            ok = boot._ensure_cache(skip_update=False)
        self.assertTrue(ok)
        refresh.assert_called_once()

    def test_no_network_keeps_cache_usable(self):
        # Cache stale + remote unreachable -> fall back to cached copy
        # without erroring. User can still install last-known-good apps.
        self._seed_complete_cache(mtime_offset=-86400 * 2)
        with mock.patch.object(boot, "_read_remote_version", return_value=None), \
             mock.patch.object(boot, "_refresh_cache", return_value=False):
            ok = boot._ensure_cache(skip_update=False)
        self.assertTrue(ok)  # still usable from cache

    def test_empty_cache_and_no_network_is_unusable(self):
        # First-ever run + no network -> can't bootstrap. This is the
        # only path where _ensure_cache returns False.
        with mock.patch.object(boot, "_read_remote_version", return_value=None), \
             mock.patch.object(boot, "_refresh_cache", return_value=False):
            ok = boot._ensure_cache(skip_update=False)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
