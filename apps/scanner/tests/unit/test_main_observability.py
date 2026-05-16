"""Unit tests for scanner.main observability helpers.

Covers _write_summary failure visibility (PR D): a write failure must
log at ERROR, attempt a system alert, and NOT raise — the scan run
itself is unaffected by a summary-file problem.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from scanner.main import _write_summary


def test_write_summary_success(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "scan_summary.json"
    _write_summary(str(path), {"status": "completed", "alerts_sent": 3})
    assert path.exists()
    import json

    assert json.loads(path.read_text())["status"] == "completed"


def test_write_summary_failure_does_not_raise() -> None:
    """An unwritable path must not propagate — observability never crashes
    the scanner."""
    # A directory path can't be opened for writing as a file.
    with patch("scanner.main._send_system_alert"):
        _write_summary("/", {"status": "completed"})  # must not raise


def test_write_summary_failure_logs_error(caplog) -> None:  # type: ignore[no-untyped-def]
    with patch("scanner.main._send_system_alert"), caplog.at_level(logging.ERROR):
        _write_summary("/", {"status": "completed"})
    assert any(
        "Failed to write" in rec.message and rec.levelno == logging.ERROR for rec in caplog.records
    )


def test_write_summary_failure_fires_system_alert() -> None:
    with patch("scanner.main._send_system_alert") as mock_alert:
        _write_summary("/", {"status": "completed"})
    mock_alert.assert_called_once()
    msg = mock_alert.call_args[0][0]
    assert "scan_summary.json write failed" in msg
