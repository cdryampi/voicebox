"""
Pydantic models for request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


class VoiceProfileCreate(BaseModel):
    """Request model for creating a voice profile."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    language: str = Field(default="en", pattern="^(zh|en|ja|ko|de|fr|ru|pt|es|it)$")


class VoiceProfileResponse(BaseModel):
    """Response model for voice profile."""
    id: str
    name: str
    description: Optional[str]
    language: str
    avatar_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProfileSampleCreate(BaseModel):
    """Request model for adding a sample to a profile."""
    reference_text: str = Field(..., min_length=1, max_length=1000)


class ProfileSampleUpdate(BaseModel):
    """Request model for updating a profile sample."""
    reference_text: str = Field(..., min_length=1, max_length=1000)


class ProfileSampleResponse(BaseModel):
    """Response model for profile sample."""
    id: str
    profile_id: str
    audio_path: str
    reference_text: str

    class Config:
        from_attributes = True


class GenerationRequest(BaseModel):
    """Request model for voice generation."""
    profile_id: str
    text: str = Field(..., min_length=1, max_length=5000)
    language: str = Field(default="en", pattern="^(zh|en|ja|ko|de|fr|ru|pt|es|it)$")
    seed: Optional[int] = Field(None, ge=0)
    model_size: Optional[str] = Field(default=None, pattern="^(1\\.7B|0\\.6B)$")
    instruct: Optional[str] = Field(None, max_length=500)


class GenerationResponse(BaseModel):
    """Response model for voice generation."""
    id: str
    profile_id: str
    text: str
    language: str
    audio_path: str
    duration: float
    seed: Optional[int]
    instruct: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class HistoryQuery(BaseModel):
    """Query model for generation history."""
    profile_id: Optional[str] = None
    search: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class HistoryResponse(BaseModel):
    """Response model for history entry (includes profile name)."""
    id: str
    profile_id: str
    profile_name: str
    text: str
    language: str
    audio_path: str
    duration: float
    seed: Optional[int]
    instruct: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class HistoryListResponse(BaseModel):
    """Response model for history list."""
    items: List[HistoryResponse]
    total: int


class TranscriptionRequest(BaseModel):
    """Request model for audio transcription."""
    language: Optional[str] = Field(None, pattern="^(en|zh)$")


class TranscriptionResponse(BaseModel):
    """Response model for transcription."""
    text: str
    duration: float


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    model_loaded: bool
    model_downloaded: Optional[bool] = None  # Whether model is cached/downloaded
    model_size: Optional[str] = None  # Current model size if loaded
    gpu_available: bool
    gpu_type: Optional[str] = None  # GPU type (CUDA, MPS, or None)
    vram_used_mb: Optional[float] = None
    backend_type: Optional[str] = None  # Backend type (mlx or pytorch)


class ModelStatus(BaseModel):
    """Response model for model status."""
    model_name: str
    display_name: str
    downloaded: bool
    downloading: bool = False  # True if download is in progress
    size_mb: Optional[float] = None
    loaded: bool = False


class ModelStatusListResponse(BaseModel):
    """Response model for model status list."""
    models: List[ModelStatus]


class ModelDownloadRequest(BaseModel):
    """Request model for triggering model download."""
    model_name: str


class ActiveDownloadTask(BaseModel):
    """Response model for active download task."""
    model_name: str
    status: str
    started_at: datetime


class ActiveGenerationTask(BaseModel):
    """Response model for active generation task."""
    task_id: str
    profile_id: str
    text_preview: str
    started_at: datetime


class ActiveStoryRenderTask(BaseModel):
    """Response model for active story render task."""
    job_id: str
    story_id: str
    status: str
    total_lines: int
    processed_lines: int
    started_at: datetime


class ActiveTasksResponse(BaseModel):
    """Response model for active tasks."""
    downloads: List[ActiveDownloadTask]
    generations: List[ActiveGenerationTask]
    story_renders: List[ActiveStoryRenderTask] = []


class AudioChannelCreate(BaseModel):
    """Request model for creating an audio channel."""
    name: str = Field(..., min_length=1, max_length=100)
    device_ids: List[str] = Field(default_factory=list)


