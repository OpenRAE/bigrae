"""Operation-result admission, domain apply, effects and the RAES and VPN result families.

The ``engine.services`` facade re-exports these names. Engine modules import
dependencies from the owning leaf module, not from this package.
"""

from __future__ import annotations

from .applier import apply_pending_operation_results as apply_pending_operation_results
from .applier import evaluate_operation_result as evaluate_operation_result

__all__ = [
    "apply_pending_operation_results",
    "evaluate_operation_result",
]
