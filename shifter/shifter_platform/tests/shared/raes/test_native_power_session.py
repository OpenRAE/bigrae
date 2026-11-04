"""The installed session retains released ownership and exact native requests."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from shared.authorization import CredentialCeiling
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef
from shared.native_participant import NativeControlCommandRecord
from shared.raes.native_power_session_factory import NativePowerSessionConfiguration
from tests.shared.raes.test_native_participant_actions import _CutResolver, installed_action
from tests.shared.raes.test_native_participant_crossings import _crossing_evidence, _CrossingOwner
from tests.shared.raes.test_native_power_candidate import candidate_configuration

__all__ = ["installed_action"]
_SOURCE = Path(__file__).parent / "fixtures/control/participant-power-admission.sdl.yaml"


class _SessionAuthority(_CutResolver):
    """Synthetic trusted owner recognizes only the test's persisted command IDs."""

    def __init__(self):
        self.known_commands = set()

    def resolve_cut(self, policy, intent, snapshot):
        cut = super().resolve_cut(policy, intent, snapshot)
        return cut.model_copy(update={"evidence_refs": ["fixture:authority", *sorted(self.known_commands)]})


@pytest.fixture
def session_inputs(installed_action, tmp_path):
    config = candidate_configuration(installed_action)
    config.pop("scenario")
    config.pop("dispatch")
    crossing = _CrossingOwner()
    crossing.evidence.add("shifter-native-power-supervision-candidate/v1")
    resolver = _SessionAuthority()
    installed_action[4].resolver = resolver
    return {
        **config,
        "binding_id": uuid4(),
        "scenario_path": _SOURCE,
        "store_root": tmp_path,
        "resolver": resolver,
        "crossing_policy_resolver": crossing,
        "source_ref": "urn:shifter:synthetic-configuration",
        "principal_uuid": uuid4(),
        "has_unresolved_invocation": lambda: False,
    }


def command(session, kind, *, authority, proposal_id, action_id, verb="pause", decision_id=None):
    request_id = proposal_id if kind == "proposal" else action_id if kind == "action" else uuid4()
    prepared = session.prepare(
        kind=kind,
        verb=verb,
        request_id=request_id,
        proposal_id=proposal_id,
        action_id=action_id,
        expected_cut_digest=session.cursor.control_cut_digest,
        decision_id=decision_id,
    )
    authority.known_commands.add(f"urn:shifter:control-command:{request_id}")
    return NativeControlCommandRecord(
        request_id,
        session.binding_id,
        kind,
        verb,
        proposal_id,
        action_id,
        prepared,
        CredentialContext(
            PrincipalRef(uuid4(), "human"), "session", uuid4(), CredentialCeiling(frozenset()), frozenset()
        ),
    )


def test_session_reopens_the_original_episode_and_retries_original_action_once(session_inputs):
    from shared.raes.native_power_session_factory import open_native_power_session

    first = open_native_power_session(NativePowerSessionConfiguration(**session_inputs))
    proposal_id, action_id = uuid4(), uuid4()
    try:
        for kind in ("proposal", "approval", "action"):
            record = command(
                first, kind, authority=session_inputs["resolver"], proposal_id=proposal_id, action_id=action_id
            )
            outcome = first.submit(record, crossing_evidence=_crossing_evidence())
            status = first._owner.get_operation(str(outcome.operation_id))
            assert outcome.state == "succeeded", (kind, status.diagnostics)
        original = outcome.operation_id
        assert first.submit(record, crossing_evidence=_crossing_evidence()).operation_id == original
        expected_cursor = first.cursor
        assert len(session_inputs["port"].requests) == 1
    finally:
        first.close()
    recovered = open_native_power_session(NativePowerSessionConfiguration(**session_inputs))
    try:
        assert recovered.cursor == expected_cursor
        assert recovered.submit(record, crossing_evidence=_crossing_evidence()).operation_id == original
        assert len(session_inputs["port"].requests) == 1
    finally:
        recovered.close()


