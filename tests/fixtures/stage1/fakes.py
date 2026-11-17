"""Test doubles for the dashboard: a fake ``discover`` and the sample blueprint.

The fake mirrors the contract in design section 7 (progress callback, a result
with ``checkpoint`` / ``outdir`` / ``blueprint`` / ``outputs`` / ``reused``)
and writes the same artefacts the real orchestrator writes, so the job
manager and the server read them exactly as they would in production.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SAMPLE_PATH = Path(__file__).resolve().parent / "sample_blueprint.json"
STEP_IDS = ("ingestion", "checkpoint", "scanning_inventory", "dependency_analysis", "blueprint")
SAMPLE_REPORT = "# Discovery report\n\nSample report for dashboard tests.\n"


def load_sample() -> dict[str, Any]:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class FakeCheckpoint:
    checkpoint_id: str

    def as_dict(self) -> dict[str, Any]:
        return {"checkpoint_id": self.checkpoint_id}


@dataclass(frozen=True)
class FakeResult:
    checkpoint: FakeCheckpoint
    outdir: Path
    blueprint: dict[str, Any]
    outputs: dict[str, str]
    reused: bool = False


def write_artifacts(outdir: Path, blueprint: dict[str, Any]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "application-blueprint.json").write_text(
        json.dumps(blueprint, sort_keys=True), encoding="utf-8")
    (outdir / "discovery-report.md").write_bytes(SAMPLE_REPORT.encode("utf-8"))
    (outdir / "unresolved-dependencies.json").write_text(
        json.dumps({"schema_version": "stage1.unresolved/1.0",
                    "count": len(blueprint["unresolved"]), "items": blueprint["unresolved"]}),
        encoding="utf-8")
    (outdir / "diagnostics.json").write_text(
        json.dumps({"schema_version": "stage1.diagnostics/1.0",
                    "counts": blueprint["summary"]["diagnostics"], "items": blueprint["diagnostics"]}),
        encoding="utf-8")
    (outdir / "inventory.csv").write_text(
        "path,class,extension,size,sha256,encoding,analysis_blocker\n", encoding="utf-8")


def make_fake_discover(
    blueprint: dict[str, Any] | None = None,
    error: BaseException | None = None,
    gate: threading.Event | None = None,
    calls: list[Any] | None = None,
) -> Callable[..., FakeResult]:
    """Build a ``discover`` stand-in; *gate* blocks it until set, *error* raises."""

    sample = blueprint if blueprint is not None else load_sample()
    checkpoint_id = sample["project"]["checkpoint"]["id"]

    def fake_discover(request: Any, store: Path, *, progress: Any = None, **_: Any) -> FakeResult:
        if calls is not None:
            calls.append(request)
        emit = progress or (lambda *_args: None)
        emit(STEP_IDS[0], "running", "validating input")
        if gate is not None:
            gate.wait(10)
        if error is not None:
            raise error
        emit(STEP_IDS[0], "completed", "input accepted")
        for step in STEP_IDS[1:]:
            emit(step, "running", "")
            emit(step, "warning" if step == "dependency_analysis" else "completed", "done")
        outdir = Path(store) / "discoveries" / checkpoint_id
        write_artifacts(outdir, sample)
        return FakeResult(FakeCheckpoint(checkpoint_id), outdir, sample, {}, False)

    return fake_discover
