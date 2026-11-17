"""Stage 1 inventory detectors: directories, build scripts, compiler configs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from p1.classify import classify, is_ci_config
from p1.findings import BUILD_SCRIPT_KINDS, COMPILER_CONFIG_KINDS
from p1.inventory import (
    detect_build_scripts,
    detect_compiler_configs,
    list_directories,
    wants_text,
)
from p1.model import IngestedFile
from s1helpers import (
    SECRET,
    analyse,
    assert_well_formed,
    dump_all,
    enterprise,
)


@pytest.fixture(scope="module")
def ent(tmp_path_factory):
    return enterprise(tmp_path_factory)


# --------------------------------------------------------------------------
# classify.py extension
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", [
    "setup/app.iss", "setup/app.nsi", "setup/inc.nsh", "ci/Jenkinsfile",
    "Jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml",
    "appveyor.yml", ".appveyor.yml", ".github/workflows/build.yml",
    ".github/workflows/Release.YAML", "sub/.github/workflows/x.yml",
    ".circleci/config.yml", "build/x.mk", "b/rules.mak",
])
def test_build_and_ci_files_are_build_scripts(path: str) -> None:
    assert classify(path, b"").cls == "build_script"


@pytest.mark.parametrize("path,expected", [
    ("conf/app.yml", "configuration"),
    (".github/dependabot.yml", "configuration"),
    (".github/workflows/README.md", "documentation"),
    (".github/CODEOWNERS", "unknown"),
    ("src/x.dof", "pascal_project"),
    (".gitignore", "version_control"),
    (".git/config", "version_control"),
    ("Makefile", "build_script"),
])
def test_existing_classification_is_unchanged(path: str, expected: str) -> None:
    assert classify(path, b"").cls == expected


def test_is_ci_config_predicate() -> None:
    assert is_ci_config(".github/workflows/a.yml")
    assert is_ci_config("x/Jenkinsfile")
    assert not is_ci_config("config/a.yml")
    assert not is_ci_config("")


# --------------------------------------------------------------------------
# list_directories
# --------------------------------------------------------------------------


def _files(*items: tuple[str, int]) -> list[IngestedFile]:
    return [IngestedFile(path=p, sha256="0" * 64, size=s) for p, s in items]


def test_directories_counts_and_depth(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f.pas").write_text("x")
    (tmp_path / "a" / "g.pas").write_text("yy")
    files = _files(("a/b/f.pas", 1), ("a/g.pas", 2), ("top.txt", 5))
    by_path = {d.path: d for d in list_directories(tmp_path, files)}
    assert set(by_path) == {"a", "a/b"}
    assert by_path["a"].depth == 1 and by_path["a/b"].depth == 2
    assert by_path["a"].file_count == 1
    assert by_path["a"].total_file_count == 2
    assert by_path["a"].total_bytes == 3
    assert by_path["a/b"].file_count == 1
    assert not by_path["a"].empty


def test_truly_empty_directories_are_preserved(tmp_path: Path) -> None:
    (tmp_path / "keep" / "deeper").mkdir(parents=True)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "f.pas").write_text("a")
    result = list_directories(tmp_path, _files(("x/f.pas", 1)))
    by_path = {d.path: d for d in result}
    assert by_path["keep"].empty and by_path["keep/deeper"].empty
    assert by_path["keep"].total_file_count == 0
    assert not by_path["x"].empty
    assert [d.path for d in result] == sorted(d.path for d in result)


def test_directories_skip_vcs_and_missing_root(tmp_path: Path) -> None:
    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    assert [d.path for d in list_directories(tmp_path, [])] == ["src"]
    gone = tmp_path / "nope"
    derived = list_directories(gone, _files(("p/q/r.pas", 3)))
    assert [d.path for d in derived] == ["p", "p/q"]


def test_directories_fixture_has_marker_and_is_deterministic(ent) -> None:
    result = list_directories(ent.root, ent.files)
    paths = [d.path for d in result]
    assert "empty_dir_marker" in paths and "lib/jedi" in paths
    assert "" not in paths
    reverse = list_directories(ent.root, list(reversed(ent.files)))
    assert [d.as_dict() for d in result] == [d.as_dict() for d in reverse]
    assert all(not str(ent.root) in json.dumps(d.as_dict()) for d in result)


# --------------------------------------------------------------------------
# build scripts
# --------------------------------------------------------------------------


def _scripts(ent):
    return {
        f.path: f for f in detect_build_scripts(ent.analysed, ent.text_of, [])
    }


def test_fixture_build_bat(ent) -> None:
    bat = _scripts(ent)["build.bat"]
    assert bat.kind == "batch"
    assert {"msbuild", "dcc32", "rsvars"} <= set(bat.tools)
    assert set(bat.referenced_projects) == {
        "ERPSystem.dproj", "ERPSystem.dpr"
    }
    assert {e.line for e in bat.evidence} >= {2, 3, 4}


def test_fixture_makefile_and_workflow(ent) -> None:
    scripts = _scripts(ent)
    make = scripts["Makefile"]
    assert make.kind == "makefile"
    assert {"lazbuild", "make"} <= set(make.tools)
    flow = scripts[".github/workflows/build.yml"]
    assert flow.kind == "ci-config"
    assert "msbuild" in flow.tools
    assert flow.referenced_projects == ("ERPSystem.dproj",)
    assert_well_formed(list(scripts.values()))


def test_script_kinds_and_tools_by_extension(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {
        "a.ps1": "& \"$env:BDS\\bin\\dcc64.exe\" App.dpr\n",
        "b.sh": "#!/bin/sh\nfpc -Mobjfpc main.pp\nmake -j4\n",
        "setup.iss": "[Setup]\nAppName=X\n",
        "inst.nsi": "OutFile x.exe\n",
        "Group.groupproj": '<Project><ItemGroup><Projects Include="App.dproj"/>'
                           "</ItemGroup></Project>\n",
        "App.dproj": "<Project><Target Name=\"Pre\"><Exec Command=\"msbuild\"/>"
                     "</Target></Project>\n",
        "Plain.dproj": "<Project><PropertyGroup/></Project>\n",
        "ci/Jenkinsfile": "pipeline { stage('b') { bat 'lazbuild a.lpi' } }\n",
        "cron.d/crontab": "0 1 * * * run\n",
    })
    found = {f.path: f for f in detect_build_scripts(
        estate.analysed, estate.text_of, [])}
    assert found["a.ps1"].kind == "powershell"
    assert "dcc64" in found["a.ps1"].tools
    assert found["a.ps1"].referenced_projects == ("App.dpr",) or \
        found["a.ps1"].referenced_projects == ()  # App.dpr not in input
    assert found["b.sh"].kind == "shell"
    assert {"fpc", "make"} <= set(found["b.sh"].tools)
    assert found["setup.iss"].kind == "installer"
    assert "inno" in found["setup.iss"].tools
    assert found["inst.nsi"].kind == "installer"
    assert "nsis" in found["inst.nsi"].tools
    assert found["Group.groupproj"].kind == "msbuild"
    assert found["App.dproj"].kind == "msbuild"
    assert "Plain.dproj" not in found
    assert found["ci/Jenkinsfile"].kind == "ci-config"
    assert "lazbuild" in found["ci/Jenkinsfile"].tools
    assert all(f.kind in BUILD_SCRIPT_KINDS for f in found.values())
    assert_well_formed(list(found.values()))


def test_groupproj_resolves_members(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {
        "g/All.groupproj": '<Projects Include="..\\app\\App.dproj"/>\n'
                           '<Projects Include="Lib.dproj"/>\n',
        "app/App.dproj": "<Project/>\n",
        "g/Lib.dproj": "<Project/>\n",
    })
    found = {f.path: f for f in detect_build_scripts(
        estate.analysed, estate.text_of, [])}
    assert found["g/All.groupproj"].referenced_projects == (
        "app/App.dproj", "g/Lib.dproj")


def test_comments_and_prose_do_not_trigger_tools(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {
        "a.bat": "rem msbuild is not used here\n:: dcc32 neither\n"
                 "echo please make sure things work\n",
        "b.sh": "# fpc and lazbuild are mentioned only in a comment\n"
                "echo done\n",
    })
    found = {f.path: f for f in detect_build_scripts(
        estate.analysed, estate.text_of, [])}
    assert found["a.bat"].tools == () and found["b.sh"].tools == ()
    assert found["a.bat"].evidence  # still located (line 1)


def test_script_without_text_is_unknown_but_evidenced(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {"x.bat": "msbuild a.dproj\n"})
    found = detect_build_scripts(estate.analysed, {}, [])
    assert len(found) == 1
    assert found[0].status == "UNKNOWN" and found[0].evidence
    assert found[0].tools == ()


def test_script_secret_is_redacted(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {
        "r.bat": "set API_TOKEN=abc123xyz & msbuild a.dproj\n"
                 "msbuild b.dproj /p:Password=hunter2secret\n"
                 "curl https://user:pw0rd@host.example/x\n",
    })
    dumped = dump_all(detect_build_scripts(estate.analysed, estate.text_of, []))
    for leaked in ("abc123xyz", "hunter2secret", "pw0rd"):
        assert leaked not in dumped


def test_script_adversarial_inputs_are_bounded(tmp_path: Path) -> None:
    huge = ("msbuild App.dproj /t:Build\n" * 10_000)
    garbage = bytes(range(256)) * 200
    estate = analyse(tmp_path / "t", {
        "huge.bat": huge, "bin.sh": garbage, "App.dproj": "<Project/>",
        "unterminated.ps1": "Write-Host \"msbuild a.dproj\n",
        "mega.cmd": "x" * 3_000_000 + "\nmsbuild a.dproj\n",
    })
    found = {f.path: f for f in detect_build_scripts(
        estate.analysed, estate.text_of, [])}
    assert len(found["huge.bat"].evidence) == 25
    assert found["huge.bat"].tools == ("msbuild",)
    assert found["huge.bat"].referenced_projects == ("App.dproj",)
    assert_well_formed(list(found.values()))


def test_build_scripts_are_deterministic_under_shuffle(ent) -> None:
    base = dump_all(detect_build_scripts(ent.analysed, ent.text_of, []))
    for seed in (1, 2, 3):
        again = detect_build_scripts(ent.shuffled(seed), ent.text_of, [])
        assert dump_all(again) == base


# --------------------------------------------------------------------------
# compiler configs
# --------------------------------------------------------------------------


def _configs(ent):
    return {
        f.path: f for f in detect_compiler_configs(ent.analysed, ent.text_of)
    }


def test_fixture_dcc32_cfg(ent) -> None:
    cfg = _configs(ent)["dcc32.cfg"]
    assert cfg.kind == "dcc-cfg" and cfg.scope == "global"
    switches = dict(cfg.switches)
    assert switches["-$O"] == "+" and switches["-$W"] == "+"
    assert switches["-U"] == "lib\\jedi;core"
    assert switches["-D"] == "ERP_BUILD;RELEASE"
    assert switches["-E"] == "bin" and switches["-N0"] == "dcu"
    assert set(cfg.defines) == {"ERP_BUILD", "RELEASE"}
    assert set(cfg.search_paths) >= {"lib\\jedi", "core", "src", "resources"}
    assert [e.line for e in cfg.evidence][:2] == [1, 2]


def test_fixture_dproj(ent) -> None:
    proj = _configs(ent)["ERPSystem.dproj"]
    assert proj.kind == "delphi-project" and proj.scope == "project"
    assert "ERP_BUILD" in proj.defines
    assert not any(d.startswith("$(") for d in proj.defines)
    assert "lib\\jedi" in proj.search_paths and "core" in proj.search_paths
    assert not any(p.startswith("$(DCC_") for p in proj.search_paths)
    assert ("DCC_Namespace", "System;Xml;Data;Winapi;$(DCC_Namespace)") in \
        proj.switches
    assert all(e.line > 1 for e in proj.evidence)


def test_fixture_configs_are_well_formed_and_vocabulary(ent) -> None:
    found = detect_compiler_configs(ent.analysed, ent.text_of)
    assert {f.path for f in found} == {"dcc32.cfg", "ERPSystem.dproj"}
    assert all(f.kind in COMPILER_CONFIG_KINDS for f in found)
    assert_well_formed(found)


def test_dof_fpc_cfg_lpi_and_other(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {
        "old/App.dof": "[Compiler]\nA=8\nR=1\n[Directories]\n"
                       "SearchPath=..\\lib;C:\\vendor\\src\n"
                       "Conditionals=LEGACY;DEBUG\nOutputDir=bin\n"
                       "[Parameters]\nRunParams=\n",
        "fpc.cfg": "# comment\n-Fu/usr/lib/fpc/units\n-Mobjfpc\n-dFOO\n"
                   "#IFDEF CPUARM\n-Cparmv7\n#ENDIF\n#DEFINE BAR\n-Fi./inc\n",
        "Lazy.lpi": '<?xml version="1.0"?><CONFIG><ProjectOptions>'
                    '<CompilerOptions><Parsing><SyntaxMode Value="Delphi"/>'
                    '</Parsing><SearchPaths><OtherUnitFiles Value="a;b"/>'
                    '</SearchPaths><Other><CustomOptions Value="-dX -dY"/>'
                    "</Other></CompilerOptions></ProjectOptions></CONFIG>",
        "app.cfg": "key=value\nother=1\n",
    })
    found = {f.path: f for f in detect_compiler_configs(
        estate.analysed, estate.text_of)}
    dof = found["old/App.dof"]
    assert dof.kind == "delphi-options" and set(dof.defines) == {
        "LEGACY", "DEBUG"}
    assert set(dof.search_paths) == {"..\\lib", "C:\\vendor\\src"}
    fpc = found["fpc.cfg"]
    assert fpc.kind == "fpc-cfg" and fpc.scope == "global"
    assert set(fpc.defines) == {"FOO", "BAR"}
    assert dict(fpc.switches)["-M"] == "objfpc"
    assert set(fpc.search_paths) == {"/usr/lib/fpc/units", "./inc"}
    lpi = found["Lazy.lpi"]
    assert lpi.kind == "lazarus-project"
    assert set(lpi.defines) == {"X", "Y"}
    assert set(lpi.search_paths) == {"a", "b"}
    assert ("SyntaxMode", "Delphi") in lpi.switches
    other = found["app.cfg"]
    assert other.kind == "other-cfg" and other.status == "UNKNOWN"
    assert other.evidence


def test_config_hostile_inputs(tmp_path: Path) -> None:
    bomb = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">'
            '<!ENTITY b "&a;&a;&a;&a;">]><Project>&b;</Project>')
    estate = analyse(tmp_path / "t", {
        "bomb.dproj": bomb,
        "broken.dproj": "<Project><PropertyGroup>",
        "empty.lpi": "",
        "bin.cfg": bytes(range(256)) * 100,
        "huge.cfg": ("-DFOO\n" * 50_000),
        "quote.cfg": '-U"never closed\n-DX\n',
    })
    found = {f.path: f for f in detect_compiler_configs(
        estate.analysed, estate.text_of)}
    assert found["bomb.dproj"].status == "UNKNOWN"
    assert found["broken.dproj"].status == "UNKNOWN"
    assert found["empty.lpi"].status == "UNKNOWN"
    assert len(found["huge.cfg"].evidence) == 25
    assert found["huge.cfg"].defines == ("FOO",)
    assert_well_formed(list(found.values()))


def test_config_without_text_and_secret_redaction(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {
        "x.cfg": "-DFOO\n-Password=" + SECRET + "\n",
        "dcc32.cfg": "-U\"a\"\n",
    })
    no_text = detect_compiler_configs(estate.analysed, {})
    assert all(f.status == "UNKNOWN" and f.evidence for f in no_text)
    dumped = dump_all(detect_compiler_configs(estate.analysed, estate.text_of))
    assert SECRET not in dumped


def test_configs_deterministic_under_shuffle(ent) -> None:
    base = dump_all(detect_compiler_configs(ent.analysed, ent.text_of))
    for seed in (4, 5):
        assert dump_all(
            detect_compiler_configs(ent.shuffled(seed), ent.text_of)) == base


def test_wants_text_contract(ent) -> None:
    wanted = {i.path for i in ent.analysed if wants_text(i)}
    assert {"build.bat", "Makefile", ".github/workflows/build.yml",
            "dcc32.cfg", "ERPSystem.dproj", "config/erp.ini",
            "src/MainForm.dfm", "sql/schema_oracle.sql"} <= wanted
    assert "lib/legacy.dll" not in wanted
    assert "src/uConfig.pas" not in wanted


def test_pathological_lines_stay_fast(tmp_path: Path) -> None:
    import time

    nasty = ("a-" * 1000 + ".dpr" + "\n") * 1500
    estate = analyse(tmp_path / "t", {
        "x.cfg": nasty, "y.bat": nasty, "App.dproj": "<Project/>",
    })
    started = time.perf_counter()
    detect_build_scripts(estate.analysed, estate.text_of, [])
    detect_compiler_configs(estate.analysed, estate.text_of)
    assert time.perf_counter() - started < 15
