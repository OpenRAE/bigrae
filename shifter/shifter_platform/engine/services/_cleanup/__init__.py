"""Range cleanup-outcome projection and scoped provider readback evidence.

The ``engine.services`` facade re-exports these names. Engine modules import
dependencies from the owning leaf module, not from this package.
"""

from __future__ import annotations

from .outcome import CLEANUP_NOT_APPLICABLE as CLEANUP_NOT_APPLICABLE
from .outcome import CLEANUP_PENDING as CLEANUP_PENDING
from .outcome import CLEANUP_UNKNOWN as CLEANUP_UNKNOWN
from .outcome import CLEANUP_VERIFIED_TERMINAL as CLEANUP_VERIFIED_TERMINAL
from .outcome import CleanupObligation as CleanupObligation
from .outcome import RangeCleanupOutcome as RangeCleanupOutcome
from .outcome import project_range_cleanup_outcome as project_range_cleanup_outcome
from .verification import CleanupVerificationView as CleanupVerificationView
from .verification import is_cleanup_verified_absent as is_cleanup_verified_absent
from .verification import is_range_generation_cleanup_verified_absent as is_range_generation_cleanup_verified_absent
from .verification import latest_cleanup_verification as latest_cleanup_verification
from .verification import record_cleanup_verification as record_cleanup_verification

__all__ = [
    "CLEANUP_NOT_APPLICABLE",
    "CLEANUP_PENDING",
    "CLEANUP_UNKNOWN",
    "CLEANUP_VERIFIED_TERMINAL",
    "CleanupObligation",
    "CleanupVerificationView",
    "RangeCleanupOutcome",
    "is_cleanup_verified_absent",
    "is_range_generation_cleanup_verified_absent",
    "latest_cleanup_verification",
    "project_range_cleanup_outcome",
    "record_cleanup_verification",
]
