"""Bounded, read-only validation of existing sealed run exports."""

from __future__ import annotations

import gzip
import hashlib
import re
import tarfile
from collections.abc import Buffer
from contextlib import ExitStack
from dataclasses import dataclass, field
from io import BufferedIOBase, BufferedReader, RawIOBase
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from shared.raes.trial_archive_jsonl import StructuredTraceReader

from shared.exceptions import ValidationError
from shared.raes.json_ingress import parse_bounded_json_object
from shared.schemas._raes_validation import JsonObject, _reject_secret_value

CHUNK_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024**3
MAX_EXPANDED_BYTES = 64 * 1024**3
MAX_MEMBERS = 20000
MAX_JSON_BYTES = 4 * 1024**2
MAX_METADATA_BYTES = 32 * 1024**2
MANIFEST_NAME = "manifest.json"
SEAL_NAME = "seal.json"
CHECKSUMS_NAME = "checksums.sha256"
_INVALID_INVENTORY_ENTRY = "Invalid sealed inventory entry"
_SAFE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}\Z")


class TrialArchiveError(ValidationError):
    """Archive bytes cannot support a collection receipt."""


@dataclass(frozen=True, slots=True)
class TrialArchiveIdentity:
    """Independently expected identifiers, never derived from submitted bytes."""

    experiment_id: str
    plan_id: str
    entry_id: str
    run_id: str
    attempt_id: str
    plan_digest: str
    entry_digest: str
    run_version: str
    #: The exact trial SDL digest; required for a LilRAE trial seal, absent otherwise.
    scenario_sha256: str = ""

    def __post_init__(self) -> None:
        """Require bounded expected identifiers and explicit admission digests."""
        for value in (self.experiment_id, self.plan_id, self.entry_id, self.run_id, self.attempt_id, self.run_version):
            if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
                raise TrialArchiveError("Invalid expected archive identity")
        for digest in (self.plan_digest, self.entry_digest):
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise TrialArchiveError("Expected archive digest is required")
        if self.scenario_sha256 and not re.fullmatch(r"sha256:[a-f0-9]{64}", self.scenario_sha256):
            raise TrialArchiveError("Expected scenario digest is invalid")

    def as_record(self) -> dict[str, str]:
        """Return the stored identity; an absent scenario digest keeps earlier records unchanged."""
        record = {name: getattr(self, name) for name in self.__slots__}
        if not self.scenario_sha256:
            del record["scenario_sha256"]
        return record


@dataclass(frozen=True, slots=True)
class VerifiedTrialArchive:
    """Custody projections only; original scientific records stay in the archive."""

    member_count: int
    run_record_digest: str
    run_status: str
    outcome_status: str
    evidence_complete: bool
    gap_count: int
    plan_metadata: JsonObject | None = None


