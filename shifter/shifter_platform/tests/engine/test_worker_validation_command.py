"""Native operator proof lifecycle and bounded disposable-worker qualification."""

import json
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command

from tests._worker_cloud import worker_cloud
from tests.engine.services.test_disposable_workers import apparatus, tenant

__all__ = ["apparatus", "tenant", "worker_cloud"]
pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def operator(apparatus, tmp_path):
    from django.utils import timezone

    from management.models import Principal, ProviderBinding
    from workspaces.models import IdentityCutoverState

    principal = apparatus.credential.principal.uuid
    ProviderBinding.objects.create(
        principal=Principal.objects.get(uuid=principal), issuer="https://issuer.example", subject="worker-operator"
    )
    IdentityCutoverState.objects.create(
        key=1,
        state="activated",
        plan_digest="a" * 64,
        plan_payload={},
        tuple_digest="b" * 64,
        provider_store_id="test-store",
        model_id="test-model",
        bootstrap_principal_uuid=principal,
        bootstrap_verified_at=timezone.now(),
        admission_invalidated_at=timezone.now(),
    )
    path = tmp_path / "bootstrap.json"
    path.write_text(
        json.dumps(
            {
                "schema": "shifter.identity-bootstrap-facts/v1",
                "issuer": "https://issuer.example",
                "subject": "worker-operator",
            }
        )
    )
    path.chmod(0o600)
    return path


def test_operator_issues_exact_native_credentials_and_revokes_them(apparatus, operator):
    from django.utils import timezone

    from engine.services import create_disposable_worker
    from management.worker_validation import issue_worker_validation_credentials
    from shared.api_tokens.models import ApiToken
    from shared.authorization import TargetRef
    from shared.authorization.policy import scope_parent
    from shared.credentials import resolve_current_credential

    workers = (uuid4(), uuid4())
    contexts = {}
    with issue_worker_validation_credentials(
        apparatus.credential.principal.uuid, scope=apparatus.scope, worker_ids=workers
    ) as credential_for:
        parent = scope_parent(apparatus.scope)
        for identifier in workers:
            with pytest.raises(ValueError):
                credential_for(TargetRef("range", identifier))
            create_disposable_worker(
                credential_for(parent),
                scope=apparatus.scope,
                worker_id=identifier,
                experiment_id=apparatus.experiment,
            )
        targets = {TargetRef("installation"), parent, *(TargetRef("range", value) for value in workers)}
        for target in targets:
            credential = credential_for(target)
            assert credential.ceiling.target == target
            assert resolve_current_credential(credential) == credential
            contexts[target] = credential
        tokens = list(ApiToken.objects.filter(name="worker-validation"))
        assert len(tokens) == 4
        assert all(row.expires_at <= timezone.now() + timezone.timedelta(minutes=35) for row in tokens)
    assert all(row.revoked_at is not None for row in ApiToken.objects.filter(name="worker-validation"))
    for credential in contexts.values():
        with pytest.raises(ValueError):
            resolve_current_credential(credential)


def test_operator_revokes_all_credentials_after_failure(apparatus, operator):
    from management.worker_validation import issue_worker_validation_credentials
    from shared.api_tokens.models import ApiToken

    with (
        pytest.raises(RuntimeError, match="Synthetic failure"),
        issue_worker_validation_credentials(
            apparatus.credential.principal.uuid, scope=apparatus.scope, worker_ids=(uuid4(), uuid4())
        ),
    ):
        raise RuntimeError("Synthetic failure")
    assert ApiToken.objects.filter(name="worker-validation").count() == 4
    assert not ApiToken.objects.filter(name="worker-validation", revoked_at__isnull=True).exists()


def test_operator_command_rejects_inactive_cutover_before_effects(apparatus, operator):
    from engine.models import DisposableWorker
    from shared.api_tokens.models import ApiToken
    from workspaces.models import IdentityCutoverState

    IdentityCutoverState.objects.update(state="policy_pending")
    with pytest.raises(CommandError):
        call_command(
            "qualify_disposable_workers",
            bootstrap_facts=str(operator),
            scope_kind="organization",
            scope_id=apparatus.scope.organization_uuid,
            stdout=StringIO(),
        )
    assert not DisposableWorker.objects.exists()
    assert not ApiToken.objects.filter(name="worker-validation").exists()


def test_operator_worker_credential_cannot_inspect_its_sibling(apparatus, operator):
    from engine.services import get_disposable_worker
    from management.worker_validation import issue_worker_validation_credentials
    from shared.authorization import TargetRef
    from tests.engine.services.test_disposable_workers import create

    identifiers = (uuid4(), uuid4())
    with issue_worker_validation_credentials(
        apparatus.credential.principal.uuid, scope=apparatus.scope, worker_ids=identifiers
    ) as credentials:
        for identifier in identifiers:
            create(apparatus, worker_id=identifier)
        first = credentials(TargetRef("range", identifiers[0]))
        assert get_disposable_worker(first, identifiers[0]).worker_id == identifiers[0]
        with pytest.raises(PermissionError):
            get_disposable_worker(first, identifiers[1])


