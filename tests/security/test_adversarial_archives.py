"""E1 — adversarial archive suite (tasks B1, E1; plan §4.1–4.3, §7).

Every case asserts on the **stable refusal code**, never on message wording,
so wording can be improved without rewriting the suite.  The refusals come in
two flavours and both are asserted:

``IngestionError``
    The archive is refused before anything is written.  ``assert_nothing_``
    ``extracted`` then proves staging is still empty — the validate-first
    strategy, exercised rather than asserted in prose.
``IngestionError`` raised mid-extraction
    Only reachable when the *declaration* was a lie (a size that does not
    match the bytes).  ``pipeline.run`` discards the staging directory.
"""

from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

import pytest

from conftest import (
    assert_nothing_extracted,
    expect_refusal,
    make_zip,
    read_json,
    run_pipeline,
    write_tree,
)

from p1.errors import IngestionError, UnsafePathError
from p1.limits import DEFAULT_LIMITS, Limits
from p1.pathsafe import clean_entry_name
from p1.zipingest import ingest_zip


# ---------------------------------------------------------------------------
# Hostile entry names (plan §4.2)
# ---------------------------------------------------------------------------

#: ``(label, entry name, raw_name override)``.  ``raw_name`` exists because
#: ``zipfile.ZipInfo`` rewrites ``\`` to ``/`` on Windows at construction
#: time, so a genuine backslash name has to be forced afterwards.
HOSTILE_NAMES: list[tuple[str, str, str | None]] = [
    ("parent traversal", "../evil.pas", None),
    ("nested traversal", "src/../../evil.pas", None),
    ("current-dir traversal", "./../evil.pas", None),
    ("leading slash", "/etc/evil.pas", None),
    ("drive letter forward", "C:/evil.pas", None),
    ("drive letter backslash", "x", "C:\\evil.pas"),
    ("unc forward", "//server/share/evil.pas", None),
    ("unc backslash", "x", "\\\\server\\share\\evil.pas"),
    ("extended-length prefix", "x", "\\\\?\\C:\\evil.pas"),
    ("alternate data stream", "file:stream.pas", None),
    ("reserved device CON", "CON.pas", None),
    ("reserved device AUX", "aux.txt", None),
    ("reserved device COM1", "COM1.pas", None),
    ("reserved device LPT9", "LPT9.log", None),
    ("control character", "evil\x01.pas", None),
    ("bidi override", "evil\u202ev.pas", None),
    ("trailing space", "evil ", None),
    ("trailing dot", "evil.", None),
    ("non-nfc name", "cafe\u0301.pas", None),
    ("empty name", "", None),
    ("too deep", "/".join(f"seg{i:02d}" for i in range(40)) + "/x.pas", None),
    ("component too long", "a" * 300 + ".pas", None),
    ("path too long", "d/" * 3000 + "x.pas", None),
]


@pytest.mark.parametrize(
    "label,name,raw_name",
    HOSTILE_NAMES,
    ids=[label for label, _, _ in HOSTILE_NAMES],
)
def test_hostile_entry_name_is_refused(
    tmp_path: Path, label: str, name: str, raw_name: str | None
) -> None:
    archive = make_zip(
        tmp_path / "hostile.zip",
        [{"name": name, "raw_name": raw_name, "data": b"pwned"}],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    sentinels = [write_tree(tmp_path / "outside", {"keep.txt": "keep"})]

    code = expect_refusal(ingest_zip, archive, staging, limits=DEFAULT_LIMITS)
    assert code == "UNSAFE_PATH", label
    assert_nothing_extracted(staging, sentinels)


@pytest.mark.parametrize(
    "name",
    [
        "../x.pas",
        "/x.pas",
        "C:/x.pas",
        "\\\\srv\\s\\x.pas",
        "a:b",
        "CON",
        "nul.txt",
        "x\x00y",
        "x\x01y",
        "x\u202ey",
        "trailing ",
        "trailing.",
        "",
        "seg/" * 40 + "x.pas",
    ],
)
def test_clean_entry_name_rejects(name: str) -> None:
    """The lexical layer is pure: rejection has no filesystem side effect."""

    with pytest.raises(UnsafePathError) as excinfo:
        clean_entry_name(name, DEFAULT_LIMITS)
    assert excinfo.value.code == "UNSAFE_PATH"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("src/uMath.pas", "src/uMath.pas"),
        ("./src/./uMath.pas", "src/uMath.pas"),
        ("src//uMath.pas", "src/uMath.pas"),
        ("src\\uMath.pas", "src/uMath.pas"),
        ("a/b/c.pas", "a/b/c.pas"),
    ],
)
def test_clean_entry_name_normalises_safe_names(name: str, expected: str) -> None:
    assert clean_entry_name(name, DEFAULT_LIMITS) == expected


