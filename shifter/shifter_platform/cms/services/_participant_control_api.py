"""Authorized native management projections and fixed product request routing."""

from uuid import UUID

from django.db import transaction

from cms.models import ParticipantControlBinding, ParticipantControlConfiguration, RaesPackageSource, RangeInstance
from engine.services import get_range_status
from shared.credentials import CredentialContext
from shared.native_participant import (
    NativeControlCommandView,
    NativeControlOperationView,
    NativeControlOptionsView,
    NativeControlStateView,
    NativeControlSubmission,
)

from ._participant_control_binding import bind_native_participant_control, prepare_native_control_binding
from ._participant_control_commands import native_control_command_catalog


def retry_native_participant_control(
    credential: CredentialContext,
    binding_id: UUID,
    command_id: UUID,
    *,
    product: str,
) -> NativeControlOperationView:
    """Recover an original request after loss or restart without accepting replacement bytes."""
    from cms.participant_control_runtime import participant_control_registry
    from shared.raes.native_supervisory_requests import original_native_power_decision

    from ._participant_control_commands import load_native_control_command

    native_control_product_subject(binding_id, product=product)
    with participant_control_registry().lease(credential, binding_id) as owner:
        command = load_native_control_command(binding_id, command_id)
        return owner.submit(
            credential,
            submission=NativeControlSubmission(
                request_id=command.id,
                kind=command.kind,
                verb=command.verb,
                proposal_id=command.proposal_id,
                action_id=command.action_id,
                expected_cut_digest=command.request.control_cut_digest,
                decision_id=original_native_power_decision(command),
            ),
        )


def native_participant_control_options(
    credential: CredentialContext,
    *,
    product: str,
    subject_uuid: UUID,
) -> NativeControlOptionsView:
    """Authorize real product custody before disclosing opaque configuration choices."""
    from django.utils import timezone

    from shared.authorization import TargetRef
    from shared.participant_control_authority import admit_participant_subject
    from shared.raes.native_power_planning import native_power_configuration_evidence
    from workspaces.services import hierarchy_target_scope, resource_scope_from_ids

    from ._content_authority import content_scope
    from ._participant_control_configuration import _configuration_digest
    from ._participant_control_input import _range_identity
    from ._participant_control_installation import require_native_control_installation
    from ._unified_authorization import require_range_action

    admission = admit_participant_subject(credential, product, subject_uuid)
    candidate = RangeInstance.objects.get(pk=admission.subject.range_instance_pk)
    snapshot = require_range_action(
        credential,
        candidate.uuid,
        "event.manage_ranges",
        authority_target=TargetRef("event", admission.subject.event_uuid),
    )
    installed = require_native_control_installation()
    scope = resource_scope_from_ids(
        kind=snapshot.scope_kind,
        account_id=snapshot.account_id,
        organization_id=snapshot.organization_id,
        workspace_id=snapshot.workspace_id,
    )
    if scope.organization_uuid is None or snapshot.range_source != product:
        raise ValueError("Native participant options unavailable")
    organization_scope = hierarchy_target_scope("organization", scope.organization_uuid)
    with transaction.atomic():
        admission.fence()
        current = RangeInstance.objects.select_for_update().get(pk=snapshot.pk)
        if _range_identity(current) != _range_identity(snapshot) or (
            current.expires_at is not None and current.expires_at <= timezone.now()
        ):
            raise ValueError("Native participant options changed")
        source = RaesPackageSource.objects.select_for_update().get(scenario_id=current.scenario_id)
        if content_scope(source) != organization_scope and not (
            content_scope(source).kind == "installation" and source.is_operator_published
        ):
            raise ValueError("Native participant options unavailable")
        configuration = ParticipantControlConfiguration.objects.filter(
            organization_uuid=scope.organization_uuid,
            source_uuid=source.pk,
            retired_at__isnull=True,
        ).first()
        binding = ParticipantControlBinding.objects.filter(range_uuid=current.uuid, invalidated_at__isnull=True).first()
        if binding is not None and (binding.product, binding.product_subject_uuid) != (product, subject_uuid):
            raise ValueError("Native participant options unavailable")
        refresh = configuration is not None and configuration.configuration_digest != _configuration_digest(
            scope.organization_uuid,
            source.pk,
            source.package_digest,
            configuration.selection,
            native_power_configuration_evidence(),
            installed.policy_digest,
        )
        return NativeControlOptionsView(
            configuration.id if configuration is not None and not refresh else None,
            binding.id if binding is not None else None,
            refresh,
        )


def native_control_product_subject(binding_id: UUID, *, product: str) -> UUID:
    """Private routing reference for the product's own authorization, never an HTTP projection."""
    return ParticipantControlBinding.objects.get(
        pk=binding_id, product=product, invalidated_at__isnull=True
    ).product_subject_uuid


def read_native_participant_control(
    credential: CredentialContext,
    binding_id: UUID,
    *,
    product: str,
    before: UUID | None = None,
) -> NativeControlStateView:
    """Authorize current custody and return at most twenty body-free request references."""
    from cms.participant_control_runtime import participant_control_registry

    native_control_product_subject(binding_id, product=product)
    with participant_control_registry().lease(credential, binding_id) as owner:
        admission = prepare_native_control_binding(credential, binding_id, qualification=owner.port.qualification)
        with transaction.atomic():
            admission.fence()
        commands = native_control_command_catalog(binding_id)
        if before is not None:
            indices = [index for index, command in enumerate(commands) if command.id == before]
            if len(indices) != 1:
                raise ValueError("Native participant request page unavailable")
            commands = commands[: indices[0]]
        page = commands[-20:]
        summaries = tuple(
            NativeControlCommandView(
                id=item.id,
                kind=item.kind,
                verb=item.verb,
                proposal_id=item.proposal_id,
                action_id=item.action_id,
                operation_id=item.portable_operation_id,
                operation_state=None
                if item.portable_operation_id is None
                else owner.session.operation_state(item.portable_operation_id),
            )
            for item in reversed(page)
        )
        instance = RangeInstance.objects.get(uuid=admission.view.range_uuid)
        if instance.range_id is None:
            raise ValueError("Native participant range unavailable")
        observed = get_range_status(instance.range_id)
        if observed is None:
            raise ValueError("Native participant range unavailable")
        status = str(observed["status"])
        return NativeControlStateView(
            admission.view, owner.session.cursor, status, summaries, page[0].id if len(commands) > len(page) else None
        )


def activate_native_participant_control(
    credential: CredentialContext,
    *,
    product: str,
    subject_uuid: UUID,
    configuration_id: UUID,
) -> NativeControlStateView:
    """Explicitly bind a preconfigured source; no request can install a provider or runtime."""
    from cms.participant_control_runtime import participant_control_registry

    participant_control_registry()
    view = bind_native_participant_control(
        credential,
        product=product,
        subject_uuid=subject_uuid,
        configuration_id=configuration_id,
    )
    return read_native_participant_control(credential, view.id, product=product)


def submit_native_participant_control(
    credential: CredentialContext,
    binding_id: UUID,
    submission: NativeControlSubmission,
    *,
    product: str,
) -> NativeControlOperationView:
    """Route one authenticated original request through the installed durable owner."""
    from cms.participant_control_runtime import participant_control_registry

    native_control_product_subject(binding_id, product=product)
    with participant_control_registry().lease(credential, binding_id) as owner:
        return owner.submit(credential, submission)
