# Historical bridge release: v0.14.1

The bridge was published on 12 October 2026 to migrate this project's old
`schulmanager` domain to `eltern_portal_schulmanager`. Normal releases have used
the new domain again since v0.14.2. Publish new versions with the **Release**
workflow; the obsolete **Bridge release** workflow has been removed.

## Existing installations

Users still on v0.13 need the existing v0.14.1 release first, unless they already
migrated manually. Follow the upgrade instructions in
[English](../README.md#renamed-from-schulmanager) or
[German](../README.de.md#umbenannt-früher-schulmanager).
Do not republish or retag v0.14.1. Users who installed Schulmanager Online after
manually migrating must skip the bridge, as both use the old folder name.

## Retained migration support

- `bridge/schulmanager/` and `scripts/build_bridge.py` remain as fixtures for
  `tests/test_bridge.py`. They verify takeover, payload installation and cleanup.
- The bridge fixture version tracks the current integration manifest. This does
  not make it a new distributable bridge release.
- Build a test payload with `python scripts/build_bridge.py --out /tmp/bridge`.
  The script's `--release` mode is historical tooling that restructures
  `custom_components`; do not run it in a normal working checkout.
- The published tag `v0.14.1` preserves the original release layout, with only
  `custom_components/schulmanager` and the embedded payload. Never merge the
  historical `release/0.14.1-bridge` branch into `main`.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for current validation and releases.
