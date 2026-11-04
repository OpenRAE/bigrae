"""Native correlation facts, without portable SDK or product dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from shared.native_power import GcePowerIncarnation, GcePowerTarget

if TYPE_CHECKING:
    from shared.credentials import CredentialContext

NATIVE_POWER_CONTROL_PROFILE_REF = "shifter-native-power-supervision/v1"
NativeControlCommandKind = Literal["proposal", "approval", "denial", "cancellation", "action"]


@dataclass(frozen=True, slots=True)
class NativeControlSubmission:
    """One native original request choice; no receipt, verdict, or executable selector."""

    request_id: UUID
    kind: NativeControlCommandKind
    verb: Literal["pause", "resume"]
    proposal_id: UUID
    action_id: UUID
    expected_cut_digest: str
    decision_id: UUID | None = None


class NativeControlUnavailable(ValueError):
    """Installed worker capacity, ownership or configuration is unavailable."""


@dataclass(frozen=True, slots=True)
class NativePowerConfigurationEvidence:
    """Source-structure and installed implementation identity, without runtime proof."""

    raes_version: str
    implementation_digest: str


def native_power_invocation_id(operation_id: UUID, member_ref: str) -> UUID:
    """Stable native provider request identity; it confers no call permission."""
    if not isinstance(operation_id, UUID) or not operation_id.int or not member_ref or len(member_ref) > 512:
        raise ValueError("Native invocation identity unavailable")
    return uuid5(NAMESPACE_URL, f"shifter-native-power-invocation/v1:{operation_id}:{member_ref}")


@dataclass(frozen=True, slots=True)
class NativePowerInvocationGrant:
    """One consumed native permission, separate from portable admission."""

    invocation_id: UUID
    operation_id: UUID
    resource_generation: UUID
    verb: Literal["pause", "resume"]
    member_ref: str
    target: GcePowerTarget
    incarnation: GcePowerIncarnation
    attempt_id: UUID


@dataclass(frozen=True, slots=True)
class NativeRuntimeCoordinates:
    """Server-recorded identifiers, separate from caller or scenario names."""

    binding_ref: UUID
    resource_generation: UUID
    run_id: UUID

    def __post_init__(self) -> None:
        if not all(isinstance(value, UUID) for value in (self.binding_ref, self.resource_generation, self.run_id)):
            raise ValueError("Native runtime coordinates are unavailable")


@dataclass(frozen=True, slots=True)
class NativePowerInvocationRoute:
    """Verified workload routing facts, without an invocation permission or input."""

    action_id: UUID
    operation_id: UUID
    approval_id: UUID
    coordinates: NativeRuntimeCoordinates


@dataclass(frozen=True, slots=True)
class NativePowerControlSelection:
    """Installed logical references; there is no executable provider selector."""

    participant_address: str
    controller_address: str
    pause_action_contract_address: str
    resume_action_contract_address: str
    observation_boundary_address: str

    def __post_init__(self) -> None:
        values = (
            self.participant_address,
            self.controller_address,
            self.pause_action_contract_address,
            self.resume_action_contract_address,
            self.observation_boundary_address,
        )
        if any(
            not isinstance(value, str) or not 1 <= len(value) <= 256 or any(c.isspace() for c in value)
            for value in values
        ):
            raise ValueError("Installed native control selection unavailable")


@dataclass(frozen=True, slots=True)
class NativeControlConfigurationView:
    """Authorized native installation projection, separate from runtime evidence."""

    id: UUID
    organization_uuid: UUID
    source_uuid: UUID
    source_package_digest: str
    configuration_digest: str
    raes_version: str
    structural_report_ref: str
    runtime_policy_digest: str
    selection: NativePowerControlSelection = field(repr=False)


@dataclass(frozen=True, slots=True)
class NativeControlBindingView:
    """Native routing coordinates; no portable history, state or execution verdict."""

    id: UUID
    configuration_id: UUID
    range_uuid: UUID
    product: str
    subject_uuid: UUID
    coordinates: NativeRuntimeCoordinates


@dataclass(frozen=True, slots=True)
class NativeControlConfigurationStatus:
    """Authorized source administration metadata, never a runtime qualification verdict."""

    configuration: NativeControlConfigurationView | None
    requires_refresh: bool


@dataclass(frozen=True, slots=True)
class NativeControlOptionsView:
    """Opaque product routing choices; activation still performs full qualification."""

    configuration_id: UUID | None
    binding_id: UUID | None
    requires_refresh: bool


@dataclass(frozen=True, slots=True)
class NativeSupervisionCursor:
    """Request coordinates from the released fold, without an authority grant."""

    episode_id: str
    policy_ref: str
    policy_revision: str
    state_ref: str
    state_revision: int
    history_head: int
    next_order: int
    control_cut_digest: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class NativePreparedControlRequest:
    """Immutable native request bytes, separate from runtime history and verdicts."""

    intent_json: bytes = field(repr=False)
    subject_json: bytes = field(repr=False)
    control_cut_digest: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class NativeControlCommandRecord:
    """Private original request and proof; operation status remains SDK-owned."""

    id: UUID
    binding_id: UUID
    kind: NativeControlCommandKind
    verb: Literal["pause", "resume"]
    proposal_id: UUID
    action_id: UUID
    request: NativePreparedControlRequest = field(repr=False)
    credential: CredentialContext = field(repr=False)
    portable_operation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class NativeControlOperationView:
    """Detached SDK receipt projection; native execution remains Engine-owned."""

    command_id: UUID
    operation_id: UUID
    state: str


@dataclass(frozen=True, slots=True)
class NativeControlCommandView:
    """Authorized reference-only request projection; no proof, intent bytes or diagnostics."""

    id: UUID
    kind: NativeControlCommandKind
    verb: Literal["pause", "resume"]
    proposal_id: UUID
    action_id: UUID
    operation_id: UUID | None
    operation_state: str | None


@dataclass(frozen=True, slots=True)
class NativeControlStateView:
    """Native management view, distinct from participant observations or a full snapshot."""

    binding: NativeControlBindingView
    cursor: NativeSupervisionCursor
    range_status: str
    commands: tuple[NativeControlCommandView, ...]
    next_before: UUID | None


@dataclass(frozen=True, slots=True)
class NativeParticipantPowerAction:
    """Exact approved meaning for a held native reservation, never a grant."""

    coordinates: NativeRuntimeCoordinates
    participant_address: str
    controller_address: str
    episode_id: str
    action_id: str
    proposal_ref: str
    action_contract_address: str
    observation_boundary_address: str
    target_addresses: tuple[str, ...]
    verb: Literal["pause", "resume"]
    implementation_selection_digest: str
    compiler_input_digest: str = field(repr=False)
    control_cut_digest: str = field(repr=False)
    approval_ref: str = ""


class NativeControlAuthorityPort(Protocol):
    """The native owner resolves original requests and independently fences permission."""

    def commands(self) -> tuple[NativeControlCommandRecord, ...]:
        """Read the native immutable original request catalog."""
        ...

    def authorize(self, command_id: UUID | None, *, approval_id: UUID | None = None) -> None:
        """Fence the original actor and any independently required review proof."""
        ...

    def reserve(self, action: NativeParticipantPowerAction) -> UUID:
        """Strictly audit held native work before released admission commits."""
        ...
