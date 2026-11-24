"""THIRD_PARTY_NOTICES.md must match the pinned dependencies."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "release"))

import generate_notices  # noqa: E402

NOTICES = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")


def _pins(path):
    return generate_notices.read_pins(REPO / path)


@pytest.mark.parametrize("name,version", _pins("requirements-api.txt"))
def test_every_pinned_runtime_dependency_is_noticed(name, version):
    assert re.search(rf"\| {re.escape(name)} \| {re.escape(version)} \|", NOTICES)


def test_every_production_npm_package_has_its_licence_text():
    lock = json.loads((REPO / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    for dep in json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))["dependencies"]:
        version = lock["packages"][f"node_modules/{dep}"]["version"]
        assert f"### {dep} {version} — " in NOTICES


def test_no_notice_entry_is_unresolved():
    assert "LICENSE FILE NOT FOUND" not in NOTICES
    assert "UNKNOWN" not in NOTICES


def test_notices_do_not_claim_a_project_licence():
    assert "no licence has been selected" in NOTICES
    assert not (REPO / "LICENSE").exists(), "a root LICENSE must be added only on the owner's decision"


def test_dev_requirements_are_fully_pinned():
    for line in (REPO / "requirements-dev.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith(("#", "-r")):
            assert "==" in line, line
