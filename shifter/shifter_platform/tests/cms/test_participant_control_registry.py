"""One installed worker retains P1 owners across requests and drains deliberately."""

import pytest

from tests.cms.test_participant_control_binding import bind, controlled_pack, controlled_source, product_range, tenant

__all__ = ["controlled_pack", "controlled_source", "product_range", "tenant"]
pytestmark = pytest.mark.django_db(transaction=True)


def test_worker_reuses_one_owner_across_native_requests_and_refuses_active_shutdown(product_range, tmp_path, settings):
    from cms.services._participant_control_registry import NativeParticipantControlRegistry

    item = product_range
    binding = bind(item)
    registry = NativeParticipantControlRegistry(settings.PARTICIPANT_CONTROL_INSTALLATION, store_root=tmp_path)
    try:
        with registry.lease(item.case.credential, binding.id) as owner:
            expected = owner.cursor(item.case.credential)
            first = owner
        with registry.lease(item.case.credential, binding.id) as owner:
            assert owner is first
            assert owner.cursor(item.case.credential) == expected
            with pytest.raises(ValueError, match="Active participant requests remain"):
                registry.close()
        with (
            pytest.raises(ValueError, match="Participant control worker is draining"),
            registry.lease(item.case.credential, binding.id),
        ):
            pytest.fail("Shutdown must refuse new native leases")
    finally:
        registry.close()


def test_idle_eviction_releases_only_drained_owner_and_reopens_same_episode(product_range, tmp_path, settings):
    from cms.services._participant_control_registry import NativeParticipantControlRegistry

    item = product_range
    binding = bind(item)
    now = 0
    registry = NativeParticipantControlRegistry(
        settings.PARTICIPANT_CONTROL_INSTALLATION,
        store_root=tmp_path,
        clock=lambda: now,
    )
    try:
        with registry.lease(item.case.credential, binding.id) as first:
            original = first.cursor(item.case.credential)
        now += settings.PARTICIPANT_CONTROL_INSTALLATION.idle_seconds + 1
        with registry.lease(item.case.credential, binding.id) as recovered:
            assert recovered is not first
            assert recovered.cursor(item.case.credential) == original
    finally:
        registry.close()
