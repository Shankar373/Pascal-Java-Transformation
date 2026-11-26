"""Unit tests for dialect, mode and unit-visibility knowledge (tasks C1-C3).

P0 proved these facts with compiler probes; P1's job is to carry them
forward *without* upgrading ``not probed`` into ``known``.  The tests below
therefore assert the tri-state vocabulary as hard as they assert the values.
"""

from __future__ import annotations

import pytest

from p1.dialects import (
    FLAG_TO_MODE,
    MODE_TABLE,
    UNIT_CATEGORIES,
    SourceAnalysis,
    analyse_source,
    classify_unit,
    visibility_for,
)
from p1.limits import DEFAULT_LIMITS
from p1.plex import scan as scan_source

# ---------------------------------------------------------------------------
# C1 — mode table
# ---------------------------------------------------------------------------

EXPECTED_MODES = (
    "fpc",
    "objfpc",
    "delphi",
    "tp",
    "iso",
    "macpas",
    "extendedsyntax",
    "objective-pascal",
)

TRI_STATE = {"SUPPORTED", "UNSUPPORTED", "UNKNOWN"}


def test_mode_table_is_the_expected_closed_set() -> None:
    assert tuple(MODE_TABLE) == EXPECTED_MODES


def test_every_mode_entry_is_self_consistent() -> None:
    for key, info in MODE_TABLE.items():
        assert info.name == key
        assert info.fpc_flag.startswith("-M")
        assert info.evidence, f"{key} has no evidence"
        assert set(info.as_dict()) == {
            "accepted_despite_missing_from_help",
            "bare_assignfile_visible",
            "evidence",
            "fpc_flag",
            "mode",
            "result_visible",
        }


@pytest.mark.parametrize(
    ("mode", "result_visible", "bare_assignfile_visible"),
    [
        ("fpc", False, False),
        ("objfpc", True, True),
        ("delphi", True, True),
        ("tp", False, None),
        ("iso", None, None),
        ("macpas", None, None),
        ("extendedsyntax", None, None),
        ("objective-pascal", True, True),
    ],
)
def test_probe_results_are_carried_forward_verbatim(
    mode: str, result_visible: bool | None,
    bare_assignfile_visible: bool | None,
) -> None:
    info = MODE_TABLE[mode]
    assert info.result_visible is result_visible
    assert info.bare_assignfile_visible is bare_assignfile_visible


def test_only_iso_is_accepted_despite_missing_from_help() -> None:
    flagged = [
        key for key, info in MODE_TABLE.items()
        if info.accepted_despite_missing_from_help
    ]
    assert flagged == ["iso"]
    assert MODE_TABLE["iso"].fpc_flag == "-Miso"


def test_unprobed_modes_say_so() -> None:
    for mode in ("macpas", "extendedsyntax"):
        info = MODE_TABLE[mode]
        assert info.result_visible is None
        assert info.bare_assignfile_visible is None
        assert "not probed in P0" in info.evidence


def test_iso_evidence_records_the_help_flag_discrepancy() -> None:
    assert "absent from -h" in MODE_TABLE["iso"].evidence


# ---------------------------------------------------------------------------
# C1 — flag round-trip
# ---------------------------------------------------------------------------


def test_flag_to_mode_covers_every_distinct_flag() -> None:
    assert set(FLAG_TO_MODE) == {
        info.fpc_flag.lower() for info in MODE_TABLE.values()
    }
    assert set(FLAG_TO_MODE.values()) <= set(MODE_TABLE)


@pytest.mark.parametrize(
    ("flag", "mode"),
    [
        ("-mfpc", "fpc"),
        ("-mobjfpc", "objfpc"),
        ("-mdelphi", "delphi"),
        ("-mtp", "tp"),
        ("-miso", "iso"),
        ("-mmacpas", "macpas"),
        ("-mex", "extendedsyntax"),
    ],
)
def test_flag_to_mode(flag: str, mode: str) -> None:
    assert FLAG_TO_MODE[flag] == mode


def test_shared_objfpc_flag_reads_back_as_the_canonical_mode() -> None:
    """``objective-pascal`` shares ``-Mobjfpc``; last-writer-wins would make
    a plain ``-Mobjfpc`` command line read back as the alias."""

    assert MODE_TABLE["objective-pascal"].fpc_flag == "-Mobjfpc"
    assert FLAG_TO_MODE["-mobjfpc"] == "objfpc"


def test_flag_to_mode_is_a_function_of_the_flag() -> None:
    for flag, name in FLAG_TO_MODE.items():
        assert name in MODE_TABLE
        assert MODE_TABLE[name].fpc_flag.lower() == flag


