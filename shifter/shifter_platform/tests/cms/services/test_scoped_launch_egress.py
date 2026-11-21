"""Workspace-less launch scopes inherit the deployment egress baseline (ADR-017-R5)."""

from __future__ import annotations

from installation.range_egress import RangeEgressMode

from cms.services._range_workspace import resolve_scope_egress_mode


def test_workspace_less_scope_inherits_status_quo_egress() -> None:
    assert resolve_scope_egress_mode(None) == RangeEgressMode.STATUS_QUO.value
