"""Original RAES authority, rather than adapter output, controls each replacement."""

from copy import deepcopy
from uuid import uuid4

import pytest
from shifter_adapter_sdk.runtime import RuntimePlan

from shared.raes.runtime_preparation import validate_runtime_preparation
from shared.runtime_plugin_binding import RuntimePluginPin, runtime_plugin_requests


@pytest.fixture
def preparation():
    pin = RuntimePluginPin(
        organization_uuid=uuid4(),
        installation_id=uuid4(),
        pack_id="synthetic",
        pack_digest="sha256:" + "a" * 64,
        manifest={
            "protocol": "shifter.runtime-plugin/v1",
            "plugin_id": "example.prepare",
            "version": "1",
            "distribution": "example-prepare",
            "entry_point": "example",
            "worker_image": "registry.example.test/adapter@sha256:" + "c" * 64,
            "capabilities": ["provision.prepare"],
            "required_bindings": [],
            "provisioning_concerns": ["synthetic-values"],
        },
        bindings={"targets": {}},
    )
    payload = {"os_family": "linux", "settings": {"fixed": "exact", "selected": "original"}}
    rule = {
        "semantic_profile": "synthetic.settings",
        "default_closure": {"posture": "closed", "universe": "synthetic.fields", "profile": "synthetic.settings"},
        "root": {
            "kind": "recursive-record",
            "fields": {
                "fixed": {"kind": "literal", "value": "exact"},
                "selected": {"kind": "delegated"},
            },
        },
    }
    plan = {
        "resources": {
            "node.example": {"address": "node.example", "resource_type": "node", "payload": deepcopy(payload)}
        },
        "operations": [
            {"address": "node.example", "resource_type": "node", "action": "create", "payload": deepcopy(payload)}
        ],
        "realization_authority": [
            {
                "address": "node.example",
                "field_path": "settings",
                "domain": "provisioning",
                "requirement_kind": "synthetic-values",
                "payload_pointer": "/settings",
                "mode": "constrained",
                "source": "authored-leaf",
                "constraint_document": rule,
                "constraint_binding": "sha256:" + "d" * 64,
            }
        ],
    }
    (request,) = runtime_plugin_requests(pin, plan, uuid4(), 1)
    result = RuntimePlan(
        protocol=request.protocol,
        invocation_id=request.invocation_id,
        input_digest=request.digest,
        phase="prepare",
        status="planned",
        provisioning_values=[
            {
                "address": "node.example",
                "concern": "synthetic-values",
                "payload_pointer": "/settings/selected",
                "value": "PRIVATE_SUPPLIED_VALUE",
            }
        ],
    )
    result.authorize(request)
    return pin, plan, result


def test_permitted_selection_changes_only_local_payloads_and_preserves_original(preparation):
    pin, plan, result = preparation
    original = deepcopy(plan)
    candidate = validate_runtime_preparation(plan, result, pin)
    assert plan == original
    assert candidate["resources"]["node.example"]["payload"]["settings"]["selected"] == "PRIVATE_SUPPLIED_VALUE"
    assert candidate["operations"][0]["payload"] == candidate["resources"]["node.example"]["payload"]
    assert candidate["realization_authority"] == plan["realization_authority"]
    assert set(candidate["resources"]) == set(plan["resources"])


@pytest.mark.parametrize(
    "change",
    [
        "exact",
        "closed",
        "missing",
        "unknown",
        "nested-exact",
        "unknown-closure",
        "binding",
        "shape",
        "operation",
        "extra-authority",
        "ambiguous",
    ],
)
def test_no_replacement_can_weaken_original_authority(preparation, change):
    pin, plan, result = preparation
    authority = plan["realization_authority"][0]
    if change in {"exact", "closed", "unknown"}:
        authority["mode"] = change
    elif change == "missing":
        plan["realization_authority"] = []
    elif change == "binding":
        authority.pop("constraint_binding")
    elif change == "unknown-closure":
        authority["constraint_document"].pop("default_closure")
    elif change == "operation":
        plan["operations"][0]["payload"]["settings"]["selected"] = "changed after admission"
    elif change in {"extra-authority", "ambiguous"}:
        other = {**authority, "constraint_document": None, "constraint_binding": None, "mode": "exact"}
        if change == "extra-authority":
            other["requirement_kind"] = "other"
        plan["realization_authority"].append(other)
    else:
        raw = result.model_dump(mode="json")
        raw["provisioning_values"][0]["payload_pointer"] = (
            "/settings/fixed" if change == "nested-exact" else "/settings"
        )
        result = RuntimePlan.model_validate(raw)
    with pytest.raises(ValueError) as error:
        validate_runtime_preparation(plan, result, pin)
    assert "PRIVATE_SUPPLIED_VALUE" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("selected,accepted", [("PRIVATE_SUPPLIED_VALUE", True), ("outside", False)])
