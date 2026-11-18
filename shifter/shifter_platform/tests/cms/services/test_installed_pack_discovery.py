"""Installed organization packs keep their authority when selected in a workspace."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from cms.exceptions import CMSError
from cms.models import RaesPackageSource
from cms.scenarios.registry import check_scenario_access, list_launchable_scenarios
from cms.services._scoped_launch_source import revalidate_scoped_launch
from management.models import ProviderBinding, ServiceCredentialAdmission
from management.services import resolve_service_credential
from shared.authorization import AuthorizationDecision, DecisionKind, port
from shared.identity_scope import ResourceScope
from tests.cms.services.test_principal_content import content_actor
from workspaces.models import Organization, Workspace
from workspaces.services import add_account_member, create_account

__all__ = ["content_actor"]
pytestmark = [pytest.mark.django_db, pytest.mark.postgres]


@pytest.fixture
def installed(content_actor, settings, monkeypatch):
    actor = content_actor
    old = ServiceCredentialAdmission.objects.select_related("binding").get(uuid=actor.credential.credential_uuid)
    binding = ProviderBinding.objects.create(
        principal=old.binding.principal, issuer=old.binding.issuer, subject=str(uuid4())
    )
    admission = ServiceCredentialAdmission.objects.create(
        binding=binding,
        audience=old.audience,
        scopes=[
            "authorization:workspace.read_content",
            "authorization:workspace.launch_range",
            "authorization:organization.read_content",
        ],
    )
    actor.credential = resolve_service_credential(
        issuer=binding.issuer, subject=binding.subject, audience=admission.audience
    )
    account = create_account(kind="team", name="Synthetic pack team")
    organization = Organization.objects.get(account__uuid=account.uuid, is_default=True)
    workspace = Workspace.objects.get(organization=organization, is_default=True)
    actor.scope = ResourceScope("account", account.uuid, organization.uuid, workspace.uuid)
    actor.organization = ResourceScope("account", account.uuid, organization.uuid)
    add_account_member(actor.scope.account_uuid, actor.credential.principal)
    actor.denied = set()

    def check(request):
        actor.seen.append(request)
        allowed = request.scope.account_uuid == actor.scope.account_uuid and request.action not in actor.denied
        return AuthorizationDecision(
            DecisionKind.ALLOWED if allowed else DecisionKind.DENIED, "policy_allowed" if allowed else "policy_denied"
        )

    monkeypatch.setattr(port, "_provider_factory", lambda: SimpleNamespace(check=check))
    actor.source = RaesPackageSource.objects.create(
        scenario_id="synthetic-installed",
        package_name="synthetic-installed",
        source_kind="repo",
        contract_kind="raes",
        contract_profile="shifter",
        package_ref="packs/synthetic",
        package_version="1",
        package_digest="sha256:" + "1" * 64,
        conformance_status="passed",
        owner_principal_uuid=actor.credential.principal.uuid,
        scope_kind="account",
        account_uuid=actor.scope.account_uuid,
        organization_uuid=organization.uuid,
    )
    return actor


def test_workspace_lists_and_admits_its_organization_pack(installed):
    entries = list_launchable_scenarios(installed.credential, scope=installed.scope)
    assert [e["id"] for e in entries] == ["synthetic-installed"]
    assert "packs/synthetic" not in repr(entries)
    assert revalidate_scoped_launch(installed.credential, installed.scope, installed.source) == installed.credential
    assert any(r.action == "organization.read_content" for r in installed.seen)
    installed.source.refresh_from_db()
    assert installed.source.workspace_uuid is None
    assert not installed.source.is_operator_published


def test_workspace_permission_alone_cannot_discover_or_launch_parent_pack(installed):
    installed.denied.add("organization.read_content")
    assert list_launchable_scenarios(installed.credential, scope=installed.scope) == []
    with pytest.raises((ValueError, CMSError)):
        revalidate_scoped_launch(installed.credential, installed.scope, installed.source)


def test_foreign_organization_and_sibling_workspace_stay_private(installed):
    for identifier, fields in [
        ("foreign", {"organization_uuid": uuid4()}),
        ("sibling", {"organization_uuid": installed.organization.organization_uuid, "workspace_uuid": uuid4()}),
    ]:
        RaesPackageSource.objects.create(
            scenario_id=identifier,
            package_name=identifier,
            source_kind="repo",
            contract_kind="raes",
            contract_profile="shifter",
            package_ref="packs/synthetic",
            package_version="1",
            package_digest="sha256:" + "1" * 64,
            conformance_status="passed",
            owner_principal_uuid=installed.credential.principal.uuid,
            scope_kind="account",
            account_uuid=installed.scope.account_uuid,
            **fields,
        )
    assert [e["id"] for e in list_launchable_scenarios(installed.credential, scope=installed.scope)] == [
        "synthetic-installed"
    ]
    for identifier in ("foreign", "sibling"):
        with pytest.raises(ValueError):
            check_scenario_access(identifier, installed.credential, scope=installed.scope)


def test_revoked_destination_launch_permission_still_denies_parent_pack(installed):
    installed.denied.add("workspace.launch_range")
    with pytest.raises(CMSError):
        revalidate_scoped_launch(installed.credential, installed.scope, installed.source)
