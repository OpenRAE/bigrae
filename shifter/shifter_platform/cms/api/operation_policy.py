"""S6 bindings for canonical CMS operations; S8 activates owning service checks."""

from shared.authorization.operations import OperationPolicy, scope_actions

_INSTALLATION_PREPARE_CONTENT = "installation.prepare_content"
_INSTALLATION_MANAGE_ADAPTERS = "installation.manage_adapters"
_INSTALLATION_MANAGE_CLOUD_AUTHORITY = "installation.manage_cloud_authority"


_READ = scope_actions("read_content", installation=True)
_WRITE = scope_actions("manage_content", installation=True)
_PREPARE = scope_actions("prepare_content", installation=True)
_ADAPTERS = ("organization.manage_adapters",)

API_OPERATION_POLICY: dict[str, OperationPolicy] = {
    "cms_gcp_range_projects_retrieve": OperationPolicy(
        (_INSTALLATION_MANAGE_CLOUD_AUTHORITY,), "installation", "gcp_range_project_registry"
    ),
    "cms_gcp_range_projects_create": OperationPolicy(
        (_INSTALLATION_MANAGE_CLOUD_AUTHORITY,), "installation", "gcp_range_project_registry"
    ),
    "cms_gcp_range_projects_retry_create": OperationPolicy(
        (_INSTALLATION_MANAGE_CLOUD_AUTHORITY,), "installation", "gcp_range_project"
    ),
    "cms_gcp_range_projects_disable_create": OperationPolicy(
        (_INSTALLATION_MANAGE_CLOUD_AUTHORITY,), "installation", "gcp_range_project"
    ),
    "cms_content_scopes_retrieve": OperationPolicy(
        _READ, "scope", "content_scope_collection", selector="policy_filtered_ancestry"
    ),
    "cms_artifact_preparation_create": OperationPolicy(
        _PREPARE, "scope", "preparation_parent", selector="validated_parent"
    ),
    "cms_artifact_preparation_retrieve": OperationPolicy(_PREPARE, "scope", "preparation_operation"),
    "cms_artifact_preparation_cancel_create": OperationPolicy(_PREPARE, "scope", "preparation_operation"),
    "cms_artifact_preparation_retry_create": OperationPolicy(_PREPARE, "scope", "preparation_operation"),
    "cms_catalog_list": OperationPolicy(
        _READ, "scope", "catalog_collection", selector="private_scope_or_explicit_publication"
    ),
    "cms_catalog_retrieve": OperationPolicy(_READ, "scope", "catalog_entry", selector="persisted_source_scope"),
    "cms_catalog_packs_create": OperationPolicy(_WRITE, "scope", "content_parent", selector="validated_parent"),
    "cms_organizations_packs_create": OperationPolicy(("organization.manage_content",), "organization", "organization"),
    "cms_organizations_packs_removal_create": OperationPolicy(
        ("organization.manage_content",), "organization", "organization_pack", selector="persisted_source_scope"
    ),
    "cms_organizations_plugin_packs_list": OperationPolicy(_ADAPTERS, "organization", "organization_plugin_collection"),
    "cms_organizations_plugin_packs_retrieve": OperationPolicy(_ADAPTERS, "organization", "plugin_pack"),
    "cms_organizations_plugin_packs_create": OperationPolicy(_ADAPTERS, "organization", "plugin_pack"),
    "cms_organizations_plugins_retrieve": OperationPolicy(_ADAPTERS, "organization", "organization_plugin_collection"),
    "cms_organizations_plugins_create": OperationPolicy(_ADAPTERS, "organization", "organization"),
    "cms_organizations_plugins_actions_create": OperationPolicy(_ADAPTERS, "organization", "plugin_installation"),
    "cms_preparation_adapter_grants_list": OperationPolicy(
        (_INSTALLATION_MANAGE_ADAPTERS,), "installation", "adapter_grants"
    ),
    "cms_preparation_adapters_list": OperationPolicy(
        (_INSTALLATION_MANAGE_ADAPTERS,), "installation", "adapter_catalog"
    ),
    "cms_preparation_adapters_create": OperationPolicy(
        (_INSTALLATION_MANAGE_ADAPTERS,), "installation", "adapter_catalog"
    ),
    "cms_preparation_adapters_state_create": OperationPolicy(
        (_INSTALLATION_MANAGE_ADAPTERS,), "installation", "adapter"
    ),
    "cms_raes_image_mappings_list": OperationPolicy((_INSTALLATION_PREPARE_CONTENT,), "installation", "image_catalog"),
    "cms_raes_image_mappings_create": OperationPolicy(
        (_INSTALLATION_PREPARE_CONTENT,), "installation", "image_catalog"
    ),
    "cms_raes_image_mappings_disable_create": OperationPolicy(
        (_INSTALLATION_PREPARE_CONTENT,), "installation", "image_mapping"
    ),
    "api_v1_cms_range_workspace_rebind": OperationPolicy(
        scope_actions("manage_range_scope"), "scope", "range_source_and_destination", selector="both_scopes"
    ),
    "cms_scenarios_retrieve": OperationPolicy(_READ, "scope", "catalog_entry", selector="persisted_source_scope"),
    "cms_scenarios_metadata_partial_update": OperationPolicy(
        _WRITE, "scope", "catalog_entry", selector="persisted_source_scope"
    ),
    "cms_scenarios_realizability_retrieve": OperationPolicy(
        _READ, "scope", "catalog_entry", selector="persisted_source_scope"
    ),
    "api_v1_cms_workspace_range_scope_list": OperationPolicy(
        ("workspace.manage_range_scope",), "workspace", "workspace_range_collection"
    ),
}

EXTERNAL_EFFECT_POLICY = {
    "preparation_worker_input": "authenticated_workload_and_live_initiating_principal",
    "preparation_worker_result": "authenticated_workload_and_exact_attempt_generation",
    "vpn_connect": "authenticated_workload_and_live_principal_range_authority",
    "vpn_heartbeat": "authenticated_workload_and_live_principal_range_authority",
    "vpn_end": "authenticated_workload_and_exact_session",
}
