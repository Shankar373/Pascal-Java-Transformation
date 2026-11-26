"""Stage 1 runtime-dependency detector
(`p1.integrations.detect_runtime_dependencies`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from p1.findings import RUNTIME_KINDS
from p1.integrations import (
    detect_integrations,
    detect_libraries,
    detect_runtime_dependencies,
)
from p1.metadata import (
    detect_database,
    detect_native_libs,
    detect_os_dependencies,
)
from s1helpers import (
    SECRET,
    analyse,
    assert_well_formed,
    dump_all,
    enterprise,
    pas,
)


@pytest.fixture(scope="module")
def ent(tmp_path_factory):
    return enterprise(tmp_path_factory)


def _detect(analysed: list, text_of: dict) -> list:
    return detect_runtime_dependencies(
        analysed,
        text_of,
        detect_native_libs(analysed),
        detect_os_dependencies(analysed),
        detect_database(analysed),
        detect_integrations(analysed, text_of),
        detect_libraries(analysed, [], [], text_of=text_of),
    )


def _rt(estate) -> dict[tuple[str, str], Any]:
    found = _detect(estate.analysed, estate.text_of)
    assert_well_formed(found)
    return {(f.kind, f.name): f for f in found}


def _run(tmp_path: Path, files: dict) -> dict[tuple[str, str], Any]:
    return _rt(analyse(tmp_path / "t", files))


# --------------------------------------------------------------------------
# fixture application
# --------------------------------------------------------------------------


def test_fixture_dlls_bundled_and_absent(ent) -> None:
    found = _rt(ent)
    legacy = found[("dll", "legacy.dll")]
    assert legacy.resolved_in_input and "src/uLegacy.pas" in legacy.required_by
    assert all(e.file == "src/uLegacy.pas" for e in legacy.evidence)
    vendor = found[("dll", "vendor.dll")]
    assert not vendor.resolved_in_input
    assert vendor.required_by == ("src/uLegacy.pas",)


def test_fixture_ini_registry_env_path(ent) -> None:
    found = _rt(ent)
    ini = found[("configuration-file", "erp.ini")]
    assert ini.resolved_in_input and "src/uConfig.pas" in ini.required_by
    assert ini.confidence == "high"
    assert ("registry-key", "Software\\Contoso\\ERP") in found
    assert ("environment-variable", "ERP_HOME") in found
    path = found[("hardcoded-path", "C:\\ERP\\data\\import")]
    assert "src/uConfig.pas" in path.required_by
    assert not path.resolved_in_input


def test_fixture_com_service_bpl_client_runtime(ent) -> None:
    found = _rt(ent)
    assert ("com-component", "Excel.Application") in found
    service = found[("service", "TTransferService")]
    assert service.evidence[0].file == "src/uTransfer.pas"
    bpl = found[("bpl-package", "vendorui")]
    assert not bpl.resolved_in_input
    assert bpl.required_by == ("packages/ErpCore.dpk",)
    assert not any(k == "bpl-package" and n in ("rtl", "vcl", "dbrtl")
                   for k, n in found)
    client = found[("database-client", "oci.dll")]
    assert not client.resolved_in_input and client.confidence == "low"
    assert any(k == "runtime-library" and "OpenSSL" in n for k, n in found)


def test_fixture_hygiene(ent) -> None:
    found = _detect(ent.analysed, ent.text_of)
    assert all(f.kind in RUNTIME_KINDS for f in found)
    assert SECRET not in dump_all(found)
    assert not any(f.name.lower() == "kernel32.dll" for f in found)
    assert all(f.status in ("PARTIAL", "UNKNOWN") for f in found)


def test_fixture_deterministic_under_shuffle(ent) -> None:
    base = dump_all(_detect(ent.analysed, ent.text_of))
    for seed in (1, 2, 3):
        assert dump_all(_detect(ent.shuffled(seed), ent.text_of)) == base


# --------------------------------------------------------------------------
# libraries and native references
# --------------------------------------------------------------------------


def test_native_refs_kinds_and_system_dlls(tmp_path: Path) -> None:
    src = pas("a", "", (
        "function A: Integer; external 'oci.dll';\n"
        "function B: Integer; external 'kernel32.dll';\n"
        "function C: Integer; external 'libpq.so.5';\n"
        "const X = 'comctl32.ocx'; P = 'vendorui.bpl'; Q = 'mylib.dll';\n"))
    found = _run(tmp_path, {
        "a.pas": src, "bin/shipped.dll": b"MZ\x90\x00" + bytes(40)})
    assert ("database-client", "oci.dll") in found
    assert ("database-client", "libpq.so.5") in found
    assert ("com-component", "comctl32.ocx") in found
    assert ("bpl-package", "vendorui.bpl") in found
    assert ("dll", "mylib.dll") in found
    assert not any(n == "kernel32.dll" for _, n in found)
    shipped = found[("dll", "shipped.dll")]
    assert shipped.resolved_in_input and shipped.evidence[0].file == \
        "bin/shipped.dll"


def test_database_client_resolved_when_binary_ships(tmp_path: Path) -> None:
    src = pas("a", "FireDAC.Phys.Ora, FireDAC.Phys.PG, FireDAC.Comp.Client")
    found = _run(tmp_path, {
        "a.pas": src, "bin/LIBPQ.DLL": b"MZ\x90\x00" + bytes(40)})
    assert not found[("database-client", "oci.dll")].resolved_in_input
    assert found[("database-client", "libpq.dll")].resolved_in_input


def test_database_findings_imply_client_libraries(tmp_path: Path) -> None:
    src = pas("a", "sqldb, pqconnection", "var C: TPQConnection;")
    found = _run(tmp_path, {"a.pas": src})
    assert ("database-client", "libpq.dll") in found


def test_openssl_runtime_library_from_indy(tmp_path: Path) -> None:
    with_ssl = _run(tmp_path / "a", {"a.pas": pas("a", "IdHTTP, IdSSLOpenSSL")})
    assert any(k == "runtime-library" and "OpenSSL" in n
               for k, n in with_ssl)
    without = _run(tmp_path / "b", {"a.pas": pas("a", "IdHTTP")})
    assert not any(k == "runtime-library" for k, _ in without)


# --------------------------------------------------------------------------
# configuration files
# --------------------------------------------------------------------------


def test_config_files_named_in_calls(tmp_path: Path) -> None:
    body = (
        "procedure P;\nvar I: TIniFile; M: TMemIniFile;\nbegin\n"
        "  I := TIniFile.Create(ExtractFilePath(ParamStr(0)) + 'app.ini');\n"
        "  M := TMemIniFile.Create('Conf\\Settings.INI');\n"
        "  X := TIniFile.Create(ChangeFileExt(Application.ExeName, '.ini'));\n"
        "  Doc.LoadFromFile('conf\\settings.xml');\n"
        "  Doc.LoadFromFile('missing\\other.xml');\n"
        "  R.LoadFromFile('data.csv');\n"
        "end;\nconst Unrelated = 'notused.ini';")
    found = _run(tmp_path, {
        "a.pas": pas("a", "IniFiles, XMLDoc", body),
        "etc/app.ini": "[a]\nb=1\n",
        "Conf/Settings.ini": "[a]\n",
        "conf/settings.xml": "<c/>",
    })
    assert found[("configuration-file", "app.ini")].resolved_in_input
    assert found[("configuration-file", "Conf\\Settings.INI")] \
        .resolved_in_input
    assert found[("configuration-file", "conf\\settings.xml")] \
        .resolved_in_input
    assert not found[("configuration-file", "missing\\other.xml")] \
        .resolved_in_input
    assert ("data-file", "data.csv") in found
    assert not any(n in ("notused.ini", ".ini") for _, n in found)


# --------------------------------------------------------------------------
# registry, environment, COM, services, paths
# --------------------------------------------------------------------------


def test_registry_and_environment(tmp_path: Path) -> None:
    body = (
        "procedure P;\nbegin\n"
        "  R.OpenKey('\\Software\\Acme\\App', False);\n"
        "  R.OpenKeyReadOnly('SOFTWARE\\Acme\\Other');\n"
        "  K := 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Vendor\\Thing';\n"
        "  A := GetEnvironmentVariable('APP_HOME');\n"
        "  B := ExpandEnvironmentStrings('%APPDATA%\\acme');\n"
        "  C := Format('%s items %d', [S, N]);\n"
        "  D := GetEnvironmentVariable(Name);\n"
        "end;")
    found = _run(tmp_path, {"a.pas": pas("a", "Registry", body)})
    assert ("registry-key", "Software\\Acme\\App") in found
    assert ("registry-key", "SOFTWARE\\Acme\\Other") in found
    assert ("registry-key", "HKEY_LOCAL_MACHINE\\SOFTWARE\\Vendor\\Thing") \
        in found
    assert ("environment-variable", "APP_HOME") in found
    assert ("environment-variable", "APPDATA") in found
    assert not any(k == "environment-variable" and n in ("s", "d", "S", "D")
                   for k, n in found)
    assert sum(1 for k, _ in found if k == "environment-variable") == 2


def test_com_components_and_services(tmp_path: Path) -> None:
    body = (
        "type TSvc = class(TService) end;\n"
        "procedure P;\nbegin\n"
        "  A := CreateOleObject('Excel.Application');\n"
        "  B := CreateComObject(StringToGUID("
        "'{00024500-0000-0000-C000-000000000046}'));\n"
        "  C := CreateOleObject(ProgId);\n"
        "  D := CreateOleObject('NoDotsHere');\n"
        "end;")
    found = _run(tmp_path, {
        "a.pas": pas("a", "SvcMgr, ComObj", body),
        "install.bat": "sc create ErpSvc binPath= C:\\erp\\svc.exe\n"
                       "nssm install OtherSvc app.exe\nnet start ErpSvc\n",
    })
    assert ("com-component", "Excel.Application") in found
    assert ("com-component", "{00024500-0000-0000-C000-000000000046}") in found
    assert not any(n in ("NoDotsHere", "ProgId") for _, n in found)
    assert ("service", "TSvc") in found
    assert ("service", "ErpSvc") in found
    assert ("service", "OtherSvc") in found


def test_hardcoded_paths(tmp_path: Path) -> None:
    body = (
        "const\n"
        "  A = 'C:\\Data\\export\\out.csv';\n"
        "  B = '\\\\fileserver\\share\\inbox';\n"
        "  C = '/usr/local/app/conf';\n"
        "  D = 'https://host.example.com/usr/local/x';\n"
        "  E = 'relative\\dir\\file.txt';\n"
        "  F = 'c:';\n"
        "  G = 'The drive d: is full';\n"
        "// H = 'C:\\Comment\\only';\n")
    found = _run(tmp_path, {
        "a.pas": pas("a", "", body),
        "form.dfm": "object F: TF\n  DatabaseName = 'D:\\db\\main.mdb'\nend\n",
        "app.ini": "[p]\nroot=E:\\apps\\erp\nname=plain\n",
    })
    names = {n for k, n in found if k == "hardcoded-path"}
    assert names == {"C:\\Data\\export\\out.csv", "\\\\fileserver\\share\\inbox",
                     "/usr/local/app/conf", "D:\\db\\main.mdb",
                     "E:\\apps\\erp"}
    assert found[("hardcoded-path", "D:\\db\\main.mdb")].required_by == (
        "form.dfm",)


def test_names_in_comments_do_not_trigger(tmp_path: Path) -> None:
    src = ("unit a;\ninterface\nimplementation\n"
           "// X := TIniFile.Create('c.ini'); OpenKey('Software\\X');\n"
           "{ GetEnvironmentVariable('HIDDEN') CreateOleObject('A.B') }\n"
           "end.\n")
    assert _run(tmp_path, {"a.pas": src}) == {}


def test_secrets_are_never_emitted(tmp_path: Path) -> None:
    body = (
        "const\n"
        f"  A = 'Server=C:\\db\\x.fdb;Password={SECRET}';\n"
        f"  B = 'HKEY_CURRENT_USER\\Software\\X;Password={SECRET}';\n")
    found = _detect_files(tmp_path, {"a.pas": pas("a", "", body),
                                     "s.ini": f"[a]\nPassword={SECRET}\n"
                                              "path=C:\\data\\x\n"})
    assert SECRET not in dump_all(found)


def _detect_files(tmp_path: Path, files: dict) -> list:
    estate = analyse(tmp_path / "t", files)
    return _detect(estate.analysed, estate.text_of)


# --------------------------------------------------------------------------
# adversarial
# --------------------------------------------------------------------------


def test_ten_thousand_identical_references_stay_bounded(
        tmp_path: Path) -> None:
    body = ("procedure P; begin\n"
            + "  LoadLibrary('x.dll'); GetEnvironmentVariable('E1');\n" * 10_000
            + "end;\nfunction F: Integer; external 'x.dll';\n")
    found = _run(tmp_path, {"a.pas": pas("a", "", body)})
    dll = found[("dll", "x.dll")]
    assert len(dll.evidence) <= 25 and dll.required_by == ("a.pas",)
    assert len(found[("environment-variable", "E1")].evidence) <= 25


def test_many_distinct_paths_are_capped(tmp_path: Path) -> None:
    consts = "\n".join(f"  P{i} = 'C:\\data\\f{i:05d}.dat';"
                       for i in range(800))
    found = _detect_files(tmp_path, {"a.pas": pas("a", "", f"const\n{consts}")})
    assert sum(1 for f in found if f.kind == "hardcoded-path") == 500


def test_garbage_and_unterminated_inputs(tmp_path: Path) -> None:
    found = _run(tmp_path, {
        "bin.pas": bytes(range(256)) * 400,
        "open.pas": "unit o;\ninterface\nimplementation\n"
                    "const S = 'C:\\never\\closed\nT = GetEnvironmentVariable('",
        "big.ini": "x=" + "y" * 3_000_000 + "\nroot=C:\\after\\big\n",
    })
    assert isinstance(found, dict)


def test_shuffle_determinism_synthetic(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {
        f"u{i}.pas": pas(f"u{i}", "IniFiles", (
            f"var I: TIniFile;\nbegin I := TIniFile.Create('c{i}.ini');"
            f" X := GetEnvironmentVariable('V{i}'); end;"))
        for i in range(10)
    })
    base = dump_all(_detect(estate.analysed, estate.text_of))
    for seed in (1, 2, 3):
        assert dump_all(_detect(estate.shuffled(seed), estate.text_of)) == base


def test_pathological_lines_stay_fast(tmp_path: Path) -> None:
    import time

    nasty = ("a-" * 1000 + "\n") * 1500
    estate = analyse(tmp_path / "t", {"z.ini": nasty, "q.cfg": nasty})
    started = time.perf_counter()
    _detect(estate.analysed, estate.text_of)
    assert time.perf_counter() - started < 15


def test_password_appears_nowhere_in_any_detector_output(ent) -> None:
    from p1.inventory import (
        detect_build_scripts,
        detect_compiler_configs,
        list_directories,
    )

    all_findings = [
        detect_build_scripts(ent.analysed, ent.text_of, []),
        detect_compiler_configs(ent.analysed, ent.text_of),
        detect_integrations(ent.analysed, ent.text_of),
        detect_libraries(ent.analysed, [], [], text_of=ent.text_of),
        _detect(ent.analysed, ent.text_of),
        list_directories(ent.root, ent.files),
    ]
    dumped = dump_all(*all_findings)
    assert SECRET not in dumped
    assert "S3cr3t" not in dumped
    assert str(ent.root) not in dumped
    assert "erp_app" not in dumped  # the connection-string user name too
