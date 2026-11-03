"""Bounded, read-only validation of existing sealed run exports."""

from __future__ import annotations

import gzip
import hashlib
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from shared.raes.trial_archive_jsonl import StructuredTraceReader

from shared.exceptions import ValidationError
from shared.raes.json_ingress import parse_bounded_json_object
from shared.schemas._raes_validation import _reject_secret_value

CHUNK_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024**3
MAX_EXPANDED_BYTES = 64 * 1024**3
MAX_MEMBERS = 20000
MAX_JSON_BYTES = 4 * 1024**2
MAX_METADATA_BYTES = 32 * 1024**2
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

    def __post_init__(self) -> None:
        for value in (self.experiment_id, self.plan_id, self.entry_id, self.run_id, self.attempt_id, self.run_version):
            if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
                raise TrialArchiveError("Invalid expected archive identity")
        for digest in (self.plan_digest, self.entry_digest):
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise TrialArchiveError("Expected archive digest is required")


@dataclass(frozen=True, slots=True)
class VerifiedTrialArchive:
    """Custody projections only; original scientific records stay in the archive."""

    member_count: int
    run_record_digest: str
    run_status: str
    outcome_status: str
    evidence_complete: bool
    gap_count: int


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


class _BoundedReader:
    """Bound expanded tar bytes and reject oversized extension-header reads."""

    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.total = 0

    def read(self, count: int) -> bytes:
        if count < 0 or count > CHUNK_BYTES:
            raise TrialArchiveError("Archive metadata exceeds its bound")
        raw = self.source.read(count)
        self.total += len(raw)
        if self.total > MAX_EXPANDED_BYTES:
            raise TrialArchiveError("Expanded archive exceeds its bound")
        return raw