class AudioChannelUpdate(BaseModel):
    """Request model for updating an audio channel."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    device_ids: Optional[List[str]] = None


class AudioChannelResponse(BaseModel):
    """Response model for audio channel."""
    id: str
    name: str
    is_default: bool
    device_ids: List[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ChannelVoiceAssignment(BaseModel):
    """Request model for assigning voices to a channel."""
    profile_ids: List[str]


class ProfileChannelAssignment(BaseModel):
    """Request model for assigning channels to a profile."""
    channel_ids: List[str]


class StoryCreate(BaseModel):
    """Request model for creating a story."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class StoryResponse(BaseModel):
    """Response model for story (list view)."""
    id: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    item_count: int = 0

    class Config:
        from_attributes = True


class StoryItemDetail(BaseModel):
    """Detail model for story item with generation info."""
    id: str
    story_id: str
    generation_id: str
    start_time_ms: int
    track: int = 0
    trim_start_ms: int = 0
    trim_end_ms: int = 0
    created_at: datetime
    # Generation details
    profile_id: str
    profile_name: str
    text: str
    language: str
    audio_path: str
    duration: float
    seed: Optional[int]
    instruct: Optional[str]
    generation_created_at: datetime

    class Config:
        from_attributes = True


class StoryDetailResponse(BaseModel):
    """Response model for story with items."""
    id: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: List[StoryItemDetail] = []

    class Config:
        from_attributes = True


class StoryItemCreate(BaseModel):
    """Request model for adding a generation to a story."""
    generation_id: str
    start_time_ms: Optional[int] = None  # If not provided, will be calculated automatically
    track: Optional[int] = 0  # Track number (0 = main track)


class StoryItemUpdateTime(BaseModel):
    """Request model for updating a story item's timecode."""
    generation_id: str
    start_time_ms: int = Field(..., ge=0)


class StoryItemBatchUpdate(BaseModel):
    """Request model for batch updating story item timecodes."""
    updates: List[StoryItemUpdateTime]


class StoryItemReorder(BaseModel):
    """Request model for reordering story items."""
    generation_ids: List[str] = Field(..., min_length=1)


class StoryItemMove(BaseModel):
    """Request model for moving a story item (position and/or track)."""
    start_time_ms: int = Field(..., ge=0)
    track: int = 0


class StoryItemTrim(BaseModel):
    """Request model for trimming a story item."""
    trim_start_ms: int = Field(..., ge=0)
    trim_end_ms: int = Field(..., ge=0)


class StoryItemSplit(BaseModel):
    """Request model for splitting a story item."""
    split_time_ms: int = Field(..., ge=0)  # Time within the clip to split at (relative to clip start)


EmotionType = Literal["neutral", "happy", "sad", "angry", "fearful", "surprised", "calm"]


class StoryCharacterMapping(BaseModel):
    """Character-to-voice mapping for story render jobs."""
    character_name: str = Field(..., min_length=1, max_length=100)
    profile_id: str
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    default_emotion: EmotionType = "neutral"
    default_emotion_intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    default_track: int = 0


class StoryLineSpec(BaseModel):
    """Single line render instruction based on a source history generation."""
    source_generation_id: str
    character_name: str = Field(..., min_length=1, max_length=100)
    text_override: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    emotion: Optional[EmotionType] = None
    emotion_intensity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    track: Optional[int] = None
    start_time_ms: Optional[int] = Field(default=None, ge=0)


class StoryRenderFromHistoryRequest(BaseModel):
    """Create and render a new story from existing generation history."""
    story_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    model_size: Optional[str] = Field(default=None, pattern="^(1\\.7B|0\\.6B)$")
    language: str = Field(default="en", pattern="^(zh|en|ja|ko|de|fr|ru|pt|es|it)$")
    gap_ms: int = Field(default=200, ge=0, le=5000)
    continue_on_error: bool = True
    replace_existing_items: bool = False
    character_mappings: List[StoryCharacterMapping] = Field(..., min_length=1)
    lines: List[StoryLineSpec] = Field(..., min_length=1)


class StoryRenderJobResponse(BaseModel):
    """Response when a story render job is created."""
    job_id: str
    story_id: str
    status: str
    total_lines: int


class StoryRenderLineStatus(BaseModel):
    """Status for one line in a story render job."""
    id: str
    order_index: int
    source_generation_id: str
    generated_generation_id: Optional[str]
    character_name: str
    profile_id: str
    text: str
    emotion: EmotionType
    emotion_intensity: float
    resolved_instruct: Optional[str]
    track: int
    start_time_ms: int
    status: str
    error_message: Optional[str] = None


