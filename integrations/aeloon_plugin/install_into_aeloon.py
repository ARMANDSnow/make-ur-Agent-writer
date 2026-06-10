#!/usr/bin/env python3
"""Install (link) this plugin into a local Aeloon-Pro (iter 049).

Aeloon's loader imports ``manifest.entry`` with plain ``importlib`` and never
adds the plugin dir to ``sys.path`` (verified against aeloon/plugins/_sdk/
loader.py + manager.py). So two things are needed:

  1. a ``.pth`` in Aeloon's venv site-packages pointing at THIS repo root, so
     ``import integrations.aeloon_plugin.plugin`` resolves inside Aeloon;
  2. this package's ``aeloon.plugin.json`` discoverable under
     ``<aeloon-home>/plugins/<name>/`` — we symlink the package dir there.

Usage::

    python -m integrations.aeloon_plugin.install_into_aeloon \
        --venv /path/to/Aeloon-Pro/.venv [--aeloon-home ~/.aeloon] \
        [--name novel_continuer]

    # remove everything this wrote:
    python -m integrations.aeloon_plugin.install_into_aeloon --venv ... --uninstall

``--site-packages`` may be given directly instead of ``--venv``. This script
only ever creates/removes one ``.pth`` file and one symlink; it never touches
Aeloon's own code.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_DIR = Path(__file__).resolve().parent
PTH_NAME = "novel_continuer_repo.pth"


def _derive_site_packages(venv: Path) -> Path | None:
    matches = sorted((venv / "lib").glob("python*/site-packages"))
    return matches[0] if matches else None


def _resolve_site(args: argparse.Namespace) -> Path | None:
    if args.site_packages:
        return Path(args.site_packages).expanduser()
    if args.venv:
        return _derive_site_packages(Path(args.venv).expanduser())
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--venv", help="Aeloon venv root (…/Aeloon-Pro/.venv)")
    ap.add_argument("--site-packages", help="explicit site-packages dir (overrides --venv)")
    ap.add_argument("--aeloon-home", default=os.path.expanduser("~/.aeloon"))
    ap.add_argument("--name", default="novel_continuer", help="plugin dir name under plugins/")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args(argv)

    plugins_dir = Path(args.aeloon_home).expanduser() / "plugins"
    link = plugins_dir / args.name
    site = _resolve_site(args)
    pth = (site / PTH_NAME) if site else None

    if args.uninstall:
        if link.is_symlink():
            link.unlink()
            print(f"removed manifest link {link}")
        if pth and pth.exists():
            pth.unlink()
            print(f"removed {pth}")
        print("done. restart Aeloon to drop the plugin.")
        return 0

    if site is None:
        print("ERROR: pass --venv (…/Aeloon-Pro/.venv) or --site-packages.", file=sys.stderr)
        return 2
    if not site.is_dir():
        print(f"ERROR: site-packages not found: {site}", file=sys.stderr)
        return 2

    plugins_dir.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        if not link.is_symlink():
            print(f"ERROR: {link} exists and is not a symlink; remove it first.", file=sys.stderr)
            return 2
        link.unlink()
    link.symlink_to(PKG_DIR, target_is_directory=True)
    print(f"linked  {link} -> {PKG_DIR}")

    pth.write_text(str(REPO_ROOT) + "\n", encoding="utf-8")
    print(f"wrote   {pth} -> {REPO_ROOT}")

    print("\nNext:")
    print("  1) start the continuer:   python main.py web --port 8765")
    print("  2) restart Aeloon (or reload plugins), then in chat:  /novel help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
