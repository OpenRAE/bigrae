"""Real PostgreSQL serializes duplicate and aggregate experiment claims."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection, connections

from tests.cms.test_experiment_admission import admit
from tests.cms.test_experiment_admission import experiment_inputs as experiment_inputs
from tests.cms.test_runtime_plugins import tenant as tenant
from tests.cms.test_trial_archives import custody as custody

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


@pytest.mark.parametrize("same_entry", [True, False])
def test_parallel_claims_obey_unique_claim_and_aggregate_ceiling(experiment_inputs, same_entry):
    from cms.models import ExperimentEntry
    from cms.services import claim_experiment_entry

    assert connection.vendor == "postgresql"
    batch = admit(experiment_inputs)
    actor, organization, *_ = experiment_inputs
    entry_ids = list(batch.inputs["plan"]["entries"])
    selected = [entry_ids[0], entry_ids[0] if same_entry else entry_ids[-1]]
    barrier = threading.Barrier(2, timeout=30)

    def claim(entry_id):
        close_old_connections()
        try:
            barrier.wait()
            return claim_experiment_entry(actor.credential, organization.uuid, batch.id, entry_id)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, selected))
    assert sum(item is not None for item in claims) == 1
    assert ExperimentEntry.objects.exclude(token=None).count() == 1
    assert ExperimentEntry.objects.filter(batch_id=batch.id, state="pending").count() == batch.expected_trials - 1


def test_duplicate_admissions_publish_one_complete_batch(experiment_inputs, monkeypatch):
    from cms.models import ExperimentBatch, ExperimentEntry, ExperimentSnapshot
    from cms.services import _experiment_batches

    assert connection.vendor == "postgresql"
    # The real installed compiler runs once. The barrier models two identical
    # compilation results arriving concurrently at the transactional publication.
    prepared = admit(experiment_inputs)
    expected = prepared.expected_trials
    stored = {
        key: snapshot.encode()
        for key, snapshot in ExperimentSnapshot.objects.values_list("plan_entry_id", "snapshot_json")
    }
    ExperimentEntry.objects.all().delete()
    ExperimentSnapshot.objects.all().delete()
    ExperimentBatch.objects.all().delete()
    payload = dict(prepared.inputs)
    for key in ("organization_uuid", "destination", "source"):
        payload.pop(key)
    barrier = threading.Barrier(2, timeout=30)

    def compiled(*args, snapshots, **kwargs):
        barrier.wait()
        for snapshot in stored.values():
            snapshots.write(snapshot)
        return dict(payload), [(key, len(snapshot)) for key, snapshot in stored.items()]

    monkeypatch.setattr(_experiment_batches, "compile_pack_experiment", compiled)

    def publish(_):
        close_old_connections()
        try:
            return admit(experiment_inputs)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        batches = list(executor.map(publish, range(2)))
    assert batches[0].id == batches[1].id
    assert ExperimentBatch.objects.count() == 1
    assert ExperimentEntry.objects.count() == expected
    assert ExperimentSnapshot.objects.count() == expected