def test_operator_validation_refuses_lost_personal_token_eligibility(apparatus, operator, monkeypatch):
    from management.worker_validation import issue_worker_validation_credentials
    from shared.api_tokens.models import ApiToken
    from shared.authorization import AuthorizationDecision, DecisionKind, configured_authorization_provider

    provider = configured_authorization_provider()
    original = provider.check
    monkeypatch.setattr(
        provider,
        "check",
        lambda request: (
            AuthorizationDecision(DecisionKind.DENIED, "policy_denied")
            if request.action == "installation.use_personal_tokens"
            else original(request)
        ),
    )
    with (
        pytest.raises(ValueError),
        issue_worker_validation_credentials(
            apparatus.credential.principal.uuid, scope=apparatus.scope, worker_ids=(uuid4(), uuid4())
        ),
    ):
        pytest.fail("Revoked personal eligibility must deny operator proof")
    assert not ApiToken.objects.filter(name="worker-validation").exists()


@pytest.mark.parametrize("other_active", [False, True])
def test_operator_command_rejects_different_bootstrap_identity(apparatus, operator, tenant, other_active):
    from engine.models import DisposableWorker
    from shared.api_tokens.models import ApiToken

    document = json.loads(operator.read_text())
    document["subject"] = "another-operator"
    operator.write_text(json.dumps(document))
    if other_active:
        from django.contrib.auth import get_user_model

        from management.models import Principal, ProviderBinding
        from management.services import ensure_human_principal

        other = get_user_model().objects.create_user(username="other-operator")
        principal = ensure_human_principal(other)
        ProviderBinding.objects.create(
            principal=Principal.objects.get(uuid=principal.uuid), issuer=document["issuer"], subject=document["subject"]
        )
        tenant[0].policy_principals.add(principal.uuid)
    with pytest.raises(CommandError):
        call_command(
            "qualify_disposable_workers",
            bootstrap_facts=str(operator),
            scope_kind="organization",
            scope_id=apparatus.scope.organization_uuid,
        )
    assert not DisposableWorker.objects.exists()
    assert not ApiToken.objects.filter(name="worker-validation").exists()


def test_bootstrap_facts_loader_rejects_a_symlink(operator, tmp_path):
    from shared.bootstrap_facts import load_identity_bootstrap_facts

    linked = tmp_path / "linked-bootstrap"
    linked.symlink_to(operator)
    with pytest.raises(ValueError):
        load_identity_bootstrap_facts(str(linked))


@pytest.mark.django_db(transaction=True)
def test_failed_parallel_admission_retains_cleanup_custody(apparatus, operator, monkeypatch):
    import itertools
    import time

    from engine.models import DisposableWorker, WorkerPolicyRecord
    from engine.services import configure_worker_policy
    from shared.api_tokens.models import ApiToken

    policy = WorkerPolicyRecord.objects.get().configuration
    policy.update(max_live=1, max_provisioning=1)
    configure_worker_policy(apparatus.credential, policy)
    clock = itertools.count(step=1000)
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    with pytest.raises(CommandError):
        call_command(
            "qualify_disposable_workers",
            bootstrap_facts=str(operator),
            scope_kind="organization",
            scope_id=apparatus.scope.organization_uuid,
        )
    workers = list(DisposableWorker.objects.all())
    assert len(workers) == 1 and workers[0].retirement_at is not None
    assert not ApiToken.objects.filter(name="worker-validation", revoked_at__isnull=True).exists()


