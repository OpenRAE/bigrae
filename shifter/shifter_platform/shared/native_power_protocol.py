"""Closed private grant transport, separate from portable participant contracts."""

from uuid import UUID

from shared.native_participant import NativePowerInvocationGrant
from shared.native_power import parse_gce_power_incarnation, parse_gce_power_target

NATIVE_POWER_GRANT_VERSION = "shifter-native-power-grant/v1"
NATIVE_POWER_TOKEN_AUDIENCE = "shifter-native-participant-invocation"
NATIVE_POWER_TOKEN_DIRECTORY = "/var/run/secrets/shifter/native-power"
NATIVE_POWER_TOKEN_VOLUME = "native-power-identity"
NATIVE_POWER_JOB_DEADLINE_SECONDS = 1800
_FIELDS = frozenset(
    {
        "contract_version",
        "invocation_id",
        "operation_id",
        "resource_generation",
        "verb",
        "member_ref",
        "target",
        "incarnation",
        "attempt_id",
    }
)


def native_power_grant_payload(grant: NativePowerInvocationGrant) -> dict[str, object]:
    """Disclose addressing only to the independently verified owning workload."""
    return {
        "contract_version": NATIVE_POWER_GRANT_VERSION,
        "invocation_id": str(grant.invocation_id),
        "operation_id": str(grant.operation_id),
        "resource_generation": str(grant.resource_generation),
        "verb": grant.verb,
        "member_ref": grant.member_ref,
        "target": grant.target.to_transport(),
        "incarnation": grant.incarnation.to_transport(),
        "attempt_id": str(grant.attempt_id),
    }


def parse_native_power_grant(value: object) -> NativePowerInvocationGrant:
    """Reject malformed or extended grants; the final helper also compares every field to immutable input."""
    try:
        if (
            not isinstance(value, dict)
            or set(value) != _FIELDS
            or value["contract_version"] != NATIVE_POWER_GRANT_VERSION
        ):
            raise ValueError
        identities = {}
        for key in ("invocation_id", "operation_id", "resource_generation", "attempt_id"):
            raw = value[key]
            if not isinstance(raw, str):
                raise ValueError
            identity = UUID(raw)
            if not identity.int or str(identity) != raw:
                raise ValueError
            identities[key] = identity
        verb, member, target = value["verb"], value["member_ref"], value["target"]
        if verb not in {"pause", "resume"} or not isinstance(member, str) or not 1 <= len(member) <= 512:
            raise ValueError
        if not isinstance(target, dict):
            raise ValueError
        return NativePowerInvocationGrant(
            invocation_id=identities["invocation_id"],
            operation_id=identities["operation_id"],
            resource_generation=identities["resource_generation"],
            verb=verb,
            member_ref=member,
            target=parse_gce_power_target(target, instance_id=target.get("instance_name", "")),
            incarnation=parse_gce_power_incarnation(value["incarnation"]),
            attempt_id=identities["attempt_id"],
        )
    except Exception:  # noqa: BLE001  # native addressing and parser diagnostics remain private
        raise ValueError("Native power invocation permission unavailable") from None
