"""Read-only projections of validated original trial records for an export."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from raes_contracts.contracts import ExperimentRunModel

from shared.raes.trial_archive import TrialArchiveIdentity, VerifiedTrialArchive, _validated_archive
from shared.raes.trial_archive_jsonl import USAGE_FIELDS
from shared.raes.trial_archive_records import _retained_plan, _structured_document


@dataclass(frozen=True, slots=True)
class TrialArchiveContents:
    """Derived views; the original portable contracts remain authoritative."""

    facts: VerifiedTrialArchive
    plan: dict[str, Any]
    run: dict[str, Any]
    members: list[dict[str, Any]]
    capture_gaps: list[dict[str, Any]]
    usage: list[dict[str, Any]]


def _metadata(
    value: object, member: str, pointer: str = "", attempt_id: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Index disclosed values and their exact locations without estimating measurements."""
    usage: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    children: list[tuple[str | int, object]]
    if isinstance(value, dict):
        if value.get("schema_version") in ("admitted-trial-plan/v1", "experiment-capture-spec/v1"):
            return usage, gaps
        if isinstance(value.get("execution_attempt_id"), str):
            attempt_id = value["execution_attempt_id"]
        selected = {key: child for key, child in value.items() if key in USAGE_FIELDS}
        if selected:
            usage.append({"member": member, "pointer": pointer, "execution_attempt_id": attempt_id, "values": selected})
        if value.get("loss_disclosure"):
            gaps.append({"member": member, "pointer": pointer + "/loss_disclosure", "value": value["loss_disclosure"]})
        children = [
            (str(key).replace("~", "~0").replace("/", "~1"), child)
            for key, child in value.items()
            if key not in selected
        ]
    elif isinstance(value, list):
        children = list(enumerate(value))
    else:
        return usage, gaps
    for key, child in children:
        nested_usage, nested_gaps = _metadata(child, member, f"{pointer}/{key}", attempt_id)
        usage.extend(nested_usage)
        gaps.extend(nested_gaps)
    return usage, gaps


def inspect_trial_archive(path: Path, expected: TrialArchiveIdentity) -> TrialArchiveContents:
    """Reuse custody validation and released RAES contracts without changing bytes."""
    facts, documents, members, seal, formats = _validated_archive(path, expected, retain_usage=True)
    payloads = {
        name: _structured_document(raw, formats.get(name, "json"))
        for name, raw in documents.items()
        if name != "checksums.sha256"
    }
    plan = _retained_plan(list(payloads.values())).model_dump(mode="json")
    declarations = {item["path"]: item for item in cast(list[dict[str, Any]], seal["inventory"])}
    inventory = [
        {
            "path": f"{expected.run_id}/{name}",
            "size_bytes": size,
            "sha256": digest,
            "media_type": declarations.get(name, {}).get("media_type"),
            "role": declarations.get(name, {}).get("role"),
        }
        for name, (size, digest) in sorted(members.items())
    ]
    usage: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for name, payload in sorted(payloads.items()):
        if name == "seal.json":
            continue
        # Virtual JSON Lines documents name the original member and line number.
        member, pointer = name, ""
        line_number = None
        if name.startswith(":"):
            _, member, line = name.split(":", 2)
            line_number = int(line.removesuffix(".json"))
        value = payload["archive_value"] if documents[name].lstrip().startswith(b"[") else payload
        found_usage, found_gaps = _metadata(value, member, pointer)
        if line_number is not None:
            for record in found_usage + found_gaps:
                record["line"] = line_number
        usage.extend(found_usage)
        gaps.extend(found_gaps)
    if not facts.evidence_complete:
        gaps.append(
            {
                "member": "seal.json",
                "pointer": "/completeness",
                "value": seal.get("completeness"),
                "validated_gap_count": facts.gap_count,
            }
        )
    return TrialArchiveContents(
        facts,
        plan,
        ExperimentRunModel.model_validate(payloads["manifest.json"]).model_dump(mode="json"),
        inventory,
        gaps,
        usage,
    )
