"""Closed, application-independent wire contract for isolated runtime plugins.

The plugin produces a plan; the host authorizes targets and executes actions.
Producing a plan never constitutes evidence that a guest is configured or ready.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Final, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL: Final = "shifter.runtime-plugin/v1"
ENTRY_POINT_GROUP = "shifter.runtime.plugins"
ENTRY_POINT_GROUPS = (ENTRY_POINT_GROUP, "bigrae.runtime.plugins")
# Fits one injected environment value on Linux, including its name and terminator.
MAX_INPUT_BYTES = 65_536
MAX_OUTPUT_BYTES = 1_048_576
MAX_PREPARATION_BYTES = 512 * 1024
PREPARATION_OUTPUT_ENV = "BIGRAE_PLUGIN_RESULT_SECRET"
MAX_FILE_INPUT_BYTES = 512 * 1024
MAX_FILE_INPUTS = 16
FILE_INPUT_DIRECTORY = "/run/plugin-inputs"
_FILE_INPUT_ROOT = Path(FILE_INPUT_DIRECTORY)

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")]
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Version = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")]
WorkerImage = Annotated[
    str,
    Field(max_length=1024, pattern=r"^[a-z0-9][a-z0-9.:-]+/[a-z0-9/._-]+@sha256:[a-f0-9]{64}$"),
]
Phase = Literal["prepare", "validate", "configure", "verify", "cleanup"]
Capability = Literal["provision.prepare", "guest.configure", "guest.verify"]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


def decode_message(raw: str | bytes, *, limit: int) -> object:
    """Reject oversized, ambiguous, or non-JSON worker messages before validation."""
    if len(raw.encode("utf-8") if isinstance(raw, str) else raw) > limit:
        raise ValueError("plugin message exceeds its bound")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate plugin message key")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise ValueError("non-JSON plugin message value")

    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="strict")
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid plugin message encoding or nesting") from exc


def canonical_digest(value: object) -> str:
    """Bind JSON bytes independently of object-key ordering."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class PluginManifest(ClosedModel):
    """Executable identity and capabilities requested by an author-provided plugin."""

    protocol: Literal["shifter.runtime-plugin/v1", "bigrae.runtime-plugin/v1", "bigrae.runtime-plugin/v2"]
    plugin_id: Identifier
    version: Version
    distribution: Identifier
    entry_point: Identifier
    worker_image: WorkerImage
    capabilities: list[Capability] = Field(min_length=1, max_length=3)
    required_bindings: list[Identifier] = Field(max_length=64)
    provisioning_concerns: list[Identifier] = Field(
        default_factory=list, max_length=64, exclude_if=lambda value: not value
    )
    required_parameters: list[Identifier] = Field(default_factory=list, max_length=64)
    required_files: list[Identifier] = Field(
        default_factory=list, max_length=MAX_FILE_INPUTS, exclude_if=lambda value: not value
    )
    model_bindings: dict[Identifier, Identifier] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def unique_declarations(self) -> Self:
        for values in (
            self.capabilities,
            self.required_bindings,
            self.required_parameters,
            self.required_files,
            self.provisioning_concerns,
        ):
            if len(values) != len(set(values)):
                raise ValueError("plugin declarations must be unique")
        if not set(self.model_bindings.values()).issubset(self.required_bindings):
            raise ValueError("model bindings must name declared guest bindings")
        if bool(self.provisioning_concerns) != ("provision.prepare" in self.capabilities):
            raise ValueError("preparation requires explicitly declared provisioning concerns")
        if self.required_bindings and "guest.verify" not in self.capabilities:
            raise ValueError("a runtime plugin must provide readiness verification")
        if not self.required_bindings and self.capabilities != ["provision.prepare"]:
            raise ValueError("a plugin without guests must provide only preparation")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class GuestTarget(ClosedModel):
    """Authorized projection; cloud locators, passwords and private keys stay in core."""

    node_address: Annotated[str, Field(min_length=1, max_length=1024)]
    os_family: Literal["linux", "windows"]
    private_address: Annotated[str, Field(max_length=256)] = ""
    public_key: Annotated[str, Field(max_length=16_384)] = ""


