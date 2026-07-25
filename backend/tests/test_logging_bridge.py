"""Tests for unified / colored third-party logging."""

from __future__ import annotations

import logging
import sys

import pytest

from app.core.config import settings
from app.utils.logger import (
    ColumnNotFound,
    CustomFormatter,
    JSONFormatter,
    add_logging_level,
    create_suppression_filter,
)
from app.utils.logging_bridge import (
    configure_third_party_loggers,
    sql_echo_enabled,
)


def _console_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    ]


def test_configure_third_party_uses_colored_formatter(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.setattr(settings, "sql_echo", False)
    monkeypatch.setattr(settings, "log_level", "INFO")

    for name in ("sqlalchemy.engine", "uvicorn", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        plain = logging.StreamHandler()
        plain.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        lg.addHandler(plain)

    configure_third_party_loggers("INFO")

    engine = logging.getLogger("sqlalchemy.engine")
    assert engine.level == logging.WARNING
    consoles = _console_handlers(engine)
    assert len(consoles) == 1
    assert isinstance(consoles[0].formatter, CustomFormatter)

    access = logging.getLogger("uvicorn.access")
    consoles = _console_handlers(access)
    assert len(consoles) == 1
    assert isinstance(consoles[0].formatter, CustomFormatter)
    assert access.propagate is False

    error = logging.getLogger("uvicorn.error")
    assert _console_handlers(error) == []
    assert error.propagate is True


def test_sql_echo_enables_engine_info(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sql_echo", True)
    monkeypatch.setattr(settings, "log_level", "INFO")
    assert sql_echo_enabled() is True
    configure_third_party_loggers("INFO")
    assert logging.getLogger("sqlalchemy.engine").level == logging.INFO


def test_log_level_debug_enables_sql_echo(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sql_echo", False)
    monkeypatch.setattr(settings, "log_level", "DEBUG")
    assert sql_echo_enabled() is True


def test_postgres_engine_echo_disabled() -> None:
    from app.db.postgres import engine

    assert engine.echo is False


def test_custom_formatter_handles_non_copyable_record_extras() -> None:
    class NonCopyable:
        def __deepcopy__(self, memo):
            raise AssertionError("formatter must not deep-copy record extras")

    formatter = CustomFormatter()
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        "connection %s",
        ("open",),
        None,
        func="asgi_send",
    )
    record.scope = NonCopyable()

    rendered = formatter.format(record)

    assert "connection open" in rendered
    assert record.name == "uvicorn.error"


def test_custom_formatter_handles_traceback_records() -> None:
    try:
        raise RuntimeError("websocket failed")
    except RuntimeError:
        exc_info = sys.exc_info()

    formatter = CustomFormatter()
    record = logging.LogRecord(
        "uvicorn.error",
        logging.ERROR,
        __file__,
        1,
        "Exception in ASGI application",
        (),
        exc_info,
        func="run_asgi",
    )

    rendered = formatter.format(record)

    assert "Exception in ASGI application" in rendered
    assert "RuntimeError: websocket failed" in rendered


def test_logging_helpers_and_structured_production_console(monkeypatch, caplog) -> None:
    with pytest.raises(ColumnNotFound, match="Avialable columns"):
        raise ColumnNotFound(["name"])

    record = logging.LogRecord("allowed", logging.INFO, __file__, 1, "ok", (), None)
    suppression_filter = create_suppression_filter(["blocked"])
    assert suppression_filter(record) is True
    record.name = "blocked"
    assert suppression_filter(record) is False

    add_logging_level("ROOTAGENT_TEST", 35)
    logger = logging.getLogger("custom-level-test")
    logger.setLevel(35)
    with caplog.at_level(35):
        logger.rootagent_test("custom message")  # type: ignore[attr-defined]
        logging.rootagent_test("root message")  # type: ignore[attr-defined]

    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_third_party_loggers("INFO")
    handler = _console_handlers(logging.getLogger("uvicorn.access"))[0]
    assert isinstance(handler.formatter, JSONFormatter)
