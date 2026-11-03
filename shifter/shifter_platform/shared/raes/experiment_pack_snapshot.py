"""Private bounded snapshots of administrator-managed local pack installations."""

import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from shared.raes.package_loader import RaesPackageError


@contextmanager
def stage_local_experiment_pack(
    root: Path,
    *,
    max_bytes: int,
    max_entries: int,
) -> Iterator[Path]:
    """Copy regular bytes through directory descriptors; never follow a pack link."""
    with tempfile.TemporaryDirectory(prefix="experiment-pack-") as directory:
        target = Path(directory) / root.name
        target.mkdir()
        total = 0
        count = 0
        for current, directories, files, descriptor in os.fwalk(root, follow_symlinks=False):
            count += len(directories) + len(files)
            if count > max_entries:
                raise RaesPackageError("Experiment pack exceeds the member bound")
            relative = Path(current).relative_to(root)
            for name in directories:
                if not stat.S_ISDIR(os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode):
                    raise RaesPackageError("Experiment pack contains a linked directory")
                (target / relative / name).mkdir()
            for name in files:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                with os.fdopen(fd, "rb") as source:
                    metadata = os.fstat(source.fileno())
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes - total:
                        raise RaesPackageError("Experiment pack exceeds the byte or file-type bound")
                    with (target / relative / name).open("xb") as output:
                        while chunk := source.read(min(1024**2, max_bytes - total + 1)):
                            total += len(chunk)
                            if total > max_bytes:
                                raise RaesPackageError("Experiment pack exceeds the byte bound")
                            output.write(chunk)
        yield target
