#!/usr/bin/env python3
"""Run one main.py command against a caller-owned isolated workspace root."""

from __future__ import annotations

import argparse
import os
import runpy
import stat
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_WORKSPACE = "verify"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _validated_root(raw: Path) -> Path:
    path = raw.absolute()
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("isolated workspace root must be a real directory")
    marker = path / ".dragon-raja-verify-owned"
    marker_info = marker.lstat()
    if stat.S_ISLNK(marker_info.st_mode) or not stat.S_ISREG(marker_info.st_mode):
        raise ValueError("isolated workspace root is missing its ownership marker")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error("a main.py command is required")
    if any(arg == "--book" or arg.startswith("--book=") for arg in args.command):
        parser.error("isolated commands must not override the verify workspace")
    try:
        isolated_root = _validated_root(args.workspace_root)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    # Import the single path source before main.py, then replace only its
    # workspace base for this short-lived verification process. Production
    # CLI/Web processes never see this override.
    from src import paths

    paths.WORKSPACE_DIR = isolated_root
    os.environ["WORKSPACE_NAME"] = VERIFY_WORKSPACE
    os.environ.pop("BOOK", None)
    sys.argv = [str(PROJECT_ROOT / "main.py"), "--book", VERIFY_WORKSPACE, *args.command]
    runpy.run_path(str(PROJECT_ROOT / "main.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
