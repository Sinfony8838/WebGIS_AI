"""Phase-1 acceptance C7: query strings never reach the access log.

The voice WebSocket's legacy-token mode authenticates via an
``access_token`` query parameter; uvicorn's default access formatter logs
the full request line. The shipped ``backend/uvicorn-log-config.json``
swaps in ``QueryStrippingAccessFormatter`` so tokens are not persisted.
Verified against a real uvicorn launch with a sentinel token during
acceptance; these unit tests pin the formatter and the config wiring.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.app.logging_filters import QueryStrippingAccessFormatter

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "backend" / "uvicorn-log-config.json"


def _format_record(args: tuple) -> str:
    formatter = QueryStrippingAccessFormatter(
        '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    )
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="%s - \"%s %s HTTP/%s\" %d",
        args=args,
        exc_info=None,
    )
    return formatter.format(record)


def test_query_string_is_stripped_from_access_line() -> None:
    line = _format_record(
        ("127.0.0.1:5555", "GET", "/assistant/voice/stream?access_token=C7SENTINEL123", "1.1", 200)
    )
    assert "C7SENTINEL123" not in line
    assert "?" not in line
    assert "/assistant/voice/stream" in line
    assert "200" in line


def test_request_without_query_is_unchanged() -> None:
    line = _format_record(("127.0.0.1:5555", "GET", "/health", "1.1", 200))
    assert "/health" in line and "200" in line


def test_shipped_log_config_uses_the_stripping_formatter() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    access_formatter = config["formatters"]["access"]
    assert access_formatter["()"] == "backend.app.logging_filters.QueryStrippingAccessFormatter"
    # Access logging stays fully enabled (no blanket disabling as a "fix").
    assert config["loggers"]["uvicorn.access"]["level"] == "INFO"
    assert config["handlers"]["access"]["class"] == "logging.StreamHandler"
