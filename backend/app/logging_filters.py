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
