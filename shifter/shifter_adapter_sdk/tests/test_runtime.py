"""Reject replay, target escalation and ambiguous worker messages."""

import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from shifter_adapter_sdk.runtime import (
    MAX_OUTPUT_BYTES,
    PROTOCOL,
    GuestAction,
    InspectionInput,
    PluginManifest,
    RuntimeInput,
    RuntimePlan,
    canonical_digest,
    parse_input,
    parse_result,
)
from shifter_adapter_sdk.worker import inspect_invocation, main, plan_invocation


def _with_file(request, content=b"synthetic parameters\n"):
    payload = request.model_dump(mode="json")
    payload["manifest"]["required_files"] = ["parameters"]
    payload["files"] = {
        "parameters": {"sha256": "sha256:" + hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
    }
    return payload


def test_apparatus_input_has_explicit_protocol_and_no_pack_identity(request_input):
    payload = request_input.model_dump(mode="json")
    payload.pop("pack_digest")
    payload["apparatus_digest"] = "sha256:" + "c" * 64
    payload["protocol"] = payload["manifest"]["protocol"] = "bigrae.runtime-plugin/v2"
    parsed = RuntimeInput.model_validate(payload)
    assert parsed.pack_digest is None
    assert parsed.apparatus_digest == payload["apparatus_digest"]
    assert "pack_digest" not in parsed.model_dump(mode="json")
    payload["protocol"] = payload["manifest"]["protocol"] = PROTOCOL
    with pytest.raises(ValueError):
        RuntimeInput.model_validate(payload)


def test_apparatus_cannot_impersonate_a_pack(request_input):
    payload = request_input.model_dump(mode="json")
    payload["apparatus_digest"] = "sha256:" + "c" * 64
    payload["protocol"] = payload["manifest"]["protocol"] = "bigrae.runtime-plugin/v2"
    with pytest.raises(ValueError):
        RuntimeInput.model_validate(payload)


@pytest.fixture
def manifest():
    return PluginManifest(
        protocol=PROTOCOL,
        plugin_id="example.adapter",
        version="1.0",
        distribution="example-adapter",
        entry_point="example",
        worker_image="registry.example.test/adapters/example@sha256:" + "a" * 64,
        capabilities=["guest.configure", "guest.verify"],
        required_bindings=["server"],
    )


@pytest.fixture
def request_input(manifest):
    return RuntimeInput(
        protocol=PROTOCOL,
        invocation_id=uuid4(),
        operation_id=uuid4(),
        pack_digest="sha256:" + "b" * 64,
        manifest=manifest,
        phase="verify",
        provider="gcp",
        range_id=1,
        targets={"server": {"node_address": "node.example", "os_family": "linux"}},
    )


def plan(request, **changes):
    data = dict(
        protocol=request.protocol,
        invocation_id=request.invocation_id,
        input_digest=request.digest,
        phase=request.phase,
        status="planned",
        actions=[GuestAction(action_id="ready", binding="server", script="test -f /tmp/ready")],
    )
    data.update(changes)
    return RuntimePlan(**data)


def install_entry(monkeypatch, plugin, *, version="1.0", duplicate=False):
    entry = SimpleNamespace(
        dist=SimpleNamespace(name="example_adapter", version=version),
        name="example",
        load=lambda: lambda: plugin,
    )
    entries = [entry, entry] if duplicate else [entry]
    monkeypatch.setattr(
        "shifter_adapter_sdk.worker.importlib.metadata.entry_points",
        lambda: SimpleNamespace(
            select=lambda **kwargs: entries if kwargs["group"] == "shifter.runtime.plugins" else []
        ),
    )


def test_round_trip_keeps_host_target_and_input_identity(request_input):
    request = parse_input(request_input.model_dump_json())
    response = parse_result(plan(request).model_dump_json(), request)
    assert response.status == "planned"
    assert response.actions[0].binding == "server"


def test_bigrae_protocol_is_accepted_without_changing_input_identity(request_input):
    payload = request_input.model_dump(mode="json")
    payload["protocol"] = "bigrae.runtime-plugin/v1"
    payload["manifest"]["protocol"] = payload["protocol"]
    request = parse_input(json.dumps(payload))
    response = parse_result(plan(request).model_dump_json(), request)
    assert response.protocol == "bigrae.runtime-plugin/v1"


def test_request_and_manifest_protocols_must_agree(request_input):
    payload = request_input.model_dump(mode="json")
    payload["manifest"]["protocol"] = "bigrae.runtime-plugin/v1"
    with pytest.raises(ValueError):
        RuntimeInput.model_validate(payload)
    with pytest.raises(ValueError):
        InspectionInput(
            protocol=PROTOCOL,
            invocation_id=uuid4(),
            phase="inspect",
            manifest=payload["manifest"],
        )


def test_response_cannot_switch_protocol_inside_one_invocation(request_input):
    response = plan(request_input, protocol="bigrae.runtime-plugin/v1")
    with pytest.raises(ValueError, match="authorized invocation"):
        parse_result(response.model_dump_json(), request_input)


def test_worker_rejects_conflicting_product_input_aliases(monkeypatch, capsys, request_input):
    monkeypatch.setenv("SHIFTER_PLUGIN_INPUT", request_input.model_dump_json())
    monkeypatch.setenv("BIGRAE_PLUGIN_INPUT", "private-conflict")
    assert main() == 2
    error = capsys.readouterr().err
    assert "invalid plugin input" in error
    assert "private-conflict" not in error
    import os

    assert "SHIFTER_PLUGIN_INPUT" not in os.environ
    assert "BIGRAE_PLUGIN_INPUT" not in os.environ


@pytest.mark.parametrize("changed", ["invocation_id", "operation_id", "pack_digest", "range_id", "phase", "targets"])
def test_cannot_replay_into_changed_authority(request_input, changed):
    response = plan(request_input).model_dump_json()
    data = request_input.model_dump(mode="json")
    data[changed] = {
        "invocation_id": str(uuid4()),
        "operation_id": str(uuid4()),
        "pack_digest": "sha256:" + "c" * 64,
        "range_id": 2,
        "phase": "configure",
        "targets": {"server": {"node_address": "node.other", "os_family": "linux"}},
    }[changed]
    with pytest.raises(ValueError):
        parse_result(response, RuntimeInput.model_validate(data))


@pytest.mark.parametrize("raw", [b"\xff", '{"phase":"inspect","phase":"verify"}', '{"x":NaN}', "{} {}"])
def test_input_rejects_ambiguous_messages(raw):
    with pytest.raises(ValueError):
        parse_input(raw)


def test_raw_output_bound_applies_before_whitespace_normalization(request_input):
    with pytest.raises(ValueError):
        parse_result(" " * MAX_OUTPUT_BYTES + plan(request_input).model_dump_json(), request_input)


def test_worker_cannot_add_a_target_or_cloud_authority(request_input):
    data = plan(request_input).model_dump(mode="json")
    data["actions"][0]["binding"] = "another-range"
    with pytest.raises(ValueError):
        parse_result(json.dumps(data), request_input)
    data["actions"][0]["binding"] = "server"
    data["actions"][0]["role_arn"] = "unapproved"
    with pytest.raises(ValueError):
        parse_result(json.dumps(data), request_input)


def test_empty_verification_and_failed_actions_cannot_claim_success(request_input):
    with pytest.raises(ValueError):
        plan(request_input, actions=[])
    with pytest.raises(ValueError):
        plan(request_input, status="failed", failure_code="planning-failed")


def test_aggregate_action_budget_is_enforced(request_input):
    with pytest.raises(ValueError):
        plan(
            request_input,
            actions=[
                GuestAction(action_id=f"step-{i}", binding="server", script="true", timeout_seconds=300)
                for i in range(5)
            ],
        )


@pytest.mark.parametrize("version,duplicate", [("2.0", False), ("1.0", True)])
def test_missing_or_ambiguous_distribution_is_not_loaded(monkeypatch, request_input, version, duplicate):
    def never(_request):
        pytest.fail("incompatible distribution was loaded")

    install_entry(monkeypatch, SimpleNamespace(plan=never), version=version, duplicate=duplicate)
    result = plan_invocation(request_input)
    assert result.status == "failed"
    assert result.actions == []


def test_mutating_input_does_not_rebind_worker_result(monkeypatch, request_input):
    original_digest = request_input.digest

    def mutate(request):
        request.targets["server"] = request.targets["server"].model_copy(update={"node_address": "node.other"})
        return plan(request)

    install_entry(monkeypatch, SimpleNamespace(plan=mutate))
    result = plan_invocation(request_input)
    assert result.status == "failed"
    assert result.input_digest == original_digest


def test_mutated_plan_is_revalidated(monkeypatch, request_input):
    def mutate(request):
        response = plan(request)
        response.actions.clear()
        return response

    install_entry(monkeypatch, SimpleNamespace(plan=mutate))
    assert plan_invocation(request_input).status == "failed"


def test_installation_probe_needs_no_fake_range(monkeypatch, manifest):
    install_entry(monkeypatch, SimpleNamespace(plan=lambda _: None))
    request = InspectionInput(protocol=PROTOCOL, invocation_id=uuid4(), phase="inspect", manifest=manifest)
    result = inspect_invocation(request)
    assert parse_result(result.model_dump_json(), request).status == "compatible"
    assert "targets" not in request.model_dump()


def test_worker_does_not_emit_plugin_diagnostics(monkeypatch, capsys, request_input):
    def broken(_request):
        print("private diagnostic")
        raise ValueError("private exception")

    install_entry(monkeypatch, SimpleNamespace(plan=broken))
    monkeypatch.setenv("SHIFTER_PLUGIN_INPUT", request_input.model_dump_json())
    assert main() == 1
    captured = capsys.readouterr()
    assert "private" not in captured.out + captured.err
    assert parse_result(captured.out, request_input).failure_code == "planning-failed"


@pytest.mark.parametrize("field", ["private_key", "credential_ref", "public_key", "role_arn"])
def test_runtime_values_cannot_select_secret_or_arbitrary_fields(request_input, field):
    with pytest.raises(ValueError):
        GuestAction(
            action_id="configure",
            binding="server",
            script="true",
            runtime_values={"value": {"binding": "server", "field": field}},
        )


def test_runtime_value_reference_cannot_escape_original_guest_bindings(request_input):
    response = plan(
        request_input,
        actions=[
            GuestAction(
                action_id="configure",
                binding="server",
                script="true",
                runtime_values={"address": {"binding": "foreign", "field": "private_address"}},
            )
        ],
    )
    with pytest.raises(ValueError, match="authorized invocation"):
        parse_result(response.model_dump_json(), request_input)


def test_file_input_metadata_round_trip_has_no_material_or_storage_authority(request_input):
    payload = _with_file(request_input)
    admitted = parse_input(json.dumps(payload))
    assert admitted.files["parameters"].size_bytes == len(b"synthetic parameters\n")
    assert admitted.model_dump(mode="json") == payload
    for field in ("content", "storage_key", "url", "path"):
        changed = _with_file(request_input)
        changed["files"]["parameters"][field] = "private-material-marker"
        with pytest.raises(ValueError):
            parse_input(json.dumps(changed))


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "path", "zero", "too-large", "bad-digest"])
def test_file_input_declarations_are_closed_and_bounded(request_input, change):
    payload = _with_file(request_input)
    if change == "missing":
        payload["files"] = {}
    elif change == "extra":
        payload["files"]["other"] = payload["files"]["parameters"]
    elif change == "duplicate":
        payload["manifest"]["required_files"].append("parameters")
    elif change == "path":
        payload["manifest"]["required_files"] = ["../parameters"]
        payload["files"] = {"../parameters": payload["files"]["parameters"]}
    elif change == "bad-digest":
        payload["files"]["parameters"]["sha256"] = "unverified"
    else:
        payload["files"]["parameters"]["size_bytes"] = 0 if change == "zero" else 512 * 1024 + 1
    with pytest.raises(ValueError):
        parse_input(json.dumps(payload))


