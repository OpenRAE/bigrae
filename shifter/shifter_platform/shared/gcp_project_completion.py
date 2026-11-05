"""Bounded completion proof for independently verified native cloud realization."""

from __future__ import annotations

import hashlib
from typing import Literal
from uuid import UUID

from shifter_adapter_sdk.runtime import ClosedModel, Digest, canonical_digest

from shared.gcp_range_projects import ProjectID
from shared.gcp_runtime_plan import GcpProjectWork


class GcpProjectCompletion(ClosedModel):
    """A configuration-bound readback proof; never secret bytes or requested arrays."""

    schema_version: Literal["bigrae.gcp-project-completion/v1"] = "bigrae.gcp-project-completion/v1"
    lease_id: UUID
    project_id: ProjectID
    configuration_digest: Digest
    observed_state_digest: Digest


def cloud_configuration_digest(work: GcpProjectWork) -> str:
    """Core and worker bind the same approved inputs without disclosing payloads."""
    secrets = {}
    for name, secret in work.secrets.items():
        versions = [
            {
                **{key: value for key, value in row.items() if key != "payload"},
                "payload_sha256": hashlib.sha256(row["payload"]).hexdigest(),
            }
            for row in secret["versions"]
        ]
        secrets[name] = {**secret, "versions": versions}
    return canonical_digest(
        {
            "lease": work.lease.model_dump(mode="json"),
            "accounts": work.accounts,
            "secrets": secrets,
            "grants": work.grants,
            "audits": work.audits,
            "attachments": work.attachments,
        }
    )
