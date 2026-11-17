"""Guard tests for the no-LLM / no-probabilistic-dependency rule (task E3).

This is one of the two files the guard itself exempts — it must name the
patterns it asserts on.  The exemption is therefore pinned here: if
``ALLOWLIST`` ever grows, this test fails.

Two things are checked:

* the guard passes on this repository (the rule holds today);
* the guard actually *fires* on a synthetic violation (the gate is not a
  rubber stamp).
"""

from __future__ import annotations

import re
from pathlib import Path

from p1 import guard

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The two files that must contain the forbidden spellings in order to test
#: them.  Anything more here would be an exemption nobody reviewed.
EXPECTED_ALLOWLIST = (
    "tools/p1/guard.py",
    "tests/security/test_no_llm_guard.py",
)

EXPECTED_SCAN_ROOTS = ("tools", "tests", "scripts", ".github")


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


def test_allowlist_is_exactly_the_two_files_that_need_it() -> None:
    assert guard.ALLOWLIST == EXPECTED_ALLOWLIST


def test_scan_roots_are_the_product_surface() -> None:
    assert guard.SCAN_ROOTS == EXPECTED_SCAN_ROOTS


def test_forbidden_categories_are_the_adr_0005_set() -> None:
    assert tuple(guard.FORBIDDEN_CATEGORIES) == (
        "model-sdk",
        "llm-framework",
        "inference-runtime",
        "embedding",
        "vector-store",
        "ai-endpoint",
        "inference-config",
        "probabilistic-decision",
    )


def test_model_weight_suffixes_cover_the_common_formats() -> None:
    for suffix in (".safetensors", ".gguf", ".ggml", ".pt", ".pth",
                   ".onnx", ".bin", ".pkl", ".npz", ".model"):
        assert suffix in guard.MODEL_WEIGHT_SUFFIXES
    assert len(set(guard.MODEL_WEIGHT_SUFFIXES)) == len(
        guard.MODEL_WEIGHT_SUFFIXES
    ), "duplicate suffix would double-count findings"


def test_only_documentation_may_contain_model_weight_files() -> None:
    assert guard.WEIGHT_EXEMPT_ROOTS == ("docs",)


def test_every_pattern_is_a_compiled_case_insensitive_regex() -> None:
    for category, patterns in guard.FORBIDDEN_PATTERNS.items():
        assert patterns, category
        for pattern in patterns:
            assert isinstance(pattern, re.Pattern), category
            assert pattern.pattern, category
            assert pattern.flags & re.IGNORECASE, category


# ---------------------------------------------------------------------------
# The repository passes today
# ---------------------------------------------------------------------------


def test_repository_has_no_forbidden_constructs() -> None:
    passed, findings = guard.run(REPO_ROOT)
    assert passed, "\n".join(f.render() for f in findings)
    assert findings == []


def test_summary_reports_pass_with_stable_keys() -> None:
    summary = guard.summary(REPO_ROOT)
    assert summary["result"] == "PASS"
    assert summary["total_findings"] == 0
    assert summary["findings"] == []
    assert summary["gate"] == "no-llm-dependency-guard"
    assert summary["allowlist"] == list(EXPECTED_ALLOWLIST)
    assert summary["scanned_roots"] == list(EXPECTED_SCAN_ROOTS)
    assert set(summary) == {
        "allowlist", "categories_scanned", "findings",
        "findings_by_category", "gate", "result", "rule",
        "scanned_roots", "total_findings",
    }


def test_findings_are_sorted_and_renderable() -> None:
    findings = guard.scan(REPO_ROOT)
    assert findings == sorted(
        findings, key=lambda f: (f.path, f.line, f.category, f.excerpt)
    )
    for finding in findings:
        assert finding.render()


# ---------------------------------------------------------------------------
# The gate fires on a synthetic violation
# ---------------------------------------------------------------------------


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / Path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_source_file_with_a_model_sdk_import_fails(tmp_path: Path) -> None:
    _write(tmp_path, "tools/thing.py", "import openai\n")

    passed, findings = guard.run(tmp_path)
    assert passed is False
    assert [f.category for f in findings] == ["model-sdk"]
    assert findings[0].path == "tools/thing.py"
    assert findings[0].line == 1


