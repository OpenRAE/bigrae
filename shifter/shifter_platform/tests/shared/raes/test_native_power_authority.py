"""Released crossings consume the fixed native authority adapter, including revocation."""

from uuid import uuid4

import pytest

from shared.raes.native_power_session_factory import NativePowerSessionConfiguration
from tests.shared.raes.test_native_participant_actions import installed_action
from tests.shared.raes.test_native_power_session import command, session_inputs

__all__ = ["installed_action", "session_inputs"]


class _NativeAuthority:
    """Synthetic native owner with immutable commands and independently revocable permission."""

    def __init__(self):
        self.records = {}
        self.revoked = set()
        self.requests = []
        self.known_commands = set()

    def commands(self):
        return tuple(self.records.values())

    def authorize(self, command_id, *, approval_id=None):
        if command_id is None:
            return
        record = self.records[command_id]
        ids = {command_id}
        if record.kind == "action":
            assert approval_id is not None
            review = self.records[approval_id]
            assert review.kind == "approval"
            assert review.proposal_id == record.proposal_id
            ids.update((approval_id, record.proposal_id))
        if ids & self.revoked:
            raise PermissionError("Synthetic native revocation")

    def reserve(self, action):
        from uuid import UUID

        self.authorize(UUID(action.action_id), approval_id=UUID(action.approval_ref))
        self.requests.append(action)
        return uuid4()


@pytest.mark.parametrize("fault", ["current", "requester", "reviewer", "consumer"])
def test_live_native_authority_controls_released_crossings_and_reservation(session_inputs, fault):
    from shared.raes.native_power_session_factory import open_native_power_session

    native = _NativeAuthority()
    options = {
        key: value
        for key, value in session_inputs.items()
        if key not in {"resolver", "crossing_policy_resolver", "port"}
    }
    session = open_native_power_session(NativePowerSessionConfiguration(**options, port=native, authority_port=native))
    proposal, action = uuid4(), uuid4()
    try:
        for kind in ("proposal", "approval", "action"):
            record = command(session, kind, authority=native, proposal_id=proposal, action_id=action)
            native.records[record.id] = record
            if kind == "approval":
                approval = record.id
            if kind == "action" and fault != "current":
                native.revoked.add({"requester": proposal, "reviewer": approval, "consumer": action}[fault])
            result = session.submit(record)
            assert result.state == ("failed" if kind == "action" and fault != "current" else "succeeded")
        assert len(native.requests) == (1 if fault == "current" else 0)
        history = session._owner.snapshot.participant_crossing_history[session_inputs["selection"].participant_address]
        decisions = [item["occurrence"] for item in history if item["occurrence"]["stage"] == "decided"]
        assert decisions[-1]["gates"]["participant_authority"] == ("permit" if fault == "current" else "deny")
    finally:
        session.close()
