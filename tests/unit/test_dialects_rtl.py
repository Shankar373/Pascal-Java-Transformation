"""Stock Delphi units must classify as RTL; customer namespaces must not."""

from __future__ import annotations

import pytest

from p1.dialects import classify_unit


@pytest.mark.parametrize("name, category", [
    ("SOAPHTTPClient", "delphi-rtl"),
    ("Soap.SOAPHTTPClient", "delphi-rtl"),
    ("InvokeRegistry", "delphi-rtl"),
    ("Xml.XMLDoc", "delphi-rtl"),
    ("Rest.Client", "delphi-rtl"),
    ("SvcMgr", "windows-platform"),
    ("Vcl.SvcMgr", "windows-platform"),
    ("System.Win.ComObj", "windows-platform"),
])
def test_stock_units_are_classified(name: str, category: str) -> None:
    assert classify_unit(name)[0] == category


@pytest.mark.parametrize("name", [
    "Web.Core", "Xml.Custom", "Rest.Internal.Thing", "Soap.Vendor",
    "Datasnap.Private", "Acme.Billing",
])
def test_customer_namespaces_are_not_assumed_rtl(name: str) -> None:
    """A whole-namespace rule would hide a genuinely missing customer unit."""

    assert classify_unit(name) == ("unresolved", "")