def test_manifest_with_a_forbidden_dependency_fails(tmp_path: Path) -> None:
    """Manifests are only scanned where product code lives (a scan root)."""

    _write(tmp_path, "tools/requirements.txt",
           "requests==2.31.0\nnumpy==1.26.0\n")

    passed, findings = guard.run(tmp_path)
    assert passed is True  # a clean manifest is clean

    _write(tmp_path, "tools/requirements.txt", "requests==2.31.0\nllama-index\n")
    passed, findings = guard.run(tmp_path)
    assert passed is False
    assert [f.category for f in findings] == ["llm-framework"]
    assert findings[0].path == "tools/requirements.txt"


def test_inference_configuration_fails(tmp_path: Path) -> None:
    _write(tmp_path, "tools/config.py",
           'model = "gpt-4o-mini"\nmax_tokens = 512\ntemperature = 0.7\n')

    passed, findings = guard.run(tmp_path)
    assert passed is False
    assert {f.category for f in findings} == {"inference-config"}


def test_prose_is_not_scanned(tmp_path: Path) -> None:
    """Documentation quoting a forbidden name is not a product violation."""

    _write(tmp_path, "docs/notes.md",
           "We considered several model SDKs and rejected them all.\n")
    assert guard.run(tmp_path)[0] is True


def test_non_source_non_manifest_files_are_not_scanned(tmp_path: Path) -> None:
    _write(tmp_path, "tools/data.csv", "openai,anthropic\n")
    assert guard.run(tmp_path)[0] is True


def test_a_model_weight_file_outside_documentation_fails(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "tools/weights.safetensors", "\x00\x01")

    passed, findings = guard.run(tmp_path)
    assert passed is False
    assert [f.category for f in findings] == ["model-weight-file"]
    assert findings[0].line == 0


def test_a_model_weight_file_under_documentation_is_exempt(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "docs/example.gguf", "\x00\x01")
    assert guard.run(tmp_path)[0] is True


def test_the_allowlisted_files_are_the_only_ones_exempt(
    tmp_path: Path,
) -> None:
    """A file that merely *looks* like an allowlisted path still fails."""

    _write(tmp_path, "tools/p1/guard_copy.py", "import openai\n")
    _write(tmp_path, "tests/security/other_test.py", "import openai\n")

    passed, findings = guard.run(tmp_path)
    assert passed is False
    assert sorted(f.path for f in findings) == [
        "tests/security/other_test.py",
        "tools/p1/guard_copy.py",
    ]


def test_the_real_guard_file_is_exempt(tmp_path: Path) -> None:
    _write(tmp_path, "tools/p1/guard.py", "import openai\n")
    assert guard.run(tmp_path)[0] is True


def test_github_workflow_files_are_treated_as_manifests(
    tmp_path: Path,
) -> None:
    _write(tmp_path, ".github/workflows/ci.yml", "run: openai deploy\n")

    passed, findings = guard.run(tmp_path)
    assert passed is False
    assert findings[0].path == ".github/workflows/ci.yml"


def test_cache_directories_are_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "tools/__pycache__/mod.cpython-311.py", "import openai\n")
    assert guard.run(tmp_path)[0] is True


def test_scan_on_a_tree_without_any_scan_root_is_clean(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "src/main.py", "import openai\n")
    assert guard.scan(tmp_path) == []


def test_scan_of_an_empty_tree_is_clean(tmp_path: Path) -> None:
    assert guard.scan(tmp_path) == []


def test_findings_by_category_counts_each_category(tmp_path: Path) -> None:
    _write(tmp_path, "tools/a.py", "import openai\nimport anthropic\n")
    _write(tmp_path, "tools/b.py", "import torch\n")

    summary = guard.summary(tmp_path)
    assert summary["result"] == "FAIL"
    assert summary["total_findings"] == 3
    # Only categories that actually occurred are listed; an absent category
    # is not reported as a zero (which would drift with every new pattern).
    assert summary["findings_by_category"] == {
        "inference-runtime": 1,
        "model-sdk": 2,
    }
