"""
In-memory runtime log capture for frontend diagnostics.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import re
import threading
import traceback
from typing import AsyncIterator, Deque, Dict, List, Optional, Sequence, Tuple


LOG_LEVELS: Tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_CAPTURED_LOGGER_PREFIXES: Tuple[str, ...] = ("backend", "uvicorn.error")
_EXCLUDED_LOGGER_PREFIXES: Tuple[str, ...] = ("uvicorn.access",)

_RE_BEARER = re.compile(r"(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)", re.IGNORECASE)
_RE_KEY_VALUE_SECRET = re.compile(
    r"\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)\s*[:=]\s*([^\s,;]+)",
    re.IGNORECASE,
)
_RE_ACCESS_TOKEN_QUERY = re.compile(r"([?&]access_token=)([^&\s]+)", re.IGNORECASE)


def redact_sensitive_data(raw: str) -> str:
    """Redact common secret/token patterns from log messages."""
    redacted = _RE_BEARER.sub(r"\1***REDACTED***", raw)
    redacted = _RE_KEY_VALUE_SECRET.sub(r"\1=***REDACTED***", redacted)
    redacted = _RE_ACCESS_TOKEN_QUERY.sub(r"\1***REDACTED***", redacted)
    return redacted


def should_capture_log_record(record: logging.LogRecord) -> bool:
    """Allow backend + uvicorn.error, exclude noisy access logs."""
    logger_name = record.name or ""
    for prefix in _EXCLUDED_LOGGER_PREFIXES:
        if logger_name.startswith(prefix):
            return False

    for prefix in _CAPTURED_LOGGER_PREFIXES:
        if logger_name == prefix or logger_name.startswith(f"{prefix}."):
            return True
    return False


def _normalize_level(level: Optional[str]) -> Optional[str]:
    if level is None:
        return None
    normalized = level.upper()
    if normalized not in LOG_LEVELS:
        raise ValueError(f"Unsupported level: {level}")
    return normalized


def _matches_filters(
    entry_level: str,
    entry_message: str,
    level: Optional[str],
    contains: Optional[str],
) -> bool:
    normalized_level = _normalize_level(level)
    if normalized_level:
        required_value = logging._nameToLevel.get(normalized_level, logging.INFO)
        current_value = logging._nameToLevel.get(entry_level, logging.INFO)
        if current_value < required_value:
            return False
    if contains:
        if contains.lower() not in entry_message.lower():
            return False
    return True


@dataclass(frozen=True)
class RuntimeLogEntry:
    id: int
    ts: datetime
    level: str
    logger: str
    message: str
    tags: Tuple[str, ...]


@dataclass(frozen=True)
class RuntimeLogSnapshot:
    items: List[RuntimeLogEntry]
    total_buffered: int
    dropped_count: int


class RuntimeLogManager:
    """Thread-safe in-memory log buffer with async subscriptions."""

    def __init__(self, max_entries: int = 4000):
        self.max_entries = max_entries
        self._entries: Deque[RuntimeLogEntry] = deque(maxlen=max_entries)
        self._dropped_count = 0
        self._entry_id = 0
        self._lock = threading.Lock()
        self._subscriber_id = 0
        self._subscribers: Dict[int, Tuple[asyncio.AbstractEventLoop, asyncio.Queue[RuntimeLogEntry]]] = {}

    def push(
        self,
        level: str,
        logger_name: str,
        message: str,
        tags: Optional[Sequence[str]] = None,
        created_at: Optional[datetime] = None,
    ) -> RuntimeLogEntry:
        sanitized_message = redact_sensitive_data(message)
        ts = created_at or datetime.now(timezone.utc)
        entry_level = level.upper() if level else "INFO"
        entry_tags = tuple(tags or ())

        with self._lock:
            self._entry_id += 1
            if len(self._entries) == self.max_entries:
                self._dropped_count += 1
            entry = RuntimeLogEntry(
                id=self._entry_id,
                ts=ts,
                level=entry_level,
                logger=logger_name,
                message=sanitized_message,
                tags=entry_tags,
            )
            self._entries.append(entry)
            subscribers = list(self._subscribers.items())

        for subscriber_id, (loop, queue) in subscribers:
            if loop.is_closed():
                self._remove_subscriber(subscriber_id)
                continue

            def _enqueue(target_queue: asyncio.Queue[RuntimeLogEntry], item: RuntimeLogEntry) -> None:
                if target_queue.full():
                    try:
                        target_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                target_queue.put_nowait(item)

            try:
                loop.call_soon_threadsafe(_enqueue, queue, entry)
            except RuntimeError:
                self._remove_subscriber(subscriber_id)

        return entry

    def snapshot(
        self,
        *,
        limit: int = 200,
        level: Optional[str] = None,
        contains: Optional[str] = None,
    ) -> RuntimeLogSnapshot:
        normalized_level = _normalize_level(level)
        safe_limit = max(1, min(limit, 2000))
        contains_filter = contains.strip() if contains else None

        with self._lock:
            entries = list(self._entries)
            dropped_count = self._dropped_count
            total_buffered = len(self._entries)

        filtered = [
            entry
            for entry in entries
            if _matches_filters(
                entry.level,
                entry.message,
                normalized_level,
                contains_filter,
            )
        ]
        if len(filtered) > safe_limit:
            filtered = filtered[-safe_limit:]
        return RuntimeLogSnapshot(
            items=filtered,
            total_buffered=total_buffered,
            dropped_count=dropped_count,
        )

    async def subscribe(
        self,
        *,
        level: Optional[str] = None,
        contains: Optional[str] = None,
    ) -> AsyncIterator[RuntimeLogEntry]:
        normalized_level = _normalize_level(level)
        contains_filter = contains.strip() if contains else None
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[RuntimeLogEntry] = asyncio.Queue(maxsize=1000)
        subscriber_id = self._add_subscriber(loop, queue)
        try:
            while True:
                entry = await queue.get()
                if _matches_filters(
                    entry.level,
                    entry.message,
                    normalized_level,
                    contains_filter,
                ):
                    yield entry
        finally:
            self._remove_subscriber(subscriber_id)

    def _add_subscriber(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[RuntimeLogEntry],
    ) -> int:
        with self._lock:
            self._subscriber_id += 1
            subscriber_id = self._subscriber_id
            self._subscribers[subscriber_id] = (loop, queue)
            return subscriber_id

    def _remove_subscriber(self, subscriber_id: int) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)


class RingBufferLogHandler(logging.Handler):
    """Logging handler that stores records into RuntimeLogManager."""

    def __init__(self, manager: RuntimeLogManager):
        super().__init__(level=logging.DEBUG)
        self.manager = manager
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        if not should_capture_log_record(record):
            return
        try:
            message = self.format(record)
            if record.exc_info:
                message = f"{message}\n{''.join(traceback.format_exception(*record.exc_info))}"

            tags = getattr(record, "tags", None)
            normalized_tags: Optional[List[str]] = None
            if isinstance(tags, str):
                normalized_tags = [tags]
            elif isinstance(tags, Sequence):
                normalized_tags = [str(item) for item in tags if item is not None]

            self.manager.push(
                level=record.levelname,
                logger_name=record.name,
                message=message,
                tags=normalized_tags,
                created_at=datetime.fromtimestamp(record.created, tz=timezone.utc),
            )
        except Exception:
            self.handleError(record)


_MANAGER: Optional[RuntimeLogManager] = None
_HANDLER: Optional[RingBufferLogHandler] = None
_INIT_LOCK = threading.Lock()


def initialize_runtime_logs(max_entries: int = 4000) -> RuntimeLogManager:
    """Initialize runtime log capture once (idempotent)."""
    global _MANAGER, _HANDLER
    with _INIT_LOCK:
        if _MANAGER is not None and _HANDLER is not None:
            return _MANAGER

        root_logger = logging.getLogger()
        existing_handler = next(
            (handler for handler in root_logger.handlers if isinstance(handler, RingBufferLogHandler)),
            None,
        )
        if existing_handler is not None:
            _HANDLER = existing_handler
            _MANAGER = existing_handler.manager
            return _MANAGER

        manager = RuntimeLogManager(max_entries=max_entries)
        handler = RingBufferLogHandler(manager)
        root_logger.addHandler(handler)

        # Ensure backend + uvicorn.error INFO logs are captured even when root logger is stricter.
        for logger_name in ("backend", "uvicorn.error"):
            target_logger = logging.getLogger(logger_name)
            if target_logger.level == logging.NOTSET or target_logger.level > logging.INFO:
                target_logger.setLevel(logging.INFO)

        _MANAGER = manager
        _HANDLER = handler
        return manager


def get_runtime_log_manager() -> RuntimeLogManager:
    """Get runtime log manager, initializing if necessary."""
    return initialize_runtime_logs()
