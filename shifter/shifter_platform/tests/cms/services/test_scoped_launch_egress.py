"""Egress pinning for scoped range launches (organization or account placement)."""

from __future__ import annotations

from installation.range_egress import RangeEgressMode

from cms.services._scoped_launch_reservation import _launch_scope_egress


def test_launch_without_workspace_inherits_the_deployment_baseline():
    """An organization- or account-placed launch has no selector and is not zero egress."""
    assert _launch_scope_egress(None, locked=True) == RangeEgressMode.STATUS_QUO.value
    assert _launch_scope_egress(None, locked=False) == RangeEgressMode.STATUS_QUO.value
