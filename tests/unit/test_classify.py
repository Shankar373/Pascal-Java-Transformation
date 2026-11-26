"""Unit tests for deterministic file classification (task B2).

The contract under test:

* every class P1 can emit belongs to a closed vocabulary;
* the name tables (extension, exact file name) are authoritative for the
  files they cover, and content only ever *refines* them;
* content evidence can override a source-looking extension when the bytes
  contradict the name — an executable called ``evil.pas`` is reported as the
  executable it is;
* the fallbacks are explicit (``unknown`` / ``binary``) rather than a guess
  dressed up as a fact.
"""

from __future__ import annotations

import pytest

from p1.classify import (
    CLASS_VOCABULARY,
    INVENTORY_ONLY_CLASSES,
    PASCAL_SOURCE_CLASSES,
    classify,
    extension_of,
)
from p1.limits import DEFAULT_LIMITS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: Every path exercised by the vocabulary sweep.  Kept flat so a failure names
#: the exact input that produced an out-of-vocabulary class.
SAMPLE_PATHS: tuple[str, ...] = (
    "src/App.pas",
    "src/App.pp",
    "legacy/App.p",
    "src/shared.inc",
    "src/App.dpr",
    "src/App.lpr",
    "src/Pkg.dpk",
    "src/Pkg.lpk",
    "src/App.dproj",
    "src/App.lpi",
    "src/App.bdsproj",
    "src/App.groupproj",
    "forms/Main.dfm",
    "forms/Main.lfm",
    "forms/Main.xfm",
    "forms/Main.fmx",
    "res/app.res",
    "res/app.rc",
    "res/icon.ico",
    "res/logo.png",
    "conf/app.ini",
    "conf/app.xml",
    "conf/app.json",
    "conf/app.yaml",
    "db/orders.sql",
    "db/data.db",
    "db/data.sqlite",
    "db/data.mdb",
    "build/build.bat",
    "build/build.sh",
    "build/build.ps1",
    "Makefile",
    "LICENSE",
    "README.md",
    ".gitignore",
    "bin/App.exe",
    "bin/App.dll",
    "bin/App.dcu",
    "bin/App.ppu",
    "notes.txt",
    "mystery",
    "blob",
    "repo/.git/config",
    "docs/notes.rst",
)


def _classes(paths: tuple[str, ...] = SAMPLE_PATHS) -> list[tuple[str, str]]:
    return [(p, classify(p).cls) for p in paths]


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


def test_every_sample_class_is_in_the_closed_vocabulary() -> None:
    for path, cls in _classes():
        assert cls in CLASS_VOCABULARY, f"{path} -> {cls}"


def test_source_and_inventory_only_sets_are_disjoint_subsets() -> None:
    vocabulary = set(CLASS_VOCABULARY)
    assert set(PASCAL_SOURCE_CLASSES) <= vocabulary
    assert set(INVENTORY_ONLY_CLASSES) <= vocabulary
    assert not (set(PASCAL_SOURCE_CLASSES) & set(INVENTORY_ONLY_CLASSES))


def test_pascal_project_is_neither_source_nor_inventory_only() -> None:
    """Project files get their own analysis path (projects.parse_project_file).

    If this ever changes, the split above must be revisited rather than a
    class silently landing in neither bucket.
    """

    assert "pascal_project" not in PASCAL_SOURCE_CLASSES
    assert "pascal_project" not in INVENTORY_ONLY_CLASSES


# ---------------------------------------------------------------------------
# extension_of
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/App.pas", ".pas"),
        ("src/App.PAS", ".pas"),
        ("src/hidden.pas", ".pas"),
        ("Makefile", ""),
        (".gitignore", ""),          # dot-file: whole name is the signal
        ("dir.name/file", ""),
        ("no/extension/at/all", ""),
        ("trailing/", ""),
        ("a.b.c.pas", ".pas"),
    ],
)
def test_extension_of(path: str, expected: str) -> None:
    assert extension_of(path) == expected


# ---------------------------------------------------------------------------
# Extension table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/a.pas", "pascal_unit"),
        ("src/a.pp", "pascal_unit"),
        ("src/a.p", "pascal_unit"),
        ("src/a.inc", "pascal_include"),
        ("src/a.dpr", "pascal_program"),
        ("src/a.lpr", "pascal_program"),
        ("src/a.dpk", "pascal_package"),
        ("src/a.lpk", "pascal_package"),
        ("src/a.dproj", "pascal_project"),
        ("src/a.lpi", "pascal_project"),
        ("forms/a.dfm", "ui_definition"),
        ("forms/a.lfm", "ui_definition"),
        ("conf/a.ini", "configuration"),
        ("conf/a.xml", "configuration"),
        ("conf/a.json", "configuration"),
        ("db/a.sql", "sql"),
        ("db/a.sqlite", "database"),
        ("build/a.sh", "build_script"),
        ("build/a.ps1", "build_script"),
        ("build/a.bat", "build_script"),
        ("doc/a.md", "documentation"),
        ("doc/a.txt", "documentation"),
        ("bin/a.exe", "binary"),
        ("bin/a.dll", "binary"),
        ("bin/a.dcu", "binary"),
        ("bin/a.ppu", "binary"),
        ("res/a.res", "resource"),
        ("res/a.rc", "resource"),
    ],
)
def test_extension_table(path: str, expected: str) -> None:
    result = classify(path)
    assert result.cls == expected
    assert "extension" in result.evidence
    assert result.confidence == "high"
    assert result.discovery_only is True
    assert result.analysis_blocker == ""


