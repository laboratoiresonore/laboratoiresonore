"""Pin the hero-asset generator's contract: workflow JSON shape, prompt
mapping, idempotent skip, force-overwrite, polling exit conditions, and
ComfyUI-unreachable -> exit code 2."""

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

from installer.tools import generate_hero_assets as g


def _fake_response(payload):
    """Minimal context-manager response stand-in matching urllib.request.urlopen()."""
    if isinstance(payload, (dict, list)):
        body = json.dumps(payload).encode("utf-8")
    elif isinstance(payload, bytes):
        body = payload
    else:
        body = str(payload).encode("utf-8")
    cm = mock.MagicMock()
    cm.__enter__.return_value = io.BytesIO(body)
    cm.__exit__.return_value = False
    return cm


class WorkflowJsonTests(unittest.TestCase):

    def test_build_workflow_returns_prompt_keyed_dict(self):
        wf = g.build_workflow(prompt="hello", checkpoint="m.safetensors", seed=7)
        self.assertIn("prompt", wf)
        self.assertIsInstance(wf["prompt"], dict)

    def test_workflow_has_required_node_classes(self):
        wf = g.build_workflow(prompt="hello", checkpoint="m.safetensors", seed=7)
        graph = wf["prompt"]
        class_types = {node["class_type"] for node in graph.values()}
        for required in (
            "CheckpointLoaderSimple",
            "CLIPTextEncode",
            "EmptyLatentImage",
            "KSampler",
            "VAEDecode",
            "SaveImage",
        ):
            self.assertIn(required, class_types,
                          f"workflow missing node class {required!r}")

    def test_workflow_substitutes_prompt_model_and_seed(self):
        wf = g.build_workflow(
            prompt="vibrant DJ console", checkpoint="dream.safetensors", seed=12345,
        )
        graph = wf["prompt"]
        seeds = [n["inputs"].get("seed") for n in graph.values()
                 if n["class_type"] == "KSampler"]
        self.assertEqual(seeds, [12345])
        self.assertTrue(any(n["inputs"].get("ckpt_name") == "dream.safetensors"
                            for n in graph.values()
                            if n["class_type"] == "CheckpointLoaderSimple"))
        positive_texts = [
            n["inputs"]["text"] for n in graph.values()
            if n["class_type"] == "CLIPTextEncode"
        ]
        self.assertIn("vibrant DJ console", positive_texts)
        # KSampler integer inputs are actually integers, not strings.
        ksampler = next(n for n in graph.values() if n["class_type"] == "KSampler")
        self.assertIsInstance(ksampler["inputs"]["seed"], int)
        self.assertIsInstance(ksampler["inputs"]["steps"], int)


class PromptMappingTests(unittest.TestCase):

    def test_three_known_apps_with_nonempty_prompts(self):
        self.assertEqual(set(g.APP_PROMPTS),
                         {"beatweaver", "spellcaster", "comfyui-spellcaster"})
        for app_id, prompt in g.APP_PROMPTS.items():
            self.assertIsInstance(prompt, str)
            self.assertGreater(len(prompt.strip()), 10,
                               f"prompt for {app_id} too short")


class FilenameResolutionTests(unittest.TestCase):

    def test_hero_path_uses_app_id_as_basename(self):
        out = g.hero_path(Path("/tmp/heroes"), "beatweaver")
        self.assertEqual(out.name, "beatweaver.png")
        self.assertEqual(out.parent, Path("/tmp/heroes"))

    def test_hero_path_handles_hyphenated_app_id(self):
        out = g.hero_path(Path("/x"), "comfyui-spellcaster")
        self.assertEqual(out.name, "comfyui-spellcaster.png")


class IdempotenceTests(unittest.TestCase):
    """run() must skip apps whose hero PNG already exists, unless --force."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _seed_existing_heroes(self):
        for app_id in g.APP_PROMPTS:
            (self.tmpdir / f"{app_id}.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def test_skip_when_exists_and_not_force(self):
        self._seed_existing_heroes()
        with mock.patch.object(g, "_check_reachable", return_value=True), \
             mock.patch.object(g, "submit_workflow") as mock_submit:
            rc = g.run(
                comfy_url="http://x", checkpoint="m.safetensors",
                output_dir=self.tmpdir, force=False,
            )
        self.assertEqual(rc, 0)
        mock_submit.assert_not_called()

    def test_force_regenerates_even_if_exists(self):
        self._seed_existing_heroes()
        with mock.patch.object(g, "_check_reachable", return_value=True), \
             mock.patch.object(g, "submit_workflow",
                               return_value="pid-1") as mock_submit, \
             mock.patch.object(g, "poll_for_completion",
                               return_value={"filename": "x.png",
                                             "subfolder": "", "type": "output"}), \
             mock.patch.object(g, "fetch_image", return_value=b"new-png-bytes"):
            rc = g.run(
                comfy_url="http://x", checkpoint="m.safetensors",
                output_dir=self.tmpdir, force=True,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(mock_submit.call_count, len(g.APP_PROMPTS))


class PollingTests(unittest.TestCase):

    def test_returns_descriptor_when_outputs_present(self):
        history = {
            "pid-1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "lab_hero_00001_.png",
                             "subfolder": "", "type": "output"},
                        ],
                    },
                },
            },
        }
        with mock.patch("urllib.request.urlopen",
                        side_effect=lambda *a, **kw: _fake_response(history)):
            descriptor = g.poll_for_completion(
                "http://x", "pid-1",
                timeout_seconds=5.0, poll_interval=0.0,
                sleep=lambda s: None,
            )
        self.assertEqual(descriptor["filename"], "lab_hero_00001_.png")
        self.assertEqual(descriptor["type"], "output")

    def test_returns_none_on_workflow_error(self):
        history = {
            "pid-1": {
                "status": {"status_str": "error", "completed": True},
                "outputs": {},
            },
        }
        with mock.patch("urllib.request.urlopen",
                        side_effect=lambda *a, **kw: _fake_response(history)):
            descriptor = g.poll_for_completion(
                "http://x", "pid-1",
                timeout_seconds=5.0, poll_interval=0.0,
                sleep=lambda s: None,
            )
        self.assertIsNone(descriptor)

    def test_returns_none_on_timeout(self):
        # History never contains the prompt id -> we fall through to timeout.
        clock = [0.0]

        def fake_now():
            clock[0] += 1.0
            return clock[0]

        with mock.patch("urllib.request.urlopen",
                        side_effect=lambda *a, **kw: _fake_response({})):
            descriptor = g.poll_for_completion(
                "http://x", "pid-1",
                timeout_seconds=2.5, poll_interval=0.0,
                sleep=lambda s: None,
                now=fake_now,
            )
        self.assertIsNone(descriptor)


class UnreachableTests(unittest.TestCase):
    """ComfyUI down -> exit 2."""

    def test_run_returns_2_when_unreachable(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("connection refused")):
            rc = g.run(
                comfy_url="http://127.0.0.1:9", checkpoint="m.safetensors",
                output_dir=Path(tmp), force=False,
            )
        self.assertEqual(rc, 2)

    def test_run_returns_3_for_unknown_app(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(g, "_check_reachable", return_value=True):
            rc = g.run(
                comfy_url="http://x", checkpoint="m.safetensors",
                output_dir=Path(tmp), only_app="not-a-real-app",
            )
        self.assertEqual(rc, 3)


if __name__ == "__main__":
    unittest.main()
