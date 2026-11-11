"""ADR-003-R9: pull requests to ``dev`` merge through a merge queue.

``docs/adr/dev-ruleset.json`` is the repository ruleset that protects ``dev``.
GitHub configures a merge queue only through a ruleset. The queue runs the
required checks again on each merge group, and a required context that does
not report on the merge group blocks the queue. This check reads the ruleset
and the workflows as data and fails when:

* the ruleset does not target exactly ``dev`` or is not active;
* the ruleset has no merge queue, or the queue cannot group more than one pull
  request;
* the ruleset requires strict status checks, or turns them off without a merge
  queue;
* a required context has no producer workflow;
* a required status check comes from the code scanning app, which does not
  report a check run on a merge group;
* the ruleset has no ``code_scanning`` rule for CodeQL, or the ``CodeQL``
  workflow does not run on ``pull_request`` for ``dev`` and on ``merge_group``; or
* a producer does not run on ``pull_request`` for ``dev`` and on
  ``merge_group``, or its job condition filters events without ``merge_group``.

A producer is a workflow job whose ``name`` equals the context.
"""

from __future__ import annotations

import json
from pathlib import Path

from .._common import Violation, is_guard_source_path
from .._workflow_model import _dw_job_if, _dw_jobs, _dw_load_workflow, _DwShapeError

_CHECK = "dev-merge-queue"
_RULE_ID = "ADR-003-R9"
DEV_RULESET_REL = "docs/adr/dev-ruleset.json"
_WORKFLOW_DIR = ".github/workflows"
# (workflow path, workflow, jobs that report the context)
_Producer = tuple[str, dict[str, object], list[object]]
_DEV_REF = "refs/heads/dev"
_MERGE_GROUP_TYPE = "checks_requested"
# GitHub Advanced Security, which posts the code scanning check runs.
_CODE_SCANNING_APP_ID = 57789
_CODEQL_TOOL = "CodeQL"
_CODEQL_WORKFLOW = "CodeQL"


def _violation(path: str, message: str) -> Violation:
    """Build an ADR-003-R9 violation."""
    return Violation(_CHECK, _RULE_ID, path, message)


def _relevant(files: list[str] | None) -> bool:
    """True when a changed file can affect the merge queue contract."""
    if files is None:
        return True
    return any(
        path == DEV_RULESET_REL or path.startswith(f"{_WORKFLOW_DIR}/") or is_guard_source_path(path) for path in files
    )


