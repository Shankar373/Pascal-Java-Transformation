"""Unit tests for the tiny stdlib JSON-Schema validator (``p1.schemacheck``).

The validator exists so the tests can prove two things about the blueprint:
every generated document validates, and a *mutated* document is rejected.
That second property is only meaningful if the validator itself rejects each
class of mutation, so every keyword it supports is tested both ways here.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from p1.schemacheck import SchemaError, validate


def _errors(instance: Any, schema: dict[str, Any]) -> list[str]:
    return validate(instance, schema)


# --- type -------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema_type, good, bad",
    [
        ("string", "x", 1),
        ("integer", 3, 3.5),
        ("number", 3.5, "3"),
        ("boolean", True, 1),
        ("array", [], {}),
        ("object", {}, []),
        ("null", None, 0),
    ],
)
def test_type_accepts_and_rejects(schema_type: str, good: Any, bad: Any) -> None:
    schema = {"type": schema_type}
    assert _errors(good, schema) == []
    assert _errors(bad, schema)


def test_bool_is_not_an_integer_or_number() -> None:
    assert _errors(True, {"type": "integer"})
    assert _errors(False, {"type": "number"})


def test_type_list_accepts_any_member() -> None:
    schema = {"type": ["string", "null"]}
    assert _errors(None, schema) == []
    assert _errors("a", schema) == []
    assert _errors(1, schema)


# --- required / properties / additionalProperties -----------------------------


def test_required_reports_the_missing_key_with_its_path() -> None:
    schema = {"type": "object", "required": ["a"],
              "properties": {"a": {"type": "integer"}}}
    errors = _errors({}, schema)
    assert errors and "$" in errors[0] and "a" in errors[0]


def test_properties_recurse_and_report_nested_paths() -> None:
    schema = {"type": "object", "properties": {
        "outer": {"type": "object", "properties": {"n": {"type": "integer"}}}}}
    errors = _errors({"outer": {"n": "x"}}, schema)
    assert len(errors) == 1
    assert errors[0].startswith("$.outer.n")


def test_additional_properties_false_rejects_unknown_keys() -> None:
    schema = {"type": "object", "properties": {"a": {}},
              "additionalProperties": False}
    assert _errors({"a": 1}, schema) == []
    errors = _errors({"a": 1, "zzz": 2}, schema)
    assert errors and "zzz" in errors[0]


def test_additional_properties_schema_applies_to_extra_keys() -> None:
    schema = {"type": "object", "additionalProperties": {"type": "integer"}}
    assert _errors({"a": 1, "b": 2}, schema) == []
    assert _errors({"a": 1, "b": "x"}, schema)


# --- items / array bounds -----------------------------------------------------


def test_items_validate_every_element_with_index_in_path() -> None:
    schema = {"type": "array", "items": {"type": "integer"}}
    errors = _errors([1, "x", 3, "y"], schema)
    assert [e.split(":")[0] for e in errors] == ["$[1]", "$[3]"]


def test_min_and_max_items() -> None:
    schema = {"type": "array", "minItems": 1, "maxItems": 2}
    assert _errors([1], schema) == []
    assert _errors([], schema)
    assert _errors([1, 2, 3], schema)


# --- enum / const / pattern / bounds ------------------------------------------


def test_enum_and_const() -> None:
    assert _errors("a", {"enum": ["a", "b"]}) == []
    assert _errors("c", {"enum": ["a", "b"]})
    assert _errors(1, {"const": 1}) == []
    assert _errors(2, {"const": 1})


def test_const_distinguishes_bool_from_int() -> None:
    assert _errors(True, {"const": 1})
    assert _errors(1, {"const": True})


def test_pattern_is_a_search_anchored_by_the_schema_author() -> None:
    schema = {"type": "string", "pattern": "^CP-[0-9a-f]{12}$"}
    assert _errors("CP-0123456789ab", schema) == []
    assert _errors("CP-xyz", schema)
    assert _errors("xCP-0123456789ab", schema)


def test_minimum_maximum_and_min_length() -> None:
    assert _errors(5, {"type": "integer", "minimum": 0, "maximum": 10}) == []
    assert _errors(-1, {"type": "integer", "minimum": 0})
    assert _errors(11, {"type": "integer", "maximum": 10})
    assert _errors("", {"type": "string", "minLength": 1})
    assert _errors("a", {"type": "string", "minLength": 1}) == []


# --- $ref / oneOf --------------------------------------------------------------


def test_local_ref_resolves_through_defs() -> None:
    schema = {
        "$defs": {"count": {"type": "integer", "minimum": 0}},
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/count"}},
    }
    assert _errors({"a": 1}, schema) == []
    assert _errors({"a": -1}, schema)


def test_unresolvable_or_remote_ref_is_a_schema_error() -> None:
    with pytest.raises(SchemaError):
        validate({}, {"$ref": "#/$defs/missing"})
    with pytest.raises(SchemaError):
        validate({}, {"$ref": "http://example.com/x.json"})


def test_one_of_requires_exactly_one_match() -> None:
    schema = {"oneOf": [{"type": "integer"}, {"type": "string"}]}
    assert _errors(1, schema) == []
    assert _errors("a", schema) == []
    assert _errors(1.5, schema)
    both = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
    assert _errors(1, both)  # matches both -> invalid


# --- mutation rejection on a realistic document -----------------------------


_SCHEMA = {
    "type": "object",
    "required": ["name", "tags", "size"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "tags": {"type": "array", "items": {"enum": ["a", "b"]}},
        "size": {"type": "integer", "minimum": 0},
    },
}
_DOC = {"name": "x", "tags": ["a", "b"], "size": 3}


def test_document_validates_unmutated() -> None:
    assert _errors(_DOC, _SCHEMA) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("name"),
        lambda d: d.__setitem__("size", "3"),
        lambda d: d.__setitem__("size", -1),
        lambda d: d["tags"].append("zzz"),
        lambda d: d.__setitem__("extra", 1),
        lambda d: d.__setitem__("name", ""),
    ],
)
def test_every_mutation_is_rejected(mutate: Any) -> None:
    doc = copy.deepcopy(_DOC)
    mutate(doc)
    assert _errors(doc, _SCHEMA)
