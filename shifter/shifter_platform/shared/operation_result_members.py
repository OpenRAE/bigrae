"""Realized RAES member parsing for the closed operation-result contract (ADR-043).

Split out of ``operation_result_payloads`` for Sonar S104: that module owns the
step tables and payload shapes, while this leaf owns bounded per-member keys,
private host sidecars and their fail-closed parsers (#1710, #375). No Django
dependency, so the standalone provisioner image keeps importing it transitively
through ``operation_result_payloads``.
"""

from __future__ import annotations

from typing import Any

from shared.exceptions import ValidationError as OperationResultError
from shared.sftp_root import SftpRootError, normalize_sftp_root_directory

# The realized member/access projection an RAES provision returns so the portal
# has something to authorize and dial (#1710). Bounded and flat: exactly the
# fields ``Range.provisioned_instances`` needs, and secret *references* only --
# never a credential value, signed URL, or raw provider response.
RAES_MEMBER_REQUIRED_KEYS = frozenset(
    {
        "uuid",
        "name",
        "os_type",
        "private_ip",
        "instance_id",
        "subnet_name",
        "participant_access_channels",
        "participant_access_usernames",
    }
)
# Optional secret *references* and public material, one string per key. These
# are the credential-shaped optionals; the channel gate below requires the SSH /
# RDP refs when their channel is declared.
_RAES_MEMBER_REF_KEYS = frozenset({"ssh_key_secret_arn", "rdp_password_secret_arn", "host_public_key"})
# The full optional set the closed member shape accepts. ``sftp_root_directory``
# is realized per-image metadata (#375), not a credential reference, so it is
# parsed and shape-validated separately from the reference keys.
RAES_MEMBER_OPTIONAL_KEYS = _RAES_MEMBER_REF_KEYS | frozenset({"sftp_root_directory"})
#: Mirrors ``shared.raes.participant_access.SUPPORTED_ACCESS_CHANNELS`` without
#: importing it, keeping this transport module dependency-light.
RAES_MEMBER_CHANNELS = frozenset({"ssh", "rdp"})


def _parse_raes_members(raw: object, *, limit: int, field: str) -> list[dict[str, Any]]:
    """Parse a bounded realized-member list and reject duplicate guest identities."""
    if not isinstance(raw, list):
        raise OperationResultError(f"{field} members must be a list")
    if len(raw) > limit:
        raise OperationResultError(f"{field} carries more than {limit} members")
    members = []
    for index, item in enumerate(raw):
        entry_field = f"{field} members[{index}]"
        if not isinstance(item, dict):
            raise OperationResultError(f"{entry_field} must be an object")
        members.append(_parse_raes_member(item, entry_field))
    identities = [member["uuid"] for member in members]
    if len(set(identities)) != len(identities):
        raise OperationResultError(f"{field} members contains a duplicate uuid")
    return members


def _member_identity(entry: dict[str, Any], field: str) -> dict[str, Any]:
    """Return the member's flat, non-empty string identity fields."""
    identity: dict[str, Any] = {}
    for key in sorted(RAES_MEMBER_REQUIRED_KEYS - {"participant_access_channels", "participant_access_usernames"}):
        value = entry[key]
        if not isinstance(value, str) or not value:
            raise OperationResultError(f"{field} {key} must be a non-empty string")
        identity[key] = value
    return identity


def _member_channels(entry: dict[str, Any], field: str) -> list[str]:
    """Return the member's declared channels, closed on the supported vocabulary."""
    channels = entry["participant_access_channels"]
    if not isinstance(channels, list) or not all(isinstance(item, str) for item in channels):
        raise OperationResultError(f"{field} participant_access_channels must be a list of strings")
    if len(set(channels)) != len(channels):
        raise OperationResultError(f"{field} participant_access_channels contains a duplicate")
    unknown = sorted(set(channels) - RAES_MEMBER_CHANNELS)
    if unknown:
        raise OperationResultError(f"{field} declares unsupported channel(s): {', '.join(unknown)}")
    return list(channels)


