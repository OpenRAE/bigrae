"""Tests for GCP range pause/resume dispatch and capability preflight (#614).

Covers the provisioner tier: VM Runtime / GCE power-op wiring, and the
fail-before-mutation capability preflight that refuses a range whose realized
asset mix (e.g. a scenario Pod) cannot be losslessly paused.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import gce_range_cell_power
import gdc_vmruntime_assets
import range_ops
from range_ops import _execute_instance_operation, run_range_pause, run_range_resume
from range_ops._pause_resume import UnsupportedRangeLifecycleError


def _entry(mode: str, provider: str, asset_type: str) -> dict:
    return {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "name": "guest",
        "role": "victim",
        "cloud_provider": provider,
        "asset_type": asset_type,
        "operation_mode": mode,
        "state": {
            "gdc_namespace": "ns",
            "gdc_vm_name": "vm",
            "gcp_project_id": "p",
            "gcp_zone": "z",
            "gcp_instance_name": "vm",
        },
    }


class TestExecuteInstanceOperation:
    def test_gdc_vm_runtime_pause_calls_stop(self, monkeypatch):
        calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: calls.append((op, state)))
        _uuid, ok, err = _execute_instance_operation(
            None, None, None, _entry("gdc_vm_runtime", "gcp", "vm_runtime_vm"), operation="pause"
        )
        assert (ok, err) == (True, None)
        assert calls[0][0] == "stop"

    def test_gdc_vm_runtime_resume_calls_start(self, monkeypatch):
        calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: calls.append((op, state)))
        _execute_instance_operation(
            None, None, None, _entry("gdc_vm_runtime", "gcp", "vm_runtime_vm"), operation="resume"
        )
        assert calls[0][0] == "start"

    def test_gce_vm_pause_calls_stop(self, monkeypatch):
        calls = []
        monkeypatch.setattr(gce_range_cell_power, "run_power_operation", lambda op, state: calls.append((op, state)))
        _uuid, ok, err = _execute_instance_operation(
            None, None, None, _entry("gce_vm", "gcp", "gce_vm"), operation="pause"
        )
        assert (ok, err) == (True, None)
        assert calls[0][0] == "stop"

    def test_scenario_pod_reports_failure(self):
        _uuid, ok, err = _execute_instance_operation(
            None, None, None, _entry("gdc_scenario_pod", "gcp", "scenario_pod"), operation="pause"
        )
        assert ok is False
        assert err

    def test_provider_failure_does_not_disclose_private_diagnostics(self, monkeypatch, caplog):
        def fail(*args, **kwargs):
            raise RuntimeError("credential=synthetic-provider-private-value")

        monkeypatch.setattr(gce_range_cell_power, "run_power_operation", fail)

        _, ok, error = _execute_instance_operation(
            None, None, None, _entry("gce_vm", "gcp", "gce_vm"), operation="pause"
        )

        assert not ok
        assert error == "Native lifecycle operation failed"
        assert "synthetic-provider-private-value" not in caplog.text

    def test_failed_provider_result_stays_private(self):
        instance = {**_entry("aws", "aws", "vm_runtime_vm"), "aws_instance_id": "instance"}
        orchestrator = SimpleNamespace(
            orchestrate=lambda *args: SimpleNamespace(success=False, error="synthetic-provider-private-value")
        )
        plan = SimpleNamespace(get_context=lambda identifier: None)

        _, ok, error = _execute_instance_operation(object(), orchestrator, plan, instance, operation="pause")

        assert not ok
        assert error == "Native lifecycle operation failed"


class TestCapabilityPreflight:
    def _stub_common(self, monkeypatch, instances, backend="gdc"):
        monkeypatch.setattr(
            range_ops, "get_range_data_by_request_id", lambda rid: {"status": "ready", "range_backend": backend}
        )
        monkeypatch.setattr(range_ops, "get_range_instance_ids", lambda rid: instances)
        appended: list = []
        monkeypatch.setattr(
            range_ops._pause_resume, "append_operation_step_result", lambda *a, **k: appended.append((a, k))
        )
        aws = MagicMock(name="AWSExecutor")
        monkeypatch.setattr(range_ops, "AWSExecutor", aws)
        return appended, aws

    @pytest.mark.parametrize("operation", ["pause", "resume"])
    def test_shared_resource_provider_error_is_private(self, monkeypatch, caplog, operation):
        self._stub_common(monkeypatch, [_entry("gdc_vm_runtime", "gcp", "vm_runtime_vm")])
        monkeypatch.setattr(
            range_ops,
            "get_range_data_by_request_id",
            lambda rid: {"status": "ready" if operation == "pause" else "paused", "range_backend": "gdc"},
        )
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda *a: None)

        def fail(*args, **kwargs):
            raise RuntimeError("synthetic-provider-private-value")

        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", fail)
        monkeypatch.setattr(range_ops, "ensure_ngfw_running", fail)

        if operation == "pause":
            run_range_pause("req-1", operation_id="op-1")
        else:
            with pytest.raises(RuntimeError, match="NGFW start failed") as failure:
                run_range_resume("req-1", operation_id="op-1")
            assert failure.value.__cause__ is None

        assert "synthetic-provider-private-value" not in caplog.text

    @pytest.mark.parametrize("operation", ["pause", "resume"])
    def test_empty_range_cannot_mutate_shared_resources(self, monkeypatch, operation):
        self._stub_common(monkeypatch, [], backend="gce")
        monkeypatch.setattr(
            range_ops,
            "get_range_data_by_request_id",
            lambda rid: {"status": "ready" if operation == "pause" else "paused", "range_backend": "gce"},
        )
        mutations = []
        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", lambda *a, **k: mutations.append("pause"))
        monkeypatch.setattr(range_ops, "ensure_ngfw_running", lambda *a, **k: mutations.append("resume"))

        with pytest.raises(UnsupportedRangeLifecycleError):
            (run_range_pause if operation == "pause" else run_range_resume)("req-1", operation_id="op-1")

        assert mutations == []

    @pytest.mark.parametrize("operation", ["pause", "resume"])
    def test_partial_failure_retains_observed_member_outcomes(self, monkeypatch, operation):
        first = _entry("gdc_vm_runtime", "gcp", "vm_runtime_vm")
        second = {**_entry("gdc_vm_runtime", "gcp", "vm_runtime_vm"), "uuid": "22222222-2222-4222-8222-222222222222"}
        second["state"] = {**second["state"], "gdc_vm_name": "other"}
        appended, _ = self._stub_common(monkeypatch, [first, second])
        monkeypatch.setattr(
            range_ops,
            "get_range_data_by_request_id",
            lambda rid: {"status": "ready" if operation == "pause" else "paused", "range_backend": "gdc"},
        )
        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", lambda *a, **k: None)
        monkeypatch.setattr(range_ops, "ensure_ngfw_running", lambda *a, **k: None)

        def power(verb, state):
            if state["gdc_vm_name"] == "other":
                raise RuntimeError("synthetic private failure")

        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", power)

        with pytest.raises(RuntimeError, match="Failed to"):
            (run_range_pause if operation == "pause" else run_range_resume)("req-1", operation_id="op-1")

        payloads = [kwargs["result_payload"] for _, kwargs in appended]
        from shared.operation_results import parse_result_payload

        for _, kwargs in appended:
            assert (
                parse_result_payload(
                    kwargs["resource"], kwargs["operation"], step=kwargs["step"], payload=kwargs["result_payload"]
                )
                == kwargs["result_payload"]
            )
        assert payloads == [
            {
                "instances": [
                    {
                        "instance_uuid": "11111111-1111-4111-8111-111111111111",
                        "status": "paused" if operation == "pause" else "ready",
                    }
                ]
            },
            {"reason_code": "cloud_operation_failed", "diagnostic": f"Failed to {operation} 1/2 instances"},
        ]

    @pytest.mark.parametrize("operation", ["pause", "resume"])
    def test_gce_range_checks_every_footprint_before_any_power_call(self, monkeypatch, operation):
        first = _entry("gce_vm", "gcp", "gce_vm")
        second = {**_entry("gce_vm", "gcp", "gce_vm"), "uuid": "22222222-2222-4222-8222-222222222222"}
        second["state"] = {**second["state"], "gcp_instance_name": "other"}
        appended, _ = self._stub_common(monkeypatch, [first, second], backend="gce")
        monkeypatch.setattr(
            range_ops,
            "get_range_data_by_request_id",
            lambda rid: {"status": "ready" if operation == "pause" else "paused", "range_backend": "gce"},
        )
        mutations = []
        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", lambda *a, **k: mutations.append("ngfw-stop"))
        monkeypatch.setattr(range_ops, "ensure_ngfw_running", lambda *a, **k: mutations.append("ngfw-start"))
        monkeypatch.setattr(range_ops, "_update_instance_statuses", lambda *a, **k: None)

        def get(**kwargs):
            return {
                "id": "12345" if kwargs["instance"] == "vm" else "67890",
                "status": "TERMINATED" if operation == "pause" else "RUNNING",
                "disks": [{"type": "PERSISTENT" if kwargs["instance"] == "vm" else "SCRATCH", "source": "disk"}],
            }

        clients = SimpleNamespace(
            instances=SimpleNamespace(
                get=get,
                stop=lambda **kwargs: mutations.append("stop") or {"name": "stop"},
                start=lambda **kwargs: mutations.append("start") or {"name": "start"},
            ),
            zone_operations=SimpleNamespace(wait=lambda **kwargs: {"status": "DONE"}),
        )
        monkeypatch.setattr(gce_range_cell_power, "_build_clients", lambda: clients)

        with pytest.raises(UnsupportedRangeLifecycleError):
            (run_range_pause if operation == "pause" else run_range_resume)("req-1", operation_id="op-1")

        assert mutations == []
        assert appended[-1][1]["result_payload"]["reason_code"] == "unsupported_capability"

    def test_pause_with_scenario_pod_fails_before_mutation(self, monkeypatch):
        instances = [
            _entry("gdc_vm_runtime", "gcp", "vm_runtime_vm"),
            _entry("gdc_scenario_pod", "gcp", "scenario_pod"),
        ]
        appended, aws = self._stub_common(monkeypatch, instances)
        vm_calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: vm_calls.append(op))

        with pytest.raises(UnsupportedRangeLifecycleError):
            run_range_pause("req-1", operation_id="op-1")

        # No mutation: no VM power op, no AWS executor built.
        assert vm_calls == []
        aws.assert_not_called()
        # Reported an unsupported_capability terminal failure.
        payloads = [k["result_payload"] for a, k in appended if "result_payload" in k]
        assert any(p.get("reason_code") == "unsupported_capability" for p in payloads)

    def test_resume_with_scenario_pod_does_not_start_ngfw(self, monkeypatch):
        instances = [_entry("gdc_scenario_pod", "gcp", "scenario_pod")]
        self._stub_common(monkeypatch, instances)
        # A resume target is PAUSED; otherwise the idempotent no-op returns early.
        monkeypatch.setattr(
            range_ops, "get_range_data_by_request_id", lambda rid: {"status": "paused", "range_backend": "gdc"}
        )
        ngfw_calls = []
        monkeypatch.setattr(range_ops, "ensure_ngfw_running", lambda rid, ref=None: ngfw_calls.append(rid))

        with pytest.raises(UnsupportedRangeLifecycleError):
            run_range_resume("req-1", operation_id="op-1")

        # Capability check runs before the NGFW cascade.
        assert ngfw_calls == []

    def test_pause_supported_gdc_range_runs_power_op(self, monkeypatch):
        instances = [_entry("gdc_vm_runtime", "gcp", "vm_runtime_vm")]
        _appended, aws = self._stub_common(monkeypatch, instances)
        monkeypatch.setattr(range_ops, "_update_instance_statuses", lambda *a, **k: None)
        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", lambda rid, ref=None: None)
        vm_calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: vm_calls.append(op))

        run_range_pause("req-1", operation_id="op-1")

        assert vm_calls == ["stop"]
        aws.assert_not_called()  # GCP-only range does not build the AWS executor

    def test_resume_supported_gdc_range_runs_start(self, monkeypatch):
        instances = [_entry("gdc_vm_runtime", "gcp", "vm_runtime_vm")]
        self._stub_common(monkeypatch, instances)
        monkeypatch.setattr(
            range_ops, "get_range_data_by_request_id", lambda rid: {"status": "paused", "range_backend": "gdc"}
        )
        monkeypatch.setattr(range_ops, "_update_instance_statuses", lambda *a, **k: None)
        monkeypatch.setattr(range_ops, "ensure_ngfw_running", lambda rid, ref=None: None)
        vm_calls = []
        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", lambda op, state: vm_calls.append(op))

        run_range_resume("req-1", operation_id="op-1")

        assert vm_calls == ["start"]

    def test_pause_supported_gce_range_runs_stop(self, monkeypatch):
        instances = [_entry("gce_vm", "gcp", "gce_vm")]
        _appended, aws = self._stub_common(monkeypatch, instances, backend="gce")
        monkeypatch.setattr(range_ops, "_update_instance_statuses", lambda *a, **k: None)
        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", lambda rid, ref=None: None)
        gce_calls = []
        clients = SimpleNamespace(
            instances=SimpleNamespace(
                get=lambda **kwargs: {
                    "id": "12345",
                    "status": "TERMINATED",
                    "disks": [{"type": "PERSISTENT", "source": "disk"}],
                },
                stop=lambda **kwargs: gce_calls.append("stop") or {"name": "stop"},
            ),
            zone_operations=SimpleNamespace(wait=lambda **kwargs: {"status": "DONE"}),
        )
        monkeypatch.setattr(gce_range_cell_power, "_build_clients", lambda: clients)

        run_range_pause("req-1", operation_id="op-1")

        assert gce_calls == ["stop"]
        aws.assert_not_called()

    def test_pause_reports_terminal_failure_on_backend_error(self, monkeypatch):
        instances = [_entry("gdc_vm_runtime", "gcp", "vm_runtime_vm")]
        appended, _aws = self._stub_common(monkeypatch, instances)
        monkeypatch.setattr(range_ops, "_update_instance_statuses", lambda *a, **k: None)
        monkeypatch.setattr(range_ops, "pause_ngfw_for_range", lambda rid, ref=None: None)

        def _boom(op, state):
            raise RuntimeError("kubectl virt stop failed")

        monkeypatch.setattr(gdc_vmruntime_assets, "run_power_operation", _boom)

        with pytest.raises(RuntimeError, match="Failed to pause"):
            run_range_pause("req-1", operation_id="op-1")

        payloads = [k["result_payload"] for a, k in appended if "result_payload" in k]
        assert any(p.get("reason_code") == "cloud_operation_failed" for p in payloads)
