"""Bounded process-owned lifetimes for persistent native participant runtimes."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from os import getpid
from pathlib import Path
from threading import RLock
from time import monotonic
from uuid import UUID

from shared.credentials import CredentialContext
from shared.native_participant import NativeControlUnavailable
from shared.participant_control_installation import NativeControlInstallation

from ._participant_control_installation import require_native_control_installation
from ._participant_control_owner import NativeParticipantControlOwner, open_native_participant_control_owner

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _OwnerEntry:
    owner: NativeParticipantControlOwner = field(repr=False)
    last_used: float
    users: int = 0


class NativeParticipantControlRegistry:
    """Retain real owners across requests; never evict a leased or unresolved owner.

    Only the fixed single-process worker creates this registry. Its routes
    authorize through the owner's native services for every read or mutation.
    The registry holds no portable state or competing execution verdict.
    """

    def __init__(
        self,
        installation: NativeControlInstallation,
        *,
        store_root: Path | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not isinstance(installation, NativeControlInstallation):
            raise ValueError("Participant control installation unavailable")
        self._installation = installation
        self._store_root = installation.store_root if store_root is None else store_root
        if not self._store_root.is_absolute():
            raise ValueError("Participant control storage unavailable")
        self._clock, self._pid = clock, getpid()
        self._lock = RLock()
        self._owners: dict[UUID, _OwnerEntry] = {}
        self._draining = False

    def _assert_process(self) -> None:
        if getpid() != self._pid:
            raise NativeControlUnavailable("Participant control owner process changed")

    def _prune_idle(self, now: float) -> None:
        for binding_id, entry in tuple(self._owners.items()):
            if entry.users or now - entry.last_used < self._installation.idle_seconds:
                continue
            try:
                entry.owner.close()
            except Exception:  # noqa: BLE001  # retaining ownership is the safe failure, never force-release resources
                logger.warning("Participant runtime retained during idle drain", extra={"binding_ref": str(binding_id)})
                continue
            del self._owners[binding_id]

    @contextmanager
    def lease(self, credential: CredentialContext, binding_id: UUID) -> Iterator[NativeParticipantControlOwner]:
        """Borrow one owner without allowing another request to close it in use."""
        with self._lock:
            self._assert_process()
            if self._draining:
                raise NativeControlUnavailable("Participant control worker is draining")
            require_native_control_installation(self._installation.digest)
            now = self._clock()
            self._prune_idle(now)
            entry = self._owners.get(binding_id)
            if entry is None:
                if len(self._owners) >= self._installation.max_contexts:
                    raise NativeControlUnavailable("Participant control owner capacity reached")
                owner = open_native_participant_control_owner(credential, binding_id, store_root=self._store_root)
                entry = _OwnerEntry(owner, now)
                self._owners[binding_id] = entry
            entry.users += 1
        try:
            yield entry.owner
        finally:
            with self._lock:
                entry.users -= 1
                entry.last_used = self._clock()

    def close(self) -> None:
        """Stop new leases and retain each owner until requests and native callbacks drain."""
        with self._lock:
            self._assert_process()
            self._draining = True
            if any(entry.users for entry in self._owners.values()):
                raise ValueError("Active participant requests remain")
            for binding_id, entry in tuple(self._owners.items()):
                entry.owner.close()
                del self._owners[binding_id]

    @property
    def draining(self) -> bool:
        with self._lock:
            self._assert_process()
            return self._draining

    def begin_drain(self) -> None:
        """Refuse new requests while existing requests and cessation replies drain."""
        with self._lock:
            self._assert_process()
            self._draining = True
