"""SQL custody keeps a registered project held until verified restoration."""

from uuid import UUID, uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from engine.models import GcpRangeProject, GcpRangeProjectUse, Range, Request
from shared.gcp_range_projects import GcpProjectLease
from tests.shared.test_gcp_range_projects import baseline_ref as baseline_ref

pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def registration(baseline_ref):
    from management.services import create_service_principal
    from workspaces.models import Organization
    from workspaces.services import create_account

    account = create_account(kind="team", name="Synthetic project tenant")
    organization = Organization.objects.get(account_id=account.id, is_default=True)
    owner = create_service_principal("Synthetic range owner")
    return GcpRangeProject.objects.create(
        id=baseline_ref.registration_id,
        organization_uuid=organization.uuid,
        project_id="synthetic-project",
        project_number="123456789012",
        status="ready",
        baseline=baseline_ref.model_dump(mode="json"),
        created_by_principal_uuid=owner.uuid,
    )


def target_range(registration=None, *, organization=None):
    if registration is not None:
        from workspaces.models import Organization

        organization = organization or Organization.objects.get(uuid=registration.organization_uuid)
        scope = {"scope_kind": "account", "account_id": organization.account_id, "organization_id": organization.pk}
        request = Request.objects.create(
            request_id=uuid4(),
            request_type="range",
            owner_principal_uuid=registration.created_by_principal_uuid,
            **scope,
        )
        return Range.objects.create(
            request=request,
            cms_range_uuid=uuid4(),
            owner_principal_uuid=registration.created_by_principal_uuid,
            status="pending",
            provisioner_operation_id=uuid4(),
            range_backend="gce",
            range_config={},
            **scope,
        )
    request = Request.objects.create(request_id=uuid4(), request_type="range")
    return Range.objects.create(
        request=request,
        status="pending",
        provisioner_operation_id=uuid4(),
        workspace_id=1,
        range_backend="gce",
        range_config={},
    )


def bind(registration, target):
    from shared.gcp_range_projects import GcpBaselineRef

    lease = GcpProjectLease(
        lease_id=uuid4(),
        source_operation_id=target.provisioner_operation_id or uuid4(),
        project_id=registration.project_id,
        project_number=registration.project_number,
        organization_uuid=registration.organization_uuid,
        range_uuid=target.uuid,
        range_id=target.id,
        request_id=target.request.request_id,
        plan_digest="sha256:" + "a" * 64,
        baseline=GcpBaselineRef.model_validate(registration.baseline),
    )
    return GcpRangeProjectUse.objects.create(
        id=lease.lease_id, project=registration, range=target, binding=lease.model_dump(mode="json")
    )


def test_sql_refuses_a_second_active_range_even_after_a_failed_or_destroyed_status(registration):
    original = target_range()
    use = bind(registration, original)
    Range.objects.filter(pk=original.pk).update(status="destroyed")
    with pytest.raises(IntegrityError), transaction.atomic():
        bind(registration, target_range())
    assert GcpRangeProjectUse.objects.get(pk=use.pk).released_at is None


