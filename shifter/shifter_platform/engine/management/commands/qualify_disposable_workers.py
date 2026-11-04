"""Qualify native workers from the existing trusted deployment boundary."""

from __future__ import annotations

import json
import time
from argparse import Namespace
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import close_old_connections, connection
from shifter_adapter_sdk.runtime import decode_message

from engine.services import (
    WorkerView,
    configure_worker_policy,
    create_disposable_worker,
    get_disposable_worker,
    qualify_disposable_worker,
    reconcile_disposable_workers,
    resume_worker_cleanup,
    retire_disposable_worker,
    worker_credential_scope,
)
from management.services import bootstrap_principal_uuid, issue_worker_validation_credentials
from shared.authorization import TargetRef, configured_authorization_provider
from shared.authorization.policy import scope_parent
from shared.bootstrap_facts import load_identity_bootstrap_facts
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.private_files import read_private_file
from workspaces.services import get_identity_cutover_state, hierarchy_target_scope

CredentialFor = Callable[[TargetRef], CredentialContext]


class Command(BaseCommand):
    """Run bounded qualification without creating an application identity or grant."""

    help = "Qualify and retire two disposable workers as the recorded operator."

    def add_arguments(self, parser: CommandParser) -> None:
        """Select exact bootstrap facts, scope and approved apparatus inputs."""
        parser.add_argument("--bootstrap-facts", required=True)
        parser.add_argument("--scope-kind", required=True, choices=("account", "organization", "workspace"))
        parser.add_argument("--scope-id", required=True, type=UUID)
        parser.add_argument("--policy-file")
        parser.add_argument("--timeout", default=900, type=int)
        parser.add_argument("--recover", nargs="+", type=UUID)

    def handle(self, *args: object, **options: object) -> None:
        """Select the recorded operator, then use only native proof and services."""
        try:
            parsed = Namespace(**options)
            if type(parsed.timeout) is not int or not 60 <= parsed.timeout <= 900:
                raise ValueError("Worker qualification timeout is invalid")
            if not isinstance(parsed.scope_id, UUID):
                raise ValueError("Worker qualification scope is invalid")
            principal = _recorded_operator(parsed.bootstrap_facts)
            scope = hierarchy_target_scope(parsed.scope_kind, parsed.scope_id)
            identifiers = _qualification_targets(scope, parsed.recover, parsed.policy_file)
            with issue_worker_validation_credentials(principal, scope=scope, worker_ids=identifiers) as credential:
                if parsed.policy_file:
                    policy = decode_message(read_private_file(parsed.policy_file, limit=131072), limit=131072)
                    configure_worker_policy(credential(TargetRef("installation")), policy)
                self.stderr.write(json.dumps({"worker_ids": [str(value) for value in identifiers]}))
                if parsed.recover:
                    for identifier in identifiers:
                        resume_worker_cleanup(credential(TargetRef("installation")), identifier)
                    self._wait(credential, identifiers, parsed.timeout, retiring=True)
                    result = {"worker_ids": list(map(str, identifiers)), "cleanup_verified": True}
                else:
                    result = self._smoke(credential, scope, identifiers, parsed.timeout)
        except Exception:  # noqa: BLE001  # suppress private input/provider causes, including --traceback
            raise CommandError("Worker qualification failed; inspect owned worker IDs and recovery state") from None
        self.stdout.write(json.dumps(result, sort_keys=True))

    def _smoke(
        self, credential: CredentialFor, scope: ResourceScope, identifiers: tuple[UUID, ...], timeout: int
    ) -> dict[str, object]:
        experiment = uuid4()
        parent = credential(scope_parent(scope))
        qualified = []
        try:

            def create(identifier: UUID) -> None:
                """Admit one owned worker and close its thread-local database connection."""
                close_old_connections()
                try:
                    create_disposable_worker(parent, scope=scope, worker_id=identifier, experiment_id=experiment)
                finally:
                    connection.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                list(executor.map(create, identifiers))
            self._wait(credential, identifiers, timeout, retiring=False)
            qualified = [
                qualify_disposable_worker(credential(TargetRef("range", value)), value) for value in identifiers
            ]
            for field in ("vm_identity", "machine_identity", "daemon_identity"):
                if len({getattr(item, field) for item in qualified}) != 2:
                    raise ValueError("Worker identities are not independent")
        finally:
            self._cleanup(credential, identifiers, timeout)
        return {
            "worker_ids": list(map(str, identifiers)),
            "independent_workers": len(qualified),
            "cleanup_verified": True,
        }

    def _cleanup(self, credential: CredentialFor, identifiers: tuple[UUID, ...], timeout: int) -> None:
        existing = []
        failed = False
        for identifier in identifiers:
            try:
                if worker_credential_scope(identifier) is None:
                    continue
                leaf = credential(TargetRef("range", identifier))
                get_disposable_worker(leaf, identifier)
                existing.append(identifier)
                retire_disposable_worker(leaf, identifier)
            except ObjectDoesNotExist:
                continue
            except Exception:  # noqa: BLE001  # retain native custody and still attempt the other worker
                failed = True
        if existing:
            self._wait(credential, tuple(existing), timeout, retiring=True)
        if failed:
            raise ValueError("Worker cleanup requires recovery")

    @staticmethod
    def _wait(credential: CredentialFor, identifiers: tuple[UUID, ...], timeout: int, *, retiring: bool) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if retiring:
                reconcile_disposable_workers(worker_ids=identifiers)
            workers = [get_disposable_worker(credential(TargetRef("range", value)), value) for value in identifiers]
            if all(item.retired if retiring else item.status == "ready" for item in workers):
                return
            if any(_worker_failed(item, retiring=retiring) for item in workers):
                raise ValueError("Worker qualification requires recovery")
            time.sleep(2)
        raise ValueError("Worker qualification deadline exceeded")


def _recorded_operator(path: str) -> UUID:
    """Resolve only the verified activated bootstrap tuple and current provider binding."""
    facts = load_identity_bootstrap_facts(path)
    state = get_identity_cutover_state()
    principal = bootstrap_principal_uuid(facts.issuer, facts.subject)
    provider = configured_authorization_provider()
    if (
        state is None
        or state.state != "activated"
        or state.bootstrap_verified_at is None
        or principal is None
        or principal != state.bootstrap_principal_uuid
        or (state.provider_store_id, state.model_id) != (provider.store_id, provider.model_id)
    ):
        raise ValueError("Recorded operator is unavailable")
    return principal


def _qualification_targets(
    scope: ResourceScope, recovery: list[UUID] | None, policy_file: str | None
) -> tuple[UUID, ...]:
    """Allocate fresh qualification identities or validate exact retained recovery scope."""
    if recovery is None:
        return uuid4(), uuid4()
    identifiers = tuple(recovery)
    if policy_file or any(worker_credential_scope(value) != scope for value in identifiers):
        raise ValueError("Worker recovery selection is invalid")
    return identifiers


def _worker_failed(worker: WorkerView, *, retiring: bool) -> bool:
    """Distinguish completed retirement from a failed provisioning qualification."""
    return worker.recovery_required or (not retiring and worker.status in {"failed", "destroyed", "destroying"})
