"""Per-kind install actions for the universal installer.

`run_install(app_entry)` is the single entry point. It dispatches on
`app_entry["installer"]["kind"]` to one of three implementations:

- ``electron_release`` -- resolve GitHub `releases/latest`, pick the
  asset matching the platform-specific `asset_pattern`, download to
  `~/Downloads/lab-installer/<app-id>/`, and execute the platform's
  install procedure (Win NSIS, mac unzip, Linux AppImage chmod+run).
- ``run_python_installer`` -- `git clone`/`pull` into
  `~/lab-installer-source/<app-id>/` and delegate to the repo's own
  `installer/install.py --yes`.
- ``git_clone`` -- clone into a configurable target directory (default
  `target_dir` from manifest, with `{comfyui_root}` substituted from
  `$COMFYUI_ROOT` or `~/ComfyUI/ComfyUI`).

`run_install()` NEVER raises. Every failure becomes
`InstallResult(success=False, ...)` with an actionable message.

`dry_run=True` performs all resolution/planning but skips every
subprocess, download, and filesystem write -- useful for the GUI's
"preview" affordance and for tests.

Stdlib only; no third-party deps.
"""

from __future__ import annotations

import json
import os
import platform as _platform_module
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ── Public types ──────────────────────────────────────────────────────

@dataclass
class InstallResult:
    """Outcome of a single `run_install()` call.

    `artifact_path` is the meaningful filesystem location for the
    install: the downloaded installer for `electron_release`, the
    cloned source dir for `run_python_installer` / `git_clone`, or
    None when nothing was produced (dry-run or early failure).
    """
    success: bool
    message: str
    app_id: str
    artifact_path: Optional[Path]


# ── Platform detection ────────────────────────────────────────────────

def detect_platform() -> str:
    """Map runtime to one of {windows, macos-x64, macos-arm64, linux}.

    Raises ValueError on anything we don't recognize -- better to fail
    fast than guess wrong and download a binary that won't run.
    """
    sp = sys.platform
    if sp.startswith("win"):
        return "windows"
    if sp == "darwin":
        machine = _platform_module.machine().lower()
        if machine in ("arm64", "aarch64"):
            return "macos-arm64"
        if machine in ("x86_64", "amd64"):
            return "macos-x64"
        raise ValueError(f"unsupported macOS arch: {machine!r}")
    if sp.startswith("linux"):
        return "linux"
    raise ValueError(f"unsupported platform: {sp!r}")


# ── Path helpers ──────────────────────────────────────────────────────

# Where downloaded installers land. Per-app subdir keeps things tidy
# and lets us blow one app away without nuking another's cache.
def _download_dir(app_id: str) -> Path:
    return Path.home() / "Downloads" / "lab-installer" / app_id


# Where `run_python_installer` apps get checked out. Distinct from the
# downloads dir because these are working copies that we'll `git pull`
# on subsequent runs, not single-use artifacts.
def _source_dir(app_id: str) -> Path:
    return Path.home() / "lab-installer-source" / app_id


def _comfyui_root() -> Path:
    """Resolve `{comfyui_root}` for `git_clone` target_dir templates.

    Env var wins (lets users with a non-default ComfyUI install
    point at it); fallback is the canonical home-relative path the
    Spellcaster docs assume.
    """
    env = os.environ.get("COMFYUI_ROOT")
    if env:
        return Path(env)
    return Path.home() / "ComfyUI" / "ComfyUI"


def _substitute_target(target: str) -> str:
    return target.replace("{comfyui_root}", str(_comfyui_root()))


# ── GitHub releases ───────────────────────────────────────────────────

# Hardcoded so a downgrade attack via a redirect can't aim us at a
# different host. URL is constructed below; we just pin the prefix.
_GITHUB_API = "https://api.github.com"


def _fetch_latest_release(repo: str) -> dict:
    """Hit `/repos/{repo}/releases/latest` and return the JSON body.

    Raises urllib.error.URLError / json.JSONDecodeError / KeyError --
    the caller is responsible for translating those into an
    InstallResult.
    """
    url = f"{_GITHUB_API}/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "lab-installer",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def _strip_v_prefix(tag: str) -> str:
    """`v1.2.3` -> `1.2.3`. Asset patterns use the bare semver."""
    if tag.startswith("v") or tag.startswith("V"):
        return tag[1:]
    return tag


