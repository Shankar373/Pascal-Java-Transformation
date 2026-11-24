"""Tenant isolation at the API and storage boundary.

Stage 1 has no authentication until Stage 6, so the tenant is supplied by
the caller in ``X-P1-Tenant``.  These tests prove the isolation guarantee
that already holds *without* authentication: one tenant's jobs, uploads,
checkpoints, discoveries and artefacts are never visible to another tenant,
and a hostile tenant id never reaches the filesystem.
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "stage1"))

from fakes import make_fake_discover  # noqa: E402
from p1.server import create_app  # noqa: E402

SMALL_CAP = 4096
ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 64
A = {"X-P1-Tenant": "acme"}
B = {"X-P1-Tenant": "globex"}


class Server:
    def __init__(self, app):
        self.app = app
        self.port = app.server_address[1]
        self.thread = threading.Thread(target=app.serve_forever, daemon=True)
        self.thread.start()

    def request(self, method, path, body=None, headers=None, post_headers=True):
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        if method == "POST" and post_headers:
            hdrs["X-P1-Request"] = "1"
        hdrs.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def post_json(self, payload, headers=None):
        return self.request("POST", "/api/discoveries",
                            json.dumps(payload).encode(),
                            {"Content-Type": "application/json",
                             **(headers or {})})

    def upload(self, data, headers=None):
        return self.request(
            "POST", "/api/discoveries/upload?name=app.zip", data,
            {"Content-Type": "application/zip", **(headers or {})})

    def wait(self, job_id, headers=None, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, _, body = self.request(
                "GET", f"/api/discoveries/{job_id}", headers=headers)
            if status == 200:
                view = json.loads(body)
                if view["status"] in ("completed", "failed"):
                    return view
            time.sleep(0.05)
        raise AssertionError("job did not finish in time")


@pytest.fixture()
def server(tmp_path):
    app = create_app(tmp_path / "store", "127.0.0.1", 0,
                     max_upload_bytes=SMALL_CAP,
                     discover_fn=make_fake_discover())
    srv = Server(app)
    yield srv
    app.shutdown()


def error_of(data: bytes) -> dict:
    return json.loads(data)["error"]


# ------------------------------------------------------------- submission


def test_default_tenant_is_used_without_a_header(server) -> None:
    status, _, body = server.post_json({"kind": "git",
                                        "url": "https://example.com/a.git"})
    assert status == 202
    assert json.loads(body)["tenant"] == "default"


def test_job_is_stored_under_the_tenant_directory(server, tmp_path) -> None:
    status, _, body = server.post_json(
        {"kind": "git", "url": "https://example.com/a.git"}, headers=A)
    assert status == 202
    job_id = json.loads(body)["id"]
    assert (tmp_path / "store" / "tenants" / "acme" / "jobs" / job_id
            / "job.json").is_file()
    assert not (tmp_path / "store" / "jobs" / job_id).exists()


# ------------------------------------------------------------- visibility


def test_a_job_is_invisible_to_another_tenant(server) -> None:
    _, _, body = server.post_json(
        {"kind": "git", "url": "https://example.com/a.git"}, headers=A)
    job_id = json.loads(body)["id"]

    status, _, other = server.request(
        "GET", f"/api/discoveries/{job_id}", headers=B)
    assert status == 404
    assert error_of(other)["code"] == "NOT_FOUND"

    status, _, listing = server.request("GET", "/api/discoveries", headers=B)
    assert status == 200
    assert json.loads(listing)["items"] == []


def test_listing_is_scoped_to_the_calling_tenant(server) -> None:
    for headers in (A, B, A):
        server.post_json({"kind": "git", "url": "https://example.com/a.git"},
                         headers=headers)
    _, _, body_a = server.request("GET", "/api/discoveries", headers=A)
    _, _, body_b = server.request("GET", "/api/discoveries", headers=B)
    _, _, body_d = server.request("GET", "/api/discoveries")
    assert len(json.loads(body_a)["items"]) == 2
    assert len(json.loads(body_b)["items"]) == 1
    assert json.loads(body_d)["items"] == []


def test_artifacts_of_one_tenant_are_not_downloadable_by_another(server) -> None:
    _, _, body = server.post_json(
        {"kind": "git", "url": "https://example.com/a.git"}, headers=A)
    job_id = json.loads(body)["id"]
    view = server.wait(job_id, headers=A)
    assert view["status"] == "completed"

    for path in (f"/api/discoveries/{job_id}/blueprint",
                 f"/api/discoveries/{job_id}/report",
                 f"/api/discoveries/{job_id}/artifacts/checkpoint-manifest.json"):
        status, _, data = server.request("GET", path, headers=A)
        assert status == 200, path
        status, _, data = server.request("GET", path, headers=B)
        assert status == 404, path
        assert error_of(data)["code"] == "NOT_FOUND"
        status, _, data = server.request("GET", path)
        assert status == 404, path


def test_completed_discovery_is_isolated_on_disk(server, tmp_path) -> None:
    _, _, body = server.post_json(
        {"kind": "git", "url": "https://example.com/a.git"}, headers=A)
    job_id = json.loads(body)["id"]
    server.wait(job_id, headers=A)
    store = tmp_path / "store"
    assert (store / "tenants" / "acme" / "discoveries").is_dir()
    assert not (store / "discoveries").exists()


# --------------------------------------------------------- hostile tenant ids


@pytest.mark.parametrize("tenant", ["../evil", "a/b", "ACME", "", "..",
                                    "x" * 80, "a b", "jobs"])
def test_hostile_tenant_header_is_refused(server, tenant) -> None:
    status, _, body = server.request("GET", "/api/discoveries",
                                     headers={"X-P1-Tenant": tenant})
    assert status == 400
    assert error_of(body)["code"] == "INVALID_TENANT"


def test_hostile_tenant_on_post_is_refused_before_a_job_exists(
        server, tmp_path) -> None:
    status, _, body = server.post_json(
        {"kind": "git", "url": "https://example.com/a.git"},
        headers={"X-P1-Tenant": "../../escape"})
    assert status == 400
    assert error_of(body)["code"] == "INVALID_TENANT"
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path / "store" / "tenants").exists()


# ------------------------------------------------------------------ uploads


def test_upload_lands_in_the_tenant_upload_directory(server, tmp_path) -> None:
    status, _, body = server.upload(ZIP_BYTES, headers=A)
    assert status == 202
    job_id = json.loads(body)["id"]
    uploads = tmp_path / "store" / "tenants" / "acme" / "uploads"
    # the temp archive is consumed (and removed) by the job, but the tenant
    # upload directory itself is the one that was used
    assert uploads.is_dir()
    assert not (tmp_path / "store" / "uploads" / "app.zip").exists()
    server.wait(job_id, headers=A)


def test_upload_with_a_hostile_tenant_is_refused(server) -> None:
    status, _, body = server.upload(ZIP_BYTES,
                                    headers={"X-P1-Tenant": "../nope"})
    assert status == 400
    assert error_of(body)["code"] == "INVALID_TENANT"


# ------------------------------------------------------- restart isolation


def test_tenant_jobs_survive_a_restart_in_their_own_directory(tmp_path) -> None:
    from p1.jobs import JobManager

    manager = JobManager(tmp_path, tenant="acme")
    manager.submit.__self__  # noqa: B018 - documents the bound method
    job_id = manager.submit(
        __import__("p1.jobs", fromlist=["JobRequest"]).JobRequest(
            kind="git", source="https://example.com/a.git"))
    manager.shutdown()

    reopened = JobManager(tmp_path, tenant="acme")
    assert reopened.status(job_id) is not None
    other = JobManager(tmp_path, tenant="globex")
    assert other.status(job_id) is None
    reopened.shutdown()
    other.shutdown()


def test_config_reports_tenancy(server) -> None:
    status, _, body = server.request("GET", "/api/config")
    assert status == 200
    assert json.loads(body)["tenancy"] is True