def test_file_input_total_budget_is_enforced(request_input):
    payload = _with_file(request_input)
    payload["manifest"]["required_files"] = ["first", "second"]
    descriptor = {"sha256": "sha256:" + "a" * 64, "size_bytes": 300_000}
    payload["files"] = {"first": descriptor, "second": descriptor}
    with pytest.raises(ValueError):
        parse_input(json.dumps(payload))


def test_empty_file_fields_preserve_legacy_manifest_and_invocation_digests(request_input):
    before = request_input.model_dump(mode="json")
    before.pop("files", None)
    before["manifest"].pop("required_files", None)
    payload = {**before, "files": {}, "manifest": {**before["manifest"], "required_files": []}}
    admitted = parse_input(json.dumps(payload))
    assert admitted.model_dump(mode="json") == before
    assert admitted.manifest.digest == canonical_digest(before["manifest"])
    assert admitted.digest == canonical_digest(before)


def test_file_input_reader_verifies_actual_mounted_bytes(request_input, tmp_path, monkeypatch):
    from shifter_adapter_sdk import runtime

    monkeypatch.setattr(runtime, "_FILE_INPUT_ROOT", tmp_path)
    content = b"opaque\x00synthetic\xffbytes\n"
    admitted = parse_input(json.dumps(_with_file(request_input, content)))
    path = tmp_path / "parameters"
    path.write_bytes(content)
    assert runtime.read_file_input(admitted, "parameters") == content
    for changed in (content + b"changed", b"different".ljust(len(content), b"!")):
        path.write_bytes(changed)
        with pytest.raises(ValueError, match="file input"):
            runtime.read_file_input(admitted, "parameters")
    path.unlink()
    with pytest.raises(ValueError, match="file input"):
        runtime.read_file_input(admitted, "parameters")
    with pytest.raises(ValueError, match="file input"):
        runtime.read_file_input(admitted, "../parameters")


def test_worker_refuses_missing_file_before_loading_adapter(request_input, tmp_path, monkeypatch):
    from shifter_adapter_sdk import runtime

    monkeypatch.setattr(runtime, "_FILE_INPUT_ROOT", tmp_path)
    admitted = parse_input(json.dumps(_with_file(request_input)))

    def forbidden_load(_manifest):
        pytest.fail("adapter must not load without its required file")

    monkeypatch.setattr("shifter_adapter_sdk.worker._load_plugin", forbidden_load)
    result = plan_invocation(admitted)
    assert result.status == "failed"
    assert not result.actions


def test_range_validate_planning_is_not_participant_validation(request_input):
    from shifter_adapter_sdk.runtime import parse_input

    planning = request_input.model_copy(update={"phase": "validate"})
    assert parse_input(planning.model_dump_json()) == planning
    response = parse_result(plan(planning, actions=[]).model_dump_json(), planning)
    assert (response.status, response.actions) == ("planned", [])
