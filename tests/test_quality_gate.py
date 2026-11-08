"""The coverage gate must enforce each module and the strict Silver boundary."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components/eltern_portal_schulmanager"


def report():
    return {"files": {str(p.relative_to(ROOT)): {"summary": {"covered_lines": 100, "num_statements": 100}, "missing_lines": [], "excluded_lines": []} for p in SOURCE.glob("*.py")}}


@pytest.mark.parametrize("case,success", [("pass", True), ("exactly_95", False), ("flow_99", False), ("missing_module", False), ("excluded_code", False)])
def test_gate_rejects_incomplete_or_rounded_reports(tmp_path, case, success):
    data = report()
    filename = "custom_components/eltern_portal_schulmanager/manager.py"
    if case == "exactly_95":
        data["files"][filename]["summary"]["covered_lines"] = 95
    elif case == "flow_99":
        data["files"]["custom_components/eltern_portal_schulmanager/config_flow.py"]["summary"]["covered_lines"] = 99
    elif case == "missing_module":
        del data["files"][filename]
    elif case == "excluded_code":
        data["files"][filename]["excluded_lines"] = [1]
    else:
        data["files"][filename]["summary"]["covered_lines"] = 96
    path = tmp_path/"report.json"
    path.write_text(json.dumps(data))
    result = subprocess.run([sys.executable, str(ROOT/"scripts/check_quality_coverage.py"), str(path)], capture_output=True, text=True)
    assert (result.returncode == 0) is success, result.stdout


def test_local_brand_assets_match_current_custom_integration_format():
    import struct
    for name, pixels in (("icon.png", 256), ("icon@2x.png", 512), ("dark_icon.png", 256), ("dark_icon@2x.png", 512)):
        content = (SOURCE/"brand"/name).read_bytes()
        assert content[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", content[16:24]) == (pixels, pixels)