class InspectionInput(ClosedModel):
    """Installation probe with no range, guest, credential, or operation context."""

    protocol: Literal["shifter.runtime-plugin/v1", "bigrae.runtime-plugin/v1", "bigrae.runtime-plugin/v2"]
    invocation_id: UUID
    phase: Literal["inspect"]
    manifest: PluginManifest

    @model_validator(mode="after")
    def validate_protocol(self) -> Self:
        if self.protocol != self.manifest.protocol:
            raise ValueError("plugin input and manifest protocols must agree")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class InspectionResult(ClosedModel):
    """Checks packaging compatibility, never claims guest readiness."""

    protocol: Literal["shifter.runtime-plugin/v1", "bigrae.runtime-plugin/v1", "bigrae.runtime-plugin/v2"]
    invocation_id: UUID
    phase: Literal["inspect"]
    input_digest: Digest
    status: Literal["compatible", "failed"]

    def authorize(self, request: InspectionInput) -> None:
        if (
            self.protocol != request.protocol
            or self.invocation_id != request.invocation_id
            or self.input_digest != request.digest
        ):
            raise ValueError("plugin inspection does not match its invocation")


class FileInput(ClosedModel):
    """Byte-free identity for one declared file supplied by the host."""

    sha256: Digest
    size_bytes: Annotated[int, Field(strict=True, gt=0, le=MAX_FILE_INPUT_BYTES)]

    def verify_material(self, material: bytes) -> None:
        """Reject bytes that differ from this admitted identity without echoing them."""
        if (
            not isinstance(material, bytes)
            or len(material) != self.size_bytes
            or "sha256:" + hashlib.sha256(material).hexdigest() != self.sha256
        ):
            raise ValueError("file input does not match its admitted bytes")


