"""RAES-free identity and scalar transport for core-approved preparation."""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from pydantic import Field, model_validator
from shifter_adapter_sdk.runtime import ClosedModel, Digest, ProvisioningValue, RuntimePlan, canonical_digest

from shared.gcp_range_projects import MAX_PROJECTS_PER_RANGE, GcpProjectLease

_UNAVAILABLE = "Preparation mapping is unavailable or outside its declared scope"


class RuntimePreparation(ClosedModel):
    """Original source proof and ciphertext; absence is asserted under the range mutex."""

    state: Literal["prepared", "unprepared"]
    plan_digest: Digest
    pin_digest: Digest
    source_operation_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    input_digest: Digest | None = Field(default=None, exclude_if=lambda value: value is None)
    encrypted_result: Annotated[str, Field(min_length=8, max_length=1_048_576, pattern=r"^enc:v1:")] | None = Field(
        default=None,
        repr=False,
        exclude_if=lambda value: value is None,
    )

    cloud_projects: tuple[GcpProjectLease, ...] = Field(
        default=(), max_length=MAX_PROJECTS_PER_RANGE, exclude_if=lambda value: not value, repr=False
    )

    @model_validator(mode="after")
    def validate_state(self) -> RuntimePreparation:
        """Never confuse missing material with an accepted preparation."""
        fields = (self.source_operation_id, self.input_digest, self.encrypted_result)
        valid = (
            all(value is not None for value in fields)
            if self.state == "prepared"
            else all(value is None for value in fields)
        )
        if not valid or (self.state == "unprepared" and self.cloud_projects):
            raise ValueError(_UNAVAILABLE)
        if (
            any(
                lease.plan_digest != self.plan_digest or lease.source_operation_id != self.source_operation_id
                for lease in self.cloud_projects
            )
            or len({lease.lease_id for lease in self.cloud_projects}) != len(self.cloud_projects)
            or len({lease.project_id for lease in self.cloud_projects}) != len(self.cloud_projects)
        ):
            raise ValueError(_UNAVAILABLE)
        return self


def pointer_tokens(pointer: object) -> tuple[str, ...]:
    """Decode SDK-validated RFC 6901 tokens, including a constraint's root pointer."""
    if pointer == "":
        return ()
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(_UNAVAILABLE)
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _member(value: object, token: str) -> object:
    """Select existing members; array append, negative and ambiguous indices fail."""
    if isinstance(value, dict) and token in value:
        return cast(object, value[token])
    if isinstance(value, list) and token.isascii() and token.isdecimal():
        index = int(token)
        if str(index) == token and index < len(value):
            return cast(object, value[index])
    raise ValueError(_UNAVAILABLE)


def pointer_value(value: object, pointer: str) -> object:
    """Read exactly an existing JSON leaf without interpreting it as a path or code."""
    for token in pointer_tokens(pointer):
        value = _member(value, token)
    return value


def governing_authorities(plan: dict[str, Any], edit: ProvisioningValue) -> list[dict[str, Any]]:
    """Every overlapping authority remains binding, including undeclared exact ancestors."""
    path = pointer_tokens(edit.payload_pointer)
    result = []
    rows = plan.get("realization_authority")
    if not isinstance(rows, list):
        raise ValueError(_UNAVAILABLE)
    for row in rows:
        if isinstance(row, dict) and row.get("address") == edit.address:
            root = pointer_tokens(row.get("payload_pointer"))
            if path[: len(root)] == root:
                result.append(row)
    return result


def _replace_scalar(payload: dict[str, Any], edit: ProvisioningValue) -> None:
    """Change an existing scalar only; collection shape and keys cannot be replaced."""
    tokens = pointer_tokens(edit.payload_pointer)
    parent: object = payload
    for token in tokens[:-1]:
        parent = _member(parent, token)
    previous = _member(parent, tokens[-1])
    if isinstance(previous, (dict, list)):
        raise ValueError(_UNAVAILABLE)
    if isinstance(parent, list):
        parent[int(tokens[-1])] = edit.value
    elif isinstance(parent, dict):
        parent[tokens[-1]] = edit.value
    else:
        raise ValueError(_UNAVAILABLE)


def _operation_payload(plan: dict[str, Any], address: str) -> dict[str, Any]:
    """Require one mutable operation over the exact resource payload."""
    operations = plan.get("operations")
    if not isinstance(operations, list):
        raise ValueError(_UNAVAILABLE)
    matches = [item for item in operations if isinstance(item, dict) and item.get("address") == address]
    if len(matches) != 1 or matches[0].get("action") not in {"create", "update"}:
        raise ValueError(_UNAVAILABLE)
    payload = matches[0].get("payload")
    if not isinstance(payload, dict):
        raise ValueError(_UNAVAILABLE)
    return payload


def apply_prepared_values(plan: dict[str, Any], result: RuntimePlan, concerns: list[str]) -> dict[str, Any]:
    """Materialize a local copy; only the application may authorize RAES semantics."""
    if result.phase != "prepare" or result.status != "planned":
        raise ValueError(_UNAVAILABLE)
    candidate = deepcopy(plan)
    for edit in result.provisioning_values:
        _apply_edit(plan, candidate, edit, concerns)
    return candidate


def _apply_edit(
    original: dict[str, Any], candidate: dict[str, Any], edit: ProvisioningValue, concerns: list[str]
) -> None:
    """Keep wire identity, address, operation and concern authority together."""
    resource = original.get("resources", {}).get(edit.address)
    if not isinstance(resource, dict) or not isinstance(resource.get("payload"), dict):
        raise ValueError(_UNAVAILABLE)
    payload = resource["payload"]
    operation = _operation_payload(original, edit.address)
    if canonical_digest(operation) != canonical_digest(payload):
        raise ValueError(_UNAVAILABLE)
    authorities = governing_authorities(original, edit)
    matching = [row for row in authorities if row.get("requirement_kind") == edit.concern]
    if edit.concern not in concerns or len(matching) != 1:
        raise ValueError(_UNAVAILABLE)
    old_value = pointer_value(payload, edit.payload_pointer)
    changed = canonical_digest(old_value) != canonical_digest(edit.value)
    if changed and any(row.get("mode") not in {"open", "constrained"} for row in authorities):
        raise ValueError(_UNAVAILABLE)
    _replace_scalar(candidate["resources"][edit.address]["payload"], edit)
    _replace_scalar(_operation_payload(candidate, edit.address), edit)
