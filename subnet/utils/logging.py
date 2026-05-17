"""
Structured JSON log formatter for subnet epoch loop loggers.

Usage (automatic via LOG_JSON env var in run_node.py):

    LOG_JSON=true python -m subnet.cli.run_node ...

Manual usage:

    from subnet.utils.logging import JsonFormatter
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
"""
import json
import logging
import time

# Standard LogRecord attributes that should NOT be surfaced as extra fields.
# This set covers every attribute documented in the Python logging module.
_RESERVED_LOG_KEYS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
    # Additional internal attrs added by the logging machinery
    "asctime",
})


class JsonFormatter(logging.Formatter):
    """
    Format a LogRecord as a single-line JSON string.

    Output always contains: timestamp (ISO-8601 UTC), level, logger, message.
    Any extra fields passed via ``extra={"key": value}`` to the log call are
    merged in at the top level, making them queryable with jq.

    Example output (validator scoring)::

        {"timestamp": "2025-01-01T00:00:00.123456Z", "level": "INFO",
         "logger": "validator_scoring_loop", "message": "[Validator] ...",
         "epoch": 5, "peer": "12D3KooWabcd1234", "score": 0.5}
    """

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        # Ensure exc_text is populated if there is an exception
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)

        record_dict = record.__dict__

        # Build the base structured log entry
        result: dict = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)
            ) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach exception text when present
        if record.exc_text:
            result["exc"] = record.exc_text

        # Merge any caller-supplied extra fields (keys not in the reserved set)
        for key, value in record_dict.items():
            if key not in _RESERVED_LOG_KEYS and not key.startswith("_"):
                result[key] = value

        return json.dumps(result, default=str)
