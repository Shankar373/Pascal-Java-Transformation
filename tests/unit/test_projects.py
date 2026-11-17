"""Unit tests for project-root detection, profiles and shape (tasks B3, C1).

The theme is *refusing to guess*: an ambiguous layout reports ``UNKNOWN``,
a project file with no entry-point source reports ``UNKNOWN``, and a shape
derived from the absence of GUI evidence is only ever ``PARTIAL``.
"""

from __future__ import annotations

from p1.dialects import analyse_source
from p1.limits import DEFAULT_LIMITS
from p1.plex import scan as scan_source
from p1.projects import (
    META_EXTENSIONS,
    PACKAGE_EXTENSIONS,
    PROGRAM_EXTENSIONS,
    SHAPES,
    Profile,
    ProjectRoot,
    apply_source_profile,
    detect_shape,
    entry_point,
    find_project_roots,
    parse_project_file,
)

# ---------------------------------------------------------------------------
# Root detection
# ---------------------------------------------------------------------------


def test_single_program_with_sibling_project_file_is_primary() -> None:
    roots, diagnostics = find_project_roots([
        "src/MiniApp.dpr",
        "src/MiniApp.dproj",
        "src/uMath.pas",
        "README.md",
    ])

    assert diagnostics == []
    assert len(roots) == 1
    root = roots[0]
    assert root.path == "src/MiniApp.dpr"
    assert root.kind == "program"
    assert root.primary is True
    assert root.status == "SUPPORTED"
    assert root.meta_files == ["src/MiniApp.dproj"]
    assert root.diagnostics == []


def test_sibling_metadata_is_matched_by_stem_not_by_directory() -> None:
    roots, _ = find_project_roots([
        "alpha/Alpha.lpr",
        "other/Alpha.lpi",
        "beta/Beta.lpr",
    ])

    by_path = {r.path: r for r in roots}
    assert by_path["alpha/Alpha.lpr"].meta_files == ["other/Alpha.lpi"]
    assert by_path["beta/Beta.lpr"].meta_files == []


def test_package_root_is_recognised() -> None:
    roots, _ = find_project_roots(["src/Pkg.dpk", "src/Pkg.dproj"])
    assert roots[0].kind == "package"


def test_root_evidence_names_the_file_it_came_from() -> None:
    roots, _ = find_project_roots(["src/MiniApp.dpr", "src/MiniApp.dproj"])
    evidence = roots[0].evidence
    assert evidence[0] == {
        "evidence": "entry-point file (.dpr)",
        "source": "MiniApp.dpr",
    }
    assert evidence[1] == {
        "evidence": "project metadata .dproj",
        "source": "MiniApp.dproj",
    }


def test_project_file_without_a_source_is_unknown_not_guessed() -> None:
    roots, diagnostics = find_project_roots(["conf/Solo.dproj"])

    assert len(roots) == 1
    root = roots[0]
    assert root.kind == "unknown"
    assert root.status == "UNKNOWN"
    assert root.entry_point == ""
    assert [d["code"] for d in root.diagnostics] == [
        "PROJECT_ENTRY_POINT_MISSING"
    ]
    assert diagnostics == []


def test_two_roots_with_project_files_are_ambiguous() -> None:
    roots, diagnostics = find_project_roots([
        "alpha/Alpha.dpr",
        "alpha/Alpha.dproj",
        "beta/Beta.lpr",
        "beta/Beta.lpi",
    ])

    assert [d["code"] for d in diagnostics] == ["MULTIPLE_PROJECT_ROOTS"]
    assert len(roots) == 2
    for root in roots:
        assert root.status == "UNKNOWN"
        assert root.primary is False


def test_one_project_file_naming_a_primary_resolves_the_ambiguity() -> None:
    roots, diagnostics = find_project_roots([
        "alpha/Alpha.dpr",
        "alpha/Alpha.dproj",
        "beta/Beta.lpr",
    ])

    assert diagnostics == []
    by_path = {r.path: r for r in roots}
    assert by_path["alpha/Alpha.dpr"].primary is True
    assert by_path["beta/Beta.lpr"].primary is False


def test_no_project_files_at_all_yields_no_roots() -> None:
    roots, diagnostics = find_project_roots(["src/uMath.pas", "README.md"])
    assert roots == []
    assert diagnostics == []


def test_empty_inventory_yields_no_roots() -> None:
    assert find_project_roots([]) == ([], [])


