"""Job manager: state machine, persistence, restart safety, bounds, sanitising."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "stage1"))

from enterprise_app import ENTERPRISE_APP, write_enterprise_app  # noqa: E402
from fakes import load_sample, make_fake_discover  # noqa: E402
from p1.errors import IngestionError  # noqa: E402
from p1.jobs import MAX_LIST, JobManager, JobRequest  # noqa: E402

GIT = JobRequest(kind="git", source="https://git.example.com/a/b.git", ref="main")


def wait_for(manager: JobManager, job_id: str, states=("completed", "failed"), timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = manager.get(job_id)
        if view and view["status"] in states:
            return view
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {states}: {manager.get(job_id)}")


@pytest.fixture()
def make_manager(tmp_path):
    created: list[JobManager] = []

    def factory(**kwargs):
        manager = JobManager(tmp_path / "store", **kwargs)
        created.append(manager)
        return manager

    yield factory
    for manager in created:
        manager.shutdown()


def test_completed_job_records_steps_checkpoint_and_blueprint(make_manager, tmp_path):
    manager = make_manager(discover_fn=make_fake_discover())
    job_id = manager.submit(GIT)
    assert len(job_id) == 16 and int(job_id, 16) >= 0

    view = wait_for(manager, job_id)

    assert view["status"] == "completed"
    assert view["error"] is None
    assert view["checkpoint_id"] == load_sample()["project"]["checkpoint"]["id"]
    assert [s["id"] for s in view["steps"]] == [
        "ingestion", "checkpoint", "scanning_inventory", "dependency_analysis", "blueprint"]
    assert [s["status"] for s in view["steps"]] == [
        "completed", "completed", "completed", "warning", "completed"]
    assert all(isinstance(s["duration_ms"], int) for s in view["steps"])
    assert view["steps"][0]["started_at"].endswith("+00:00")
    assert view["run"]["ingested_at"].endswith("+00:00")
    assert view["blueprint"] == load_sample()


def test_state_is_persisted_atomically_as_job_json(make_manager, tmp_path):
    manager = make_manager(discover_fn=make_fake_discover())
    job_id = manager.submit(GIT)
    wait_for(manager, job_id)
    path = tmp_path / "store" / "jobs" / job_id / "job.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "completed" and data["id"] == job_id
    assert list(path.parent.glob("*.tmp")) == []
    assert "source" not in data  # the request source (a path or URL) is never stored


def test_running_state_is_visible_while_discover_blocks(make_manager):
    gate = threading.Event()
    manager = make_manager(discover_fn=make_fake_discover(gate=gate))
    job_id = manager.submit(GIT)
    view = wait_for(manager, job_id, states=("running",))
    deadline = time.monotonic() + 5
    while view["steps"][0]["status"] != "running" and time.monotonic() < deadline:
        time.sleep(0.01)
        view = manager.get(job_id)
    assert view["steps"][0]["status"] == "running"
    assert view["blueprint"] is None
    gate.set()
    assert wait_for(manager, job_id)["status"] == "completed"


def test_ingestion_error_keeps_code_and_scrubs_paths_and_tokens(make_manager):
    error = IngestionError(
        r"cannot read C:\Users\alice\secret\repo.zip at /home/bob/x/y with token=abcd1234secret",
        code="UNSAFE_PATH")
    manager = make_manager(discover_fn=make_fake_discover(error=error))
    view = wait_for(manager, manager.submit(GIT))
    assert view["status"] == "failed"
    assert view["error"]["code"] == "UNSAFE_PATH"
    text = view["error"]["message"]
    for leaked in ("alice", "bob", "abcd1234secret", "Users", "/home"):
        assert leaked not in text
    assert view["steps"][0]["status"] == "failed"
    assert view["blueprint"] is None


def test_unexpected_exception_is_generic_and_only_logged(make_manager, caplog):
    boom = RuntimeError(r"secret C:\internal\path password=hunter2")
    manager = make_manager(discover_fn=make_fake_discover(error=boom))
    with caplog.at_level(logging.ERROR, logger="p1.jobs"):
        view = wait_for(manager, manager.submit(GIT))
    assert view["error"]["code"] == "INTERNAL_ERROR"
    serialised = json.dumps(view)
    assert "hunter2" not in serialised and "internal" not in serialised
    assert any("failed" in r.getMessage() for r in caplog.records)


def test_job_left_running_by_a_crash_is_reported_interrupted(tmp_path):
    store = tmp_path / "store"
    job_dir = store / "jobs" / "0123456789abcdef"
    job_dir.mkdir(parents=True)
    steps = [{"id": "ingestion", "name": "Ingestion", "status": "running", "message": "",
              "started_at": None, "duration_ms": None}]
    (job_dir / "job.json").write_text(json.dumps({
        "id": "0123456789abcdef", "status": "running", "steps": steps, "error": None,
        "checkpoint_id": None, "created_at": "2026-01-01T00:00:00+00:00", "ingested_at": None,
    }), encoding="utf-8")
    manager = JobManager(store)
    try:
        view = manager.get("0123456789abcdef")
        assert view["status"] == "failed"
        assert view["error"]["code"] == "INTERRUPTED"
        assert view["steps"][0]["status"] == "failed"
        persisted = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        assert persisted["status"] == "failed"
    finally:
        manager.shutdown()


def test_queue_is_bounded(make_manager):
    gate = threading.Event()
    manager = make_manager(discover_fn=make_fake_discover(gate=gate), max_queue=2)
    accepted = 0
    code = None
    for _ in range(10):
        try:
            manager.submit(GIT)
            accepted += 1
        except IngestionError as exc:
            code = exc.code
            break
    gate.set()
    assert code == "QUEUE_FULL"
    assert 2 <= accepted <= 3  # queue of 2 plus the one the worker already took
    assert len(manager.list()) == accepted  # a refused job leaves no record


def test_list_is_newest_first_and_capped(tmp_path):
    store = tmp_path / "store"
    for index in range(MAX_LIST + 10):
        job_id = f"{index:016x}"
        job_dir = store / "jobs" / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(json.dumps({
            "id": job_id, "status": "failed", "steps": [], "error": {"code": "X", "message": "m"},
            "checkpoint_id": None, "created_at": f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
            "ingested_at": None}), encoding="utf-8")
    manager = JobManager(store)
    try:
        items = manager.list(limit=1000)
        assert len(items) == MAX_LIST
        stamps = [i["created_at"] for i in items]
        assert stamps == sorted(stamps, reverse=True)
        assert items[0]["id"] == f"{MAX_LIST + 9:016x}"
    finally:
        manager.shutdown()


def test_unknown_and_malformed_ids_return_none(make_manager):
    manager = make_manager(discover_fn=make_fake_discover())
    assert manager.get("ffffffffffffffff") is None
    for bad in ("../../etc", "GGGG", "", "0123456789ABCDEF", "short"):
        assert manager.get(bad) is None
        assert manager.status(bad) is None
        assert manager.blueprint_path(bad) is None


def test_progress_callback_ignores_unknown_steps_and_never_raises(make_manager):
    seen = []

    def discover(request, store, *, progress=None, **_):
        progress("not-a-step", "running", "x")
        progress("ingestion", "bogus-status", "x")
        progress("ingestion", "running", None)
        seen.append(True)
        raise IngestionError("stop", code="REF_AMBIGUOUS")

    manager = make_manager(discover_fn=discover)
    view = wait_for(manager, manager.submit(GIT))
    assert seen and view["error"]["code"] == "REF_AMBIGUOUS"


def test_temporary_upload_is_removed_after_the_job(make_manager, tmp_path):
    upload = tmp_path / "upload.zip"
    upload.write_bytes(b"PK\x03\x04")
    manager = make_manager(discover_fn=make_fake_discover())
    job_id = manager.submit(JobRequest(kind="zip", source=str(upload), label="a.zip"), cleanup=upload)
    wait_for(manager, job_id)
    deadline = time.monotonic() + 2
    while upload.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not upload.exists()


def test_invalid_checkpoint_id_from_discover_fails_the_job(make_manager):
    class Bad:
        checkpoint = type("C", (), {"checkpoint_id": "../../x"})()
        blueprint = {}

    manager = make_manager(discover_fn=lambda *a, **k: Bad())
    view = wait_for(manager, manager.submit(GIT))
    assert view["status"] == "failed" and view["error"]["code"] == "INTERNAL_ERROR"


def test_default_runner_imports_stage1_lazily_and_builds_a_request(make_manager, monkeypatch):
    """With no injected function the runner imports ``p1.stage1`` at run time."""

    import types

    seen = {}

    class DiscoveryRequest:
        def __init__(self, kind, source, ref, label, allow_ssh):
            seen["request"] = (kind, source, ref, label, allow_ssh)

    def discover(request, store, *, progress=None):
        raise IngestionError("refused", code="LIMIT_EXCEEDED")

    module = types.ModuleType("p1.stage1")
    module.DiscoveryRequest = DiscoveryRequest
    module.discover = discover
    monkeypatch.setitem(sys.modules, "p1.stage1", module)
    manager = make_manager()
    view = wait_for(manager, manager.submit(GIT))
    assert seen["request"] == ("git", "https://git.example.com/a/b.git", "main", None, False)
    assert view["error"]["code"] == "LIMIT_EXCEEDED"


# ------------------------------------------------------------------ M1: worker re-check


def dir_request(path) -> JobRequest:
    return JobRequest(kind="directory", source=str(path), label="proj")


def test_worker_passes_discover_the_resolved_path(make_manager, tmp_path):
    root = (tmp_path / "root").resolve()
    (root / "proj").mkdir(parents=True)
    calls: list = []
    manager = make_manager(discover_fn=make_fake_discover(calls=calls), allowed_roots=[root])
    wander = root / "proj" / ".." / "proj"
    wait_for(manager, manager.submit(dir_request(wander)))
    assert [Path(c.source) for c in calls] == [root / "proj"]
    assert ".." not in calls[0].source


def test_worker_rejects_a_path_outside_the_roots_with_a_sanitised_failure(make_manager, tmp_path):
    root = (tmp_path / "root").resolve()
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    calls: list = []
    manager = make_manager(discover_fn=make_fake_discover(calls=calls), allowed_roots=[root])
    view = wait_for(manager, manager.submit(dir_request(outside)))
    assert view["status"] == "failed" and view["error"]["code"] == "PATH_NOT_ALLOWED"
    assert calls == []
    assert str(tmp_path) not in json.dumps(view)


def test_worker_without_roots_refuses_directories(make_manager, tmp_path):
    calls: list = []
    manager = make_manager(discover_fn=make_fake_discover(calls=calls))
    view = wait_for(manager, manager.submit(dir_request(tmp_path)))
    assert view["error"]["code"] == "PATH_NOT_ALLOWED" and calls == []


def _link(link: Path, target: Path) -> bool:
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                              capture_output=True, check=False)
        return done.returncode == 0
    return False


def _unlink(link: Path) -> None:
    try:
        link.unlink()
    except (OSError, PermissionError):
        os.rmdir(link)


def test_toctou_retargeted_link_is_caught_by_the_worker(make_manager, tmp_path):
    root = (tmp_path / "root").resolve()
    (root / "a").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "link"
    if not _link(link, root / "a"):
        pytest.skip("cannot create a directory link here")
    gate = threading.Event()
    calls: list = []
    manager = make_manager(discover_fn=make_fake_discover(gate=gate, calls=calls), allowed_roots=[root])
    blocker = manager.submit(GIT)
    wait_for(manager, blocker, states=("running",))
    victim = manager.submit(dir_request(link))  # was inside the root when the API checked it
    _unlink(link)
    assert _link(link, outside)  # retargeted after the API check
    gate.set()
    view = wait_for(manager, victim)
    assert view["status"] == "failed" and view["error"]["code"] == "PATH_NOT_ALLOWED"
    assert all(c.kind != "directory" for c in calls)


# ------------------------------------------------------------------ M2: slots and pruning


def test_reserved_slot_counts_against_capacity_and_is_released(make_manager):
    gate = threading.Event()
    manager = make_manager(discover_fn=make_fake_discover(gate=gate), max_queue=1)
    manager.reserve_slot()
    with pytest.raises(IngestionError) as full:
        manager.reserve_slot()
    assert full.value.code == "QUEUE_FULL"
    manager.release_slot()
    manager.reserve_slot()  # capacity is back
    job_id = manager.submit(GIT, reserved=True)
    gate.set()
    assert wait_for(manager, job_id)["status"] == "completed"


def test_reserved_slot_is_not_double_counted_after_submit(make_manager):
    manager = make_manager(discover_fn=make_fake_discover(), max_queue=1)
    for _ in range(3):
        manager.reserve_slot()
        wait_for(manager, manager.submit(GIT, reserved=True))


def finished_stub(store: Path, index: int) -> str:
    job_id = f"{index:016x}"
    job_dir = store / "jobs" / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps({
        "id": job_id, "status": "failed", "steps": [], "error": {"code": "X", "message": "m"},
        "checkpoint_id": None, "created_at": f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
        "ingested_at": None}), encoding="utf-8")
    return job_id


def test_startup_prunes_the_oldest_job_directories_beyond_the_bound(tmp_path):
    store = tmp_path / "store"
    ids = [finished_stub(store, i) for i in range(12)]
    manager = JobManager(store, max_finished=5)
    try:
        left = sorted(p.name for p in (store / "jobs").iterdir())
        assert left == sorted(ids[-5:])
        assert len(manager.list()) == 5
        assert manager.get(ids[0]) is None
    finally:
        manager.shutdown()


def test_finished_jobs_are_bounded_after_each_job_and_active_ones_survive(make_manager, tmp_path):
    gate = threading.Event()
    manager = make_manager(discover_fn=make_fake_discover(gate=gate), max_finished=1)
    first = manager.submit(GIT)
    wait_for(manager, first, states=("running",))
    queued = [manager.submit(GIT) for _ in range(3)]
    jobs_dir = tmp_path / "store" / "jobs"
    assert {first, *queued} <= {p.name for p in jobs_dir.iterdir()}  # nothing active is pruned
    gate.set()
    wait_for(manager, queued[-1])
    deadline = time.monotonic() + 3
    while len(list(jobs_dir.iterdir())) > 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(list(jobs_dir.iterdir())) == 1
    assert len(manager.list()) == 1


# ------------------------------------------------------------------ L6: no host paths served


HOST_PATH = re.compile(r"[A-Za-z]:[\\/]")


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def assert_no_host_paths(view, *host_markers: str) -> None:
    """No drive path, ``Users`` or marker; a drive path quoted from the analysed source is fine."""

    corpus = "\n".join(c if isinstance(c, str) else c.decode("latin-1") for c in ENTERPRISE_APP.values()).lower()
    for text in _strings(view):
        for hit in HOST_PATH.finditer(text):
            assert text[hit.start():hit.start() + 8].lower() in corpus, f"host drive path leaked: {text[:80]!r}"
        assert "Users" not in text
        for marker in host_markers:
            assert marker not in text


def test_served_job_json_carries_no_host_paths_for_the_fake_discover(make_manager, tmp_path):
    manager = make_manager(discover_fn=make_fake_discover())
    view = wait_for(manager, manager.submit(GIT))
    assert_no_host_paths(view, str(tmp_path))


def test_real_discover_through_the_job_runner_serves_no_host_paths(tmp_path):
    apps = (tmp_path / "apps").resolve()
    app_dir = write_enterprise_app(apps / "erp")
    manager = JobManager(tmp_path / "store", allowed_roots=[apps])
    try:
        view = wait_for(manager, manager.submit(dir_request(app_dir)), timeout=60)
        assert view["status"] == "completed", view["error"]
        assert view["blueprint"]["project"]["checkpoint"]["id"] == view["checkpoint_id"]
        assert_no_host_paths(view, str(tmp_path), tmp_path.name)
        assert_no_host_paths(manager.list(), str(tmp_path))
        artefact = manager.blueprint_path(view["id"]) / "application-blueprint.json"
        assert_no_host_paths(json.loads(artefact.read_text(encoding="utf-8")), str(tmp_path))
    finally:
        manager.shutdown()
