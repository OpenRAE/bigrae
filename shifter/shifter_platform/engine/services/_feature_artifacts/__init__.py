"""Feature-artifact acquisition and launcher reconciliation.

The ``engine.services`` facade re-exports these names. Engine modules import
dependencies from the owning leaf module, not from this package.
"""

from __future__ import annotations

from .acquisition import ArtifactRequest as ArtifactRequest
from .acquisition import FeatureArtifactUnavailableError as FeatureArtifactUnavailableError
from .acquisition import StorageTarget as StorageTarget
from .acquisition import await_ready as await_ready
from .acquisition import request_acquisition as request_acquisition
from .launcher import default_storage_target as default_storage_target
from .launcher import reconcile_feature_artifact_acquisitions as reconcile_feature_artifact_acquisitions

__all__ = [
    "ArtifactRequest",
    "FeatureArtifactUnavailableError",
    "StorageTarget",
    "await_ready",
    "default_storage_target",
    "reconcile_feature_artifact_acquisitions",
    "request_acquisition",
]
