"""Owning target locks shared by launch admission and failure settlement."""

from uuid import UUID

from engine.models import GcpRangeProject, Instance, Range, VpnAccessProfile, WorkerTrial


def lock_provisioner_target(
    payload: dict[str, object],
) -> Range | Instance | VpnAccessProfile | GcpRangeProject | WorkerTrial | None:
    """Lock the named target before its intent, inside the caller's transaction.

    A missing or malformed target cannot authorize an effect. Returning None
    still lets the worker settle a stale delivery lease without inventing state.
    Generation, custody and input checks remain with the owning validators.
    """
    resource = payload.get("resource")
    target: Range | Instance | VpnAccessProfile | GcpRangeProject | WorkerTrial | None = None
    try:
        if resource == "range-project":
            target = GcpRangeProject.objects.select_for_update().filter(pk=UUID(str(payload.get("request_id")))).first()
        elif resource == "vpn-profile":
            target = (
                VpnAccessProfile.objects.select_for_update(of=("self",))
                .filter(pk=UUID(str(payload.get("profile_id"))))
                .first()
            )
        elif resource == "worker-trial":
            target = (
                WorkerTrial.objects.select_for_update(of=("self",))
                .filter(pk=UUID(str(payload.get("trial_id"))))
                .first()
            )
        elif resource in {"range", "raes-range", "ngfw"}:
            if "request_id" in payload:
                request_id = UUID(str(payload["request_id"]))
                target = _lock_requested_target(request_id, ngfw=resource == "ngfw")
            else:
                target = (
                    Range.objects.select_for_update(of=("self",)).filter(pk=int(str(payload.get("range_id")))).first()
                )
    except (TypeError, ValueError):
        return None
    return target


def _lock_requested_target(request_id: UUID, *, ngfw: bool) -> Range | Instance | None:
    """Lock only the native target kind identified by the retained request."""
    if ngfw:
        return (
            Instance.objects.select_for_update(of=("self",))
            .filter(request__request_id=request_id, role=Instance.Role.NGFW)
            .first()
        )
    return Range.objects.select_for_update(of=("self",)).filter(request__request_id=request_id).first()
