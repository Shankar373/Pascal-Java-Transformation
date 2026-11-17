"""Builders shared by the Stage 1 detector tests (inventory, integrations,
libraries, runtime dependencies).

``analyse`` turns a ``{path: content}`` mapping into exactly what the
detectors receive in production: a list of :class:`~p1.model.AnalysedFile`
produced by :func:`p1.pipeline.analyse_tree` plus the ``text_of`` mapping
built with the documented contract (``p1.inventory.wants_text``).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Mapping

from p1.errors import DiagnosticSink
from p1.inventory import wants_text
from p1.limits import DEFAULT_LIMITS
from p1.model import AnalysedFile, ingest_directory
from p1.pipeline import _decode, analyse_tree

SECRET = "S3cr3t!Pass"


class Estate:
    """An analysed tree plus its ``text_of`` index."""

    def __init__(self, root: Path, analysed: list[AnalysedFile],
                 text_of: dict[str, str], files: list[Any]) -> None:
        self.root = root
        self.analysed = analysed
        self.text_of = text_of
        self.files = files

    def shuffled(self, seed: int) -> list[AnalysedFile]:
        items = list(self.analysed)
        random.Random(seed).shuffle(items)
        return items


def analyse(root: Path, files: Mapping[str, str | bytes]) -> Estate:
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / Path(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            content if isinstance(content, bytes) else content.encode("utf-8")
        )
    ingestion = ingest_directory(root, origin="t", skip=(".git",))
    analysed = analyse_tree(ingestion, DEFAULT_LIMITS, DiagnosticSink())
    text_of: dict[str, str] = {}
    for item in analysed:
        if wants_text(item) and item.inventory.size <= (
            DEFAULT_LIMITS.max_source_bytes
        ):
            data = (root / item.path).read_bytes()
            text_of[item.path] = _decode(data, item.encoding)
    return Estate(root, analysed, text_of, ingestion.files)


def dump_all(*findings_lists: list[Any]) -> str:
    """Serialise findings the way the blueprint will (``as_dict``)."""

    return json.dumps(
        [f.as_dict() for lst in findings_lists for f in lst],
        sort_keys=True,
    )


def assert_well_formed(findings: list[Any]) -> None:
    """Every finding has located, bounded evidence and a non-final status."""

    for finding in findings:
        data = finding.as_dict()
        assert data["evidence"], data
        assert len(data["evidence"]) <= 25
        assert data["status"] in ("PARTIAL", "UNKNOWN")
        for ev in data["evidence"]:
            assert ev["file"] and not ev["file"].startswith("/")
            assert ":" not in ev["file"][:3]
            assert ev["line"] >= 0
            assert len(ev["text"]) <= 120
        if "endpoints" in data:
            assert len(data["endpoints"]) <= 20


_CACHE: dict[str, Estate] = {}


def enterprise(tmp_path_factory: Any) -> Estate:
    """The shared enterprise fixture app, analysed once per session."""

    if "enterprise" not in _CACHE:
        from fixtures.stage1.enterprise_app import ENTERPRISE_APP

        root = tmp_path_factory.mktemp("enterprise")
        _CACHE["enterprise"] = analyse(root / "app", ENTERPRISE_APP)
    return _CACHE["enterprise"]


def pas(name: str, uses: str = "", body: str = "", decl: str = "") -> str:
    """A minimal well-formed unit with a ``uses`` clause and a body."""

    clause = f"uses\n  {uses};\n" if uses else ""
    return (
        f"unit {name};\n\ninterface\n\n{clause}\n{decl}\n"
        f"implementation\n\n{body}\n\nend.\n"
    )
