"""One cooperative writer per canonical database, including maintenance."""

from contextlib import contextmanager
from pathlib import Path
import fcntl
import os


@contextmanager
def writer_lock(database):
    path = Path(database).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the inode: unlinking a live lock would permit a second writer.
    with open(str(path) + ".writer.lock", "a", encoding="utf-8") as handle:
        os.chmod(handle.name, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Another sampler or maintenance operation owns this database"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
