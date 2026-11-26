"""FastAPI front end: same contract and security posture as the stdlib server."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "stage1"))

from fakes import make_fake_discover  # noqa: E402
from p1.errors import IngestionError  # noqa: E402
from p1.fastapi_app import ApiState, create_api  # noqa: E402
from p1.tenant_auth import TokenTable, issue_token  # noqa: E402

BASE = "http://127.0.0.1:8766"
POST = {"X-P1-Request": "1"}
JSON_POST = {**POST, "Content-Type": "application/json"}
ZIP_POST = {**POST, "Content-Type": "application/zip"}
GIT = {"kind": "git", "url": "https://git.example.com/legacy/pascal-erp.git", "ref": "main"}
ZIP = b"PK\x03\x04" + b"\x00" * 64


def make(tmp_path, **kw):
    kw.setdefault("discover_fn", make_fake_discover())
    app = create_api(tmp_path / "store", "127.0.0.1", 8766, **kw)
    return TestClient(app, base_url=BASE)


@pytest.fixture
def client(tmp_path):
    with make(tmp_path) as c:
        yield c


def wait(c, job_id, headers=None):
    for _ in range(500):
        view = c.get(f"/api/discoveries/{job_id}", headers=headers).json()
        if view["status"] in ("completed", "failed"):
            return view
        time.sleep(0.02)
    raise AssertionError("timed out")


def add_first(app, path, endpoint):
    """Register a test route ahead of the static catch-all."""
    app.router.add_api_route(path, endpoint, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())


def code_of(response):
    return response.json()["error"]["code"]


def test_config_and_security_headers(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["auth_required"] is False
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


def test_git_discovery_end_to_end_and_artifacts(client):
    r = client.post("/api/discoveries", json=GIT, headers=POST)
    assert r.status_code == 202
    view = wait(client, r.json()["id"])
    assert view["status"] == "completed" and view["blueprint"]
    jid = view["id"]
    for path in ("blueprint", "report", "artifacts/diagnostics.json",
                 "artifacts/checkpoint-manifest.json"):
        assert client.get(f"/api/discoveries/{jid}/{path}").status_code == 200
    bp = client.get(f"/api/discoveries/{jid}/blueprint")
    assert "attachment" in bp.headers["content-disposition"]
    assert client.get("/api/discoveries").json()["items"][0]["id"] == jid


@pytest.mark.parametrize("headers,code,status", [
    ({"Host": "evil.example"}, "HOST_NOT_ALLOWED", 403),
    ({"Origin": "http://evil.example"}, "ORIGIN_NOT_ALLOWED", 403),
    ({"X-P1-Request": "0"}, "CSRF_HEADER_REQUIRED", 403),
])
def test_guard_refuses_bad_posts(client, headers, code, status):
    r = client.post("/api/discoveries", json=GIT, headers={**POST, **headers})
    assert (r.status_code, code_of(r)) == (status, code)


def test_missing_csrf_header_and_host_checked_on_get(client):
    assert client.post("/api/discoveries", json=GIT).status_code == 403
    assert client.get("/api/config", headers={"Host": "evil.example"}).status_code == 403


def test_unsupported_methods_and_bad_bodies(client):
    assert client.put("/api/discoveries", headers=POST).status_code == 405
    assert client.delete("/api/discoveries", headers=POST).status_code == 405
    r = client.post("/api/discoveries", content=b"{not json", headers=JSON_POST)
    assert code_of(r) == "BAD_JSON"
    r = client.post("/api/discoveries", content=b"[]", headers=JSON_POST)
    assert code_of(r) == "BAD_JSON"
    r = client.post("/api/discoveries", content=b"x=1", headers={**POST, "Content-Type": "text/plain"})
    assert code_of(r) == "BAD_CONTENT_TYPE"
    big = json.dumps({"kind": "git", "url": "h" * 20000}).encode()
    assert client.post("/api/discoveries", content=big, headers=JSON_POST).status_code == 413
    r = client.post("/api/discoveries", json={"kind": "bogus"}, headers=POST)
    assert code_of(r) == "INVALID_KIND"


@pytest.mark.parametrize("url", ["http://127.0.0.1/a.git", "https://localhost/a.git",
                                 "file:///etc/passwd", "https://user:pw@example.com/a.git"])
def test_hostile_git_urls_are_refused(client, url):
    r = client.post("/api/discoveries", json={"kind": "git", "url": url}, headers=POST)
    assert r.status_code in (400, 403)


def test_directory_ingestion_disabled_by_default(client):
    r = client.post("/api/discoveries", json={"kind": "directory", "path": "."}, headers=POST)
    assert r.status_code == 403
    assert client.get("/api/config").json()["local_directory_enabled"] is False


def test_directory_inside_root_is_accepted_outside_refused(tmp_path):
    root = tmp_path / "root"
    (root / "app").mkdir(parents=True)
    with make(tmp_path, allow_local_roots=[root]) as c:
        ok = c.post("/api/discoveries", json={"kind": "directory", "path": str(root / "app")},
                    headers=POST)
        assert ok.status_code == 202
        bad = c.post("/api/discoveries", json={"kind": "directory", "path": str(tmp_path)},
                     headers=POST)
        assert bad.status_code in (400, 403)


@pytest.mark.parametrize("jid", ["..%2fetc", "ZZZ", "1234", "g" * 16])
def test_ids_are_validated(client, jid):
    assert client.get(f"/api/discoveries/{jid}").status_code in (400, 404)


def test_unknown_ids_artifacts_and_routes(client):
    assert client.get("/api/discoveries/" + "0" * 16).status_code == 404
    assert client.get("/api/discoveries/" + "0" * 16 + "/artifacts/passwd").status_code == 404
    assert client.get("/api/nothing").status_code == 404
    assert client.get("/nothing.js").status_code == 404


def test_upload_flow(client):
    r = client.post("/api/discoveries/upload?name=app.zip", content=ZIP, headers=ZIP_POST)
    assert r.status_code == 202
    assert wait(client, r.json()["id"])["status"] == "completed"
    assert list(client.app.state.p1.uploads_for("default").glob("*.part")) == []


@pytest.mark.parametrize("name,body,ctype,code", [
    ("app.zip", b"not a zip at all", "application/zip", "NOT_A_ZIP"),
    ("app.txt", ZIP, "application/zip", "INVALID_NAME"),
    ("app.zip", ZIP, "text/plain", "BAD_CONTENT_TYPE"),
    ("app.zip", b"", "application/zip", "EMPTY_UPLOAD"),
])
def test_bad_uploads(client, name, body, ctype, code):
    r = client.post(f"/api/discoveries/upload?name={name}", content=body,
                    headers={**POST, "Content-Type": ctype})
    assert code_of(r) == code
    assert list(client.app.state.p1.uploads_for("default").iterdir()) == []


def test_upload_size_cap_and_chunked_refusal(tmp_path):
    with make(tmp_path, max_upload_bytes=100) as c:
        r = c.post("/api/discoveries/upload?name=a.zip", content=ZIP + b"0" * 100,
                   headers=ZIP_POST)
        assert r.status_code == 413
        r = c.post("/api/discoveries/upload?name=a.zip", content=iter([ZIP]), headers=ZIP_POST)
        assert code_of(r) == "LENGTH_REQUIRED"


def test_upload_content_length_mismatch_leaves_nothing(client):
    r = client.post("/api/discoveries/upload?name=a.zip", content=ZIP,
                    headers={**ZIP_POST, "Content-Length": "10"})
    assert r.status_code >= 400
    assert list(client.app.state.p1.uploads_for("default").iterdir()) == []


def test_tenant_header_isolation(client):
    a, b = {"X-P1-Tenant": "acme"}, {"X-P1-Tenant": "globex"}
    jid = client.post("/api/discoveries", json=GIT, headers={**POST, **a}).json()["id"]
    assert wait(client, jid, a)["status"] == "completed"
    assert client.get(f"/api/discoveries/{jid}", headers=b).status_code == 404
    assert client.get(f"/api/discoveries/{jid}/blueprint", headers=b).status_code == 404
    assert client.get("/api/discoveries", headers=b).json()["items"] == []
    assert client.get("/api/discoveries", headers={"X-P1-Tenant": "../x"}).status_code == 400
    assert client.get("/api/discoveries", headers={"X-P1-Tenant": "jobs"}).status_code == 400


def test_token_mode_binds_tenant_to_token(tmp_path):
    tokens_file = tmp_path / "tokens"
    ta, tb = issue_token(tokens_file, "acme"), issue_token(tokens_file, "globex")
    text = tokens_file.read_text()
    assert text.count("\n") == 2 and ta not in text and tb not in text
    with make(tmp_path, tokens=TokenTable.load(tokens_file)) as c:
        assert c.get("/api/config").json()["auth_required"] is True
        assert c.get("/api/discoveries").status_code == 401
        assert c.get("/api/discoveries", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/api/discoveries", headers={"Authorization": f"Basic {ta}"}).status_code == 401
        auth_a = {"Authorization": f"Bearer {ta}"}
        jid = c.post("/api/discoveries", json=GIT, headers={**POST, **auth_a}).json()["id"]
        assert wait(c, jid, auth_a)["tenant"] == "acme"
        spoof = {"Authorization": f"Bearer {tb}", "X-P1-Tenant": "acme"}
        assert c.get(f"/api/discoveries/{jid}", headers=spoof).status_code == 404
        assert c.get("/api/discoveries", headers=spoof).json()["items"] == []
        assert c.post("/api/discoveries", json=GIT, headers=POST).status_code == 401


def test_token_file_validation(tmp_path):
    bad = tmp_path / "t"
    bad.write_text("acme:nothex\n")
    with pytest.raises(IngestionError, match="malformed"):
        TokenTable.load(bad)
    bad.write_text("# only comments\n")
    with pytest.raises(IngestionError):
        TokenTable.load(bad)
    with pytest.raises(IngestionError):
        TokenTable.load(tmp_path / "missing")
    with pytest.raises(IngestionError):
        issue_token(tmp_path / "x", "jobs")


def test_static_serves_ui_without_traversal(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>x</title>")
    (dist / "assets" / "a.js").write_text("1")
    (dist / "secret.env").write_text("S")
    with make(tmp_path, static_dir=dist) as c:
        assert c.get("/").headers["content-type"].startswith("text/html")
        assert c.get("/assets/a.js").status_code == 200
        assert c.get("/secret.env").status_code == 404
        assert c.get("/..%2f..%2fetc/passwd").status_code == 404
        assert c.get("/api/config").json()["ui"] == "react"


def test_legacy_ui_fallback_when_no_build(tmp_path):
    with make(tmp_path, static_dir=tmp_path / "nope") as c:
        assert c.get("/").status_code == 200
        assert c.get("/api/config").json()["ui"] == "legacy"


def test_tenant_creation_is_capped_in_open_mode(client):
    from p1.fastapi_app import MAX_TENANTS
    ok = 0
    last = None
    for i in range(MAX_TENANTS + 5):
        last = client.get("/api/discoveries", headers={"X-P1-Tenant": f"t{i}"})
        ok += last.status_code == 200
    assert ok < MAX_TENANTS + 5
    assert last.status_code == 429 and code_of(last) == "TOO_MANY_TENANTS"


def test_local_root_overlapping_the_store_is_refused(tmp_path):
    with pytest.raises(IngestionError, match="store"):
        create_api(tmp_path / "store", "127.0.0.1", 8766, allow_local_roots=[tmp_path])
    with pytest.raises(IngestionError):
        create_api(tmp_path / "store", "127.0.0.1", 8766,
                   allow_local_roots=[tmp_path / "store" / "tenants"])


def test_id_with_trailing_newline_is_invalid(client):
    assert client.get("/api/discoveries/0123456789abcdef%0A").status_code == 400


def test_second_concurrent_upload_of_one_tenant_is_refused(client):
    state = client.app.state.p1
    assert state.tenant_gate("default").try_acquire()
    try:
        r = client.post("/api/discoveries/upload?name=a.zip", content=ZIP, headers=ZIP_POST)
        assert r.status_code == 429
        assert state.gate.try_acquire()
        state.gate.release()
    finally:
        state.tenant_gate("default").release()


def test_https_origin_only_accepted_behind_a_tls_proxy(tmp_path):
    h = {**POST, "Origin": "https://127.0.0.1:8766"}
    with make(tmp_path) as c:
        assert c.post("/api/discoveries", json={"kind": "bogus"}, headers=h).status_code == 403
    with make(tmp_path / "b", behind_tls_proxy=True) as c:
        assert c.post("/api/discoveries", json={"kind": "bogus"}, headers=h).status_code == 400


def test_upload_split_across_tiny_chunks_is_accepted(client):
    r = client.post("/api/discoveries/upload?name=a.zip",
                    content=iter([ZIP[:2], ZIP[2:3], ZIP[3:]]),
                    headers={**ZIP_POST, "Content-Length": str(len(ZIP))})
    assert r.status_code == 202


def test_token_file_rejects_reserved_tenant_at_load(tmp_path):
    f = tmp_path / "t"
    f.write_text("jobs:" + "a" * 64 + "\n")
    with pytest.raises(IngestionError):
        TokenTable.load(f)


def test_error_responses_carry_security_headers(client):
    r = client.get("/api/discoveries/" + "0" * 16)
    assert r.status_code == 404
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_unhandled_exception_returns_500_with_security_headers(tmp_path):
    app = create_api(tmp_path / "store", "127.0.0.1", 8766,
                     discover_fn=make_fake_discover())

    def boom():
        raise RuntimeError("secret internal detail")

    add_first(app, "/boom", boom)

    with TestClient(app, base_url=BASE, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500 and code_of(r) == "INTERNAL_ERROR"
    assert "secret" not in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_tenant_gate_is_created_once_per_tenant(client):
    state = client.app.state.p1
    assert state.tenant_gate("acme") is state.tenant_gate("acme")
    assert state.tenant_gate("acme") is not state.tenant_gate("globex")


def test_startup_with_too_many_tenant_directories_is_a_clean_refusal(tmp_path):
    from p1.tenancy import MAX_TENANTS
    for i in range(MAX_TENANTS):
        (tmp_path / "store" / "tenants" / f"t{i}").mkdir(parents=True)
    with pytest.raises(IngestionError) as exc:
        ApiState(tmp_path / "store", "127.0.0.1", 8766)
    assert exc.value.code == "TOO_MANY_TENANTS"


def test_client_disconnect_is_not_logged_as_a_server_fault(client, caplog):
    from starlette.requests import ClientDisconnect

    def gone():
        raise ClientDisconnect()

    add_first(client.app, "/gone", gone)

    with caplog.at_level("ERROR", logger="p1.api"):
        r = client.get("/gone")
    assert r.status_code == 400 and code_of(r) == "CLIENT_DISCONNECT"
    assert not caplog.records


def test_oversized_artifact_is_refused_not_loaded(client, monkeypatch):
    import p1.fastapi_app as module
    jid = client.post("/api/discoveries", json=GIT, headers=POST).json()["id"]
    wait(client, jid)
    monkeypatch.setattr(module, "MAX_ARTIFACT_BYTES", 10)
    r = client.get(f"/api/discoveries/{jid}/blueprint")
    assert r.status_code == 413 and code_of(r) == "ARTIFACT_TOO_LARGE"