class RuntimeInput(ClosedModel):
    """Exactly one operation and phase; values are never taken from plugin output."""

    protocol: Literal["shifter.runtime-plugin/v1", "bigrae.runtime-plugin/v1", "bigrae.runtime-plugin/v2"]
    invocation_id: UUID
    operation_id: UUID
    pack_digest: Digest | None = Field(default=None, exclude_if=lambda value: value is None)
    apparatus_digest: Digest | None = Field(default=None, exclude_if=lambda value: value is None)
    manifest: PluginManifest
    phase: Phase
    provider: Literal["aws", "gcp"]
    range_id: Annotated[int, Field(strict=True, ge=1)]
    targets: dict[Identifier, GuestTarget] = Field(max_length=64)
    plan_digest: Digest | None = Field(default=None, exclude_if=lambda value: value is None)
    parameters: dict[Identifier, Annotated[str, Field(max_length=8192)]] = Field(default_factory=dict, max_length=64)
    files: dict[Identifier, FileInput] = Field(
        default_factory=dict, max_length=MAX_FILE_INPUTS, exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.protocol == "bigrae.runtime-plugin/v2":
            if self.pack_digest is not None or self.apparatus_digest is None:
                raise ValueError("apparatus protocol requires only apparatus identity")
        elif self.pack_digest is None or self.apparatus_digest is not None:
            raise ValueError("pack protocol requires only pack identity")
        self._validate_phase()
        if self.protocol != self.manifest.protocol:
            raise ValueError("plugin input and manifest protocols must agree")
        if set(self.targets) != set(self.manifest.required_bindings):
            raise ValueError("target bindings must exactly match the installed declaration")
        if set(self.parameters) != set(self.manifest.required_parameters):
            raise ValueError("parameter bindings must exactly match the installed declaration")
        if set(self.files) != set(self.manifest.required_files):
            raise ValueError("file inputs must exactly match the installed declaration")
        if sum(item.size_bytes for item in self.files.values()) > MAX_FILE_INPUT_BYTES:
            raise ValueError("file inputs exceed their total byte budget")
        if len(self.model_dump_json().encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("plugin input exceeds its bound")
        return self

    def _validate_phase(self) -> None:
        """Separate preparation context from guest-only phase inputs."""
        if self.phase == "prepare":
            if "provision.prepare" not in self.manifest.capabilities or self.plan_digest is None:
                raise ValueError("preparation requires its declared capability and original plan digest")
        elif not self.targets or self.plan_digest is not None:
            raise ValueError("guest phases require guest bindings and no preparation context")

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


def read_file_input(request: RuntimeInput, name: str) -> bytes:
    """Read a declared mounted file, checking its bound size and SHA-256.

    Kubernetes projects Secret keys through symlinks in its read-only volume.
    Input names cannot select a path outside that host-owned mount.
    """
    expected = request.files.get(name)
    if expected is None or name not in request.manifest.required_files:
        raise ValueError("file input is unavailable")
    try:
        with (_FILE_INPUT_ROOT / name).open("rb") as stream:
            material = stream.read(expected.size_bytes + 1)
    except OSError:
        raise ValueError("file input is unavailable") from None
    expected.verify_material(material)
    return material


class GuestValueReference(ClosedModel):
    """A public value resolved by the host from an original guest binding.

    Values reach the guest action only, never the isolated planning worker.
    This cannot name an arbitrary output key, secret reference, or cloud object.
    """

    binding: Identifier
    field: Literal["private_address", "participant_ssh_public_key"]


class GuestAction(ClosedModel):
    """An action on a declared guest; interpreter and transport are host-owned."""

    action_id: Identifier
    binding: Identifier
    script: Annotated[str, Field(min_length=1, max_length=65_536)] = Field(repr=False)
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=300)] = 60
    runtime_values: dict[Identifier, GuestValueReference] = Field(default_factory=dict, max_length=64)


class ProvisioningValue(ClosedModel):
    """One proposed scalar replacement; core owns all semantic authorization."""

    address: Annotated[str, Field(min_length=1, max_length=1024)]
    concern: Identifier
    payload_pointer: Annotated[
        str, Field(min_length=1, max_length=4096, pattern=r"^/(?:[^~/]|~[01])*(?:/(?:[^~/]|~[01])*)*$")
    ]
    value: (
        Annotated[str, Field(strict=True, max_length=8192)]
        | Annotated[int, Field(strict=True)]
        | Annotated[float, Field(strict=True, allow_inf_nan=False)]
        | Annotated[bool, Field(strict=True)]
        | None
    ) = Field(repr=False)


class SecretPayloadValue(ClosedModel):
    """A literal backend selection for an otherwise unspecified native secret version."""

    version_ref: Annotated[str, Field(min_length=1, max_length=2048)]
    value: Annotated[str, Field(strict=True, max_length=65536)] = Field(repr=False)

    @model_validator(mode="after")
    def bounded_bytes(self) -> Self:
        if len(self.value.encode("utf-8")) > 65536:
            raise ValueError("secret payload exceeds the provider byte limit")
        return self


