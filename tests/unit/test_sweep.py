"""Unit tests for the fixture-corpus regression gate (task E5).

The gate is the only thing standing between ``corpus/`` and silent drift, so
its own failure modes are tested directly: a broken expectation table must be
refused rather than treated as "no expectations, everything matches", and a
fixture that nobody declared must fail the build rather than pass quietly.

Nothing here invokes a compiler - the comparison logic is pure, so it is
tested without FPC, Docker or a network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from p1 import sweep

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "corpus"
EXPECTATIONS = CORPUS / "expectations.txt"


# ---------------------------------------------------------------------------
# The repository's own contract
# ---------------------------------------------------------------------------


def test_expectations_cover_the_whole_corpus_exactly() -> None:
    """Every compilable fixture is declared, and nothing else is."""

    table = sweep.load_expectations(EXPECTATIONS)
    fixtures = sweep.discover_fixtures(CORPUS)

    # Same ordering as discover_fixtures: case-insensitive, so the corpus
    # files and the table entries line up one-for-one.
    assert sorted(table, key=str.lower) == fixtures, (
        "corpus/ and corpus/expectations.txt disagree; a fixture without an "
        "expectation (or the reverse) fails the gate at runtime"
    )
    # Guards against a "no expectations" gate: an empty table is refused by
    # load_expectations, and a shrunken one would fail the equality above.
    assert len(fixtures) >= 24


def test_every_expectation_uses_the_declared_vocabulary() -> None:
    table = sweep.load_expectations(EXPECTATIONS)
    for rel, (verdict, _overrides) in table.items():
        assert verdict in ("PASS", "FAIL-DEPENDENCY"), rel


def test_the_windows_only_fixture_declares_a_linux_override() -> None:
    """unit ComObj exists on Windows only, so the verdict is platform-relative."""

    table = sweep.load_expectations(EXPECTATIONS)
    rel = "dbaccess/ado_style_connection.pas"
    assert sweep.expected_for(table, rel, "windows") == "PASS"
    assert sweep.expected_for(table, rel, "linux") == "FAIL-DEPENDENCY"


def test_a_platform_override_does_not_leak_to_other_fixtures() -> None:
    table = sweep.load_expectations(EXPECTATIONS)
    rel = "dbaccess/bde_style_query.pas"
    assert sweep.expected_for(table, rel, "windows") == "FAIL-DEPENDENCY"
    assert sweep.expected_for(table, rel, "linux") == "FAIL-DEPENDENCY"


# ---------------------------------------------------------------------------
# Parsing the expectation table
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, text: str, name: str = "expectations.txt") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "# heading\n"
        "\n"
        "  a.pas|PASS  \n"
        "\n"
        "# trailing comment\n"
        "b.pas|FAIL-DEPENDENCY\n",
    )
    table = sweep.load_expectations(path)
    assert table == {
        "a.pas": ("PASS", {}),
        "b.pas": ("FAIL-DEPENDENCY", {}),
    }


def test_a_missing_expectations_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(sweep.GateError):
        sweep.load_expectations(tmp_path / "absent.txt")


def test_an_empty_expectations_file_is_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "# nothing but comments\n\n")
    with pytest.raises(sweep.GateError):
        sweep.load_expectations(path)


@pytest.mark.parametrize(
    "line",
    [
        "a.pas",                    # no verdict
        "a.pas|LIKELY",             # vocabulary violation
        "|PASS",                    # no fixture
        "a.pas|PASS|linux",         # override without a verdict
        "a.pas|PASS|linux=MAYBE",   # override vocabulary violation
        "a.pas|PASS|windows",       # ditto
    ],
)
def test_a_malformed_line_is_refused(tmp_path: Path, line: str) -> None:
    """A broken contract must not degrade into 'nothing to check'."""

    path = _write(tmp_path, line + "\n")
    with pytest.raises(sweep.GateError):
        sweep.load_expectations(path)


def test_a_duplicate_entry_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.pas|PASS\na.pas|PASS\n")
    with pytest.raises(sweep.GateError):
        sweep.load_expectations(path)


def test_backslash_paths_are_normalised(tmp_path: Path) -> None:
    path = _write(tmp_path, "sub\\a.pas|PASS\n")
    table = sweep.load_expectations(path)
    assert "sub/a.pas" in table


# ---------------------------------------------------------------------------
# Parsing sweep output
# ---------------------------------------------------------------------------


def test_host_records_are_parsed() -> None:
    raw = "PASS|objfpc|a.pas\nFAIL|fpc|b.pas|b.pas(4,2) Fatal: nope\n"
    assert sweep.parse_records(raw) == [
        ("PASS", "objfpc", "a.pas"),
        ("FAIL", "fpc", "b.pas"),
    ]


def test_container_records_and_headers_are_parsed() -> None:
    raw = (
        "TOOL|/usr/bin/fpc|version=3.2.2\n"
        "PLATFORM|Linux 6.1 x86_64\n"
        "RESULT|PASS|objfpc|a.pas\n"
        "RESULT|FAIL|fpc|b.pas|b.pas(4,2) Fatal: nope\n"
        "EXPECTATION|a.pas|expected=PASS|actual=PASS|MATCH\n"
        "SUMMARY|fixtures=2|PASS=1|FAIL=1|MATCH=2|MISMATCH=0\n"
    )
    assert sweep.parse_records(raw) == [
        ("PASS", "objfpc", "a.pas"),
        ("FAIL", "fpc", "b.pas"),
    ]


def test_backslash_separators_are_normalised() -> None:
    assert sweep.parse_records("PASS|fpc|sub\\a.pas\n") == [
        ("PASS", "fpc", "sub/a.pas")
    ]


def test_noise_is_not_mistaken_for_a_verdict() -> None:
    raw = (
        "GATE|PASS|mismatches=0\n"
        "hello world\n"
        "PASS\n"              # too short to be a record
        "MAYBE|fpc|a.pas\n"   # unknown verdict
        "\n"
    )
    assert sweep.parse_records(raw) == []


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _table() -> dict[str, tuple[str, dict[str, str]]]:
    return {
        "a.pas": ("PASS", {}),
        "b.pas": ("FAIL-DEPENDENCY", {}),
        "c.pas": ("PASS", {"linux": "FAIL-DEPENDENCY"}),
    }


def _fixtures() -> list[str]:
    return ["a.pas", "b.pas", "c.pas"]


def test_a_declared_dependency_failure_is_satisfied_by_a_fail() -> None:
    records = [("PASS", "fpc", "a.pas"), ("FAIL", "fpc", "b.pas"),
               ("PASS", "fpc", "c.pas")]
    report, code = sweep.compare(records, _table(), "windows", _fixtures())
    assert code == 0
    assert sum(1 for line in report if line.endswith("|MATCH")) == 3


def test_a_declared_pass_is_not_satisfied_by_a_fail() -> None:
    records = [("FAIL", "fpc", "a.pas"), ("FAIL", "fpc", "b.pas"),
               ("PASS", "fpc", "c.pas")]
    report, code = sweep.compare(records, _table(), "windows", _fixtures())
    assert code == 1
    assert any(
        line.startswith("EXPECTATION|a.pas|") and line.endswith("|MISMATCH")
        for line in report
    )


def test_the_platform_override_decides_agreement() -> None:
    records = [("PASS", "fpc", "a.pas"), ("FAIL", "fpc", "b.pas"),
               ("FAIL", "fpc", "c.pas")]
    assert sweep.compare(records, _table(), "linux", _fixtures())[1] == 0
    assert sweep.compare(records, _table(), "windows", _fixtures())[1] == 1


def test_an_undeclared_fixture_is_a_mismatch() -> None:
    records = [("PASS", "fpc", "a.pas"), ("FAIL", "fpc", "b.pas"),
               ("PASS", "fpc", "c.pas"), ("PASS", "fpc", "surprise.pas")]
    report, code = sweep.compare(records, _table(), "windows", _fixtures())
    assert code == 1
    assert any(
        "EXPECTATION|surprise.pas|expected=UNDECLARED" in line
        for line in report
    )


def test_an_expectation_with_no_fixture_is_a_mismatch() -> None:
    records = [("PASS", "fpc", "a.pas"), ("FAIL", "fpc", "b.pas")]
    report, code = sweep.compare(records, _table(), "windows", _fixtures())
    assert code == 1
    assert any(
        line.startswith("EXPECTATION|c.pas|") and "NOT-SWEPT" in line
        for line in report
    )


def test_a_duplicate_record_is_a_mismatch() -> None:
    records = [("PASS", "fpc", "a.pas"), ("FAIL", "fpc", "a.pas")]
    report, code = sweep.compare(records, _table(), "windows", _fixtures())
    assert code == 1
    assert any("expected=duplicate" in line for line in report)


def test_the_summary_counts_every_outcome() -> None:
    records = [("PASS", "fpc", "a.pas"), ("FAIL", "fpc", "b.pas"),
               ("FAIL", "fpc", "c.pas")]
    report, code = sweep.compare(records, _table(), "linux", _fixtures())
    assert code == 0
    assert report[-1] == (
        "SUMMARY|fixtures=3|expected=3|MATCH=3|MISMATCH=0"
    )


# ---------------------------------------------------------------------------
# The command line entry point
# ---------------------------------------------------------------------------


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.pas").write_text("program A;\nbegin\nend.\n", encoding="utf-8")
    (corpus / "b.pas").write_text("program B;\nbegin\nend.\n", encoding="utf-8")
    expect = tmp_path / "expectations.txt"
    expect.write_text("a.pas|PASS\nb.pas|FAIL-DEPENDENCY\n", encoding="utf-8")
    return corpus, expect


def test_a_matching_record_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    corpus, expect = _scaffold(tmp_path)
    record = tmp_path / "record.txt"
    record.write_text("PASS|fpc|a.pas\nFAIL|fpc|b.pas\n", encoding="utf-8")

    code = sweep.main([
        "--input", str(record), "--corpus", str(corpus),
        "--expect", str(expect), "--platform", "linux",
    ])

    assert code == 0
    out = capsys.readouterr().out
    assert out.rstrip().endswith("GATE|PASS|mismatches=0")
    assert "MATCH=2" in out


def test_a_new_mismatch_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    corpus, expect = _scaffold(tmp_path)
    record = tmp_path / "record.txt"
    record.write_text("FAIL|fpc|a.pas\nFAIL|fpc|b.pas\n", encoding="utf-8")

    code = sweep.main([
        "--input", str(record), "--corpus", str(corpus),
        "--expect", str(expect), "--platform", "linux",
    ])

    assert code == 1
    out = capsys.readouterr().out
    assert "MISMATCH=1" in out
    assert out.rstrip().endswith("GATE|FAIL|mismatches=1")


def test_a_broken_record_file_exits_two(tmp_path: Path) -> None:
    corpus, expect = _scaffold(tmp_path)

    code = sweep.main([
        "--input", str(tmp_path / "absent.txt"), "--corpus", str(corpus),
        "--expect", str(expect),
    ])
    assert code == 2


def test_a_sweep_with_no_records_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    corpus, expect = _scaffold(tmp_path)
    record = tmp_path / "record.txt"
    record.write_text("nothing to see here\n", encoding="utf-8")

    code = sweep.main([
        "--input", str(record), "--corpus", str(corpus),
        "--expect", str(expect),
    ])
    assert code == 2
    assert "no PASS/FAIL records" in capsys.readouterr().err


def test_an_archive_is_never_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A retained baseline that overwrites itself retains nothing (A4)."""

    corpus, expect = _scaffold(tmp_path)
    record = tmp_path / "record.txt"
    record.write_text("PASS|fpc|a.pas\nFAIL|fpc|b.pas\n", encoding="utf-8")
    out = tmp_path / "archive.txt"
    out.write_text("previous run\n", encoding="utf-8")

    code = sweep.main([
        "--input", str(record), "--corpus", str(corpus),
        "--expect", str(expect), "--out", str(out),
    ])

    assert code == 2
    assert out.read_text(encoding="utf-8") == "previous run\n"
    assert "refusing to overwrite" in capsys.readouterr().err


