"""Stage 1 acceptance: the customer journey through the real API and the real
``discover`` pipeline (no fakes).  Each test names the acceptance criterion
(AC-n) it evidences; see docs/stage1/STAGE1_ACCEPTANCE.md."""

from __future__ import annotations

import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from blueprint_helpers import enterprise_tree, evidence_owners
from conftest import make_zip

from p1.checkpoint_verify import verify_checkpoint
from p1.fastapi_app import create_api
from p1.schemacheck import validate

REPO = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO / "docs/stage1/schemas/application-blueprint.schema.json")
                    .read_text(encoding="utf-8"))
BASE = "http://127.0.0.1:8766"
POST = {"X-P1-Request": "1"}
ZIP_POST = {**POST, "Content-Type": "application/zip"}
SENTINEL = "P1_EXECUTED_SENTINEL"


def api(tmp_path: Path, name: str = "store", **kw) -> TestClient:
    return TestClient(create_api(tmp_path / name, "127.0.0.1", 8766, **kw), base_url=BASE)


def finish(client: TestClient, job_id: str, headers=None) -> dict:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        view = client.get(f"/api/discoveries/{job_id}", headers=headers).json()
        if view["status"] in ("completed", "failed"):
            return view
        time.sleep(0.1)
    raise AssertionError("discovery did not finish")


def upload(client: TestClient, path: Path, headers=None) -> dict:
    r = client.post(f"/api/discoveries/upload?name={path.name}", content=path.read_bytes(),
                    headers={**ZIP_POST, **(headers or {})})
    assert r.status_code == 202, r.text
    return finish(client, r.json()["id"], headers)


@pytest.fixture(scope="module")
def estate_zip(tmp_path_factory) -> Path:
    """Enterprise estate plus files that would do harm if anything ran them."""

    tree = enterprise_tree(tmp_path_factory.mktemp("estate"))
    plant = {
        "tools/build.bat": f"@echo off\r\necho {SENTINEL} > executed.flag\r\n",
        "tools/build.sh": f"#!/bin/sh\ntouch executed.flag # {SENTINEL}\n",
        "tools/evil.ps1": f"New-Item executed.flag # {SENTINEL}\n",
        "tools/evil.exe": "MZ" + SENTINEL,
        "src/Hostile.pas": "unit Hostile;\ninterface\n{$MESSAGE FATAL 'boom'}\n"
                           "{$I C:\\Windows\\win.ini}\nimplementation\nend.\n",
    }
    for rel, text in plant.items():
        target = tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="latin-1")
    out = tmp_path_factory.mktemp("zip") / "estate.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(tree.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(tree).as_posix())
    return out


@pytest.fixture(scope="module")
def journey(tmp_path_factory, estate_zip):
    """One real ZIP discovery, observed for process creation while it runs."""

    tmp = tmp_path_factory.mktemp("journey")
    spawned: list[str] = []
    real_popen = subprocess.Popen

    def watching(args, *a, **k):
        spawned.append(str(args))
        return real_popen(args, *a, **k)

    mp = pytest.MonkeyPatch()
    mp.setattr(subprocess, "Popen", watching)
    for name in ("system", "startfile", "execv", "execve", "spawnv", "spawnl"):
        if hasattr(os, name):
            mp.setattr(os, name, lambda *a, _n=name, **k: spawned.append(_n))
    try:
        with api(tmp) as client:
            view = upload(client, estate_zip)
            blueprint = client.get(f"/api/discoveries/{view['id']}/blueprint").json()
            yield {"client": client, "view": view, "blueprint": blueprint,
                   "spawned": list(spawned), "tmp": tmp,
                   "store": client.app.state.p1.store}
    finally:
        mp.undo()


def test_ac1_zip_journey_completes_with_all_five_steps(journey):
    view = journey["view"]
    assert view["status"] == "completed"
    assert [s["id"] for s in view["steps"]] == [
        "ingestion", "checkpoint", "scanning_inventory", "dependency_analysis", "blueprint"]
    assert {s["status"] for s in view["steps"]} <= {"completed", "warning"}


def test_ac2_blueprint_matches_the_published_schema(journey):
    assert validate(journey["blueprint"], SCHEMA) == []


def test_ac3_every_finding_carries_located_evidence(journey):
    owners = list(evidence_owners(journey["blueprint"]))
    assert owners
    for where, item in owners:
        assert item["evidence"], where
        assert all(e.get("file") for e in item["evidence"]), where


def test_ac4_checkpoint_is_immutable_and_verifies(journey):
    cps = list((journey["store"] / "checkpoints").glob("CP-*"))
    assert len(cps) == 1
    assert verify_checkpoint(cps[0]).ok
    files = [p for p in (cps[0] / "source").rglob("*") if p.is_file()]
    assert files and all(not os.access(p, os.W_OK) for p in files)