def test_native_expiry_cleans_worker_after_operator_proof_is_revoked(apparatus, operator):
    from django.utils import timezone

    from engine.models import CapacityDraw, DisposableWorker, ProvisionerLaunchIntent
    from engine.services import create_disposable_worker, reconcile_disposable_workers
    from management.worker_validation import issue_worker_validation_credentials
    from shared.authorization.policy import scope_parent
    from shared.operation_results import ResultStep
    from tests.engine.services.test_native_warm_retirement import _apply_result

    identifier = uuid4()
    with issue_worker_validation_credentials(
        apparatus.credential.principal.uuid, scope=apparatus.scope, worker_ids=(identifier,)
    ) as credential:
        create_disposable_worker(
            credential(scope_parent(apparatus.scope)),
            scope=apparatus.scope,
            worker_id=identifier,
            experiment_id=apparatus.experiment,
        )
    provision = ProvisionerLaunchIntent.objects.get(payload__operation="provision")
    _apply_result(
        provision,
        ResultStep.RAES_TERMINAL_FAILED,
        {"reason_code": "cloud_operation_failed", "diagnostic": "Synthetic partial provision"},
    )
    row = DisposableWorker.objects.get(pk=identifier)
    reconcile_disposable_workers(now=row.deadline + timezone.timedelta(seconds=1))
    cleanup = ProvisionerLaunchIntent.objects.get(payload__operation="destroy")
    assert CapacityDraw.objects.filter(draw_key=identifier, released_at__isnull=True).exists()
    _apply_result(
        cleanup,
        ResultStep.RAES_TERMINAL_DESTROYED,
        {
            "raes_status": "succeeded",
            "cleanup_inventory": {
                "outcome": "VERIFIED_ABSENT",
                "scope": {"request_id": str(row.request_id)},
                "residual_categories": [],
            },
        },
    )
    reconcile_disposable_workers(worker_ids=(identifier,))
    assert DisposableWorker.objects.get(pk=identifier).terminal_at is not None
    assert not CapacityDraw.objects.filter(draw_key=identifier, released_at__isnull=True).exists()


@pytest.mark.parametrize("kind", ["symlink", "public", "oversized", "fifo"])
def test_operator_command_rejects_unsafe_private_input(apparatus, operator, tmp_path, kind):
    import os

    from shared.api_tokens.models import ApiToken

    path = operator
    if kind == "symlink":
        path = tmp_path / "linked-facts"
        path.symlink_to(operator)
    elif kind == "public":
        path.chmod(0o644)
    elif kind == "oversized":
        path.write_bytes(b" " * 65537)
    else:
        path = tmp_path / "facts-pipe"
        os.mkfifo(path, 0o600)
    with pytest.raises(CommandError):
        call_command(
            "qualify_disposable_workers",
            bootstrap_facts=str(path),
            scope_kind="organization",
            scope_id=apparatus.scope.organization_uuid,
        )
    assert not ApiToken.objects.filter(name="worker-validation").exists()


def test_operator_credentials_expire_without_metadata_changes(apparatus, operator, monkeypatch):
    from django.utils import timezone

    from management.worker_validation import issue_worker_validation_credentials
    from shared.authorization import TargetRef
    from shared.credentials import resolve_current_credential

    with issue_worker_validation_credentials(
        apparatus.credential.principal.uuid, scope=apparatus.scope, worker_ids=(uuid4(), uuid4())
    ) as credential_for:
        credential = credential_for(TargetRef("installation"))
        future = timezone.now() + timezone.timedelta(minutes=36)
        with monkeypatch.context() as expired:
            expired.setattr(timezone, "now", lambda: future)
            with pytest.raises(ValueError):
                resolve_current_credential(credential)


def test_operator_issuance_audit_failure_leaves_no_live_credentials(apparatus, operator, monkeypatch):
    from management import worker_validation
    from shared.api_tokens.audit import TokenEvent
    from shared.api_tokens.models import ApiToken

    original = worker_validation.record_token_event
    created = []

    def audit(event, **kwargs):
        if event is TokenEvent.CREATED:
            created.append(kwargs["token_id"])
            if len(created) == 3:
                raise ValueError("Synthetic audit failure")
        return original(event, **kwargs)

    monkeypatch.setattr(worker_validation, "record_token_event", audit)
    with (
        pytest.raises(ValueError),
        worker_validation.issue_worker_validation_credentials(
            apparatus.credential.principal.uuid, scope=apparatus.scope, worker_ids=(uuid4(), uuid4())
        ),
    ):
        pytest.fail("Partial issuance must not enter the qualification")
    assert not ApiToken.objects.filter(name="worker-validation").exists()


@pytest.mark.django_db(transaction=True)
def test_operator_smoke_creates_and_retires_two_native_workers(apparatus, operator, worker_cloud):
    from engine.models import DisposableWorker

    output = StringIO()
    call_command(
        "qualify_disposable_workers",
        bootstrap_facts=str(operator),
        scope_kind="organization",
        scope_id=apparatus.scope.organization_uuid,
        stdout=output,
    )
    result = json.loads(output.getvalue())
    assert result["independent_workers"] == 2 and result["cleanup_verified"]
    assert DisposableWorker.objects.filter(terminal_at__isnull=False).count() == 2

    from shared.api_tokens.models import ApiToken
    from shared.models import AuditLog

    tokens = list(ApiToken.objects.filter(name="worker-validation"))
    assert len(tokens) == 4 and all(item.revoked_at is not None for item in tokens)
    assert {item.target_type for item in tokens} == {"installation", "organization", "range"}
    assert all(item.target is not None for item in tokens)
    assert AuditLog.objects.filter(
        actor_principal_uuid=apparatus.credential.principal.uuid, context="operator worker validation"
    ).exists()
