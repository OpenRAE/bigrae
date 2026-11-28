"""Engine models.

Infrastructure lifecycle models for Shifter platform.

- Request: Provisioning request container (1:1 with RequestSpec)
- Instantiation: Abstract base for materialized specs
- Range: User's cyber range instance with provisioned infrastructure
- NGFW: User's Next-Generation Firewall with AWS resources
- SubnetAllocation: CIDR reservation to prevent race conditions during provisioning

Split into a package (#561) so no module exceeds 500 lines. Django app_label,
table names, and every field/Meta/method are unchanged - this is a pure module
reorganization with zero migration drift. The implementation is spread across
private submodules by domain:

- ``_request``: Request, Instantiation (abstract base), Instance, App.
- ``_range``: Range (depends on ``_request.Request``).
- ``_subnet``: Subnet, SubnetAllocation (depends on ``_range.Range`` and
  ``_request.Instantiation``).
- ``_outbox``: OutboxStatus, RangeEventOutbox.
- ``_launch``: ProvisionerLaunchStatus, InterruptState, ProvisionerLaunchIntent.
- ``_raes``: RaesImageMapping, RaesContentDeliveryBinding, RaesParticipantAccessBinding,
  RaesArtifactSatisfactionBinding.

All models are re-exported here so Django's app registry discovers them via
``engine.models`` and callers keep using ``from engine.models import X``
exactly as before the split.
"""

from engine.models._capacity import CapacityDeclaration
from engine.models._capacity_assessment import CapacityAssessment, CapacityDraw, CapacityReservation
from engine.models._cleanup_verification import CleanupVerificationOutcome, RangeCleanupVerification
from engine.models._feature_artifacts import AcquiredFeatureArtifact
from engine.models._gcp_range_projects import GcpRangeProject, GcpRangeProjectUse
from engine.models._launch import (
    InterruptState,
    ProvisionerLaunchIntent,
    ProvisionerLaunchStatus,
    RangeCancellationAuthority,
)
from engine.models._operation_io import (
    OperationInput,
    OperationResultDisposition,
    OperationResultInbox,
    OperationResultKind,
)
from engine.models._outbox import OutboxStatus, RangeEventOutbox
from engine.models._preparation import (
    PreparationAdapter,
    PreparationAttempt,
    PreparationGrant,
    PreparationOperation,
    PreparationScopeLock,
    PreparedArtifactAdmission,
)
from engine.models._raes import (
    RaesArtifactSatisfactionBinding,
    RaesContentDeliveryBinding,
    RaesImageMapping,
    RaesParticipantAccessBinding,
)
from engine.models._range import Range
from engine.models._range_authority_change import RangeAuthorityChange
from engine.models._receipt import ReceiptVerifierRegistration
from engine.models._request import App, Instance, Instantiation, Request
from engine.models._retry_binding import PublicOperationRetryBinding, RetryBindingStatus
from engine.models._runtime_plugins import (
    RuntimePluginInstallation,
    RuntimePluginInvocation,
    RuntimePluginPackBinding,
    RuntimePluginRangeBinding,
    RuntimePluginValidation,
)
from engine.models._subnet import Subnet, SubnetAllocation
from engine.models._vpn_profile import VpnAccessProfile, VpnCrlState
from engine.models._vpn_session import VpnSession, VpnSessionEndReason, VpnSessionState
from engine.models._warm_pool import WarmRangeGeneration

__all__ = [
    "AcquiredFeatureArtifact",
    "App",
    "CapacityAssessment",
    "CapacityDeclaration",
    "CapacityDraw",
    "CapacityReservation",
    "CleanupVerificationOutcome",
    "DisposableWorker",
    "GcpRangeProject",
    "GcpRangeProjectUse",
    "Instance",
    "Instantiation",
    "InterruptState",
    "OperationInput",
    "OperationResultDisposition",
    "OperationResultInbox",
    "OperationResultKind",
    "OutboxStatus",
    "PreparationAdapter",
    "PreparationAttempt",
    "PreparationGrant",
    "PreparationOperation",
    "PreparationScopeLock",
    "PreparedArtifactAdmission",
    "ProvisionerLaunchIntent",
    "ProvisionerLaunchStatus",
    "PublicOperationRetryBinding",
    "RaesArtifactSatisfactionBinding",
    "RaesContentDeliveryBinding",
    "RaesImageMapping",
    "RaesParticipantAccessBinding",
    "Range",
    "RangeAuthorityChange",
    "RangeCancellationAuthority",
    "RangeCleanupVerification",
    "RangeEventOutbox",
    "ReceiptVerifierRegistration",
    "Request",
    "RetryBindingStatus",
    "RuntimePluginInstallation",
    "RuntimePluginInvocation",
    "RuntimePluginPackBinding",
    "RuntimePluginRangeBinding",
    "RuntimePluginValidation",
    "Subnet",
    "SubnetAllocation",
    "VpnAccessProfile",
    "VpnCrlState",
    "VpnSession",
    "VpnSessionEndReason",
    "VpnSessionState",
    "WarmRangeGeneration",
    "WorkerHostIdentity",
    "WorkerHostObservation",
    "WorkerPolicyRecord",
    "WorkerRetirementHold",
    "WorkerTrial",
]

from engine.models._disposable_worker import (
    DisposableWorker,
    WorkerHostIdentity,
    WorkerHostObservation,
    WorkerPolicyRecord,
    WorkerRetirementHold,
)
from engine.models._worker_trial import WorkerTrial
