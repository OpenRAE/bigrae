"""Join original scientific records through the released public RAES contracts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
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
from shared.schemas._raes_validation import _reject_secret_value


def _walk(value: object) -> Iterator[dict]:
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


def _artifact_path(uri: str, run_id: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme == "run" and parsed.netloc == run_id and not parsed.query and not parsed.fragment:
        return safe_archive_path(parsed.path.removeprefix("/"))
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise TrialArchiveError("Evidence byte reference must resolve inside the archive")
    return safe_archive_path(uri.removeprefix(f"{run_id}/"))


def validate_record_binding(payload: dict, expected: TrialArchiveIdentity) -> set[str]:
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


def _binding_objects(value: object, expected: TrialArchiveIdentity) -> Iterator[dict]:
    if isinstance(value, dict):
        if value.get("schema_version") == "admitted-trial-plan/v1":
            # A complete admitted plan legitimately contains other entries.
            # Its published validator owns those nested run identities.
            plan = AdmittedTrialPlanModel.model_validate(value)
            if (plan.plan_id, plan.plan_digest) != (expected.plan_id, expected.plan_digest):
                raise TrialArchiveError("Structured evidence contains another admitted plan")
            return
        yield value
        for child in value.values():
            yield from _binding_objects(child, expected)
    elif isinstance(value, list):
        for child in value:
            yield from _binding_objects(child, expected)


def validate_structured_bindings(payload: dict, expected: TrialArchiveIdentity) -> set[str]:
    """Validate nested current records; reference objects are historical links."""
    attempts = set()
    for record in _binding_objects(payload, expected):
        attempts.update(validate_record_binding(record, expected))
        if len(attempts) > 20000:
            raise TrialArchiveError("Structured evidence attempt identities exceed their bound")
    return attempts


def _verify_byte_references(payloads: list[dict], inventory: dict, run_id: str) -> None:
    for payload in payloads:
        for value in _walk(payload):
            # Existing artifact references and URI-backed raw evidence use
            # these owner-defined fields. No remote dereference is allowed.
            uri = value.get("uri") or value.get("content_uri")
            checksum = value.get("checksum") or value.get("content_checksum")
            if not uri or checksum is None:
                continue
            path = _artifact_path(uri, run_id)
            actual = inventory.get(path)
            if actual is None or checksum.get("algorithm") != "sha256" or actual[1] != checksum.get("value"):
                raise TrialArchiveError("Declared evidence bytes are missing or corrupt")
            if "size_bytes" in value and actual[0] != value["size_bytes"]:
                raise TrialArchiveError("Declared evidence size differs from the inventory")


def _join_retained_records(
    payloads: list[dict], run: ExperimentRunModel, receipts: list[TrialCleanupReceiptModel]
) -> list[TrialCleanupReceiptModel]:
    """Validate current-run evidence identities and complete retained references."""
    by_receipt = {item.receipt_id: item for item in receipts}
    evidence_ids = set()
    for payload in (item for document in payloads for item in _walk(document)):
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
    references = list(run.traceability.evidence_record_refs) if run.traceability else []
    if run.execution_accounting is not None:
        references.extend(
            reference for attempt in run.execution_accounting.attempts for reference in attempt.evidence_record_refs
        )
    if any((reference.ref_id, reference.ref_version) not in evidence_ids for reference in references):
        raise TrialArchiveError("Declared evidence record is absent")
    return list(by_receipt.values())


def _coverage(marker: dict, run: ExperimentRunModel, payloads: list[dict]) -> tuple[bool, int]:
    completeness = marker["completeness"]
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
    content = record.raw_content
    uri = content.artifact_ref.uri if content.artifact_ref is not None else content.content_uri
    return uri is not None and inventory.get(_artifact_path(uri, run_id), (0, ""))[0] > 0


def _timestamp(value: str | None) -> datetime | None:
    return parse_rfc3339_datetime("capture coverage", value) if value is not None else None


def _window_applies(window: ExperimentCaptureWindowModel, start: datetime, end: datetime | None) -> bool:
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
    payloads: list[dict], run: ExperimentRunModel, plan: AdmittedTrialPlanModel
) -> tuple[dict[tuple[str, str], ExperimentCaptureSpecModel], list[ExperimentEvidenceRecordModel], int]:
    specifications, records = {}, []
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


def _capture_gaps(
    payloads: list[dict], inventory: dict[str, tuple[int, str]], run: ExperimentRunModel, plan: AdmittedTrialPlanModel
) -> int:
    """Count missing or empty declared captures without changing scientific status."""
    specifications, records, gaps = _capture_inputs(payloads, run, plan)
    attempts = _attempt_captures(run, records)
    for key, specification in specifications.items():
        windows = {window.window_id: window for window in specification.capture_windows}
        for requirement_id, requirement in specification.capture_requirements.items():
            for window_id in requirement.window_refs:
                for start, end, retained in attempts:
                    if not _window_applies(windows[window_id], start, end):
                        continue
                    matching = (
                        record
                        for record in retained
                        if (record.capture_spec_ref.ref_id, record.capture_spec_ref.ref_version) == key
                        and record.capture_requirement_ref == requirement_id
                        and record.output_contract == requirement.output_contract
                        and record.capture_window_ref == window_id
                        and _window_applies(
                            windows[window_id], _timestamp(record.captured_at), _timestamp(record.captured_at)
                        )
                    )
                    # Explicit loss remains original and _coverage counts it.
                    observed = any(
                        record.raw_content.loss_disclosure or _has_capture_bytes(record, inventory, run.run_id)
                        for record in matching
                    )
                    gaps += not observed
    return gaps


def _structured_document(raw: bytes, kind: str) -> dict:
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
    if plan.plan_digest != expected.plan_digest or run.run_version != expected.run_version:
        raise TrialArchiveError("Archive contract digest or version differs")
    experiment = plan.input_refs.study_ref or plan.input_refs.authoring_input_ref
    if experiment.ref_id != expected.experiment_id or plan.plan_id != expected.plan_id:
        raise TrialArchiveError("Archive belongs to another experiment or plan")
    if run.run_id != expected.run_id or run.task_ref != plan.input_refs.task_ref:
        raise TrialArchiveError("Archive run or task identity differs")
    entry = plan.entries.get(expected.entry_id)
    if entry is None or entry.run_id != run.run_id or entry.entry_digest != expected.entry_digest:
        raise TrialArchiveError("Archive run differs from the expected entry")


def validate_archive_records(
    documents: dict,
    inventory: dict,
    marker: dict,
    expected: TrialArchiveIdentity,
    *,
    trace_attempts: set[str],
    formats: dict[str, str],
) -> tuple:
    """Keep collection and scientific success independent, including partial runs."""
    payloads = [
        _structured_document(raw, formats.get(name, "json"))
        for name, raw in documents.items()
        if name != "checksums.sha256"
    ]
    for payload in payloads:
        trace_attempts.update(validate_structured_bindings(payload, expected))
    _verify_byte_references(payloads, inventory, expected.run_id)
    run = ExperimentRunModel.model_validate(_json(documents["manifest.json"]))
    plans = [
        AdmittedTrialPlanModel.model_validate(item)
        for payload in payloads
        for item in _walk(payload)
        if item.get("schema_version") == "admitted-trial-plan/v1"
    ]
    if len(plans) != 1:
        raise TrialArchiveError("Archive must retain one admitted trial plan")
    plan = plans[0]
    _validate_plan_identity(plan, run, expected)
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
    return run.run_status, run.outcome_status, complete and capture_gaps == 0, gap_count + capture_gaps
