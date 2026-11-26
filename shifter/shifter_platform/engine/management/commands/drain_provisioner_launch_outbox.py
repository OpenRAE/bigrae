"""Drain validated launch intents from the dedicated privileged worker."""

from __future__ import annotations

import contextlib
import tempfile
import threading
import time
from argparse import ArgumentParser
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from engine.services import (
    reconcile_feature_artifact_acquisitions,
    reconcile_participant_validations,
    reconcile_runtime_plugin_operations,
    reconcile_runtime_plugins,
)
from engine.services._failed_cleanup_retry import retry_due_failed_cleanup_tasks
from engine.services._launch_interrupt_convergence import drain_due_interrupts
from engine.services._launch_outbox import claim_next_intent, launch_intent
from engine.services._vpn_profiles import reconcile_vpn_profiles

HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "worker-provisioner-launcher-heartbeat"
HEARTBEAT_INTERVAL_SECONDS = 30


class Command(BaseCommand):
    """Drain due launch intents while maintaining worker liveness."""

    help = "Launch due provisioner intents from the dedicated launcher identity."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Register batch and polling options for the launcher worker."""
        parser.add_argument("--batch-size", type=int, default=20)
        parser.add_argument("--loop", action="store_true", default=False)
        parser.add_argument("--interval", type=int, default=10)

    def handle(self, *args: Any, **options: Any) -> None:
        """Drain once or continuously according to the command options."""
        while True:
            self._touch_heartbeat()
            drained = self._drain_batch(options["batch_size"])
            interrupted = self._drain_interrupts(options["batch_size"])
            with self._active_heartbeat():
                retry_due_failed_cleanup_tasks(limit=3)
                reconcile_runtime_plugins(limit=3)
                reconcile_runtime_plugin_operations(limit=30)
                reconcile_participant_validations(limit=3)
                reconcile_feature_artifact_acquisitions(limit=3)

                reconcile_vpn_profiles(limit=100)
            self.stdout.write(f"Drained {drained} launch intents, {interrupted} interrupts")
            if not options["loop"]:
                return
            time.sleep(options["interval"])

    def _drain_interrupts(self, batch_size: int) -> int:
        """Converge due provision-task interrupts (#277) on the same worker."""
        with self._active_heartbeat():
            return drain_due_interrupts(batch_size)

    @staticmethod
    def _touch_heartbeat() -> None:
        """Refresh the launcher liveness marker when the filesystem permits."""
        with contextlib.suppress(OSError):
            HEARTBEAT_FILE.touch()

    @contextlib.contextmanager
    def _active_heartbeat(self) -> Iterator[None]:
        """Keep liveness fresh while a bounded provider reconciliation runs."""
        stopped = threading.Event()

        def heartbeat_loop() -> None:
            """Refresh liveness until the active provider call completes."""
            while not stopped.wait(HEARTBEAT_INTERVAL_SECONDS):
                self._touch_heartbeat()

        self._touch_heartbeat()
        thread = threading.Thread(
            target=heartbeat_loop,
            name="provisioner-launcher-heartbeat",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=1)
            self._touch_heartbeat()

    def _drain_batch(self, batch_size: int) -> int:
        drained = 0
        for _ in range(batch_size):
            row = claim_next_intent()
            if row is None:
                break
            with self._active_heartbeat():
                launch_intent(row)
            drained += 1
        return drained