# ---------------------------------------------------------------------------
# C3 — visibility
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "result", "assignfile"),
    [
        ("objfpc", "SUPPORTED", "SUPPORTED"),
        ("delphi", "SUPPORTED", "SUPPORTED"),
        ("objective-pascal", "SUPPORTED", "SUPPORTED"),
        ("fpc", "UNSUPPORTED", "UNSUPPORTED"),
        ("tp", "UNSUPPORTED", "UNKNOWN"),
        ("iso", "UNKNOWN", "UNKNOWN"),
        ("macpas", "UNKNOWN", "UNKNOWN"),
        ("extendedsyntax", "UNKNOWN", "UNKNOWN"),
    ],
)
def test_visibility_is_tri_state(mode: str, result: str, assignfile: str) -> None:
    answer = visibility_for(mode)
    assert answer["mode"] == mode
    assert answer["result_visible"] == result
    assert answer["bare_assignfile_visible"] == assignfile
    assert answer["result_visible"] in TRI_STATE
    assert answer["bare_assignfile_visible"] in TRI_STATE


def test_unprobed_mode_is_unknown_not_guessed() -> None:
    answer = visibility_for("not-a-mode")
    assert answer["result_visible"] == "UNKNOWN"
    assert answer["bare_assignfile_visible"] == "UNKNOWN"
    assert answer["evidence"] == "mode not present in the P0 mode table"
    assert "fpc_flag" not in answer


def test_visibility_carries_the_assignfile_declaring_unit() -> None:
    assert visibility_for("objfpc")["assignfile_declaring_unit"] == "ObjPas"


def test_visibility_evidence_is_the_probe_record() -> None:
    assert visibility_for("objfpc")["evidence"] == MODE_TABLE["objfpc"].evidence


# ---------------------------------------------------------------------------
# C2 — unit classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("SysUtils", "cross-rtl"),
        ("Classes", "cross-rtl"),
        ("Math", "cross-rtl"),
        ("System.SysUtils", "delphi-rtl"),
        ("System.Classes", "delphi-rtl"),
        ("Crt", "fpc-rtl"),
        ("Dos", "fpc-rtl"),
        ("Windows", "windows-platform"),
        ("Winapi.SomeUnlistedThing", "windows-platform"),
        ("BaseUnix", "unix-platform"),
        ("Forms", "vcl"),
        ("Controls", "vcl"),
        ("Vcl.Dialogs", "vcl"),
        ("Interfaces", "lcl"),
        ("LCLIntf", "lcl"),
        ("Lcl.Something", "lcl"),
        ("FMX.Forms", "fmx"),
        ("Fmx.Whatever", "fmx"),
        ("DB", "database"),
        ("SqlExpr", "database"),
        ("DBTables", "database"),
        ("FireDAC.Comp.Client", "database"),
        ("Indy", "known-third-party"),
        ("IdHTTP", "known-third-party"),
    ],
)
def test_classify_unit_categories(name: str, category: str) -> None:
    matched_category, matched = classify_unit(name)
    assert matched_category == category
    assert matched, f"{name} produced no matched name"
    assert matched_category in UNIT_CATEGORIES


@pytest.mark.parametrize(
    "name",
    ["", "   ", "ZzzNotAUnit", "Foo.Bar", "Some.Unknown.Unit", "1234"],
)
def test_unknown_units_are_unresolved_not_third_party(name: str) -> None:
    """"Not in our table" is not evidence of anything."""

    category, matched = classify_unit(name)
    assert category == "unresolved"
    assert matched == ""
    assert category in UNIT_CATEGORIES


def test_classify_unit_is_case_and_space_insensitive() -> None:
    assert classify_unit("  sysutils  ") == classify_unit("SysUtils")


def test_qualified_and_bare_forms_are_both_recognised_as_rtl() -> None:
    """``System.SysUtils`` and ``SysUtils`` need not share a category, only
    the RTL reason they produce downstream (deps maps all three RTL
    categories onto ``rtl-unit``)."""

    rtl = {"cross-rtl", "delphi-rtl", "fpc-rtl"}
    assert classify_unit("System.SysUtils")[0] in rtl
    assert classify_unit("SysUtils")[0] in rtl
    assert classify_unit("Crt")[0] in rtl


# ---------------------------------------------------------------------------
# C3 — per-source analysis
# ---------------------------------------------------------------------------


def _analyse(text: str, path: str) -> SourceAnalysis:
    return analyse_source(scan_source(text, path=path, limits=DEFAULT_LIMITS),
                          path)


def test_unit_declaration_name_and_kind() -> None:
    analysis = _analyse(
        "unit uThing;\n\ninterface\n\nimplementation\n\nend.\n",
        "src/uThing.pas",
    )
    assert analysis.source_kind == "unit"
    assert analysis.declared_name == "uThing"
    assert analysis.name_mismatch is False
    assert analysis.diagnostics == []


def test_unit_name_mismatch_is_reported_not_repaired() -> None:
    analysis = _analyse(
        "unit uThing;\n\ninterface\n\nimplementation\n\nend.\n",
        "src/Other.pas",
    )
    assert analysis.name_mismatch is True
    codes = [d["code"] for d in analysis.diagnostics]
    assert codes == ["UNIT_NAME_MISMATCH"]
    assert analysis.diagnostics[0]["line"] == 1
    assert analysis.diagnostics[0]["column"] == 1


def test_program_declaration() -> None:
    analysis = _analyse(
        "program MiniApp;\n\nbegin\nend.\n",
        "src/MiniApp.dpr",
    )
    assert analysis.source_kind == "program"
    assert analysis.declared_name == "MiniApp"


