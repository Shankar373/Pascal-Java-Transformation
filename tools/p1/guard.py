"""No-LLM / no-probabilistic dependency guard (task E3, ADR 0005).

The rule this enforces, verbatim in intent from ``docs/decisions/0005``:

    CI **fails** if model SDKs, embedding packages, vector-store packages,
    AI endpoints, model-weight files or inference configuration appear in
    product dependencies or deployment manifests.

Two scan scopes are used, with different strictness:

``manifests``
    Dependency and deployment manifests.  Any hit fails — these are machine
    read, so there is no such thing as a benign mention.
``source``
    Product source files.  Any hit fails, except in the two files that must
    necessarily spell the patterns (this module and its test).
``weights``
    Model-weight file extensions.  Presence anywhere outside ``docs/`` fails.

Documentation is **not** scanned: ADR 0005 explicitly states that the rule
governs dependencies and deployment manifests, and a design document that
quotes a forbidden name is not a product violation.  Scanning prose would
make the guard fire on its own rule, which is how such gates rot into being
ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Finding",
    "scan",
    "FORBIDDEN_CATEGORIES",
    "MODEL_WEIGHT_SUFFIXES",
    "ALLOWLIST",
    "MANIFEST_NAMES",
    "SOURCE_SUFFIXES",
    "SCAN_ROOTS",
]

# --------------------------------------------------------------------------
# What is forbidden
# --------------------------------------------------------------------------

#: category -> compiled patterns.  Ordered for deterministic reporting.
FORBIDDEN_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "model-sdk": tuple(
        re.compile(p, re.I)
        for p in (
            r"\bopenai\b", r"\banthropic\b", r"\bcohere\b", r"\bmistralai\b",
            r"\bgroq\b", r"\btogether[_-]?ai\b", r"\bvertex[_-]?ai\b",
            r"\bbedrock\b", r"\bazure[_-]?openai\b", r"\bgenai\b",
        )
    ),
    "llm-framework": tuple(
        re.compile(p, re.I)
        for p in (
            r"\blangchain\b", r"\bllama[_-]?index\b", r"\blanggraph\b",
            r"\bllamaindex\b", r"\bsemantic[_-]?kernel\b",
            r"\btransformers\b", r"\bautogen\b", r"\bcrewai\b",
            r"\bguardrails[_-]?ai\b",
        )
    ),
    "inference-runtime": tuple(
        re.compile(p, re.I)
        for p in (
            r"\bpytorch\b", r"\btorch\b", r"\btensorflow\b", r"\bkeras\b",
            r"\bonnxruntime\b", r"\bollama\b", r"\bcandle\b",
            r"\bctransformers\b", r"\bllama[_-]?cpp\b", r"\bggml\b",
        )
    ),
    "embedding": tuple(
        re.compile(p, re.I)
        for p in (
            r"\bembeddings?\b", r"\btext2vec\b", r"\bsentence[_-]?transformers\b",
            r"\bfastembed\b", r"\bhuggingface\b", r"\bhf[_-]?hub\b",
        )
    ),
    "vector-store": tuple(
        re.compile(p, re.I)
        for p in (
            r"\bchroma\b", r"\bchromadb\b", r"\bpinecone\b", r"\bweaviate\b",
            r"\bqdrant\b", r"\bmilvus\b", r"\bpgvector\b", r"\bfaiss\b",
            r"\bredis[_-]?vl\b", r"\bvector[_-]?store\b", r"\bvector[_-]?db\b",
        )
    ),
    "ai-endpoint": tuple(
        re.compile(p, re.I)
        for p in (
            r"\bapi[_-]?openai[_-]?com\b", r"\banthropic[_-]?ai\b",
            r"\bgenerativelanguage\b", r"\bai\.googleapis\b",
            r"\binference[_-]?endpoint\b", r"\bllm[_-]?api\b",
        )
    ),
    "inference-config": tuple(
        re.compile(p, re.I)
        for p in (
            r"\bmodel\s*[:=]\s*[\"']?[a-z0-9._-]*(gpt|claude|llama|gemini)",
            r"\btemperature\s*[:=]", r"\btop[_-]?p\s*[:=]",
            r"\bmax[_-]?tokens\s*[:=]", r"\bnum[_-]?predict\b",
        )
    ),
    "probabilistic-decision": tuple(
        re.compile(p, re.I)
        for p in (
            r"\bsemantic[_-]?similarity\b", r"\bvector\s+search\b",
            r"\bknn[_-]?search\b", r"\brag\b", r"\bretrieval[_-]?augmented\b",
        )
    ),
}

#: Stable category list, in report order.
FORBIDDEN_CATEGORIES: tuple[str, ...] = tuple(FORBIDDEN_PATTERNS)

#: Extensions that identify a model-weight or inference artefact.
MODEL_WEIGHT_SUFFIXES: tuple[str, ...] = (
    ".safetensors", ".gguf", ".ggml", ".pt", ".pth", ".ckpt", ".onnx",
    ".h5", ".hdf5", ".pb", ".tflite", ".pkl", ".pickle", ".joblib",
    ".npz", ".npy", ".model", ".bin", ".weights", ".msgpack",
)

#: Exact manifest file names (case-insensitive).
MANIFEST_NAMES: frozenset[str] = frozenset({
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
    "pyproject.toml", "setup.py", "setup.cfg", "pipfile", "poetry.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "gradle.properties", "cargo.toml", "cargo.lock", "go.mod", "go.sum",
    "gemfile", "gemfile.lock", "composer.json", "composer.lock",
    "pipfile.lock", "environment.yml", "environment.yaml", "conda.yml",
    "dockerfile", "dockerfile.dev", "dockerfile.prod",
    "chart.yaml", "terraform.tfstate", ".terraform.lock.hcl",
})

#: Manifest *patterns* (glob-ish, matched on the lower-cased path).
MANIFEST_PATTERNS: tuple[str, ...] = (
    "docker-compose*.yml", "docker-compose*.yaml",
    "*.csproj", "*.fsproj", "*.vbproj", "*.nuspec",
    "helm/**/values*.yaml", "helm/**/values*.yml",
    ".github/workflows/*.yml", ".github/workflows/*.yaml",
    ".gitlab-ci*.yml", "azure-pipelines*.yml", "jenkinsfile",
    "*.tf", "*.tfvars",
)

#: Source suffixes scanned as product code.
SOURCE_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".pyi", ".ps1", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts",
    ".tsx", ".jsx", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".cs",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".sql", ".pascal", ".pas",
})

#: Directories never scanned (documentation, fixtures, version control).
SCAN_ROOTS: tuple[str, ...] = ("tools", "tests", "scripts", ".github")

#: Files allowed to contain the patterns because they *are* the guard.
#: The companion test asserts this tuple is exactly these two entries, so the
#: exemption cannot quietly grow.
ALLOWLIST: tuple[str, ...] = (
    "tools/p1/guard.py",
    "tests/security/test_no_llm_guard.py",
)

#: Directories where a model-weight file is expected and harmless.
WEIGHT_EXEMPT_ROOTS: tuple[str, ...] = ("docs",)


@dataclass(frozen=True)
class Finding:
    """One forbidden construct found, with its location."""

    path: str
    line: int
    category: str
    excerpt: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.category}: {self.excerpt}"

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "excerpt": self.excerpt,
            "file": self.path,
            "line": self.line,
        }


def _is_manifest(relative: str) -> bool:
    lowered = relative.lower()
    name = lowered.rsplit("/", 1)[-1]
    if name in MANIFEST_NAMES:
        return True
    for pattern in MANIFEST_PATTERNS:
        if _glob_match(pattern, lowered):
            return True
    return False


def _glob_match(pattern: str, value: str) -> bool:
    """Minimal ``**``/``*`` glob matching (no external dependency)."""

    regex = ""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            regex += "(?:.*/)?"
            index += 3
        elif char == "*":
            regex += "[^/]*"
            index += 1
        elif char == "?":
            regex += "[^/]"
            index += 1
        else:
            regex += re.escape(char)
            index += 1
    return re.fullmatch(regex, value) is not None


def _iter_files(root: Path):
    """Yield ``(relative_posix, absolute)`` for scannable files, sorted."""

    for scan_root in SCAN_ROOTS:
        base = root / scan_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in (".git", "__pycache__", ".pytest_cache", "node_modules")
                   for part in path.parts):
                continue
            yield path.relative_to(root).as_posix(), path


def scan(root: Path | str) -> list[Finding]:
    """Scan *root* for forbidden constructs.  Returns findings, sorted."""

    root = Path(root)
    findings: list[Finding] = []

    for relative, path in _iter_files(root):
        if relative in ALLOWLIST:
            continue
        is_manifest = _is_manifest(relative)
        suffix = path.suffix.lower()
        is_source = suffix in SOURCE_SUFFIXES
        if not is_manifest and not is_source:
            continue

        # Manifests are machine-read and source is code: the same category set
        # applies to both.  Only prose (documentation) is exempt, and prose is
        # outside SCAN_ROOTS entirely.
        categories = FORBIDDEN_CATEGORIES

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            for category in categories:
                for pattern in FORBIDDEN_PATTERNS[category]:
                    match = pattern.search(line)
                    if match:
                        findings.append(Finding(
                            path=relative,
                            line=line_number,
                            category=category,
                            excerpt=line.strip()[:160],
                        ))
                        break  # one finding per line per category

    # Model-weight files anywhere outside docs/.
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in (".git", "__pycache__", ".pytest_cache")
               for part in path.parts):
            continue
        relative = path.relative_to(root).as_posix()
        if any(
            relative == prefix or relative.startswith(prefix + "/")
            for prefix in WEIGHT_EXEMPT_ROOTS
        ):
            continue
        if path.suffix.lower() in MODEL_WEIGHT_SUFFIXES:
            findings.append(Finding(
                path=relative,
                line=0,
                category="model-weight-file",
                excerpt=path.name,
            ))

    findings.sort(key=lambda f: (f.path, f.line, f.category, f.excerpt))
    return findings


def run(root: Path | str) -> tuple[bool, list[Finding]]:
    """Return ``(passed, findings)`` for a gate invocation."""

    findings = scan(root)
    return (not findings), findings


def summary(root: Path | str) -> dict[str, object]:
    """Machine-readable gate summary (stable key order)."""

    passed, findings = run(root)
    by_category: dict[str, int] = {}
    for finding in findings:
        by_category[finding.category] = by_category.get(finding.category, 0) + 1
    return {
        "allowlist": list(ALLOWLIST),
        "categories_scanned": list(FORBIDDEN_CATEGORIES),
        "findings": [f.as_dict() for f in findings],
        "findings_by_category": {k: by_category[k] for k in sorted(by_category)},
        "gate": "no-llm-dependency-guard",
        "result": "PASS" if passed else "FAIL",
        "rule": "ADR 0005 / P1 task E3",
        "scanned_roots": list(SCAN_ROOTS),
        "total_findings": len(findings),
    }
