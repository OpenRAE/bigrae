"""Retain referenced native root Content before native compilation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from raes.content import Content
from raes.scenario import InstantiatedScenario
from shifter_adapter_sdk.runtime import canonical_digest

from shared.gcp_cloud_content import CloudContentEnvelope, encode_cloud_content


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
    declarations: dict[str, dict[str, Any]], plan: dict[str, Any], pack_root: Path | None
) -> CloudContentEnvelope | None:
    """Reuse pack containment/inventory/materialization and the existing field key."""
    if not declarations:
        return None
    from shared.field_encryption import encrypt_value
    from shared.raes.content_payload import payload_chunks
    from shared.raes.pack_delivery_inputs import (
        build_inventory_index,
        load_pack_projection,
        resolve_pack_input,
        verify_input_against_inventory,
        verify_projection_against_inventory,
    )

    contents = {}
    projection = inventory = None
    for ref, value in declarations.items():
        content = Content.model_validate(value)
        if content.type != "file" or content.text_from is not None or content.service_materialization is not None:
            raise ValueError("Cloud content materialization is unsupported")
        if content.text is not None and content.source is None:
            material = content.text.encode("utf-8")
        elif content.source is not None and content.text is None and pack_root is not None:
            if projection is None:
                inventory, projection = build_inventory_index(pack_root), load_pack_projection(pack_root)
                verify_projection_against_inventory(pack_root, inventory)
            if inventory is None:
                raise ValueError("Cloud content inventory is unavailable")
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
            material = b"".join(
                payload_chunks(content_type="file", content_format=entry.content_format, source_path=path)
            )
        else:
            raise ValueError("Cloud content payload has not been prepared")
        contents[ref] = material
    encoded = encode_cloud_content(contents)
    return CloudContentEnvelope(
        plan_digest=canonical_digest(plan),
        content_digest=canonical_digest(encoded),
        ciphertext=encrypt_value(json.dumps(encoded, sort_keys=True)),
    )