def _pick_asset(release: dict, pattern: str) -> Optional[dict]:
    """Find the release asset whose `name` matches `pattern` exactly.

    `pattern` has already had `{version}` substituted by the caller.
    """
    for asset in release.get("assets", []):
        if asset.get("name") == pattern:
            return asset
    return None


# ── electron_release ──────────────────────────────────────────────────

def _install_electron_release(
    app_entry: dict, plat: str, dry_run: bool,
) -> InstallResult:
    app_id = app_entry["id"]
    repo = app_entry["repo"]
    asset_patterns = app_entry["installer"].get("asset_pattern", {})

    raw_pattern = asset_patterns.get(plat)
    if raw_pattern is None:
        return InstallResult(
            success=False,
            message=(
                f"no asset_pattern for platform {plat!r} in "
                f"{app_id!r} manifest entry "
                f"(have: {sorted(asset_patterns)})"
            ),
            app_id=app_id,
            artifact_path=None,
        )

    try:
        release = _fetch_latest_release(repo)
    except urllib.error.URLError as e:
        return InstallResult(
            success=False,
            message=f"could not reach GitHub API for {repo!r}: {e}",
            app_id=app_id,
            artifact_path=None,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return InstallResult(
            success=False,
            message=f"GitHub API returned non-JSON for {repo!r}: {e}",
            app_id=app_id,
            artifact_path=None,
        )
    except Exception as e:  # noqa: BLE001 -- never raise from run_install
        return InstallResult(
            success=False,
            message=f"unexpected error fetching release for {repo!r}: {e}",
            app_id=app_id,
            artifact_path=None,
        )

    tag = release.get("tag_name")
    if not tag:
        return InstallResult(
            success=False,
            message=f"latest release for {repo!r} has no tag_name",
            app_id=app_id,
            artifact_path=None,
        )
    version = _strip_v_prefix(tag)

    asset_name = raw_pattern.replace("{version}", version)
    asset = _pick_asset(release, asset_name)
    if asset is None:
        names = [a.get("name", "?") for a in release.get("assets", [])]
        return InstallResult(
            success=False,
            message=(
                f"no asset named {asset_name!r} in {repo!r} {tag!r} "
                f"(found: {names})"
            ),
            app_id=app_id,
            artifact_path=None,
        )

    download_url = asset.get("browser_download_url")
    if not download_url:
        return InstallResult(
            success=False,
            message=f"asset {asset_name!r} has no browser_download_url",
            app_id=app_id,
            artifact_path=None,
        )

    target_dir = _download_dir(app_id)
    target_path = target_dir / asset_name

    if dry_run:
        return InstallResult(
            success=True,
            message=(
                f"[dry-run] would download {download_url} -> {target_path} "
                f"and run platform installer for {plat}"
            ),
            app_id=app_id,
            artifact_path=target_path,
        )

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return InstallResult(
            success=False,
            message=f"could not create download dir {target_dir}: {e}",
            app_id=app_id,
            artifact_path=None,
        )

    # Download to a sibling .part file then rename -- that way a
    # cancelled / errored download doesn't leave a half-written file
    # masquerading as a complete installer.
    partial_path = target_path.with_suffix(target_path.suffix + ".part")
    try:
        with urllib.request.urlopen(download_url, timeout=120) as resp:
            with open(partial_path, "wb") as f:
                shutil.copyfileobj(resp, f)
        partial_path.replace(target_path)
    except urllib.error.URLError as e:
        if partial_path.exists():
            try:
                partial_path.unlink()
            except OSError:
                pass
        return InstallResult(
            success=False,
            message=f"download failed for {download_url}: {e}",
            app_id=app_id,
            artifact_path=None,
        )
    except OSError as e:
        if partial_path.exists():
            try:
                partial_path.unlink()
            except OSError:
                pass
        return InstallResult(
            success=False,
            message=f"could not write to {partial_path}: {e}",
            app_id=app_id,
            artifact_path=None,
        )

    return _exec_electron_installer(app_id, target_path, plat)


def _exec_electron_installer(
    app_id: str, asset_path: Path, plat: str,
) -> InstallResult:
    try:
        if plat == "windows":
            # Don't pass /S -- different NSIS scripts handle silent
            # mode differently and a wrong flag silently no-ops the
            # install. Let the user click through the wizard.
            subprocess.run([str(asset_path)], check=True)
        elif plat in ("macos-x64", "macos-arm64"):
            subprocess.run(
                ["unzip", str(asset_path), "-d", str(asset_path.parent)],
                check=True,
            )
        elif plat == "linux":
            os.chmod(asset_path, 0o755)
            subprocess.run([str(asset_path)], check=True)
        else:
            return InstallResult(
                success=False,
                message=f"no installer exec strategy for platform {plat!r}",
                app_id=app_id,
                artifact_path=asset_path,
            )
    except subprocess.CalledProcessError as e:
        return InstallResult(
            success=False,
            message=f"installer subprocess failed: {e}",
            app_id=app_id,
            artifact_path=asset_path,
        )
    except FileNotFoundError as e:
        return InstallResult(
            success=False,
            message=f"required tool not found: {e}",
            app_id=app_id,
            artifact_path=asset_path,
        )
    except OSError as e:
        return InstallResult(
            success=False,
            message=f"OS error launching installer: {e}",
            app_id=app_id,
            artifact_path=asset_path,
        )

    return InstallResult(
        success=True,
        message=f"installed {app_id} from {asset_path.name}",
        app_id=app_id,
        artifact_path=asset_path,
    )


# ── run_python_installer ──────────────────────────────────────────────

def _git_clone_or_pull_cmd(repo_url: str, dest: Path) -> list[list[str]]:
    """Return the list of commands to bring `dest` up to date with
    `repo_url`. Either a single `git clone` (fresh) or a `git pull`
    (existing checkout)."""
    if (dest / ".git").exists():
        return [["git", "-C", str(dest), "pull", "--ff-only"]]
    return [["git", "clone", repo_url, str(dest)]]


def _github_https_url(repo: str) -> str:
    """`owner/name` -> `https://github.com/owner/name.git`. Pinned to
    HTTPS so we don't depend on a configured SSH key."""
    return f"https://github.com/{repo}.git"


def _install_run_python_installer(
    app_entry: dict, dry_run: bool,
) -> InstallResult:
    app_id = app_entry["id"]
    repo = app_entry["repo"]
    dest = _source_dir(app_id)
    repo_url = _github_https_url(repo)

    git_cmds = _git_clone_or_pull_cmd(repo_url, dest)
    py_cmd = [sys.executable, "installer/install.py", "--yes"]

    if dry_run:
        plan = "; ".join(" ".join(c) for c in git_cmds)
        return InstallResult(
            success=True,
            message=(
                f"[dry-run] would run: {plan}; then "
                f"{' '.join(py_cmd)} (cwd={dest})"
            ),
            app_id=app_id,
            artifact_path=dest,
        )

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return InstallResult(
            success=False,
            message=f"could not create source parent dir {dest.parent}: {e}",
            app_id=app_id,
            artifact_path=None,
        )

    try:
        for cmd in git_cmds:
            subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        return InstallResult(
            success=False,
            message=f"git command failed: {e}",
            app_id=app_id,
            artifact_path=None,
        )
    except FileNotFoundError:
        return InstallResult(
            success=False,
            message="git not found on PATH -- install git and retry",
            app_id=app_id,
            artifact_path=None,
        )
    except OSError as e:
        return InstallResult(
            success=False,
            message=f"OS error running git: {e}",
            app_id=app_id,
            artifact_path=None,
        )

    try:
        subprocess.run(py_cmd, cwd=str(dest), check=True)
    except subprocess.CalledProcessError as e:
        return InstallResult(
            success=False,
            message=f"app's installer (install.py) failed: {e}",
            app_id=app_id,
            artifact_path=dest,
        )
    except FileNotFoundError as e:
        return InstallResult(
            success=False,
            message=f"installer/install.py not found in {dest}: {e}",
            app_id=app_id,
            artifact_path=dest,
        )
    except OSError as e:
        return InstallResult(
            success=False,
            message=f"OS error running install.py: {e}",
            app_id=app_id,
            artifact_path=dest,
        )

    return InstallResult(
        success=True,
        message=f"installed {app_id} via its own install.py",
        app_id=app_id,
        artifact_path=dest,
    )


# ── git_clone ─────────────────────────────────────────────────────────

def _install_git_clone(
    app_entry: dict, dry_run: bool,
) -> InstallResult:
    app_id = app_entry["id"]
    repo = app_entry["repo"]
    target_template = app_entry["installer"].get("target_dir")
    if not target_template:
        return InstallResult(
            success=False,
            message=f"{app_id!r} git_clone entry has no target_dir",
            app_id=app_id,
            artifact_path=None,
        )

    target = Path(_substitute_target(target_template)).expanduser()
    repo_url = _github_https_url(repo)
    git_cmds = _git_clone_or_pull_cmd(repo_url, target)

    if dry_run:
        plan = "; ".join(" ".join(c) for c in git_cmds)
        return InstallResult(
            success=True,
            message=f"[dry-run] would run: {plan} (target={target})",
            app_id=app_id,
            artifact_path=target,
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return InstallResult(
            success=False,
            message=f"could not create target parent {target.parent}: {e}",
            app_id=app_id,
            artifact_path=None,
        )

    try:
        for cmd in git_cmds:
            subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        return InstallResult(
            success=False,
            message=f"git command failed: {e}",
            app_id=app_id,
            artifact_path=None,
        )
    except FileNotFoundError:
        return InstallResult(
            success=False,
            message="git not found on PATH -- install git and retry",
            app_id=app_id,
            artifact_path=None,
        )
    except OSError as e:
        return InstallResult(
            success=False,
            message=f"OS error running git: {e}",
            app_id=app_id,
            artifact_path=None,
        )

    return InstallResult(
        success=True,
        message=f"cloned {app_id} into {target}",
        app_id=app_id,
        artifact_path=target,
    )


# ── Dispatch ──────────────────────────────────────────────────────────

def run_install(
    app_entry: dict,
    *,
    platform: Optional[str] = None,
    dry_run: bool = False,
) -> InstallResult:
    """Install one app per its manifest entry. Never raises.

    `platform` overrides runtime detection (handy for tests + for
    cross-platform "what would happen" preview). `dry_run=True`
    skips every subprocess/download/filesystem-write -- only
    resolution + planning happens.
    """
    try:
        app_id = app_entry.get("id", "<unknown>") if isinstance(app_entry, dict) else "<unknown>"
        if not isinstance(app_entry, dict):
            return InstallResult(
                success=False,
                message="app_entry must be a dict",
                app_id=app_id,
                artifact_path=None,
            )
        installer = app_entry.get("installer")
        if not isinstance(installer, dict):
            return InstallResult(
                success=False,
                message=f"{app_id!r}: installer block missing or malformed",
                app_id=app_id,
                artifact_path=None,
            )
        kind = installer.get("kind")

        if kind == "electron_release":
            if platform is None:
                try:
                    plat = detect_platform()
                except ValueError as e:
                    return InstallResult(
                        success=False,
                        message=str(e),
                        app_id=app_id,
                        artifact_path=None,
                    )
            else:
                plat = platform
            return _install_electron_release(app_entry, plat, dry_run)

        if kind == "run_python_installer":
            return _install_run_python_installer(app_entry, dry_run)

        if kind == "git_clone":
            return _install_git_clone(app_entry, dry_run)

        return InstallResult(
            success=False,
            message=f"{app_id!r}: unknown installer kind {kind!r}",
            app_id=app_id,
            artifact_path=None,
        )
    except Exception as e:  # noqa: BLE001 -- contract: NEVER raise
        app_id = "<unknown>"
        if isinstance(app_entry, dict):
            app_id = app_entry.get("id", "<unknown>")
        return InstallResult(
            success=False,
            message=f"unexpected error in run_install: {e!r}",
            app_id=app_id,
            artifact_path=None,
        )


__all__ = ["InstallResult", "run_install", "detect_platform"]
