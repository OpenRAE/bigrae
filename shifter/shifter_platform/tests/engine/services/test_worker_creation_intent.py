"""Forward migration and persistence protect original worker creation intent."""

import importlib
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.engine.services.test_disposable_workers import apparatus, create, tenant

__all__ = ["apparatus", "tenant"]


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_migration_recovers_original_trial_and_accepts_legacy_inserts(apparatus):
    from django.db import IntegrityError, connection, transaction
    from django.db.migrations.executor import MigrationExecutor

    from engine.models import DisposableWorker, OperationInput, Range
    from engine.services import bind_worker_trial

    initial, bound = uuid4(), uuid4()
    first = create(apparatus, trial_id=initial)
    second = create(apparatus)
    bind_worker_trial(apparatus.credential, second.worker_id, bound)
    envelopes = list(OperationInput.objects.order_by("pk").values_list("envelope", flat=True))
    before = [("engine", "0123_worker_host_observations")]
    after = [("engine", "0124_worker_creation_intent")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(before)
        legacy = executor.loader.project_state(before).apps.get_model("engine", "DisposableWorker")
        MigrationExecutor(connection).migrate(after)

        original = DisposableWorker.objects.get(pk=first.worker_id)
        later = DisposableWorker.objects.get(pk=second.worker_id)
        assert original.initial_trial_id == original.trial_id == initial
        assert later.initial_trial_id is None and later.trial_id == bound
        with pytest.raises(IntegrityError), transaction.atomic():
            DisposableWorker.objects.filter(pk=later.pk).update(initial_trial_id=bound)
        assert create(apparatus, worker_id=first.worker_id, trial_id=initial).trial_id == initial
        assert create(apparatus, worker_id=second.worker_id).trial_id == bound
        assert list(OperationInput.objects.order_by("pk").values_list("envelope", flat=True)) == envelopes

        # A previous application process omits the new field during a rolling upgrade.
        values = {
            field.attname: getattr(original, field.attname)
            for field in legacy._meta.concrete_fields
            if not field.primary_key and field.name not in {"created_at", "range", "request_id"}
        }
        values.update(
            range_id=Range.objects.create(
                workspace_id=original.range.workspace_id,
                scope_kind=original.range.scope_kind,
                account_id=original.range.account_id,
                organization_id=original.range.organization_id,
                owner_principal_uuid=original.range.owner_principal_uuid,
            ).pk,
            request_id=uuid4(),
            trial_id=bound,
        )
        with pytest.raises(IntegrityError, match="creation intent conflicts"), transaction.atomic():
            DisposableWorker.objects.create(**values, initial_trial_id=uuid4())
        inserted = legacy.objects.create(**values)
        captured = DisposableWorker.objects.get(pk=inserted.pk)
        assert captured.initial_trial_id == captured.trial_id == bound
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())


def test_sqlite_creation_intent_guards_preserve_initial_value():
    migration = importlib.import_module("engine.migrations.0124_worker_creation_intent")
    with closing(sqlite3.connect(":memory:")) as database:
        database.execute(
            "CREATE TABLE engine_disposableworker (id INTEGER PRIMARY KEY, initial_trial_id TEXT, trial_id TEXT)"
        )
        editor = SimpleNamespace(connection=SimpleNamespace(vendor="sqlite"), execute=database.execute)
        migration.install_guard(None, editor)
        database.execute("INSERT INTO engine_disposableworker VALUES (1, NULL, NULL)")
        trial = uuid4().hex
        database.execute("UPDATE engine_disposableworker SET trial_id=? WHERE id=1", (trial,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            database.execute("UPDATE engine_disposableworker SET initial_trial_id=? WHERE id=1", (trial,))
        with pytest.raises(sqlite3.IntegrityError, match="conflicts"):
            database.execute("INSERT INTO engine_disposableworker VALUES (2, NULL, ?)", (trial,))
        database.execute("INSERT INTO engine_disposableworker VALUES (2, ?, ?)", (trial, trial))
        migration.remove_guard(None, editor)
        database.execute("UPDATE engine_disposableworker SET initial_trial_id=? WHERE id=1", (trial,))
