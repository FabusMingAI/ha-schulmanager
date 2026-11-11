# Contributing

This repository contains the HACS integration **Eltern Portal Manager Bavaria**
(domain `eltern_portal_schulmanager`). Start with the user documentation in
[English](README.md) or [German](README.de.md).

## Repository map

| Path | Purpose |
| --- | --- |
| `custom_components/eltern_portal_schulmanager/` | Integration code, translations, runtime brand assets and dashboard cards |
| `tests/` | Python tests with mocked portal/AI responses and synthetic fixtures |
| `tests/browser/` | Desktop/mobile Chromium tests for the actual dashboard cards |
| `dev/ha-test/` | Isolated, pinned Home Assistant container and test image |
| `dashboard/` | Example dashboard configuration |
| `docs/screenshots/` | Reproducible screenshot generator and fictional demo data |
| `docs/images/` | README screenshots and the original vector icon source; runtime PNG icons live under the integration's `brand/` directory |
| `bridge/` | Legacy migration test fixtures, not a second current integration |
| `scripts/` | Coverage validation and migration-fixture tooling |

## Python tests and coverage

CI uses Python 3.13. From the repository root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements_test.txt
python -m pytest -q --cov=custom_components.eltern_portal_schulmanager \
  --cov-report=term-missing --cov-report=xml --cov-report=json
python scripts/check_quality_coverage.py coverage.json
```

The coverage gate requires **more than 95% in every integration module** and
**100% in configuration flow and diagnostics**. Missing modules and excluded
runtime lines fail the gate. See [the quality assessment](docs/QUALITY_SCALE.md)
for current scope and remaining Gold criteria.

Use fictional children, teachers and schools. Tests must not access real school
accounts. Keep local environment files, credentials, logs and coverage output out
of commits. For HA 2026.10.1 / Python 3.14, follow the
[isolated container guide](docs/WEBUNTIS_TEST_ENVIRONMENT.md).

## Dashboard checks and screenshots

```bash
npm --prefix tests/browser ci
npm --prefix tests/browser test
```

Requires system Chromium; set `CHROMIUM_PATH` if it is not `/usr/bin/chromium`.
See [browser checks](tests/browser/README.md) and
[screenshot generation](docs/screenshots/README.md). Runtime cards are plain
JavaScript and have no build step. Reuse the runtime PNG icons instead of adding
copies to documentation folders.

## Changes and pull requests

- Keep changes focused. Add regression tests for behavior changes.
- Update English and German user documentation together when behavior changes.
- Record user-visible changes under `Unreleased` in `CHANGELOG.md`.
- Keep commit messages in English.
- Do not remove migration support or legacy identifiers just because the domain
  was renamed; existing installations and calendar UIDs depend on them.
- Merge only after Tests (including coverage and browser checks), HACS and
  Hassfest pass for the current commit.
- Delete completed feature branches once their commits are in `main`. Preserve
  release tags; inspect branches with commits outside `main` before deleting.

## Releases

Prepare a separate, focused release change:

1. Align the version in the integration manifest, dashboard card `VERSION` and
   bridge fixture manifest.
2. Move release notes from `Unreleased` to a dated version section in the changelog.
3. Merge after all checks pass, then run **Actions → Release → Run workflow** on
   `main`. It verifies the version and changelog, reruns tests, and publishes the
   tag and GitHub release.

Documentation-only maintenance can stay under `Unreleased` without changing the
installed version. Never republish an existing tag. The one-time v0.14.1 bridge
is historical; see [bridge migration notes](docs/BRIDGE_RELEASE.md).

## Other references

- [WebUntis compatibility and community-test limitations](docs/WEBUNTIS_COMPATIBILITY.md)
- [Archived test runs](docs/history/WEBUNTIS_TEST_RUN_2026-10-16.md)
- [Automation/editor guidance](.github/copilot-instructions.md)
