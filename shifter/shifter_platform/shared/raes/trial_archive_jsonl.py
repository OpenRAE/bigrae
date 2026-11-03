"""Incremental JSON Lines checks; retain bounded scientific metadata only."""

from __future__ import annotations

from shared.raes.trial_archive import TrialArchiveError, TrialArchiveIdentity
from shared.raes.trial_archive_records import _artifact_path, _walk, validate_structured_bindings
from shared.schemas._raes_validation import JsonObject

_SCIENTIFIC_RECORDS = {
    "experiment-run/v1",
    "experiment-evidence-record/v1",
    "admitted-trial-plan/v1",
    "trial-cleanup-receipt/v1",
    "experiment-capture-spec/v1",
}


class StructuredTraceReader:
    """Validate each line while indexing only bounded joins and record documents."""

    def __init__(
        self, expected: TrialArchiveIdentity, *, record_bound: int, metadata_budget: int, reference_budget: int
    ) -> None:
        """Initialize invocation-local streaming limits and bounded indexes."""
        self.expected = expected
        self.record_bound = record_bound
        self.metadata_budget = metadata_budget
        self.reference_budget = reference_budget
        self.pending = b""
        self.records: dict[str, bytes] = {}
        self.references: dict[str, tuple[int | None, str]] = {}
        self.attempt_ids: set[str] = set()
        self.metadata_bytes = 0
        self.lines = 0
        self.disclosed_gaps = 0

    def feed(self, chunk: bytes) -> None:
        """Validate complete lines and bound the pending record."""
        lines = (self.pending + chunk).split(b"\n")
        self.pending = lines.pop()
        if len(self.pending) > self.record_bound:
            raise TrialArchiveError("Structured trace line exceeds its bound")
        for line in lines:
            self._line(line)

    def finish(self) -> None:
        """Validate a final record without a trailing newline."""
        if self.pending:
            self._line(self.pending)
        self.pending = b""

    def _line(self, raw: bytes) -> None:
        """Validate a complete trace object and index its original scientific records."""
        from shared.raes.trial_archive import _json

        self.lines += 1
        if self.lines > 1000000 or len(raw) > self.record_bound:
            raise TrialArchiveError("Structured trace exceeds its line bounds")
        if not raw.strip():
            raise TrialArchiveError("Structured trace contains a blank JSON line")
        payload = _json(raw)
        self.attempt_ids.update(validate_structured_bindings(payload, self.expected))
        if len(self.attempt_ids) > self.reference_budget:
            raise TrialArchiveError("Structured trace attempt identities exceed their bound")
        scientific = False
        for value in _walk(payload):
            scientific = self._index_record(value) or scientific
        if scientific:
            self._retain_scientific(raw)

    def _index_record(self, value: JsonObject) -> bool:
        """Index every declared byte reference and original loss disclosure."""
        self.disclosed_gaps += bool(value.get("loss_disclosure"))
        uri = value.get("uri") or value.get("content_uri")
        checksum = value.get("checksum") or value.get("content_checksum")
        if uri and checksum is not None:
            self._reference(uri, checksum, value.get("size_bytes"))
        return value.get("schema_version") in _SCIENTIFIC_RECORDS

    def _retain_scientific(self, raw: bytes) -> None:
        """Retain one containing line within the shared scientific metadata budget."""
        self.metadata_bytes += len(raw)
        if self.metadata_bytes > self.metadata_budget:
            raise TrialArchiveError("Scientific trace records exceed the metadata bound")
        self.records[f"{self.lines}.json"] = raw
        if len(self.records) > self.reference_budget:
            raise TrialArchiveError("Scientific trace records exceed their count bound")

    def _reference(self, uri: object, checksum: object, size: object) -> None:
        """Retain one bounded, internally resolvable trace byte identity."""
        if size is not None and (type(size) is not int or size < 0):
            raise TrialArchiveError("Invalid structured trace byte size")
        if not isinstance(uri, str):
            raise TrialArchiveError("Invalid structured trace byte URI")
        path = _artifact_path(uri, self.expected.run_id)
        digest = _trace_checksum(checksum)
        identity = (size, digest)
        if path in self.references and self.references[path] != identity:
            raise TrialArchiveError("Conflicting structured trace byte references")
        self.references[path] = identity
        if len(self.references) > self.reference_budget:
            raise TrialArchiveError("Structured trace references exceed their bound")


def _trace_checksum(checksum: object) -> str:
    """Require the declared SHA-256 identity before retaining a trace reference."""
    if not isinstance(checksum, dict) or checksum.get("algorithm") != "sha256":
        raise TrialArchiveError("Invalid structured trace checksum")
    digest = checksum.get("value")
    if not isinstance(digest, str) or len(digest) != 64:
        raise TrialArchiveError("Invalid structured trace checksum")
    return digest
