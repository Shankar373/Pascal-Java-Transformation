"""End-to-end Stage 1 workflow: ingest -> checkpoint -> blueprint.

Every test drives :func:`p1.stage1.discover` over the realistic enterprise
fixture (tests/fixtures/stage1/enterprise_app.py) through the three input
kinds, and asserts the guarantees Stage 1 exists to provide.
"""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from fixtures.stage1.enterprise_app import (
    ENTERPRISE_APP,
    EXPECTED,
    write_enterprise_app,
)

from p1.checkpoint import verify_checkpoint
from p1.errors import IngestionError
from p1.schemacheck import validate
from p1.stage1 import STEP_IDS, DiscoveryRequest, discover

REPO = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (REPO / "docs/stage1/schemas/application-blueprint.schema.json")
    .read_text(encoding="utf-8")
)


def _git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd, capture_output=True, text=True, check=True, env=env,
    )
    return out.stdout.strip()


@pytest.fixture()
def app(tmp_path: Path) -> Path:
    return write_enterprise_app(tmp_path / "app")


@pytest.fixture()
def git_app(tmp_path: Path) -> Path:
    root = write_enterprise_app(tmp_path / "gitapp")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    return root


@pytest.fixture()
def zip_app(tmp_path: Path) -> Path:
    archive = tmp_path / "erp.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for rel in sorted(ENTERPRISE_APP):
            info = zipfile.ZipInfo(rel, date_time=(2020, 1, 2, 3, 4, 6))
            info.external_attr = 0o100644 << 16
            data = ENTERPRISE_APP[rel]
            z.writestr(info, data if isinstance(data, bytes)
                       else data.encode("utf-8"))
    return archive


def _run(tmp_path: Path, request: DiscoveryRequest, name: str = "store"):
    steps: list[tuple[str, str, str]] = []
    result = discover(request, tmp_path / name,
                      progress=lambda *a: steps.append(a))
    return result, steps


def test_directory_discovery_produces_valid_blueprint(tmp_path, app) -> None:
    result, steps = _run(tmp_path, DiscoveryRequest(
        "directory", str(app), label="legacy-erp"))
    assert validate(result.blueprint, SCHEMA) == []
    assert result.blueprint["project"]["name"] == "legacy-erp"
    assert result.blueprint["summary"]["total_files"] == EXPECTED["file_count"]
    reported = [(s, st) for s, st, _ in steps if st in ("completed", "failed")]
    assert reported == [(sid, "completed") for sid, _ in STEP_IDS]


def test_every_output_artefact_is_written(tmp_path, app) -> None:
    result, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    for name in ("blueprint", "manifest", "graph", "report", "unresolved",
                 "diagnostics", "inventory", "run_record"):
        assert Path(result.outputs[name]).is_file(), name


def test_blueprint_covers_every_discovery_domain(tmp_path, app) -> None:
    result, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    b = result.blueprint
    deps = b["dependencies"]
    assert {p["path"] for p in b["projects"]} == set(EXPECTED["projects"])
    assert b["dialect"]["label"] == "Delphi / Object Pascal"
    ids = {u["id"] for u in b["unresolved"]}
    assert f"unit:{EXPECTED['unresolved_unit']}" in ids
    assert f"include:{EXPECTED['unresolved_include']}" in ids
    libs = {lib["name"]: lib["origin"] for lib in deps["libraries"]}
    assert libs[EXPECTED["bundled_library"]] == "bundled"
    for name in EXPECTED["absent_libraries"]:
        assert libs[name] == "external"
    categories = {i["category"] for i in deps["integrations"]}
    assert {"http-client", "soap-webservice", "ftp", "email", "com-ole",
            "windows-service", "reporting"} <= categories
    runtime = {(r["kind"], r["name"].lower()): r["resolved_in_input"]
               for r in deps["runtime"]}
    assert runtime[("dll", "legacy.dll")] is True
    assert runtime[("dll", EXPECTED["absent_dll"])] is False
    assert any(k[0] == "environment-variable" for k in runtime)
    assert any(k[0] == "registry-key" for k in runtime)
    assert deps["build"]["scripts"] and deps["build"]["compiler_configs"]
    assert any(d["path"] == "empty_dir_marker"
               for d in b["inventory"]["directories"])


