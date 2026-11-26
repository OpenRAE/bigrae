"""Audit-action mapping for range and NGFW status changes.

Leaf helper shared by the event handlers and the operation-result appliers. It
lives outside both packages so neither imports the other.
"""

from __future__ import annotations

from shared.audit import AuditAction
from shared.enums import ResourceStatus


def _status_to_action(status: str) -> str:
    """Map range status to audit action."""
    status_action_map = {
        ResourceStatus.READY.value: AuditAction.READY,
        ResourceStatus.FAILED.value: AuditAction.FAILED,
        ResourceStatus.DESTROYED.value: AuditAction.DEPROVISION,
        ResourceStatus.PROVISIONING.value: AuditAction.PROVISION,
        ResourceStatus.DESTROYING.value: AuditAction.DEPROVISION,
    }
    return status_action_map.get(status, AuditAction.UPDATE)