def safe_archive_path(value: object) -> str:
    """Reject aliases before using a name as an inventory key."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise TrialArchiveError("Unsafe archive path")
    return value


class _BoundedReader(RawIOBase):
    """Bound expanded tar bytes and reject oversized extension-header reads."""

    def __init__(self, source: BufferedIOBase) -> None:
        """Initialize invocation-local streaming limits and bounded indexes."""
        self.source = source
        self.total = 0

    def read(self, count: int = -1) -> bytes:
        """Bound each read and the aggregate expanded archive stream."""
        if count < 0 or count > CHUNK_BYTES:
            raise TrialArchiveError("Archive metadata exceeds its bound")
        raw = self.source.read(count)
        self.total += len(raw)
        if self.total > MAX_EXPANDED_BYTES:
            raise TrialArchiveError("Expanded archive exceeds its bound")
        return raw

    def readable(self) -> bool:
        """Expose the standard read-only raw stream capability."""
        return True

    def readinto(self, buffer: Buffer) -> int:
        """Fill a standard buffered-reader request through the same byte limits."""
        view = memoryview(buffer).cast("B")
        raw = self.read(len(view))
        view[: len(raw)] = raw
        return len(raw)


class _BoundedTarFile(tarfile.TarFile):
    """Keep validation state on the archive that owns the parsing hooks."""

    trial_end_marker = False
    trial_extension_bytes = 0


class _BoundedTarInfo(tarfile.TarInfo):
    """Reject huge PAX/GNU metadata before tarfile allocates its body."""

    @classmethod
    def fromtarfile(cls, archive: tarfile.TarFile) -> _BoundedTarInfo:
        """Observe the end marker before invoking the standard tar member parser."""
        header = archive.fileobj.read(tarfile.BLOCKSIZE)
        if header == b"\0" * tarfile.BLOCKSIZE:
            cast(_BoundedTarFile, archive).trial_end_marker = True
        member = cls.frombuf(header, archive.encoding, archive.errors)
        member.offset = archive.fileobj.tell() - tarfile.BLOCKSIZE
        # CPython parser hook is absent from typeshed.
        return member._proc_member(archive)  # type: ignore[attr-defined]

    def _bound_extension(self, archive: tarfile.TarFile) -> None:
        """Reject oversized extension metadata before the standard parser allocates it."""
        total = getattr(archive, "trial_extension_bytes", 0) + self.size
        cast(_BoundedTarFile, archive).trial_extension_bytes = total
        if self.size > CHUNK_BYTES or total > MAX_JSON_BYTES:
            raise TrialArchiveError("Archive metadata exceeds its bound")

    def _proc_pax(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
        """Apply metadata bounds before the standard PAX parser reads its body."""
        self._bound_extension(archive)
        return super()._proc_pax(archive)  # type: ignore[misc]  # CPython parser hook is absent from typeshed.

    def _proc_gnulong(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
        """Apply metadata bounds before the standard GNU name parser reads its body."""
        self._bound_extension(archive)
        return super()._proc_gnulong(archive)  # type: ignore[misc]  # CPython parser hook is absent from typeshed.


def _read_member(
    source: IO[bytes], size: int, *, retain: bool, structured: StructuredTraceReader | None = None
) -> tuple[str, bytes]:
    """Hash streamed artifact bytes while checking credentials and bounded metadata."""
    digest = hashlib.sha256()
    retained = bytearray()
    tail = b""
    remaining = size
    while remaining:
        chunk = source.read(min(CHUNK_BYTES, remaining))
        if not chunk:
            raise TrialArchiveError("Truncated archive member")
        remaining -= len(chunk)
        digest.update(chunk)
        # Use the existing high-confidence credential-value rules, not the
        # sidecar field allowlist that intentionally excludes full traces.
        _reject_secret_value("archive", (tail + chunk).decode("latin1"), error_cls=TrialArchiveError)
        tail = chunk[-256:]
        if structured is not None:
            structured.feed(chunk)
        if retain:
            retained.extend(chunk)
    if structured is not None:
        structured.finish()
    return digest.hexdigest(), bytes(retained)


def _default_format(name: str) -> str:
    """Choose conservative structured parsing from a member extension."""
    if name.lower().endswith((".jsonl", ".ndjson")):
        return "jsonl"
    if name.lower().endswith((".yaml", ".yml")):
        return "yaml"
    return "json" if name.lower().endswith(".json") else "binary"


def _scan_format(name: str, formats: dict[str, str] | None) -> str:
    """Select inventory declarations after the initial containment scan."""
    if formats is not None:
        return formats[name]
    return "json" if name in {MANIFEST_NAME, SEAL_NAME} else "binary"


def _retain_document(name: str, size: int, kind: str, *, strict: bool) -> bool:
    """Enforce the per-document metadata bound before reading its body."""
    document = kind in {"json", "yaml"} or name == CHECKSUMS_NAME
    if document and size > MAX_JSON_BYTES:
        if strict or name in {MANIFEST_NAME, SEAL_NAME, CHECKSUMS_NAME}:
            raise TrialArchiveError("Archive structured document exceeds its record bound")
        return False
    return document


def _structured_reader(
    kind: str, expected: TrialArchiveIdentity, metadata_budget: int, retain_usage: bool = False
) -> StructuredTraceReader | None:
    """Create an incremental reader only for declared JSON Lines streams."""
    from shared.raes.trial_archive_jsonl import StructuredTraceReader

    if kind != "jsonl":
        return None
    return StructuredTraceReader(
        expected,
        record_bound=MAX_JSON_BYTES,
        metadata_budget=metadata_budget,
        reference_budget=MAX_MEMBERS,
        retain_usage=retain_usage,
    )


def _merge_structured(
    reader: StructuredTraceReader,
    documents: dict[str, bytes],
    references: dict[str, tuple[int | None, str]],
    attempts: set[str],
    index: str,
) -> None:
    """Merge bounded trace indexes without retaining complete trace bodies."""
    for key, value in reader.records.items():
        documents[f":{index}:{key}"] = value
    for key, reference in reader.references.items():
        if key in references and references[key] != reference:
            raise TrialArchiveError("Conflicting structured trace references")
        references[key] = reference
    attempts.update(reader.attempt_ids)
    if len(references) > MAX_MEMBERS or len(attempts) > MAX_MEMBERS:
        raise TrialArchiveError("Structured trace references exceed their bound")


def _verify_tar_end(archive: tarfile.TarFile) -> None:
    """Require both tar end blocks and drain gzip integrity checks."""
    if (
        not getattr(archive, "trial_end_marker", False)
        or archive.fileobj.read(tarfile.BLOCKSIZE) != b"\0" * tarfile.BLOCKSIZE
    ):
        raise TrialArchiveError("Truncated archive end marker")
    # Drain the decompressor so truncation and gzip CRC failures
    # after the tar end marker cannot pass unnoticed.
    while tail := archive.fileobj.read(CHUNK_BYTES):
        if any(tail):
            raise TrialArchiveError("Unexpected bytes after the archive")


def _member_name(member: tarfile.TarInfo, index: int, expected: TrialArchiveIdentity, names: set[str]) -> str:
    """Reject oversized, duplicate, unsafe, and foreign member paths."""
    if index >= MAX_MEMBERS or member.size < 0 or member.size > MAX_EXPANDED_BYTES:
        raise TrialArchiveError("Archive exceeds its member bounds")
    name = safe_archive_path(member.name.rstrip("/") if member.isdir() else member.name)
    if name in names or name.split("/", 1)[0] != expected.run_id:
        raise TrialArchiveError("Duplicate or foreign archive member")
    names.add(name)
    return name


def _archive_body(archive: tarfile.TarFile, member: tarfile.TarInfo) -> IO[bytes]:
    """Require an available regular member stream from the tar reader."""
    body = archive.extractfile(member)
    if body is None:
        raise TrialArchiveError("Archive member is unavailable")
    return body


@dataclass
class _ScanState:
    """Accumulate bounded indexes for one pass, without retaining artifact bodies."""

    members: dict[str, tuple[int, str]] = field(default_factory=dict)
    documents: dict[str, bytes] = field(default_factory=dict)
    names: set[str] = field(default_factory=set)
    references: dict[str, tuple[int | None, str]] = field(default_factory=dict)
    attempts: set[str] = field(default_factory=set)
    gaps: int = 0
    metadata_bytes: int = 0
    retain_usage: bool = False


def _consume_member(
    state: _ScanState,
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    index: int,
    expected: TrialArchiveIdentity,
    formats: dict[str, str] | None,
) -> None:
    """Hash one safe member and merge only its bounded structured indexes."""
    name = _member_name(member, index, expected, state.names)
    if member.isdir():
        return
    if not member.isreg() or member.issparse() or "/" not in name:
        raise TrialArchiveError("Archive member must be a regular file")
    relative = name.split("/", 1)[1]
    kind = _scan_format(relative, formats)
    retain = _retain_document(relative, member.size, kind, strict=formats is not None)
    if retain:
        state.metadata_bytes += member.size
        if state.metadata_bytes > MAX_METADATA_BYTES:
            raise TrialArchiveError("Archive documents exceed their bound")
    structured = _structured_reader(kind, expected, MAX_METADATA_BYTES - state.metadata_bytes, state.retain_usage)
    with _archive_body(archive, member) as body:
        checksum, raw = _read_member(body, member.size, retain=retain, structured=structured)
    if structured is not None:
        state.metadata_bytes += structured.metadata_bytes
        state.gaps += structured.disclosed_gaps
        _merge_structured(structured, state.documents, state.references, state.attempts, relative)
    state.members[relative] = (member.size, checksum)
    if retain:
        state.documents[relative] = raw


def _scan(
    path: Path, expected: TrialArchiveIdentity, formats: dict[str, str] | None = None, *, retain_usage: bool = False
) -> tuple[dict[str, tuple[int, str]], dict[str, bytes], dict[str, tuple[int | None, str]], int, set[str]]:
    """Stream one archive pass and verify its complete tar termination."""
    state = _ScanState(retain_usage=retain_usage)
    with ExitStack() as stack:
        compressed = stack.enter_context(path.open("rb"))
        magic = compressed.read(2)
        compressed.seek(0)
        source = stack.enter_context(gzip.GzipFile(fileobj=compressed)) if magic == b"\x1f\x8b" else compressed
        bounded = stack.enter_context(BufferedReader(_BoundedReader(source), buffer_size=tarfile.RECORDSIZE))
        archive = stack.enter_context(_BoundedTarFile.open(fileobj=bounded, mode="r|", tarinfo=_BoundedTarInfo))
        for index, member in enumerate(archive):
            _consume_member(state, archive, member, index, expected, formats)
        files = {f"{expected.run_id}/{key}" for key in state.members}
        if any(str(parent) in files for name in state.names for parent in PurePosixPath(name).parents):
            raise TrialArchiveError("Archive file and directory collision")
        _verify_tar_end(archive)
    return state.members, state.documents, state.references, state.gaps, state.attempts


def _declared_formats(marker: JsonObject, members: dict[str, tuple[int, str]]) -> dict[str, str]:
    """Select declared media semantics with conservative extension fallbacks."""
    formats = {name: _default_format(name) for name in members}
    jsonl_types = {"application/x-ndjson", "application/ndjson", "application/jsonl", "application/json-lines"}
    yaml_types = {"application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml"}
    record_roles = {"manifest", "evidence-record", "run-record", "admitted-plan", "cleanup-receipt"}
    for row in _sealed_rows(marker):
        media_type, role = row["media_type"], row["role"]
        if (
            not isinstance(media_type, str)
            or not 0 < len(media_type) <= 128
            or not isinstance(role, str)
            or not 0 < len(role) <= 128
        ):
            raise TrialArchiveError("Invalid archive format declaration")
        media_type = media_type.partition(";")[0].strip().lower()
        if media_type in jsonl_types:
            formats[safe_archive_path(row["path"])] = "jsonl"
        elif media_type == "application/json" or media_type.endswith("+json"):
            formats[safe_archive_path(row["path"])] = "json"
        elif media_type in yaml_types or media_type.endswith("+yaml") or role in {"sdl", "hydrated-sdl"}:
            formats[safe_archive_path(row["path"])] = "yaml"
        elif role in record_roles:
            formats[safe_archive_path(row["path"])] = "json"
    return formats


def _json(raw: bytes) -> JsonObject:
    """Parse a bounded JSON object with the existing strict ingress rules."""
    return parse_bounded_json_object(raw, max_bytes=MAX_JSON_BYTES)


def _sealed_rows(marker: JsonObject) -> list[JsonObject]:
    """Require a bounded list of inventory objects before inspecting entries."""
    rows = marker.get("inventory")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_MEMBERS:
        raise TrialArchiveError("Invalid sealed inventory")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise TrialArchiveError(_INVALID_INVENTORY_ENTRY)
        result.append(row)
    return result


def _inventory_entry(row: JsonObject) -> tuple[str, tuple[int, str]]:
    """Validate one byte identity using the producer's existing inventory fields."""
    name = safe_archive_path(row["path"])
    size, checksum = row["size_bytes"], row["checksum"]
    if type(size) is not int or size < 0 or not isinstance(checksum, dict):
        raise TrialArchiveError(_INVALID_INVENTORY_ENTRY)
    digest = checksum["value"]
    if checksum["algorithm"] != "sha256" or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise TrialArchiveError(_INVALID_INVENTORY_ENTRY)
    return name, (size, digest)


