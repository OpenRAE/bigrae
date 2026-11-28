"""Live application authority bound to an individual verified VPN certificate."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from engine.models import (
    InterruptState,
    OperationResultInbox,
    ProvisionerLaunchIntent,
    ProvisionerLaunchStatus,
    Range,
    VpnAccessProfile,
    VpnCrlState,
)
from engine.services._launch_interrupt import _request_intent_interrupt
from engine.services._range.binding_digest import range_runtime_binding_digest
from engine.services._vpn.profile_authority import (
    admit_vpn_profile_authority,
)
from engine.services._vpn.profile_operations import assert_vpn_revocation_published, queue_vpn_operation
from shared.credentials import CredentialContext, CredentialRevoked, resolve_current_credential
from shared.operation_authority import credential_reference_from_record
from shared.remote_access import parse_openvpn_capability


def request_vpn_profile(
    credential: CredentialContext, request_id: UUID, *, participation: bool = False
) -> VpnAccessProfile:
    """Admit and enqueue first issuance; repeated downloads retain the binding."""

    fields = admit_vpn_profile_authority(credential, request_id, participation=participation)
    runtime = Range.objects.select_related("request").get(request__request_id=request_id)
    deadline = parse_openvpn_capability(runtime.remote_access_capability).teardown_at
    if deadline <= timezone.now():
        raise ValueError("VPN range expired")
    with transaction.atomic():
        runtime = Range.objects.select_for_update(of=("self",)).select_related("request").get(pk=runtime.pk)
        if fields["authority_binding_digest"] != range_runtime_binding_digest(runtime) or runtime.status != "ready":
            raise ValueError("VPN range changed")
        credential_uuid = fields["credential_uuid"]
        if runtime.resource_generation is None or not isinstance(credential_uuid, UUID):
            raise ValueError("VPN range binding unavailable")
        row, created = VpnAccessProfile.objects.get_or_create(
            range=runtime,
            generation=request_id,
            resource_generation=runtime.resource_generation,
            credential_uuid=credential_uuid,
            revoked_at__isnull=True,
            defaults={**fields, "expires_at": deadline},
        )
        if row.state not in {"pending", "ready"} or row.revoked_at is not None:
            raise ValueError("VPN profile retired")
        if created:
            queue_vpn_operation(row, "issue")
    return row


def get_vpn_crl() -> str:
    """Return only a current public signed CRL to the admitted pool workload."""

    row = VpnCrlState.objects.filter(pk=1).first()
    if row is None or not row.pem or row.expires_at is None or row.expires_at <= timezone.now():
        raise ValueError("VPN CRL unavailable")
    return row.pem


def reconcile_vpn_profiles(*, limit: int = 100) -> int:
    """Retire permanently invalid proofs; refresh CRLs through the same native queue."""

    retired = 0
    rows = (
        VpnAccessProfile.objects.filter(state__in=["pending", "ready"])
        .select_related("range__request")
        .order_by("updated_at")[: min(max(limit, 1), 250)]
    )
    for row in rows:
        invalid = _profile_permanently_invalid(row)
        if invalid is None:
            continue
        with transaction.atomic():
            current = VpnAccessProfile.objects.select_for_update().get(pk=row.pk)
            if invalid and current.revoked_at is None:
                current.state, current.revoked_at = "revoked", timezone.now()
                current.save(update_fields=["state", "revoked_at", "updated_at"])
                request_vpn_issuance_interrupt(current)
                retired += 1
            elif not invalid:
                current.save(update_fields=["updated_at"])
    _recover_vpn_maintenance(limit)
    # A receipt that arrives after revocation must still be cleaned up.
    for row in VpnAccessProfile.objects.filter(state="revoked", secret_removed_at__isnull=True).order_by("updated_at")[
        : min(max(limit, 1), 250)
    ]:
        _reconcile_revoked_profile(row)
    _refresh_vpn_crl()
    return retired


def _refresh_vpn_crl() -> None:
    """Queue renewal of the accepted public revocation list before it expires."""

    state = VpnCrlState.objects.filter(pk=1).first()
    if state is not None and (
        state.expires_at is None
        or state.expires_at <= timezone.now() + timedelta(hours=12)
        or state.requested_revision > state.published_revision
    ):
        candidate = (
            VpnAccessProfile.objects.filter(secret_removed_at__isnull=True)
            .exclude(certificate_serial="")
            .order_by("updated_at")
            .first()
        )
        if candidate is not None and _pki_operation_finished(candidate):
            with transaction.atomic():
                candidate = VpnAccessProfile.objects.select_for_update().get(pk=candidate.pk)
                # The state lock serializes this check with queue_vpn_operation.
                VpnCrlState.objects.select_for_update().get(pk=1)
                if _pki_operation_finished(candidate) and not _crl_refresh_in_flight():
                    queue_vpn_operation(candidate, "refresh-crl")


def _crl_refresh_in_flight() -> bool:
    """Find a queued CRL refresh that has no accepted terminal result yet."""

    finished = OperationResultInbox.objects.filter(
        operation_id=OuterRef("provisioner_operation_id"), result_kind="TERMINAL_SUCCESS", disposition="APPLIED"
    )
    return (
        VpnAccessProfile.objects.filter(provisioner_operation="refresh-crl", secret_removed_at__isnull=True)
        .exclude(Exists(finished))
        .exists()
    )


def _issuance_unconfirmed(profile: VpnAccessProfile) -> bool:
    """Exhausted dispatch or a missing bounded issuer receipt requires recovery."""

    if profile.state != "pending" or profile.issuance_operation_id is None:
        return False
    origin = ProvisionerLaunchIntent.objects.filter(operation_id=profile.issuance_operation_id).first()
    if origin is None:
        return False
    return origin.status == ProvisionerLaunchStatus.DLQ or (
        origin.status == ProvisionerLaunchStatus.SUCCEEDED
        and origin.launched_at is not None
        and origin.launched_at <= timezone.now() - timedelta(minutes=15)
    )


def _pki_operation_finished(profile: VpnAccessProfile) -> bool:
    """Check accepted native terminal evidence for the current PKI generation."""

    if profile.provisioner_operation_id is None:
        return False
    return OperationResultInbox.objects.filter(
        operation_id=profile.provisioner_operation_id, result_kind="TERMINAL_SUCCESS", disposition="APPLIED"
    ).exists()


def _recover_vpn_maintenance(limit: int) -> None:
    """Reuse native interruption for failed or unconfirmed PKI maintenance."""

    rows = VpnAccessProfile.objects.filter(
        provisioner_operation__in=["revoke", "purge", "refresh-crl"], secret_removed_at__isnull=True
    ).order_by("updated_at")[: min(max(limit, 1), 250)]
    for row in rows:
        with transaction.atomic():
            current = VpnAccessProfile.objects.select_for_update().get(pk=row.pk)
            if current.provisioner_operation_id is None or not _pki_operation_unconfirmed(current):
                continue
            intent = ProvisionerLaunchIntent.objects.select_for_update().get(
                operation_id=current.provisioner_operation_id
            )
            if intent.payload != {
                "version": 1,
                "resource": "vpn-profile",
                "operation": current.provisioner_operation,
                "request_id": str(current.generation),
                "profile_id": str(current.pk),
            }:
                raise ValueError("VPN maintenance identity changed")
            _request_intent_interrupt(intent)


def _pki_operation_unconfirmed(profile: VpnAccessProfile) -> bool:
    """Detect dispatched or failed PKI work that still requires native convergence."""

    if profile.provisioner_operation_id is None or _pki_operation_finished(profile):
        return False
    intent = ProvisionerLaunchIntent.objects.filter(operation_id=profile.provisioner_operation_id).first()
    return intent is not None and (
        intent.status == ProvisionerLaunchStatus.DLQ
        or (
            intent.status == ProvisionerLaunchStatus.SUCCEEDED
            and intent.launched_at is not None
            and intent.launched_at <= timezone.now() - timedelta(minutes=15)
        )
        or OperationResultInbox.objects.filter(
            operation_id=profile.provisioner_operation_id,
            result_kind="TERMINAL_FAILURE",
            disposition="APPLIED",
        ).exists()
    )


def request_vpn_issuance_interrupt(profile: VpnAccessProfile) -> None:
    """Reuse native cancellation before deleting a possibly in-flight profile."""

    if profile.issuance_operation_id is None:
        return
    origin = ProvisionerLaunchIntent.objects.select_for_update().get(operation_id=profile.issuance_operation_id)
    if origin.interrupt_state == InterruptState.NONE:
        now = timezone.now()
        origin.interrupt_state = InterruptState.REQUESTED
        origin.interrupt_requested_at = origin.interrupt_next_attempt_at = now
        origin.interrupt_deadline = now + timedelta(minutes=15)
        origin.save(
            update_fields=[
                "interrupt_state",
                "interrupt_requested_at",
                "interrupt_next_attempt_at",
                "interrupt_deadline",
            ]
        )
    if not origin.task_ref and origin.interrupt_state == InterruptState.REQUESTED:
        # As in the native interrupt controller, no reserved provider identity
        # means dispatch was unconfigured; the interrupt prevents later launch.
        queue_vpn_operation(profile, "revoke")
        origin.interrupt_state = InterruptState.DESTROY_ENQUEUED
        origin.save(update_fields=["interrupt_state"])


def _profile_permanently_invalid(row: VpnAccessProfile) -> bool | None:
    """Distinguish permanent proof expiry from reversible policy and provider outages."""
    invalid = (
        row.expires_at <= timezone.now()
        or row.range.resource_generation != row.resource_generation
        or row.range.status in {"destroying", "destroyed"}
        or _issuance_unconfirmed(row)
    )
    try:
        resolve_current_credential(credential_reference_from_record(row))
    except CredentialRevoked:
        invalid = True
    except Exception:  # noqa: BLE001  # an outage or reversible denial defers revocation; the next pass retries
        # Admission still fails closed. A dependency outage or reversible
        # policy denial does not irreversibly revoke an issued certificate.
        if not invalid:
            return None
    return invalid


def _reconcile_revoked_profile(row: VpnAccessProfile) -> None:
    """Advance retained revocation evidence before scheduling private-material cleanup."""

    with transaction.atomic():
        current = VpnAccessProfile.objects.select_for_update().get(pk=row.pk)
        if current.provisioner_operation in {"revoke", "purge", "refresh-crl"} and not _pki_operation_finished(current):
            # The existing interrupt worker owns replacement after absence.
            pass
        elif current.revocation_operation_id is not None and current.provisioner_operation != "purge":
            try:
                assert_vpn_revocation_published(current)
            except ValueError:
                pass
            else:
                queue_vpn_operation(current, "purge")
        elif current.provisioner_operation not in {"revoke", "purge", "refresh-crl"}:
            request_vpn_issuance_interrupt(current)
        current.save(update_fields=["updated_at"])
