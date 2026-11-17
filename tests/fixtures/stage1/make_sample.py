"""Regenerate ``sample_blueprint.json`` from the real Stage 1 pipeline.

    python tests/fixtures/stage1/make_sample.py

The sample is the blueprint of the enterprise fixture application, so it is
schema-valid by construction and cannot drift from what ``discover`` emits
(``tests/unit/test_sample_blueprint.py`` enforces both).  It is UI test data;
the dashboard never hard-codes any of its values.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "tools"))

from enterprise_app import write_enterprise_app  # noqa: E402

from p1.stage1 import DiscoveryRequest, discover  # noqa: E402

SAMPLE_LABEL = "legacy-pascal-erp"


def build_sample() -> dict:
    with tempfile.TemporaryDirectory(prefix="p1-sample-") as tmp:
        root = Path(tmp)
        app = write_enterprise_app(root / SAMPLE_LABEL)
        result = discover(
            DiscoveryRequest("directory", str(app), label=SAMPLE_LABEL),
            root / "store",
        )
        return result.blueprint


def main() -> int:
    target = HERE / "sample_blueprint.json"
    text = json.dumps(build_sample(), sort_keys=True, indent=2,
                      ensure_ascii=True) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
