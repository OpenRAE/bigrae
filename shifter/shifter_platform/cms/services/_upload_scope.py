"""Canonical upload namespace, purpose and metadata admission."""

from dataclasses import dataclass
from typing import Literal

from django.conf import settings

from cms.exceptions import CMSError
from cms.models import AgentType
from shared.audit import AuditEntityType
from shared.identity_scope import ResourceScope
from shared.operation_envelope import canonical_payload_digest

from ._content_authority import content_scope_fields


@dataclass(frozen=True, slots=True)
class UploadOptions:
    """Host-selected asset purpose; the signed admission retains its destination."""

    kind: Literal["agent", "file"] = "agent"
    replaces: int | None = None


def upload_entity(kind: str) -> AuditEntityType:
    """Keep file events distinct from installer events without exposing material."""
    return AuditEntityType.FILE_ASSET if kind == "file" else AuditEntityType.AGENT


def bounded_upload_label(value: object, maximum: int) -> None:
    """Reject blank, oversized or control-bearing upload metadata."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise CMSError("Invalid upload metadata")


def validated_installer_metadata(name: str, filename: str, file_size: int, agent_type: str) -> str:
    """Preserve installer format, operating-system and live size policy."""
    from cms.assets.validation import ValidationError as AssetValidationError
    from cms.assets.validation import enforce_max_file_size_bytes, validate_file_extension

    bounded_upload_label(name, 100)
    bounded_upload_label(filename, 255)
    if type(file_size) is not int or file_size <= 0 or agent_type not in AgentType.values:
        raise CMSError("Invalid upload metadata")
    try:
        enforce_max_file_size_bytes(file_size)
        file_format = validate_file_extension(filename)
    except (ValueError, AssetValidationError):
        raise CMSError("Invalid upload metadata") from None
    if file_format.os_slug is None or not settings.AWS_S3_BUCKET_NAME:
        raise CMSError("Upload unavailable")
    return file_format.os_slug


def _scope_digest(scope: ResourceScope) -> str:
    """Derive the storage budget identity from resolved content ancestry."""
    return canonical_payload_digest(
        {name: str(value) if value is not None else None for name, value in content_scope_fields(scope).items()}
    )
