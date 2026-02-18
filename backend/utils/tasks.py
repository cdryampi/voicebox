"""
Task tracking for active downloads and generations.
"""

from typing import Optional, Dict, List, Literal, Deque
from datetime import datetime
from dataclasses import dataclass, field
from collections import deque
import threading


@dataclass
class DownloadTask:
    """Represents an active download task."""
    model_name: str
    status: str = "downloading"  # downloading, extracting, complete, error
    started_at: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None


@dataclass
class GenerationTask:
    """Represents an active generation task."""
    task_id: str
    profile_id: str
    text_preview: str  # First 50 chars of text
    started_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class StoryRenderTask:
    """Represents an active story render task."""
    job_id: str
    story_id: str
    status: str = "running"  # queued, running, completed, failed, partial_failed
    total_lines: int = 0
    processed_lines: int = 0
    started_at: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None


@dataclass
class TaskTerminalEvent:
    """Represents a terminal task transition emitted by backend."""
    id: int
    kind: Literal["generation", "download", "story_render", "model_op"]
    state: Literal["completed", "failed"]
    entity_id: str
    message: str
    error_code: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ModelOperationState:
    """Represents current global model operation state."""
    kind: Literal["download", "activate", "delete"]
    model_name: str
    started_at: datetime = field(default_factory=datetime.utcnow)


