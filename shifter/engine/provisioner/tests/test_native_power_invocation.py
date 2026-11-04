"""The final native call consumes only the exact server-issued permission."""

from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock
from uuid import uuid4

import pytest
from shared.native_power import parse_gce_power_target
from shared.raes.power_input import NativePowerInput, NativePowerMember

from tests.test_gce_range_cell_incarnation import _TARGET, _clients, _observations, _retained_incarnation


@pytest.fixture
def native_call(monkeypatch):
    import native_power_invocation

    attempt_id = uuid4()
    monkeypatch.setattr(native_power_invocation, "uuid4", lambda: attempt_id)
    operation_id, generation = uuid4(), uuid4()
    member = NativePowerMember(
        "provision.node.web#0",
        parse_gce_power_target(_TARGET, instance_id="synthetic-web"),
        _retained_incarnation(),
    )
    instance, disk = _observations()
    instance["status"] = "RUNNING"
    observed = []
    clients = _clients(instance, disk, observed)

    def changed(status, **kwargs):
        instance["status"] = status
        return NS(name="synthetic-operation")

    clients.instances.stop = Mock(side_effect=lambda **kwargs: changed("TERMINATED", **kwargs))
    clients.instances.start = Mock(side_effect=lambda **kwargs: changed("RUNNING", **kwargs))
    clients.zone_operations = NS(wait=lambda **kwargs: NS(status="DONE"))
    return NS(
        operation_id=operation_id,
        attempt_id=attempt_id,
        power=NativePowerInput(generation, (member,)),
        member=member,
        clients=clients,
        observed=observed,
    )


def permission(item, verb="pause"):
    from shared.native_participant import NativePowerInvocationGrant, native_power_invocation_id

    return NativePowerInvocationGrant(
        invocation_id=native_power_invocation_id(item.operation_id, item.member.member_ref),
        operation_id=item.operation_id,
        resource_generation=item.power.resource_generation,
        verb=verb,
        member_ref=item.member.member_ref,
        target=item.member.target,
        incarnation=item.member.incarnation,
        attempt_id=item.attempt_id,
    )


def invoke(item, acquire, verb="pause", complete=None, withdraw=None):
    from native_power_invocation import NativePowerInvocationCallbacks, invoke_native_power_member

    return invoke_native_power_member(
        operation_id=item.operation_id,
        verb=verb,
        power=item.power,
        member_ref=item.member.member_ref,
        clients=item.clients,
        callbacks=NativePowerInvocationCallbacks(
            acquire=lambda member, attempt: acquire(member), complete=complete or Mock(), withdraw=withdraw or Mock()
        ),
    )


@pytest.mark.parametrize("verb", ["pause", "resume"])
def test_exact_permission_is_acquired_after_preflight_and_used_once(native_call, verb):
    item = native_call
    if verb == "resume":
        item.clients.instances.get()["status"] = "TERMINATED"

    def acquire(member_ref):
        assert member_ref == item.member.member_ref
        assert item.observed
        item.clients.instances.stop.assert_not_called()
        item.clients.instances.start.assert_not_called()
        return permission(item, verb)

    invoke(item, acquire, verb)
    call = item.clients.instances.stop if verb == "pause" else item.clients.instances.start
    call.assert_called_once_with(
        project="synthetic-project",
        zone="europe-west3-a",
        instance="synthetic-web",
        request_id=str(permission(item, verb).invocation_id),
        timeout=10.0,
        retry=None,
    )


@pytest.mark.parametrize(
    "fault", ["id", "operation", "generation", "verb", "member", "target", "incarnation", "attempt"]
)
def test_foreign_permission_never_reaches_provider(native_call, fault):
    grant = permission(native_call)
    if fault == "id":
        grant = replace(grant, invocation_id=uuid4())
    elif fault == "operation":
        grant = replace(grant, operation_id=uuid4())
    elif fault == "generation":
        grant = replace(grant, resource_generation=uuid4())
    elif fault == "verb":
        grant = replace(grant, verb="resume")
    elif fault == "member":
        grant = replace(grant, member_ref="provision.node.foreign#0")
    elif fault == "target":
        grant = replace(grant, target=replace(grant.target, instance_name="foreign"))
    elif fault == "attempt":
        grant = replace(grant, attempt_id=uuid4())
    else:
        grant = replace(grant, incarnation=replace(grant.incarnation, instance_identity="999"))
    with pytest.raises(ValueError):
        invoke(native_call, lambda _: grant)
    native_call.clients.instances.stop.assert_not_called()
    native_call.clients.instances.start.assert_not_called()


def test_lost_permission_reply_performs_no_cloud_call(native_call):
    def lost(member_ref):
        raise TimeoutError("Synthetic reply lost after durable grant")

    withdraw = Mock()
    with pytest.raises(ValueError, match="permission unavailable"):
        invoke(native_call, lost, withdraw=withdraw)
    native_call.clients.instances.stop.assert_not_called()
    withdraw.assert_called_once_with(native_call.member.member_ref, native_call.attempt_id)


def test_successful_bounded_call_acknowledges_permission_cessation(native_call):
    complete = Mock()
    invoke(native_call, lambda _: permission(native_call), complete=complete)
    complete.assert_called_once_with(permission(native_call).invocation_id, native_call.attempt_id)


def test_uncertain_provider_result_retains_permission_exclusion(native_call):
    complete = Mock()
    native_call.clients.instances.stop.side_effect = TimeoutError("Synthetic cloud response unknown")
    with pytest.raises(TimeoutError):
        invoke(native_call, lambda _: permission(native_call), complete=complete)
    native_call.clients.instances.stop.assert_called_once()
    complete.assert_not_called()


def test_lost_completion_reply_does_not_repeat_a_cloud_call(native_call):
    complete = Mock(side_effect=TimeoutError("Synthetic cessation reply lost"))
    with pytest.raises(TimeoutError):
        invoke(native_call, lambda _: permission(native_call), complete=complete)
    native_call.clients.instances.stop.assert_called_once()
    complete.assert_called_once()
