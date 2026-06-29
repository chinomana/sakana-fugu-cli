"""Structured logging configuration."""

from __future__ import annotations

import sys

import structlog


def setup_logging(verbose: bool = False) -> None:
    """Configure structured logging with Rich console output."""
    level = 10 if verbose else 30  # DEBUG or WARNING

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
