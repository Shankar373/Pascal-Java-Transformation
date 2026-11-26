"""Discovery job manager for the local dashboard (design section 8).

One worker thread drains a bounded queue.  Each job's state is persisted
atomically as ``<store>/jobs/<id>/job.json`` so a restart never reports a job
as still running: a job left ``queued`` or ``running`` is reported ``failed``
with code ``INTERRUPTED`` on load.

Failures are sanitised before they are stored or returned: an
``IngestionError`` keeps its stable ``code`` and a scrubbed message; any other
exception becomes ``INTERNAL_ERROR`` with a generic message, and the details
go only to the logging module.

Timestamps here are run-record data (wall clock, UTC), never inputs to the
deterministic blueprint.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from p1.errors import IngestionError
from p1.server_security import (
    CHECKPOINT_PATTERN,
    ID_PATTERN,
    RequestRejected,
    redact_url,
    resolve_local_directory,
    scrub_message,
)
from p1.tenancy import DEFAULT_TENANT, tenant_root, validate_tenant

__all__ = [
    "JobManager",
    "JobRequest",
    "STEP_DEFINITIONS",
    "MAX_LIST",
    "BLUEPRINT_NAME",
]

LOG = logging.getLogger("p1.jobs")

MAX_LIST = 50
MAX_FINISHED = 200
MAX_BLUEPRINT_BYTES = 64 * 1024 * 1024
BLUEPRINT_NAME = "application-blueprint.json"
GENERIC_ERROR = "The discovery failed unexpectedly. See the server log for details."

#: (id, display name) in pipeline order — matches design section 6.
STEP_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("ingestion", "Ingestion"),
    ("checkpoint", "Checkpoint"),
    ("scanning_inventory", "Scanning & Inventory"),
    ("dependency_analysis", "Dependency Analysis"),
    ("blueprint", "Application Blueprint"),
)
_STEP_IDS = frozenset(step_id for step_id, _ in STEP_DEFINITIONS)
_PROGRESS_STATUSES = {"running", "completed", "warning", "failed"}
_ACTIVE = ("queued", "running")


@dataclass(frozen=True)
class JobRequest:
    """What the worker needs; mirrors ``p1.stage1.DiscoveryRequest`` fields."""

    kind: str
    source: str
    ref: str | None = None
    label: str | None = None
    allow_ssh: bool = False


def _now(precision: str = "seconds") -> str:
    return datetime.now(timezone.utc).isoformat(timespec=precision)


class _QueueFull(IngestionError):
    code = "QUEUE_FULL"


class JobManager:
    """Runs discoveries one at a time and records their progress."""

    def __init__(
        self,
        store: Path,
        discover_fn: Callable[..., Any] | None = None,
        max_queue: int = 8,
        allowed_roots: Iterable[Path] = (),
        max_finished: int = MAX_FINISHED,
        tenant: str = DEFAULT_TENANT,
    ) -> None:
        self.tenant = validate_tenant(tenant)
        #: Tenant-scoped storage root: the default tenant keeps the store
        #: root, every other tenant is isolated under ``tenants/<id>/``.
        self._store = tenant_root(store, self.tenant)
        self._roots = tuple(Path(r).resolve() for r in allowed_roots)
        self._max_finished = max(1, int(max_finished))
        self._max_queue = max_queue
        self._reserved = 0
        self._jobs_dir = self._store / "jobs"
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        self._discover_fn = discover_fn
        self._queue: queue.Queue[tuple[str, JobRequest]] = queue.Queue(maxsize=max_queue)
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._clock: dict[str, float] = {}
        self._cleanup: dict[str, Path] = {}
        self._stopping = threading.Event()
        self._load_existing()
        self._worker = threading.Thread(target=self._run, name="p1-job-worker", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------ public

    def reserve_slot(self) -> None:
        """Claim queue capacity before an upload body is read (``QUEUE_FULL`` if none)."""

        with self._lock:
            if self._queue.qsize() + self._reserved >= self._max_queue:
                raise _QueueFull("the job queue is full; try again shortly")
            self._reserved += 1

    def release_slot(self) -> None:
        """Give back a slot claimed by :meth:`reserve_slot` that was not submitted."""

        with self._lock:
            self._reserved = max(0, self._reserved - 1)

    def submit(self, request: JobRequest, cleanup: Path | None = None,
               reserved: bool = False) -> str:
        """Queue a job; raise ``QUEUE_FULL`` when the bound is reached.

        With ``reserved=True`` the caller holds a :meth:`reserve_slot` claim that
        this call consumes (also when it raises).
        """

        job_id = secrets.token_hex(8)
        job = self._new_job(job_id, request)
        with self._lock:
            if reserved:
                self._reserved = max(0, self._reserved - 1)
            self._jobs[job_id] = job
            if cleanup is not None:
                self._cleanup[job_id] = cleanup
            try:
                self._queue.put_nowait((job_id, request))
            except queue.Full:
                self._jobs.pop(job_id, None)
                self._cleanup.pop(job_id, None)
                raise _QueueFull("the job queue is full; try again shortly") from None
            self._persist(job)
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Public view of one job (with blueprint when completed) or None."""

        job = self._job(job_id)
        if job is None:
            return None
        view = self._public(job)
        view["blueprint"] = self._read_blueprint(job) if job["status"] == "completed" else None
        return view

    def list(self, limit: int = MAX_LIST) -> list[dict[str, Any]]:
        """Newest-first public summaries, capped at :data:`MAX_LIST`."""

        limit = max(1, min(int(limit), MAX_LIST))
        with self._lock:
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: (j["created_at"], j["id"]), reverse=True)
        out = []
        for job in jobs[:limit]:
            view = self._public(job)
            view["summary"] = job.get("summary")
            out.append(view)
        return out

    def status(self, job_id: str) -> str | None:
        """Status string of a job, or None when the id is unknown."""

        job = self._job(job_id)
        return None if job is None else str(job["status"])

    def blueprint_path(self, job_id: str) -> Path | None:
        """Path of the finished artefact directory for a completed job."""

        job = self._job(job_id)
        if job is None or job["status"] != "completed":
            return None
        checkpoint = job.get("checkpoint_id")
        if not isinstance(checkpoint, str) or not CHECKPOINT_PATTERN.match(checkpoint):
            return None
        return self._store / "discoveries" / checkpoint

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop the worker after the current job."""

        self._stopping.set()
        self._worker.join(timeout)

    # ----------------------------------------------------------- internals

    def _new_job(self, job_id: str, request: JobRequest) -> dict[str, Any]:
        label = request.label or (redact_url(request.source) if request.kind == "git" else "")
        return {
            "id": job_id,
            "tenant": self.tenant,
            "status": "queued",
            "kind": request.kind,
            "label": scrub_message(label, 120) if label else None,
            "ref": request.ref,
            "steps": [
                {"id": sid, "name": name, "status": "pending", "message": "",
                 "started_at": None, "duration_ms": None}
                for sid, name in STEP_DEFINITIONS
            ],
            "error": None,
            "checkpoint_id": None,
            "created_at": _now("microseconds"),  # sub-second: orders pruning and listing
            "ingested_at": None,
            "summary": None,
        }

    def _public(self, job: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return {
                "id": job["id"],
                "tenant": job.get("tenant", DEFAULT_TENANT),
                "status": job["status"],
                "kind": job.get("kind"),
                "label": job.get("label"),
                "ref": job.get("ref"),
                "steps": [dict(s) for s in job["steps"]],
                "error": dict(job["error"]) if job["error"] else None,
                "checkpoint_id": job.get("checkpoint_id"),
                "created_at": job["created_at"],
                "run": {"ingested_at": job.get("ingested_at")},
            }

    def _job(self, job_id: str) -> dict[str, Any] | None:
        if not isinstance(job_id, str) or not ID_PATTERN.match(job_id):
            return None
        with self._lock:
            if job_id in self._jobs:
                return self._jobs[job_id]
        loaded = self._read_job_file(self._jobs_dir / job_id / "job.json")
        if loaded is None or loaded.get("id") != job_id:
            return None
        loaded.setdefault("tenant", self.tenant)
        return self._interrupt_if_stale(loaded)

    def _persist(self, job: dict[str, Any]) -> None:
        directory = self._jobs_dir / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        data = json.dumps(job, indent=2, sort_keys=True).encode("utf-8")
        temp = directory / f"job.json.{secrets.token_hex(4)}.tmp"
        temp.write_bytes(data)
        for attempt in range(10):
            try:
                os.replace(temp, directory / "job.json")
                return
            except PermissionError:  # Windows: a reader briefly holds the file
                time.sleep(0.02 * (attempt + 1))
        temp.unlink(missing_ok=True)
        LOG.error("could not persist job %s", job["id"])

    @staticmethod
    def _read_job_file(path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and isinstance(data.get("steps"), list) else None

    def _interrupt_if_stale(self, job: dict[str, Any]) -> dict[str, Any]:
        if job.get("status") not in _ACTIVE:
            return job
        job["status"] = "failed"
        job["error"] = {"code": "INTERRUPTED",
                        "message": "The server stopped before this discovery finished."}
        for step in job["steps"]:
            if step.get("status") == "running":
                step["status"] = "failed"
        self._persist(job)
        return job

    def _load_existing(self) -> None:
        entries = []
        for path in self._jobs_dir.glob("*/job.json"):
            if not ID_PATTERN.match(path.parent.name):
                continue
            job = self._read_job_file(path)
            if job and job.get("id") == path.parent.name:
                job.setdefault("tenant", self.tenant)
                entries.append(job)
        entries.sort(key=lambda j: (str(j.get("created_at")), j["id"]), reverse=True)
        for job in entries:
            self._jobs[job["id"]] = self._interrupt_if_stale(job)
        self._prune()

    def _prune(self) -> None:
        """Keep the newest finished jobs; delete older ones from memory and disk.

        Queued and running jobs are never touched.
        """

        with self._lock:
            finished = [j for j in self._jobs.values() if j["status"] not in _ACTIVE]
            finished.sort(key=lambda j: (str(j["created_at"]), j["id"]), reverse=True)
            doomed = [j["id"] for j in finished[self._max_finished:]]
            for job_id in doomed:
                self._jobs.pop(job_id, None)
        for job_id in doomed:
            shutil.rmtree(self._jobs_dir / job_id, ignore_errors=True)

    def _read_blueprint(self, job: dict[str, Any]) -> dict[str, Any] | None:
        directory = self.blueprint_path(job["id"])
        if directory is None:
            return None
        path = directory / BLUEPRINT_NAME
        try:
            if path.stat().st_size > MAX_BLUEPRINT_BYTES:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            LOG.error("blueprint for job %s is unreadable", job["id"])
            return None
        return data if isinstance(data, dict) else None

    # -------------------------------------------------------------- worker

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                item = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            job_id, request = item
            try:
                self._execute(job_id, request)
            except Exception:  # last-resort guard: the worker must survive
                LOG.exception("job %s crashed the runner", job_id)
            finally:
                self._remove_cleanup(job_id)
                self._prune()

    def _remove_cleanup(self, job_id: str) -> None:
        path = self._cleanup.pop(job_id, None)
        if path is not None:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                LOG.warning("could not remove temporary upload for job %s", job_id)

    def _execute(self, job_id: str, request: JobRequest) -> None:
        job = self._jobs[job_id]
        with self._lock:
            job["status"] = "running"
            self._persist(job)
        progress = self._progress_callback(job)
        try:
            result = self._invoke(request, progress)
            self._finish_ok(job, result)
        except IngestionError as exc:
            self._finish_failed(job, exc.code, scrub_message(exc.message))
        except Exception:
            LOG.exception("discovery %s failed", job_id)
            self._finish_failed(job, "INTERNAL_ERROR", GENERIC_ERROR)

    def _vetted(self, request: JobRequest) -> JobRequest:
        """Re-run the API's containment check at run time (closes the submit-to-run gap).

        Discover receives the *resolved* path, so a link retargeted after the
        API check cannot redirect it.
        """

        if request.kind != "directory":
            return request
        try:
            resolved = resolve_local_directory(request.source, self._roots)
        except RequestRejected:
            raise IngestionError("the directory is not inside an allowed local root",
                                 code="PATH_NOT_ALLOWED") from None
        return replace(request, source=str(resolved))

    def _invoke(self, request: JobRequest, progress: Callable[[str, str, str], None]) -> Any:
        request = self._vetted(request)
        if self._discover_fn is not None:
            return self._discover_fn(request, self._store, progress=progress)
        from p1.stage1 import DiscoveryRequest, discover  # lazy: built concurrently

        real = DiscoveryRequest(kind=request.kind, source=request.source, ref=request.ref,
                                label=request.label, allow_ssh=request.allow_ssh)
        return discover(real, self._store, progress=progress)

    def _progress_callback(self, job: dict[str, Any]) -> Callable[[str, str, str], None]:
        def callback(step_id: str, status: str, message: str = "") -> None:
            try:
                self._apply_progress(job, step_id, status, message)
            except Exception:  # never raise into the pipeline
                LOG.exception("progress update failed")
        return callback

    def _apply_progress(self, job: dict[str, Any], step_id: str, status: str, message: str) -> None:
        if step_id not in _STEP_IDS or status not in _PROGRESS_STATUSES:
            return
        with self._lock:
            step = next(s for s in job["steps"] if s["id"] == step_id)
            step["message"] = scrub_message(message or "", 200)
            if status == "running":
                step["status"] = "running"
                step["started_at"] = _now()
                self._clock[f"{job['id']}:{step_id}"] = time.monotonic()
            else:
                step["status"] = status
                started = self._clock.pop(f"{job['id']}:{step_id}", None)
                if started is not None:
                    step["duration_ms"] = int((time.monotonic() - started) * 1000)
            self._persist(job)

    def _finish_ok(self, job: dict[str, Any], result: Any) -> None:
        checkpoint_id = _checkpoint_id(result)
        blueprint = getattr(result, "blueprint", None)
        with self._lock:
            for step in job["steps"]:
                if step["status"] in ("pending", "running"):
                    step["status"] = "completed"
            job["checkpoint_id"] = checkpoint_id
            job["ingested_at"] = _now()
            job["summary"] = _summary(blueprint)
            job["status"] = "completed"
            self._persist(job)

    def _finish_failed(self, job: dict[str, Any], code: str, message: str) -> None:
        with self._lock:
            for step in job["steps"]:
                if step["status"] == "running":
                    step["status"] = "failed"
            job["error"] = {"code": code, "message": message}
            job["ingested_at"] = _now()
            job["status"] = "failed"
            self._persist(job)


def _checkpoint_id(result: Any) -> str:
    info = getattr(result, "checkpoint", None)
    value = getattr(info, "checkpoint_id", None)
    if value is None and hasattr(info, "as_dict"):
        value = info.as_dict().get("checkpoint_id")
    if not isinstance(value, str) or not CHECKPOINT_PATTERN.match(value):
        raise ValueError("discover returned an invalid checkpoint id")
    return value


def _summary(blueprint: Any) -> dict[str, Any] | None:
    if not isinstance(blueprint, dict):
        return None
    summary = blueprint.get("summary") or {}
    project = blueprint.get("project") or {}
    stage = blueprint.get("stage") or {}
    return {
        "project": project.get("name"),
        "total_files": summary.get("total_files"),
        "blockers": summary.get("blockers"),
        "stage_status": stage.get("status"),
    }
