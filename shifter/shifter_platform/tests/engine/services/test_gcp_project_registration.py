"""Native project registration never borrows staff status or range authority."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth.models import User

from engine.models import GcpRangeProject, OperationInput, OperationResultInbox, ProvisionerLaunchIntent
from engine.services._gcp_project_registration import disable_gcp_range_project, register_gcp_range_project
from shared.exceptions import ValidationError

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def operator(monkeypatch, live_session_credential, settings):
    from shared.authorization import AuthorizationDecision, DecisionKind, port
    from shared.gcp_project_registration import PROTECTED_PROJECT_ENV_NAMES
    from workspaces.models import Organization
    from workspaces.services import create_account

    for name in PROTECTED_PROJECT_ENV_NAMES:
        setattr(settings, name, "")
    settings.CLOUD_PROVIDER = "gcp"
    settings.GCP_PROJECT_ID = "synthetic-control"
    settings.GCP_DYNAMIC_SECRET_PROJECT_ID = "synthetic-credentials"
    settings.STORAGE_BUCKET_NAME = "synthetic-private-assets"
    settings.ENGINE_TASK_CLUSTER = "synthetic-namespace"
    settings.ENGINE_TASK_DEFINITION = "synthetic-provisioner:1"
    actor = User.objects.create_user(username="project-operator", is_staff=False)
    actor.credential = live_session_credential(actor)
    actor.allow_project_administration = True
    account = create_account(kind="team", name="Synthetic organization")
    organization = Organization.objects.get(account_id=account.id, is_default=True)

    def check(request):
        allowed = actor.allow_project_administration and (
            request.principal == actor.credential.principal
            and request.action == "installation.manage_cloud_authority"
            and request.target.type == "installation"
            and request.scope.kind == "installation"
        )
        return AuthorizationDecision(
            DecisionKind.ALLOWED if allowed else DecisionKind.DENIED, "policy_allowed" if allowed else "policy_denied"
        )

    monkeypatch.setattr(port, "_provider_factory", lambda: SimpleNamespace(check=check))
    return actor, organization


def register(operator):
    actor, organization = operator
    return register_gcp_range_project(actor.credential, organization.uuid, "synthetic-project")


def receipt_for(row, *, change=None, failure=False):
    from shared.gcp_project_registration import GcpProjectRegistrationReceipt
    from shared.gcp_range_projects import GcpBaselineRef
    from shared.operation_envelope import build_operation_envelope, canonical_payload_digest
    from shared.operation_results import build_result_identity

    ref = GcpBaselineRef(
        registration_id=row.pk,
        capture_operation_id=row.provisioner_operation_id
        if row.baseline is None
        else row.baseline["capture_operation_id"],
        bucket="synthetic-private-assets",
        ciphertext_sha256="sha256:" + "a" * 64,
        ciphertext_bytes=1024,
        generation="1234",
        state_digest="sha256:" + "b" * 64,
    )
    if change:
        ref = ref.model_copy(update=change)
    value = GcpProjectRegistrationReceipt(
        registration_id=row.pk,
        organization_uuid=row.organization_uuid,
        project_id=row.project_id,
        project_number="123456789012",
        baseline=ref,
    )
    step = "gcp_project_failed" if failure else "gcp_project_ready"
    payload = (
        {"reason_code": "cloud_operation_failed", "diagnostic": "Project capture failed"}
        if failure
        else value.model_dump(mode="json")
    )
    envelope = build_operation_envelope(
        operation_id=row.provisioner_operation_id,
        request_id=row.pk,
        resource="range-project",
        operation=row.provisioner_operation,
        payload=payload,
    )
    return OperationResultInbox.objects.create(
        operation_id=row.provisioner_operation_id,
        request_id=row.pk,
        resource="range-project",
        operation=row.provisioner_operation,
        contract_version=envelope["contract_version"],
        result_kind="TERMINAL_FAILURE" if failure else "TERMINAL_SUCCESS",
        result_step=step,
        result_identity=build_result_identity(
            operation_id=row.provisioner_operation_id, step=step, digest=canonical_payload_digest(payload)
        ),
        payload_digest=canonical_payload_digest(payload),
        envelope=envelope,
    )


def test_operator_registration_commits_one_reference_input_and_original_authority(operator):
    result = register(operator)
    assert not operator[0].is_staff
    assert result.status == "pending"
    assert register(operator) == result
    assert (
        GcpRangeProject.objects.count()
        == ProvisionerLaunchIntent.objects.count()
        == OperationInput.objects.count()
        == 1
    )
    row = GcpRangeProject.objects.get(pk=result.id)
    intent = ProvisionerLaunchIntent.objects.get(operation_id=row.provisioner_operation_id)
    stored = OperationInput.objects.get(operation_id=row.provisioner_operation_id)
    assert stored.request_id == row.pk
    assert stored.envelope["payload"]["bucket"] == "synthetic-private-assets"
    assert stored.envelope["payload"]["protected_project_ids"] == ["synthetic-control", "synthetic-credentials"]
    assert intent.initiating_principal_uuid == operator[0].credential.principal.uuid
    assert intent.credential_uuid == operator[0].credential.credential_uuid
    assert intent.authority_action == "installation.manage_cloud_authority"
    assert intent.executing_workload["command"] == [
        "range-project",
        "register",
        "--request-id",
        str(row.pk),
        "--operation-id",
        str(row.provisioner_operation_id),
    ]
    from engine.launch_payload_authority import authorize_provisioner_payload

    authorize_provisioner_payload(intent.payload, expected_operation_id=intent.operation_id)


def test_staff_flag_cannot_replace_explicit_operator_policy(operator):
    actor, _organization = operator
    actor.is_staff = actor.is_superuser = True
    actor.allow_project_administration = False
    with pytest.raises(PermissionError, match="not permitted"):
        register(operator)
    assert not GcpRangeProject.objects.exists()


@pytest.mark.parametrize("project_id", ["synthetic-control", "synthetic-credentials", "Bad/identity", "", "x"])
def test_protected_or_invalid_project_registration_has_no_outbox_side_effect(operator, project_id):
    actor, organization = operator
    with pytest.raises(ValidationError):
        register_gcp_range_project(actor.credential, organization.uuid, project_id)
    assert not GcpRangeProject.objects.exists()
    assert not ProvisionerLaunchIntent.objects.exists()


def test_registration_cannot_move_to_another_organization(operator):
    from workspaces.models import Organization
    from workspaces.services import create_account

    original = register(operator)
    account = create_account(kind="team", name="Another synthetic organization")
    other = Organization.objects.get(account_id=account.id, is_default=True)
    with pytest.raises(ValidationError):
        register_gcp_range_project(operator[0].credential, other.uuid, original.project_id)
    assert GcpRangeProject.objects.get(pk=original.id).organization_uuid == original.organization_uuid


@pytest.mark.parametrize("change", ["credential", "policy", "disabled"])
def test_revoked_or_disabled_registration_cannot_launch(operator, change):
    from engine.launch_payload_authority import authorize_provisioner_payload
    from management.models import PrincipalSession

    result = register(operator)
    row = GcpRangeProject.objects.get(pk=result.id)
    intent = ProvisionerLaunchIntent.objects.get(operation_id=row.provisioner_operation_id)
    if change == "credential":
        PrincipalSession.objects.filter(credential_uuid=operator[0].credential.credential_uuid).delete()
    elif change == "policy":
        operator[0].allow_project_administration = False
    else:
        disable_gcp_range_project(operator[0].credential, row.pk)
    with pytest.raises(PermissionError, match="unavailable"):
        authorize_provisioner_payload(intent.payload, expected_operation_id=intent.operation_id)


def test_exact_current_capture_receipt_is_required_to_make_project_ready(operator):
    from engine.services import apply_pending_operation_results

    result = register(operator)
    row = GcpRangeProject.objects.get(pk=result.id)
    receipt = receipt_for(row)
    assert apply_pending_operation_results() == 1
    row.refresh_from_db()
    receipt.refresh_from_db()
    assert row.status == "ready"
    assert row.baseline == receipt.envelope["payload"]["baseline"]
    assert receipt.disposition == "APPLIED"


@pytest.mark.parametrize("field", ["registration_id", "capture_operation_id", "bucket"])
def test_capture_receipt_cannot_substitute_scope_generation_or_storage(operator, field):
    from engine.services import apply_pending_operation_results

    row = GcpRangeProject.objects.get(pk=register(operator).id)
    receipt = receipt_for(row, change={field: "different-assets" if field == "bucket" else uuid4()})
    assert apply_pending_operation_results() == 1
    row.refresh_from_db()
    receipt.refresh_from_db()
    assert row.status == "pending" and row.baseline is None
    assert receipt.disposition == "REJECTED_INVALID"


def test_failed_capture_remains_unavailable_and_retains_original_operation(operator):
    from engine.services import apply_pending_operation_results

    row = GcpRangeProject.objects.get(pk=register(operator).id)
    operation_id = row.provisioner_operation_id
    receipt_for(row, failure=True)
    assert apply_pending_operation_results() == 1
    row.refresh_from_db()
    assert (row.status, row.baseline, row.provisioner_operation_id) == ("failed", None, operation_id)


def test_registration_api_is_bounded_closed_and_does_not_expose_artifact_locators(operator):
    from rest_framework.test import APIClient

    actor, organization = operator
    client = APIClient()
    client.force_authenticate(user=actor)
    url = "/api/v1/cms/gcp-range-projects/"
    body = {"organization_uuid": str(organization.uuid), "project_id": "synthetic-project"}
    response = client.post(url, body, format="json")
    assert response.status_code == 202, response.content
    view = response.json()
    assert set(view) == {"id", "organization_uuid", "project_id", "project_number", "status", "failure_code", "in_use"}
    assert view["status"] == "pending"
    assert client.get(url).json()["results"] == [view]
    for extra in ({"bucket": "another-bucket"}, {"baseline": {}}, {"protected_project_ids": []}):
        assert client.post(url, {**body, **extra}, format="json").status_code == 400
    assert client.get(url, {"cursor": "invalid"}).status_code == 400
    assert client.post(f"{url}{view['id']}/disable/", {}, format="json").json()["status"] == "disabled"
    actor.allow_project_administration = False
    assert client.get(url).status_code == 403
    assert client.post(url, body, format="json").status_code == 403


def test_capture_cannot_reenable_registration_disabled_while_worker_was_running(operator):
    from engine.services import apply_pending_operation_results

    row = GcpRangeProject.objects.get(pk=register(operator).id)
    receipt = receipt_for(row)
    disable_gcp_range_project(operator[0].credential, row.pk)
    assert apply_pending_operation_results() == 1
    row.refresh_from_db()
    receipt.refresh_from_db()
    assert row.baseline is not None and row.status == "disabled"
    assert receipt.disposition == "APPLIED"


@pytest.mark.parametrize("change", ["credential", "policy", "operation", "request"])
def test_late_capture_cannot_borrow_changed_authority_or_generation(operator, change):
    from engine.services import apply_pending_operation_results
    from management.models import PrincipalSession

    row = GcpRangeProject.objects.get(pk=register(operator).id)
    receipt = receipt_for(row)
    if change == "credential":
        PrincipalSession.objects.filter(credential_uuid=operator[0].credential.credential_uuid).delete()
    elif change == "policy":
        operator[0].allow_project_administration = False
    elif change == "operation":
        GcpRangeProject.objects.filter(pk=row.pk).update(provisioner_operation_id=uuid4())
    else:
        request_id = uuid4()
        # An append-only row with the wrong correlation is synthetic incoming evidence.
        receipt.envelope["request_id"] = str(request_id)
        receipt.request_id = request_id
        receipt.save(update_fields=["request_id", "envelope"])
    assert apply_pending_operation_results() == 1
    row.refresh_from_db()
    receipt.refresh_from_db()
    assert row.baseline is None and row.status == "pending"
    assert receipt.disposition == {"operation": "REJECTED_STALE", "request": "REJECTED_OWNERSHIP"}.get(
        change, "REJECTED_INVALID"
    )


def test_capture_and_result_disposition_roll_back_if_strict_audit_fails(operator):
    from engine.services import apply_pending_operation_results

    row = GcpRangeProject.objects.get(pk=register(operator).id)
    receipt = receipt_for(row)

    from shared.audit import bind_audit_writer, get_audit_writer, reset_audit_writer

    class FailingWriter:
        def write(self, event):
            raise RuntimeError("Synthetic audit failure")

    original = get_audit_writer()
    reset_audit_writer()
    bind_audit_writer(FailingWriter())
    try:
        with pytest.raises(RuntimeError, match="Synthetic audit failure"):
            apply_pending_operation_results()
    finally:
        reset_audit_writer()
        bind_audit_writer(original)
    row.refresh_from_db()
    receipt.refresh_from_db()
    assert row.baseline is None and row.status == "pending"
    assert receipt.disposition == "PENDING"


def test_disabled_registration_reenables_only_after_original_baseline_verification(operator):
    from engine.services import apply_pending_operation_results, retry_gcp_range_project

    row = GcpRangeProject.objects.get(pk=register(operator).id)
    receipt_for(row)
    assert apply_pending_operation_results() == 1
    row.refresh_from_db()
    original_baseline, original_operation = row.baseline, row.provisioner_operation_id
    disable_gcp_range_project(operator[0].credential, row.pk)
    assert retry_gcp_range_project(operator[0].credential, row.pk).status == "pending"
    row.refresh_from_db()
    assert row.provisioner_operation == "verify" and row.provisioner_operation_id != original_operation
    stored = OperationInput.objects.get(operation_id=row.provisioner_operation_id)
    assert stored.envelope["payload"]["baseline"] == original_baseline
    assert row.baseline == original_baseline
    receipt_for(row)
    assert apply_pending_operation_results() == 1
    row.refresh_from_db()
    assert row.status == "ready" and row.baseline == original_baseline


def test_failed_first_capture_can_retry_with_new_generation_but_old_receipt_is_stale(operator):
    from engine.services import apply_pending_operation_results, retry_gcp_range_project

    row = GcpRangeProject.objects.get(pk=register(operator).id)
    receipt_for(row, failure=True)
    assert apply_pending_operation_results() == 1
    old = receipt_for(row)
    assert retry_gcp_range_project(operator[0].credential, row.pk).status == "pending"
    row.refresh_from_db()
    assert row.provisioner_operation == "register" and row.provisioner_operation_id != old.operation_id
    assert apply_pending_operation_results() == 1
    old.refresh_from_db()
    assert old.disposition == "REJECTED_STALE"
    row.refresh_from_db()
    assert row.baseline is None


def test_registered_image_project_cannot_become_a_scenario_project(operator):
    from engine.models import RaesImageMapping

    RaesImageMapping.objects.create(
        provider="gcp", source_name="synthetic-source", image_ref="projects/synthetic-images/global/images/example"
    )
    with pytest.raises(ValidationError):
        register_gcp_range_project(operator[0].credential, operator[1].uuid, "synthetic-images")
    assert not GcpRangeProject.objects.exists()


def test_service_principal_uses_its_own_native_administration_proof(operator):
    from rest_framework.test import APIClient

    from management.services import create_service_principal
    from shared.authorization import CredentialCeiling
    from shared.credentials import CredentialContext
    from tests._credential_helpers import persisted_credential

    actor, organization = operator
    principal = create_service_principal("Synthetic installation operator")
    credential = persisted_credential(
        CredentialContext(
            principal,
            "service",
            uuid4(),
            CredentialCeiling(frozenset({"installation.manage_cloud_authority"})),
            frozenset({"authorization:installation.manage_cloud_authority"}),
        )
    )
    actor.credential = credential
    client = APIClient()
    client.force_authenticate(token=credential)
    response = client.post(
        "/api/v1/cms/gcp-range-projects/",
        {"organization_uuid": str(organization.uuid), "project_id": "synthetic-project"},
        format="json",
    )
    assert response.status_code == 202, response.content
    row = GcpRangeProject.objects.get(pk=response.json()["id"])
    intent = ProvisionerLaunchIntent.objects.get(operation_id=row.provisioner_operation_id)
    assert row.created_by_principal_uuid == principal.uuid
    assert (intent.initiating_principal_uuid, intent.credential_uuid, intent.credential_kind) == (
        principal.uuid,
        credential.credential_uuid,
        "service",
    )