def test_extension_constants_are_the_documented_sets() -> None:
    assert PROGRAM_EXTENSIONS == (".dpr", ".lpr")
    assert PACKAGE_EXTENSIONS == (".dpk", ".lpk")
    assert META_EXTENSIONS == (".dproj", ".lpi", ".bdsproj", ".groupproj")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _entry(text: str, path: str) -> dict[str, object]:
    scan = scan_source(text, path=path, limits=DEFAULT_LIMITS)
    analysis = analyse_source(scan, path)
    root = ProjectRoot(path=path, kind="program")
    return entry_point(root, scan, analysis)


def test_entry_point_carries_a_source_location() -> None:
    out = _entry("program MiniApp;\nbegin\nend.\n", "src/MiniApp.dpr")
    assert out["declared_name"] == "MiniApp"
    assert out["status"] == "SUPPORTED"
    assert out["source"] == "src/MiniApp.dpr"
    assert out["location"] == "src/MiniApp.dpr:1:9"


def test_entry_point_without_a_declaration_is_partial() -> None:
    root = ProjectRoot(path="src/MiniApp.dpr", kind="program")
    out = entry_point(root, None, None)
    assert out["status"] == "PARTIAL"
    assert out["declared_name"] == ""
    assert out["location"] == ""


def test_entry_point_of_an_unknown_root_is_unknown() -> None:
    root = ProjectRoot(path="conf/Solo.dproj", kind="unknown")
    out = entry_point(root, None, None)
    assert out["status"] == "UNKNOWN"


def test_entry_point_status_vocabulary_is_closed() -> None:
    assert _entry("program A;\nbegin\nend.\n", "a.dpr")["status"] in (
        "SUPPORTED", "PARTIAL", "UNKNOWN"
    )


# ---------------------------------------------------------------------------
# Shape detection
# ---------------------------------------------------------------------------


def _shape(text: str, path: str, profile: Profile | None = None):
    scan = scan_source(text, path=path, limits=DEFAULT_LIMITS)
    analysis = analyse_source(scan, path)
    root = ProjectRoot(path=path, kind="program")
    detect_shape(root, scan, analysis, profile or Profile())
    return root


def test_apptype_console_is_high_confidence() -> None:
    root = _shape(
        "program MiniApp;\n{$APPTYPE CONSOLE}\nbegin\nend.\n",
        "src/MiniApp.dpr",
    )
    assert root.shape == "console"
    assert root.shape_confidence == "high"
    assert root.shape_status == "SUPPORTED"
    assert any("APPTYPE CONSOLE" in str(e["evidence"])
               for e in root.shape_evidence)


def test_project_app_type_is_only_medium_confidence() -> None:
    profile = Profile(app_type="console")
    root = _shape(
        "program MiniApp;\nbegin\nend.\n",
        "src/MiniApp.dpr",
        profile,
    )
    assert root.shape == "console"
    assert root.shape_confidence == "medium"
    assert root.shape_status == "PARTIAL"


def test_library_source_is_a_library_shape() -> None:
    root = _shape(
        "library MyLib;\nbegin\nend.\n",
        "src/MyLib.dpr",
    )
    assert root.shape == "library"
    assert root.shape_confidence == "high"
    assert root.shape_status == "SUPPORTED"


def test_package_source_is_a_package_shape() -> None:
    root = _shape("package Pkg;\nbegin\nend.\n", "src/Pkg.dpk")
    assert root.shape == "package"
    assert root.shape_confidence == "high"


def test_lcl_units_produce_a_gui_lcl_shape() -> None:
    root = _shape(
        "program App;\nuses Interfaces, LCLIntf;\nbegin\nend.\n",
        "lcl/App.lpr",
    )
    assert root.shape == "gui_lcl"
    assert root.shape_confidence == "high"
    assert root.shape_status == "SUPPORTED"


def test_vcl_units_produce_a_gui_vcl_shape() -> None:
    root = _shape(
        "program App;\nuses Forms, Controls, Graphics;\nbegin\nend.\n",
        "vcl/App.dpr",
    )
    assert root.shape == "gui_vcl"
    assert root.shape_confidence == "high"


def test_service_units_produce_a_service_shape() -> None:
    root = _shape(
        "program Svc;\nuses SvcManager;\nbegin\nend.\n",
        "src/Svc.dpr",
    )
    assert root.shape == "service"
    assert root.shape_confidence == "medium"
    assert root.shape_status == "PARTIAL"


def test_program_without_gui_evidence_is_console_but_not_certain() -> None:
    """Absence of a GUI signal is not proof of a console application."""

    root = _shape("program Plain;\nbegin\nend.\n", "src/Plain.dpr")
    assert root.shape == "console"
    assert root.shape_confidence == "medium"
    assert root.shape_status == "PARTIAL"


