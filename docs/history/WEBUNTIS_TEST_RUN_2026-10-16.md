# Historical WebUntis test runs: 16 October 2026

This is an archived development log, not the current setup guide. Counts and
paths below describe the environment at that date. WebUntis was merged in
PR #26 and released in v0.14.9 on 11 November 2026. The old `/local` card-copy
mechanism mentioned at the end was replaced by integration static paths in
v0.14.3.

For current commands see [the test environment guide](../WEBUNTIS_TEST_ENVIRONMENT.md).

## Verified run

16 October 2026, Linux ARM64 / Debian 13, Docker 29.9.1, Compose 5.6.0:

- Source baseline: `d233286327eb7e4d1cb0528f5484d9be98f1b6ca` on
  `feature/17-webuntis-parser`; the environment and compatibility fixes are
  committed on that same draft PR. Local `AGENTS.md`, `CLAUDE.md` and editor
  settings are not part of the PR.
- Existing deployment directory reused:
  `~/ha-webuntis-test-20261016-102747`; original attempt files preserved in
  `previous-attempt/`, original root logs retained. New logs live in `logs/`.
- Compose project: `ha-webuntis-test-20261016-102747`. The directory's
  `compose.yaml` includes the checkout's development Compose file, and its
  `.env` supplies the dedicated configuration path and bind address.
  Set `HA_TEST_PROJECT` to that project name when using `run.sh` on Mireia.
- Runtime config check exited 0. From Mireia, the configured Tailscale URL
  on port 8124 returned frontend 200, unauthenticated API 401 and onboarding
  200. Fresh onboarding has no account or production connections.
- Runtime container was running with zero restarts and the pinned digest.
  The custom integration was discovered at startup, but no portal or
  WebUntis configuration entry was created.
- First complete test run: 49 passed, 2 failed. Both failures were test
  compatibility issues with HA 2026.10: obsolete `voluptuous_serialize` and
  deprecated `DeviceEntry.config_entries` in assertions. Tests now use HA's
  probatio serializer and single-entry device attribute when available,
  retaining the earlier APIs for older supported HA test environments.
  Targeted rerun: both passed.
- Final complete rerun: **51 passed in 15.76 seconds**, including all six
  WebUntis tests (five existing cases plus the new synthetic fixture batch).
  This result applies to the pinned HA 2026.10.1 test environment.

The above 51-test run is the historical environment baseline before calendar
assignment was implemented. `tests/test_webuntis_integration.py` now additionally
exercises optional configuration, the real HA calendar service, per-child
assignment, combined events, updates, deletions, source failures and removal of
the mapping. Live WebUntis credentials have not been used. Production was not
accessed, and no PR was merged by this work.

Follow-up on 16 October: the full extended suite passed **59 tests**. In the
running container, the new options flow was exercised through the browser with
the synthetic Local Calendar. The child substitution sensor changed from five
portal entries to eight combined entries (one cancellation, one teacher/room
change and one room-only change added). The dashboard showed all three new
events. Removing the mapping returned the count to five; restoring it returned
to eight. Diagnostics remained empty. The demo source remains assigned for
further review. No live WebUntis integration/account has been tested yet.

The test profile also needs `config/www` before startup for persistent automatic
Lovelace resource registration. It was initially missing in this minimal profile;
creating it and restarting the test container enables the normal `/local` card
resource instead of relying on the frontend fallback module.
