#!/usr/bin/env python3
"""Maintainer-only: generate hero card images for each app in the public
manifest by submitting a workflow to a local Spellcaster ComfyUI instance.

Workflow:
    # 1. Make sure Spellcaster's ComfyUI is running and reachable. The
    #    default local ComfyUI endpoint is http://127.0.0.1:8190.

    # 2. Review the per-app prompts before kicking off a long run:
    python tools/generate_hero_assets.py --list

    # 3. Generate everything. By default, apps that already have a hero
    #    PNG are skipped (idempotent). Pass --force to overwrite, or
    #    --app <id> to regenerate just one:
    python tools/generate_hero_assets.py \\
        --comfy-url http://127.0.0.1:8190 \\
        --checkpoint dreamshaperXL_v21TurboDPMSDE.safetensors \\
        --output installer/src/assets/heroes/

The tool talks to ComfyUI's HTTP API directly (POST /prompt, GET /history,
GET /view) - no extra dependencies. Per-image timeout is 5 minutes;
checkpoint-missing or other workflow errors are reported and the run
continues to the next app rather than aborting the batch.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


# Per-app hero prompts. Aesthetic choices -- easy to tweak in-place.
APP_PROMPTS: dict[str, str] = {
    "beatweaver": (
        "vibrant DJ console, neon glow, dark club atmosphere, "
        "vinyl turntables and EQ knobs, cinematic depth of field"
    ),
    "spellcaster": (
        "wizard's grimoire glowing with arcane ornaments, "
        "GIMP brush stroke aesthetic, purple-violet magical light"
    ),
    "comfyui-spellcaster": (
        "node graph editor floating in liminal space, "
        "cables of light connecting glowing crystal nodes, "
        "technical diagram beauty"
    ),
}

DEFAULT_COMFY_URL = "http://127.0.0.1:8190"
DEFAULT_CHECKPOINT = "dreamshaperXL_v21TurboDPMSDE.safetensors"
DEFAULT_OUTPUT_DIR = Path("installer/src/assets/heroes")
DEFAULT_SEED = 42
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 768
DEFAULT_STEPS = 28
DEFAULT_CFG = 6.5
DEFAULT_SAMPLER = "dpmpp_2m"
DEFAULT_SCHEDULER = "karras"
DEFAULT_NEGATIVE = (
    "low quality, blurry, watermark, signature, text, jpeg artifacts, "
    "deformed, ugly, cropped, malformed"
)
POLL_INTERVAL_SECONDS = 1.5
DEFAULT_TIMEOUT_SECONDS = 5 * 60


def build_workflow(
    *,
    prompt: str,
    checkpoint: str,
    seed: int,
    negative: str = DEFAULT_NEGATIVE,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    steps: int = DEFAULT_STEPS,
    cfg: float = DEFAULT_CFG,
    sampler: str = DEFAULT_SAMPLER,
    scheduler: str = DEFAULT_SCHEDULER,
    filename_prefix: str = "lab_hero",
) -> dict:
    """Build a minimal SDXL/Flux-compatible ComfyUI workflow graph.

    Nodes (string keys, since ComfyUI accepts either): CheckpointLoaderSimple
    -> CLIPTextEncode (positive + negative) -> EmptyLatentImage -> KSampler
    -> VAEDecode -> SaveImage. Returns the dict shape ComfyUI's /prompt
    endpoint expects: {"prompt": <graph>}.
    """
    graph = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1,
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt,
                "clip": ["4", 1],
            },
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": negative,
                "clip": ["4", 1],
            },
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2],
            },
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": filename_prefix,
                "images": ["8", 0],
            },
        },
    }
    return {"prompt": graph}


def hero_path(output_dir: Path, app_id: str) -> Path:
    """Resolve where the hero PNG for a given app id should live."""
    return Path(output_dir) / f"{app_id}.png"


def _http_post_json(url: str, payload: dict, *, timeout: float = 30.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_json(url: str, *, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_bytes(url: str, *, timeout: float = 60.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def submit_workflow(comfy_url: str, workflow: dict) -> str:
    """POST a workflow to /prompt. Returns the prompt_id on success.
    Raises urllib.error.HTTPError on rejected workflows (caller decides
    whether to log + continue or abort)."""
    url = comfy_url.rstrip("/") + "/prompt"
    response = _http_post_json(url, workflow)
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(
            f"ComfyUI accepted the request but returned no prompt_id: {response!r}"
        )
    return prompt_id


def poll_for_completion(
    comfy_url: str,
    prompt_id: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    sleep=time.sleep,
    now=time.monotonic,
) -> Optional[dict]:
    """Poll /history/{prompt_id} until the workflow finishes. Returns the
    first output image descriptor ({"filename","subfolder","type"}) on
    success, or None if the job errored, didn't produce an image, or the
    timeout elapsed."""
    url = comfy_url.rstrip("/") + f"/history/{prompt_id}"
    deadline = now() + timeout_seconds
    while now() < deadline:
        try:
            history = _http_get_json(url)
        except urllib.error.URLError:
            sleep(poll_interval)
            continue

        entry = history.get(prompt_id) if isinstance(history, dict) else None
        if not entry:
            sleep(poll_interval)
            continue

        status = entry.get("status", {}) if isinstance(entry, dict) else {}
        status_str = status.get("status_str") if isinstance(status, dict) else None
        if status_str == "error":
            return None

        outputs = entry.get("outputs", {}) if isinstance(entry, dict) else {}
        for node_output in outputs.values():
            images = node_output.get("images") if isinstance(node_output, dict) else None
            if images:
                first = images[0]
                return {
                    "filename": first.get("filename"),
                    "subfolder": first.get("subfolder", ""),
                    "type": first.get("type", "output"),
                }

        completed = status.get("completed") if isinstance(status, dict) else False
        if completed:
            return None

        sleep(poll_interval)
    return None


def fetch_image(comfy_url: str, descriptor: dict) -> bytes:
    """Download bytes for the image descriptor returned by poll_for_completion."""
    qs = urllib.parse.urlencode({
        "filename": descriptor["filename"],
        "subfolder": descriptor.get("subfolder", "") or "",
        "type": descriptor.get("type", "output"),
    })
    url = comfy_url.rstrip("/") + "/view?" + qs
    return _http_get_bytes(url)


def _check_reachable(comfy_url: str) -> bool:
    """Best-effort liveness check before we start the batch. /system_stats
    is a cheap GET that ComfyUI exposes."""
    url = comfy_url.rstrip("/") + "/system_stats"
    try:
        with urllib.request.urlopen(url, timeout=5.0):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _format_size(n_bytes: int) -> str:
    mb = n_bytes / (1024 * 1024)
    if mb >= 1.0:
        return f"{mb:.1f} MB"
    kb = n_bytes / 1024
    return f"{kb:.0f} KB"


def generate_one(
    *,
    app_id: str,
    prompt: str,
    output_path: Path,
    comfy_url: str,
    checkpoint: str,
    seed: int,
    index: int,
    total: int,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Run the full submit -> poll -> download flow for one app. Returns
    True on success (file written), False on any recoverable failure
    (workflow rejected, polling timeout, image fetch error)."""
    label = f"[{index}/{total}] {app_id}"
    print(f"{label} - submitting...", flush=True)

    workflow = build_workflow(
        prompt=prompt, checkpoint=checkpoint, seed=seed,
        filename_prefix=f"lab_hero_{app_id}",
    )

    try:
        prompt_id = submit_workflow(comfy_url, workflow)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"{label} - REJECTED ({e.code}): {body or e.reason}", file=sys.stderr)
        return False
    except (urllib.error.URLError, RuntimeError) as e:
        print(f"{label} - submit failed: {e}", file=sys.stderr)
        return False

    print(f"{label} - generating (prompt_id={prompt_id})...", flush=True)
    descriptor = poll_for_completion(
        comfy_url, prompt_id, timeout_seconds=timeout_seconds,
    )
    if descriptor is None:
        print(f"{label} - timed out or errored, skipping", file=sys.stderr)
        return False

    try:
        data = fetch_image(comfy_url, descriptor)
    except (urllib.error.URLError, OSError) as e:
        print(f"{label} - download failed: {e}", file=sys.stderr)
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    print(f"{label} - saved ({_format_size(len(data))})", flush=True)
    return True


