"""Enforce >95% in every integration module, and 100% in flow/diagnostics."""
import ast
import json
from pathlib import Path
import sys

report = json.loads(Path(sys.argv[1]).read_text())
root = Path(__file__).resolve().parents[1]
source = root / "custom_components" / "eltern_portal_schulmanager"
required = {"config_flow.py", "diagnostics.py"}
expected = {p.name for p in source.glob("*.py")}
seen = set()
failed = False
for filename, result in report["files"].items():
    if Path(filename).parent.name != source.name:
        continue
    name = Path(filename).name
    seen.add(name)
    summary = result["summary"]
    covered, total = summary["covered_lines"], summary["num_statements"]
    # coverage.py excludes TYPE_CHECKING by default; imports in that block
    # are static type declarations, not runtime behaviour to test.
    typing_lines = set()
    for node in ast.walk(ast.parse((source / name).read_text())):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"
                and all(isinstance(child, (ast.Import, ast.ImportFrom)) for child in node.body)):
            typing_lines.update(range(node.lineno, node.end_lineno + 1))
    if set(result.get("excluded_lines", [])) - typing_lines:
        print(f"ERROR: {name} contains excluded runtime lines; the audit requires all integration code")
        failed = True
    if name in required and covered != total:
        print(f"ERROR: {name} needs 100% coverage; missing {result['missing_lines']}")
        failed = True
    elif total and covered * 100 <= total * 95:
        print(f"ERROR: {name} needs more than 95% coverage: {covered}/{total}; missing {result['missing_lines']}")
        failed = True
    else:
        print(f"PASS: {name}: {covered}/{total} lines")
if missing := expected - seen:
    print(f"ERROR: modules missing from coverage report: {sorted(missing)}")
    failed = True
sys.exit(1 if failed else 0)
