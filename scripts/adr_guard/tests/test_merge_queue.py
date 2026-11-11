"""ADR-003-R9 ``dev-merge-queue`` guard.

The suite runs the check against the repository and against temporary copies
of the ``dev`` ruleset and the workflows, each with one contract break. A copy
keeps the real producer workflows, so the mutations test the real shapes.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "adr_guard.py"
SPEC = importlib.util.spec_from_file_location("adr_guard", MODULE_PATH)
ADR_GUARD = importlib.util.module_from_spec(SPEC)
sys.modules["adr_guard"] = ADR_GUARD
SPEC.loader.exec_module(ADR_GUARD)

REPO_ROOT = Path(__file__).resolve().parents[3]
RULESET_REL = "docs/adr/dev-ruleset.json"
WORKFLOW_DIR = ".github/workflows"


def _rule(ruleset: dict, rule_type: str) -> dict:
    return next(rule for rule in ruleset["rules"] if rule["type"] == rule_type)


def _drop_rule(rule_type: str) -> Callable[[dict], None]:
    def mutate(ruleset: dict) -> None:
        ruleset["rules"] = [rule for rule in ruleset["rules"] if rule["type"] != rule_type]

    return mutate


def _set_param(rule_type: str, key: str, value: object) -> Callable[[dict], None]:
    def mutate(ruleset: dict) -> None:
        _rule(ruleset, rule_type)["parameters"][key] = value

    return mutate


def _include(refs: list[str]) -> Callable[[dict], None]:
    def mutate(ruleset: dict) -> None:
        ruleset["conditions"]["ref_name"]["include"] = refs

    return mutate


def _add_context(context: str) -> Callable[[dict], None]:
    def mutate(ruleset: dict) -> None:
        _rule(ruleset, "required_status_checks")["parameters"]["required_status_checks"].append({"context": context})

    return mutate


class DevMergeQueueTest(unittest.TestCase):
    """The ruleset and the producer workflows hold the ADR-003-R9 contract."""

    def _copy_repo(self, tmp: Path) -> None:
        (tmp / "docs/adr").mkdir(parents=True)
        shutil.copy(REPO_ROOT / RULESET_REL, tmp / RULESET_REL)
        shutil.copytree(REPO_ROOT / WORKFLOW_DIR, tmp / WORKFLOW_DIR)

    def _violations(
        self,
        ruleset_mutation: Callable[[dict], None] | None = None,
        workflow_edit: tuple[str, str, str] | None = None,
    ) -> list[str]:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._copy_repo(tmp)
            if ruleset_mutation is not None:
                ruleset = json.loads((tmp / RULESET_REL).read_text(encoding="utf-8"))
                ruleset_mutation(ruleset)
                (tmp / RULESET_REL).write_text(json.dumps(ruleset), encoding="utf-8")
            if workflow_edit is not None:
                name, old, new = workflow_edit
                path = tmp / WORKFLOW_DIR / name
                text = path.read_text(encoding="utf-8")
                self.assertIn(old, text, f"fixture edit target missing from {name}")
                path.write_text(text.replace(old, new, 1), encoding="utf-8")
            return [v.message for v in ADR_GUARD.check_dev_merge_queue(tmp, None)]

    def test_repository_conforms(self) -> None:
        self.assertEqual(ADR_GUARD.check_dev_merge_queue(REPO_ROOT, None), [])
        self.assertIn("dev-merge-queue", ADR_GUARD.CHECKS)
        self.assertIn("dev-merge-queue", ADR_GUARD.CHECK_LEVELS["ci"])

    def test_ruleset_breaks_fail(self) -> None:
        cases = {
            "no merge queue": (_drop_rule("merge_queue"), "must have a merge_queue rule"),
            "single-entry groups": (
                _set_param("merge_queue", "max_entries_to_merge", 1),
                "max_entries_to_merge must be at least 2",
            ),
            "strict checks": (
                _set_param("required_status_checks", "strict_required_status_checks_policy", True),
                "must not require strict status checks",
            ),
            "main targeted": (_include(["refs/heads/dev", "refs/heads/main"]), "must include exactly refs/heads/dev"),
            "no required checks": (_drop_rule("required_status_checks"), "must have a required_status_checks rule"),
            "unknown context": (_add_context("No Such Check"), "'No Such Check' has no producer workflow"),
        }
        for label, (mutation, expected) in cases.items():
            with self.subTest(label):
                messages = self._violations(ruleset_mutation=mutation)
                self.assertTrue(any(expected in m for m in messages), messages)

    def test_non_strict_without_queue_fails(self) -> None:
        messages = self._violations(ruleset_mutation=_drop_rule("merge_queue"))
        self.assertTrue(any("only when it uses the merge queue" in m for m in messages), messages)

    def test_producer_breaks_fail(self) -> None:
        cases = {
            "title lint without merge_group": (
                ("pr-title-lint.yml", "  merge_group:\n    types: [checks_requested]\n", ""),
                "'Lint PR title' must run on merge_group",
            ),
            "codeql without merge_group": (
                ("codeql-analysis.yml", "  merge_group:\n    types: [checks_requested]\n", ""),
                "'CodeQL' must run on merge_group",
            ),
            "PR Gate filters out merge_group": (
                (
                    "deploy.yml",
                    "if: ${{ always() && (github.event_name == 'pull_request' || "
                    "github.event_name == 'merge_group') }}\n    runs-on: ubuntu-latest\n    steps:\n"
                    "      - name: Assert required PR jobs passed",
                    "if: ${{ always() && github.event_name == 'pull_request' }}\n    runs-on: ubuntu-latest\n"
                    "    steps:\n      - name: Assert required PR jobs passed",
                ),
                "'PR Gate' filters events without merge_group",
            ),
            "title lint skips dev": (
                ("pr-title-lint.yml", "    branches:\n      - dev\n      - main\n", "    branches:\n      - main\n"),
                "'Lint PR title' must run on pull_request to dev",
            ),
        }
        for label, (edit, expected) in cases.items():
            with self.subTest(label):
                messages = self._violations(workflow_edit=edit)
                self.assertTrue(any(expected in m for m in messages), messages)

    def test_relevance(self) -> None:
        self.assertEqual(ADR_GUARD.check_dev_merge_queue(Path("/nonexistent"), ["README.md"]), [])
        self.assertTrue(ADR_GUARD.check_dev_merge_queue(Path("/nonexistent"), [RULESET_REL]))


if __name__ == "__main__":
    unittest.main()
