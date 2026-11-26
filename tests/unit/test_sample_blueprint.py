"""The UI sample blueprint must stay schema-valid and in step with the pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "fixtures" / "stage1"))

from make_sample import build_sample  # noqa: E402

from p1.schemacheck import validate  # noqa: E402

SAMPLE = REPO / "tests" / "fixtures" / "stage1" / "sample_blueprint.json"
SCHEMA = REPO / "docs" / "stage1" / "schemas" / "application-blueprint.schema.json"


def test_sample_validates_against_the_schema() -> None:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert validate(sample, schema) == []


def test_sample_is_what_the_pipeline_emits_today() -> None:
    """Fails when detectors change; regenerate with ``make_sample.py``."""

    committed = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert build_sample() == committed
