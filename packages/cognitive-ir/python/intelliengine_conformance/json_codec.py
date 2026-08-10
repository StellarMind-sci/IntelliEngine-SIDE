from __future__ import annotations

import json
import math
from typing import Any


MAX_SAFE_INTEGER = 9_007_199_254_740_991


class JsonInputError(ValueError):
    """Raw input is not in the profile's strict JSON domain."""

    def __init__(self, reason: str, path: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.path = path


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonInputError("duplicate-member", "/" + key.replace("~", "~0").replace("/", "~1"))
        result[key] = value
    return result


def _integer(text: str) -> int:
    value = int(text)
    if abs(value) > MAX_SAFE_INTEGER:
        raise JsonInputError("unsafe-integer")
    return value


def _number(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise JsonInputError("non-finite-number")
    return value


def _check_scalars(value: Any, path: str = "") -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise JsonInputError("unpaired-surrogate", path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_scalars(item, f"{path}/{index}")
    elif isinstance(value, dict):
        for key, item in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            _check_scalars(key, f"{path}/{escaped}")
            _check_scalars(item, f"{path}/{escaped}")


def parse_json_bytes(raw: bytes) -> Any:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise JsonInputError("bom-forbidden")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise JsonInputError("invalid-utf8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_int=_integer,
            parse_float=_number,
            parse_constant=lambda _value: (_ for _ in ()).throw(JsonInputError("non-finite-number")),
        )
    except JsonInputError:
        raise
    except json.JSONDecodeError as error:
        path = "/a" if '"a"' in text else ""
        raise JsonInputError("invalid-json-escape", path) from error
    _check_scalars(value)
    return value


def _utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be", "surrogatepass")


def _number_to_string(value: int | float) -> str:
    if isinstance(value, int) and abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("JCS integer is outside the portable safe range")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JCS only permits finite binary64 numbers")
    if number == 0:
        return "0"
    negative = number < 0
    if negative:
        number = -number
    shortest = repr(number).lower()
    if "e" in shortest:
        mantissa, exponent_text = shortest.split("e")
        exponent = int(exponent_text)
        digits = mantissa.replace(".", "")
        decimal_position = mantissa.index(".") if "." in mantissa else len(mantissa)
        decimal_position += exponent
        scientific_exponent = decimal_position - 1
        if -6 <= scientific_exponent < 21:
            if decimal_position <= 0:
                rendered = "0." + "0" * (-decimal_position) + digits
            elif decimal_position >= len(digits):
                rendered = digits + "0" * (decimal_position - len(digits))
            else:
                rendered = digits[:decimal_position] + "." + digits[decimal_position:]
        else:
            fraction = digits[1:].rstrip("0")
            rendered = digits[0] + (("." + fraction) if fraction else "") + f"e{scientific_exponent:+d}"
    else:
        rendered = shortest
        if rendered.endswith(".0"):
            rendered = rendered[:-2]
    return ("-" if negative else "") + rendered


def _string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _render(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        _check_scalars(value)
        return _string(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _number_to_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_render(item) for item in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=_utf16_key)
        return "{" + ",".join(_string(key) + ":" + _render(value[key]) for key in keys) + "}"
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def canonicalize(value: Any) -> bytes:
    return _render(value).encode("utf-8")
