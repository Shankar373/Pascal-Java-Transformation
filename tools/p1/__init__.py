"""P1 — secure ingestion and Pascal application discovery.

Deterministic, standard-library-only implementation.  See
``docs/p1/P1_IMPLEMENTATION_PLAN.md`` for the design and
``docs/p0/P1_TASKS.md`` for the task/acceptance mapping.

This package contains no probabilistic, learned or externally-inferred
component of any kind: every result is a deterministic function of the input
bytes (ADR 0005).
"""

__all__ = ["__version__"]

#: Package version.  Bumped when an emitted schema changes.
__version__ = "1.0.0"