def test_an_initialized_native_binding_cannot_recreate_a_missing_episode(session_inputs):
    from shared.raes.native_power_session_factory import open_native_power_session

    first = open_native_power_session(NativePowerSessionConfiguration(**session_inputs))
    expected = first.cursor
    first.close()
    recovered = open_native_power_session(NativePowerSessionConfiguration(**session_inputs, allow_initialize=False))
    assert recovered.cursor == expected
    recovered.close()
    original_root = session_inputs["store_root"]
    original_root.rename(original_root.with_name(original_root.name + "-retained"))
    original_root.mkdir()
    for _ in range(2):
        with pytest.raises(ValueError, match="runtime history unavailable"):
            open_native_power_session(NativePowerSessionConfiguration(**session_inputs, allow_initialize=False))


def test_open_invocation_prevents_control_mutation_and_owner_close(session_inputs):
    from shared.raes.native_power_session_factory import open_native_power_session

    unresolved = False
    owner = open_native_power_session(
        NativePowerSessionConfiguration(**{**session_inputs, "has_unresolved_invocation": lambda: unresolved})
    )
    record = command(owner, "proposal", authority=session_inputs["resolver"], proposal_id=uuid4(), action_id=uuid4())
    try:
        unresolved = True
        with pytest.raises(ValueError, match="Native invocation remains unresolved"):
            owner.submit(record, crossing_evidence=_crossing_evidence())
        with pytest.raises(ValueError, match="Native invocation remains unresolved"):
            owner.close()
        assert owner.cursor.history_head == 0
    finally:
        unresolved = False
        owner.close()


def test_session_refuses_a_command_from_another_native_binding(session_inputs):
    from shared.raes.native_power_session_factory import open_native_power_session

    owner = open_native_power_session(NativePowerSessionConfiguration(**session_inputs))
    try:
        record = command(
            owner, "proposal", authority=session_inputs["resolver"], proposal_id=uuid4(), action_id=uuid4()
        )
        with pytest.raises(ValueError, match="Native participant request unavailable"):
            owner.submit(replace(record, binding_id=uuid4()), crossing_evidence=_crossing_evidence())
        assert owner.cursor.history_head == 0
    finally:
        owner.close()


def test_original_cancellation_target_cannot_change_during_retry(session_inputs):
    from shared.raes.native_power_session_factory import open_native_power_session
    from shared.raes.native_supervisory_requests import native_power_retry_request

    owner = open_native_power_session(NativePowerSessionConfiguration(**session_inputs))
    proposal, action, decision = uuid4(), uuid4(), uuid4()
    try:
        original = command(
            owner,
            "cancellation",
            authority=session_inputs["resolver"],
            proposal_id=proposal,
            action_id=action,
            decision_id=decision,
        )
        assert native_power_retry_request(original, decision_id=decision) == original.request
        for changed in (None, uuid4()):
            with pytest.raises(ValueError, match="Native supervisory request unavailable"):
                native_power_retry_request(original, decision_id=changed)
    finally:
        owner.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "urn:shifter:principal:foreign"),
        ("target_scope", "target:foreign"),
        ("run_scope", "run:foreign"),
        ("authorization_scope", ("role:foreign",)),
    ],
)
def test_original_receipt_lookup_refuses_foreign_scope_before_returning_a_result(
    session_inputs, monkeypatch, field, value
):
    from shared.raes.native_power_session_factory import open_native_power_session

    owner = open_native_power_session(NativePowerSessionConfiguration(**session_inputs))
    try:
        record = command(
            owner, "proposal", authority=session_inputs["resolver"], proposal_id=uuid4(), action_id=uuid4()
        )
        outcome = owner.submit(record, crossing_evidence=_crossing_evidence())
        original = owner._store.find_by_idempotency(f"native-command:{record.id}")
        assert original is not None
        foreign = original.receipt.context.model_copy(update={field: value})
        candidate = replace(
            original,
            receipt=replace(original.receipt, context=foreign),
            status=replace(original.status, context=foreign),
        )
        monkeypatch.setattr(owner._store, "find_by_idempotency", lambda *args, **kwargs: candidate)
        with pytest.raises(ValueError, match="Native participant request unavailable"):
            owner.submit(record, crossing_evidence=_crossing_evidence())
        assert owner._owner.get_operation(str(outcome.operation_id)) is not None
    finally:
        owner.close()
