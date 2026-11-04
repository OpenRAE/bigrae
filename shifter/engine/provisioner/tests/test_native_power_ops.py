"""Whole-range dispatch exercises fixed power calls and real read-only guest probes."""

from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock
from uuid import uuid4

import pytest
from shared.native_participant import NativePowerInvocationGrant, native_power_invocation_id
from shared.operation_results import ResultStep
from shared.raes.power_input import build_native_power_input, parse_native_power_input

import native_power_ops as ops
import raes_native_power_readiness as readiness
from executors.base import CommandResult
from gcp_range_cell_resources import HOST_PUBLIC_KEY_METADATA_KEY
from provisioner_db_operation_input import ValidatedOperationInput
from tests.test_raes_range_ops import _projection, _serialized_plan


@pytest.fixture(params=["pause", "resume"])
def run_case(request, monkeypatch):
    verb = request.param
    operation_id, request_id, generation, original_id = (uuid4() for _ in range(4))
    plan = _serialized_plan()
    node = plan["resources"].pop("node.web")
    node.update(address="provision.node.web")
    node["payload"]["count"] = 2
    plan["resources"]["provision.node.web"] = node
    raw = []
    instances, disks = {}, {}
    prefix = "projects/synthetic-project/zones/europe-west3-a"
    for index in range(2):
        name = f"synthetic-web-{index}"
        raw.append(
            {
                "uuid": f"provision.node.web#{index}",
                "instance_id": name,
                "native_power_target": {
                    "backend": "gce",
                    "project_id": "synthetic-project",
                    "zone": "europe-west3-a",
                    "instance_name": name,
                    "bootstrap_capability": "standard",
                },
                "native_power_incarnation": {
                    "instance_identity": str(100 + index),
                    "disks": [{"name": f"{name}-boot", "identity": str(200 + index)}],
                },
            }
        )
        instances[name] = {
            "id": str(100 + index),
            "status": "RUNNING" if verb == "pause" else "TERMINATED",
            "disks": [{"type": "PERSISTENT", "source": f"{prefix}/disks/{name}-boot"}],
            "metadata": {"items": [{"key": HOST_PUBLIC_KEY_METADATA_KEY, "value": "ssh-ed25519 synthetic-host-key"}]},
            "networkInterfaces": [{"networkIP": f"10.9.0.{10 + index}"}],
        }
        disks[f"{name}-boot"] = {"id": str(200 + index), "users": [f"{prefix}/instances/{name}"]}
    power_payload = build_native_power_input(plan, raw, generation, backend="gce")
    power = parse_native_power_input(power_payload, plan=plan)
    original = _projection(
        plan=plan,
        resource_generation=str(generation),
        _image_candidates={
            "gce:ubuntu": ({"image_ref": "projects/synthetic-project/global/images/original", "source_version": ""},)
        },
    )
    calls, results, guest_calls, grants, completions = [], [], [], [], []

    def mutate(status, **kwargs):
        calls.append(kwargs)
        instances[kwargs["instance"]]["status"] = status
        return NS(result=lambda timeout: None)

    clients = NS(
        instances=NS(
            get=lambda **kwargs: instances[kwargs["instance"]],
            stop=lambda **kwargs: mutate("TERMINATED", **kwargs),
            start=lambda **kwargs: mutate("RUNNING", **kwargs),
        ),
        disks=NS(get=lambda **kwargs: disks[kwargs["disk"]]),
    )

    def acquire(op_id, reference, attempt_id):
        grants.append(reference)
        member = next(member for member in power.members if member.member_ref == reference)
        return NativePowerInvocationGrant(
            invocation_id=native_power_invocation_id(op_id, reference),
            attempt_id=attempt_id,
            operation_id=op_id,
            resource_generation=generation,
            verb=verb,
            member_ref=reference,
            target=member.target,
            incarnation=member.incarnation,
        )

    transport = NS(
        acquire=acquire, complete=lambda invocation_id, attempt_id: completions.append(invocation_id), withdraw=Mock()
    )
    monkeypatch.setattr(ops.NativePowerControlClient, "from_environment", lambda: transport)
    monkeypatch.setattr(ops, "_build_clients", lambda: clients)
    monkeypatch.setattr(ops, "get_raes_operation_input", lambda **kwargs: NS(input=original))
    monkeypatch.setattr(ops, "append_operation_step_result", lambda ref, **kwargs: results.append(kwargs))
    monkeypatch.setattr(
        readiness, "existing_raes_ssh_secret", lambda range_id, reference: f"synthetic-secret:{reference}"
    )

    def guest(output, **kwargs):
        guest_calls.append(deepcopy(output))
        return NS(
            target=output["private_ip"],
            document_name="linux",
            wait_for_ready=lambda **kwargs: True,
            executor=NS(
                run_command=lambda *args, **kwargs: CommandResult(True, 0, 'ID=ubuntu\nVERSION_ID="22.04"\n', "")
            ),
            close=lambda: None,
        )

    # Only the external SSH connection is synthetic. Run the actual OS parser,
    # authored-value validator, composition verifier and final incarnation check.
    from raes_operating_system import observe_operating_systems

    monkeypatch.setattr(
        readiness,
        "observe_operating_systems",
        lambda plan, outputs: observe_operating_systems(
            plan,
            outputs,
            execution_builder=guest,
        ),
    )
    run = ValidatedOperationInput(
        str(operation_id),
        str(request_id),
        "range",
        verb,
        {
            "range_spec": plan,
            "native_power": power_payload,
            "native_provisioning_operation_id": str(original_id),
        },
    )
    monkeypatch.setattr(ops, "get_operation_input", lambda **kwargs: run)
    return NS(
        run=run,
        verb=verb,
        original=original,
        power=power,
        calls=calls,
        results=results,
        instances=instances,
        disks=disks,
        guest_calls=guest_calls,
        grants=grants,
        completions=completions,
        transport=transport,
    )