def _member_usernames(entry: dict[str, Any], channels: list[str], field: str) -> dict[str, str]:
    """Return the per-channel logins, requiring exactly one per declared channel."""
    usernames = entry["participant_access_usernames"]
    if not isinstance(usernames, dict):
        raise OperationResultError(f"{field} participant_access_usernames must be an object")
    if sorted(usernames) != sorted(channels):
        raise OperationResultError(f"{field} participant_access_usernames must name exactly the declared channels")
    for channel, username in usernames.items():
        if not isinstance(username, str) or not username:
            raise OperationResultError(f"{field} participant_access_usernames['{channel}'] must be a non-empty string")
    return dict(usernames)


def _member_credential_refs(entry: dict[str, Any], channels: list[str], field: str) -> dict[str, Any]:
    """Return the optional secret *references*, one per declared channel.

    A declared channel with no credential reference is an unrealized endpoint,
    not a credential-less one: the portal would resolve nothing at dial time.
    """
    refs: dict[str, Any] = {}
    for key in sorted(_RAES_MEMBER_REF_KEYS):
        if key not in entry:
            continue
        value = entry[key]
        if not isinstance(value, str):
            raise OperationResultError(f"{field} {key} must be a string")
        refs[key] = value
    for channel, key in (("ssh", "ssh_key_secret_arn"), ("rdp", "rdp_password_secret_arn")):
        if channel in channels and not refs.get(key):
            raise OperationResultError(f"{field} declares {channel} without a {key} reference")
    return refs


def _member_sftp_root(entry: dict[str, Any], field: str) -> dict[str, Any]:
    """Return the validated per-image SFTP root, or ``{}`` when the member omits it.

    The value is untrusted realized configuration: it is shape-checked at this
    closed result boundary with the same helper the image-config parser uses, so
    a malformed guest path fails the transport parse instead of reaching the
    connection layer.
    """
    if "sftp_root_directory" not in entry:
        return {}
    value = entry["sftp_root_directory"]
    if not isinstance(value, str):
        raise OperationResultError(f"{field} sftp_root_directory must be a string")
    try:
        return {"sftp_root_directory": normalize_sftp_root_directory(value)}
    except SftpRootError as exc:
        raise OperationResultError(f"{field} sftp_root_directory is invalid: {exc}") from exc


def _parse_raes_member(entry: dict[str, Any], field: str) -> dict[str, Any]:
    """Parse one realized member, failing closed on shape or channel tamper."""
    unexpected = sorted(frozenset(entry) - (RAES_MEMBER_REQUIRED_KEYS | RAES_MEMBER_OPTIONAL_KEYS))
    if unexpected:
        raise OperationResultError(f"{field} has unexpected field(s): {', '.join(unexpected)}")
    missing = sorted(RAES_MEMBER_REQUIRED_KEYS - frozenset(entry))
    if missing:
        raise OperationResultError(f"{field} is missing field(s): {', '.join(missing)}")

    channels = _member_channels(entry, field)
    return {
        **_member_identity(entry, field),
        "participant_access_channels": channels,
        "participant_access_usernames": _member_usernames(entry, channels, field),
        **_member_credential_refs(entry, channels, field),
        **_member_sftp_root(entry, field),
    }


def _parse_private_host_results(payload: dict[str, Any]) -> dict[str, Any]:
    """Decode safe observations and immutable historical management references."""
    from shared.range_management import validate_management_access
    from shared.worker_observations import validate_worker_observations

    result = {}
    for field, validator in (
        ("worker_observations", validate_worker_observations),
        ("management_access", validate_management_access),
    ):
        if field in payload:
            try:
                result[field] = validator(payload[field])
            except (ValueError, TypeError):
                raise OperationResultError("invalid private host projection") from None
    return result