def test_extension_match_does_not_read_the_content() -> None:
    """An extension hit is decided before any content is sniffed."""

    result = classify("doc/a.md", head=b"\x00\x01\x02\x03")
    assert result.cls == "documentation"
    assert result.evidence == ("extension",)


# ---------------------------------------------------------------------------
# Exact file names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("Makefile", "build_script"),
        ("makefile", "build_script"),
        ("GNUmakefile", "build_script"),
        ("Dockerfile", "build_script"),
        ("LICENSE", "licence"),
        ("LICENCE", "licence"),
        ("COPYING", "licence"),
        ("NOTICE", "licence"),
        ("README", "documentation"),
        ("CHANGELOG", "documentation"),
        ("AUTHORS", "documentation"),
        (".gitignore", "version_control"),
        (".gitattributes", "version_control"),
        (".gitmodules", "version_control"),
        (".hgignore", "version_control"),
        (".editorconfig", "configuration"),
        ("sub/dir/Makefile", "build_script"),
    ],
)
def test_file_name_table(path: str, expected: str) -> None:
    result = classify(path)
    assert result.cls == expected
    assert result.evidence == ("file-name",)
    assert result.confidence == "high"


def test_file_name_beats_extension() -> None:
    """A dot-file's whole name is the signal, so it has no extension."""

    result = classify(".gitignore")
    assert extension_of(".gitignore") == ""
    assert result.cls == "version_control"


# ---------------------------------------------------------------------------
# Magic bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "head", "expected", "evidence"),
    [
        ("src/App.pas", b"MZ\x90\x00", "binary",
         ("magic", "extension-override")),
        ("src/App.dpr", b"MZ\x90\x00", "binary",
         ("magic", "extension-override")),
        ("src/App.inc", b"\x7fELF\x02\x01", "binary",
         ("magic", "extension-override")),
        ("blob", b"MZ\x90\x00rest", "binary", ("magic",)),
        ("blob", b"\x7fELF\x02\x01rest", "binary", ("magic",)),
        ("picture", b"\x89PNG\r\n\x1a\n", "resource", ("magic",)),
        ("picture", b"GIF89a", "resource", ("magic",)),
        ("doc", b"%PDF-1.7", "binary", ("magic",)),
        ("pack", b"PK\x03\x04", "binary", ("magic",)),
    ],
)
def test_magic_bytes(
    path: str, head: bytes, expected: str, evidence: tuple[str, ...]
) -> None:
    result = classify(path, head)
    assert result.cls == expected
    assert result.evidence == evidence
    assert result.confidence == "high"
    assert result.discovery_only is True


def test_executable_named_like_source_is_reported_as_executable() -> None:
    """Reporting ``evil.pas`` as Pascal source would be a silent lie."""

    result = classify("src/evil.pas", b"MZ\x90\x00\x03\x00")
    assert result.cls == "binary"
    assert "extension-override" in result.evidence
    assert "extension" not in result.evidence


def test_png_magic_does_not_override_a_png_extension() -> None:
    """The override exists only where magic *contradicts* the name."""

    result = classify("res/logo.png", b"\x89PNG\r\n\x1a\n")
    assert result.cls == "resource"
    assert result.evidence == ("extension",)


# ---------------------------------------------------------------------------
# Content sniffing (no usable extension)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "head", "expected", "evidence"),
    [
        ("script", b"select * from orders;\n", "sql",
         ("content-keyword:select",)),
        ("script", b"INSERT INTO t VALUES (1);\n", "sql",
         ("content-keyword:insert",)),
        ("main", b"program Foo;\nbegin\nend.\n", "pascal_program",
         ("content-keyword",)),
        ("main", b"library Foo;\nbegin\nend.\n", "pascal_program",
         ("content-keyword",)),
        ("unit", b"unit uThing;\ninterface\nend.\n", "pascal_unit",
         ("content-keyword",)),
        ("cfg", b"<?xml version='1.0'?>\n<Project/>\n", "configuration",
         ("content-keyword:<?xml",)),
        ("main", b"// leading comment\nprogram Foo;\nbegin\nend.\n",
         "pascal_program", ("content-keyword",)),
        ("main", b"{ directive }\nprogram Foo;\nbegin\nend.\n",
         "pascal_program", ("content-keyword",)),
        ("main", b"(* comment *)\nprogram Foo;\nbegin\nend.\n",
         "pascal_program", ("content-keyword",)),
    ],
)
def test_content_sniff(
    path: str, head: bytes, expected: str, evidence: tuple[str, ...]
) -> None:
    result = classify(path, head)
    assert result.cls == expected
    assert result.evidence == evidence
    assert result.confidence == "medium"


