"""Reauthorize CMS's exact retained file use before supplying bounded material."""

from collections.abc import Mapping
from uuid import UUID

from django.conf import settings
from django.db import transaction

from cms.exceptions import CMSError
from cms.models import FileAssetUse, NamedFileAsset, RangeInstance
from shared.authorization.policy import scope_parent
from shared.cloud import get_object_storage
from shared.operation_authority import credential_reference_from_record
from shared.runtime_file_inputs import RuntimeFileBinding
from workspaces.services import resource_scope_from_ids

from ._content_authority import content_scope, fence_content_scope, require_content_scope
from ._runtime_file_admission import UNAVAILABLE, _binding, _within, file_use_range_digest


def _check_use(use: FileAssetUse, item: RuntimeFileBinding, instance: RangeInstance) -> None:
    """Require the original range, read authority and exact retained version."""
    row = use.file_asset
    actual = content_scope(row)
    parent = scope_parent(actual)
    launch_scope = resource_scope_from_ids(
        kind=instance.scope_kind,
        account_id=instance.account_id,
        organization_id=instance.organization_id,
        workspace_id=instance.workspace_id,
    )
    recorded = (
        use.authority_kind,
        use.authority_resource_uuid,
        use.authority_owner_uuid,
        use.authority_binding_digest,
        use.authority_target_type,
        use.authority_target_uuid,
        use.authority_action,
        use.authority_scope_kind,
        use.authority_account_uuid,
        use.authority_organization_uuid,
        use.authority_workspace_uuid,
    )
    expected = (
        "content",
        instance.uuid,
        row.owner_principal_uuid,
        file_use_range_digest(instance),
        parent.type,
        parent.uuid,
        f"{parent.type}.read_content",
        actual.kind,
        actual.account_uuid,
        actual.organization_uuid,
        actual.workspace_uuid,
    )
    if recorded != expected:
        raise CMSError(UNAVAILABLE)
    if (
        _binding(row) != item
        or row.storage_deleted_at is not None
        or not _within(actual, launch_scope, assignment=False)
        or instance.status not in {"pending", "provisioning"}
        or instance.range_id is None
        or row.storage_provider != str(settings.CLOUD_PROVIDER)
    ):
        raise CMSError(UNAVAILABLE)


def load_runtime_file_inputs(request_id: UUID, bindings: Mapping[str, RuntimeFileBinding]) -> dict[str, bytes]:
    """Read only the versions admitted to this request, including retired versions."""
    instance = RangeInstance.all_objects.select_related("request").get(request__request_id=request_id)
    uses = {
        use.input_name: use for use in FileAssetUse.objects.select_related("file_asset").filter(range_instance=instance)
    }
    if not bindings or set(uses) != set(bindings):
        raise CMSError(UNAVAILABLE)
    admitted = {}
    material = {}
    for name, item in bindings.items():
        use = uses[name]
        _check_use(use, item, instance)
        row = use.file_asset
        actual = content_scope(row)
        admitted[name] = require_content_scope(credential_reference_from_record(use), actual, "read_content")
        material[name] = get_object_storage().read_object_header(
            bucket=row.storage_bucket,
            key=row.s3_key,
            max_bytes=item.size_bytes + 1,
            expected_identity=row.object_identity,
        )
        item.verify_material(material[name])
    # Repeat remote policy after storage I/O, before local SQL proof fences.
    # A changed grant cannot ride through a slow provider read.
    for name, use in uses.items():
        admitted[name] = require_content_scope(admitted[name], content_scope(use.file_asset), "read_content")
    with transaction.atomic():
        current = RangeInstance.all_objects.select_for_update().get(pk=instance.pk)
        if current.request_id != instance.request_id or current.range_id != instance.range_id:
            raise CMSError(UNAVAILABLE)
        for name, item in bindings.items():
            use = FileAssetUse.objects.select_for_update().get(pk=uses[name].pk)
            use.file_asset = NamedFileAsset.all_objects.select_for_update().get(pk=use.file_asset_id)
            _check_use(use, item, current)
            fence_content_scope(admitted[name], content_scope(use.file_asset))
    return material
