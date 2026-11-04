"""Exercise the native acceptance adapter against real pytest outcomes."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "name,status", [("passes", "passed"), ("fails", "failed"), ("skips", "skipped"), ("broken", "broken")]
)
def test_acceptance_observes_exact_case(name, status):
    script = Path(__file__).with_name("design_checks.py")
    # Pytest collects only test-prefixed functions by default.
    fixture = script.with_name("design_cases.py")
    request = {"test_file": str(fixture.relative_to(script.resolve().parents[3])), "test_name": "test_" + name}
    result = subprocess.run(  # noqa: S603 - fixed local interpreter and repository adapter.
        [sys.executable, str(script), "acceptance"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["status"] == status
    assert observed["matches"] == 1
