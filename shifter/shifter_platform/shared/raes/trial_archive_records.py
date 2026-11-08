"""Join original scientific records through the released public RAES contracts."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterator
from datetime import datetime
from typing import overload
from urllib.parse import urlsplit

from raes import SDLParseError, load_sdl_fragment
from raes_contracts.contracts import (
    AdmittedTrialPlanModel,
    ExperimentCaptureSpecModel,
    ExperimentCaptureWindowModel,
    ExperimentEvidenceRecordModel,
    ExperimentReferenceModel,
    ExperimentRunModel,
    TrialCleanupReceiptModel,
    validate_admitted_trial_run,
)
from raes_contracts.json_ingress import parse_bounded_json
from raes_contracts.timestamps import parse_rfc3339_datetime

from shared.audit.integrity import _SECRET_KEY_SUFFIXES, _SECRET_KEYS
from shared.raes.trial_archive import MAX_JSON_BYTES, TrialArchiveError, TrialArchiveIdentity, _json, safe_archive_path
from shared.raes.trial_archive_lilrae import TRIAL_RECORD_CONTRACT, validate_trial_record
from shared.schemas._raes_validation import JsonObject, _reject_secret_value


def _walk(value: object) -> Iterator[JsonObject]:
    """Visit bounded parsed documents without changing their original bytes."""
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            if (normalized in _SECRET_KEYS or normalized.endswith(_SECRET_KEY_SUFFIXES)) and child not in (
                None,
                "",
                False,
                "[REDACTED]",
                "<redacted>",
                "REDACTED",
                [],
                {},
            ):
                raise TrialArchiveError("Archive contains a prohibited credential field")
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
    elif isinstance(value, str):
        _reject_secret_value("archive", value, error_cls=TrialArchiveError)


def reject_retained_credentials(value: object) -> None:
    """Apply the same scientific-record credential policy before SQL retention."""
    deque(_walk(value), maxlen=0)


def _artifact_path(uri: str, run_id: str) -> str:
    """Resolve a local evidence reference without permitting external retrieval."""
    parsed = urlsplit(uri)
    if parsed.scheme == "run" and parsed.netloc == run_id and not parsed.query and not parsed.fragment:
        return safe_archive_path(parsed.path.removeprefix("/"))
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise TrialArchiveError("Evidence byte reference must resolve inside the archive")
    return safe_archive_path(uri.removeprefix(f"{run_id}/"))


def validate_record_binding(payload: JsonObject, expected: TrialArchiveIdentity) -> set[str]:
    """Check explicit record ownership without confusing historical source refs."""
    if payload.get("run_id", expected.run_id) != expected.run_id:
        raise TrialArchiveError("Structured evidence belongs to another run")
    if payload.get("run_version", expected.run_version) != expected.run_version:
        raise TrialArchiveError("Structured evidence belongs to another run version")
    if payload.get("run_ref") is not None:
        reference = ExperimentReferenceModel.model_validate(payload["run_ref"])
        if (reference.ref_kind, reference.ref_id, reference.ref_version) != (
            "run",
            expected.run_id,
            expected.run_version,
        ):
            raise TrialArchiveError("Structured evidence belongs to another run")
    attempt_id = payload.get("execution_attempt_id")
    if attempt_id is None:
        return set()
    if not isinstance(attempt_id, str) or not 0 < len(attempt_id) <= 128:
        raise TrialArchiveError("Invalid structured evidence attempt identity")
    return {attempt_id}


def _binding_objects(value: object, expected: TrialArchiveIdentity) -> Iterator[JsonObject]:
    """Visit current records while leaving published admitted-plan nesting intact."""
    if isinstance(value, dict):
        if value.get("schema_version") == "admitted-trial-plan/v1":
            # A complete admitted plan legitimately contains other entries.
            # Its published validator owns those nested run identities.
            plan = AdmittedTrialPlanModel.model_validate(value)
            if (plan.plan_id, plan.plan_digest) != (expected.plan_id, expected.plan_digest):
                raise TrialArchiveError("Structured evidence contains another admitted plan")
        else:
            yield value
            for child in value.values():
                yield from _binding_objects(child, expected)
    elif isinstance(value, list):
        for child in value:
            yield from _binding_objects(child, expected)


def validate_structured_bindings(payload: JsonObject, expected: TrialArchiveIdentity) -> set[str]:
    """Validate nested current records; reference objects are historical links."""
    attempts = set()
    for record in _binding_objects(payload, expected):
        attempts.update(validate_record_binding(record, expected))
        if len(attempts) > 20000:
            raise TrialArchiveError("Structured evidence attempt identities exceed their bound")
    return attempts


def _verify_byte_reference(value: JsonObject, inventory: dict[str, tuple[int, str]], run_id: str) -> None:
    """Join one declared original artifact URI, checksum, and optional byte size."""
    uri = value.get("uri") or value.get("content_uri")
    checksum = value.get("checksum") or value.get("content_checksum")
    if not uri or checksum is None:
        return
    if not isinstance(uri, str) or not isinstance(checksum, dict):
        raise TrialArchiveError("Invalid declared evidence byte reference")
    path = _artifact_path(uri, run_id)
    actual = inventory.get(path)
    if actual is None or checksum.get("algorithm") != "sha256" or actual[1] != checksum.get("value"):
        raise TrialArchiveError("Declared evidence bytes are missing or corrupt")
    _verify_byte_size(value, actual[0])


def _verify_byte_size(value: JsonObject, actual_size: int) -> None:
    """Reject malformed or differing optional sizes on declared byte references."""
    if "size_bytes" in value and (type(value["size_bytes"]) is not int or actual_size != value["size_bytes"]):
        raise TrialArchiveError("Declared evidence size differs from the inventory")


def _verify_byte_references(payloads: list[JsonObject], inventory: dict[str, tuple[int, str]], run_id: str) -> None:
    """Verify every nested byte reference without fetching external content."""
    for payload in payloads:
        for value in _walk(payload):
            _verify_byte_reference(value, inventory, run_id)


def _join_record(
    payload: JsonObject,
    run: ExperimentRunModel,
    by_receipt: dict[str, TrialCleanupReceiptModel],
    evidence_ids: set[tuple[str, str]],
) -> None:
    """Validate one retained scientific identity against the original run."""
    schema = payload.get("schema_version")
    if schema == "trial-cleanup-receipt/v1":
        receipt = TrialCleanupReceiptModel.model_validate(payload)
        if receipt.receipt_id in by_receipt and by_receipt[receipt.receipt_id] != receipt:
            raise TrialArchiveError("Conflicting cleanup records")
        by_receipt[receipt.receipt_id] = receipt
    elif schema == "experiment-evidence-record/v1":
        evidence = ExperimentEvidenceRecordModel.model_validate(payload)
        identity = (evidence.evidence_record_id, evidence.record_version)
        if identity in evidence_ids or (
            evidence.run_ref.ref_kind,
            evidence.run_ref.ref_id,
            evidence.run_ref.ref_version,
        ) != ("run", run.run_id, run.run_version):
            raise TrialArchiveError("Duplicate or foreign evidence record")
        evidence_ids.add(identity)
    elif schema == "experiment-run/v1":
        retained_run = ExperimentRunModel.model_validate(payload)
        if retained_run != run:
            raise TrialArchiveError("Conflicting or foreign archival run record")


def _join_retained_records(
    payloads: list[JsonObject], run: ExperimentRunModel, receipts: list[TrialCleanupReceiptModel]
) -> list[TrialCleanupReceiptModel]:
    """Validate current-run evidence identities and complete retained references."""
    by_receipt = {item.receipt_id: item for item in receipts}
    evidence_ids: set[tuple[str, str]] = set()
    for payload in (item for document in payloads for item in _walk(document)):
        _join_record(payload, run, by_receipt, evidence_ids)
    references = list(run.traceability.evidence_record_refs) if run.traceability else []
    if run.execution_accounting is not None:
        references.extend(
            reference for attempt in run.execution_accounting.attempts for reference in attempt.evidence_record_refs
        )
    if any((reference.ref_id, reference.ref_version) not in evidence_ids for reference in references):
        raise TrialArchiveError("Declared evidence record is absent")
    return list(by_receipt.values())


def _coverage(marker: JsonObject, run: ExperimentRunModel, payloads: list[JsonObject]) -> tuple[bool, int]:
    """Combine original loss disclosures independently of scientific outcomes."""
    completeness = marker["completeness"]
    if not isinstance(completeness, dict):
        raise TrialArchiveError("Invalid archive completeness disclosure")
    complete, gaps = completeness["complete"], completeness["limitations"]
    if type(complete) is not bool or not isinstance(gaps, list) or complete != (not gaps):
        raise TrialArchiveError("Invalid archive completeness disclosure")
    capture_gaps = (
        sum(attempt.capture_status != "complete" for attempt in run.execution_accounting.attempts)
        if run.execution_accounting
        else 0
    )
    disclosed_loss = sum(bool(item.get("loss_disclosure")) for document in payloads for item in _walk(document))
    gap_count = max(len(gaps), capture_gaps, disclosed_loss, int(run.record_state == "partial"))
    return complete and gap_count == 0, gap_count


def _has_capture_bytes(
    record: ExperimentEvidenceRecordModel, inventory: dict[str, tuple[int, str]], run_id: str
) -> bool:
    """Require nonempty original content for a declared captured artifact."""
    content = record.raw_content
    uri = content.artifact_ref.uri if content.artifact_ref is not None else content.content_uri
    return uri is not None and inventory.get(_artifact_path(uri, run_id), (0, ""))[0] > 0


@overload
def _timestamp(value: str) -> datetime:
    """Parse a required public-contract timestamp."""
    ...


@overload
def _timestamp(value: None) -> None:
    """Preserve an unbounded optional timestamp."""
    ...


def _timestamp(value: str | None) -> datetime | None:
    """Parse an optional capture boundary through the public timestamp contract."""
    return parse_rfc3339_datetime("capture coverage", value) if value is not None else None


def _window_applies(window: ExperimentCaptureWindowModel, start: datetime, end: datetime | None) -> bool:
    """Determine whether two observed capture intervals can overlap."""
    window_start, window_end = _timestamp(window.starts_at), _timestamp(window.ends_at)
    return not (
        (window_end is not None and window_end < start)
        or (end is not None and window_start is not None and window_start > end)
    )


def _attempt_captures(
    run: ExperimentRunModel, records: list[ExperimentEvidenceRecordModel]
) -> list[tuple[datetime, datetime | None, list[ExperimentEvidenceRecordModel]]]:
    """Use published accounting links; an unassigned record cannot cover retries."""
    by_id = {(record.evidence_record_id, record.record_version): record for record in records}
    if run.execution_accounting is None:
        # Legacy lineage has no per-attempt evidence links. Preserve its bytes
        # while reporting unproven capture coverage for each retained attempt.
        return [
            (_timestamp(run.started_at), _timestamp(run.ended_at), []) for _ in run.trial_provenance.execution_attempts
        ]
    attempts = run.execution_accounting.attempts
    coverage = []
    for attempt in attempts:
        start, end = _timestamp(attempt.started_at), _timestamp(attempt.ended_at)
        identities = {(ref.ref_id, ref.ref_version) for ref in attempt.evidence_record_refs}
        identities.update((record.evidence_record_id, record.record_version) for record in attempt.evidence_records)
        retained = records if len(attempts) == 1 else [by_id[identity] for identity in identities]
        retained = [
            record
            for record in retained
            if _timestamp(record.captured_at) >= start and (end is None or _timestamp(record.captured_at) <= end)
        ]
        coverage.append((start, end, retained))
    return coverage


def _capture_inputs(
    payloads: list[JsonObject], run: ExperimentRunModel, plan: AdmittedTrialPlanModel
) -> tuple[dict[tuple[str, str], ExperimentCaptureSpecModel], list[ExperimentEvidenceRecordModel], int]:
    """Validate retained capture declarations and identify missing specifications."""
    specifications: dict[tuple[str, str], ExperimentCaptureSpecModel] = {}
    records: list[ExperimentEvidenceRecordModel] = []
    for value in (item for payload in payloads for item in _walk(payload)):
        if value.get("schema_version") == "experiment-capture-spec/v1":
            spec = ExperimentCaptureSpecModel.model_validate(value)
            key = (spec.capture_spec_id, spec.spec_version)
            if key in specifications and specifications[key] != spec:
                raise TrialArchiveError("Conflicting capture specifications")
            specifications[key] = spec
        elif value.get("schema_version") == "experiment-evidence-record/v1":
            records.append(ExperimentEvidenceRecordModel.model_validate(value))
    declared = {(ref.ref_id, ref.ref_version) for ref in plan.input_refs.capture_spec_refs}
    if run.traceability:
        declared.update((ref.ref_id, ref.ref_version) for ref in run.traceability.capture_spec_refs)
    declared.update((record.capture_spec_ref.ref_id, record.capture_spec_ref.ref_version) for record in records)
    return specifications, records, len(declared - specifications.keys())


def _specification_gaps(
    specification: ExperimentCaptureSpecModel,
    key: tuple[str, str],
    start: datetime,
    end: datetime | None,
    records: list[ExperimentEvidenceRecordModel],
    inventory: dict[str, tuple[int, str]],
    run_id: str,
) -> int:
    """Count absent capture windows within one applicable execution attempt."""
    windows = {window.window_id: window for window in specification.capture_windows}
    gaps = 0
    for requirement_id, requirement in specification.capture_requirements.items():
        for window_id in requirement.window_refs:
            window = windows[window_id]
            if _window_applies(window, start, end):
                matching = [
                    record
                    for record in records
                    if _matches_capture(record, key, requirement_id, requirement.output_contract, window)
                ]
                gaps += not any(
                    record.raw_content.loss_disclosure or _has_capture_bytes(record, inventory, run_id)
                    for record in matching
                )
    return gaps


def _matches_capture(
    record: ExperimentEvidenceRecordModel,
    key: tuple[str, str],
    requirement_id: str,
    output_contract: str,
    window: ExperimentCaptureWindowModel,
) -> bool:
    """Join record declarations and timestamp to one specified capture window."""
    captured = _timestamp(record.captured_at)
    return (
        (record.capture_spec_ref.ref_id, record.capture_spec_ref.ref_version) == key
        and record.capture_requirement_ref == requirement_id
        and record.output_contract == output_contract
        and record.capture_window_ref == window.window_id
        and _window_applies(window, captured, captured)
    )


def _capture_gaps(
    payloads: list[JsonObject],
    inventory: dict[str, tuple[int, str]],
    run: ExperimentRunModel,
    plan: AdmittedTrialPlanModel,
) -> int:
    """Count missing or empty declared captures without changing scientific status."""
    specifications, records, gaps = _capture_inputs(payloads, run, plan)
    attempts = _attempt_captures(run, records)
    for key, specification in specifications.items():
        for start, end, retained in attempts:
            gaps += _specification_gaps(specification, key, start, end, retained, inventory, run.run_id)
    return gaps


def _structured_document(raw: bytes, kind: str) -> JsonObject:
    """Parse original JSON or safe YAML without rewriting accepted bytes."""
    if kind != "yaml":
        root = "array" if raw.lstrip().startswith(b"[") else "object"
        value = parse_bounded_json(raw, max_bytes=MAX_JSON_BYTES, root=root)
        return value if isinstance(value, dict) else {"archive_value": value}
    try:
        value = load_sdl_fragment(raw.decode("utf-8"), mapping_keys="literal")
    except SDLParseError:
        raise TrialArchiveError("Archive YAML document is invalid") from None
    return value if isinstance(value, dict) else {"archive_value": value}


def _validate_plan_identity(
    plan: AdmittedTrialPlanModel, run: ExperimentRunModel, expected: TrialArchiveIdentity
) -> None:
    """Join expected admission identities to the released plan and run models."""
    if plan.plan_digest != expected.plan_digest or run.run_version != expected.run_version:
        raise TrialArchiveError("Archive contract digest or version differs")
    experiment = plan.input_refs.study_ref or plan.input_refs.authoring_input_ref
    if experiment.ref_id != expected.experiment_id or plan.plan_id != expected.plan_id:
        raise TrialArchiveError("Archive belongs to another experiment or plan")
    if run.run_id != expected.run_id or run.task_ref != plan.input_refs.task_ref:
        raise TrialArchiveError("Archive run or task identity differs")
    _validate_entry_identity(plan, run, expected)


def _validate_entry_identity(
    plan: AdmittedTrialPlanModel, run: ExperimentRunModel, expected: TrialArchiveIdentity
) -> None:
    """Join the expected entry identity and digest to its admitted run."""
    entry = plan.entries.get(expected.entry_id)
    if entry is None or entry.run_id != run.run_id or entry.entry_digest != expected.entry_digest:
        raise TrialArchiveError("Archive run differs from the expected entry")


def _retained_plan(payloads: list[JsonObject]) -> AdmittedTrialPlanModel:
    """Require exactly one original admitted plan from nested retained records."""
    plans = [
        AdmittedTrialPlanModel.model_validate(item)
        for payload in payloads
        for item in _walk(payload)
        if item.get("schema_version") == "admitted-trial-plan/v1"
    ]
    if len(plans) != 1:
        raise TrialArchiveError("Archive must retain one admitted trial plan")
    return plans[0]


def _execution_history(
    run: ExperimentRunModel, expected: TrialArchiveIdentity, trace_attempts: set[str]
) -> list[TrialCleanupReceiptModel]:
    """Bind the independently expected attempt to retained accounting and trace links."""
    accounting, lineage = run.execution_accounting, run.trial_provenance
    if accounting is not None:
        entry_id = accounting.plan_entry_id
        attempt_ids = {item.execution_attempt_id for item in accounting.attempts}
        receipts = [item.cleanup_receipt for item in accounting.attempts if item.cleanup_receipt is not None]
    elif lineage is not None:
        entry_id = lineage.plan_entry_id
        attempt_ids = {item.execution_attempt_id for item in lineage.execution_attempts}
        receipts = []
    else:
        raise TrialArchiveError("Archive lacks execution attempt accounting")
    if entry_id != expected.entry_id or expected.attempt_id not in attempt_ids:
        raise TrialArchiveError("Archive differs from the expected execution attempt")
    if not trace_attempts <= attempt_ids:
        raise TrialArchiveError("Structured trace references an undeclared execution attempt")
    return receipts


def validate_archive_records(
    documents: dict[str, bytes],
    inventory: dict[str, tuple[int, str]],
    marker: JsonObject,
    expected: TrialArchiveIdentity,
    *,
    trace_attempts: set[str],
    formats: dict[str, str],
) -> tuple[str, str, bool, int, JsonObject | None]:
    """Keep collection and scientific success independent, including partial runs."""
    payloads = [
        _structured_document(raw, formats.get(name, "json"))
        for name, raw in documents.items()
        if name != "checksums.sha256"
    ]
    for payload in payloads:
        trace_attempts.update(validate_structured_bindings(payload, expected))
    _verify_byte_references(payloads, inventory, expected.run_id)
    if marker.get("sealed_contract_versions") == [TRIAL_RECORD_CONTRACT]:
        return validate_trial_record(documents, marker, expected, trace_attempts)
    run = ExperimentRunModel.model_validate(_json(documents["manifest.json"]))
    plan = _retained_plan(payloads)
    _validate_plan_identity(plan, run, expected)
    receipts = _execution_history(run, expected, trace_attempts)
    receipts = _join_retained_records(payloads, run, receipts)
    validate_admitted_trial_run(plan, run, receipts)
    if any(
        marker.get(key) != value
        for key, value in (
            ("run_id", run.run_id),
            ("run_version", run.run_version),
            ("run_status", run.run_status),
            ("outcome_status", run.outcome_status),
        )
    ):
        raise TrialArchiveError("Seal identity or outcome contradicts its run")
    complete, gap_count = _coverage(marker, run, payloads)
    capture_gaps = _capture_gaps(payloads, inventory, run, plan)
    entry = plan.entries[expected.entry_id]
    metadata = {
        "plan_id": plan.plan_id,
        "plan_digest": plan.plan_digest,
        "replacement_origin": plan.replacement_origin.model_dump(mode="json") if plan.replacement_origin else None,
        "entries": {
            expected.entry_id: {
                "plan_entry_id": entry.plan_entry_id,
                "entry_digest": entry.entry_digest,
                "run_id": entry.run_id,
                "coordinate": entry.coordinate.model_dump(mode="json"),
            }
        },
    }
    if len(json.dumps(metadata).encode()) > 16384:
        raise TrialArchiveError("Archive plan association exceeds supported metadata size")
    return run.run_status, run.outcome_status, complete and capture_gaps == 0, gap_count + capture_gaps, metadata