def test_ac5_machine_readable_reports_are_all_published(journey):
    client, jid = journey["client"], journey["view"]["id"]
    for name in ("application-blueprint.json", "application-manifest.json",
                 "dependency-graph.json", "unresolved-dependencies.json",
                 "diagnostics.json", "checkpoint-manifest.json",
                 "project-inventory.json", "architecture-report.json"):
        r = client.get(f"/api/discoveries/{jid}/artifacts/{name}")
        assert r.status_code == 200 and isinstance(r.json(), dict), name
    assert client.get(f"/api/discoveries/{jid}/artifacts/inventory.csv").text.startswith("path,")
    assert client.get(f"/api/discoveries/{jid}/report").text.strip()


def test_ac6_nothing_in_the_input_is_executed(journey):
    assert journey["spawned"] == []
    for root in (journey["store"], journey["tmp"]):
        assert not list(root.rglob("executed.flag"))
    scripts = journey["blueprint"]["dependencies"]["build"]["scripts"]
    assert {Path(s["path"]).name for s in scripts} >= {"build.bat", "build.sh", "evil.ps1"}


def test_ac7_processing_is_deterministic_across_stores(tmp_path, estate_zip, journey):
    with api(tmp_path, "second") as client:
        view = upload(client, estate_zip)
        again = client.get(f"/api/discoveries/{view['id']}/blueprint").content
    first = journey["client"].get(f"/api/discoveries/{journey['view']['id']}/blueprint").content
    assert first == again


def test_ac8_directory_input_yields_the_same_findings(tmp_path, journey):
    tree = enterprise_tree(tmp_path / "src")
    with api(tmp_path, "dirstore", allow_local_roots=[tmp_path / "src"]) as client:
        r = client.post("/api/discoveries", json={"kind": "directory", "path": str(tree)},
                        headers=POST)
        view = finish(client, r.json()["id"])
        assert view["status"] == "completed"
        bp = client.get(f"/api/discoveries/{view['id']}/blueprint").json()
    assert validate(bp, SCHEMA) == []
    zbp = journey["blueprint"]
    # the zip carries extra planted files; the enterprise findings must be a subset
    assert bp["summary"]["projects"] == zbp["summary"]["projects"]
    assert bp["dialect"]["primary"] == zbp["dialect"]["primary"]
    names = {item["name"] for item in bp["dependencies"]["libraries"]}
    assert names and names <= {item["name"] for item in zbp["dependencies"]["libraries"]}


def test_ac9_tenants_cannot_read_each_others_discoveries(tmp_path, estate_zip):
    a, b = {"X-P1-Tenant": "acme"}, {"X-P1-Tenant": "globex"}
    with api(tmp_path) as client:
        view = upload(client, estate_zip, a)
        assert view["status"] == "completed"
        jid = view["id"]
        assert client.get(f"/api/discoveries/{jid}/blueprint", headers=a).status_code == 200
        for path in ("", "/blueprint", "/report", "/artifacts/inventory.csv"):
            assert client.get(f"/api/discoveries/{jid}{path}", headers=b).status_code == 404
            assert client.get(f"/api/discoveries/{jid}{path}").status_code == 404
        assert client.get("/api/discoveries", headers=b).json()["items"] == []
        store = client.app.state.p1.store
        assert list((store / "tenants" / "acme" / "checkpoints").glob("CP-*"))
        assert not list(store.glob("checkpoints/CP-*"))


@pytest.mark.parametrize("entries,why", [
    ([("../../escape.pas", b"unit x; end.")], "zip-slip"),
    ([("a.pas", b"x"), ("A.PAS", b"y")], "case-fold duplicate"),
    ([("/abs/evil.pas", b"x")], "absolute path"),
])
def test_ac10_hostile_archives_are_refused_and_publish_nothing(tmp_path, entries, why):
    bad = make_zip(tmp_path / "bad.zip", entries)
    with api(tmp_path) as client:
        view = upload(client, bad)
        assert view["status"] == "failed", why
        assert view["error"]["code"]
        store = client.app.state.p1.store
        assert not list(store.glob("discoveries/*"))
        assert not list(store.glob("checkpoints/CP-*"))
        assert list((store / "uploads").iterdir()) == []


def test_ac11_failed_run_is_recoverable_by_a_clean_retry(tmp_path, estate_zip):
    bad = make_zip(tmp_path / "bad.zip", [("../x.pas", b"x")])
    with api(tmp_path) as client:
        assert upload(client, bad)["status"] == "failed"
        assert upload(client, estate_zip)["status"] == "completed"


def test_ac12_restart_preserves_finished_discoveries(tmp_path, estate_zip):
    with api(tmp_path) as client:
        jid = upload(client, estate_zip)["id"]
        before = client.get(f"/api/discoveries/{jid}/blueprint").content
    with api(tmp_path) as client:
        assert client.get(f"/api/discoveries/{jid}").json()["status"] == "completed"
        assert client.get(f"/api/discoveries/{jid}/blueprint").content == before