def test_a_matching_run_writes_the_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    corpus, expect = _scaffold(tmp_path)
    record = tmp_path / "record.txt"
    record.write_text("PASS|fpc|a.pas\nFAIL|fpc|b.pas\n", encoding="utf-8")
    out = tmp_path / "archive.txt"

    code = sweep.main([
        "--input", str(record), "--corpus", str(corpus),
        "--expect", str(expect), "--out", str(out),
    ])

    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert text.endswith("GATE|PASS|mismatches=0\n")
    assert text == capsys.readouterr().out


def test_the_two_modes_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        sweep.main(["--host", "--docker"])
    with pytest.raises(SystemExit):
        sweep.main([])


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_only_compilable_fixtures_are_discovered(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "nested").mkdir(parents=True)
    (corpus / "a.pas").write_text("", encoding="utf-8")
    (corpus / "b.dpr").write_text("", encoding="utf-8")
    (corpus / "c.lpr").write_text("", encoding="utf-8")
    (corpus / "notes.md").write_text("", encoding="utf-8")
    (corpus / "nested" / "d.inc").write_text("", encoding="utf-8")

    assert sweep.discover_fixtures(corpus) == [
        "a.pas", "b.dpr", "c.lpr",
    ]


def test_discovery_is_sorted_and_case_stable(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name in ("Zeta.pas", "alpha.pas", "Beta.pas"):
        (corpus / name).write_text("", encoding="utf-8")

    found = sweep.discover_fixtures(corpus)
    assert found == ["alpha.pas", "Beta.pas", "Zeta.pas"]
    assert found == sorted(found, key=str.lower)


def test_discovery_of_a_missing_corpus_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(sweep.GateError):
        sweep.discover_fixtures(tmp_path / "absent")
