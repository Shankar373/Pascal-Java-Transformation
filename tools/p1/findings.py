"""Typed findings shared by the Stage 1 detectors and the blueprint.

Every Stage 1 detector returns instances of the dataclasses below, and the
blueprint serialises them with :meth:`as_dict`.  Keeping the shapes in one
module means a detector and the blueprint cannot drift apart: a field added
here is visible to both, and a test can assert the full key set.

Rules every finding obeys (the "evidence-backed" requirement):

* **Evidence is mandatory.**  A finding with no :class:`Evidence` is a bug;
  :func:`require_evidence` is the one place that enforces it.
* **Evidence is redacted.**  ``Evidence.text`` is a short excerpt and never
  carries a credential — callers pass it through ``metadata._redact`` first.
* **Deterministic.**  ``as_dict`` returns plain, sorted-key-friendly values
  (no sets, no tuples-of-tuples, no clocks, no absolute paths).
* **Detection is not support.**  ``status`` is one of the capability states
  from :mod:`p1.statuses`; detectors emit ``PARTIAL`` or ``UNKNOWN`` and never
  ``SUPPORTED``/``VERIFIED`` for an inferred fact.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Evidence",
    "DirectoryEntry",
    "BuildScriptFinding",
    "CompilerConfigFinding",
    "IntegrationFinding",
    "LibraryFinding",
    "RuntimeDependencyFinding",
    "require_evidence",
    "CONFIDENCE_LEVELS",
    "INTEGRATION_CATEGORIES",
    "LIBRARY_CATEGORIES",
    "LIBRARY_ORIGINS",
    "RUNTIME_KINDS",
    "BUILD_SCRIPT_KINDS",
    "COMPILER_CONFIG_KINDS",
]

CONFIDENCE_LEVELS = ("high", "medium", "low")

#: Closed vocabularies.  Adding a value is a schema change (the blueprint
#: schema enumerates them and a test asserts the two agree).
INTEGRATION_CATEGORIES = (
    "com-ole",
    "dcom",
    "email",
    "file-exchange",
    "ftp",
    "http-client",
    "http-server",
    "ldap",
    "messaging",
    "printing",
    "reporting",
    "rpc",
    "scheduled-job",
    "serial-port",
    "soap-webservice",
    "socket",
    "windows-service",
)

LIBRARY_CATEGORIES = (
    "compression",
    "crypto",
    "database",
    "framework",
    "json-xml",
    "networking",
    "other",
    "reporting",
    "rtl",
    "ui-components",
    "utility",
)

#: ``bundled``  – source/binary present in the ingested input.
#: ``external`` – a known third-party library that is not in the input.
#: ``rtl``      – standard Delphi/FPC runtime library (absent by design).
#: ``framework``– VCL / FMX / LCL.
#: ``unresolved`` – referenced, not in the input, not recognised.
LIBRARY_ORIGINS = ("bundled", "external", "framework", "rtl", "unresolved")

RUNTIME_KINDS = (
    "bpl-package",
    "com-component",
    "configuration-file",
    "data-file",
    "database-client",
    "dll",
    "environment-variable",
    "hardcoded-path",
    "registry-key",
    "runtime-library",
    "service",
)

BUILD_SCRIPT_KINDS = (
    "batch",
    "ci-config",
    "dcc-command-line",
    "installer",
    "lazbuild",
    "makefile",
    "msbuild",
    "powershell",
    "shell",
)

COMPILER_CONFIG_KINDS = (
    "dcc-cfg",
    "delphi-options",
    "delphi-project",
    "fpc-cfg",
    "lazarus-project",
    "other-cfg",
)


@dataclass(frozen=True)
class Evidence:
    """One located, redacted observation backing a finding."""

    file: str
    line: int = 0
    column: int = 0
    #: Short excerpt (at most 120 characters), credential-redacted.
    text: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "column": self.column,
            "file": self.file,
            "line": self.line,
            "text": self.text[:120],
        }


def require_evidence(evidence: tuple[Evidence, ...], what: str) -> None:
    """Raise when a finding would be emitted without any evidence."""

    if not evidence:
        raise ValueError(f"finding {what!r} has no evidence")


def _ev(evidence: tuple[Evidence, ...]) -> list[dict[str, object]]:
    ordered = sorted(
        evidence, key=lambda e: (e.file, e.line, e.column, e.text)
    )
    return [e.as_dict() for e in ordered]


@dataclass(frozen=True)
class DirectoryEntry:
    """One directory of the ingested tree (including empty ones)."""

    path: str  # POSIX, relative; "" is never emitted (the root is implicit)
    depth: int  # 1 for a top-level directory
    file_count: int  # files directly inside
    total_file_count: int  # files in the whole subtree
    total_bytes: int  # bytes in the whole subtree
    empty: bool  # no files anywhere in the subtree

    def as_dict(self) -> dict[str, object]:
        return {
            "depth": self.depth,
            "empty": self.empty,
            "file_count": self.file_count,
            "path": self.path,
            "total_bytes": self.total_bytes,
            "total_file_count": self.total_file_count,
        }


@dataclass(frozen=True)
class BuildScriptFinding:
    """A build, packaging or CI script and what it invokes."""

    path: str
    kind: str  # BUILD_SCRIPT_KINDS
    #: Tool names invoked, e.g. ``("dcc32", "msbuild")`` (sorted, unique).
    tools: tuple[str, ...] = ()
    #: Project files (paths inside the input) the script references.
    referenced_projects: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    confidence: str = "medium"
    status: str = "PARTIAL"

    def as_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "evidence": _ev(self.evidence),
            "kind": self.kind,
            "path": self.path,
            "referenced_projects": sorted(set(self.referenced_projects)),
            "status": self.status,
            "tools": sorted(set(self.tools)),
        }


@dataclass(frozen=True)
class CompilerConfigFinding:
    """A compiler configuration file and the switches it states."""

    path: str
    kind: str  # COMPILER_CONFIG_KINDS
    #: ``"global"`` configs apply to a whole folder tree, ``"project"`` to one.
    scope: str = "project"
    #: ``(switch, value)`` pairs, in file order, e.g. ``("-U", "..\\lib")``.
    switches: tuple[tuple[str, str], ...] = ()
    defines: tuple[str, ...] = ()
    search_paths: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    confidence: str = "medium"
    status: str = "PARTIAL"

    def as_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "defines": sorted(set(self.defines)),
            "evidence": _ev(self.evidence),
            "kind": self.kind,
            "path": self.path,
            "scope": self.scope,
            "search_paths": sorted(set(self.search_paths)),
            "status": self.status,
            "switches": [[name, value] for name, value in self.switches],
        }


@dataclass(frozen=True)
class IntegrationFinding:
    """An external integration the application talks to or exposes."""

    category: str  # INTEGRATION_CATEGORIES
    technology: str  # e.g. "Indy", "Synapse", "MSXML", "Winsock", "TService"
    #: Hosts / URLs / queue names found in literals (credentials redacted).
    endpoints: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    confidence: str = "low"
    status: str = "PARTIAL"

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "endpoints": sorted(set(self.endpoints)),
            "evidence": _ev(self.evidence),
            "status": self.status,
            "technology": self.technology,
        }


@dataclass(frozen=True)
class LibraryFinding:
    """A library the application depends on (source, binary or by reference)."""

    name: str  # canonical, e.g. "VCL", "Indy", "DevExpress"
    category: str  # LIBRARY_CATEGORIES
    origin: str  # LIBRARY_ORIGINS
    vendor: str = ""
    #: Unit names (lower-case) that evidence the library.
    units: tuple[str, ...] = ()
    #: Input files that reference it.
    referenced_by: tuple[str, ...] = ()
    #: ``True`` when the library's source/binary is present in the input.
    resolved: bool = False
    evidence: tuple[Evidence, ...] = ()
    confidence: str = "medium"
    status: str = "PARTIAL"

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "evidence": _ev(self.evidence),
            "name": self.name,
            "origin": self.origin,
            "referenced_by": sorted(set(self.referenced_by)),
            "resolved": self.resolved,
            "status": self.status,
            "units": sorted(set(self.units)),
            "vendor": self.vendor,
        }


@dataclass(frozen=True)
class RuntimeDependencyFinding:
    """Something the running application needs that is not Pascal source."""

    kind: str  # RUNTIME_KINDS
    name: str
    required_by: tuple[str, ...] = ()
    #: ``True`` when the named artefact exists in the ingested input.
    resolved_in_input: bool = False
    evidence: tuple[Evidence, ...] = ()
    confidence: str = "medium"
    status: str = "PARTIAL"

    def as_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "evidence": _ev(self.evidence),
            "kind": self.kind,
            "name": self.name,
            "required_by": sorted(set(self.required_by)),
            "resolved_in_input": self.resolved_in_input,
            "status": self.status,
        }

