"""CMS-owned file admission and retained version fences for adapter planning."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from django.db import transaction
from shifter_adapter_sdk.runtime import MAX_FILE_INPUT_BYTES, canonical_digest

from cms.exceptions import CMSError
from cms.models import AgentUploadBudget, FileAssetUse, NamedFileAsset, RangeInstance
from shared.authorization.policy import scope_parent
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.operation_authority import credential_reference_fields
from shared.runtime_file_inputs import RuntimeFileBinding
from shared.runtime_plugin_binding import RuntimePluginScope
from workspaces.services import resolve_resource_scope

from ._content_authority import content_scope, fence_content_scope, require_content_scope
from ._upload_scope import _scope_digest

UNAVAILABLE = "The adapter's required files are unavailable"


def file_use_range_digest(instance: RangeInstance) -> str:
    """Bind the request and its original CMS ownership and placement."""
    return canonical_digest(
        {
            "request": str(instance.request.request_id) if instance.request is not None else None,
            "range": str(instance.uuid),
            "owner": str(instance.owner_principal_uuid),
            "scope": [instance.scope_kind, instance.account_id, instance.organization_id, instance.workspace_id],
        }
    )


def _within(file_scope: ResourceScope, launch_scope: ResourceScope, *, assignment: bool) -> bool:
    """Require a common customer; launch may consume only its own ancestors."""
    return (
        file_scope.kind == launch_scope.kind == "account"
        and file_scope.account_uuid == launch_scope.account_uuid
        and (file_scope.organization_uuid is None or file_scope.organization_uuid == launch_scope.organization_uuid)
        and (
            assignment or file_scope.workspace_uuid is None or file_scope.workspace_uuid == launch_scope.workspace_uuid
        )
    )


def _binding(row: NamedFileAsset) -> RuntimeFileBinding:
    return RuntimeFileBinding(
        asset_uuid=row.asset_uuid,
        version_id=row.pk,
        sha256="sha256:" + row.sha256_hash,
        size_bytes=row.file_size_bytes,
    )


def prepare_file_selection(
    credential: CredentialContext, scope: ResourceScope, selections: Mapping[str, UUID], *, assignment: bool = False
) -> dict[str, RuntimeFileBinding]:
    """Resolve current versions and remote read policy before acquiring SQL locks."""
    admitted = {}
    for name, identifier in selections.items():
        row = NamedFileAsset.objects.filter(asset_uuid=identifier).first()
        actual = content_scope(row)
        if row is None or not _within(actual, scope, assignment=assignment):
            raise CMSError(UNAVAILABLE)
        require_content_scope(credential, actual, "read_content")
        admitted[name] = _binding(row)
    if sum(item.size_bytes for item in admitted.values()) > MAX_FILE_INPUT_BYTES:
        raise CMSError(UNAVAILABLE)
    return admitted


def prepare_runtime_files(
    credential: CredentialContext, scope: ResourceScope, plugin: RuntimePluginScope | None
) -> RuntimePluginScope | None:
    """Bind CMS's admission to the exact executable and administrator selection."""
    if plugin is None:
        return None
    from engine.services import runtime_plugin_file_selection

    digest, selections = runtime_plugin_file_selection(plugin)
    files = prepare_file_selection(credential, scope, selections)
    return RuntimePluginScope(
        **plugin.model_dump(exclude={"files", "binding_digest"}), files=files, binding_digest=digest
    )


def fence_file_selection(
    credential: CredentialContext,
    scope: ResourceScope,
    files: Mapping[str, RuntimeFileBinding],
    *,
    assignment: bool = False,
) -> dict[str, NamedFileAsset]:
    """Serialize admission with replacement, retirement and physical cleanup."""
    if not transaction.get_connection().in_atomic_block:
        raise CMSError(UNAVAILABLE)
    snapshots = {name: NamedFileAsset.objects.filter(pk=item.version_id).first() for name, item in files.items()}
    scopes = {name: content_scope(row) for name, row in snapshots.items()}
    for digest in sorted({_scope_digest(actual) for actual in scopes.values()}):
        if not AgentUploadBudget.objects.select_for_update().filter(pk=digest).exists():
            raise CMSError(UNAVAILABLE)
    locked = {
        row.pk: row
        for row in NamedFileAsset.objects.select_for_update()
        .filter(pk__in=[item.version_id for item in files.values()])
        .order_by("pk")
    }
    result = {}
    for name, item in files.items():
        row = locked.get(item.version_id)
        actual = scopes[name]
        if (
            row is None
            or _binding(row) != item
            or content_scope(row) != actual
            or not _within(actual, scope, assignment=assignment)
        ):
            raise CMSError(UNAVAILABLE)
        fence_content_scope(credential, actual)
        result[name] = row
    return result


def pin_runtime_file_uses(
    credential: CredentialContext,
    scope: ResourceScope,
    instance: RangeInstance,
    files: Mapping[str, RuntimeFileBinding],
) -> None:
    """Commit file uses beside the first native range; never overwrite a replay."""
    rows = fence_file_selection(credential, scope, files)
    resolved = resolve_resource_scope(scope)
    if (
        instance.request is None
        or (instance.scope_kind, instance.account_id, instance.organization_id, instance.workspace_id)
        != (
            resolved.kind,
            resolved.account_id,
            resolved.organization_id,
            resolved.workspace_id,
        )
        or instance.status != "provisioning"
        or instance.range_id is not None
    ):
        raise CMSError(UNAVAILABLE)
    for name, row in rows.items():
        actual = content_scope(row)
        parent = scope_parent(actual)
        FileAssetUse.objects.create(
            file_asset=row,
            range_instance=instance,
            input_name=name,
            **credential_reference_fields(credential),
            authority_kind="content",
            authority_action=f"{parent.type}.read_content",
            authority_target_type=parent.type,
            authority_target_uuid=parent.uuid,
            authority_scope_kind=actual.kind,
            authority_account_uuid=actual.account_uuid,
            authority_organization_uuid=actual.organization_uuid,
            authority_workspace_uuid=actual.workspace_uuid,
            authority_owner_uuid=row.owner_principal_uuid,
            authority_resource_uuid=instance.uuid,
            authority_binding_digest=file_use_range_digest(instance),
        )
