"""Retain referenced native root Content before native compilation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from raes.content import Content
from raes.scenario import InstantiatedScenario
from shifter_adapter_sdk.runtime import canonical_digest

from shared.gcp_cloud_content import CloudContentEnvelope, encode_cloud_content
from shared.raes.content_delivery import DeliveryProjection
from shared.raes.pack_delivery_inputs import InventoryEntry

type _PackInputCache = tuple[dict[str, InventoryEntry], DeliveryProjection]


def referenced_cloud_content(scenario: InstantiatedScenario) -> dict[str, dict[str, Any]]:
    """Native references resolve exactly; no filename, URI or substring inference."""
    references = {
        version.payload_content_ref
        for node in scenario.nodes.values()
        if node.runtime is not None
        for application in node.runtime.platform_applications
        for secret in application.secrets
        for version in secret.versions
        if version.payload_content_ref
    }
    declarations = {f"content.{name}": value for name, value in scenario.content.items()}
    if not references <= declarations.keys():
        raise ValueError("Cloud content reference is unresolved")
    return {ref: declarations[ref].model_dump(mode="json") for ref in sorted(references)}


def prepare_cloud_content(
    declarations: dict[str, dict[str, Any]] | None, plan: dict[str, Any], pack_root: Path | None
) -> CloudContentEnvelope | None:
    """Reuse pack containment/inventory/materialization and the existing field key."""
    if not declarations:
        return None
    from shared.field_encryption import encrypt_value

    contents = {}
    cache = None
    for ref, value in declarations.items():
        content = Content.model_validate(value)
        _validate_content_type(content)
        material, cache = _content_bytes(content, pack_root, cache)
        contents[ref] = material
    encoded = encode_cloud_content(contents)
    return CloudContentEnvelope(
        plan_digest=canonical_digest(plan),
        content_digest=canonical_digest(encoded),
        ciphertext=encrypt_value(json.dumps(encoded, sort_keys=True)),
    )


def _validate_content_type(content: Content) -> None:
    """Only literal file content or an inventoried source can supply secret bytes."""
    if content.type != "file" or content.text_from is not None or content.service_materialization is not None:
        raise ValueError("Cloud content materialization is unsupported")


def _content_bytes(
    content: Content, pack_root: Path | None, cache: _PackInputCache | None
) -> tuple[bytes, _PackInputCache | None]:
    """Verify a source once per preparation while preserving exact inline UTF-8 bytes."""
    from shared.raes.content_payload import payload_chunks
    from shared.raes.pack_delivery_inputs import (
        build_inventory_index,
        load_pack_projection,
        resolve_pack_input,
        verify_input_against_inventory,
        verify_projection_against_inventory,
    )

    if content.text is not None and content.source is None:
        return content.text.encode("utf-8"), cache
    if content.source is None or content.text is not None or pack_root is None:
        raise ValueError("Cloud content payload has not been prepared")
    if cache is None:
        cache = build_inventory_index(pack_root), load_pack_projection(pack_root)
        verify_projection_against_inventory(pack_root, cache[0])
    inventory, projection = cache
    entry = projection.resolve(
        source_name=content.source.name,
        source_version=content.source.version,
        content_type="file",
        content_format=content.format,
    )
    path = resolve_pack_input(pack_root, entry.input_path)
    verify_input_against_inventory(pack_root, path, "file", inventory)
    if path.stat().st_size > 65536:
        raise ValueError("Cloud content exceeds its size limit")
    material = b"".join(payload_chunks(content_type="file", content_format=entry.content_format, source_path=path))
    return material, cache
