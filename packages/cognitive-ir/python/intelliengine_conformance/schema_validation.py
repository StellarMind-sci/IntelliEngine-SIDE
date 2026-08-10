from __future__ import annotations

import math
import re
from typing import Any

from .json_codec import canonicalize


class SchemaValidationError(ValueError):
    pass


def _pointer(root: Any, fragment: str) -> Any:
    if fragment == "#":
        return root
    if not fragment.startswith("#/"):
        raise SchemaValidationError("only local JSON Pointer references are supported")
    value = root
    for token in fragment[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _type_matches(instance: Any, expected: str) -> bool:
    numeric = isinstance(instance, (int, float)) and not isinstance(instance, bool)
    finite_numeric = numeric and (not isinstance(instance, float) or math.isfinite(instance))
    return {
        "null": instance is None,
        "boolean": isinstance(instance, bool),
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "number": finite_numeric,
        "integer": finite_numeric and (isinstance(instance, int) or instance.is_integer()),
        "string": isinstance(instance, str),
    }.get(expected, False)


def is_valid(instance: Any, schema: Any, root_schema: Any | None = None) -> bool:
    root = schema if root_schema is None else root_schema
    if isinstance(schema, bool):
        return schema
    if not isinstance(schema, dict):
        return False
    if "$ref" in schema and not is_valid(instance, _pointer(root, schema["$ref"]), root):
        return False
    if "type" in schema:
        declared = schema["type"]
        types = declared if isinstance(declared, list) else [declared]
        if not any(_type_matches(instance, item) for item in types):
            return False
    if "const" in schema and canonicalize(instance) != canonicalize(schema["const"]):
        return False
    if "enum" in schema and not any(canonicalize(instance) == canonicalize(item) for item in schema["enum"]):
        return False
    if "allOf" in schema and not all(is_valid(instance, child, root) for child in schema["allOf"]):
        return False
    if "anyOf" in schema and not any(is_valid(instance, child, root) for child in schema["anyOf"]):
        return False
    if "oneOf" in schema and sum(is_valid(instance, child, root) for child in schema["oneOf"]) != 1:
        return False
    if "not" in schema and is_valid(instance, schema["not"], root):
        return False
    if "if" in schema:
        selected = schema.get("then") if is_valid(instance, schema["if"], root) else schema.get("else")
        if selected is not None and not is_valid(instance, selected, root):
            return False
    if isinstance(instance, dict):
        required = schema.get("required", [])
        if any(name not in instance for name in required):
            return False
        properties = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        matched: set[str] = set()
        for name, child in properties.items():
            if name in instance:
                matched.add(name)
                if not is_valid(instance[name], child, root):
                    return False
        for pattern, child in patterns.items():
            for name, value in instance.items():
                if re.search(pattern, name):
                    matched.add(name)
                    if not is_valid(value, child, root):
                        return False
        additional = schema.get("additionalProperties", True)
        for name, value in instance.items():
            if name not in matched and (additional is False or (isinstance(additional, dict) and not is_valid(value, additional, root))):
                return False
        if "propertyNames" in schema and any(not is_valid(name, schema["propertyNames"], root) for name in instance):
            return False
        if len(instance) < schema.get("minProperties", 0) or len(instance) > schema.get("maxProperties", math.inf):
            return False
        for trigger, dependencies in schema.get("dependentRequired", {}).items():
            if trigger in instance and any(name not in instance for name in dependencies):
                return False
        for trigger, child in schema.get("dependentSchemas", {}).items():
            if trigger in instance and not is_valid(instance, child, root):
                return False
    if isinstance(instance, list):
        prefix = schema.get("prefixItems", [])
        for index, child in enumerate(prefix[: len(instance)]):
            if not is_valid(instance[index], child, root):
                return False
        items = schema.get("items", True)
        if isinstance(items, (dict, bool)):
            if any(not is_valid(value, items, root) for value in instance[len(prefix) :]):
                return False
        if len(instance) < schema.get("minItems", 0) or len(instance) > schema.get("maxItems", math.inf):
            return False
        if schema.get("uniqueItems") and len({canonicalize(item) for item in instance}) != len(instance):
            return False
        if "contains" in schema:
            count = sum(is_valid(item, schema["contains"], root) for item in instance)
            if count < schema.get("minContains", 1) or count > schema.get("maxContains", math.inf):
                return False
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0) or len(instance) > schema.get("maxLength", math.inf):
            return False
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            return False
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if isinstance(instance, float) and not math.isfinite(instance):
            return False
        if instance < schema.get("minimum", -math.inf) or instance <= schema.get("exclusiveMinimum", -math.inf):
            return False
        if instance > schema.get("maximum", math.inf) or instance >= schema.get("exclusiveMaximum", math.inf):
            return False
        if "multipleOf" in schema:
            divisor = schema["multipleOf"]
            if not isinstance(divisor, (int, float)) or isinstance(divisor, bool):
                return False
            if (isinstance(divisor, float) and not math.isfinite(divisor)) or divisor <= 0:
                return False
            instance_numerator, instance_denominator = instance.as_integer_ratio()
            divisor_numerator, divisor_denominator = divisor.as_integer_ratio()
            numerator = instance_numerator * divisor_denominator
            denominator = instance_denominator * divisor_numerator
            if numerator % denominator != 0:
                return False
    return True


def require_valid(instance: Any, schema: Any, label: str) -> None:
    if not is_valid(instance, schema):
        raise SchemaValidationError(f"{label} does not satisfy its machine schema")
