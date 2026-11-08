"""Enforce audited modules while reporting the remaining Silver coverage gap."""
import json
from pathlib import Path
import sys

report = json.loads(Path(sys.argv[1]).read_text())
required = {"config_flow.py", "diagnostics.py"}
seen = set()
failed = False
for filename, result in report["files"].items():
    summary = result["summary"]
    covered = summary["covered_lines"]
    total = summary["num_statements"]
    name = Path(filename).name
    if name in required:
        seen.add(name)
        if covered != total:
            print(f"ERROR: {name} must have 100% line coverage; missing {result['missing_lines']}")
            failed = True
    if total and covered / total <= 0.95:
        print(f"Silver still open: {filename}: {covered}/{total} lines ({100*covered/total:.2f}%)")
if missing := required - seen:
    print(f"ERROR: missing coverage for {sorted(missing)}")
    failed = True
sys.exit(1 if failed else 0)
