"""Exercise the consumer setup and Git path boundary with native commands."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


class DocumentationWorkflowTests(unittest.TestCase):
    def test_ci_uses_the_verified_setup_and_native_make_gates(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/vale.yml").read_text())
        commands = [step.get("run", "") for step in workflow["jobs"]["vale"]["steps"]]
        for command in ("make docs-tools", "make docs-changed", "make docs-required", "make docs-report"):
            self.assertIn(command, commands)
        # PyYAML uses YAML 1.1 and reads the unquoted GitHub key `on` as True.
        paths = workflow.get("on", workflow.get(True))["pull_request"]["paths"]
        for path in ("**/*.md", ".vale.ini", ".ste-required.txt", "tools/install-vale.sh", "Makefile"):
            self.assertIn(path, paths)
        self.assertEqual(workflow["permissions"], {"contents": "read"})

    def test_docs_build_uses_the_same_make_entrypoint_without_pr_publication(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/docs.yml").read_text())
        steps = workflow["jobs"]["build"]["steps"]
        self.assertIn("make docs-build", [step.get("run") for step in steps])
        upload = next(step for step in steps if "upload-pages-artifact@" in step.get("uses", ""))
        self.assertEqual(upload["if"], "github.event_name != 'pull_request'")
        self.assertEqual(workflow["jobs"]["deploy"]["if"], "github.event_name != 'pull_request'")


class DocumentationToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        shutil.copy(ROOT / "Makefile", self.repo)
        tools = self.repo / "tools"
        tools.mkdir()
        shutil.copy(ROOT / "tools/install-vale.sh", tools)
        self.capture = self.repo / "calls.jsonl"
        self.env = {**os.environ, "LINT_CAPTURE": str(self.capture)}
        self.env.pop("MAKEFLAGS", None)
        for name, path in (
            ("vale", ".tools/vale/current/vale"),
            ("ste", ".tools/doc-tools/0.1.0/tools/ste-lint.sh"),
        ):
            script = self.repo / path
            script.parent.mkdir(parents=True, exist_ok=True)
            implementation = Path(str(script) + ".py") if name == "ste" else script
            implementation.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "with open(os.environ['LINT_CAPTURE'], 'a') as stream:\n"
                f"    stream.write(json.dumps({{'tool': {name!r}, 'args': sys.argv[1:]}}) + '\\n')\n"
                "if '--no-exit' in sys.argv:\n"
                "    print('SYNTHETIC_EVIDENCE: a retained source excerpt')\n"
                "    print('Legacy Vale summary')\n"
                "sys.exit(int(os.environ.get('LINT_STATUS', '0')))\n"
            )
            if name == "ste":
                script.write_text('#!/bin/sh\nexec python3 "$0.py" "$@"\n')
            script.chmod(0o755)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        for name in ("old.md", "deleted.md"):
            (self.repo / name).write_text("The page is retained.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Initial fixture")
        self.git("update-ref", "refs/remotes/origin/dev", "HEAD")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True)

    def run_target(self, target: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["make", "--no-print-directory", target],
            cwd=self.repo,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self) -> list[dict]:
        if not self.capture.exists():
            return []
        return [json.loads(line) for line in self.capture.read_text().splitlines()]

    def test_changed_paths_preserve_names_and_skip_deletions(self) -> None:
        names = [".guide/nested/README.md", "page with spaces.md", "-guide.md", "line\nbreak.md"]
        for name in names:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Read this guide.\n")
        (self.repo / "old.md").rename(self.repo / "renamed guide.md")
        (self.repo / "deleted.md").unlink()
        self.git("add", "-A")
        self.git("commit", "-qm", "Change fixture pages")
        result = self.run_target("docs-changed")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tool"], "vale")
        self.assertEqual(set(calls[0]["args"]), {"./" + name for name in [*names, "renamed guide.md"]})

    def test_empty_selection_does_not_scan_the_corpus(self) -> None:
        result = self.run_target("docs-changed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_missing_base_is_a_failure_not_an_empty_selection(self) -> None:
        result = self.run_target("docs-changed", DOCS_BASE="missing-base")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing-base", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_required_paths_with_spaces_reach_both_checkers(self) -> None:
        (self.repo / "page with spaces.md").write_text("Read this guide.\n")
        (self.repo / ".ste-required.txt").write_text("page with spaces.md\n")
        result = self.run_target("docs-required")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.calls(),
            [{"tool": "vale", "args": ["./page with spaces.md"]}, {"tool": "ste", "args": ["./page with spaces.md"]}],
        )

    def test_empty_or_stale_required_list_fails(self) -> None:
        for content in ("", "missing.md\n"):
            with self.subTest(content=content):
                (self.repo / ".ste-required.txt").write_text(content)
                self.assertNotEqual(self.run_target("docs-required").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_checker_errors_propagate(self) -> None:
        (self.repo / ".ste-required.txt").write_text("old.md\n")
        result = self.run_target("docs-required", LINT_STATUS="2")
        self.assertNotEqual(result.returncode, 0)

    def test_corpus_report_keeps_hidden_prose_and_preserves_native_errors(self) -> None:
        for name in (".guide/page with spaces.md", "CHANGELOG.md"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Read this guide.\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "Add corpus fixture")
        result = self.run_target("docs-report")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SYNTHETIC_EVIDENCE", result.stdout)
        self.assertIn("Legacy Vale summary", result.stdout)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIn("./.guide/page with spaces.md", call["args"])
            self.assertNotIn("./CHANGELOG.md", call["args"])
        self.assertIn("--no-exit", calls[0]["args"])
        self.assertEqual(calls[1]["args"][:3], ["--fail-over", "-1", "--summary"])
        self.assertNotEqual(self.run_target("docs-report", LINT_STATUS="2").returncode, 0)

    def test_bad_package_download_cannot_reach_extraction(self) -> None:
        # Remove the fake package; setup must never use it as a download substitute.
        shutil.rmtree(self.repo / ".tools")
        binaries = self.repo / "bin"
        binaries.mkdir()
        curl = binaries / "curl"
        curl.write_text('#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\nprintf altered > "$2"\n')
        curl.chmod(0o755)
        result = self.run_target("docs-tools", PATH=f"{binaries}:{os.environ['PATH']}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum", result.stderr.lower())
        self.assertFalse((self.repo / ".tools/vale/current/vale").exists())
        self.assertFalse((self.repo / ".tools/doc-tools/0.1.0/tools/ste-lint.sh").exists())


if __name__ == "__main__":
    unittest.main()
