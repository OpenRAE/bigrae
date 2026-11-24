"""RAES range creation, bindings, image registry, evidence and status projection.

The ``engine.services`` facade re-exports these names. Engine modules import
dependencies from the owning leaf module, not from this package.
"""

from __future__ import annotations

from .evidence import record_raes_operation_status as record_raes_operation_status
from .evidence import record_raes_runtime_snapshot as record_raes_runtime_snapshot
from .image import RaesImageMappingError as RaesImageMappingError
from .image import RaesImageMappingOptions as RaesImageMappingOptions
from .image import RaesImageMappingView as RaesImageMappingView
from .image import disable_raes_image_mapping as disable_raes_image_mapping
from .image import list_backend_artifacts as list_backend_artifacts
from .image import list_raes_image_mappings as list_raes_image_mappings
from .image import upsert_raes_image_mapping as upsert_raes_image_mapping
from .range import RaesRangeRef as RaesRangeRef
from .range import RangeBindings as RangeBindings
from .range import create_raes_range as create_raes_range
from .range import dispatch_created_raes_range as dispatch_created_raes_range
from .range import grant_raes_remote_access as grant_raes_remote_access
from .status import project_raes_operation_status as project_raes_operation_status

__all__ = [
    "RaesImageMappingError",
    "RaesImageMappingOptions",
    "RaesImageMappingView",
    "RaesRangeRef",
    "RangeBindings",
    "create_raes_range",
    "disable_raes_image_mapping",
    "dispatch_created_raes_range",
    "grant_raes_remote_access",
    "list_backend_artifacts",
    "list_raes_image_mappings",
    "project_raes_operation_status",
    "record_raes_operation_status",
    "record_raes_runtime_snapshot",
    "upsert_raes_image_mapping",
]