def test_no_evidence_at_all_is_unknown() -> None:
    root = ProjectRoot(path="conf/Solo.dproj", kind="unknown")
    detect_shape(root, None, None, Profile())
    assert root.shape == "unknown"
    assert root.shape_confidence == "low"
    assert root.shape_status == "UNKNOWN"
    assert root.shape_evidence == []


def test_shape_vocabulary_is_closed() -> None:
    for shape in ("console", "gui_vcl", "gui_lcl", "gui_fmx", "service",
                  "library", "package", "unknown"):
        assert shape in SHAPES


# ---------------------------------------------------------------------------
# Project file parsing
# ---------------------------------------------------------------------------

DPROJ = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">\n'
    "  <PropertyGroup>\n"
    "    <MainSource>MiniApp.dpr</MainSource>\n"
    "    <AppType>Console</AppType>\n"
    "    <Platform>Win32</Platform>\n"
    "    <DCC_Define>DEBUG;CONDITIONALEXPRESSIONS</DCC_Define>\n"
    "    <DCC_UnitSearchPath>src;lib</DCC_UnitSearchPath>\n"
    "    <DCC_ExeOutput>.\\Win32\\Debug</DCC_ExeOutput>\n"
    "  </PropertyGroup>\n"
    "</Project>\n"
)

LPI = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<CONFIG>\n"
    "  <ProjectOptions>\n"
    "    <CompilerOptions>\n"
    "      <Parsing><SyntaxMode Value=\"ObjFPC\"/></Parsing>\n"
    "      <SearchPaths><OtherUnitFiles Value=\"src;lib\"/></SearchPaths>\n"
    "      <Other><CustomOptions Value=\"-dDEBUG -uSTALE\"/></Other>\n"
    "    </CompilerOptions>\n"
    "    <Linking><Options><Win32>"
    "<GraphicApplication Value=\"True\"/></Win32></Options></Linking>\n"
    "    <Target><Filename Value=\"app.exe\"/></Target>\n"
    "  </ProjectOptions>\n"
    "</CONFIG>\n"
)


def test_dproj_profile() -> None:
    profile, diagnostics = parse_project_file("src/MiniApp.dproj", DPROJ)
    assert diagnostics == []
    assert profile.app_type == "console"
    assert profile.platform == "Win32"
    assert profile.defines == ["CONDITIONALEXPRESSIONS", "DEBUG"]
    assert profile.unit_search_paths == ["lib", "src"]
    assert profile.output_kind == "executable"
    assert profile.sources == ["src/MiniApp.dproj"]
    assert profile.mode == "not-specified"


def test_dproj_evidence_names_the_xml_tag() -> None:
    profile, _ = parse_project_file("src/MiniApp.dproj", DPROJ)
    app_type = [e for e in profile.evidence if e.get("field", "") == ""
                and str(e["evidence"]).startswith("app_type=")]
    assert app_type
    assert app_type[0]["source"] == "MiniApp.dproj"
    assert app_type[0]["xml_tag"] == "PropertyGroup/AppType"


def test_lpi_profile() -> None:
    profile, diagnostics = parse_project_file("src/App.lpi", LPI)
    assert diagnostics == []
    assert profile.mode == "objfpc"
    assert profile.unit_search_paths == ["lib", "src"]
    assert profile.defines == ["DEBUG"]
    assert profile.app_type == "gui"
    assert profile.output_kind == "executable"


def test_lpi_undef_removes_a_define() -> None:
    text = LPI.replace("-dDEBUG -uSTALE", "-dDEBUG -dSTALE -uSTALE")
    profile, _ = parse_project_file("src/App.lpi", text)
    assert profile.defines == ["DEBUG"]


def test_empty_project_file_is_a_visible_degraded_discovery() -> None:
    profile, diagnostics = parse_project_file("src/App.dproj", "   \n")
    assert [d["code"] for d in diagnostics] == ["PROJECT_FILE_EMPTY"]
    assert profile.sources == []
    assert profile.mode == "not-specified"


def test_malformed_project_file_never_raises() -> None:
    profile, diagnostics = parse_project_file(
        "src/App.dproj", "<Project><PropertyGroup></Project>"
    )
    assert [d["code"] for d in diagnostics] == ["PROJECT_FILE_UNPARSEABLE"]
    assert diagnostics[0]["line"] >= 1
    assert diagnostics[0]["column"] >= 1
    assert profile.sources == []


