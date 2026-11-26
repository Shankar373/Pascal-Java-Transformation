"""Dashboard server security: a real server on an ephemeral loopback port."""

from __future__ import annotations

import http.client
import json
import os
import re
import select
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures" / "stage1"))

from fakes import make_fake_discover  # noqa: E402
from p1.server import create_app  # noqa: E402
from p1.server_security import (  # noqa: E402
    resolve_local_directory, safe_upload_name, scrub_message, validate_git_request, RequestRejected,
)

SMALL_CAP = 4096
ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 64
HEADERS_REQUIRED = ("content-security-policy", "x-content-type-options", "referrer-policy")


class Server:
    def __init__(self, app):
        self.app = app
        self.port = app.server_address[1]
        self.thread = threading.Thread(target=app.serve_forever, daemon=True)
        self.thread.start()

    def request(self, method, path, body=None, headers=None, host=None, post_headers=True):
        hdrs = {"Host": host or f"127.0.0.1:{self.port}"}
        if method == "POST" and post_headers:
            hdrs["X-P1-Request"] = "1"
        hdrs.update(headers or {})
        hdrs = {k: v for k, v in hdrs.items() if v is not None}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def post_json(self, payload, path="/api/discoveries", **kw):
        headers = {"Content-Type": "application/json"}
        headers.update(kw.pop("headers", {}))
        return self.request("POST", path, json.dumps(payload).encode(), headers, **kw)

    def upload(self, name, data, **kw):
        headers = {"Content-Type": "application/zip"}
        headers.update(kw.pop("headers", {}))
        return self.request("POST", f"/api/discoveries/upload?name={name}", data, headers, **kw)


def build(tmp_path, **kwargs):
    kwargs.setdefault("discover_fn", make_fake_discover())
    app = create_app(tmp_path / "store", "127.0.0.1", 0, max_upload_bytes=SMALL_CAP, **kwargs)
    return Server(app)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    srv = build(tmp_path_factory.mktemp("srv"))
    yield srv
    srv.app.shutdown()


def error_of(data: bytes) -> dict:
    return json.loads(data)["error"]


def uploads_left(srv: Server) -> list[str]:
    return sorted(p.name for p in (srv.app.store / "uploads").iterdir())


# ---------------------------------------------------------------- headers / hosts


def test_security_headers_on_every_kind_of_response(server):
    for path in ("/", "/app.css", "/app.js", "/api/config", "/nope", "/api/discoveries/zzz"):
        _, headers, _ = server.request("GET", path)
        for name in HEADERS_REQUIRED:
            assert name in headers, (path, name)
        assert headers["content-security-policy"].startswith("default-src 'self'")
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:80", "127.0.0.1",
                                  "127.0.0.1:1", "", "localhost.evil.com:%d"])
def test_host_header_rebinding_is_rejected(server, host):
    host = host.replace("%d", str(server.port))
    status, _, body = server.request("GET", "/api/config", host=host or "x:0")
    assert status == 403 and error_of(body)["code"] == "HOST_NOT_ALLOWED"


