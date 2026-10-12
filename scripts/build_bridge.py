#!/usr/bin/env python3
"""Build the bridge release (old domain ``schulmanager``) – see docs/BRIDGE_RELEASE.md.

    python scripts/build_bridge.py --out /tmp/bridge   # build into a folder (tests, checks)
    python scripts/build_bridge.py --release           # restructure the repo for the bridge tag

The bridge is ``bridge/schulmanager`` plus the complete current integration as
``payload/eltern_portal_schulmanager``. HACS installs the *first* folder under
``custom_components``, so the bridge tag must contain only ``custom_components/schulmanager``.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "bridge" / "schulmanager"
NEW = ROOT / "custom_components" / "eltern_portal_schulmanager"


def _version(path: pathlib.Path) -> str:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))["version"]


def build(target: pathlib.Path) -> pathlib.Path:
    """Create ``target/schulmanager`` and return it."""
    if _version(BRIDGE) != _version(NEW):
        sys.exit(f"Version mismatch: bridge {_version(BRIDGE)} != integration {_version(NEW)}")
    out = target / "schulmanager"
    shutil.rmtree(out, ignore_errors=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(BRIDGE, out, ignore=ignore)
    shutil.copytree(NEW / "brand", out / "brand", ignore=ignore)
    shutil.copytree(NEW, out / "payload" / NEW.name, ignore=ignore)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", type=pathlib.Path, help="build into this folder")
    group.add_argument("--release", action="store_true", help="restructure custom_components for the bridge tag")
    args = parser.parse_args()
    if args.out:
        print(build(args.out))
        return
    out = build(ROOT / "custom_components")
    shutil.rmtree(NEW)
    print(f"custom_components now contains only {out.name}/ (payload {_version(out / 'payload' / NEW.name)})")
    print("Commit this on the bridge branch only – never merge it into main.")


if __name__ == "__main__":
    main()