def run(item):
    ops.run_range_power(item.run.request_id, item.verb, operation_id=item.run.operation_id)


def test_native_cli_dispatch_uses_exact_grants_then_truthful_readback(run_case):
    item = run_case
    run(item)
    assert len(item.calls) == len(item.completions) == 2
    assert item.grants == [member.member_ref for member in item.power.members]

    assert [call["request_id"] for call in item.calls] == [str(value) for value in item.completions]
    assert all(call["retry"] is None and call["timeout"] == 10.0 for call in item.calls)
    if item.verb == "resume":
        assert [result["step"] for result in item.results] == [
            ResultStep.RANGE_RAES_MEMBERS_RESUMING,
            ResultStep.RANGE_RAES_MEMBERS_READY,
            ResultStep.RANGE_TERMINAL_READY,
        ]
        assert len(item.guest_calls) == 2
        assert all(output["gcp_host_ssh_username"] == "raes" for output in item.guest_calls)
    else:
        assert [result["step"] for result in item.results] == [
            ResultStep.RANGE_RAES_MEMBERS_PAUSED,
            ResultStep.RANGE_TERMINAL_PAUSED,
        ]
        assert item.guest_calls == []


@pytest.mark.parametrize("run_case", ["resume"], indirect=True)
@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "0.0.0.0", "192.0.2.1", "8.8.8.8"])  # noqa: S104 -- refused synthetic destinations
def test_resumed_guest_probes_never_target_special_use_or_public_space(run_case, address):
    run_case.instances["synthetic-web-0"]["networkInterfaces"][0]["networkIP"] = address
    with pytest.raises(RuntimeError, match="Native range power incomplete"):
        run(run_case)
    assert not run_case.guest_calls
    assert run_case.results[-1]["step"] == ResultStep.RANGE_TERMINAL_FAILED


def test_reviewed_repair_observes_already_satisfied_members_without_a_redundant_mutation(run_case):
    expected = "TERMINATED" if run_case.verb == "pause" else "RUNNING"
    for vm in run_case.instances.values():
        vm["status"] = expected
    run(run_case)
    assert run_case.calls == []
    assert len(run_case.grants) == len(run_case.completions) == 2
    assert run_case.results[-1]["step"] == (
        ResultStep.RANGE_TERMINAL_PAUSED if run_case.verb == "pause" else ResultStep.RANGE_TERMINAL_READY
    )
    assert len(run_case.guest_calls) == (0 if run_case.verb == "pause" else 2)