def _rules_by_type(ruleset: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return the ruleset rules keyed by type. A rule without parameters maps to {}."""
    rules = ruleset.get("rules")
    by_type: dict[str, dict[str, object]] = {}
    if not isinstance(rules, list):
        return by_type
    for rule in rules:
        if isinstance(rule, dict) and isinstance(rule.get("type"), str):
            params = rule.get("parameters")
            by_type[rule["type"]] = params if isinstance(params, dict) else {}
    return by_type


def _target_violations(ruleset: dict[str, object]) -> list[Violation]:
    """The ruleset must be an active branch ruleset for exactly ``dev``."""
    violations: list[Violation] = []
    if ruleset.get("target") != "branch" or ruleset.get("enforcement") != "active":
        violations.append(_violation(DEV_RULESET_REL, "the dev ruleset must be an active branch ruleset"))
    conditions = ruleset.get("conditions")
    ref_name = conditions.get("ref_name") if isinstance(conditions, dict) else None
    include = ref_name.get("include") if isinstance(ref_name, dict) else None
    if include != [_DEV_REF]:
        violations.append(
            _violation(
                DEV_RULESET_REL,
                f"the dev ruleset must include exactly {_DEV_REF}; main does not use the merge queue",
            )
        )
    return violations


def _queue_violations(rules: dict[str, dict[str, object]]) -> list[Violation]:
    """``dev`` needs a merge queue that groups pull requests and non-strict checks."""
    violations: list[Violation] = []
    queue = rules.get("merge_queue")
    if queue is None:
        violations.append(_violation(DEV_RULESET_REL, "the dev ruleset must have a merge_queue rule"))
    else:
        for key in ("max_entries_to_merge", "max_entries_to_build"):
            value = queue.get(key)
            if not isinstance(value, int) or value < 2:
                violations.append(
                    _violation(
                        DEV_RULESET_REL,
                        f"merge_queue {key} must be at least 2 so a merge group holds more than one pull request",
                    )
                )
    checks = rules.get("required_status_checks")
    if checks is None:
        violations.append(_violation(DEV_RULESET_REL, "the dev ruleset must have a required_status_checks rule"))
        return violations
    strict = checks.get("strict_required_status_checks_policy")
    if strict is not False:
        violations.append(
            _violation(
                DEV_RULESET_REL,
                "dev must not require strict status checks; the merge queue tests each pull request "
                "against the latest dev",
            )
        )
    elif queue is None:
        violations.append(
            _violation(DEV_RULESET_REL, "dev may turn off strict status checks only when it uses the merge queue")
        )
    return violations


def _required_contexts(rules: dict[str, dict[str, object]]) -> list[str]:
    """Return the required status check contexts of the ruleset."""
    checks = rules.get("required_status_checks", {}).get("required_status_checks")
    if not isinstance(checks, list):
        return []
    return [str(item["context"]) for item in checks if isinstance(item, dict) and item.get("context")]


def _code_scanning_violations(
    rules: dict[str, dict[str, object]], workflows: dict[str, dict[str, object]]
) -> list[Violation]:
    """CodeQL gates the queue through a code_scanning rule, not a required check run."""
    violations: list[Violation] = []
    checks = rules.get("required_status_checks", {}).get("required_status_checks")
    for item in checks if isinstance(checks, list) else []:
        if isinstance(item, dict) and item.get("integration_id") == _CODE_SCANNING_APP_ID:
            violations.append(
                _violation(
                    DEV_RULESET_REL,
                    f"required context '{item.get('context')}' comes from code scanning, which does not report "
                    "on a merge group; require code scanning results with a code_scanning rule",
                )
            )
    tools = rules.get("code_scanning", {}).get("code_scanning_tools")
    if not isinstance(tools, list) or not any(
        isinstance(tool, dict) and tool.get("tool") == _CODEQL_TOOL for tool in tools
    ):
        violations.append(_violation(DEV_RULESET_REL, "the dev ruleset must have a code_scanning rule for CodeQL"))
    codeql = [(rel, wf) for rel, wf in workflows.items() if wf.get("name") == _CODEQL_WORKFLOW]
    if not codeql:
        violations.append(_violation(DEV_RULESET_REL, "the code_scanning rule for CodeQL has no CodeQL workflow"))
    for rel, wf in codeql:
        violations.extend(_producer_violations(_CODEQL_WORKFLOW, rel, wf, []))
    return violations


def _load_workflows(repo_root: Path) -> dict[str, dict[str, object]]:
    """Load every workflow under .github/workflows keyed by repo-relative path."""
    workflows: dict[str, dict[str, object]] = {}
    for path in sorted((repo_root / _WORKFLOW_DIR).glob("*.y*ml")):
        rel = f"{_WORKFLOW_DIR}/{path.name}"
        try:
            workflows[rel] = _dw_load_workflow(repo_root, rel)
        except _DwShapeError:
            continue
    return workflows


def _producers(context: str, workflows: dict[str, dict[str, object]]) -> list[_Producer]:
    """Return (path, workflow, producing jobs) for each workflow that reports ``context``."""
    found: list[_Producer] = []
    for rel, wf in workflows.items():
        try:
            jobs = _dw_jobs(wf, rel)
        except _DwShapeError:
            continue
        named = [job for job in jobs.values() if isinstance(job, dict) and job.get("name") == context]
        if named:
            found.append((rel, wf, named))
    return found


def _branches_cover_dev(config: object) -> bool:
    """True when a pull_request trigger config reaches pull requests to ``dev``."""
    if not isinstance(config, dict):
        return True
    branches = config.get("branches")
    if branches is None:
        return True
    return isinstance(branches, list) and "dev" in [str(branch) for branch in branches]


def _merge_group_requested(config: object) -> bool:
    """True when a merge_group trigger config includes the checks_requested type."""
    if not isinstance(config, dict):
        return True
    types = config.get("types")
    return types is None or (isinstance(types, list) and _MERGE_GROUP_TYPE in types)


def _trigger_map(on: object) -> dict[str, object]:
    """Return the workflow triggers as an event-to-config mapping."""
    if isinstance(on, str):
        on = [on]
    if isinstance(on, list):
        return {str(event): None for event in on}
    return {str(event): config for event, config in on.items()} if isinstance(on, dict) else {}


def _producer_violations(context: str, rel: str, wf: dict[str, object], jobs: list[object]) -> list[Violation]:
    """A producer must run on pull_request for dev and on merge_group."""
    events = _trigger_map(wf.get("on"))
    violations: list[Violation] = []
    if "pull_request" not in events or not _branches_cover_dev(events["pull_request"]):
        violations.append(_violation(rel, f"producer of required context '{context}' must run on pull_request to dev"))
    if "merge_group" not in events or not _merge_group_requested(events["merge_group"]):
        violations.append(
            _violation(
                rel,
                f"producer of required context '{context}' must run on merge_group "
                f"({_MERGE_GROUP_TYPE}) because dev merges through a merge queue",
            )
        )
    for job in jobs:
        condition = _dw_job_if(job) if isinstance(job, dict) else ""
        if "event_name" in condition and "merge_group" not in condition:
            violations.append(
                _violation(
                    rel,
                    f"a job that reports required context '{context}' filters events without merge_group",
                )
            )
    return violations


def _load_ruleset(repo_root: Path) -> tuple[dict[str, object] | None, str]:
    """Return the dev ruleset, or None and the reason it cannot be used."""
    try:
        ruleset = json.loads((repo_root / DEV_RULESET_REL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot read the dev ruleset: {exc}"
    if not isinstance(ruleset, dict):
        return None, "the dev ruleset must be a JSON object"
    return ruleset, ""


def check_dev_merge_queue(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """ADR-003-R9: dev uses a merge queue whose required contexts report on merge groups."""
    if not _relevant(files):
        return []
    ruleset, load_error = _load_ruleset(repo_root)
    if ruleset is None:
        return [_violation(DEV_RULESET_REL, load_error)]
    rules = _rules_by_type(ruleset)
    violations = _target_violations(ruleset) + _queue_violations(rules)
    contexts = _required_contexts(rules)
    if not contexts:
        violations.append(_violation(DEV_RULESET_REL, "the dev ruleset must require at least one status check"))
    workflows = _load_workflows(repo_root)
    violations.extend(_code_scanning_violations(rules, workflows))
    for context in contexts:
        producers = _producers(context, workflows)
        if not producers:
            violations.append(_violation(DEV_RULESET_REL, f"required context '{context}' has no producer workflow"))
        for rel, wf, jobs in producers:
            violations.extend(_producer_violations(context, rel, wf, jobs))
    return violations
