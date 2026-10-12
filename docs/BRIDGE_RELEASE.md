# Releasing the bridge (0.14.1)

0.14.1 must be installed by HACS **into `custom_components/schulmanager`**, over the old 0.13
installation. HACS installs the *first* folder below `custom_components` of the release tag,
so the tag must contain only `custom_components/schulmanager` (bridge + payload).
`main` keeps the normal layout (`custom_components/eltern_portal_schulmanager`).

## Steps

```bash
git checkout main && git pull
pytest -q                                   # incl. tests/test_bridge.py
git checkout -b release/0.14.1-bridge
python scripts/build_bridge.py --release    # custom_components/ now only has schulmanager/
git add -A custom_components
git commit -m "Bridge release 0.14.1: old domain, installs and takes over Eltern Portal Manager Bavaria"
git tag v0.14.1 && git push origin release/0.14.1-bridge v0.14.1
gh release create v0.14.1 --title v0.14.1 --notes-file <(sed -n '/^## 0.14.1/,/^## 0.14.0/p' CHANGELOG.md | sed '1d;$d')
```

Never merge `release/0.14.1-bridge` into `main`.

## How long the bridge stays the latest release

Everyone who updates while 0.14.1 is the newest release gets the automatic takeover. Anyone
updating from 0.13 *after* 0.14.2 is out skips the bridge and is stuck again (old code keeps
running). So:

- keep 0.14.1 as the latest release for a while (suggestion: until the end of the next school
  holidays / a few weeks) and collect wishes for 0.14.2 as issues in the meantime;
- 0.14.2 is released from `main` again (new domain). HACS switches back to
  `custom_components/eltern_portal_schulmanager`; the leftover bridge folder is removed at
  startup by the new integration.

## Risk: Schulmanager Online

While 0.14.1 is the latest release, HACS installs it into `custom_components/schulmanager`.
Someone who already took over by hand with 0.14.0 **and** installed Schulmanager Online
afterwards would get that folder overwritten. The bridge cannot prevent this (HACS copies the
files before any of our code runs). Release notes and READMEs ask those users to skip 0.14.1.
Given that 0.14.0 was only out for a short time, this should affect hardly anyone.
