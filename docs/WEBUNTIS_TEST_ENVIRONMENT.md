# Isolated Home Assistant / WebUntis test environment (#17)

This environment was created for development of [PR #26](https://github.com/FabusMingAI/ha-schulmanager/pull/26).
It does not use production configuration, credentials, school data, host networking,
privileged containers, USB devices or the Docker socket. The community release
remains unverified against a real WebUntis account.

## Scope

WebUntis is an optional per-child calendar source selected under **Configure →
WebUntis calendar (optional)**. Without an assignment, the integration never
queries a WebUntis calendar. Configured sources use the HA calendar service for
the next 14 days, feed the existing substitutions model and appear in child
sensors, calendar events and the dashboard. Existing portal substitutions stay
available. The fixtures are synthetic and contain no real pupils, teachers or
account details. A passing fixture test does not establish compatibility with
every live WebUntis account or integration version.

To reproduce the optional configuration in the running test instance, create a
**Local Calendar** named **WebUntis Demo** and add synthetic events whose
description is JSON in the format of `tests/fixtures/webuntis/events.json`.
Use future dates within the next 14 days. This substitutes for the upstream
WebUntis calendar provider without using school credentials. In the integration's
Configure menu choose **WebUntis calendar (optional)**, then the demo child,
then `calendar.webuntis_demo`. The integration's own calendar is deliberately
excluded to prevent a feedback loop. Clearing the selection removes the mapping.

## Versions and isolation

- Runtime image: Home Assistant 2026.10.1, pinned by digest in
  `dev/ha-test/env.example` (verified on Linux ARM64).
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

From the development checkout, inspect `git status --short --branch`,
`docker context show`, `docker ps -a`, `docker compose ls --all`, `ss -ltn`
and disk space. Use the development host's local Docker context and reuse an
existing isolated environment where possible. Preserve its configuration and
logs before changing it.

## Set up a dedicated configuration

Set `HA_TEST_DIR` to a dedicated directory outside the repository. For a new
environment, create `config/custom_components`, `config/www` and `logs` there, copy
`dev/ha-test/configuration.yaml` into `config/configuration.yaml`, and copy
`custom_components/eltern_portal_schulmanager` into
`config/custom_components/eltern_portal_schulmanager`. Do not copy any production
`.storage`, database, `secrets.yaml` or credentials.

Copy `dev/ha-test/env.example` to `$HA_TEST_DIR/.env` and set:

- `HA_IMAGE`: the pinned digest (do not replace with a moving `stable` tag).
- `HA_TEST_CONFIG`: the absolute path of this test environment's `config` directory.
- `HA_TEST_BIND`: loopback or the development host's private Tailscale address.
- `HA_TEST_PORT`: a verified free port, for example 8124.

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
a request on the development host alone does not prove that remote path.

```bash
python3 dev/ha-test/check_http.py http://SELECTED_TEST_ADDRESS:8124 \
  | tee "$HA_TEST_DIR/logs/http-startup.json"
```

Stop only this environment with the same wrapper and `stop homeassistant`.
Keep persistent test data; do not use `down -v` or delete the state directory
as a routine shutdown action. Logs and `.env` stay outside Git.

## Verification status

For v0.14.9 on 11 November 2026, all **191 tests** passed on the isolated
HA 2026.10.1 / Python 3.14 image and on GitHub CI / Python 3.13. Python line
coverage was **97.92%**, with every module above 95% and config flow,
diagnostics and the WebUntis parser at 100%. Desktop/mobile browser checks
also cover timed WebUntis changes without a portal timetable.

The suite exercises optional configuration, real HA calendar services,
per-child assignments, combined events, source failures and recovery, removal
of mappings, delayed notifications, persisted cache restart and daylight saving.
No real WebUntis account has yet been tested. See
[compatibility and limitations](WEBUNTIS_COMPATIBILITY.md) before community testing.

The [16 October development log](history/WEBUNTIS_TEST_RUN_2026-10-16.md)
is retained separately for reproducibility; it is not the current test result.
