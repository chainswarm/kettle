"""
Unit tests for subnet.utils.logging.JsonFormatter.

Verifies:
 1. Basic format — required keys present with correct values.
 2. Extra fields passed via ``extra={}`` appear in the JSON output.
"""
import json
import logging

import pytest

from subnet.utils.logging import JsonFormatter


def _make_record(
    name: str = "test_logger",
    level: int = logging.INFO,
    msg: str = "hello",
    **extra_attrs,
) -> logging.LogRecord:
    """Helper: build a LogRecord and optionally attach extra attributes."""
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra_attrs.items():
        setattr(record, key, value)
    return record


def test_json_formatter_basic() -> None:
    """
    JsonFormatter.format() returns valid JSON with the four required base keys.
    """
    formatter = JsonFormatter()
    record = _make_record(name="my_logger", level=logging.WARNING, msg="test message")
    output = formatter.format(record)

    # Must be parseable JSON
    data = json.loads(output)

    assert "timestamp" in data, "missing 'timestamp' key"
    assert "level" in data, "missing 'level' key"
    assert "logger" in data, "missing 'logger' key"
    assert "message" in data, "missing 'message' key"

    assert data["level"] == "WARNING"
    assert data["logger"] == "my_logger"
    assert data["message"] == "test message"
    # Timestamp must be a non-empty string with UTC 'Z' suffix
    assert isinstance(data["timestamp"], str)
    assert data["timestamp"].endswith("Z")


def test_json_formatter_extra_fields() -> None:
    """
    Extra fields set on the LogRecord appear as top-level keys in JSON output.
    This matches what Python's logging module does when ``extra={"k": v}`` is
    passed to a log call — it sets those keys directly on the LogRecord.
    """
    formatter = JsonFormatter()
    record = _make_record(
        name="validator_scoring_loop",
        level=logging.INFO,
        msg="[Validator] score",
        epoch=42,
        score=0.5,
        peer="12D3KooWabcd1234",
    )
    output = formatter.format(record)
    data = json.loads(output)

    # Extra fields must be present
    assert data.get("epoch") == 42, f"expected epoch=42, got {data.get('epoch')!r}"
    assert data.get("score") == 0.5, f"expected score=0.5, got {data.get('score')!r}"
    assert data.get("peer") == "12D3KooWabcd1234", f"expected peer field, got {data.get('peer')!r}"

    # Base keys still present
    assert data["logger"] == "validator_scoring_loop"
    assert data["message"] == "[Validator] score"
