"""Capability status vocabulary for P1.

The vocabulary is fixed by the master prompt and ``docs/p0/FEASIBILITY_REPORT.md``:

``SUPPORTED``
    The capability is implemented here and exercised by a passing test in this
    repository.
``PARTIAL``
    Implemented for a documented subset, or heuristic; the gap is named.
``UNSUPPORTED``
    Deliberately not attempted in this phase.
``UNAVAILABLE``
    The tool, credential or owner decision required does not exist here.
``UNKNOWN``
    Cannot be determined from the evidence available.

``VERIFIED`` is deliberately **absent**: it requires original-vs-Java
differential tests and is unreachable before P3 (``P1_TASKS.md`` §F).
Producing it here would be a false claim, so :func:`validate_status` rejects it.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple

__all__ = [
    "SUPPORTED",
    "PARTIAL",
    "UNSUPPORTED",
    "UNAVAILABLE",
    "UNKNOWN",
    "STATUSES",
    "VERIFIED_FORBIDDEN",
    "CapabilityState",
    "validate_status",
    "evidence_required_for",
]

SUPPORTED = "SUPPORTED"
PARTIAL = "PARTIAL"
UNSUPPORTED = "UNSUPPORTED"
UNAVAILABLE = "UNAVAILABLE"
UNKNOWN = "UNKNOWN"

#: The complete, closed vocabulary.  Anything else is a programming error.
STATUSES: tuple[str, ...] = (SUPPORTED, PARTIAL, UNSUPPORTED, UNAVAILABLE, UNKNOWN)

#: Never emitted by P1; listed so the rejection is explicit rather than implicit.
VERIFIED_FORBIDDEN = "VERIFIED"


class CapabilityState(NamedTuple):
    """A capability is always a ``(construct, mode, platform)`` triple (IR I4).

    ``mode`` and ``platform`` are ``"any"`` when the dimension does not apply;
    they are never omitted, so two states that differ only by platform can
    never collide into one row.
    """

    construct: str
    mode: str
    platform: str
    status: str
    evidence: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "construct": self.construct,
            "mode": self.mode,
            "platform": self.platform,
            "status": self.status,
            "evidence": self.evidence,
        }


def validate_status(status: str) -> str:
    """Return ``status`` if it is in the vocabulary, else raise ``ValueError``.

    ``VERIFIED`` raises with an explanation rather than a generic message,
    because it is the one value most likely to be added by mistake.
    """

    if status == VERIFIED_FORBIDDEN:
        raise ValueError(
            "VERIFIED is not reachable in P1: it requires original-vs-Java "
            "differential tests (P3). Use SUPPORTED/PARTIAL/UNSUPPORTED/"
            "UNAVAILABLE/UNKNOWN instead."
        )
    if status not in STATUSES:
        raise ValueError(
            f"unknown capability status {status!r}; expected one of {STATUSES}"
        )
    return status


def evidence_required_for(status: str) -> bool:
    """``SUPPORTED``/``PARTIAL`` must cite evidence; the rest must not invent any.

    ``UNKNOWN`` and ``UNAVAILABLE`` are honest absences of evidence and are
    allowed to carry an empty string.  ``UNSUPPORTED`` is a deliberate scope
    decision, likewise.
    """

    validate_status(status)
    return status in (SUPPORTED, PARTIAL)


def validate_states(states: Iterable[CapabilityState]) -> list[CapabilityState]:
    """Validate a batch and assert the evidence rule (D3: no claim without proof)."""

    out: list[CapabilityState] = []
    seen: set[tuple[str, str, str]] = set()
    for state in states:
        validate_status(state.status)
        if evidence_required_for(state.status) and not state.evidence.strip():
            raise ValueError(
                f"capability {state.construct!r} ({state.mode}/{state.platform}) "
                f"is {state.status} but cites no evidence"
            )
        key = (state.construct, state.mode, state.platform)
        if key in seen:
            raise ValueError(
                f"duplicate capability state for {key!r}; states must be unique "
                "per (construct, mode, platform)"
            )
        seen.add(key)
        out.append(state)
    return out
