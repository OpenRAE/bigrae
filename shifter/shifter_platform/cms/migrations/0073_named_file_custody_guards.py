"""Retain file purpose, admitted object bytes and range input selections."""

from importlib import import_module

from django.db import migrations

_LEGACY = import_module("cms.migrations.0060_upload_custody_guards")
_UPLOAD_FIELDS = (*_LEGACY._INPUT, "asset_kind", "file_owner_uuid", "replaces_file_id", "replacement_generation")
_FILE_FIELDS = (
    "id",
    "asset_uuid",
    "name",
    "created_at",
    "owner_principal_uuid",
    "scope_kind",
    "account_uuid",
    "organization_uuid",
    "workspace_uuid",
    "scope_generation",
    "s3_key",
    "original_filename",
    "file_size_bytes",
    "sha256_hash",
    "storage_provider",
    "storage_bucket",
    "object_identity",
)
_GUARDS = (
    ("cms_agentupload", "cms_upload_custody_immutable", "cms_guard_upload_custody"),
    ("cms_namedfileasset", "cms_named_file_custody_immutable", "cms_guard_named_file_custody"),
    ("cms_fileassetuse", "cms_file_use_custody_immutable", "cms_guard_file_use_custody"),
)


def _create_guard(editor, names, fields, extra=()):
    vendor = editor.connection.vendor
    compare = "IS DISTINCT FROM" if vendor == "postgresql" else "IS NOT"
    changes = [f"NEW.{field} {compare} OLD.{field}" for field in fields]
    changes.extend(item.replace("COMPARE", compare) for item in extra)
    condition = " OR ".join(f"({item})" for item in changes)
    table, trigger, function = names
    if vendor == "postgresql":
        editor.execute(f"""CREATE FUNCTION {function}()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF {condition} THEN RAISE EXCEPTION 'file or upload custody is immutable' USING ERRCODE = '23514';
            END IF; RETURN NEW; END; $$""")
        editor.execute(f"CREATE TRIGGER {trigger} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()")
    elif vendor == "sqlite":
        editor.execute(f"""CREATE TRIGGER {trigger} BEFORE UPDATE ON {table}
            WHEN {condition} BEGIN SELECT RAISE(ABORT, 'file or upload custody is immutable'); END""")
    else:
        raise RuntimeError("Unsupported upload persistence backend")


def install_guards(apps, schema_editor):
    _LEGACY.remove_guard(apps, schema_editor)
    _create_guard(
        schema_editor,
        _GUARDS[0],
        _UPLOAD_FIELDS,
        (
            "OLD.validated_identity <> '{}' AND NEW.validated_identity COMPARE OLD.validated_identity",
            "OLD.validated_sha256 <> '' AND NEW.validated_sha256 COMPARE OLD.validated_sha256",
            "OLD.agent_id IS NOT NULL AND NEW.agent_id COMPARE OLD.agent_id",
            "OLD.file_asset_id IS NOT NULL AND NEW.file_asset_id COMPARE OLD.file_asset_id",
        ),
    )
    _create_guard(
        schema_editor,
        _GUARDS[1],
        _FILE_FIELDS,
        (
            "OLD.storage_deleted_at IS NOT NULL AND NEW.storage_deleted_at COMPARE OLD.storage_deleted_at",
            """OLD.storage_deleted_at IS NULL AND NEW.storage_deleted_at IS NOT NULL AND EXISTS (
            SELECT 1 FROM cms_fileassetuse u JOIN cms_rangeinstance r ON r.id = u.range_instance_id
            WHERE u.file_asset_id = OLD.id AND r.status <> 'destroyed')""",
        ),
    )
    use = apps.get_model("cms", "FileAssetUse")
    _create_guard(schema_editor, _GUARDS[2], tuple(field.column for field in use._meta.local_fields))


def remove_guards(apps, schema_editor):
    for table, trigger, function in reversed(_GUARDS):
        suffix = f" ON {table}" if schema_editor.connection.vendor == "postgresql" else ""
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {trigger}{suffix}")
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(f"DROP FUNCTION IF EXISTS {function}()")
    _LEGACY.install_guard(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("cms", "0072_named_file_assets")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