class TaskManager:
    """Manages active downloads and generations."""
    
    def __init__(self):
        self._lock = threading.RLock()
        self._active_downloads: Dict[str, DownloadTask] = {}
        self._active_generations: Dict[str, GenerationTask] = {}
        self._active_story_renders: Dict[str, StoryRenderTask] = {}
        self._terminal_events: Deque[TaskTerminalEvent] = deque(maxlen=1000)
        self._next_event_id = 0
        self._model_operation_lock = threading.Lock()
        self._model_operation: Optional[ModelOperationState] = None
        self._cancelled_story_renders: set[str] = set()

    def _push_terminal_event(
        self,
        kind: Literal["generation", "download", "story_render", "model_op"],
        state: Literal["completed", "failed"],
        entity_id: str,
        message: str,
        error_code: Optional[str] = None,
    ) -> TaskTerminalEvent:
        with self._lock:
            self._next_event_id += 1
            event = TaskTerminalEvent(
                id=self._next_event_id,
                kind=kind,
                state=state,
                entity_id=entity_id,
                message=message,
                error_code=error_code,
            )
            self._terminal_events.append(event)
            return event
    
    def start_download(self, model_name: str) -> None:
        """Mark a download as started."""
        with self._lock:
            self._active_downloads[model_name] = DownloadTask(
                model_name=model_name,
                status="downloading",
            )
    
    def complete_download(self, model_name: str, message: Optional[str] = None) -> None:
        """Mark a download as complete."""
        with self._lock:
            if model_name in self._active_downloads:
                del self._active_downloads[model_name]
        self._push_terminal_event(
            kind="download",
            state="completed",
            entity_id=model_name,
            message=message or f"Model download completed: {model_name}",
        )
    
    def error_download(self, model_name: str, error: str, error_code: Optional[str] = None) -> None:
        """Mark a download as failed."""
        # Failed downloads must not remain in the active list; otherwise
        # polling endpoints report them as perpetually downloading.
        with self._lock:
            if model_name in self._active_downloads:
                del self._active_downloads[model_name]
        self._push_terminal_event(
            kind="download",
            state="failed",
            entity_id=model_name,
            message=error,
            error_code=error_code,
        )
    
    def start_generation(self, task_id: str, profile_id: str, text: str) -> None:
        """Mark a generation as started."""
        text_preview = text[:50] + "..." if len(text) > 50 else text
        with self._lock:
            self._active_generations[task_id] = GenerationTask(
                task_id=task_id,
                profile_id=profile_id,
                text_preview=text_preview,
            )
    
    def complete_generation(self, task_id: str, message: Optional[str] = None) -> None:
        """Mark a generation as complete."""
        task_preview: Optional[str] = None
        with self._lock:
            task = self._active_generations.get(task_id)
            if task:
                task_preview = task.text_preview
                del self._active_generations[task_id]
        self._push_terminal_event(
            kind="generation",
            state="completed",
            entity_id=task_id,
            message=message or f"Generation completed: {task_preview or task_id}",
        )

    def fail_generation(self, task_id: str, error: str, error_code: Optional[str] = None) -> None:
        """Mark a generation as failed."""
        with self._lock:
            if task_id in self._active_generations:
                del self._active_generations[task_id]
        self._push_terminal_event(
            kind="generation",
            state="failed",
            entity_id=task_id,
            message=error,
            error_code=error_code,
        )

    def start_story_render(self, job_id: str, story_id: str, total_lines: int) -> None:
        """Mark a story render as started."""
        with self._lock:
            self._cancelled_story_renders.discard(job_id)
            self._active_story_renders[job_id] = StoryRenderTask(
                job_id=job_id,
                story_id=story_id,
                status="running",
                total_lines=total_lines,
                processed_lines=0,
            )

    def update_story_render_progress(self, job_id: str, processed_lines: int) -> None:
        """Update processed line count for a story render."""
        with self._lock:
            task = self._active_story_renders.get(job_id)
            if task:
                task.processed_lines = processed_lines

    def complete_story_render(
        self,
        job_id: str,
        status: str = "completed",
        error: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        """Mark a story render as complete and remove from active list."""
        with self._lock:
            task = self._active_story_renders.get(job_id)
            if task:
                task.status = status
                task.error = error
                del self._active_story_renders[job_id]
            self._cancelled_story_renders.discard(job_id)

        terminal_state: Literal["completed", "failed"] = (
            "completed" if status == "completed" else "failed"
        )
        message = (
            f"Story render completed: {job_id}"
            if terminal_state == "completed"
            else (error or f"Story render failed: {job_id}")
        )
        self._push_terminal_event(
            kind="story_render",
            state=terminal_state,
            entity_id=job_id,
            message=message,
            error_code=error_code,
        )
    
    def get_active_downloads(self) -> List[DownloadTask]:
        """Get all active downloads."""
        with self._lock:
            return [
                task
                for task in self._active_downloads.values()
                if task.status in {"downloading", "extracting"}
            ]
    
    def get_active_generations(self) -> List[GenerationTask]:
        """Get all active generations."""
        with self._lock:
            return list(self._active_generations.values())

    def get_active_story_renders(self) -> List[StoryRenderTask]:
        """Get all active story renders."""
        with self._lock:
            return list(self._active_story_renders.values())
    
    def is_download_active(self, model_name: str) -> bool:
        """Check if a download is active."""
        with self._lock:
            return model_name in self._active_downloads
    
    def is_generation_active(self, task_id: str) -> bool:
        """Check if a generation is active."""
        with self._lock:
            return task_id in self._active_generations

    def is_story_render_active(self, job_id: str) -> bool:
        """Check if a story render is active."""
        with self._lock:
            return job_id in self._active_story_renders

    def request_story_render_cancel(self, job_id: str) -> bool:
        """Request cancellation for a running story render job."""
        with self._lock:
            if job_id not in self._active_story_renders:
                return False
            self._cancelled_story_renders.add(job_id)
            return True

    def request_cancel_all_story_renders(self) -> List[str]:
        """Request cancellation for all active story render jobs."""
        with self._lock:
            ids = list(self._active_story_renders.keys())
            self._cancelled_story_renders.update(ids)
            return ids

    def is_story_render_cancel_requested(self, job_id: str) -> bool:
        """Check whether cancellation was requested for a story render job."""
        with self._lock:
            return job_id in self._cancelled_story_renders

    def clear_story_render_cancel_request(self, job_id: str) -> None:
        """Clear cancellation flag for story render."""
        with self._lock:
            self._cancelled_story_renders.discard(job_id)

    def clear_active_generations(
        self,
        reason: str = "Generation cancelled by operator",
        error_code: str = "TASK_CANCELLED",
    ) -> List[str]:
        """Force-clear tracked active generations (best effort control action)."""
        with self._lock:
            ids = list(self._active_generations.keys())
            self._active_generations.clear()
        for task_id in ids:
            self._push_terminal_event(
                kind="generation",
                state="failed",
                entity_id=task_id,
                message=reason,
                error_code=error_code,
            )
        return ids

    def start_model_operation(
        self,
        kind: Literal["download", "activate", "delete"],
        model_name: str,
    ) -> bool:
        """Acquire global model-operation lock if free."""
        acquired = self._model_operation_lock.acquire(blocking=False)
        if not acquired:
            return False
        with self._lock:
            self._model_operation = ModelOperationState(kind=kind, model_name=model_name)
        return True

    def complete_model_operation(self, message: Optional[str] = None) -> None:
        """Release model-operation lock and emit completed event."""
        with self._lock:
            op = self._model_operation
            self._model_operation = None
        if self._model_operation_lock.locked():
            self._model_operation_lock.release()
        if op:
            self._push_terminal_event(
                kind="model_op",
                state="completed",
                entity_id=op.model_name,
                message=message or f"Model {op.kind} completed: {op.model_name}",
            )

    def fail_model_operation(self, error: str, error_code: Optional[str] = None) -> None:
        """Release model-operation lock and emit failed event."""
        with self._lock:
            op = self._model_operation
            self._model_operation = None
        if self._model_operation_lock.locked():
            self._model_operation_lock.release()
        if op:
            self._push_terminal_event(
                kind="model_op",
                state="failed",
                entity_id=op.model_name,
                message=error,
                error_code=error_code,
            )

    def get_model_operation_state(self) -> Optional[ModelOperationState]:
        """Get active model operation if any."""
        with self._lock:
            return self._model_operation

    def list_terminal_events(
        self,
        *,
        since_id: Optional[int] = None,
        limit: int = 30,
    ) -> List[TaskTerminalEvent]:
        """Get terminal events ordered by id ascending."""
        safe_limit = max(1, min(limit, 200))
        with self._lock:
            events = list(self._terminal_events)
        if since_id is not None:
            events = [event for event in events if event.id > since_id]
        if len(events) > safe_limit:
            events = events[-safe_limit:]
        return events

    def get_last_terminal_event(self) -> Optional[TaskTerminalEvent]:
        """Get latest terminal event."""
        with self._lock:
            if not self._terminal_events:
                return None
            return self._terminal_events[-1]


# Global task manager instance
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """Get or create the global task manager."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
