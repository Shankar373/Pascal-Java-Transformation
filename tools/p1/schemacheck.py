"""A tiny stdlib JSON-Schema validator for the Stage 1 blueprint.

Supports exactly the keywords the blueprint schema uses: ``type``,
``required``, ``properties``, ``items``, ``enum``, ``const``, ``minimum``,
``maximum``, ``pattern``, ``minLength``, ``minItems``, ``maxItems``,
``additionalProperties`` (``false`` or a schema), local ``$ref`` (``#/...``)
and ``oneOf``.  Unknown keywords (``description``, ``$schema``, ``title``,
``$defs`` ...) are ignored, as the specification allows.

It is a test instrument, not a general validator: a ``$ref`` it cannot
resolve raises :class:`SchemaError` rather than being skipped, because a
silently skipped reference would turn the schema into a rubber stamp.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["validate", "SchemaError"]


class SchemaError(ValueError):
    """The *schema* (not the instance) is unusable."""


_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: (
        isinstance(v, (int, float)) and not isinstance(v, bool)
    ),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def validate(instance: Any, schema: dict[str, Any]) -> list[str]:
    """Return a sorted list of ``"<path>: <message>"`` errors (empty = valid)."""

    errors: list[str] = []
    _check(instance, schema, schema, "$", errors)
    return sorted(errors)


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#"):
        raise SchemaError(f"only local $ref is supported, got {ref!r}")
    node: Any = root
    for part in [p for p in ref[1:].split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise SchemaError(f"unresolvable $ref {ref!r}")
        node = node[part]
    if not isinstance(node, dict):
        raise SchemaError(f"$ref {ref!r} does not point at a schema")
    return node


def _same(a: Any, b: Any) -> bool:
    """JSON equality that does not conflate ``True`` with ``1``."""

    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _check_type(value: Any, schema: dict[str, Any], path: str,
                errors: list[str]) -> bool:
    wanted = schema["type"]
    names = wanted if isinstance(wanted, list) else [wanted]
    for name in names:
        check = _TYPE_CHECKS.get(name)
        if check is None:
            raise SchemaError(f"unknown type {name!r}")
        if check(value):
            return True
    errors.append(f"{path}: expected type {wanted}, got {type(value).__name__}")
    return False


def _check_scalar(value: Any, schema: dict[str, Any], path: str,
                  errors: list[str]) -> None:
    if "enum" in schema and not any(_same(value, m) for m in schema["enum"]):
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if "const" in schema and not _same(value, schema["const"]):
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} is above maximum {schema['maximum']}")


def _check_object(value: dict[str, Any], schema: dict[str, Any],
                  root: dict[str, Any], path: str, errors: list[str]) -> None:
    properties = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in value:
            errors.append(f"{path}: missing required property {key!r}")
    for key, item in value.items():
        child = f"{path}.{key}"
        if key in properties:
            _check(item, properties[key], root, child, errors)
            continue
        extra = schema.get("additionalProperties", True)
        if extra is False:
            errors.append(f"{path}: additional property {key!r} is not allowed")
        elif isinstance(extra, dict):
            _check(item, extra, root, child, errors)


def _check_array(value: list[Any], schema: dict[str, Any],
                 root: dict[str, Any], path: str, errors: list[str]) -> None:
    if len(value) < schema.get("minItems", 0):
        errors.append(f"{path}: fewer than minItems {schema['minItems']}")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{path}: more than maxItems {schema['maxItems']}")
    if "items" in schema:
        for index, item in enumerate(value):
            _check(item, schema["items"], root, f"{path}[{index}]", errors)


def _check(value: Any, schema: dict[str, Any], root: dict[str, Any],
           path: str, errors: list[str]) -> None:
    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), root, path, errors)
        return
    if "type" in schema and not _check_type(value, schema, path, errors):
        return
    _check_scalar(value, schema, path, errors)
    if isinstance(value, dict):
        _check_object(value, schema, root, path, errors)
    elif isinstance(value, list):
        _check_array(value, schema, root, path, errors)
    if "oneOf" in schema:
        matches = sum(
            1 for option in schema["oneOf"] if not _sub_errors(value, option, root)
        )
        if matches != 1:
            errors.append(f"{path}: matches {matches} oneOf options, expected 1")


def _sub_errors(value: Any, schema: dict[str, Any],
                root: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _check(value, schema, root, "$", errors)
    return errors