class StoryRenderStatusResponse(BaseModel):
    """Current status for a story render job."""
    job_id: str
    story_id: str
    status: str
    total_lines: int
    processed_lines: int
    error_summary: Optional[str]
    output_audio_path: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    lines: List[StoryRenderLineStatus]


class GroqModelsResponse(BaseModel):
    """Groq model list and runtime status."""
    enabled: bool
    default_model: str
    models: List[str]


class StoryComposeWithGroqRequest(BaseModel):
    """Compose story lines with Groq and render them to audio."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    prompt: str = Field(..., min_length=5, max_length=4000)
    mode: Literal["novela", "roleplay"] = "roleplay"
    language: str = Field(default="en", pattern="^(zh|en|ja|ko|de|fr|ru|pt|es|it)$")
    target_lines: int = Field(default=8, ge=2, le=40)
    llm_model: Optional[str] = Field(default=None, max_length=120)
    model_size: Optional[str] = Field(default=None, pattern="^(1\\.7B|0\\.6B)$")
    gap_ms: int = Field(default=200, ge=0, le=5000)
    continue_on_error: bool = True
    character_mappings: List[StoryCharacterMapping] = Field(..., min_length=1, max_length=10)


class StudioLimits(BaseModel):
    """Hard limits used by Studio draft generation and previews."""
    max_lines: int = Field(default=20, ge=2, le=40)
    max_chars_per_line: int = Field(default=300, ge=50, le=1000)
    preview_seconds: int = Field(default=5, ge=1, le=10)


class StudioDraftCreateRequest(BaseModel):
    """Create a Studio draft from a prompt using Groq."""
    story_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    prompt: str = Field(..., min_length=5, max_length=4000)
    mode: Literal["novela", "roleplay"] = "roleplay"
    language: str = Field(default="en", pattern="^(zh|en|ja|ko|de|fr|ru|pt|es|it)$")
    llm_model: Optional[str] = Field(default=None, max_length=120)
    model_size: Optional[str] = Field(default=None, pattern="^(1\\.7B|0\\.6B)$")
    gap_ms: int = Field(default=200, ge=0, le=5000)
    continue_on_error: bool = True
    character_mappings: List[StoryCharacterMapping] = Field(..., min_length=1, max_length=10)
    limits: Optional[StudioLimits] = None


class StudioDraftResponse(BaseModel):
    """Basic response for Studio draft creation."""
    draft_id: str
    story_id: str
    line_count: int
    status: str
    limits_applied: StudioLimits


class StudioDraftListItem(BaseModel):
    """Studio draft item for listing and quick selection."""
    draft_id: str
    story_id: str
    name: str
    status: str
    line_count: int
    created_at: datetime
    updated_at: datetime


class StudioDraftLineResponse(BaseModel):
    """Studio draft line/card detail."""
    id: str
    order_index: int
    character_name: str
    profile_id: str
    text: str
    emotion: EmotionType
    emotion_intensity: float
    truncated: bool = False
    preview_status: str
    preview_audio_url: Optional[str] = None
    preview_duration: Optional[float] = None
    preview_error: Optional[str] = None

    class Config:
        from_attributes = True


class StudioDraftDetailResponse(BaseModel):
    """Full Studio draft response including all cards."""
    draft_id: str
    story_id: str
    name: str
    description: Optional[str] = None
    prompt: str
    mode: Literal["novela", "roleplay"]
    language: str
    llm_model: str
    model_size: Optional[str] = None
    gap_ms: int
    continue_on_error: bool
    status: str
    limits_applied: StudioLimits
    character_mappings: List[StoryCharacterMapping]
    created_at: datetime
    updated_at: datetime
    lines: List[StudioDraftLineResponse]


class StudioDraftLineUpdate(BaseModel):
    """Line-level update payload for Studio drafts."""
    line_id: str
    character_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    text: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    emotion: Optional[EmotionType] = None
    emotion_intensity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    order_index: Optional[int] = Field(default=None, ge=0)


class StudioDraftLinesUpdateRequest(BaseModel):
    """Batch line update request for Studio drafts."""
    lines: List[StudioDraftLineUpdate] = Field(..., min_length=1)


class StudioPreviewResponse(BaseModel):
    """Response for single card preview generation."""
    line_id: str
    status: str
    preview_audio_url: Optional[str] = None
    duration: Optional[float] = None
    error: Optional[str] = None


class StudioRenderFinalResponse(BaseModel):
    """Response for launching final render from a Studio draft."""
    draft_id: str
    job_id: str
    story_id: str
    status: str
    total_lines: int
