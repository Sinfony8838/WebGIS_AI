"""Logging hardening for the WebGIS-AI server (phase-1 acceptance C7).

The voice WebSocket's legacy-token mode authenticates via an
``access_token`` query parameter (browsers cannot set custom headers on a
WebSocket handshake). Uvicorn's default access log prints the full request
line including the query string, which would persist that token in logs.

``QueryStrippingAccessFormatter`` keeps access logging fully enabled but
drops everything from the first ``?`` in the logged path — credentials in
query strings never reach the log sink. It only affects the *logged* line,
never routing or the request itself.
"""
from __future__ import annotations

import logging

import uvicorn.logging


class QueryStrippingRequestFilter(logging.Filter):
    """Cover default launchers and Uvicorn's WebSocket handshake log too."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple):
            return True
        path_index = None
        if record.name == "uvicorn.access" and len(args) == 5:
            path_index = 2
        elif record.name == "uvicorn.error" and "WebSocket %s" in str(record.msg) and len(args) >= 2:
            path_index = 1
        if path_index is not None and isinstance(args[path_index], str):
            record.args = args[:path_index] + (args[path_index].split("?", 1)[0],) + args[path_index + 1:]
        return True


def install_request_log_filters() -> None:
    # Uvicorn configures logging before importing the app, including launches
    # without --log-config (the public Windows launcher). Keep all handlers.
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, QueryStrippingRequestFilter) for item in logger.filters):
            logger.addFilter(QueryStrippingRequestFilter())


class QueryStrippingAccessFormatter(uvicorn.logging.AccessFormatter):
    """Access formatter that never logs query strings."""

    def format(self, record: logging.LogRecord) -> str:
        args = record.args
        if (
            isinstance(args, tuple)
            and len(args) >= 3
            and isinstance(args[2], str)
            and "?" in args[2]
        ):
            # args layout used by uvicorn's access log:
            # (client_addr, method, full_path_with_query, http_version, status_code)
            record.args = args[:2] + (args[2].split("?", 1)[0],) + args[3:]
        return super().format(record)