class _BoundedTarInfo(tarfile.TarInfo):
    """Reject huge PAX/GNU metadata before tarfile allocates its body."""

    @classmethod
    def fromtarfile(cls, archive: tarfile.TarFile) -> _BoundedTarInfo:
        header = archive.fileobj.read(tarfile.BLOCKSIZE)
        if header == b"\0" * tarfile.BLOCKSIZE:
            archive.trial_end_marker = True
        member = cls.frombuf(header, archive.encoding, archive.errors)
        member.offset = archive.fileobj.tell() - tarfile.BLOCKSIZE
        return member._proc_member(archive)

    def _bound_extension(self, archive: tarfile.TarFile) -> None:
        total = getattr(archive, "trial_extension_bytes", 0) + self.size
        archive.trial_extension_bytes = total
        if self.size > CHUNK_BYTES or total > MAX_JSON_BYTES:
            raise TrialArchiveError("Archive metadata exceeds its bound")

    def _proc_pax(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
        self._bound_extension(archive)
        return super()._proc_pax(archive)

    def _proc_gnulong(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
        self._bound_extension(archive)
        return super()._proc_gnulong(archive)


def _read_member(
    source: BinaryIO, size: int, *, retain: bool, structured: StructuredTraceReader | None = None
) -> tuple[str, bytes]:
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
    if name.lower().endswith((".jsonl", ".ndjson")):
        return "jsonl"
    if name.lower().endswith((".yaml", ".yml")):
        return "yaml"
    return "json" if name.lower().endswith(".json") else "binary"


def _scan_format(name: str, formats: dict | None) -> str:
    if formats is not None:
        return formats[name]
    return "json" if name in {"manifest.json", "seal.json"} else "binary"


def _retain_document(name: str, size: int, kind: str, *, strict: bool) -> bool:
    document = kind in {"json", "yaml"} or name == "checksums.sha256"
    if document and size > MAX_JSON_BYTES:
        if strict or name in {"manifest.json", "seal.json", "checksums.sha256"}:
            raise TrialArchiveError("Archive structured document exceeds its record bound")
        return False
    return document


def _structured_reader(kind: str, expected: TrialArchiveIdentity, metadata_budget: int) -> StructuredTraceReader | None:
    from shared.raes.trial_archive_jsonl import StructuredTraceReader

    if kind != "jsonl":
        return None
    return StructuredTraceReader(
        expected, record_bound=MAX_JSON_BYTES, metadata_budget=metadata_budget, reference_budget=MAX_MEMBERS
    )


def _merge_structured(
    reader: StructuredTraceReader,
    documents: dict[str, bytes],
    references: dict[str, tuple[int | None, str]],
    attempts: set[str],
    index: int,
) -> None:
    for key, value in reader.records.items():
        documents[f":{index}:{key}"] = value
    for key, value in reader.references.items():
        if key in references and references[key] != value:
            raise TrialArchiveError("Conflicting structured trace references")
        references[key] = value
    attempts.update(reader.attempt_ids)
    if len(references) > MAX_MEMBERS or len(attempts) > MAX_MEMBERS:
        raise TrialArchiveError("Structured trace references exceed their bound")


def _verify_tar_end(archive: tarfile.TarFile) -> None:
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
    if index >= MAX_MEMBERS or member.size < 0 or member.size > MAX_EXPANDED_BYTES:
        raise TrialArchiveError("Archive exceeds its member bounds")
    name = safe_archive_path(member.name.rstrip("/") if member.isdir() else member.name)
    if name in names or name.split("/", 1)[0] != expected.run_id:
        raise TrialArchiveError("Duplicate or foreign archive member")
    names.add(name)
    return name


def _archive_body(archive: tarfile.TarFile, member: tarfile.TarInfo) -> BinaryIO:
    body = archive.extractfile(member)
    if body is None:
        raise TrialArchiveError("Archive member is unavailable")
    return body


def _scan(
    path: Path, expected: TrialArchiveIdentity, formats: dict | None = None
) -> tuple[dict, dict, dict, int, set[str]]:
    members, documents, names = {}, {}, set()
    trace_references = {}
    trace_attempts = set()
    trace_gaps = 0
    metadata_bytes = 0
    with path.open("rb") as compressed:
        magic = compressed.read(2)
        compressed.seek(0)
        source = gzip.GzipFile(fileobj=compressed) if magic == b"\x1f\x8b" else compressed
        try:
            bounded = _BoundedReader(source)
            with tarfile.open(fileobj=bounded, mode="r|", tarinfo=_BoundedTarInfo) as archive:
                for index, member in enumerate(archive):
                    name = _member_name(member, index, expected, names)
                    if member.isdir():
                        continue
                    if not member.isreg() or member.issparse() or "/" not in name:
                        raise TrialArchiveError("Archive member must be a regular file")
                    relative = name.split("/", 1)[1]
                    kind = _scan_format(relative, formats)
                    retain = _retain_document(relative, member.size, kind, strict=formats is not None)
                    if retain:
                        metadata_bytes += member.size
                        if metadata_bytes > MAX_METADATA_BYTES:
                            raise TrialArchiveError("Archive documents exceed their bound")
                    body = _archive_body(archive, member)
                    structured = _structured_reader(
                        kind if formats is not None else "binary", expected, MAX_METADATA_BYTES - metadata_bytes
                    )
                    with body:
                        checksum, raw = _read_member(body, member.size, retain=retain, structured=structured)
                    if structured is not None:
                        metadata_bytes += structured.metadata_bytes
                        trace_gaps += structured.disclosed_gaps
                        _merge_structured(structured, documents, trace_references, trace_attempts, index)
                    members[relative] = (member.size, checksum)
                    if retain:
                        documents[relative] = raw
                files = {f"{expected.run_id}/{key}" for key in members}
                if any(str(parent) in files for name in names for parent in PurePosixPath(name).parents):
                    raise TrialArchiveError("Archive file and directory collision")
                _verify_tar_end(archive)
        finally:
            if source is not compressed:
                source.close()
    return members, documents, trace_references, trace_gaps, trace_attempts


def _declared_formats(marker: dict, members: dict[str, tuple[int, str]]) -> dict[str, str]:
    formats = {name: _default_format(name) for name in members}
    jsonl_types = {"application/x-ndjson", "application/ndjson", "application/jsonl", "application/json-lines"}
    yaml_types = {"application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml"}
    record_roles = {"manifest", "evidence-record", "run-record", "admitted-plan", "cleanup-receipt"}
    for row in marker["inventory"]:
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
            formats[row["path"]] = "jsonl"
        elif media_type == "application/json" or media_type.endswith("+json"):
            formats[row["path"]] = "json"
        elif media_type in yaml_types or media_type.endswith("+yaml") or role in {"sdl", "hydrated-sdl"}:
            formats[row["path"]] = "yaml"
        elif role in record_roles:
            formats[row["path"]] = "json"
    return formats


def _json(raw: bytes) -> dict:
    return parse_bounded_json_object(raw, max_bytes=MAX_JSON_BYTES)


def _inventory(marker: dict, members: dict, documents: dict) -> dict:
    if marker.get("schema_version") != "aptl.run-seal/v1" or marker.get("seal_state") != "sealed":
        raise TrialArchiveError("Unsupported sealed archive")
    rows = marker.get("inventory")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_MEMBERS:
        raise TrialArchiveError("Invalid sealed inventory")
    declared = {}
    for row in rows:
        name = safe_archive_path(row["path"])
        checksum = row["checksum"]
        if (
            name in declared
            or name in {"seal.json", "checksums.sha256"}
            or type(row["size_bytes"]) is not int
            or row["size_bytes"] < 0
            or checksum["algorithm"] != "sha256"
            or not isinstance(checksum["value"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", checksum["value"])
        ):
            raise TrialArchiveError("Invalid sealed inventory entry")
        declared[name] = (row["size_bytes"], checksum["value"])
    actual = {name: identity for name, identity in members.items() if name not in {"seal.json", "checksums.sha256"}}
    if declared != actual or "manifest.json" not in declared:
        raise TrialArchiveError("Archive inventory is incomplete or corrupt")
    if "checksums.sha256" in members:
        checksums = {}
        for line in documents["checksums.sha256"].decode("utf-8").splitlines():
            checksum, name = line.split("  ", 1)
            if name in checksums:
                raise TrialArchiveError("Duplicate export checksum")
            checksums[safe_archive_path(name)] = checksum
        if checksums != {name: checksum for name, (_, checksum) in members.items() if name != "checksums.sha256"}:
            raise TrialArchiveError("Export checksums do not match the archive")
    return declared


def validate_trial_archive(path: Path, expected: TrialArchiveIdentity) -> VerifiedTrialArchive:
    """Validate all declared bytes before any destination upload is authorized."""
    from shared.raes.trial_archive_records import validate_archive_records

    try:
        if not 0 < path.stat().st_size <= MAX_ARCHIVE_BYTES:
            raise TrialArchiveError("Archive exceeds its compressed size bound")
        members, documents, _, _, _ = _scan(path, expected)
        marker = _json(documents["seal.json"])
        inventory = _inventory(marker, members, documents)
        formats = _declared_formats(marker, members)
        checked_members, documents, trace_references, trace_gaps, trace_attempts = _scan(path, expected, formats)
        if checked_members != members:
            raise TrialArchiveError("Archive bytes changed during validation")
        for name, (size, digest) in trace_references.items():
            if (
                name not in inventory
                or inventory[name][1] != digest
                or (size is not None and inventory[name][0] != size)
            ):
                raise TrialArchiveError("Structured trace references missing or corrupt bytes")
        run_digest = "sha256:" + members["manifest.json"][1]
        if marker.get("run_record_digest") != run_digest:
            raise TrialArchiveError("Sealed manifest digest does not match")
        facts = validate_archive_records(
            documents, inventory, marker, expected, trace_attempts=trace_attempts, formats=formats
        )
        if trace_gaps:
            facts = (facts[0], facts[1], False, max(facts[3], trace_gaps))
        return VerifiedTrialArchive(len(members), run_digest, *facts)
    except TrialArchiveError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OSError, EOFError, tarfile.TarError):
        raise TrialArchiveError("Archive structure or record validation failed") from None
