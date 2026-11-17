"""Resource bounds for the dashboard server's uploads and connections.

Pure helpers kept apart from the HTTP handler so each bound can be tested
without a socket:

* :class:`UploadGate` limits concurrent upload bodies (a refused upload is
  answered ``429 BUSY`` before any body byte is read);
* :func:`upload_deadline` is the total wall-clock allowance for one upload;
* :func:`sweep_uploads` removes ``*.part`` files and orphaned ``*.zip`` files
  left under ``<store>/uploads`` by an earlier process.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

__all__ = [
    "MAX_CONCURRENT_UPLOADS",
    "MAX_CONNECTIONS",
    "PROCESS_START",
    "UPLOAD_BASE_DEADLINE",
    "UPLOAD_MIN_BYTES_PER_SECOND",
    "UploadGate",
    "sweep_uploads",
    "upload_deadline",
]

LOG = logging.getLogger("p1.server")

#: Concurrent upload bodies accepted at once.
MAX_CONCURRENT_UPLOADS = 2
#: Concurrent connections served; the rest get an immediate 503.
MAX_CONNECTIONS = 32
#: Fixed part of the per-upload wall-clock deadline, seconds.
UPLOAD_BASE_DEADLINE = 120.0
#: Slowest sustained rate that earns extra time (1 MiB/s): size-proportional allowance.
UPLOAD_MIN_BYTES_PER_SECOND = 1024 * 1024
#: Files older than this moment belong to an earlier process.
PROCESS_START = time.time()


def upload_deadline(length: int, base: float, min_rate: float) -> float:
    """Seconds allowed to receive *length* bytes: *base* plus length / *min_rate*."""

    return base + max(0, length) / max(1.0, float(min_rate))


class UploadGate:
    """A bounded, non-blocking counter of in-flight uploads."""

    def __init__(self, limit: int = MAX_CONCURRENT_UPLOADS) -> None:
        self._slots = threading.BoundedSemaphore(limit)

    def try_acquire(self) -> bool:
        return self._slots.acquire(blocking=False)

    def release(self) -> None:
        self._slots.release()


def sweep_uploads(directory: Path, before: float = PROCESS_START) -> int:
    """Delete stale ``*.part`` / ``*.zip`` files older than *before*; return the count."""

    removed = 0
    for pattern in ("*.part", "*.zip"):
        for path in directory.glob(pattern):
            try:
                if path.is_file() and path.stat().st_mtime < before:
                    path.unlink()
                    removed += 1
            except OSError:
                LOG.warning("could not remove a stale upload file")
    return removed
