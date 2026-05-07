#!/usr/bin/env python3
"""LaboratoireSonore Universal Installer -- single front door for the
whole ecosystem.

Usage:
    # Default: GUI list of apps with Install buttons
    python lab_installer.py

    # Headless / scripted
    python lab_installer.py --list
    python lab_installer.py --install beatweaver --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python lab_installer.py` to work both as a script (dev) and
# as a frozen exe (release). When run as a script, the parent of the
# script's directory is the package root.
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from installer.src import manifest  # noqa: E402
else:
    from . import manifest


def cmd_list(args) -> int:
    apps = manifest.visible_apps()
    if not apps:
        print("(no apps available)")
        return 1
    print(f"{'ID':<24} {'Name':<24} Repo")
    print("-" * 80)
    for app in apps:
        print(f"{app['id']:<24} {app['name']:<24} {app.get('repo','-')}")
    return 0


def cmd_install(args) -> int:
    apps = {a["id"]: a for a in manifest.visible_apps()}
    if args.app_id not in apps:
        print(f"unknown app id: {args.app_id!r}", file=sys.stderr)
        print(f"available: {', '.join(sorted(apps))}", file=sys.stderr)
        return 2

    app = apps[args.app_id]

    # Lazy-import actions so --list works even on installs that didn't
    # ship the actions package yet (older bootstrap caches).
    if __package__ is None:
        from installer.src import actions  # type: ignore
    else:
        from . import actions

    result = actions.run_install(app, dry_run=getattr(args, "dry_run", False))
    if result.success:
        print(f"[OK] {result.app_id}: {result.message}")
        if result.artifact_path:
            print(f"     artifact: {result.artifact_path}")
        return 0
    else:
        print(f"[FAIL] {result.app_id}: {result.message}", file=sys.stderr)
        return 1


def cmd_gui(args) -> int:
    # Lazy-import the GUI so a fresh checkout missing customtkinter / PIL
    # still runs --list and --install without choking at import time.
    try:
        if __package__ is None:
            from installer.src import gui  # type: ignore
        else:
            from . import gui
    except Exception:  # noqa: BLE001
        print("GUI unavailable; use --list / --install instead",
              file=sys.stderr)
        return 1

    if gui.launch():
        return 0
    print("GUI failed to start; use --list / --install instead",
          file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lab_installer",
        description="LaboratoireSonore universal installer."
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="list visible apps").set_defaults(fn=cmd_list)

    p_install = sub.add_parser("install", help="install one app")
    p_install.add_argument("app_id")
    p_install.add_argument("--yes", action="store_true",
                            help="skip confirmation prompts")
    p_install.add_argument("--dry-run", action="store_true",
                            help="print the plan without downloading or running anything")
    p_install.set_defaults(fn=cmd_install)

    # Top-level convenience flags so common invocations don't need a
    # subcommand:
    parser.add_argument("--list", action="store_true",
                         help="shortcut for `list`")
    parser.add_argument("--install", metavar="APP_ID",
                         help="shortcut for `install APP_ID`")
    parser.add_argument("--yes", action="store_true",
                         help="(with --install) skip confirmation")

    args = parser.parse_args(argv)

    if args.list:
        return cmd_list(args)
    if args.install:
        args.app_id = args.install
        return cmd_install(args)
    if args.cmd:
        return args.fn(args)

    return cmd_gui(args)


if __name__ == "__main__":
    sys.exit(main())