def _verify_export_checksums(members: dict[str, tuple[int, str]], documents: dict[str, bytes]) -> None:
    """Join the optional standard checksum document to every exported file."""
    if CHECKSUMS_NAME not in members:
        return
    checksums = {}
    for line in documents[CHECKSUMS_NAME].decode("utf-8").splitlines():
        checksum, name = line.split("  ", 1)
        if name in checksums:
            raise TrialArchiveError("Duplicate export checksum")
        checksums[safe_archive_path(name)] = checksum
    if checksums != {name: checksum for name, (_, checksum) in members.items() if name != CHECKSUMS_NAME}:
        raise TrialArchiveError("Export checksums do not match the archive")


def _inventory(
    marker: JsonObject, members: dict[str, tuple[int, str]], documents: dict[str, bytes]
) -> dict[str, tuple[int, str]]:
    """Require a closed, exact inventory before any structured record joins."""
    if marker.get("schema_version") != "aptl.run-seal/v1" or marker.get("seal_state") != "sealed":
        raise TrialArchiveError("Unsupported sealed archive")
    declared = {}
    for row in _sealed_rows(marker):
        name, identity = _inventory_entry(row)
        if name in declared or name in {SEAL_NAME, CHECKSUMS_NAME}:
            raise TrialArchiveError(_INVALID_INVENTORY_ENTRY)
        declared[name] = identity
    actual = {name: identity for name, identity in members.items() if name not in {SEAL_NAME, CHECKSUMS_NAME}}
    if declared != actual or MANIFEST_NAME not in declared:
        raise TrialArchiveError("Archive inventory is incomplete or corrupt")
    _verify_export_checksums(members, documents)
    return declared


