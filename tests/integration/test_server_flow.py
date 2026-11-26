"""End-to-end dashboard flow against a real server and a fake ``discover``."""

from __future__ import annotations

import http.client
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "stage1"))

from fakes import SAMPLE_REPORT, load_sample, make_fake_discover  # noqa: E402
from p1.errors import IngestionError  # noqa: E402
from p1.server import create_app, main  # noqa: E402

WEB = Path(__file__).resolve().parents[2] / "tools" / "p1" / "web"
ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 32


class Client:
    def __init__(self, app):
        self.app = app
        self.port = app.server_address[1]
        threading.Thread(target=app.serve_forever, daemon=True).start()

    def call(self, method, path, body=None, headers=None):
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        if method == "POST":
            hdrs["X-P1-Request"] = "1"
        hdrs.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=hdrs)
            resp = conn.getresponse()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
        finally:
            conn.close()

    def post_git(self, url="https://git.example.com/legacy/pascal-erp.git", ref="main"):
        body = json.dumps({"kind": "git", "url": url, "ref": ref}).encode()
        return self.call("POST", "/api/discoveries", body, {"Content-Type": "application/json"})

    def wait(self, job_id):
        for _ in range(500):
            _, _, body = self.call("GET", f"/api/discoveries/{job_id}")
            view = json.loads(body)
            if view["status"] in ("completed", "failed"):
                return view
            time.sleep(0.02)
        raise AssertionError("timed out")


def start(tmp_path, **kwargs):
    kwargs.setdefault("discover_fn", make_fake_discover())
    return Client(create_app(tmp_path / "store", "127.0.0.1", 0, **kwargs))


@pytest.fixture()
def client(tmp_path):
    c = start(tmp_path)
    yield c
    c.app.shutdown()


def test_git_flow_completes_and_blueprint_download_equals_sample(client):
    status, _, body = client.post_git()
    assert status == 202
    accepted = json.loads(body)
    assert accepted["status"] == "queued" and len(accepted["id"]) == 16

    view = client.wait(accepted["id"])
    assert view["status"] == "completed" and view["error"] is None
    assert view["blueprint"] == load_sample()
    assert view["checkpoint_id"] == load_sample()["project"]["checkpoint"]["id"]
    assert [s["status"] for s in view["steps"]][0] == "completed"

    status, headers, body = client.call("GET", f"/api/discoveries/{accepted['id']}/blueprint")
    assert status == 200 and headers["content-type"].startswith("application/json")
    assert headers["content-disposition"].startswith("attachment")
    assert json.loads(body) == load_sample()


def test_report_is_plain_text_and_not_an_attachment(client):
    job_id = json.loads(client.post_git()[2])["id"]
    client.wait(job_id)
    status, headers, body = client.call("GET", f"/api/discoveries/{job_id}/report")
    assert status == 200
    assert headers["content-type"] == "text/plain; charset=utf-8"
    assert "content-disposition" not in headers
    assert body.decode() == SAMPLE_REPORT


def test_artifacts_download_with_correct_types(client):
    job_id = json.loads(client.post_git()[2])["id"]
    client.wait(job_id)
    status, headers, body = client.call("GET", f"/api/discoveries/{job_id}/artifacts/unresolved-dependencies.json")
    assert status == 200 and json.loads(body)["count"] == len(load_sample()["unresolved"])
    status, headers, body = client.call("GET", f"/api/discoveries/{job_id}/artifacts/inventory.csv")
    assert headers["content-type"].startswith("text/csv") and body.startswith(b"path,class")
    status, _, body = client.call("GET", f"/api/discoveries/{job_id}/artifacts/diagnostics.json")
    assert json.loads(body)["schema_version"] == "stage1.diagnostics/1.0"


def test_zip_upload_flow(client):
    status, _, body = client.call("POST", "/api/discoveries/upload?name=erp.zip", ZIP_BYTES,
                                  {"Content-Type": "application/zip"})
    assert status == 202
    view = client.wait(json.loads(body)["id"])
    assert view["status"] == "completed" and view["kind"] == "zip" and view["label"] == "erp.zip"


def test_failed_discover_is_a_sanitised_failure(tmp_path):
    err = IngestionError(r"clone failed in C:\Users\me\AppData\x with token=sekret123", code="COMMIT_MOVED")
    c = start(tmp_path, discover_fn=make_fake_discover(error=err))
    try:
        view = c.wait(json.loads(c.post_git()[2])["id"])
        assert view["status"] == "failed"
        assert view["error"]["code"] == "COMMIT_MOVED"
        assert "sekret123" not in json.dumps(view) and "AppData" not in json.dumps(view)
        assert view["blueprint"] is None
        status, _, body = c.call("GET", f"/api/discoveries/{view['id']}/blueprint")
        assert status == 409
    finally:
        c.app.shutdown()


def test_recent_discoveries_lists_newest_first_with_summary(client):
    ids = []
    for _ in range(3):
        ids.append(json.loads(client.post_git()[2])["id"])
        client.wait(ids[-1])
        time.sleep(1.1)  # created_at has one-second resolution
    status, _, body = client.call("GET", "/api/discoveries")
    items = json.loads(body)["items"]
    assert status == 200 and [i["id"] for i in items] == list(reversed(ids))
    assert items[0]["summary"]["project"] == "legacy-pascal-erp"
    assert "blueprint" not in items[0]


def test_config_endpoint_shape(client):
    status, _, body = client.call("GET", "/api/config")
    cfg = json.loads(body)
    assert status == 200
    assert cfg["stage"] == 1 and cfg["local_directory_enabled"] is False and cfg["ssh_enabled"] is False
    assert cfg["max_upload_bytes"] == 512 * 1024 * 1024


@pytest.mark.parametrize("path,ctype,needle", [
    ("/", "text/html; charset=utf-8", b"<!doctype html>"),
    ("/index.html", "text/html; charset=utf-8", b"<!doctype html>"),
    ("/app.css", "text/css; charset=utf-8", b"{"),
    ("/app.js", "text/javascript; charset=utf-8", b"function"),
])
def test_static_files_have_correct_types_and_csp(client, path, ctype, needle):
    status, headers, body = client.call("GET", path)
    assert status == 200
    assert headers["content-type"] == ctype
    assert needle in body.lower()
    assert body == (WEB / ("index.html" if path in ("/", "/index.html") else path[1:])).read_bytes()
    assert headers["content-security-policy"].startswith("default-src 'self'")
    assert headers["x-content-type-options"] == "nosniff"


def test_main_refuses_non_loopback_bind_without_flag(tmp_path):
    assert main(["--store", str(tmp_path), "--host", "0.0.0.0", "--port", "0"]) == 2
    assert main(["--store", str(tmp_path), "--allow-local-root", str(tmp_path / "missing")]) == 2


def test_served_job_and_blueprint_json_carry_no_host_or_store_paths(client):
    import re
    _, _, body = client.post_git()
    job_id = json.loads(body)["id"]
    client.wait(job_id)
    store = str(client.app.store)
    for path in (f"/api/discoveries/{job_id}", f"/api/discoveries/{job_id}/blueprint", "/api/discoveries"):
        status, _, data = client.call("GET", path)
        text = data.decode("utf-8")
        assert status == 200
        assert store not in text and store.replace("\\", "\\\\") not in text
        assert "Users" not in text
        for hit in re.finditer(r"[A-Za-z]:\\\\", text):  # only the analysed source's own C:\ path may appear
            assert text[hit.start():hit.start() + 9].lower() == "c:" + chr(92) * 2 + "erp" + chr(92) * 2
