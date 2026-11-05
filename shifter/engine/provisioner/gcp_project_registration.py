"""Read-only project registration at the existing native provisioner boundary."""

from __future__ import annotations

import os
from uuid import UUID

from cryptography.fernet import Fernet
from shared.gcp_project_registration import (
    PROTECTED_IMAGE_ENV_NAMES,
    PROTECTED_PROJECT_ENV_NAMES,
    GcpProjectRegistrationInput,
    configured_project_ids,
)


def run_project_registration(request_id: str, operation_id: str, *, operation: str = "register") -> None:
    """Inventory metadata and retain encrypted evidence; never grant roles or create projects."""
    from config import resolve_cloud_provider
    from config._gce_image_keys import _load_gce_image_key_profiles
    from gcp_project_baselines import GcsBaselineStore, capture_project_baseline, verify_project_baseline
    from gcp_project_inventory import GcpProjectInventory
    from provisioner_db_appends import OperationRef, append_operation_step_result
    from provisioner_db_operation_input import get_operation_input

    if operation not in {"register", "verify"}:
        raise ValueError("Registered project operation unavailable")
    validated = get_operation_input(
        operation_id=operation_id, request_id=request_id, resource="range-project", operation=operation
    )
    ref = OperationRef(validated.request_id, validated.operation_id)
    try:
        original = GcpProjectRegistrationInput.model_validate(validated.payload)
        profiles = _load_gce_image_key_profiles()
        images = [os.environ.get(name, "") for name in PROTECTED_IMAGE_ENV_NAMES]
        images.extend(
            profile.source_image or profile.source_machine_image
            for entries in profiles.values()
            for profile in entries.values()
        )
        protected = configured_project_ids(
            (os.environ.get(name, "") for name in PROTECTED_PROJECT_ENV_NAMES),
            images,
        )
        if (
            resolve_cloud_provider() != "gcp"
            or str(original.registration_id) != str(UUID(request_id))
            or original.project_id in protected
        ):
            raise ValueError("Registered project capture unavailable")
        if (operation == "verify") != (original.baseline is not None):
            raise ValueError("Registered project operation unavailable")
        inventory, store = GcpProjectInventory(), GcsBaselineStore()
        cipher = Fernet(os.environ["FIELD_ENCRYPTION_KEY"].encode())
        receipt = (
            capture_project_baseline(original, UUID(operation_id), inventory=inventory, store=store, cipher=cipher)
            if operation == "register"
            else verify_project_baseline(original, inventory=inventory, store=store, cipher=cipher)
        )
    except Exception:  # noqa: BLE001  # provider inventory, credentials and baseline bytes never enter diagnostics
        append_operation_step_result(
            ref,
            resource="range-project",
            operation=operation,
            step="gcp_project_failed",
            result_payload={"reason_code": "cloud_operation_failed", "diagnostic": "Registered project capture failed"},
        )
        raise ValueError("Registered project capture failed") from None
    append_operation_step_result(
        ref,
        resource="range-project",
        operation=operation,
        step="gcp_project_ready",
        result_payload=receipt.model_dump(mode="json"),
    )