def test_no_declaration_at_all_is_unknown() -> None:
    analysis = _analyse(
        "{ shared helpers }\nconst SHARED_VERSION = '1.0.0';\n",
        "shared.inc",
    )
    assert analysis.source_kind == "unknown"
    assert analysis.declared_name == ""
    assert analysis.confidence == "low"


def test_mode_directive_drives_mode_and_dialect() -> None:
    analysis = _analyse(
        "unit uMath;\n{$MODE OBJFPC}\ninterface\nimplementation\nend.\n",
        "src/uMath.pas",
    )
    assert analysis.mode == "objfpc"
    assert analysis.dialect == "fpc"
    assert analysis.confidence == "high"
    assert analysis.mode_evidence
    assert analysis.mode_evidence[0]["line"] == 2
    assert analysis.mode_evidence[0]["column"] == 1
    assert analysis.mode_evidence[0]["source"] == "source"
    assert analysis.dialect_evidence[0]["evidence"] == "{$MODE OBJFPC}"


@pytest.mark.parametrize(
    ("directive", "mode", "dialect"),
    [
        ("{$MODE DELPHI}", "delphi", "delphi"),
        ("{$MODE TP}", "tp", "turbo-pascal"),
        ("{$MODE ISO}", "iso", "iso-7185"),
        ("{$MODE OBJFPC}", "objfpc", "fpc"),
    ],
)
def test_mode_directive_mapping(directive: str, mode: str, dialect: str) -> None:
    analysis = _analyse(
        f"unit uThing;\n{directive}\ninterface\nimplementation\nend.\n",
        "src/uThing.pas",
    )
    assert analysis.mode == mode
    assert analysis.dialect == dialect


def test_unknown_mode_is_not_invented() -> None:
    analysis = _analyse(
        "unit uThing;\n{$MODE WAT}\ninterface\nimplementation\nend.\n",
        "src/uThing.pas",
    )
    assert analysis.mode == "unknown"
    assert analysis.dialect == "unknown"
    # The directive was still seen and recorded as evidence.
    assert analysis.mode_evidence
    assert analysis.directives["MODE"] == ["WAT"]


def test_extension_supplies_dialect_when_no_mode_directive() -> None:
    analysis = _analyse(
        "program Alpha;\nbegin\nend.\n",
        "alpha/Alpha.dpr",
    )
    assert analysis.dialect == "delphi"
    assert analysis.dialect_evidence
    assert analysis.dialect_evidence[0]["source"] == "extension"
    assert analysis.confidence == "high"


def test_mode_directive_outranks_the_extension() -> None:
    """A ``.dpr`` compiled in OBJFPC mode is FPC-flavoured, not Delphi."""

    analysis = _analyse(
        "program Alpha;\n{$MODE OBJFPC}\nbegin\nend.\n",
        "alpha/Alpha.dpr",
    )
    assert analysis.dialect == "fpc"
    assert analysis.dialect_evidence[0].get("line") == 2
    sources = [e["source"] for e in analysis.dialect_evidence]
    assert sources[0] == "source"


def test_framework_is_none_without_framework_units() -> None:
    analysis = _analyse(
        "unit uMath;\ninterface\nuses SysUtils;\nimplementation\nend.\n",
        "src/uMath.pas",
    )
    assert analysis.framework == "none"
    assert analysis.framework_evidence == []


def test_framework_is_detected_from_unit_references() -> None:
    analysis = _analyse(
        "unit uMainForm;\ninterface\nuses Classes, SysUtils, Forms;\n"
        "implementation\nend.\n",
        "src/uMainForm.pas",
    )
    assert analysis.framework == "vcl"
    assert analysis.framework_evidence
    assert analysis.framework_evidence[0]["source"] == "source"


def test_directives_are_recorded_by_name() -> None:
    analysis = _analyse(
        "unit uThing;\n{$MODE OBJFPC}\n{$DEFINE VERBOSE}\n{$R app.res}\n"
        "interface\nimplementation\nend.\n",
        "src/uThing.pas",
    )
    assert analysis.directives["MODE"] == ["OBJFPC"]
    assert analysis.directives["DEFINE"] == ["VERBOSE"]
    assert analysis.directives["R"] == ["app.res"]


def test_analysis_is_a_pure_function_of_the_scan() -> None:
    text = "unit uThing;\n{$MODE OBJFPC}\ninterface\nimplementation\nend.\n"
    path = "src/uThing.pas"
    first = _analyse(text, path)
    second = _analyse(text, path)
    assert first == second
    assert first.dialect == second.dialect
    assert first.mode == second.mode


def test_source_analysis_serialises_with_a_stable_key_set() -> None:
    keys = set(_analyse("unit u;\n", "src/u.pas").__dict__)
    assert keys == {
        "path", "declared_name", "source_kind", "dialect", "mode",
        "framework", "dialect_evidence", "mode_evidence", "framework_evidence",
        "confidence", "directives", "name_mismatch", "diagnostics",
    }