def test_profile_serialises_with_a_stable_key_set() -> None:
    keys = set(Profile().as_dict())
    assert keys == {
        "app_type", "defines", "evidence", "mode", "output_kind",
        "overflow_check", "platform", "range_check", "sources",
        "string_model", "unit_search_paths",
    }


def test_unset_profile_fields_say_not_specified_not_unknown() -> None:
    """'not specified' and 'could not be determined' are different claims."""

    profile = Profile()
    assert profile.mode == "not-specified"
    assert profile.platform == "not-specified"
    assert profile.range_check == "not-specified"
    assert profile.overflow_check == "not-specified"
    assert profile.string_model == "not-specified"
    assert profile.app_type == "not-specified"
    assert profile.output_kind == "not-specified"


# ---------------------------------------------------------------------------
# Source-directive overlay
# ---------------------------------------------------------------------------


def _overlay(text: str, path: str, profile: Profile | None = None) -> Profile:
    profile = profile or Profile()
    scan = scan_source(text, path=path, limits=DEFAULT_LIMITS)
    analysis = analyse_source(scan, path)
    apply_source_profile(profile, scan, analysis, path)
    return profile


def test_source_directives_fill_an_unspecified_profile() -> None:
    profile = _overlay(
        "unit uMath;\n"
        "{$MODE OBJFPC}\n"
        "{$DEFINE VERBOSE}\n"
        "{$R +}\n"
        "{$Q -}\n"
        "{$H+}\n"
        "{$APPTYPE CONSOLE}\n"
        "{$IFDEF MSWINDOWS}\n"
        "interface\nimplementation\nend.\n",
        "src/uMath.pas",
    )
    assert profile.mode == "objfpc"
    assert "VERBOSE" in profile.defines
    assert profile.range_check == "on"
    assert profile.overflow_check == "off"
    assert profile.string_model == "long"
    assert profile.app_type == "console"
    assert profile.platform == "windows"
    assert "src/uMath.pas" in profile.sources


def test_every_overlay_change_is_evidenced() -> None:
    profile = _overlay(
        "unit uMath;\n{$MODE OBJFPC}\n{$R +}\ninterface\nend.\n",
        "src/uMath.pas",
    )
    fields = {e["field"] for e in profile.evidence}
    assert {"mode", "range_check"} <= fields
    for entry in profile.evidence:
        assert entry["source"] == "uMath.pas"
        assert entry["value"]
        assert entry["evidence"]


def test_project_file_state_is_not_silently_overwritten() -> None:
    """The project file states the build's intent; a directive in one unit
    must not retroactively rewrite it for the whole build."""

    profile = Profile(mode="delphi", platform="win32")
    _overlay(
        "unit uMath;\n{$MODE OBJFPC}\n{$IFDEF LINUX}\ninterface\nend.\n",
        "src/uMath.pas",
        profile,
    )
    assert profile.mode == "delphi"
    assert profile.platform == "win32"
    assert not any(e.get("field") == "mode" for e in profile.evidence)


def test_undef_removes_a_project_define() -> None:
    profile = Profile(defines=["DEBUG", "VERBOSE"])
    _overlay(
        "unit uMath;\n{$UNDEF DEBUG}\ninterface\nend.\n",
        "src/uMath.pas",
        profile,
    )
    assert profile.defines == ["VERBOSE"]


def test_define_is_not_duplicated() -> None:
    profile = Profile(defines=["VERBOSE"])
    _overlay(
        "unit uMath;\n{$DEFINE VERBOSE}\ninterface\nend.\n",
        "src/uMath.pas",
        profile,
    )
    assert profile.defines == ["VERBOSE"]


def test_output_kind_follows_the_declared_source_kind() -> None:
    profile = _overlay("library L;\nbegin\nend.\n", "src/L.dpr")
    assert profile.output_kind == "library"

    profile = _overlay("unit u;\ninterface\nend.\n", "src/u.pas")
    assert profile.output_kind == "not-specified"


def test_modeswitch_is_evidence_not_a_mode() -> None:
    profile = _overlay(
        "unit uMath;\n{$MODESWITCH TYPEHELPERS}\ninterface\nend.\n",
        "src/uMath.pas",
    )
    assert profile.mode == "not-specified"
    assert any(e["field"] == "modeswitch" for e in profile.evidence)


def test_overlay_without_a_scan_is_a_no_op() -> None:
    profile = Profile(mode="objfpc")
    apply_source_profile(profile, None, None, "src/uMath.pas")
    assert profile.mode == "objfpc"
    assert profile.evidence == []
    assert profile.sources == []