def test_host_header_missing_is_rejected(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.putrequest("GET", "/api/config", skip_host=True)
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 403
    conn.close()


def test_localhost_alias_with_the_right_port_is_accepted(server):
    status, _, _ = server.request("GET", "/api/config", host=f"localhost:{server.port}")
    assert status == 200


# ---------------------------------------------------------------- POST protections


def test_cross_origin_post_is_rejected(server):
    for origin in ("http://evil.example.com", "null", "https://127.0.0.1:%d" % server.port):
        status, _, body = server.post_json({"kind": "git", "url": "https://git.example.com/a.git"},
                                           headers={"Origin": origin})
        assert status == 403 and error_of(body)["code"] == "ORIGIN_NOT_ALLOWED", origin


def test_same_origin_post_is_accepted(server):
    status, _, _ = server.post_json({"kind": "git", "url": "https://git.example.com/a.git"},
                                    headers={"Origin": f"http://127.0.0.1:{server.port}"})
    assert status == 202


def test_missing_custom_header_is_rejected(server):
    status, _, body = server.post_json({"kind": "git", "url": "https://git.example.com/a.git"},
                                       post_headers=False)
    assert status == 403 and error_of(body)["code"] == "CSRF_HEADER_REQUIRED"
    status, _, _ = server.upload("a.zip", ZIP_BYTES, post_headers=False)
    assert status == 403


def test_wrong_custom_header_value_is_rejected(server):
    status, _, _ = server.post_json({"kind": "git", "url": "https://git.example.com/a.git"},
                                    headers={"X-P1-Request": "0"})
    assert status == 403


# ---------------------------------------------------------------- ids and paths


@pytest.mark.parametrize("bad", ["../", "..", "%2e%2e", "%2e%2e%2f", "..%5c", "%5c..", "0123456789ABCDEF",
                                 "0123456789abcde", "0123456789abcdef0", "..%2f..%2fetc%2fpasswd",
                                 "0123456789abcdef%00", "a" * 300])
def test_malformed_ids_and_traversal_are_rejected(server, bad):
    for suffix in ("", "/blueprint", "/report", "/artifacts/inventory.csv"):
        status, _, body = server.request("GET", f"/api/discoveries/{bad}{suffix}")
        assert status in (400, 404), (bad, suffix, status)
        assert "error" in json.loads(body)


def test_valid_but_unknown_id_is_404(server):
    status, _, body = server.request("GET", "/api/discoveries/0123456789abcdef")
    assert status == 404 and error_of(body)["code"] == "NOT_FOUND"


@pytest.mark.parametrize("path", ["/../tools/p1/server.py", "/%2e%2e/tools/p1/server.py", "/web/", "/web/app.js",
                                  "/index.html/../server.py", "/p1/server.py", "//etc/passwd",
                                  "/..\\server.py", "/app.js/", "/static/../app.js", "/jobs/", "/.git/config"])
def test_static_is_an_allow_list_no_traversal_no_listing(server, path):
    status, headers, body = server.request("GET", path)
    assert status in (400, 404)
    assert b"def " not in body and b"Index of" not in body


def test_artifact_allow_list_and_completion(server):
    status, _, body = server.post_json({"kind": "git", "url": "https://git.example.com/a.git"})
    job_id = json.loads(body)["id"]
    wait_completed(server, job_id)
    for name in ("application-blueprint.json", "unresolved-dependencies.json", "diagnostics.json",
                 "inventory.csv", "discovery-report.md"):
        status, headers, _ = server.request("GET", f"/api/discoveries/{job_id}/artifacts/{name}")
        assert status == 200, name
    for name in ("job.json", "../job.json", "checkpoint.json", "run-record.json", "..%2fjob.json",
                 "inventory.csv/", "INVENTORY.CSV", "unknown.txt"):
        status, _, _ = server.request("GET", f"/api/discoveries/{job_id}/artifacts/{name}")
        assert status == 404, name


def wait_completed(server, job_id):
    import time
    for _ in range(300):
        _, _, body = server.request("GET", f"/api/discoveries/{job_id}")
        if json.loads(body)["status"] in ("completed", "failed"):
            return json.loads(body)
        time.sleep(0.02)
    raise AssertionError("job did not finish")


# ---------------------------------------------------------------- bodies and uploads


def test_oversize_upload_is_413_and_leaves_no_file(server):
    status, _, body = server.upload("big.zip", ZIP_BYTES + b"\x00" * (SMALL_CAP + 10))
    assert status == 413 and error_of(body)["code"] == "UPLOAD_TOO_LARGE"
    assert uploads_left(server) == []


def test_upload_that_ends_early_leaves_no_partial_file(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.putrequest("POST", "/api/discoveries/upload?name=a.zip", skip_host=True)
    for key, value in {"Host": f"127.0.0.1:{server.port}", "X-P1-Request": "1",
                       "Content-Type": "application/zip", "Content-Length": "2000"}.items():
        conn.putheader(key, value)
    conn.endheaders()
    conn.send(ZIP_BYTES)
    conn.sock.shutdown(1)
    resp = conn.getresponse()
    assert resp.status == 400
    conn.close()
    assert uploads_left(server) == []


def test_non_zip_payload_is_rejected_and_removed(server):
    status, _, body = server.upload("a.zip", b"this is not a zip archive at all")
    assert status == 400 and error_of(body)["code"] == "NOT_A_ZIP"
    assert uploads_left(server) == []


@pytest.mark.parametrize("name", ["evil.exe", "a.zip.exe", "noext", ".zip", "", "a.zip%00.exe", "x.ZIPX"])
def test_non_zip_names_are_rejected(server, name):
    status, _, body = server.upload(name, ZIP_BYTES)
    assert status == 400 and error_of(body)["code"] == "INVALID_NAME"
    assert uploads_left(server) == []


def test_upload_name_is_reduced_to_a_safe_basename():
    assert safe_upload_name("..\\..\\win dows\\My App (v2).ZIP") == "My_App__v2_.ZIP"
    assert safe_upload_name("../../etc/passwd.zip") == "passwd.zip"
    assert "/" not in safe_upload_name("a/b/c.zip") and "\\" not in safe_upload_name("a\\b.zip")
    assert len(safe_upload_name("x" * 300 + ".zip")) <= 100


def test_good_upload_is_accepted_and_temp_file_is_cleaned_after_the_job(server):
    import time
    status, _, body = server.upload("../../app.zip", ZIP_BYTES)
    assert status == 202
    job_id = json.loads(body)["id"]
    view = wait_completed(server, job_id)
    assert view["status"] == "completed"
    assert view["label"] == "app.zip"
    for _ in range(100):
        if not uploads_left(server):
            break
        time.sleep(0.02)
    assert uploads_left(server) == []


def test_oversize_json_body_and_bad_json(server):
    status, _, body = server.request("POST", "/api/discoveries", b"{" + b" " * 40000 + b"}",
                                     {"Content-Type": "application/json"})
    assert status == 413
    for payload in (b"not json", b"[1,2]", b'"x"'):
        status, _, body = server.request("POST", "/api/discoveries", payload,
                                         {"Content-Type": "application/json"})
        assert status == 400 and error_of(body)["code"] == "BAD_JSON"
    status, _, _ = server.request("POST", "/api/discoveries", b"{}", {"Content-Type": "text/plain"})
    assert status == 400


def test_missing_content_length_is_refused(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.putrequest("POST", "/api/discoveries", skip_host=True)
    for key, value in {"Host": f"127.0.0.1:{server.port}", "X-P1-Request": "1",
                       "Content-Type": "application/json"}.items():
        conn.putheader(key, value)
    conn.endheaders()
    assert conn.getresponse().status == 411
    conn.close()


# ---------------------------------------------------------------- git / ssh / local directory


@pytest.mark.parametrize("url", ["http://git.example.com/a.git", "file:///etc/passwd", "/etc/passwd",
                                 "C:\\repos\\x", "git://git.example.com/a.git", "ext::sh -c id",
                                 "--upload-pack=evil", "", "https://x/\nHost: y", "ftp://x/y"])
def test_git_kind_only_accepts_remote_https(server, url):
    status, _, body = server.post_json({"kind": "git", "url": url})
    assert status == 400, url
    assert error_of(body)["code"] in ("INVALID_URL", "UNSUPPORTED_URL", "UNSUPPORTED_SCHEME", "INVALID_REMOTE_URL")


def test_ssh_is_disabled_unless_enabled(tmp_path, server):
    for url in ("ssh://git@git.example.com/a.git", "git@git.example.com:a/b.git"):
        status, _, body = server.post_json({"kind": "git", "url": url})
        assert status == 403 and error_of(body)["code"] == "SSH_DISABLED"
    enabled = build(tmp_path / "ssh", allow_ssh=True)
    try:
        status, _, _ = enabled.post_json({"kind": "git", "url": "ssh://git@git.example.com/a.git"})
        assert status == 202
        _, _, cfg = enabled.request("GET", "/api/config")
        assert json.loads(cfg)["ssh_enabled"] is True
    finally:
        enabled.app.shutdown()


@pytest.mark.parametrize("ref", ["-x", "a b", "a;b", "$(id)", "x" * 300, 5, ["a"]])
def test_bad_refs_are_rejected(server, ref):
    status, _, body = server.post_json({"kind": "git", "url": "https://git.example.com/a.git", "ref": ref})
    assert status == 400 and error_of(body)["code"] == "INVALID_REF"


def test_git_credentials_in_url_are_refused_and_never_echoed_or_stored(server):
    url = "https://user:s3cr3tpassw0rd@git.example.com/a.git"
    before = {p.name for p in (server.app.store / "jobs").iterdir()}
    status, _, body = server.post_json({"kind": "git", "url": url})
    assert status == 400 and error_of(body)["code"] == "CREDENTIALS_IN_URL"
    assert "s3cr3t" not in body.decode()
    assert {p.name for p in (server.app.store / "jobs").iterdir()} == before


def test_local_directory_is_disabled_by_default(server, tmp_path):
    _, _, cfg = server.request("GET", "/api/config")
    assert json.loads(cfg)["local_directory_enabled"] is False
    status, _, body = server.post_json({"kind": "directory", "path": str(tmp_path)})
    assert status == 403 and error_of(body)["code"] == "LOCAL_DIRECTORY_DISABLED"


def make_link(link: Path, target: Path) -> bool:
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, check=False)
        return result.returncode == 0
    return False


def test_local_directory_inside_root_is_accepted_and_escapes_are_rejected(tmp_path):
    root = tmp_path / "root"
    (root / "proj").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    srv = build(tmp_path / "srv", allow_local_roots=[root])
    try:
        _, _, cfg = srv.request("GET", "/api/config")
        assert json.loads(cfg)["local_directory_enabled"] is True
        status, _, _ = srv.post_json({"kind": "directory", "path": str(root / "proj")})
        assert status == 202
        cases = [str(outside), str(root / ".." / "outside"), str(root / "proj" / ".." / ".." / "outside"),
                 str(tmp_path), str(root / "missing"), "", "x\x00y"]
        for path in cases:
            status, _, body = srv.post_json({"kind": "directory", "path": path})
            assert status in (400, 403), path
            assert str(tmp_path) not in error_of(body)["message"]
        link = root / "escape"
        if make_link(link, outside):
            status, _, body = srv.post_json({"kind": "directory", "path": str(link)})
            assert status == 403 and error_of(body)["code"] == "PATH_NOT_ALLOWED"
    finally:
        srv.app.shutdown()


def test_resolve_local_directory_unit(tmp_path):
    root = (tmp_path / "r").resolve()
    root.mkdir()
    assert resolve_local_directory(str(root), [root]) == root
    with pytest.raises(RequestRejected):
        resolve_local_directory(str(root), [])
    with pytest.raises(RequestRejected):
        resolve_local_directory(123, [root])


def test_validate_git_request_unit():
    assert validate_git_request("https://h.example/a.git", "main", False) == ("https://h.example/a.git", "main")
    assert validate_git_request("https://h.example/a.git", "", False)[1] is None


# ---------------------------------------------------------------- methods / errors


def test_unknown_paths_404_and_methods_405(server):
    assert server.request("GET", "/nope")[0] == 404
    assert server.request("GET", "/api/nope")[0] == 404
    assert server.request("POST", "/api/config", b"{}", {"Content-Type": "application/json"})[0] == 405
    assert server.request("POST", "/", b"{}", {"Content-Type": "application/json"})[0] == 405
    assert server.request("POST", "/app.js", b"{}", {"Content-Type": "application/json"})[0] == 405
    for method in ("PUT", "DELETE", "PATCH"):
        status, headers, body = server.request(method, "/api/discoveries")
        assert status == 405 and error_of(body)["code"] == "METHOD_NOT_ALLOWED"
    status, _, _ = server.request("POST", "/api/discoveries/0123456789abcdef", b"{}",
                                  {"Content-Type": "application/json"})
    assert status == 405
    status, _, _ = server.request("PUT", "/api/discoveries", host="evil.com")
    assert status == 403


def test_head_and_options_are_safe(server):
    status, headers, body = server.request("HEAD", "/api/config")
    assert status == 200 and body == b"" and "content-security-policy" in headers
    status, headers, body = server.request("OPTIONS", "/api/discoveries")
    assert status == 204 and body == b""
    assert "access-control-allow-origin" not in headers
    assert server.request("OPTIONS", "/api/discoveries", host="evil.com")[0] == 403
    assert server.request("HEAD", "/nope")[0] == 404


def test_error_bodies_never_contain_paths_or_tokens(server, tmp_path):
    probes = [
        server.request("GET", "/nope"),
        server.request("GET", "/api/discoveries/xyz"),
        server.post_json({"kind": "git", "url": "file:///C:/Windows/win.ini"}),
        server.post_json({"kind": "directory", "path": str(tmp_path)}),
        server.upload("x.exe", ZIP_BYTES),
        server.request("POST", "/api/discoveries", b"{bad", {"Content-Type": "application/json"}),
    ]
    for status, _, body in probes:
        text = body.decode("utf-8")
        assert status >= 400
        assert "Traceback" not in text
        assert not re.search(r"[A-Za-z]:\\\\|/home/|/Users/|Windows", text), text
        assert str(tmp_path) not in text and "win.ini" not in text


def test_malformed_http_gets_json_error_not_html(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.sock = None
    conn.connect()
    conn.sock.sendall(b"GARBAGE\r\n\r\n")
    data = conn.sock.recv(4096).decode("latin-1")
    conn.close()
    assert "<html" not in data.lower()


def test_failed_job_error_is_sanitised_through_the_api(tmp_path):
    from p1.errors import IngestionError
    err = IngestionError(r"bad archive C:\Users\victim\x.zip ghp_abcdefghijklmnopqrstuvwxyz0123456789", code="UNSAFE_PATH")
    srv = build(tmp_path, discover_fn=make_fake_discover(error=err))
    try:
        _, _, body = srv.post_json({"kind": "git", "url": "https://git.example.com/a.git"})
        view = wait_completed(srv, json.loads(body)["id"])
        assert view["status"] == "failed" and view["error"]["code"] == "UNSAFE_PATH"
        assert "victim" not in json.dumps(view) and "ghp_" not in json.dumps(view)
    finally:
        srv.app.shutdown()


def test_queue_full_is_429(tmp_path):
    gate = threading.Event()
    srv = build(tmp_path, discover_fn=make_fake_discover(gate=gate), max_queue=1)
    try:
        statuses = [srv.post_json({"kind": "git", "url": "https://git.example.com/a.git"})[0] for _ in range(5)]
        gate.set()
        assert 429 in statuses and statuses[0] == 202
    finally:
        gate.set()
        srv.app.shutdown()


def test_scrub_message_unit():
    text = scrub_message("open /var/lib/data/x failed; https://u:pw@host/r token: abc; C:\\a\\b.txt")
    assert "/var/lib" not in text and "pw@" not in text and "abc" not in text and "C:\\a" not in text


# ---------------------------------------------------------------- M3: git gate parity with p1.remotegit


REJECTED_GIT = [
    ("https://u:p@git.example.com/a.git", "CREDENTIALS_IN_URL"),
    ("https://localhost/a.git", "HOST_NOT_PUBLIC"),
    ("https://LOCALHOST/a.git", "HOST_NOT_PUBLIC"),
    ("https://foo.localhost/a.git", "HOST_NOT_PUBLIC"),
    ("https://127.0.0.1/a.git", "HOST_NOT_PUBLIC"),
    ("https://10.1.2.3/a.git", "HOST_NOT_PUBLIC"),
    ("https://169.254.169.254/latest", "HOST_NOT_PUBLIC"),
    ("https://[::1]/a.git", "HOST_NOT_PUBLIC"),
    ("https://[::ffff:127.0.0.1]/a.git", "HOST_NOT_PUBLIC"),
    ("https:///etc/passwd", "INVALID_REMOTE_URL"),
    ("https://h_x.example.com/a.git", "INVALID_REMOTE_URL"),
]


@pytest.mark.parametrize("url,code", REJECTED_GIT)
def test_git_url_policy_matches_remotegit_at_the_api(server, url, code):
    status, _, body = server.post_json({"kind": "git", "url": url})
    assert status == 400, url
    assert error_of(body)["code"] == code
    assert "passw" not in body.decode() and "u:p@" not in body.decode()


@pytest.mark.parametrize("ref", ["a..b", "a/", "x.lock", "a//b", ".hidden", "a/.b", "@", "a.", "/a"])
def test_git_ref_policy_matches_remotegit_at_the_api(server, ref):
    status, _, body = server.post_json({"kind": "git", "url": "https://git.example.com/a.git", "ref": ref})
    assert status == 400 and error_of(body)["code"] == "INVALID_REF", ref


ACCEPTED_HTTPS = [
    "https://git.example.com/a/b.git",
    "HTTPS://Git.Example.COM/a/b.git",
    "hTtPs://git.example.com:8443/a",
    "https://git-1.my.example.org/x",
    "https://8.8.8.8/a.git",
    "https://[2606:4700:4700::1111]/a.git",
]
ACCEPTED_SSH = [
    "ssh://git@git.example.com/a.git",
    "SSH://git@git.example.com/a.git",
    "ssh://git@[2606:4700:4700::1111]/a.git",
    "git@git.example.com:a/b.git",
    "a_b@host.com:x/y",
]
DIVERGENT_SCP = ["a@b_c:x", "git@[2606:4700:4700::1111]:a/b.git", "git@[::1]:a"]


@pytest.mark.parametrize("url", ACCEPTED_HTTPS + ACCEPTED_SSH)
def test_every_url_the_api_accepts_is_remote_to_the_orchestrator(url):
    from p1.stage1 import is_remote_git
    accepted, _ = validate_git_request(url, None, True)
    assert accepted == url
    assert is_remote_git(url) is True


@pytest.mark.parametrize("url", DIVERGENT_SCP)
def test_scp_forms_the_orchestrator_would_treat_as_local_are_refused(url):
    with pytest.raises(RequestRejected) as raised:
        validate_git_request(url, None, True)
    assert raised.value.status == 400


@pytest.mark.parametrize("url", ACCEPTED_SSH)
def test_ssh_forms_stay_disabled_by_default(url):
    with pytest.raises(RequestRejected) as raised:
        validate_git_request(url, None, False)
    assert raised.value.status == 403 and raised.value.code == "SSH_DISABLED"


def test_git_gate_performs_no_network_access(monkeypatch):
    import socket

    def boom(*_a, **_k):
        raise AssertionError("network access in the API layer")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "gethostbyname", boom)
    assert validate_git_request("https://git.example.com/a.git", "main", False)[1] == "main"
    with pytest.raises(RequestRejected):
        validate_git_request("https://localhost/a", None, False)


# ---------------------------------------------------------------- L2 / L3 / L4


def raw_exchange(port, head: bytes) -> tuple[int, list[tuple[str, str]], bytes]:
    import socket
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(head)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    raw = b"".join(chunks)
    head_bytes, _, body = raw.partition(b"\r\n\r\n")
    lines = head_bytes.decode("latin-1").split("\r\n")
    headers = [tuple(line.split(": ", 1)) for line in lines[1:]]
    return int(lines[0].split()[1]), headers, body


def test_static_files_carry_exactly_one_cache_control_header(server):
    for path in ("/", "/app.css", "/app.js", "/api/config"):
        _, headers, _ = raw_exchange(
            server.port, f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1:{server.port}\r\n\r\n".encode())
        names = [name.lower() for name, _ in headers]
        assert names.count("cache-control") == 1, (path, headers)


def test_more_than_one_host_header_is_a_400(server):
    host = f"127.0.0.1:{server.port}"
    status, _, body = raw_exchange(
        server.port, f"GET /api/config HTTP/1.0\r\nHost: {host}\r\nHost: {host}\r\n\r\n".encode())
    assert status == 400 and json.loads(body)["error"]["code"] == "BAD_HOST"
    status, _, _ = raw_exchange(
        server.port, f"GET /api/config HTTP/1.0\r\nHost: evil.example\r\nHost: {host}\r\n\r\n".encode())
    assert status == 400


@pytest.mark.parametrize("bound,accepted,refused", [
    ("127.0.0.1", {"127.0.0.1:80", "localhost:80", "[::1]:80"}, {"127.0.0.2:80", "localhost:81", "[::1]", "::1:80"}),
    ("::1", {"[::1]:80", "localhost:80"}, {"127.0.0.1:80", "[::2]:80"}),
    ("192.0.2.7", {"192.0.2.7:80"}, {"localhost:80", "[::1]:80", "127.0.0.1:80"}),
    ("example.test", {"example.test:80"}, {"localhost:80", "[::1]:80"}),
])
def test_host_policy_is_exactly_the_bound_address_plus_loopback_aliases_when_loopback(bound, accepted, refused):
    from p1.server_security import allowed_hosts, host_is_allowed, origin_is_allowed
    allowed = allowed_hosts(bound, 80)
    for host in accepted:
        assert host_is_allowed(host, allowed), host
        assert origin_is_allowed(f"http://{host}", allowed), host
    for host in refused:
        assert not host_is_allowed(host, allowed), host
        assert not origin_is_allowed(f"http://{host}", allowed), host
    assert not origin_is_allowed("https://" + sorted(accepted)[0], allowed)


def test_module_docstring_documents_the_host_policy():
    import p1.server_security as module
    doc = module.__doc__ or ""
    assert "localhost:<port>" in doc and "[::1]:<port>" in doc


# ---------------------------------------------------------------- M2: exhaustion bounds


def open_upload(srv, declared: int, first: bytes = ZIP_BYTES[:8], name="slow.zip"):
    """Start an upload but send only *first*: the server blocks waiting for the rest."""
    import socket
    sock = socket.create_connection(("127.0.0.1", srv.port), timeout=10)
    head = (f"POST /api/discoveries/upload?name={name} HTTP/1.0\r\nHost: 127.0.0.1:{srv.port}\r\n"
            f"X-P1-Request: 1\r\nContent-Type: application/zip\r\nContent-Length: {declared}\r\n\r\n")
    sock.sendall(head.encode() + first)
    return sock


def read_response(sock) -> tuple[int, dict]:
    chunks = []
    while True:
        data = sock.recv(65536)
        if not data:
            break
        chunks.append(data)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split()[1]), json.loads(body) if body else {}


def wait_until(predicate, timeout=5.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def part_files(srv) -> list[Path]:
    return list((srv.app.store / "uploads").glob("*.part"))


def test_third_concurrent_upload_gets_429_busy_before_its_body_is_read(tmp_path):
    srv = build(tmp_path)
    holders = []
    try:
        holders = [open_upload(srv, 1000), open_upload(srv, 1000)]
        assert wait_until(lambda: len(part_files(srv)) == 2)
        third = open_upload(srv, 1000, first=b"")  # headers only: an eager reader would hang
        status, payload = read_response(third)
        third.close()
        assert status == 429 and payload["error"]["code"] == "BUSY"
        assert len(part_files(srv)) == 2
    finally:
        for sock in holders:
            sock.close()
        srv.app.shutdown()


def test_upload_slot_is_released_when_an_upload_finishes(tmp_path):
    srv = build(tmp_path)
    try:
        for _ in range(5):  # more sequential uploads than the semaphore size
            status, _, _ = srv.upload("a.zip", ZIP_BYTES)
            assert status == 202
        holders = [open_upload(srv, 1000), open_upload(srv, 1000)]
        for sock in holders:
            sock.close()
        assert wait_until(lambda: srv.upload("b.zip", ZIP_BYTES)[0] == 202)  # slots freed again
    finally:
        srv.app.shutdown()


def test_full_queue_is_refused_before_the_body_is_read_and_costs_no_disk(tmp_path):
    gate = threading.Event()
    srv = build(tmp_path, discover_fn=make_fake_discover(gate=gate), max_queue=1)
    try:
        statuses = []
        for _ in range(3):  # one runs, one queues; the rest fill the queue
            statuses.append(srv.post_json({"kind": "git", "url": "https://git.example.com/a.git"})[0])
        assert statuses[:2] == [202, 202] or 429 in statuses
        sock = open_upload(srv, 1000, first=b"")  # headers only
        status, payload = read_response(sock)
        sock.close()
        assert status == 429 and payload["error"]["code"] == "QUEUE_FULL"
        assert part_files(srv) == [] and uploads_left(srv) == []
        assert srv.app.jobs._reserved == 0
    finally:
        gate.set()
        srv.app.shutdown()


def test_reserved_slot_is_released_when_the_upload_fails(tmp_path):
    srv = build(tmp_path, max_queue=1)
    try:
        for _ in range(3):
            status, _, _ = srv.upload("bad.zip", b"not a zip at all")
            assert status == 400
        assert srv.app.jobs._reserved == 0
        assert srv.upload("ok.zip", ZIP_BYTES)[0] == 202
    finally:
        srv.app.shutdown()


def test_slow_upload_hits_the_wall_clock_deadline_with_408_and_removes_the_part_file(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr("p1.server.UPLOAD_BASE_DEADLINE", 0.6)
    monkeypatch.setattr("p1.server.UPLOAD_MIN_BYTES_PER_SECOND", 1e12)
    srv = build(tmp_path)
    sock = open_upload(srv, 3000, first=ZIP_BYTES[:8])
    try:
        started = time.monotonic()
        try:
            for _ in range(40):  # a trickle that never stalls long enough for the socket timeout
                time.sleep(0.15)
                sock.sendall(b"\x00")
                if select.select([sock], [], [], 0)[0]:
                    break
        except OSError:
            pass
        elapsed = time.monotonic() - started
        status, payload = read_response(sock)
        assert status == 408 and payload["error"]["code"] == "UPLOAD_TIMEOUT"
        assert elapsed < 3  # cut off near the 0.6 s deadline, not after the whole trickle
        assert wait_until(lambda: uploads_left(srv) == [])
    finally:
        sock.close()
        srv.app.shutdown()


def test_upload_deadline_grows_with_the_declared_size():
    from p1.server_uploads import upload_deadline
    assert upload_deadline(0, 120, 1024) == 120
    assert upload_deadline(10 * 1024, 120, 1024) == 130
    assert upload_deadline(-5, 120, 1024) == 120


def test_connections_beyond_the_cap_get_an_immediate_503(tmp_path):
    import socket
    srv = build(tmp_path, max_connections=2)
    idle = []
    try:
        for _ in range(2):
            idle.append(socket.create_connection(("127.0.0.1", srv.port), timeout=10))

        def refused() -> bool:
            probe = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
            try:
                return probe.recv(64).startswith(b"HTTP/1.0 503")
            finally:
                probe.close()

        assert wait_until(refused)
        for sock in idle:
            sock.close()
        assert wait_until(lambda: srv.request("GET", "/api/config")[0] == 200)
    finally:
        for sock in idle:
            sock.close()
        srv.app.shutdown()


def test_startup_sweeps_stale_part_and_zip_files_but_not_fresh_or_other_files(tmp_path):
    import os
    import time
    uploads = tmp_path / "store" / "uploads"
    uploads.mkdir(parents=True)
    old = time.time() - 10_000
    stale = [uploads / "dead.zip.part", uploads / "orphan.zip"]
    for path in stale:
        path.write_bytes(b"PK")
        os.utime(path, (old, old))
    other = uploads / "keep.txt"
    other.write_text("x")
    os.utime(other, (old, old))
    fresh = uploads / "fresh.zip"
    fresh.write_bytes(b"PK")
    srv = build(tmp_path)
    try:
        assert not any(p.exists() for p in stale)
        assert other.exists() and fresh.exists()
    finally:
        srv.app.shutdown()
