"""Manifest loader."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


PUBLIC_MANIFEST = {
    "schema_version": 1,
    "apps": [
        {
            "id": "beatweaver",
            "name": "BeatWeaver",
            "summary": (
                "DJ overlay tool -- auto-detects BPM + key, lets you layer "
                "32 hand-tuned synth presets in the right key on top of "
                "any track. Bundled offline neural TTS announcer."
            ),
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
        },
        {
            "id": "spellcaster",
            "name": "Spellcaster",
            "summary": (
                "AI image generation hidden behind one menu -- GIMP / "
                "Darktable / DaVinci Resolve / chat UI integrations. "
                "9 architectures, 69 one-click tools."
            ),
            "repo": "laboratoiresonore/spellcaster",
            "installer": {
                "kind": "electron_release",
                "asset_pattern": {
                    "windows": "spellcaster-installer.exe",
                    "macos":   "spellcaster-installer-macos.zip",
                    "linux":   "spellcaster-installer",
                },
            },
        },
        {
            "id": "comfyui-spellcaster",
            "name": "ComfyUI-Spellcaster",
            "summary": (
                "Architecture-aware ComfyUI custom nodes -- auto-detect "
                "checkpoint, load matching CLIP/VAE, sample with "
                "optimal settings. Standalone version of the four "
                "nodes that drive Spellcaster."
            ),
            "repo": "laboratoiresonore/ComfyUI-Spellcaster",
            "installer": {
                "kind": "git_clone",
                "target_dir": "{comfyui_root}/custom_nodes/ComfyUI-Spellcaster",
            },
        },
    ],
}


def _bundle_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def visible_apps(*, installer_root: Optional[Path] = None) -> list[dict]:
    apps: list[dict] = list(PUBLIC_MANIFEST["apps"])

    # Optional: a key.png next to the installer can carry additional
    # manifest entries (e.g. licensed-only apps). The loader is
    # lazy-imported so a fresh checkout missing PIL still runs the
    # public path cleanly.
    try:
        if __package__ is None:
            from installer.src import stego_loader  # type: ignore
        else:
            from . import stego_loader
        extra = stego_loader.read(installer_root=installer_root)
    except Exception:  # noqa: BLE001 -- loader returns None on failure;
        extra = None    # this catches an unforeseen import-time issue

    if isinstance(extra, dict):
        for app in (extra.get("apps") or []):
            if isinstance(app, dict) and "id" in app:
                apps.append(app)

    return apps


# Stable public alias used by older tests / external callers.
def load_private_manifest(*, installer_root: Optional[Path] = None,
                          blob_path: Optional[Path] = None) -> Optional[dict]:
    """Compatibility shim. Returns the parsed extra-manifest dict from
    the optional sibling key.png, or None when not present/invalid."""
    try:
        if __package__ is None:
            from installer.src import stego_loader  # type: ignore
        else:
            from . import stego_loader
        return stego_loader.read(installer_root=installer_root)
    except Exception:  # noqa: BLE001
        return None