def test_native_finite_domain_controls_scalar_selection(preparation, selected, accepted):
    pin, plan, result = preparation
    authority = plan["realization_authority"][0]
    authority.pop("constraint_document")
    authority.pop("constraint_binding")
    authority["bounds"] = [
        {"value_pointer": "/selected", "domain": {"kind": "enum", "values": ["PRIVATE_SUPPLIED_VALUE"]}}
    ]
    raw = result.model_dump(mode="json")
    raw["provisioning_values"][0]["value"] = selected
    result = RuntimePlan.model_validate(raw)
    if accepted:
        validate_runtime_preparation(plan, result, pin)
    else:
        with pytest.raises(ValueError):
            validate_runtime_preparation(plan, result, pin)


@pytest.mark.parametrize("kind,accepted", [("open", True), ("exact", False)])
def test_legacy_structure_preserves_exact_siblings(preparation, kind, accepted):
    pin, plan, result = preparation
    authority = plan["realization_authority"][0]
    authority.pop("constraint_document")
    authority.pop("constraint_binding")
    authority["mode"] = "open"
    authority["structure"] = {"kind": "record", "fields": {"fixed": {"kind": "exact"}, "selected": {"kind": kind}}}
    if accepted:
        validate_runtime_preparation(plan, result, pin)
    else:
        with pytest.raises(ValueError):
            validate_runtime_preparation(plan, result, pin)


@pytest.mark.parametrize("pointer", ["/missing", "/settings/missing", "/settings/selected/child"])
def test_existing_leaf_requirement_rejects_new_or_nontraversable_paths(preparation, pointer):
    pin, plan, result = preparation
    raw = result.model_dump(mode="json")
    raw["provisioning_values"][0]["payload_pointer"] = pointer
    with pytest.raises(ValueError):
        validate_runtime_preparation(plan, RuntimePlan.model_validate(raw), pin)


@pytest.mark.parametrize("index,accepted", [("0", True), ("00", False), ("-1", False), ("1", False), ("-", False)])
def test_array_selection_cannot_append_or_change_member_identity(preparation, index, accepted):
    pin, plan, result = preparation
    authority = plan["realization_authority"][0]
    authority.pop("constraint_document")
    authority.pop("constraint_binding")
    authority["mode"] = "open"
    for payload in (plan["resources"]["node.example"]["payload"], plan["operations"][0]["payload"]):
        payload["settings"]["selected"] = ["original"]
    raw = result.model_dump(mode="json")
    raw["provisioning_values"][0]["payload_pointer"] = f"/settings/selected/{index}"
    selected = RuntimePlan.model_validate(raw)
    if accepted:
        effective = validate_runtime_preparation(plan, selected, pin)
        assert effective["resources"]["node.example"]["payload"]["settings"]["selected"] == ["PRIVATE_SUPPLIED_VALUE"]
    else:
        with pytest.raises(ValueError):
            validate_runtime_preparation(plan, selected, pin)


def _large_preparation(preparation, groups=6):
    """Retain a closed exact inventory beside the one delegated scalar."""
    pin, plan, result = preparation
    inventory = {f"group-{group}": {f"item-{item}": item for item in range(1000)} for group in range(groups)}
    for payload in (plan["resources"]["node.example"]["payload"], plan["operations"][0]["payload"]):
        payload["settings"].update(deepcopy(inventory))
    fields = plan["realization_authority"][0]["constraint_document"]["root"]["fields"]
    fields.update(
        {
            group: {
                "kind": "recursive-record",
                "fields": {name: {"kind": "literal", "value": value} for name, value in items.items()},
            }
            for group, items in inventory.items()
        }
    )
    (request,) = runtime_plugin_requests(pin, plan, uuid4(), 1)
    result = result.model_copy(update={"invocation_id": request.invocation_id, "input_digest": request.digest})
    result.authorize(request)
    return pin, plan, result


def test_large_admitted_authority_uses_the_supported_plan_budget(preparation):
    pin, plan, result = _large_preparation(preparation)
    original = deepcopy(plan)
    effective = validate_runtime_preparation(plan, result, pin)
    assert plan == original
    settings = effective["resources"]["node.example"]["payload"]["settings"]
    assert settings["selected"] == "PRIVATE_SUPPLIED_VALUE"
    assert settings["group-5"] == original["resources"]["node.example"]["payload"]["settings"]["group-5"]


def test_large_authority_keeps_closed_nested_values_exact(preparation):
    pin, plan, result = _large_preparation(preparation)
    raw = result.model_dump(mode="json")
    raw["provisioning_values"].append(
        {
            "address": "node.example",
            "concern": "synthetic-values",
            "payload_pointer": "/settings/group-0/item-0",
            "value": 42,
        }
    )
    with pytest.raises(ValueError, match="original admitted plan"):
        validate_runtime_preparation(plan, RuntimePlan.model_validate(raw), pin)


def test_authority_beyond_the_fixed_plan_budget_is_refused(preparation):
    pin, plan, result = _large_preparation(preparation, groups=66)
    with pytest.raises(ValueError, match="original admitted plan"):
        validate_runtime_preparation(plan, result, pin)
