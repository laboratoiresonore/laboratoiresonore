"""Pin the pure-function helpers + headless contract of the installer
GUI: deterministic accent hashing, summary truncation, footer count
text, hero fallback, and ``launch()`` returning False (rather than
crashing) when the Tk root can't be built."""

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from installer.src import gui


class HelperPurityTests(unittest.TestCase):
    """The helpers below must be safe to call without a Tk root --
    they're the only parts pinned by automated tests."""

    def test_truncate_summary_short_text_unchanged(self):
        text = "Short summary."
        self.assertEqual(gui.truncate_summary(text), text)

    def test_truncate_summary_three_lines_unchanged(self):
        # Pick a body small enough to wrap inside 3×20-char lines.
        # 9 four-letter words = 9*4 + 8 spaces = 44 chars -> 3 lines.
        text = " ".join(["word"] * 9)
        result = gui.truncate_summary(text, max_lines=3, line_width=20)
        self.assertLessEqual(len(result.split("\n")), 3)
        self.assertFalse(result.endswith("..."))

    def test_truncate_summary_long_text_ends_with_ellipsis(self):
        text = " ".join(["word"] * 200)
        result = gui.truncate_summary(text, max_lines=3, line_width=20)
        self.assertEqual(len(result.split("\n")), 3)
        self.assertTrue(result.endswith("..."))

    def test_truncate_summary_empty_string(self):
        self.assertEqual(gui.truncate_summary(""), "")


class AccentColorTests(unittest.TestCase):

    def test_explicit_accent_color_used_when_well_formed(self):
        app = {"id": "x", "accent_color": "#abcdef"}
        self.assertEqual(gui.accent_color_for(app), "#abcdef")

    def test_malformed_accent_color_falls_back_to_hash(self):
        app = {"id": "spellcaster", "accent_color": "purple"}
        result = gui.accent_color_for(app)
        # Hashed pick -- 7 chars, leading '#', valid hex.
        self.assertEqual(len(result), 7)
        self.assertTrue(result.startswith("#"))
        int(result[1:], 16)  # raises if not valid hex

    def test_hashed_accent_is_deterministic(self):
        app = {"id": "voodoomancer"}
        self.assertEqual(gui.accent_color_for(app), gui.accent_color_for(app))

    def test_distinct_ids_get_distinct_colours(self):
        # Not strictly guaranteed by hashing but with sha256 over
        # short strings the collision probability is astronomically
        # tiny -- any collision here = bug, not bad luck.
        a = gui.accent_color_for({"id": "beatweaver"})
        b = gui.accent_color_for({"id": "spellcaster"})
        self.assertNotEqual(a, b)


class HeroLoaderTests(unittest.TestCase):

    def test_missing_hero_returns_fallback_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = {"id": "nonexistent-app", "name": "Phantom"}
            result, source = gui.load_hero(app, assets_root=Path(tmp))
            self.assertEqual(source, "fallback")
            self.assertIsInstance(result, dict)
            self.assertEqual(result["letter"], "P")
            self.assertEqual(result["width"], gui.HERO_W)
            self.assertEqual(result["height"], gui.HERO_H)

    def test_fallback_letter_uses_id_when_name_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = {"id": "zeta"}
            result, source = gui.load_hero(app, assets_root=Path(tmp))
            self.assertEqual(source, "fallback")
            self.assertEqual(result["letter"], "Z")


class FooterCountTests(unittest.TestCase):

    def test_count_text_simple(self):
        apps = [{"id": "beatweaver"}, {"id": "spellcaster"}]
        self.assertEqual(gui.footer_count_text(apps), "(2 apps)")

    def test_count_text_zero(self):
        self.assertEqual(gui.footer_count_text([]), "(0 apps)")


class LaunchFailureTests(unittest.TestCase):
    """``launch()`` must never raise out -- environments without a
    display / without tkinter must surface as a False return value
    so the caller can drop back to CLI mode."""

    def test_returns_false_when_root_construction_raises(self):
        with mock.patch.object(gui, "_make_root",
                               side_effect=RuntimeError("no display")):
            self.assertFalse(gui.launch(visible_apps_fn=lambda: []))

    def test_returns_false_on_tk_import_error(self):
        # Simulate a stripped-down Python where even tkinter itself
        # fails to import. ``_make_root`` does the import inside the
        # function for the non-customtkinter path, so patching it to
        # raise ImportError covers that case too.
        with mock.patch.object(gui, "_make_root",
                               side_effect=ImportError("no tkinter")):
            self.assertFalse(gui.launch())


class ModuleImportTests(unittest.TestCase):
    """The module loads cleanly even when the optional GUI deps are
    absent on the host. We simulate this by stubbing the relevant
    entries in ``sys.modules`` before re-importing."""

    def test_reimport_without_customtkinter_or_pil_succeeds(self):
        saved = {
            name: sys.modules.get(name)
            for name in ("customtkinter", "PIL", "PIL.Image", "PIL.ImageTk",
                         "installer.src.gui")
        }
        try:
            # Block fresh imports of the optional deps.
            for name in ("customtkinter", "PIL", "PIL.Image", "PIL.ImageTk"):
                sys.modules[name] = None  # type: ignore[assignment]
            sys.modules.pop("installer.src.gui", None)
            reloaded = importlib.import_module("installer.src.gui")
            self.assertFalse(reloaded._HAS_CTK)
            self.assertFalse(reloaded._HAS_PIL)
            # Pure helpers still work without the optional deps.
            self.assertEqual(reloaded.footer_count_text([]), "(0 apps)")
            self.assertTrue(
                reloaded.accent_color_for({"id": "beatweaver"}).startswith("#")
            )
        finally:
            for name, mod in saved.items():
                if mod is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = mod
            # Restore the canonical, fully-featured module for any other
            # tests that run after this one in the same process.
            importlib.import_module("installer.src.gui")


if __name__ == "__main__":
    unittest.main()
