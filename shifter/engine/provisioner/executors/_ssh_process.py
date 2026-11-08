"""Local ssh client process errors and bounded output copy for the guest SSH executors."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time

from executors.base import ExecutorConnectionError, ExecutorTimeoutError

#: Message when the local ssh client binary is absent.
SSH_CLIENT_MISSING = "ssh binary not found. Ensure openssh-client is installed."


class GuestSSHConnectionError(ExecutorConnectionError):
    """Raised when SSH connection fails."""


def invoke_ssh_to_file(ssh_args: list[str], output_path: str, max_bytes: int, timeout_seconds: int) -> int:
    """Stream the client's standard output to a file within a byte and time bound."""
    deadline = time.monotonic() + timeout_seconds
    with open(output_path, "wb") as output, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(  # noqa: S603  # NOSONAR — trusted ssh binary with controlled args
                ssh_args, stdin=subprocess.DEVNULL, stdout=output, stderr=stderr_file
            )
        except FileNotFoundError as e:
            raise GuestSSHConnectionError(SSH_CLIENT_MISSING) from e
        except OSError as e:
            raise GuestSSHConnectionError(f"SSH subprocess failed: {e}") from e
        while process.poll() is None:
            if os.path.getsize(output_path) > max_bytes or time.monotonic() > deadline:
                process.kill()
                process.wait()
                raise ExecutorTimeoutError("SSH output exceeded its byte or time bound")
            time.sleep(0.5)
    if os.path.getsize(output_path) > max_bytes:
        raise ExecutorTimeoutError("SSH output exceeded its byte bound")
    return process.returncode
