"""Pin the public manifest contract."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from installer.src import manifest


class PublicManifestTests(unittest.TestCase):

    def test_three_public_apps(self):
        ids = [a["id"] for a in manifest.PUBLIC_MANIFEST["apps"]]
        self.assertIn("beatweaver", ids)
        self.assertIn("spellcaster", ids)
        self.assertIn("comfyui-spellcaster", ids)

    def test_every_app_has_required_fields(self):
        for app in manifest.PUBLIC_MANIFEST["apps"]:
            for k in ("id", "name", "summary", "repo", "installer"):
                self.assertIn(k, app, f"app {app.get('id')!r} missing {k!r}")
            self.assertIn("kind", app["installer"])

    def test_visible_apps_returns_public_lineup(self):
        apps = manifest.visible_apps()
        ids = {a["id"] for a in apps}
        self.assertEqual(ids,
                          {"beatweaver", "spellcaster", "comfyui-spellcaster"})


if __name__ == "__main__":
    unittest.main()
