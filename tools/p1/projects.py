"""Project roots, entry points, project-file profiles and app shape (B4/B5, C1).

Rules
-----

* **Evidence or no claim.**  Every root, profile field and shape carries the
  file (and line where available) that produced it.
* **Ambiguity is a state, not a guess.**  When several roots compete and no
  project file names a primary, the primary is ``UNKNOWN`` with every
  candidate listed (task B4).
* **Shapes are detected, never assumed convertible.**  A GUI shape is
  recorded with a capability gap, not a promise: P0 proved ``Forms`` is a
  ``FAIL-DEPENDENCY`` fixture, and GUI conversion is out of scope for the
  first release.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .dialects import SourceAnalysis, classify_unit
from .plex import ScanResult

__all__ = [
    "ProjectRoot",
    "Profile",
    "find_project_roots",
    "parse_project_file",
    "apply_source_profile",
    "detect_shape",
    "entry_point",
    "PROGRAM_EXTENSIONS",
    "PACKAGE_EXTENSIONS",
    "META_EXTENSIONS",
]

PROGRAM_EXTENSIONS = (".dpr", ".lpr")
PACKAGE_EXTENSIONS = (".dpk", ".lpk")
META_EXTENSIONS = (".dproj", ".lpi", ".bdsproj", ".groupproj")

#: Units whose presence makes an application a GUI application.
_GUI_UNITS = {
    "vcl": ("forms", "vcl.forms", "controls", "vcl.controls"),
    "lcl": ("interfaces", "lclintf", "lclforms", "lforms"),
    "fmx": ("fmx.forms", "fmx.controls"),
}

#: Units that indicate a Windows service.
_SERVICE_UNITS = ("svcmgr", "svcmanager", "isapiapp", "isapitss")

#: Shapes, in the vocabulary the report uses.
SHAPES = (
    "console",
    "gui_vcl",
    "gui_lcl",
    "gui_fmx",
    "library",
    "package",
    "service",
    "unknown",
)


@dataclass
class Profile:
    """The build/compiler profile tuple (task C1, IR invariants I3/I4).

    Every field is a string so the profile serialises deterministically;
    ``"not-specified"`` means "no directive states it" and is deliberately
    distinct from ``"unknown"`` (could not be determined).
    """

    mode: str = "not-specified"
    defines: list[str] = field(default_factory=list)
    platform: str = "not-specified"
    unit_search_paths: list[str] = field(default_factory=list)
    range_check: str = "not-specified"
    overflow_check: str = "not-specified"
    string_model: str = "not-specified"
    app_type: str = "not-specified"
    output_kind: str = "not-specified"
    evidence: list[dict[str, object]] = field(default_factory=list)
    #: Sources that contributed, in sorted order.
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "app_type": self.app_type,
            "defines": sorted(set(self.defines)),
            "evidence": self.evidence,
            "mode": self.mode,
            "output_kind": self.output_kind,
            "overflow_check": self.overflow_check,
            "platform": self.platform,
            "range_check": self.range_check,
            "sources": sorted(set(self.sources)),
            "string_model": self.string_model,
            "unit_search_paths": sorted(set(self.unit_search_paths)),
        }


@dataclass
class ProjectRoot:
    """One detected project root and everything justified about it."""

    path: str
    kind: str  # "program" | "library" | "package" | "unknown"
    entry_point: str = ""
    meta_files: list[str] = field(default_factory=list)
    evidence: list[dict[str, object]] = field(default_factory=list)
    #: ``SUPPORTED`` (unambiguous) / ``UNKNOWN`` (ambiguous) / ``PARTIAL``.
    status: str = "SUPPORTED"
    primary: bool = False
    shape: str = "unknown"
    shape_evidence: list[dict[str, object]] = field(default_factory=list)
    shape_confidence: str = "low"
    shape_status: str = "UNKNOWN"
    profile: Profile = field(default_factory=Profile)
    diagnostics: list[dict[str, object]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "entry_point": self.entry_point,
            "evidence": self.evidence,
            "kind": self.kind,
            "meta_files": sorted(self.meta_files),
            "path": self.path,
            "primary": self.primary,
            "profile": self.profile.as_dict(),
            "shape": self.shape,
            "shape_confidence": self.shape_confidence,
            "shape_evidence": self.shape_evidence,
            "shape_status": self.shape_status,
            "status": self.status,
        }


# --------------------------------------------------------------------------
# Project file parsing
# --------------------------------------------------------------------------


def _local(tag: str) -> str:
    """Strip an XML namespace from a tag name."""

    return tag.rsplit("}", 1)[-1]


def _find_all(root: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in root.iter() if _local(e.tag) == name]


def parse_project_file(path: str, text: str) -> tuple[Profile, list[dict[str, object]]]:
    """Extract a :class:`Profile` from a ``.dproj``/``.lpi``/``.bdsproj``.

    Returns ``(profile, diagnostics)``.  A malformed project file yields an
    empty profile plus a diagnostic — it never raises, because an unreadable
    project file is degraded discovery, not a fatal error, and IR invariant
    I2 requires the failure to be visible.
    """

    profile = Profile()
    diagnostics: list[dict[str, object]] = []
    if not text.strip():
        diagnostics.append({
            "code": "PROJECT_FILE_EMPTY",
            "message": "project file is empty",
            "file": path,
            "line": 1,
            "column": 1,
        })
        return profile, diagnostics

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        line, column = getattr(exc, "position", (1, 1))
        diagnostics.append({
            "code": "PROJECT_FILE_UNPARSEABLE",
            "message": f"project file is not well-formed XML: {exc}",
            "file": path,
            "line": line,
            "column": column,
        })
        return profile, diagnostics

    profile.sources.append(path)
    evidence = profile.evidence

    def note(field_name: str, value: str, tag: str) -> None:
        evidence.append({
            "evidence": f"{field_name}={value}",
            "source": PurePosixPath(path).name,
            "xml_tag": tag,
        })

    # --- Lazarus (.lpi) ---------------------------------------------------
    for element in _find_all(root, "SyntaxMode"):
        value = (element.get("Value") or "").strip()
        if value:
            profile.mode = value.lower()
            note("mode", value, "CompilerOptions/Parsing/SyntaxMode")
    for element in _find_all(root, "OtherUnitFiles"):
        value = element.get("Value") or ""
        for part in re.split(r"[;]", value):
            part = part.strip()
            if part:
                profile.unit_search_paths.append(part)
        if value:
            note("unit_search_paths", value, "CompilerOptions/SearchPaths/OtherUnitFiles")
    for element in _find_all(root, "CustomOptions"):
        value = element.get("Value") or ""
        for define in re.findall(r"-d([A-Za-z_][A-Za-z0-9_]*)", value):
            profile.defines.append(define)
        for undef in re.findall(r"-u([A-Za-z_][A-Za-z0-9_]*)", value):
            profile.defines = [d for d in profile.defines if d != undef]
        if value:
            note("custom_options", value, "CompilerOptions/Other/CustomOptions")
    for element in _find_all(root, "GraphicApplication"):
        value = (element.get("Value") or "").strip().lower()
        if value in ("true", "false"):
            profile.app_type = "gui" if value == "true" else "console"
            note("app_type", profile.app_type,
                 "CompilerOptions/Linking/Options/Win32/GraphicApplication")
    # <Target><Filename Value="x"/></Target> gives the output name; the
    # generic Filename elements elsewhere (unit list entries) do not.
    targets = [e for e in _find_all(root, "Target")]
    for target in targets:
        for child in target:
            if _local(child.tag) == "Filename":
                value = child.get("Value") or ""
                if value:
                    profile.output_kind = "executable"
                    note("target", value, "CompilerOptions/Target/Filename")

    # --- Delphi (.dproj / .bdsproj) --------------------------------------
    for element in _find_all(root, "MainSource"):
        value = (element.text or "").strip()
        if value:
            note("main_source", value, "PropertyGroup/MainSource")
    for element in _find_all(root, "AppType"):
        value = (element.text or "").strip().lower()
        if value:
            profile.app_type = value
            note("app_type", value, "PropertyGroup/AppType")
    for element in _find_all(root, "FrameworkType"):
        value = (element.text or "").strip().lower()
        if value:
            note("framework_type", value, "PropertyGroup/FrameworkType")
    for element in _find_all(root, "Platform"):
        value = (element.text or "").strip()
        if value:
            profile.platform = value
            note("platform", value, "PropertyGroup/Platform")
    for element in _find_all(root, "DCC_Define"):
        value = (element.text or "").strip()
        if value:
            for define in value.split(";"):
                define = define.strip()
                if define:
                    profile.defines.append(define)
            note("defines", value, "PropertyGroup/DCC_Define")
    for element in _find_all(root, "DCC_UnitSearchPath"):
        value = (element.text or "").strip()
        if value:
            for part in value.split(";"):
                part = part.strip()
                if part:
                    profile.unit_search_paths.append(part)
            note("unit_search_paths", value, "PropertyGroup/DCC_UnitSearchPath")
    for element in _find_all(root, "DCC_ExeOutput"):
        value = (element.text or "").strip()
        if value:
            profile.output_kind = "executable"
            note("exe_output", value, "PropertyGroup/DCC_ExeOutput")
    for element in _find_all(root, "DCC_DcuOutput"):
        value = (element.text or "").strip()
        if value:
            note("dcu_output", value, "PropertyGroup/DCC_DcuOutput")

    # A package project declares it explicitly.
    if _find_all(root, "GenPackage") or any(
        _local(e.tag) == "DCC_OutputExt" and (e.text or "").strip() == "bpl"
        for e in root.iter()
    ):
        profile.output_kind = "package"
        note("output_kind", "package", "GenPackage/DCC_OutputExt")

    profile.defines = sorted(set(profile.defines))
    profile.unit_search_paths = sorted(set(profile.unit_search_paths))
    return profile, diagnostics


# --------------------------------------------------------------------------
# Source-directive enrichment
# --------------------------------------------------------------------------

_PLATFORM_DIRECTIVE_SYMBOLS = {
    "MSWINDOWS": "windows",
    "WIN32": "win32",
    "WIN64": "win64",
    "LINUX": "linux",
    "DARWIN": "macos",
    "UNIX": "unix",
    "MSDOS": "msdos",
    "CPU386": "x86",
    "CPUX86_64": "x86-64",
    "CPUARM": "arm",
}


def apply_source_profile(
    profile: Profile,
    scan: ScanResult | None,
    analysis: SourceAnalysis | None,
    path: str,
) -> None:
    """Overlay source directives onto *profile* (IR invariant I3).

    A project file states the *build's* intent; a directive in the file being
    read states the *unit's* intent.  The directive is therefore applied last,
    and every value it changes is appended to ``evidence`` so the reader can
    see which of the two produced the final figure.  Nothing is inferred: a
    check that no directive mentions stays ``not-specified`` rather than
    being filled in from a remembered compiler default.
    """

    if scan is None:
        return

    source_name = PurePosixPath(path).name

    def note(field_name: str, value: str, detail: str) -> None:
        profile.evidence.append({
            "evidence": detail,
            "field": field_name,
            "source": source_name,
            "value": value,
        })

    for directive in scan.directives:
        name = directive.name
        argument = directive.argument.strip()
        where = f"{source_name}:{directive.line}:{directive.column}"
        detail = f"{{${name} {argument}}} at {where}"

        if name == "MODE" and argument and profile.mode == "not-specified":
            profile.mode = argument.split()[0].lower()
            profile.sources.append(path)
            note("mode", profile.mode, detail)

        elif name == "MODESWITCH" and argument:
            # A mode*switch* alters the allowed syntax, not the mode itself,
            # so it is recorded as evidence without changing `mode`.
            note("modeswitch", argument, detail)
            profile.sources.append(path)

        elif name == "DEFINE" and argument:
            token = argument.split()[0]
            if token and token not in profile.defines:
                profile.defines.append(token)
            profile.sources.append(path)
            note("define", token, detail)

        elif name == "UNDEF" and argument:
            token = argument.split()[0]
            profile.defines = [d for d in profile.defines if d != token]
            profile.sources.append(path)

        elif name in ("R", "RANGECHECKS"):
            if name == "R" and argument in ("+", "-"):
                profile.range_check = "on" if argument == "+" else "off"
                profile.sources.append(path)
                note("range_check", profile.range_check, detail)
            elif name == "RANGECHECKS" and argument:
                profile.range_check = (
                    "on" if argument.upper() in ("ON", "+") else "off"
                )
                profile.sources.append(path)
                note("range_check", profile.range_check, detail)

        elif name == "Q" and argument in ("+", "-"):
            profile.overflow_check = "on" if argument == "+" else "off"
            profile.sources.append(path)
            note("overflow_check", profile.overflow_check, detail)

        elif name == "H" and argument in ("+", "-"):
            profile.string_model = (
                "long" if argument == "+" else "short"
            )
            profile.sources.append(path)
            note("string_model", profile.string_model, detail)

        elif name == "APPTYPE" and argument:
            profile.app_type = argument.strip().lower()
            profile.sources.append(path)
            note("app_type", profile.app_type, detail)

        elif name in ("IFDEF", "IFNDEF") and argument:
            symbol = argument.split()[0].upper()
            platform = _PLATFORM_DIRECTIVE_SYMBOLS.get(symbol)
            if platform and profile.platform == "not-specified":
                profile.platform = platform
                profile.sources.append(path)
                note("platform", platform, detail)

        elif name == "INCLUDE" or name == "I":
            profile.sources.append(path)

    if analysis is not None:
        if profile.output_kind == "not-specified" and analysis.source_kind:
            profile.output_kind = {
                "library": "library",
                "package": "package",
                "program": "executable",
                "unit": "not-specified",
            }.get(analysis.source_kind, "not-specified")
            if profile.output_kind != "not-specified":
                profile.sources.append(path)
        if analysis.mode != "unknown" and profile.mode == "not-specified":
            profile.mode = analysis.mode
            profile.sources.append(path)

    profile.defines = sorted(set(profile.defines))
    profile.sources = sorted(set(profile.sources))


# --------------------------------------------------------------------------
# Root detection
# --------------------------------------------------------------------------


def _stem(path: str) -> str:
    name = PurePosixPath(path).name
    return name.rsplit(".", 1)[0].lower() if "." in name else name.lower()


def find_project_roots(paths: list[str]) -> tuple[list[ProjectRoot], list[dict[str, object]]]:
    """Locate project roots in an inventory of POSIX-relative paths.

    A root is a ``.dpr``/``.lpr``/``.dpk``/``.lpk`` file.  A sibling project
    file with the same stem (``.dproj``/``.lpi``) is attached to it as
    metadata.  A project file with no matching source becomes a root of
    ``kind="unknown"`` with status ``UNKNOWN`` — we know a project is
    declared, but not what its entry point is.
    """

    diagnostics: list[dict[str, object]] = []
    by_stem: dict[str, list[str]] = {}
    for path in sorted(paths):
        by_stem.setdefault(_stem(path), []).append(path)

    roots: list[ProjectRoot] = []
    claimed: set[str] = set()

    for path in sorted(paths):
        lower = path.lower()
        if lower.endswith(PROGRAM_EXTENSIONS):
            kind = "program"
        elif lower.endswith(PACKAGE_EXTENSIONS):
            kind = "package"
        else:
            continue

        root = ProjectRoot(path=path, kind=kind)
        root.evidence.append({
            "evidence": f"entry-point file ({PurePosixPath(path).suffix})",
            "source": PurePosixPath(path).name,
        })
        siblings = [
            p for p in by_stem.get(_stem(path), [])
            if p.lower().endswith(META_EXTENSIONS)
        ]
        for sibling in sorted(siblings):
            root.meta_files.append(sibling)
            claimed.add(sibling)
            root.evidence.append({
                "evidence": f"project metadata {PurePosixPath(sibling).suffix}",
                "source": PurePosixPath(sibling).name,
            })
        roots.append(root)

    # Project files that were not attached to any source file.
    for path in sorted(paths):
        if not path.lower().endswith(META_EXTENSIONS) or path in claimed:
            continue
        root = ProjectRoot(
            path=path,
            kind="unknown",
            status="UNKNOWN",
            evidence=[{
                "evidence": (
                    "project metadata present but no matching "
                    f"{','.join(PROGRAM_EXTENSIONS + PACKAGE_EXTENSIONS)} "
                    "entry-point file"
                ),
                "source": PurePosixPath(path).name,
            }],
        )
        root.diagnostics.append({
            "code": "PROJECT_ENTRY_POINT_MISSING",
            "message": (
                f"{path} declares a project but no entry-point source file "
                "was found; entry point is UNKNOWN"
            ),
            "file": path,
            "line": 1,
            "column": 1,
        })
        roots.append(root)

    # Ambiguity: several roots and no project file naming a primary.
    if len(roots) > 1:
        with_main = [
            r for r in roots if any(
                m.lower().endswith((".dproj", ".lpi")) for m in r.meta_files
            )
        ]
        if len(with_main) == 1:
            with_main[0].primary = True
        else:
            for root in roots:
                root.status = "UNKNOWN"
                root.primary = False
            diagnostics.append({
                "code": "MULTIPLE_PROJECT_ROOTS",
                "message": (
                    f"{len(roots)} candidate project roots and no single "
                    "project file naming a primary; the primary entry point "
                    "is UNKNOWN (candidates: "
                    + ", ".join(sorted(r.path for r in roots))
                    + ")"
                ),
                "line": 1,
                "column": 1,
            })
    elif len(roots) == 1:
        roots[0].primary = True

    return roots, diagnostics


def entry_point(root: ProjectRoot, scan: ScanResult | None,
                analysis: SourceAnalysis | None) -> dict[str, object]:
    """Describe the entry point of *root* with its source span."""

    out: dict[str, object] = {
        "declared_name": "",
        "kind": root.kind,
        "location": "",
        "source": root.path,
        "status": "UNKNOWN",
    }
    if analysis is not None and analysis.declared_name:
        line = column = None
        for token in scan.tokens if scan else []:
            if token.kind == "ident" and token.text == analysis.declared_name:
                line, column = token.line, token.column
                break
        out["declared_name"] = analysis.declared_name
        out["status"] = "SUPPORTED"
        if line is not None:
            out["location"] = f"{root.path}:{line}:{column}"
    elif root.kind == "unknown":
        out["status"] = "UNKNOWN"
    else:
        out["status"] = "PARTIAL"
    return out


# --------------------------------------------------------------------------
# Application shape
# --------------------------------------------------------------------------


def detect_shape(
    root: ProjectRoot,
    scan: ScanResult | None,
    analysis: SourceAnalysis | None,
    profile: Profile,
) -> None:
    """Populate ``root.shape*`` in place from the strongest available evidence."""

    evidence: list[dict[str, object]] = []
    shape = "unknown"
    confidence = "low"

    # 1. Explicit application-type directive or project setting.
    apptypes = (analysis.directives.get("APPTYPE", []) if analysis else [])
    for value in apptypes:
        normalised = value.strip().upper()
        if normalised == "CONSOLE":
            shape, confidence = "console", "high"
            evidence.append({
                "evidence": "{$APPTYPE CONSOLE}",
                "source": PurePosixPath(root.path).name,
            })
        elif normalised in ("WINDOWS", "GUI"):
            shape, confidence = "gui_vcl", "medium"
            evidence.append({
                "evidence": f"{{$APPTYPE {value}}}",
                "source": PurePosixPath(root.path).name,
            })

    if profile.app_type and profile.app_type not in ("not-specified", ""):
        normalised = profile.app_type.lower()
        if normalised in ("console", "gui", "service", "library", "package"):
            mapped = {
                "console": "console",
                "gui": "gui_vcl",
                "service": "service",
                "library": "library",
                "package": "package",
            }[normalised]
            if shape == "unknown":
                shape, confidence = mapped, "medium"
            evidence.append({
                "evidence": f"project AppType={profile.app_type}",
                "source": PurePosixPath(sorted(root.meta_files or [root.path])[0]).name,
            })

    # 2. Source kind wins for library/package.
    if analysis is not None:
        if analysis.source_kind == "library" and shape == "unknown":
            shape, confidence = "library", "high"
            evidence.append({
                "evidence": "source declares `library`",
                "source": PurePosixPath(root.path).name,
            })
        elif analysis.source_kind == "package":
            shape, confidence = "package", "high"
            evidence.append({
                "evidence": "source declares `package`",
                "source": PurePosixPath(root.path).name,
            })

    # 3. Framework units decide the GUI flavour.
    if shape in ("unknown", "gui_vcl"):
        frameworks: dict[str, list[str]] = {}
        if scan is not None:
            for token in scan.tokens:
                if token.kind != "ident":
                    continue
                category, matched = classify_unit(token.text)
                if category in ("vcl", "lcl", "fmx"):
                    frameworks.setdefault(category, []).append(token.text)
        if frameworks:
            # Pick by reference count, tie-broken alphabetically (deterministic).
            best = sorted(
                frameworks.items(), key=lambda kv: (-len(kv[1]), kv[0])
            )[0]
            framework, names = best
            mapped = {"vcl": "gui_vcl", "lcl": "gui_lcl", "fmx": "gui_fmx"}
            if shape == "unknown":
                shape, confidence = mapped[framework], "high"
                evidence.append({
                    "evidence": (
                        f"{framework} framework unit(s) referenced: "
                        + ", ".join(sorted(set(names))[:5])
                    ),
                    "source": PurePosixPath(root.path).name,
                })

    # 4. Windows service indicators.
    if shape == "unknown" and scan is not None:
        low_names = {t.lower for t in scan.tokens if t.kind == "ident"}
        service_hits = sorted(low_names.intersection(_SERVICE_UNITS))
        if service_hits:
            shape, confidence = "service", "medium"
            evidence.append({
                "evidence": "service unit(s): " + ", ".join(service_hits),
                "source": PurePosixPath(root.path).name,
            })

    # 5. A program with no GUI signal is a console application — but only
    #    *medium* confidence, because absence of evidence is not evidence.
    if shape == "unknown" and analysis is not None:
        if analysis.source_kind == "program":
            shape, confidence = "console", "medium"
            evidence.append({
                "evidence": (
                    "declares `program` and references no GUI framework unit"
                ),
                "source": PurePosixPath(root.path).name,
            })

    if shape == "unknown":
        status = "UNKNOWN"
        confidence = "low"
    elif confidence == "high":
        status = "SUPPORTED"
    else:
        status = "PARTIAL"

    root.shape = shape
    root.shape_evidence = evidence
    root.shape_confidence = confidence
    root.shape_status = status
