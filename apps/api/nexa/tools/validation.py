"""Validation of tool-call arguments requested by the LLM or the workflow."""

from __future__ import annotations

from datetime import date, datetime
from datetime import time as dtime
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from nexa.nlp.arabic import to_western_digits
from nexa.nlp.datetime_norm import extract_date, extract_time

_FORMATS = FormatChecker()


@_FORMATS.checks("time", raises=ValueError)
def _time_format(value: object) -> bool:
    """Business time format: HH:MM or HH:MM:SS (24h). RFC 3339 offsets are not required for spoken times."""
    if not isinstance(value, str):
        return True
    dtime.fromisoformat(value)
    return True


def coerce_arguments(schema: dict[str, Any], args: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Light, predictable coercion of common LLM mistakes (numbers as strings, Arabic digits, dates)."""
    props = schema.get("properties", {})
    out: dict[str, Any] = {}
    for key, value in args.items():
        if value is None or value == "":
            continue  # treat empty as "not provided"
        spec = props.get(key, {})
        typ = spec.get("type")
        if isinstance(value, str):
            v = to_western_digits(value).strip()
            if typ == "integer" and v.lstrip("-").isdigit():
                value = int(v)
            elif typ == "number":
                try:
                    value = float(v)
                except ValueError:
                    value = v
            elif typ == "boolean" and v.lower() in ("true", "false", "yes", "no"):
                value = v.lower() in ("true", "yes")
            elif spec.get("format") == "date":
                d = _parse_date(v, today)
                value = d.isoformat() if d else v
            elif spec.get("format") == "time":
                t, _ = extract_time(v)
                value = t.strftime("%H:%M") if t else v
            else:
                value = v
        out[key] = value
    return out


def _parse_date(v: str, today: date | None) -> date | None:
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return extract_date(v, today or datetime.now().date())


def validate_arguments(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=_FORMATS)
    errors = []
    for err in sorted(validator.iter_errors(args), key=lambda e: list(e.path)):
        field = ".".join(str(p) for p in err.path) or (err.validator_value[0] if err.validator == "required" else "")
        if err.validator == "required":
            missing = [r for r in err.validator_value if r not in err.instance]
            errors.append(f"missing required information: {', '.join(missing)}")
        elif err.validator == "additionalProperties":
            errors.append(err.message)
        else:
            errors.append(f"{field}: {err.message}")
    return errors
