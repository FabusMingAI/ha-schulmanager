#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: bash dev/ha-test/run.sh /absolute/path/to/test.env <compose arguments...>" >&2
  exit 2
fi
env_file=$1
shift
compose_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec docker compose \
  --project-name "${HA_TEST_PROJECT:-ha-webuntis-test}" \
  --env-file "$env_file" \
  -f "$compose_dir/compose.yaml" "$@"
