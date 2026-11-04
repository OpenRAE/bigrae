"""Native command admission persists original released requests before submission."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from shared.native_participant import NativeControlSubmission
from shared.raes.native_control_plane import NativeControlPlaneConfiguration
from tests.cms.test_participant_control_binding import bind, controlled_pack, controlled_source, product_range, tenant

__all__ = ["controlled_pack", "controlled_source", "product_range", "tenant"]
pytestmark = pytest.mark.django_db


@pytest.fixture
def native_request(product_range, tmp_path):
    from raes_runtime.operation_supervision_configuration import OperationSupervisionConfiguration

    from cms.services import prepare_native_control_binding
    from shared.raes.native_control_plane import create_native_control_plane
    from shared.raes.native_power_candidate import build_native_power_control_candidate
    from shared.raes.native_supervision_cursor import native_supervision_cursor
    from shared.raes.native_supervisory_requests import build_native_power_control_request
    from tests.engine.services.test_native_compiler_context import _NoDispatch
    from tests.shared.raes.test_native_participant_actions import _CutResolver
    from tests.shared.raes.test_native_participant_crossings import _CrossingOwner

    item = product_range
    view = bind(item)
    admission = prepare_native_control_binding(item.case.credential, view.id)
    native = admission.native.input
    candidate = build_native_power_control_candidate(
        scenario=item.case.scenario,
        context=native.compiler.context,
        coordinates=view.coordinates,
        power=native.power,
        selection=admission.configuration.selection,
        dispatch=_NoDispatch(),
        port=_NoDispatch(),
    )
    owner = create_native_control_plane(
        NativeControlPlaneConfiguration(
            target=candidate.target,
            scenario=item.case.scenario,
            context=native.compiler.context,
            store_root=tmp_path / "native-runtime",
            coordinates=view.coordinates,
            resolver=_CutResolver(),
            crossing_policy_resolver=_CrossingOwner(),
            enforce_final_sink_flow_control=False,
            supervision=OperationSupervisionConfiguration(admission_ms=10000, commit_ms=10000, drain_ms=5000),
        )
    ).owner
    try:
        episode = f"episode:{view.coordinates.run_id}"
        owner.initialize_participant_episode(admission.configuration.selection.participant_address, episode_id=episode)
        cursor = native_supervision_cursor(
            model=candidate.model,
            snapshot=owner.snapshot,
            participant_address=admission.configuration.selection.participant_address,
            episode_id=episode,
        )
        request_id, action_id = uuid4(), uuid4()
        prepared = build_native_power_control_request(
            model=candidate.model,
            snapshot=owner.snapshot,
            binding=candidate.bindings[0],
            episode_id=episode,
            source_ref=str(admission.configuration.id),
            evidence_ref=f"urn:shifter:native-control-command:{request_id}",
            submission=NativeControlSubmission(
                kind="proposal",
                request_id=request_id,
                proposal_id=request_id,
                action_id=action_id,
                expected_cut_digest=cursor.control_cut_digest,
                verb=candidate.bindings[0].verb,
            ),
        )
        yield SimpleNamespace(
            item=item,
            admission=admission,
            request_id=request_id,
            action_id=action_id,
            prepared=prepared,
            owner=owner,
            candidate=candidate,
            episode=episode,
        )
    finally:
        owner.close()


def persist(case, **changes):
    from cms.services._participant_control_commands import persist_native_control_command

    values = {
        "request_id": case.request_id,
        "kind": "proposal",
        "verb": "pause",
        "proposal_id": case.request_id,
        "action_id": case.action_id,
        "request": case.prepared,
    }
    values.update(changes)
    return persist_native_control_command(case.admission, **values)


def test_original_native_request_is_idempotent_and_keeps_its_requesting_proof(native_request):
    from cms.models import ParticipantControlCommand

    case = native_request
    record = persist(case)
    assert persist(case) == record
    assert record.request == case.prepared
    assert record.credential == case.item.case.credential
    assert record.portable_operation_id is None
    assert ParticipantControlCommand.objects.count() == 1
    assert "native-control-command:" not in repr(record)


@pytest.mark.parametrize("fault", ["verb", "request", "subject", "subject-ref", "proof", "generation"])
def test_inconsistent_request_or_changed_native_authority_is_never_persisted(native_request, fault):
    from cms.models import ParticipantControlCommand
    from shared.exceptions import ValidationError

    case = native_request
    changes = {}
    if fault == "verb":
        changes["verb"] = "resume"
    elif fault == "request":
        changes["request_id"] = uuid4()
    elif fault == "subject":
        changes["request"] = replace(case.prepared, subject_json=b'{"synthetic":"foreign subject"}')
    elif fault == "subject-ref":
        import json

        subject = json.loads(case.prepared.subject_json)
        subject["subject_ref"] = "synthetic:another-request"
        changes["request"] = replace(case.prepared, subject_json=json.dumps(subject).encode())
    elif fault == "proof":
        case.item.case.actor.is_active = False
        case.item.case.actor.save(update_fields=["is_active"])
    else:
        case.item.case.row.resource_generation = uuid4()
        case.item.case.row.save(update_fields=["resource_generation"])
    with pytest.raises(ValidationError):
        persist(case, **changes)
    assert not ParticipantControlCommand.objects.exists()


def test_failed_strict_command_audit_rolls_back_before_sdk_submission(native_request, monkeypatch):
    from cms.models import ParticipantControlCommand

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic native command audit unavailable")

    monkeypatch.setattr("cms.services._participant_control_commands.audit_log", unavailable)
    with pytest.raises(RuntimeError, match="native command audit unavailable"):
        persist(native_request)
    assert not ParticipantControlCommand.objects.exists()


def test_service_may_request_but_cannot_supply_the_selected_human_approval(native_request):
    from cms.models import ParticipantControlCommand
    from cms.services import prepare_native_control_binding
    from cms.services._participant_control_commands import persist_native_control_command
    from management.services import create_service_principal
    from shared.authorization import CredentialCeiling
    from shared.credentials import CredentialContext
    from shared.exceptions import ValidationError
    from shared.raes.native_supervisory_requests import build_native_power_control_request
    from tests._credential_helpers import persisted_credential

    case = native_request
    principal = create_service_principal("Synthetic supervised request service")
    case.item.case.actor.policy_principals.add(principal.uuid)
    credential = persisted_credential(
        CredentialContext(
            principal,
            "service",
            uuid4(),
            CredentialCeiling(frozenset({"event.manage_ranges"})),
            frozenset({"authorization:event.manage_ranges"}),
        )
    )
    admission = prepare_native_control_binding(credential, case.admission.view.id)
    record = persist_native_control_command(
        admission,
        request_id=case.request_id,
        kind="proposal",
        verb="pause",
        proposal_id=case.request_id,
        action_id=case.action_id,
        request=case.prepared,
    )
    assert record.credential == credential
    request_id = uuid4()
    decision = build_native_power_control_request(
        model=case.candidate.model,
        snapshot=case.owner.snapshot,
        binding=case.candidate.bindings[0],
        episode_id=case.episode,
        source_ref=str(case.admission.configuration.id),
        evidence_ref=f"urn:shifter:native-control-command:{request_id}",
        submission=NativeControlSubmission(
            kind="approval",
            request_id=request_id,
            proposal_id=case.request_id,
            action_id=case.action_id,
            expected_cut_digest=case.prepared.control_cut_digest,
            verb=case.candidate.bindings[0].verb,
        ),
    )
    with pytest.raises(ValidationError, match="Human approval required"):
        persist_native_control_command(
            admission,
            request_id=request_id,
            kind="approval",
            verb="pause",
            proposal_id=case.request_id,
            action_id=case.action_id,
            request=decision,
        )
    assert ParticipantControlCommand.objects.filter(binding_id=admission.view.id).count() == 1


def test_native_command_retains_one_sdk_correlation_without_rewriting_the_request(native_request):
    from cms.services._participant_control_commands import (
        correlate_native_control_operation,
        load_native_control_command,
    )
    from shared.exceptions import ValidationError

    original = persist(native_request)
    portable = uuid4()
    correlated = correlate_native_control_operation(original.binding_id, original.id, portable)
    assert correlated.request == original.request
    assert correlated.credential == original.credential
    assert correlated.portable_operation_id == portable
    assert correlate_native_control_operation(original.binding_id, original.id, portable) == correlated
    assert load_native_control_command(original.binding_id, original.id) == correlated
    with pytest.raises(ValidationError):
        correlate_native_control_operation(original.binding_id, original.id, uuid4())
    with pytest.raises(ValidationError):
        load_native_control_command(uuid4(), original.id)


def test_correlation_audit_failure_leaves_the_original_request_uncorrelated(native_request, monkeypatch):
    from cms.models import ParticipantControlCommand
    from cms.services._participant_control_commands import correlate_native_control_operation

    original = persist(native_request)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic native correlation audit unavailable")

    monkeypatch.setattr("cms.services._participant_control_commands.audit_log", unavailable)
    with pytest.raises(RuntimeError, match="native correlation audit unavailable"):
        correlate_native_control_operation(original.binding_id, original.id, uuid4())
    assert ParticipantControlCommand.objects.get(pk=original.id).portable_operation_uuid is None
