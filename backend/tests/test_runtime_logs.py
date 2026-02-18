import logging

from backend.utils.runtime_logs import (
    RuntimeLogManager,
    redact_sensitive_data,
    should_capture_log_record,
)


def test_redaction_masks_tokens_and_api_keys() -> None:
    raw = (
        "Authorization: Bearer abc123token "
        "VOICEBOX_API_KEY=supersecret "
        "url=https://demo.dev/health?access_token=mytoken123"
    )
    redacted = redact_sensitive_data(raw)
    assert "abc123token" not in redacted
    assert "supersecret" not in redacted
    assert "mytoken123" not in redacted
    assert "***REDACTED***" in redacted


def test_runtime_log_manager_ring_buffer_and_filters() -> None:
    manager = RuntimeLogManager(max_entries=3)
    manager.push("INFO", "backend.main", "line one")
    manager.push("WARNING", "backend.main", "line two")
    manager.push("ERROR", "backend.main", "line three")
    manager.push("INFO", "backend.main", "line four")

    snapshot_all = manager.snapshot(limit=10)
    assert snapshot_all.total_buffered == 3
    assert snapshot_all.dropped_count == 1
    assert [entry.message for entry in snapshot_all.items] == [
        "line two",
        "line three",
        "line four",
    ]

    snapshot_error = manager.snapshot(limit=10, level="ERROR")
    assert len(snapshot_error.items) == 1
    assert snapshot_error.items[0].message == "line three"

    snapshot_contains = manager.snapshot(limit=10, contains="four")
    assert len(snapshot_contains.items) == 1
    assert snapshot_contains.items[0].message == "line four"


def test_should_capture_log_record_scope() -> None:
    backend_record = logging.LogRecord("backend.main", logging.INFO, __file__, 1, "ok", (), None)
    uvicorn_error = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "ok", (), None)
    uvicorn_access = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "skip", (), None)
    random_record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "skip", (), None)

    assert should_capture_log_record(backend_record) is True
    assert should_capture_log_record(uvicorn_error) is True
    assert should_capture_log_record(uvicorn_access) is False
    assert should_capture_log_record(random_record) is False

