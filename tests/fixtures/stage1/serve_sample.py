"""Run the dashboard with a fake ``discover`` for manual and visual checks.

    python tests/fixtures/stage1/serve_sample.py [--port 8765] [--store DIR]

A completed job is pre-seeded and its id is logged, so the blueprint view can
be opened directly at ``http://127.0.0.1:<port>/?job=<id>``.  Submitting a new
discovery from the page also works and returns the sample blueprint.
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "tools"))

from fakes import make_fake_discover  # noqa: E402
from p1.jobs import JobRequest  # noqa: E402
from p1.server import create_app  # noqa: E402

LOG = logging.getLogger("serve_sample")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--store", default=None)
    parser.add_argument("--local-root", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    store = Path(args.store) if args.store else Path(tempfile.mkdtemp(prefix="p1-sample-"))
    roots = [Path(args.local_root)] if args.local_root else []
    app = create_app(store, "127.0.0.1", args.port, roots, False, make_fake_discover())
    job_id = app.jobs.submit(JobRequest(kind="git", source="https://git.example.com/legacy/pascal-erp.git",
                                        ref="main"))
    while app.jobs.status(job_id) not in ("completed", "failed"):
        time.sleep(0.05)
    host, port = app.server_address
    LOG.info("seeded job %s -> http://%s:%s/?job=%s", job_id, host, port, job_id)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