@pytest.mark.parametrize("field", ["project_id", "organization_uuid", "project_number", "baseline"])
def test_accepted_registration_identity_and_baseline_are_immutable(registration, field):
    replacement = (
        {**registration.baseline, "state_digest": "sha256:" + "f" * 64}
        if field == "baseline"
        else (uuid4() if field == "organization_uuid" else "changed")
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        GcpRangeProject.objects.filter(pk=registration.pk).update(**{field: replacement})


@pytest.mark.parametrize("field", ["binding", "project_id", "range_id"])
def test_use_cannot_be_reparented_or_rewritten(registration, field):
    use = bind(registration, target_range())
    replacement = {} if field == "binding" else (uuid4() if field == "project_id" else target_range().pk)
    with pytest.raises(IntegrityError), transaction.atomic():
        GcpRangeProjectUse.objects.filter(pk=use.pk).update(**{field: replacement})


def test_active_use_cannot_be_deleted_to_bypass_exclusivity(registration):
    use = bind(registration, target_range())
    with pytest.raises(IntegrityError), transaction.atomic():
        GcpRangeProjectUse.objects.filter(pk=use.pk).delete()


def test_unapplied_or_missing_cleanup_proof_cannot_release_a_project(registration):
    use = bind(registration, target_range())
    with pytest.raises(IntegrityError), transaction.atomic():
        GcpRangeProjectUse.objects.filter(pk=use.pk).update(
            released_at=timezone.now(),
            release_operation_id=uuid4(),
            release_state_digest=use.binding["baseline"]["state_digest"],
        )


def test_applied_current_restore_releases_once_and_allows_a_new_range(registration):
    from engine.models import OperationInput, OperationResultInbox
    from shared.gcp_range_projects import GcpProjectRestorationProof
    from shared.operation_envelope import build_operation_envelope, canonical_payload_digest

    target = target_range()
    use = bind(registration, target)
    operation_id = uuid4()
    target.status = "destroyed"
    target.provisioner_operation_id = operation_id
    target.save(update_fields=["status", "provisioner_operation_id"])
    digest = use.binding["baseline"]["state_digest"]
    proof = GcpProjectRestorationProof(
        lease_id=use.pk,
        registration_id=registration.pk,
        baseline_state_digest=digest,
        observed_state_digest=digest,
        outcome="restored",
    )
    payload = {
        "raes_status": "succeeded",
        "cleanup_inventory": {
            "outcome": "VERIFIED_ABSENT",
            "residual_categories": [],
            "scope": {"gcp_projects": [proof.model_dump(mode="json")]},
        },
    }
    envelope = build_operation_envelope(
        operation_id=operation_id,
        request_id=target.request.request_id,
        resource="raes-range",
        operation="destroy",
        payload=payload,
    )
    OperationInput.objects.create(
        operation_id=operation_id,
        request_id=target.request.request_id,
        resource="raes-range",
        operation="destroy",
        contract_version=envelope["contract_version"],
        envelope={**envelope, "payload": {}},
    )
    receipt = OperationResultInbox.objects.create(
        operation_id=operation_id,
        request_id=target.request.request_id,
        resource="raes-range",
        operation="destroy",
        contract_version=envelope["contract_version"],
        result_kind="TERMINAL_SUCCESS",
        result_step="raes_terminal_destroyed",
        result_identity=str(uuid4()),
        payload_digest=canonical_payload_digest(payload),
        envelope=envelope,
        disposition="PENDING",
    )
    fields = {"released_at": timezone.now(), "release_operation_id": operation_id, "release_state_digest": digest}
    with pytest.raises(IntegrityError), transaction.atomic():
        GcpRangeProjectUse.objects.filter(pk=use.pk).update(**fields)
    receipt.disposition = "APPLIED"
    receipt.save(update_fields=["disposition"])
    GcpRangeProjectUse.objects.filter(pk=use.pk).update(**fields)
    with pytest.raises(IntegrityError), transaction.atomic():
        GcpRangeProjectUse.objects.filter(pk=use.pk).update(
            released_at=None, release_operation_id=None, release_state_digest=""
        )
    next_use = bind(registration, target_range())
    assert next_use.released_at is None
    assert GcpRangeProjectUse.objects.filter(project=registration, released_at__isnull=True).count() == 1


def allocate(target, project_ids, digest="sha256:" + "a" * 64):
    from engine.services._gcp_project_bindings import allocate_gcp_projects

    return allocate_gcp_projects(range_id=target.pk, project_ids=project_ids, plan_digest=digest)


def test_allocation_replay_retains_lease_and_refuses_changed_selection(registration):
    target = target_range(registration)
    leases = allocate(target, [registration.project_id])
    assert allocate(target, [registration.project_id]) == leases
    for projects, digest in (([], leases[0].plan_digest), ([registration.project_id], "sha256:" + "f" * 64)):
        with pytest.raises(ValueError, match="unavailable"):
            allocate(target, projects, digest)
    assert GcpRangeProjectUse.objects.filter(range=target).count() == 1


@pytest.mark.parametrize("unavailable", ["organization", "disabled", "pending", "failed", "held", "missing"])
def test_unavailable_or_foreign_project_never_allocates(registration, unavailable):
    if unavailable == "organization":
        from workspaces.models import Organization
        from workspaces.services import create_account

        account = create_account(kind="team", name="Another synthetic tenant")
        other = Organization.objects.get(account_id=account.id, is_default=True)
        target = target_range(registration, organization=other)
        with pytest.raises(ValueError, match="unavailable"):
            allocate(target, [registration.project_id])
    else:
        if unavailable == "held":
            bind(registration, target_range(registration))
        elif unavailable != "missing":
            GcpRangeProject.objects.filter(pk=registration.pk).update(status=unavailable)
        target = target_range(registration)
        identifier = "missing-project" if unavailable == "missing" else registration.project_id
        with pytest.raises(ValueError, match="unavailable"):
            allocate(target, [identifier])
    assert not GcpRangeProjectUse.objects.filter(range=target).exists()


def test_multi_project_allocation_rolls_back_all_uses_on_one_unavailable_project(registration, baseline_ref):
    other_id = UUID(int=(1 << 128) - 1)
    other = GcpRangeProject.objects.create(
        id=other_id,
        organization_uuid=registration.organization_uuid,
        project_id="synthetic-second",
        project_number="111122223333",
        status="ready",
        baseline={**baseline_ref.model_dump(mode="json"), "registration_id": str(other_id)},
        created_by_principal_uuid=uuid4(),
    )
    bind(other, target_range(registration))
    target = target_range(registration)
    with pytest.raises(ValueError, match="unavailable"):
        allocate(target, [registration.project_id, other.project_id])
    assert not GcpRangeProjectUse.objects.filter(range=target).exists()
    # The earlier available project is immediately usable by a different range.
    assert len(allocate(target_range(registration), [registration.project_id])) == 1


@pytest.mark.parametrize("state", ["destroyed", "failed", "destroying", "pausing", "ready"])
def test_only_pending_or_provisioning_range_can_acquire_projects(registration, state):
    target = target_range(registration)
    Range.objects.filter(pk=target.pk).update(status=state)
    with pytest.raises(ValueError, match="unavailable"):
        allocate(target, [registration.project_id])
    assert not GcpRangeProjectUse.objects.filter(range=target).exists()


def test_new_use_cannot_start_released_to_bypass_restoration(registration):
    use = bind(registration, target_range(registration))
    use.id = uuid4()
    use.range = target_range(registration)
    use.released_at = timezone.now()
    use.release_operation_id = uuid4()
    use.release_state_digest = use.binding["baseline"]["state_digest"]
    with pytest.raises(IntegrityError), transaction.atomic():
        use.save(force_insert=True)


@pytest.mark.django_db(transaction=True)
def test_concurrent_ranges_cannot_both_acquire_the_same_project(registration):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connections

    ids = [target_range(registration).pk, target_range(registration).pk]
    barrier = Barrier(2)

    def attempt(range_id):
        from engine.services._gcp_project_bindings import allocate_gcp_projects

        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return allocate_gcp_projects(
                range_id=range_id, project_ids=[registration.project_id], plan_digest="sha256:" + "a" * 64
            )
        except ValueError:
            return ()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(attempt, ids))
    assert sorted(len(result) for result in results) == [0, 1]
    assert GcpRangeProjectUse.objects.filter(project=registration, released_at__isnull=True).count() == 1