def test_program_header_is_not_a_unit() -> None:
    result = classify("main", b"program Foo;\nbegin\nend.\n")
    assert result.cls == "pascal_program"
    # A content-only program is a candidate, not a fact: it has no extension
    # to corroborate it, so discovery_only stays False (it will be parsed).
    assert result.discovery_only is False


def test_content_only_unit_is_parsed_not_just_inventoried() -> None:
    result = classify("unit", b"unit uThing;\ninterface\nend.\n")
    assert result.discovery_only is False


# ---------------------------------------------------------------------------
# The ambiguous ``.p`` extension
# ---------------------------------------------------------------------------


def test_dot_p_with_pascal_content_stays_pascal() -> None:
    result = classify("legacy/old.p", b"unit old;\ninterface\nend.\n")
    assert result.cls == "pascal_unit"
    assert result.evidence == ("extension",)
    assert result.confidence == "high"


def test_dot_p_with_sql_content_is_sniffed_as_sql() -> None:
    result = classify("legacy/query.p", b"select * from t;\n")
    assert result.cls == "sql"
    assert result.evidence == ("extension", "content-keyword")
    assert result.confidence == "medium"
    assert result.discovery_only is True


def test_dot_p_with_no_content_keeps_the_table_answer() -> None:
    result = classify("legacy/old.p")
    assert result.cls == "pascal_unit"
    assert result.confidence == "high"


def test_dot_p_with_unrecognised_content_keeps_the_table_answer() -> None:
    result = classify("legacy/old.p", b"print('hello')\n")
    assert result.cls == "pascal_unit"


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------


def test_no_extension_and_no_content_is_explicitly_unknown() -> None:
    result = classify("mystery")
    assert result.cls == "unknown"
    assert result.evidence == ("no-extension", "no-content")
    assert result.confidence == "low"


def test_no_extension_with_unrecognised_text_is_explicitly_unknown() -> None:
    result = classify("mystery", b"hello world\n")
    assert result.cls == "unknown"
    assert result.evidence == ("no-extension", "content-unrecognised")
    assert result.confidence == "low"


def test_nul_bytes_without_a_known_magic_are_binary() -> None:
    result = classify("mystery", b"\x00\x01\x02\x03")
    assert result.cls == "binary"
    assert result.evidence == ("nul-byte",)
    assert result.confidence == "medium"


def test_mostly_non_text_bytes_are_binary() -> None:
    result = classify("mystery", bytes(range(0, 32)))
    assert result.cls == "binary"


def test_empty_file_with_an_extension_uses_the_table() -> None:
    result = classify("doc/empty.txt", b"")
    assert result.cls == "documentation"
    assert result.confidence == "high"


# ---------------------------------------------------------------------------
# Version-control metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [".git/config", "repo/.git/HEAD", "a/b/.git/objects/pack/x"],
)
def test_git_directory_is_version_control(path: str) -> None:
    result = classify(path, b"[core]\n")
    assert result.cls == "version_control"
    assert result.evidence == ("path-segment",)
    assert result.discovery_only is True


def test_gitignore_anywhere_in_the_tree_is_version_control() -> None:
    result = classify("a/b/.gitignore", b"*.log\n")
    assert result.cls == "version_control"
    assert result.evidence == ("file-name",)


# ---------------------------------------------------------------------------
# Determinism and serialisation
# ---------------------------------------------------------------------------


def test_classify_is_deterministic() -> None:
    for path in SAMPLE_PATHS:
        first = classify(path, b"unit x;\n")
        second = classify(path, b"unit x;\n")
        assert first == second
        assert first.as_dict() == second.as_dict()


def test_as_dict_has_the_stable_key_set() -> None:
    keys = set(classify("src/a.pas").as_dict())
    assert keys == {
        "analysis", "class", "class_evidence", "confidence", "discovery_only",
    }


@pytest.mark.parametrize("path", SAMPLE_PATHS)
def test_class_evidence_is_never_empty(path: str) -> None:
    result = classify(path, b"unit x;\n")
    assert result.evidence, f"{path} produced a class with no evidence"
    assert result.confidence in ("high", "medium", "low")


@pytest.mark.parametrize("path", SAMPLE_PATHS)
def test_analysis_blocker_is_empty_at_this_layer(path: str) -> None:
    """Size/read blockers are applied by the pipeline, not by classify."""

    assert classify(path, b"unit x;\n", size=10 ** 9).analysis_blocker == ""


def test_limits_are_honoured_for_sniffing() -> None:
    """A tiny sniff budget must not change the verdict for a short head."""

    head = b"unit x;\n" + b" " * 4096
    assert classify("u", head, limits=DEFAULT_LIMITS).cls == "pascal_unit"
    assert classify("u", head[:4], limits=DEFAULT_LIMITS).cls == "pascal_unit"
