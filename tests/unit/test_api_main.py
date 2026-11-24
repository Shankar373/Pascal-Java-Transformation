"""``p1 api`` and ``p1 tenant-token`` command behaviour (no server is started)."""

from __future__ import annotations

import pytest

from p1 import api_main, cli
from p1.tenant_auth import TokenTable, hash_token


@pytest.fixture
def tokens(tmp_path):
    path = tmp_path / "tokens.txt"
    assert api_main.issue_main(["--tokens-file", str(path), "--tenant", "acme"]) == 0
    return path


def test_issue_prints_token_once_and_stores_only_its_hash(tmp_path, capsys):
    path = tmp_path / "t.txt"
    assert api_main.issue_main(["--tokens-file", str(path), "--tenant", "acme"]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    text = path.read_text()
    assert token not in text and hash_token(token) in text
    assert TokenTable.load(path).resolve(token) == "acme"


@pytest.mark.parametrize("tenant", ["jobs", "../x", "ACME", ""])
def test_issue_refuses_invalid_tenants(tmp_path, tenant, capsys):
    assert api_main.issue_main(["--tokens-file", str(tmp_path / "t"), "--tenant", tenant]) == 2
    assert not (tmp_path / "t").exists()


def test_api_refuses_a_non_loopback_bind_without_tokens(tmp_path):
    assert api_main.main(["--store", str(tmp_path / "s"), "--host", "0.0.0.0"]) == 2


def test_api_refuses_tokens_over_cleartext_on_a_public_bind(tmp_path, tokens):
    argv = ["--store", str(tmp_path / "s"), "--host", "0.0.0.0", "--tenant-tokens-file", str(tokens)]
    assert api_main.main(argv) == 2


def test_api_refuses_a_bad_token_file(tmp_path):
    bad = tmp_path / "bad"
    bad.write_text("garbage\n")
    assert api_main.main(["--store", str(tmp_path / "s"), "--tenant-tokens-file", str(bad)]) == 2


def test_api_refuses_missing_local_root(tmp_path):
    assert api_main.main(["--store", str(tmp_path / "s"), "--allow-local-root", str(tmp_path / "nope")]) == 2


def test_api_refuses_a_root_that_overlaps_the_store(tmp_path):
    assert api_main.main(["--store", str(tmp_path / "s"), "--allow-local-root", str(tmp_path)]) == 2


def test_api_starts_uvicorn_with_hardened_options(tmp_path, monkeypatch, tokens):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    argv = ["--store", str(tmp_path / "s"), "--port", "8801", "--tenant-tokens-file", str(tokens)]
    assert api_main.main(argv) == 0
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8801
    assert seen["server_header"] is False and seen["limit_concurrency"] == 64
    assert seen["app"].state.p1.tokens is not None


def test_public_bind_is_allowed_with_tokens_behind_a_tls_proxy(tmp_path, monkeypatch, tokens):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    argv = ["--store", str(tmp_path / "s"), "--host", "0.0.0.0", "--behind-tls-proxy",
            "--tenant-tokens-file", str(tokens)]
    assert api_main.main(argv) == 0
    assert seen["app"].state.p1.behind_tls_proxy is True


def test_cli_dispatches_api_and_tenant_token_with_leading_flags(tmp_path, capsys):
    path = tmp_path / "t.txt"
    assert cli.main(["tenant-token", "--tokens-file", str(path), "--tenant", "globex"]) == 0
    assert cli.main(["api", "--store", str(tmp_path / "s"), "--host", "0.0.0.0"]) == 2
