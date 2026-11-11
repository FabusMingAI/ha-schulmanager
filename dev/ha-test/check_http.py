"""Check an isolated HA instance without credentials or state changes."""

import argparse
import json
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Exact URL of the development instance")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    base = args.url.rstrip("/")
    deadline = time.monotonic() + args.timeout
    while True:
        try:
            with urllib.request.urlopen(base + "/", timeout=5) as response:
                assert response.status == 200
                assert "text/html" in response.headers.get("Content-Type", "")
            break
        except (urllib.error.URLError, TimeoutError):
            if time.monotonic() >= deadline:
                raise SystemExit("HA did not become reachable before the timeout")
            time.sleep(2)
    try:
        urllib.request.urlopen(base + "/api/", timeout=5)
    except urllib.error.HTTPError as error:
        assert error.code == 401, f"Expected API authentication, got {error.code}"
    else:
        raise SystemExit("The API unexpectedly allowed an unauthenticated request")
    with urllib.request.urlopen(base + "/api/onboarding", timeout=5) as response:
        onboarding_status = response.status
        onboarding = json.load(response)
    assert isinstance(onboarding, list)
    print(json.dumps({
        "url": base,
        "frontend_http": 200,
        "unauthenticated_api_http": 401,
        "onboarding_http": onboarding_status,
        "onboarding_steps": [{"step": step["step"], "done": step["done"]} for step in onboarding],
        "scope": "HTTP startup only; no WebUntis end-to-end claim",
    }, indent=2))


if __name__ == "__main__":
    main()