def run(
    *,
    comfy_url: str,
    checkpoint: str,
    output_dir: Path,
    only_app: Optional[str] = None,
    force: bool = False,
    seed: int = DEFAULT_SEED,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    """Execute the full batch. Returns a process exit code:
    0 = at least attempted everything, all done or skipped cleanly
    2 = ComfyUI unreachable
    3 = bad --app argument (unknown id)"""
    if only_app is not None and only_app not in APP_PROMPTS:
        known = ", ".join(sorted(APP_PROMPTS))
        print(f"ERROR: unknown app id {only_app!r}. Known: {known}",
              file=sys.stderr)
        return 3

    if not _check_reachable(comfy_url):
        print(f"ERROR: ComfyUI not reachable at {comfy_url}", file=sys.stderr)
        print("       Is Spellcaster running? Try `curl {url}/system_stats`."
              .format(url=comfy_url.rstrip("/")), file=sys.stderr)
        return 2

    apps = [only_app] if only_app else list(APP_PROMPTS.keys())
    total = len(apps)
    failures = 0
    skipped = 0
    succeeded = 0

    for i, app_id in enumerate(apps, start=1):
        out = hero_path(output_dir, app_id)
        if out.exists() and not force:
            print(f"[{i}/{total}] {app_id} - already exists, skipping "
                  f"(pass --force to regenerate)", flush=True)
            skipped += 1
            continue

        ok = generate_one(
            app_id=app_id,
            prompt=APP_PROMPTS[app_id],
            output_path=out,
            comfy_url=comfy_url,
            checkpoint=checkpoint,
            seed=seed,
            index=i,
            total=total,
            timeout_seconds=timeout_seconds,
        )
        if ok:
            succeeded += 1
        else:
            failures += 1

    print(f"\nDone. {succeeded} generated, {skipped} skipped, {failures} failed.")
    return 0


def _print_listing() -> int:
    print("App -> hero prompt mapping:\n")
    for app_id, prompt in APP_PROMPTS.items():
        print(f"  {app_id}")
        print(f"    {prompt}\n")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--comfy-url", default=DEFAULT_COMFY_URL,
                   help=f"ComfyUI base URL (default: {DEFAULT_COMFY_URL})")
    p.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT,
                   help=f"checkpoint filename on the ComfyUI host "
                        f"(default: {DEFAULT_CHECKPOINT})")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR,
                   help="directory to write <app-id>.png into "
                        "(default: installer/src/assets/heroes/)")
    p.add_argument("--app", default=None,
                   help="generate only this app id (default: all three)")
    p.add_argument("--list", action="store_true",
                   help="print app -> prompt mapping and exit")
    p.add_argument("--force", action="store_true",
                   help="regenerate even if the output PNG already exists")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED,
                   help=f"sampler seed (default: {DEFAULT_SEED})")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                   help=f"per-image polling timeout in seconds "
                        f"(default: {DEFAULT_TIMEOUT_SECONDS:.0f})")
    args = p.parse_args(argv)

    if args.list:
        return _print_listing()

    return run(
        comfy_url=args.comfy_url,
        checkpoint=args.checkpoint,
        output_dir=args.output,
        only_app=args.app,
        force=args.force,
        seed=args.seed,
        timeout_seconds=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