def test_rtl_units_are_not_reported_as_missing(tmp_path, app) -> None:
    result, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    errors = {u["name"].lower() for u in result.blueprint["unresolved"]
              if u["kind"] == "unit" and u["severity"] == "error"}
    assert errors == {EXPECTED["unresolved_unit"], "vendorui"}


def test_secret_never_reaches_any_artefact(tmp_path, app) -> None:
    result, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    for name, path in result.outputs.items():
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        assert EXPECTED["secret_in_source"] not in text, name


def test_no_absolute_or_store_path_in_deterministic_outputs(
        tmp_path, app) -> None:
    result, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    needles = {str(tmp_path), str(tmp_path).replace("\\", "/"),
               str(tmp_path).replace("\\", "\\\\")}
    for name, path in result.outputs.items():
        if name == "run_record":
            continue
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        for needle in needles:
            assert needle not in text, (name, needle)


def test_checkpoint_is_preserved_and_verifiable(tmp_path, app) -> None:
    result, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    info = result.checkpoint
    assert verify_checkpoint(info.path).ok
    preserved = info.source_root / "ERPSystem.dpr"
    assert preserved.read_bytes() == (app / "ERPSystem.dpr").read_bytes()
    with pytest.raises(PermissionError):
        preserved.write_bytes(b"changed")


def test_rerun_reuses_checkpoint_and_is_byte_identical(tmp_path, app) -> None:
    first, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    second, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    assert second.reused and not first.reused
    assert first.checkpoint.checkpoint_id == second.checkpoint.checkpoint_id
    for name in ("blueprint", "manifest", "graph", "unresolved", "inventory"):
        assert (Path(first.outputs[name]).read_bytes()
                == Path(second.outputs[name]).read_bytes()), name


def test_two_separate_stores_give_identical_blueprints(tmp_path, app) -> None:
    a, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)), "s1")
    b, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)), "s2")
    assert a.checkpoint.checkpoint_id == b.checkpoint.checkpoint_id
    assert (Path(a.outputs["blueprint"]).read_bytes()
            == Path(b.outputs["blueprint"]).read_bytes())


def test_tampered_checkpoint_is_never_reused(tmp_path, app) -> None:
    first, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    victim = first.checkpoint.source_root / "ERPSystem.dpr"
    os.chmod(victim, 0o666)
    victim.write_bytes(b"program Evil; begin end.")
    with pytest.raises(IngestionError) as caught:
        _run(tmp_path, DiscoveryRequest("directory", str(app)))
    assert caught.value.code == "CHECKPOINT_TAMPERED"


def test_zip_input_preserves_original_archive(tmp_path, zip_app) -> None:
    result, _ = _run(tmp_path, DiscoveryRequest("zip", str(zip_app),
                                                label="erp"))
    original = result.checkpoint.path / "original" / "input.zip"
    assert original.read_bytes() == zip_app.read_bytes()
    assert validate(result.blueprint, SCHEMA) == []
    assert result.blueprint["project"]["ingestion_source"]["kind"] == "zip"


def test_git_input_is_pinned_to_exact_commit(tmp_path, git_app) -> None:
    sha = _git(git_app, "rev-parse", "HEAD")
    result, _ = _run(tmp_path, DiscoveryRequest("git", str(git_app),
                                                label="erp"))
    source = result.blueprint["project"]["ingestion_source"]
    assert source["kind"] == "git" and source["commit"] == sha
    assert result.checkpoint.commit == sha
    assert result.blueprint["project"]["checkpoint"]["tree_id"]


