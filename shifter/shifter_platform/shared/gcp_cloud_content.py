"""Closed encrypted transport for native secret Content, independent of RAES and Django."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from typing import Annotated, Any

from pydantic import Field
from shifter_adapter_sdk.runtime import ClosedModel, Digest, canonical_digest, decode_message


class CloudContentEnvelope(ClosedModel):
    """Only sealed bytes ride the immutable operation input."""

    plan_digest: Digest
    content_digest: Digest
    ciphertext: Annotated[str, Field(min_length=8, max_length=1_048_576, pattern=r"^enc:v1:")] = Field(repr=False)


def encode_cloud_content(contents: Mapping[str, bytes]) -> dict[str, str]:
    """Secret Manager accepts at most 64 KiB per version; bound total input too."""
    if len(contents) > 1024 or sum(len(value) for value in contents.values()) > 524288:
        raise ValueError("Cloud content exceeds its size limit")
    result = {}
    for ref, material in contents.items():
        if not isinstance(ref, str) or not ref.startswith("content.") or not 0 < len(material) <= 65536:
            raise ValueError("Cloud content is unavailable")
        result[ref] = base64.b64encode(material).decode("ascii")
    return result


def open_cloud_content(
    envelope: CloudContentEnvelope | None, plan: Mapping[str, Any], decrypt: Callable[[str], str]
) -> dict[str, bytes]:
    """An authenticated ciphertext still belongs to exactly one original plan."""
    if envelope is None:
        return {}
    try:
        if envelope.plan_digest != canonical_digest(plan):
            raise ValueError()
        raw = decode_message(decrypt(envelope.ciphertext), limit=1_048_576)
        if not isinstance(raw, dict) or canonical_digest(raw) != envelope.content_digest:
            raise ValueError()
        contents = {key: base64.b64decode(value, validate=True) for key, value in raw.items()}
        if encode_cloud_content(contents) != raw:
            raise ValueError()
        return contents
    except Exception:  # noqa: BLE001  # encrypted payload and decoder diagnostics must stay private
        raise ValueError("Cloud content is unavailable") from None