def test_traversal_is_refused_not_rewritten(tmp_path: Path) -> None:
    """Normalisation must never turn an attack into a valid path."""

    with pytest.raises(UnsafePathError):
        clean_entry_name("src/../../etc/passwd", DEFAULT_LIMITS)


def test_nul_in_an_entry_name_never_reaches_the_payload(tmp_path: Path) -> None:
    """A NUL-truncated name cannot smuggle a second extension onto a file.

    ZIP readers terminate a name at the first NUL — the classic
    ``evil.pas\\x00.exe`` trick.  The suffix must not survive into the
    extracted tree, and the surviving name must still be a safe relative path.
    """

    archive = make_zip(
        tmp_path / "nul.zip",
        [{
            "name": "placeholder",
            "raw_name": "src/uMath.pas\x00.exe",
            "data": b"unit uMath; end.\n",
        }],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    result = ingest_zip(archive, staging)

    assert [f.path for f in result.files] == ["src/uMath.pas"]
    assert (staging / "src" / "uMath.pas").is_file()
    assert not (staging / "src" / "uMath.pas.exe").exists()


# ---------------------------------------------------------------------------
# Symlinks and special files (plan §4.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,code",
    [
        (0o120777, "SYMLINK_ENTRY"),
        (0o120000, "SYMLINK_ENTRY"),
        (0o010644, "SPECIAL_FILE_ENTRY"),
        (0o020644, "SPECIAL_FILE_ENTRY"),
        (0o060644, "SPECIAL_FILE_ENTRY"),
        (0o140644, "SPECIAL_FILE_ENTRY"),
    ],
)
def test_special_file_entries_are_refused(
    tmp_path: Path, mode: int, code: str
) -> None:
    archive = make_zip(
        tmp_path / "special.zip",
        [{"name": "link.pas", "mode": mode, "data": b"whatever"}],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    assert expect_refusal(ingest_zip, archive, staging) == code
    assert list(staging.iterdir()) == []


@pytest.mark.parametrize(
    "mode",
    [
        0o100644,  # regular file
        0o040755,  # directory
        0,         # no unix type information at all
        0o000020,  # DOS archive attribute stored in the high word
    ],
)
def test_ordinary_entries_are_not_mistaken_for_special_files(
    tmp_path: Path, mode: int
) -> None:
    """A false rejection would make ordinary enterprise archives unusable."""

    archive = make_zip(
        tmp_path / "ordinary.zip",
        [{"name": "src/ok.pas", "mode": mode, "data": b"unit ok; end.\n"}],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    result = ingest_zip(archive, staging)
    assert [f.path for f in result.files] == ["src/ok.pas"]


# ---------------------------------------------------------------------------
# Limits (plan §4.1)
# ---------------------------------------------------------------------------


def test_too_many_entries(tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "many.zip",
        [(f"f{i}.pas", b"unit x; end.") for i in range(5)],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    code = expect_refusal(
        ingest_zip, archive, staging, limits=Limits(max_entries=3)
    )
    assert code == "TOO_MANY_ENTRIES"
    assert list(staging.iterdir()) == []


def test_oversized_entry(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "big.zip", [("big.pas", b"A" * 4096)])
    staging = tmp_path / "stage"
    staging.mkdir()
    code = expect_refusal(
        ingest_zip, archive, staging, limits=Limits(max_entry_bytes=1024)
    )
    assert code == "ENTRY_TOO_LARGE"
    assert list(staging.iterdir()) == []


def test_total_size_budget(tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "total.zip",
        [(f"f{i}.pas", b"B" * 512) for i in range(4)],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    code = expect_refusal(
        ingest_zip, archive, staging, limits=Limits(max_total_bytes=1536)
    )
    assert code == "TOTAL_TOO_LARGE"
    assert list(staging.iterdir()) == []


def test_compression_ratio_bomb(tmp_path: Path) -> None:
    """A default-limits archive whose expansion ratio exceeds the bound."""

    archive = make_zip(
        tmp_path / "bomb.zip",
        [{"name": "zeros.pas", "data": b"\0" * 5_000_000}],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    code = expect_refusal(ingest_zip, archive, staging, limits=DEFAULT_LIMITS)
    assert code == "ZIP_BOMB_RATIO"
    assert list(staging.iterdir()) == []


def test_deep_nesting_is_refused(tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "deep.zip",
        [{"name": "/".join("d" * 8 for _ in range(40)) + "/x.pas",
          "data": b"unit x; end."}],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    assert expect_refusal(ingest_zip, archive, staging) == "UNSAFE_PATH"


@pytest.mark.parametrize(
    "label,entries",
    [
        ("exact duplicate", [("a.pas", b"one"), ("a.pas", b"two")]),
        ("case collision", [("Src/A.pas", b"one"), ("src/a.pas", b"two")]),
    ],
)
def test_duplicate_entries_are_refused(
    tmp_path: Path, label: str, entries: list[tuple[str, bytes]]
) -> None:
    archive = make_zip(tmp_path / "dup.zip", entries)
    staging = tmp_path / "stage"
    staging.mkdir()
    assert expect_refusal(ingest_zip, archive, staging) == "DUPLICATE_ENTRY"
    assert list(staging.iterdir()) == []


# ---------------------------------------------------------------------------
# Malformed and truncated input
# ---------------------------------------------------------------------------


def test_not_a_zip(tmp_path: Path) -> None:
    path = tmp_path / "fake.zip"
    path.write_bytes(b"this is definitely not a zip archive")
    staging = tmp_path / "stage"
    staging.mkdir()
    assert expect_refusal(ingest_zip, path, staging) == "NOT_A_ZIP"


def test_truncated_zip(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "ok.zip", [("a.pas", b"unit a; end.")])
    data = archive.read_bytes()
    archive.write_bytes(data[: len(data) // 2])
    staging = tmp_path / "stage"
    staging.mkdir()
    assert expect_refusal(ingest_zip, archive, staging) == "NOT_A_ZIP"


def test_missing_archive(tmp_path: Path) -> None:
    staging = tmp_path / "stage"
    staging.mkdir()
    assert (
        expect_refusal(ingest_zip, tmp_path / "absent.zip", staging)
        == "INPUT_NOT_FOUND"
    )


def test_declared_size_lies(tmp_path: Path) -> None:
    """Phase 2 re-counts bytes because declarations are untrusted."""

    archive = tmp_path / "liar.zip"
    make_zip(archive, [("liar.pas", b"unit liar; end.")])

    # Inflate the *declared* uncompressed size in the central directory only.
    payload = bytearray(archive.read_bytes())
    offset = payload.rfind(b"PK\x01\x02")
    assert offset > 0, "central directory header not found"
    struct.pack_into("<I", payload, offset + 24, 4096)
    archive.write_bytes(bytes(payload))

    staging = tmp_path / "stage"
    staging.mkdir()
    assert expect_refusal(ingest_zip, archive, staging) == "SIZE_MISMATCH"


def test_refusal_leaves_no_artefacts(tmp_path: Path) -> None:
    """A refused input must not produce output documents (fail closed)."""

    archive = tmp_path / "hostile.zip"
    make_zip(archive, [{"name": "../escape.pas", "data": b"pwned"}])
    outdir = tmp_path / "out"

    with pytest.raises(IngestionError) as excinfo:
        run_pipeline(archive, outdir, kind="zip")
    assert excinfo.value.code == "UNSAFE_PATH"
    assert not outdir.exists() or list(outdir.iterdir()) == []
    assert not (tmp_path / "escape.pas").exists()


def test_pipeline_discards_staging_after_a_refusal(tmp_path: Path) -> None:
    """Staging is a temporary artefact: a failure must not leave one behind."""

    import tempfile

    archive = tmp_path / "hostile.zip"
    make_zip(archive, [{"name": "../escape.pas", "data": "pwned"}])
    outdir = tmp_path / "out"

    before = set(Path(tempfile.gettempdir()).glob("p1-stage-*"))
    with pytest.raises(IngestionError):
        run_pipeline(archive, outdir, kind="zip")
    after = set(Path(tempfile.gettempdir()).glob("p1-stage-*"))
    assert after - before == set()


# ---------------------------------------------------------------------------
# Ingestion that must *succeed* (guards against an over-tight policy)
# ---------------------------------------------------------------------------


def test_zero_byte_file_is_inventoried_not_dropped(tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "empty.zip",
        [("empty.pas", b""), ("keep/real.pas", b"unit real; end.")],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    result = ingest_zip(archive, staging)
    by_path = {f.path: f for f in result.files}
    assert set(by_path) == {"empty.pas", "keep/real.pas"}
    assert by_path["empty.pas"].size == 0
    assert len(by_path["empty.pas"].sha256) == 64


def test_utf16_source_round_trips(tmp_path: Path) -> None:
    """A BOM-marked UTF-16 source is ingested and readable."""

    text = "unit uEnc;\ninterface\nimplementation\nend.\n"
    archive = make_zip(
        tmp_path / "enc.zip",
        [{"name": "uEnc.pas", "data": b"\xff\xfe" + text.encode("utf-16le")}],
    )
    staging = tmp_path / "stage"
    staging.mkdir()
    result = ingest_zip(archive, staging)
    assert [f.path for f in result.files] == ["uEnc.pas"]
    assert (staging / "uEnc.pas").read_bytes().startswith(b"\xff\xfe")


def test_source_larger_than_the_analysis_budget_is_kept(
    tmp_path: Path, app_tree: Path
) -> None:
    """Analysis budget bounds *reading*, never inventory (task D4)."""

    outdir = tmp_path / "out"
    result = run_pipeline(
        app_tree,
        outdir,
        kind="directory",
        limits=Limits(max_source_bytes=32),
    )
    manifest = read_json(Path(result.outputs["manifest"]))
    paths = {f["path"] for f in manifest["files"]}
    assert "src/MiniApp.dpr" in paths, "oversized source was dropped"

    blocked = {
        f["path"]: f["analysis_blocker"]
        for f in manifest["files"]
        if f.get("analysis_blocker")
    }
    assert blocked.get("src/MiniApp.dpr") == "too-large"


def test_zip_and_directory_produce_the_same_inventory(
    tmp_path: Path, app_tree: Path
) -> None:
    """Identical bytes must yield identical file records (task B3)."""

    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in sorted(app_tree.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(app_tree).as_posix())

    out_zip = tmp_path / "out-zip"
    out_dir = tmp_path / "out-dir"
    run_pipeline(archive, out_zip, kind="zip")
    run_pipeline(app_tree, out_dir, kind="directory")

    def files(out: Path) -> list[dict[str, object]]:
        manifest = read_json(Path(out) / "application-manifest.json")
        return [
            {k: f.get(k) for k in
             ("path", "sha256", "size", "class", "class_evidence",
              "encoding", "encoding_confidence", "capability_status")}
            for f in manifest["files"]
        ]

    assert files(out_zip) == files(out_dir)

    left = read_json(Path(out_zip) / "application-manifest.json")
    right = read_json(Path(out_dir) / "application-manifest.json")

    # Everything the discovery produced must be identical; the input kind may
    # differ only in its own bookkeeping.
    for key in ("dialects", "profiles", "project_roots", "shapes",
                "capability_states", "classification", "dependency_summary",
                "build_requirements", "database", "sql_files", "native_libs",
                "os_dependencies", "mode_visibility"):
        assert left[key] == right[key], key

    # Diagnostics may differ only in the ingestion-specific informational
    # codes each path emits for itself.
    ingestion_only = {"ZIP_INGESTED", "PATH_EXCLUDED_FROM_INVENTORY"}
    assert [
        d for d in left["diagnostics"] if d["code"] not in ingestion_only
    ] == [
        d for d in right["diagnostics"] if d["code"] not in ingestion_only
    ]

    def without_timestamps(manifest: dict[str, object]) -> str:
        stripped = [
            {k: v for k, v in f.items() if k != "source_timestamp"}
            for f in manifest["files"]  # type: ignore[index]
        ]
        return json.dumps(stripped, sort_keys=True)

    assert without_timestamps(left) == without_timestamps(right)
    # ...and the timestamp itself is the sole per-file divergence: a ZIP
    # carries a DOS timestamp, a plain directory has none.
    assert all("source_timestamp" in f for f in left["files"])
    assert not any("source_timestamp" in f for f in right["files"])