@pytest.mark.parametrize("run_case", ["resume"], indirect=True)
def test_guest_checks_cannot_report_ready_after_the_same_vm_stops_again(run_case, monkeypatch):

    original = readiness.verify_bootstrap_composition

    def stop_after_checks(plan, outputs):
        original(plan, outputs)
        run_case.instances["synthetic-web-0"]["status"] = "TERMINATED"

    monkeypatch.setattr(readiness, "verify_bootstrap_composition", stop_after_checks)
    with pytest.raises(RuntimeError, match="Native range power incomplete"):
        run(run_case)
    assert run_case.guest_calls
    assert run_case.results[-1]["step"] == ResultStep.RANGE_TERMINAL_FAILED


@pytest.mark.parametrize("fault", ["vm", "disk", "missing-member", "origin", "plan", "missing-origin", "no-authority"])
def test_native_refusals_never_fall_back_to_legacy_or_mutate(run_case, monkeypatch, fault):
    item = run_case
    legacy = Mock(side_effect=AssertionError("Legacy path reached"))
    import range_ops

    monkeypatch.setattr(range_ops, "run_range_pause", legacy)
    monkeypatch.setattr(range_ops, "run_range_resume", legacy)
    if fault == "vm":
        item.instances["synthetic-web-1"]["id"] = "999"
    elif fault == "disk":
        item.disks["synthetic-web-1-boot"]["id"] = "999"
    elif fault == "missing-member":
        item.run.payload["native_power"]["members"].pop()
    elif fault == "origin":
        object.__setattr__(item.original, "resource_generation", str(uuid4()))
    elif fault == "plan":
        object.__setattr__(item.original, "plan", {})
    elif fault == "missing-origin":
        del item.run.payload["native_provisioning_operation_id"]
    else:
        item.transport.acquire = Mock(side_effect=PermissionError("synthetic-private-cause"))
    with pytest.raises(RuntimeError, match="Native range power incomplete"):
        run(item)
    assert item.calls == []
    assert item.completions == []
    assert item.results[-1]["step"] == ResultStep.RANGE_TERMINAL_FAILED
    legacy.assert_not_called()


def test_partial_power_failure_preserves_only_observed_members(run_case, monkeypatch, caplog):
    item = run_case
    original = item.transport.acquire

    def deny_second(op_id, reference, attempt_id):
        if reference.endswith("#1"):
            raise PermissionError("synthetic-private-cause")
        return original(op_id, reference, attempt_id)

    item.transport.acquire = deny_second
    with pytest.raises(RuntimeError):
        run(item)
    assert len(item.calls) == 1
    assert item.results[0]["result_payload"]["members"] == [
        {
            "member_ref": "provision.node.web#0",
            "status": "paused" if item.verb == "pause" else "resuming",
        }
    ]
    assert item.results[-1]["step"] == ResultStep.RANGE_TERMINAL_FAILED
    assert "synthetic-private-cause" not in caplog.text + repr(item.results)


def test_running_guests_cannot_be_reported_ready_when_guest_probe_fails(run_case, monkeypatch):
    if run_case.verb != "resume":
        return
    monkeypatch.setattr(readiness, "observe_operating_systems", Mock(side_effect=ValueError("synthetic-private-probe")))
    with pytest.raises(RuntimeError):
        run(run_case)
    assert len(run_case.calls) == 2
    assert [result["step"] for result in run_case.results] == [
        ResultStep.RANGE_RAES_MEMBERS_RESUMING,
        ResultStep.RANGE_TERMINAL_FAILED,
    ]


def test_missing_canonical_input_cannot_enter_legacy_path(monkeypatch):
    import range_ops

    legacy = Mock()
    monkeypatch.setattr(range_ops, "run_range_pause", legacy)
    monkeypatch.setattr(ops, "get_operation_input", Mock(side_effect=ValueError("Input unavailable")))
    with pytest.raises(ValueError):
        ops.run_range_power(str(uuid4()), "pause", operation_id=str(uuid4()))
    legacy.assert_not_called()
