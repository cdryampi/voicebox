"""
Task tracking for active downloads and generations.
"""

from typing import Optional, Dict, List
from datetime import datetime
from dataclasses import dataclass, field


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


class TaskManager:
    """Manages active downloads and generations."""
    
    def __init__(self):
        self._active_downloads: Dict[str, DownloadTask] = {}
        self._active_generations: Dict[str, GenerationTask] = {}
        self._active_story_renders: Dict[str, StoryRenderTask] = {}
    
    def start_download(self, model_name: str) -> None:
        """Mark a download as started."""
        self._active_downloads[model_name] = DownloadTask(
            model_name=model_name,
            status="downloading",
        )
    
    def complete_download(self, model_name: str) -> None:
        """Mark a download as complete."""
        if model_name in self._active_downloads:
            del self._active_downloads[model_name]
    
    def error_download(self, model_name: str, error: str) -> None:
        """Mark a download as failed."""
        # Failed downloads must not remain in the active list; otherwise
        # polling endpoints report them as perpetually downloading.
        if model_name in self._active_downloads:
            del self._active_downloads[model_name]
    
    def start_generation(self, task_id: str, profile_id: str, text: str) -> None:
        """Mark a generation as started."""
        text_preview = text[:50] + "..." if len(text) > 50 else text
        self._active_generations[task_id] = GenerationTask(
            task_id=task_id,
            profile_id=profile_id,
            text_preview=text_preview,
        )
    
    def complete_generation(self, task_id: str) -> None:
        """Mark a generation as complete."""
        if task_id in self._active_generations:
            del self._active_generations[task_id]

    def start_story_render(self, job_id: str, story_id: str, total_lines: int) -> None:
        """Mark a story render as started."""
        self._active_story_renders[job_id] = StoryRenderTask(
            job_id=job_id,
            story_id=story_id,
            status="running",
            total_lines=total_lines,
            processed_lines=0,
        )

    def update_story_render_progress(self, job_id: str, processed_lines: int) -> None:
        """Update processed line count for a story render."""
        task = self._active_story_renders.get(job_id)
        if task:
            task.processed_lines = processed_lines

    def complete_story_render(self, job_id: str, status: str = "completed", error: Optional[str] = None) -> None:
        """Mark a story render as complete and remove from active list."""
        task = self._active_story_renders.get(job_id)
        if task:
            task.status = status
            task.error = error
            del self._active_story_renders[job_id]
    
    def get_active_downloads(self) -> List[DownloadTask]:
        """Get all active downloads."""
        return [
            task
            for task in self._active_downloads.values()
            if task.status in {"downloading", "extracting"}
        ]
    
    def get_active_generations(self) -> List[GenerationTask]:
        """Get all active generations."""
        return list(self._active_generations.values())

    def get_active_story_renders(self) -> List[StoryRenderTask]:
        """Get all active story renders."""
        return list(self._active_story_renders.values())
    
    def is_download_active(self, model_name: str) -> bool:
        """Check if a download is active."""
        return model_name in self._active_downloads
    
    def is_generation_active(self, task_id: str) -> bool:
        """Check if a generation is active."""
        return task_id in self._active_generations

    def is_story_render_active(self, job_id: str) -> bool:
        """Check if a story render is active."""
        return job_id in self._active_story_renders


# Global task manager instance
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """Get or create the global task manager."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