class RuntimePlan(ClosedModel):
    """Untrusted worker response. Core must bind it to input before execution."""

    protocol: Literal["shifter.runtime-plugin/v1", "bigrae.runtime-plugin/v1", "bigrae.runtime-plugin/v2"]
    invocation_id: UUID
    input_digest: Digest
    phase: Phase
    status: Literal["planned", "failed"]
    failure_code: Literal["", "incompatible", "invalid-input", "planning-failed"] = ""
    actions: list[GuestAction] = Field(default_factory=list, max_length=64, repr=False)
    provisioning_values: list[ProvisioningValue] = Field(
        default_factory=list, max_length=4096, repr=False, exclude_if=lambda value: not value
    )
    secret_payloads: list[SecretPayloadValue] = Field(
        default_factory=list, max_length=1024, repr=False, exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        self._validate_phase()
        identities = {(item.address, item.payload_pointer) for item in self.provisioning_values}
        if len(identities) != len(self.provisioning_values):
            raise ValueError("preparation replacements must be unique")
        if len({item.version_ref for item in self.secret_payloads}) != len(self.secret_payloads):
            raise ValueError("secret payload selections must be unique")
        if len({action.action_id for action in self.actions}) != len(self.actions):
            raise ValueError("action identifiers must be unique")
        if sum(action.timeout_seconds for action in self.actions) > 1200:
            raise ValueError("plugin plan exceeds the execution budget")
        limit = MAX_PREPARATION_BYTES if self.phase == "prepare" else MAX_OUTPUT_BYTES
        if len(self.model_dump_json().encode("utf-8")) > limit:
            raise ValueError("plugin output exceeds its bound")
        return self

    def _validate_phase(self) -> None:
        """Enforce closed failure and phase-specific effect contracts."""
        if self.status == "failed":
            if not self.failure_code or self.actions or self.provisioning_values or self.secret_payloads:
                raise ValueError("failed planning must carry only a bounded failure code")
        elif self.failure_code:
            raise ValueError("planned actions cannot carry a failure code")
        elif self.phase in {"prepare", "validate"} and self.actions:
            raise ValueError("validation cannot execute guest actions")
        elif self.phase == "verify" and not self.actions:
            raise ValueError("readiness requires at least one verification action")
        if (self.provisioning_values or self.secret_payloads) and self.phase != "prepare":
            raise ValueError("only preparation can propose provisioning values")

    def authorize(self, request: RuntimeInput) -> None:
        """Reject replay, another phase or operation, and undeclared guest targets."""
        if (
            self.protocol != request.protocol
            or self.invocation_id != request.invocation_id
            or self.input_digest != request.digest
            or self.phase != request.phase
            or any(action.binding not in request.targets for action in self.actions)
            or any(
                value.binding not in request.targets
                for action in self.actions
                for value in action.runtime_values.values()
            )
        ):
            raise ValueError("plugin plan does not match its authorized invocation")
        capability = "guest.verify" if self.phase == "verify" else "guest.configure"
        if any(item.concern not in request.manifest.provisioning_concerns for item in self.provisioning_values):
            raise ValueError("preparation requires an undeclared concern")
        if self.actions and capability not in request.manifest.capabilities:
            raise ValueError("plugin plan requires an undeclared capability")


class RuntimePlugin(Protocol):
    """Author implementation loaded only inside the isolated worker."""

    def plan(self, request: RuntimeInput) -> RuntimePlan: ...


def parse_input(raw: str | bytes) -> RuntimeInput | InspectionInput:
    """Parse a bounded request without importing any executable plugin."""
    value = decode_message(raw, limit=MAX_INPUT_BYTES)
    if isinstance(value, dict) and value.get("phase") == "inspect":
        return InspectionInput.model_validate(value)
    return RuntimeInput.model_validate(value)


def parse_result(
    raw: str | bytes, request: RuntimeInput | InspectionInput, *, result_secret: str = ""
) -> RuntimePlan | InspectionResult:
    """Host-side parser: validate shape and invocation before using worker output."""
    if request.phase == "prepare":
        from .runtime_sealing import open_result

        raw = open_result(raw, result_secret)
    limit = MAX_PREPARATION_BYTES if request.phase == "prepare" else MAX_OUTPUT_BYTES
    value = decode_message(raw, limit=limit)
    if isinstance(request, InspectionInput):
        inspection = InspectionResult.model_validate(value)
        inspection.authorize(request)
        return inspection
    plan = RuntimePlan.model_validate(value)
    plan.authorize(request)
    return plan
