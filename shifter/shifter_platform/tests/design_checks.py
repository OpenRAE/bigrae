"""Native design validation adapters; no application credentials are required."""

from __future__ import annotations

import ast
import configparser
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parents[1]
REPOSITORY = PLATFORM.parents[1]


class Observation:
    """Distinguish executed assertions from collection and fixture failures."""

    def __init__(self) -> None:
        self.matches = 0
        self.status = "missing"
        self.message = "No unique executed acceptance case"

    def pytest_collection_finish(self, session) -> None:
        self.matches = len(session.items)

    def pytest_runtest_logreport(self, report) -> None:
        if report.failed or report.skipped or report.when == "call":
            self.status = "broken" if report.failed and report.when != "call" else report.outcome
            self.message = str(report.longrepr) if report.failed else ""

    def pytest_collectreport(self, report) -> None:
        if report.failed:
            self.status, self.message = "broken", "Acceptance test collection failed"


def acceptance(request: dict[str, str]) -> dict[str, object]:
    """Run precisely one repository test and return its bounded observation."""
    path = REPOSITORY / request["test_file"]
    if path.is_symlink() or not path.resolve().is_relative_to(PLATFORM / "tests") or not path.is_file():
        raise ValueError("Acceptance test must be a regular platform test file")
    name = request["test_name"]
    if not name or "::" in name or any(ord(char) < 32 for char in name):
        raise ValueError("An exact test name is required")
    observer = Observation()
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        code = pytest.main(
            [str(path) + "::" + name, "-o", "addopts=", "-p", "no:cacheprovider", "-q"], plugins=[observer]
        )
    if code not in (0, 1) and observer.status != "broken":
        observer.status, observer.message = "broken", "Acceptance runner failed"
    return {
        "test_name": name,
        "status": observer.status,
        "matches": observer.matches,
        "message": observer.message[-6000:],
    }


def wiring() -> dict[str, list[str]]:
    """Generate the application import view from code using the existing package list."""
    config = configparser.ConfigParser()
    config.read(REPOSITORY / ".importlinter")
    packages = config["importlinter"]["root_packages"].split()
    edges: dict[str, list[str]] = {}
    for package in packages:
        for path in sorted((PLATFORM / package).rglob("*.py")):
            if "migrations" in path.parts:
                continue
            module = ".".join(path.relative_to(PLATFORM).with_suffix("").parts).removesuffix(".__init__")
            imports = set()
            for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    parent = module if path.name == "__init__.py" else module.rpartition(".")[0]
                    prefix = ".".join(parent.split(".")[: len(parent.split(".")) - node.level + 1])
                    imports.add(".".join(filter(None, [prefix if node.level else "", node.module])))
            edges[module] = sorted(value for value in imports if value.split(".")[0] in packages)
    return edges


if __name__ == "__main__":
    if sys.argv[1:] == ["wiring"]:
        sys.stdout.write(json.dumps(wiring(), sort_keys=True) + "\n")
    elif sys.argv[1:] == ["acceptance"]:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError("Acceptance request exceeds its bound")
        sys.stdout.write(json.dumps(acceptance(json.loads(raw))) + "\n")
    else:
        raise SystemExit("Choose wiring or acceptance")