def _validated_archive(
    path: Path, expected: TrialArchiveIdentity, *, retain_usage: bool = False
) -> tuple[VerifiedTrialArchive, dict[str, bytes], dict[str, tuple[int, str]], JsonObject, dict[str, str]]:
    """Validate all declared bytes before any destination upload is authorized."""
    from shared.raes.trial_archive_records import validate_archive_records

    try:
        if not 0 < path.stat().st_size <= MAX_ARCHIVE_BYTES:
            raise TrialArchiveError("Archive exceeds its compressed size bound")
        members, documents, _, _, _ = _scan(path, expected)
        marker = _json(documents[SEAL_NAME])
        inventory = _inventory(marker, members, documents)
        formats = _declared_formats(marker, members)
        checked_members, documents, trace_references, trace_gaps, trace_attempts = _scan(
            path, expected, formats, retain_usage=retain_usage
        )
        if checked_members != members:
            raise TrialArchiveError("Archive bytes changed during validation")
        for name, (size, digest) in trace_references.items():
            if (
                name not in inventory
                or inventory[name][1] != digest
                or (size is not None and inventory[name][0] != size)
            ):
                raise TrialArchiveError("Structured trace references missing or corrupt bytes")
        run_digest = "sha256:" + members[MANIFEST_NAME][1]
        if marker.get("run_record_digest") != run_digest:
            raise TrialArchiveError("Sealed manifest digest does not match")
        facts = validate_archive_records(
            documents, inventory, marker, expected, trace_attempts=trace_attempts, formats=formats
        )
        if trace_gaps:
            facts = (facts[0], facts[1], False, max(facts[3], trace_gaps), facts[4])
        return VerifiedTrialArchive(len(members), run_digest, *facts), documents, members, marker, formats
    except TrialArchiveError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OSError, EOFError, tarfile.TarError):
        raise TrialArchiveError("Archive structure or record validation failed") from None


def validate_trial_archive(path: Path, expected: TrialArchiveIdentity) -> VerifiedTrialArchive:
    """Validate all original bytes without retaining export-only usage metadata."""
    return _validated_archive(path, expected)[0]
