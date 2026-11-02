"""Byte-free file selections and a composition-bound CMS material provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated
from uuid import UUID

from pydantic import Field
from shifter_adapter_sdk.runtime import FileInput


class RuntimeFileBinding(FileInput):
    """Exact CMS-owned version admitted beside one immutable operation."""

    asset_uuid: UUID
    version_id: Annotated[int, Field(strict=True, gt=0)]


FileInputProvider = Callable[[UUID, Mapping[str, RuntimeFileBinding]], Mapping[str, bytes]]
_provider: FileInputProvider | None = None


def bind_file_input_provider(provider: FileInputProvider) -> None:
    """Bind the owning CMS service once at composition startup."""
    global _provider
    if not callable(provider) or (_provider is not None and _provider is not provider):
        raise ValueError("File input provider is unavailable or already bound")
    _provider = provider


def load_file_input_material(request_id: UUID, bindings: Mapping[str, RuntimeFileBinding]) -> dict[str, bytes]:
    """Require the owner to reauthorize and return only exact declared bytes."""
    if not bindings:
        return {}
    if _provider is None or not isinstance(request_id, UUID) or not request_id.int:
        raise ValueError("File input material is unavailable")
    expected = {name: RuntimeFileBinding.model_validate(binding) for name, binding in bindings.items()}
    try:
        material = _provider(request_id, dict(expected))
        if not isinstance(material, Mapping) or len(material) != len(expected) or set(material) != set(expected):
            raise ValueError("File input material changed")
        for name, binding in expected.items():
            binding.verify_material(material[name])
        return dict(material)
    except Exception:  # noqa: BLE001  # provider causes may contain private storage and file diagnostics
        raise ValueError("File input material is unavailable") from None