def test_git_ref_pins_an_earlier_commit(tmp_path, git_app) -> None:
    sha = _git(git_app, "rev-parse", "main")
    (git_app / "later.txt").write_text("x", encoding="utf-8")
    _git(git_app, "add", "-A")
    _git(git_app, "commit", "-q", "-m", "later")
    result, _ = _run(tmp_path, DiscoveryRequest("git", str(git_app), ref=sha))
    assert result.checkpoint.commit == sha
    assert not (result.checkpoint.source_root / "later.txt").exists()


def test_git_branch_name_resolves(tmp_path, git_app) -> None:
    sha = _git(git_app, "rev-parse", "main")
    result, _ = _run(tmp_path, DiscoveryRequest("git", str(git_app),
                                                ref="main"))
    assert result.checkpoint.commit == sha


@pytest.mark.parametrize("ref", ["--upload-pack=x", "a b", "nope/missing"])
def test_bad_local_refs_are_refused(tmp_path, git_app, ref) -> None:
    with pytest.raises(IngestionError):
        _run(tmp_path, DiscoveryRequest("git", str(git_app), ref=ref))


def test_all_three_input_kinds_agree(tmp_path, app, zip_app, git_app) -> None:
    def core(result):
        b = result.blueprint
        return (b["summary"]["pascal_sources"], b["summary"]["projects"],
                sorted(u["id"] for u in b["unresolved"]),
                [lib["name"] for lib in b["dependencies"]["libraries"]])
    d = core(_run(tmp_path, DiscoveryRequest("directory", str(app)), "a")[0])
    z = core(_run(tmp_path, DiscoveryRequest("zip", str(zip_app)), "b")[0])
    g = core(_run(tmp_path, DiscoveryRequest("git", str(git_app)), "c")[0])
    assert d == z == g


def test_refused_input_leaves_no_blueprint_and_no_staging(tmp_path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip at all")
    store = tmp_path / "store"
    steps: list[tuple[str, str, str]] = []
    with pytest.raises(IngestionError):
        discover(DiscoveryRequest("zip", str(bad)), store,
                 progress=lambda *a: steps.append(a))
    assert steps[-1][:2] == ("ingestion", "failed")
    assert not (store / "discoveries").exists() \
        or not list((store / "discoveries").iterdir())
    assert not [p for p in store.iterdir() if p.name.startswith("p1-stage-")]


def test_symlink_in_directory_input_fails_closed(tmp_path, app) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        os.symlink(outside, app / "evil.pas")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted here")
    with pytest.raises(IngestionError):
        _run(tmp_path, DiscoveryRequest("directory", str(app)))


def test_progress_callback_errors_cannot_break_the_run(tmp_path, app) -> None:
    def boom(*_args: str) -> None:
        raise RuntimeError("callback bug")

    result = discover(DiscoveryRequest("directory", str(app)),
                      tmp_path / "store", progress=boom)
    assert validate(result.blueprint, SCHEMA) == []


def test_run_record_is_the_only_nondeterministic_output(tmp_path, app) -> None:
    result, _ = _run(tmp_path, DiscoveryRequest("directory", str(app)))
    record = json.loads(Path(result.outputs["run_record"])
                        .read_text(encoding="utf-8"))
    assert record["checkpoint_id"] == result.checkpoint.checkpoint_id
    assert [s["id"] for s in record["steps"]] == [s for s, _ in STEP_IDS]
    assert record["ingested_at"].endswith("Z")
    assert "ingested_at" not in json.dumps(result.blueprint)


def test_unknown_kind_is_refused() -> None:
    with pytest.raises(IngestionError) as caught:
        DiscoveryRequest("ftp", "x")
    assert caught.value.code == "UNKNOWN_INPUT_KIND"


def test_missing_directory_is_refused(tmp_path) -> None:
    with pytest.raises(IngestionError) as caught:
        discover(DiscoveryRequest("directory", str(tmp_path / "nope")),
                 tmp_path / "store")
    assert caught.value.code == "INPUT_NOT_FOUND"
