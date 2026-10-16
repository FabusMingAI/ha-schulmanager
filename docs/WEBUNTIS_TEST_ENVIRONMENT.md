# Isolated Home Assistant / WebUntis test environment (#17)

This environment is for development of [draft PR #26](https://github.com/FabusMingAI/ha-schulmanager/pull/26).
It does not use production configuration, credentials, school data, host networking,
privileged containers, USB devices or the Docker socket. Do not merge the draft
as part of setting up or running these tests.

## Scope

`webuntis.py` currently parses structured descriptions from calendar events.
It is **not connected to configuration, the refresh lifecycle or child events**.
A passing parser test or a running HA container does not establish WebUntis
end-to-end functionality. The fixtures are synthetic and contain no real pupils,
teachers or account details.

## Versions and isolation

- Runtime image: Home Assistant 2026.10.1, pinned by digest in
  `dev/ha-test/env.example` (Linux ARM64 was exercised on Mireia).
- Test plugin: `pytest-homeassistant-custom-component==0.13.372`, matching
  HA 2026.10.1 / Python 3.14. The existing Python 3.13 CI environment is separate.
- The test image installs the full HA pytest plugin and manifest requirements.
  Existing runtime packages are constrained to the versions already in the image.
  The test-only `pytest-codspeed` dependency requires a newer `rich` than the
  container includes; only `rich` is exempted, inside a separate test venv
  with access to the base packages. The base Python installation stays intact.
  Pip reports that this test-only `rich` is incompatible with preinstalled
  `surepy` (Sure Petcare). That unrelated integration is outside this test
  suite; this is not a globally dependency-clean image for all HA integrations.
  A conflicting dependency fails the build instead of silently replacing HA's
  `aiohttp` or other dependencies. No `PYTHONPATH=/tmp/testdeps` overlay is used.
- The test service has **no network**, mounts the checkout read-only and writes
  temporary test state under `/tmp` inside its disposable container. It does not
  mount the persistent HA configuration.
- The runtime has a dedicated persistent configuration mount and a bridge network.
  Bind to loopback by default; for remote use choose the development machine's
  Tailscale address. Do not bind to the production host or forward its ports.
- Docker JSON logs rotate at 10 MB, three files. Keep command logs in the test
  directory outside the checkout.

## Inspect before setup

From the development checkout, check `git status --short --branch`, the current
PR head, `docker context show`, `docker ps -a`, `docker compose ls --all`,
`ss -ltn` and disk space. Docker must use Mireia's local Unix socket, not a
remote production context. Inspect existing `~/ha-webuntis-test-*` directories
and their logs first. Reuse an existing isolated environment where possible.

On 16 October the existing attempt was reused. Preserve its original `.env`,
Compose file, configuration and logs before changing them. Its initial tests
failed collection because the HA test plugin was missing, and pip installed
versions inconsistent with the runtime. Those failures were test preparation
failures, not evidence that the WebUntis parser worked or failed.

## Set up a dedicated configuration

Set `HA_TEST_DIR` to a dedicated directory outside the repository. For a new
environment, create `config/custom_components` and `logs` there, copy
`dev/ha-test/configuration.yaml` into `config/configuration.yaml`, and copy
`custom_components/eltern_portal_schulmanager` into
`config/custom_components/eltern_portal_schulmanager`. Do not copy any production
`.storage`, database, `secrets.yaml` or credentials.

Copy `dev/ha-test/env.example` to `$HA_TEST_DIR/.env` and set:

- `HA_IMAGE`: the pinned digest (do not replace with a moving `stable` tag).
- `HA_TEST_CONFIG`: the absolute path of this test environment's `config` directory.
- `HA_TEST_BIND`: loopback or the development host's private Tailscale address.
- `HA_TEST_PORT`: a verified free port; 8124 was selected on Mireia.

The configuration snapshot is independent of the read-only source mount used
by pytest. After changing integration code, copy the updated integration into
the test config and restart only the test service before checking runtime code.
Record the source commit and whether uncommitted source changes were present.

## Build, test, check configuration and start

Run these from the repository root, using the chosen state directory:

```bash
export HA_TEST_DIR=/absolute/path/to/isolated-test
export HA_TEST_PROJECT=ha-webuntis-test
set -o pipefail

bash dev/ha-test/run.sh "$HA_TEST_DIR/.env" config --quiet
bash dev/ha-test/run.sh "$HA_TEST_DIR/.env" build tests \
  2>&1 | tee "$HA_TEST_DIR/logs/build.log"
bash dev/ha-test/run.sh "$HA_TEST_DIR/.env" run --rm -T tests \
  2>&1 | tee "$HA_TEST_DIR/logs/tests.log"
bash dev/ha-test/run.sh "$HA_TEST_DIR/.env" run --rm -T \
  --entrypoint python homeassistant -m homeassistant \
  --script check_config --config /config \
  2>&1 | tee "$HA_TEST_DIR/logs/check-config.log"
bash dev/ha-test/run.sh "$HA_TEST_DIR/.env" up -d homeassistant
bash dev/ha-test/run.sh "$HA_TEST_DIR/.env" logs --no-color homeassistant \
  > "$HA_TEST_DIR/logs/startup.log"
```

The wrapper does not read or execute the environment file in a shell; Docker
Compose parses it. To repeat only the parser tests, append pytest arguments:

```bash
bash dev/ha-test/run.sh "$HA_TEST_DIR/.env" run --rm -T tests \
  -q -p no:cacheprovider --basetemp=/tmp/ha-pytest tests/test_webuntis.py
```

The fixture-batch regression expects exactly one cancellation, one teacher/room
substitution and one room-only change; normal, ambiguous and invalid lessons
are ignored. Other tests exercise the existing integration with mocked portal
and AI responses, not live school accounts.

## Verify HTTP and collect results

Wait for startup, then request the exact selected test URL with a finite
timeout. Check `/` returns HTTP 200, `/api/` requires authentication (HTTP 401)
and `/api/onboarding` reports onboarding on a fresh instance. Record HTTP
status and the container's running state/restart count. Test the bound Tailscale
address from another Tailscale device to establish client-to-host reachability;
a request on Mireia alone does not prove that remote path.

```bash
python3 dev/ha-test/check_http.py http://SELECTED_TEST_ADDRESS:8124 \
  | tee "$HA_TEST_DIR/logs/http-startup.json"
```

Stop only this environment with the same wrapper and `stop homeassistant`.
Keep persistent test data; do not use `down -v` or delete the state directory
as a routine shutdown action. Logs and `.env` stay outside Git.

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

Remaining feature work in #17: configuration of a WebUntis calendar source,
refresh lifecycle integration, per-child assignment and combined events.
The fixture tests and HTTP startup checks do not cover those paths. Production
was not accessed, and no PR was merged by this work.
