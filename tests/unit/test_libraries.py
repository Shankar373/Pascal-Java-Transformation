"""Stage 1 library detector (`p1.integrations.detect_libraries`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from p1.findings import LIBRARY_CATEGORIES, LIBRARY_ORIGINS
from p1.integrations import detect_libraries
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


def _libs(estate, unresolved=()):
    found = detect_libraries(
        estate.analysed, [], list(unresolved), text_of=estate.text_of)
    assert_well_formed(found)
    return {f.name: f for f in found}


def _run(tmp_path: Path, files: dict, unresolved=()) -> dict:
    return _libs(analyse(tmp_path / "t", files), unresolved)


# --------------------------------------------------------------------------
# fixture application
# --------------------------------------------------------------------------


def test_fixture_external_libraries(ent) -> None:
    libs = _libs(ent)
    for name, category in (("FastReport", "reporting"),
                           ("DevExpress", "ui-components")):
        lib = libs[name]
        assert lib.origin == "external" and not lib.resolved
        assert lib.category == category
        assert lib.status == "PARTIAL" and lib.evidence
    assert set(libs["FastReport"].units) == {"frxclass", "frxdbset"}
    assert set(libs["DevExpress"].units) == {
        "cxgrid", "cxgriddbtableview", "dxbarmanager"}
    assert libs["FastReport"].referenced_by == ("src/uReports.pas",)


def test_fixture_bundled_jedi(ent) -> None:
    jedi = _libs(ent)["JEDI"]
    assert jedi.origin == "bundled" and jedi.resolved
    assert jedi.units == ("jvedit",)
    assert jedi.referenced_by == ("src/uGrids.pas",)
    assert jedi.vendor == "Project JEDI"
    assert jedi.evidence[0].file == "src/uGrids.pas"


def test_fixture_framework_rtl_database_and_indy(ent) -> None:
    libs = _libs(ent)
    assert libs["VCL"].origin == "framework"
    assert libs["VCL"].category == "framework"
    assert "forms" in libs["VCL"].units
    assert libs["RTL"].origin == "rtl" and libs["RTL"].category == "rtl"
    assert libs["FireDAC"].origin == "rtl"
    assert libs["FireDAC"].category == "database"
    assert libs["Indy"].origin == "external"
    assert {"idhttp", "idftp", "idsmtp"} <= set(libs["Indy"].units)
    assert not libs["VCL"].resolved and not libs["RTL"].resolved


def test_fixture_package_requires(ent) -> None:
    libs = _libs(ent)
    vendor = libs["vendorui"]
    assert vendor.origin == "unresolved" and not vendor.resolved
    assert vendor.referenced_by == ("packages/ErpCore.dpk",)
    assert vendor.evidence[0].file == "packages/ErpCore.dpk"
    assert "dbrtl" in libs["DB (TDataSet)"].units
    assert "rtl" in libs["RTL"].units and "vcl" in libs["VCL"].units


def test_fixture_vocabulary_secrets_and_sorting(ent) -> None:
    found = detect_libraries(ent.analysed, [], ["umissingvendor"])
    assert all(f.category in LIBRARY_CATEGORIES for f in found)
    assert all(f.origin in LIBRARY_ORIGINS for f in found)
    assert [f.name for f in found] == sorted(f.name for f in found)
    assert SECRET not in dump_all(found)
    # The project's own units are never reported as libraries.
    names = {f.name.lower() for f in found}
    assert not names & {"udatamodule", "mainform", "coreutils", "uconfig"}


def test_fixture_deterministic_under_shuffle(ent) -> None:
    base = dump_all(detect_libraries(ent.analysed, [], []))
    for seed in (1, 2, 3):
        assert dump_all(detect_libraries(ent.shuffled(seed), [], [])) == base


# --------------------------------------------------------------------------
# families
# --------------------------------------------------------------------------

_FAMILY_CASES = [
    ("cxGrid", "DevExpress"), ("dxBarManager", "DevExpress"),
    ("TmsFNCCloudBase", "TMS"), ("AdvGrid", "TMS"),
    ("JvEdit", "JEDI"), ("JclBase", "JCL"), ("RzPanel", "Raize"),
    ("IdHTTP", "Indy"), ("IdGlobal", "Indy"), ("blcksock", "Synapse"),
    ("OverbyteIcsHttpProt", "ICS"), ("ZConnection", "Zeos"),
    ("frxClass", "FastReport"), ("QuickRpt", "QuickReport"),
    ("QRCtrls", "QuickReport"), ("ppReport", "ReportBuilder"),
    ("RvClass", "Rave"), ("VirtualTrees", "VirtualTrees"),
    ("FastMM4", "FastMM"), ("FastMM5", "FastMM"),
    ("mormot.core.base", "mORMot"), ("SynCommons", "mORMot"),
    ("Spring.Collections", "Spring4D"), ("TestFramework", "DUnit"),
    ("DUnitX.TestFramework", "DUnitX"), ("DCPrijndael", "DCPcrypt"),
    ("uTPLb_Hash", "LockBox"), ("AbZipper", "Abbrevia"),
    ("ZLib", "ZLib"), ("ZipForge", "ZipForge"),
    ("SuperObject", "SuperObject"), ("uLkJSON", "uLkJSON"),
    ("System.JSON", "System.JSON"), ("synedit", "SynEdit"),
    ("FireDAC.Comp.Client", "FireDAC"), ("DBTables", "BDE"),
    ("ADODB", "ADO"), ("SqlExpr", "dbExpress"), ("IBDatabase", "IBX"),
    ("Uni", "UniDAC"), ("sqldb", "SQLdb"), ("DB", "DB (TDataSet)"),
    ("Vcl.Forms", "VCL"), ("Fmx.Forms", "FMX"),
    ("Windows", "Windows platform units"),
    ("System.SysUtils", "Delphi RTL"), ("SysUtils", "RTL"),
]


@pytest.mark.parametrize("unit,family", _FAMILY_CASES)
def test_known_unit_families(tmp_path: Path, unit: str, family: str) -> None:
    libs = _run(tmp_path, {"a.pas": pas("a", unit)})
    assert family in libs, (unit, sorted(libs))
    assert unit.lower() in libs[family].units


@pytest.mark.parametrize("unit", [
    "IdleHelper", "Identity", "AdvApi32", "DXTypes", "QRCodeGen",
    "JvmBridge", "SpringBoard", "Abstract", "Zoo", "ppm", "Cxx_helper",
])
def test_lookalike_units_are_not_libraries(tmp_path: Path, unit: str) -> None:
    libs = _run(tmp_path, {"a.pas": pas("a", unit)})
    known = {name for name, lib in libs.items() if lib.origin != "unresolved"}
    assert known == set(), (unit, known)
    assert unit in libs and libs[unit].origin == "unresolved"


def test_names_in_comments_and_strings_do_not_trigger(tmp_path: Path) -> None:
    src = (
        "unit a;\ninterface\nuses SysUtils;\nimplementation\n"
        "{ uses cxGrid, IdHTTP, frxClass; }\n// uses JvEdit;\n"
        "const S = 'uses cxGrid; frxClass';\nend.\n"
    )
    libs = _run(tmp_path, {"a.pas": src})
    assert set(libs) == {"RTL"}


# --------------------------------------------------------------------------
# origins
# --------------------------------------------------------------------------


def test_bundled_versus_external_origin(tmp_path: Path) -> None:
    files = {
        "app/a.pas": pas("a", "cxGrid, frxClass, Jv.Missing"),
        "vendor/dx/cxGrid.pas": pas("cxGrid", "SysUtils"),
    }
    libs = _run(tmp_path, files)
    assert libs["DevExpress"].origin == "bundled"
    assert libs["DevExpress"].resolved
    assert libs["FastReport"].origin == "external"


def test_user_units_present_in_input_are_not_libraries(tmp_path: Path) -> None:
    libs = _run(tmp_path, {
        "a.pas": pas("a", "uHelper, uGone"),
        "uHelper.pas": pas("uHelper"),
    }, unresolved=["ugone"])
    assert "uHelper" not in libs
    assert libs["uGone"].origin == "unresolved"
    assert libs["uGone"].category == "other"
    assert libs["uGone"].referenced_by == ("a.pas",)


def test_package_requires_variants(tmp_path: Path) -> None:
    dpk = ("package P;\n\nrequires\n  rtl270,\n  vcl,\n  cxLibraryRS23,\n"
           "  JvCoreD23R,\n  mystery,\n  FireDACCommon;\n\n"
           "contains\n  U in 'u.pas';\n\nend.\n")
    libs = _run(tmp_path, {"p/P.dpk": dpk})
    assert libs["RTL"].origin == "rtl"
    assert libs["VCL"].origin == "framework"
    assert libs["DevExpress"].origin == "external"
    assert libs["JEDI"].origin == "external"
    assert libs["FireDAC"].origin == "rtl"
    assert libs["mystery"].origin == "unresolved"
    assert libs["mystery"].evidence[0].line >= 1


def test_lcl_versus_vcl_framework_choice(tmp_path: Path) -> None:
    lcl = _run(tmp_path / "l", {
        "App.lpr": "program App;\nuses\n  Interfaces, Forms, Controls;\n"
                   "begin\nend.\n",
        "App.lpi": "<CONFIG/>",
    })
    assert "LCL" in lcl and "VCL" not in lcl
    vcl = _run(tmp_path / "v", {
        "App.dpr": "program App;\nuses\n  Forms, Controls;\nbegin\nend.\n",
    })
    assert "VCL" in vcl and "LCL" not in vcl


def test_lazarus_project_required_packages(tmp_path: Path) -> None:
    lpi = ('<CONFIG><ProjectOptions><RequiredPackages><Item>'
           '<PackageName Value="LCL"/></Item><Item>'
           '<PackageName Value="SynEdit"/></Item><Item>'
           '<PackageName Value="FCL"/></Item><Item>'
           '<PackageName Value="VendorPkg"/></Item>'
           "</RequiredPackages></ProjectOptions></CONFIG>")
    libs = _run(tmp_path, {"A.lpi": lpi})
    assert libs["LCL"].origin == "framework"
    assert libs["SynEdit"].origin == "external"
    assert libs["FPC RTL"].origin == "rtl"
    assert libs["VendorPkg"].origin == "unresolved"
    assert libs["VendorPkg"].evidence[0].file == "A.lpi"


# --------------------------------------------------------------------------
# adversarial
# --------------------------------------------------------------------------


def test_many_unresolved_units_are_capped(tmp_path: Path) -> None:
    units = ", ".join(f"uMissing{i:04d}" for i in range(700))
    libs = _run(tmp_path, {"a.pas": pas("a", units)})
    unresolved = [l for l in libs.values() if l.origin == "unresolved"]
    assert len(unresolved) == 500


def test_identical_references_and_evidence_cap(tmp_path: Path) -> None:
    files = {f"u{i}.pas": pas(f"u{i}", "cxGrid") for i in range(300)}
    libs = _run(tmp_path, files)
    lib = libs["DevExpress"]
    assert len(lib.evidence) == 25
    assert len(lib.referenced_by) <= 50
    assert lib.units == ("cxgrid",)


def test_garbage_and_truncated_sources(tmp_path: Path) -> None:
    libs = _run(tmp_path, {
        "bin.pas": bytes(range(256)) * 300,
        "open.pas": "unit open;\ninterface\nuses cxGrid, \n",
        "star.pas": "unit s; interface uses (* never closed",
    })
    assert "DevExpress" in libs


def test_shuffle_determinism_synthetic(tmp_path: Path) -> None:
    estate = analyse(tmp_path / "t", {
        f"u{i}.pas": pas(f"u{i}", "cxGrid, IdHTTP, uGone, Forms")
        for i in range(10)
    })
    base = dump_all(detect_libraries(estate.analysed, [], []))
    for seed in (4, 5, 6):
        assert dump_all(
            detect_libraries(estate.shuffled(seed), [], [])) == base
