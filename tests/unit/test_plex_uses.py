"""Regression tests for Delphi ``uses`` clause forms (Stage 1 completion).

The P1 scanner used to reject ``Unit in 'path.pas'`` (every ``.dpr``) and
dotted unit names (``System.SysUtils``), dropping the whole clause — which
hid unresolved units from the blueprint.  These tests pin the fixed behaviour
and that genuinely malformed clauses are still reported, not accepted.
"""

from __future__ import annotations

import pytest

from p1.plex import scan


def _units(text: str) -> list[list[str]]:
    return [[item.name for item in clause.items]
            for clause in scan(text, path="t.dpr").uses]


def _codes(text: str) -> list[str]:
    return [d["code"] for d in scan(text, path="t.dpr").diagnostics]


def test_in_clause_with_form_comment_is_parsed() -> None:
    text = (
        "program P;\nuses\n  Forms,\n"
        "  MainForm in 'src/MainForm.pas' {FormMain},\n"
        "  uDM in 'src/uDM.pas' {DM: TDataModule},\n  uX;\nbegin end.\n"
    )
    assert _units(text) == [["Forms", "MainForm", "uDM", "uX"]]
    assert _codes(text) == []


def test_dotted_unit_names_are_parsed() -> None:
    text = "unit U;\ninterface\nuses System.SysUtils, FireDAC.Comp.Client;\n"
    assert _units(text) == [["System.SysUtils", "FireDAC.Comp.Client"]]
    assert _codes(text) == []


def test_dotted_and_in_together() -> None:
    text = "program P;\nuses Vendor.Core in 'v\core.pas', A;\nbegin end.\n"
    assert _units(text) == [["Vendor.Core", "A"]]


@pytest.mark.parametrize("text", [
    "uses A in B;\n",            # `in` must be followed by a string
    "uses A in 'x' 'y';\n",      # two paths
    "uses A. ;\n",               # dangling dot
    "uses A in 'x' in 'y';\n",   # repeated in
    "uses 'x';\n",               # string without a unit
])
def test_malformed_clauses_are_still_reported(text: str) -> None:
    assert "USES_MALFORMED" in _codes(text)
