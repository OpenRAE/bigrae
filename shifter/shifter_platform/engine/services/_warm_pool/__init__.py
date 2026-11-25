"""Warm generation allocation, admission, retirement and recovery.

The ``engine.services`` facade re-exports these names. Engine modules import
dependencies from the owning leaf module, not from this package.
"""

from __future__ import annotations

from .admission import reserve_warm_generation as reserve_warm_generation
from .allocation import WarmGenerationDraft as WarmGenerationDraft
from .allocation import abandon_warm_preparation as abandon_warm_preparation
from .allocation import active_generation_count as active_generation_count
from .allocation import admit_warm_generation_capacity as admit_warm_generation_capacity
from .allocation import bucket_state_counts as bucket_state_counts
from .allocation import claim_ready_generation as claim_ready_generation
from .allocation import create_warm_generation as create_warm_generation
from .allocation import enqueue_admitted_warm_activation as enqueue_admitted_warm_activation
from .allocation import enqueue_range_activation as enqueue_range_activation
from .allocation import finalize_retiring_generations as finalize_retiring_generations
from .allocation import preview_ready_generation as preview_ready_generation
from .allocation import ready_generations as ready_generations
from .allocation import recover_stalled_generations as recover_stalled_generations
from .allocation import release_warm_generation_capacity as release_warm_generation_capacity
from .allocation import retire_generation as retire_generation
from .allocation import retire_generations_for_request as retire_generations_for_request
from .allocation import retire_removed_bucket_generations as retire_removed_bucket_generations
from .allocation import total_active_generation_count as total_active_generation_count
from .allocation import warm_capacity_scope_ref as warm_capacity_scope_ref
from .sweep import WarmRecoveryProgress as WarmRecoveryProgress
from .sweep import reconcile_retained_warm_generations as reconcile_retained_warm_generations

__all__ = [
    "WarmGenerationDraft",
    "WarmRecoveryProgress",
    "abandon_warm_preparation",
    "active_generation_count",
    "admit_warm_generation_capacity",
    "bucket_state_counts",
    "claim_ready_generation",
    "create_warm_generation",
    "enqueue_admitted_warm_activation",
    "enqueue_range_activation",
    "finalize_retiring_generations",
    "preview_ready_generation",
    "ready_generations",
    "reconcile_retained_warm_generations",
    "recover_stalled_generations",
    "release_warm_generation_capacity",
    "reserve_warm_generation",
    "retire_generation",
    "retire_generations_for_request",
    "retire_removed_bucket_generations",
    "total_active_generation_count",
    "warm_capacity_scope_ref",
]
