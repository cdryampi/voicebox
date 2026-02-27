"""
FastAPI application for voicebox backend.

Handles voice cloning, generation history, and server mode.
"""

from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional, Literal
from datetime import datetime
import asyncio
import uvicorn
import argparse
import torch
import tempfile
import io
import json
import logging
from pathlib import Path
import uuid
import signal
import os
from pydantic import ValidationError

from . import (
    database,
    models,
    profiles,
    history,
    tts,
    transcribe,
    config,
    export_import,
    channels,
    stories,
    studio_drafts,
    runtime_defaults,
    __version__,
)
from .database import (
    get_db,
    Generation as DBGeneration,
    ProfileSample as DBProfileSample,
    Story as DBStory,
    StoryRenderJob as DBStoryRenderJob,
    VoiceProfile as DBVoiceProfile,
)
from .utils.progress import get_progress_manager
from .utils.tasks import get_task_manager
from .utils.cache import clear_voice_prompt_cache
from .utils.groq import (
    GroqSTTError,
    list_available_groq_models,
    transcribe_audio_with_groq,
)
from .utils import runtime_logs
from .platform_detect import get_backend_type
from .settings import load_settings
from .auth import is_request_authorized

SETTINGS = load_settings()
logger = logging.getLogger(__name__)

if SETTINGS.data_dir:
    config.set_data_dir(SETTINGS.data_dir)

app = FastAPI(
    title="voicebox API",
    description="Production-quality Qwen3-TTS voice cloning API",
    version=__version__,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\\.0\\.0\\.1)(:\\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


PUBLIC_PATHS = {"/", "/docs", "/openapi.json", "/redoc"}


def _new_db_session() -> Session:
    """Create a short-lived session for routes that stream files."""
    if database.SessionLocal is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return database.SessionLocal()


def _get_runtime_model_defaults(db: Session) -> models.ModelDefaultsResponse:
    """Fetch persisted model defaults with env fallback."""
    return runtime_defaults.get_model_defaults(db, settings=SETTINGS)


def _is_cuda_single_model_mode() -> bool:
    """
    In Colab CUDA deployments we keep only one heavy model loaded at once (TTS or Whisper)
    to avoid VRAM pressure and unstable runtime behavior.
    """
    return bool(SETTINGS.colab_profile and torch.cuda.is_available())


def _is_cuda_assert_error(exc: Exception) -> bool:
    return "device-side assert" in str(exc).lower()


def _get_loaded_tts_model_size(tts_model) -> Optional[str]:
    """Best-effort read of currently loaded TTS model size."""
    try:
        if not tts_model.is_loaded():
            return None
        loaded_size = getattr(tts_model, "_current_model_size", None)
        if loaded_size:
            return loaded_size
        return getattr(tts_model, "model_size", None)
    except Exception:
        return None


def _resolve_runtime_tts_model_size(requested_model_size: Optional[str]) -> str:
    """
    Resolve TTS model size for runtime, pinning Colab/CUDA sessions to 1.7B.
    This prevents model-switch churn that frequently leaves CUDA in an invalid state.
    """
    if _is_cuda_single_model_mode():
        if requested_model_size and requested_model_size != "1.7B":
            logger.warning(
                "Ignoring requested TTS model_size=%s in Colab/CUDA mode; forcing 1.7B",
                requested_model_size,
                extra={"tags": ["models", "single_model_mode", "coerce_size"]},
            )
        return "1.7B"
    if requested_model_size in {"1.7B", "0.6B"}:
        return requested_model_size
    if SETTINGS.default_model_size in {"1.7B", "0.6B"}:
        return SETTINGS.default_model_size
    return "1.7B"


def _resolve_stt_provider() -> Literal["groq", "whisper_local"]:
    provider = (SETTINGS.stt_provider or "").strip().lower()
    if provider not in {"groq", "whisper_local"}:
        provider = "groq" if SETTINGS.colab_profile else "whisper_local"
    if SETTINGS.colab_profile:
        # Colab profile is intentionally pinned to remote STT to avoid CUDA churn.
        return "groq"
    return provider  # type: ignore[return-value]


def _is_stt_remote_only_mode() -> bool:
    """
    In Colab we keep backend dedicated to Qwen TTS and run STT remotely via Groq.
    """
    return bool(SETTINGS.colab_profile and _resolve_stt_provider() == "groq")


def _extract_error_message_and_code(detail: object) -> tuple[str, Optional[str]]:
    """Normalize FastAPI error detail payload into message + optional error code."""
    if isinstance(detail, str):
        return detail, None
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or detail)
        error_code = detail.get("error_code")
        if error_code is not None:
            error_code = str(error_code)
        return message, error_code
    return str(detail), None


async def _read_upload_bytes_or_400(
    file: UploadFile,
    *,
    max_size: Optional[int] = None,
    empty_detail: str = "Uploaded file is empty",
) -> bytes:
    """Read uploaded file bytes safely and reject empty/oversized payloads."""
    try:
        await file.seek(0)
    except Exception:
        # Best effort; some UploadFile implementations may not support seek.
        pass

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail=empty_detail)

    if max_size is not None and len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {max_size / (1024 * 1024)}MB",
        )

    return content


def _model_operation_conflict_response(task_manager, requested_kind: str, requested_model: str) -> JSONResponse:
    active_op = task_manager.get_model_operation_state()
    return JSONResponse(
        status_code=409,
        content={
            "detail": "Another model operation is already in progress.",
            "error_code": "MODEL_OPERATION_IN_PROGRESS",
            "requested_operation": requested_kind,
            "requested_model_name": requested_model,
            "active_operation": {
                "kind": active_op.kind if active_op else None,
                "model_name": active_op.model_name if active_op else None,
                "started_at": active_op.started_at.isoformat() if active_op else None,
            },
        },
    )


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if request.method != "OPTIONS" and request.url.path not in PUBLIC_PATHS:
        authorized = is_request_authorized(
            SETTINGS,
            request.headers.get("Authorization"),
            query_token=request.query_params.get("access_token"),
            method=request.method,
        )
        if not authorized:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


# ============================================
# ROOT & HEALTH ENDPOINTS
# ============================================

@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "voicebox API", "version": __version__}


@app.post("/shutdown")
async def shutdown():
    """Gracefully shutdown the server."""
    async def shutdown_async():
        await asyncio.sleep(0.1)  # Give response time to send
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(shutdown_async())
    return {"message": "Shutting down..."}


@app.get("/health", response_model=models.HealthResponse)
async def health():
    """Health check endpoint."""
    from huggingface_hub import hf_hub_download, constants as hf_constants
    from pathlib import Path
    import os

    tts_model = tts.get_tts_model()
    backend_type = get_backend_type()

    # Check for GPU availability (CUDA or MPS)
    has_cuda = torch.cuda.is_available()
    has_mps = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()
    gpu_available = has_cuda or has_mps

    gpu_type = None
    if has_cuda:
        gpu_type = f"CUDA ({torch.cuda.get_device_name(0)})"
    elif has_mps:
        gpu_type = "MPS (Apple Silicon)"
    elif backend_type == "mlx":
        gpu_type = "Metal (Apple Silicon via MLX)"
    
    vram_used = None
    if has_cuda:
        vram_used = torch.cuda.memory_allocated() / 1024 / 1024  # MB
    
    # Check if model is loaded - use the same logic as model status endpoint
    model_loaded = False
    model_size = None
    try:
        # Use the same check as model status endpoint
        if tts_model.is_loaded():
            model_loaded = True
            # Get the actual loaded model size
            # Check _current_model_size first (more reliable for actually loaded models)
            model_size = getattr(tts_model, '_current_model_size', None)
            if not model_size:
                # Fallback to model_size attribute (which should be set when model loads)
                model_size = getattr(tts_model, 'model_size', None)
    except Exception:
        # If there's an error checking, assume not loaded
        model_loaded = False
        model_size = None
    
    # Check if default model is downloaded (cached)
    model_downloaded = None
    try:
        # Check if the default model (1.7B) is cached
        # Use different model IDs based on backend
        if backend_type == "mlx":
            default_model_id = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
        else:
            default_model_id = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
        
        # Method 1: Try scan_cache_dir if available
        try:
            from huggingface_hub import scan_cache_dir
            cache_info = scan_cache_dir()
            for repo in cache_info.repos:
                if repo.repo_id == default_model_id:
                    model_downloaded = True
                    break
        except (ImportError, Exception):
            # Method 2: Check cache directory (using HuggingFace's OS-specific cache location)
            cache_dir = hf_constants.HF_HUB_CACHE
            repo_cache = Path(cache_dir) / ("models--" + default_model_id.replace("/", "--"))
            if repo_cache.exists():
                has_model_files = (
                    any(repo_cache.rglob("*.bin")) or
                    any(repo_cache.rglob("*.safetensors")) or
                    any(repo_cache.rglob("*.pt")) or
                    any(repo_cache.rglob("*.pth")) or
                    any(repo_cache.rglob("*.npz"))  # MLX models may use npz
                )
                model_downloaded = has_model_files
    except Exception:
        pass
    
    return models.HealthResponse(
        status="healthy",
        model_loaded=model_loaded,
        model_downloaded=model_downloaded,
        model_size=model_size,
        gpu_available=gpu_available,
        gpu_type=gpu_type,
        vram_used_mb=vram_used,
        backend_type=backend_type,
    )


@app.get("/runtime")
async def runtime_info():
    """Runtime diagnostics useful for remote deployment debugging."""
    backend_type = get_backend_type()
    tts_model = tts.get_tts_model()
    stt_provider = _resolve_stt_provider()
    db = _new_db_session()
    try:
        defaults = _get_runtime_model_defaults(db)
    finally:
        db.close()

    runtime = {
        "backend_type": backend_type,
        "host": SETTINGS.host,
        "port": SETTINGS.port,
        "colab_profile": SETTINGS.colab_profile,
        "stt_provider": stt_provider,
        "stt_remote_enabled": stt_provider == "groq",
        "stt_fallback_local_enabled": False,
        "default_model_size": defaults.default_tts_model_size,
        "default_whisper_model_size": defaults.default_whisper_model_size,
        "torch_cuda_available": torch.cuda.is_available(),
        "torch_cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "torch_mps_available": hasattr(torch.backends, "mps") and torch.backends.mps.is_available(),
        "tts_loaded": tts_model.is_loaded(),
        "tts_model_size": getattr(tts_model, "_current_model_size", None),
        "tts_device": getattr(tts_model, "device", None),
        "tts_torch_dtype": str(getattr(tts_model, "torch_dtype", None)) if hasattr(tts_model, "torch_dtype") else None,
        "data_dir": str(config.get_data_dir()),
    }

    if torch.cuda.is_available():
        runtime["vram_allocated_mb"] = torch.cuda.memory_allocated() / 1024 / 1024

    return runtime


@app.get("/server/logs", response_model=models.ServerLogsResponse)
async def get_server_logs(
    limit: int = 200,
    level: Optional[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]] = None,
    contains: Optional[str] = None,
):
    """Get a buffered runtime logs snapshot for operational diagnostics."""
    manager = runtime_logs.get_runtime_log_manager()
    snapshot = manager.snapshot(limit=limit, level=level, contains=contains)
    return models.ServerLogsResponse(
        items=[
            models.ServerLogEntry(
                id=entry.id,
                ts=entry.ts,
                level=entry.level,
                logger=entry.logger,
                message=entry.message,
                tags=list(entry.tags),
            )
            for entry in snapshot.items
        ],
        total_buffered=snapshot.total_buffered,
        dropped_count=snapshot.dropped_count,
    )


@app.get("/server/logs/stream")
async def stream_server_logs(
    level: Optional[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]] = None,
    contains: Optional[str] = None,
):
    """Stream runtime logs as SSE for live remote debugging."""
    manager = runtime_logs.get_runtime_log_manager()

    async def event_generator():
        async for entry in manager.subscribe(level=level, contains=contains):
            payload = models.ServerLogEntry(
                id=entry.id,
                ts=entry.ts,
                level=entry.level,
                logger=entry.logger,
                message=entry.message,
                tags=list(entry.tags),
            ).model_dump(mode="json")
            yield f"event: log\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/capabilities", response_model=models.CapabilitiesResponse)
async def get_capabilities():
    """Return feature flags supported by this backend build."""
    return models.CapabilitiesResponse(
        studio_batch_delete=True,
        model_progress_snapshot=True,
        query_token_get_auth=True,
        runtime_defaults=True,
    )


@app.get("/llm/groq/models", response_model=models.GroqModelsResponse)
async def list_groq_models():
    """List selectable Groq models for story composition."""
    dynamic_models = list_available_groq_models(SETTINGS)
    return models.GroqModelsResponse(
        enabled=bool(SETTINGS.groq_api_key),
        default_model=SETTINGS.groq_model,
        models=dynamic_models,
    )


# ============================================
# VOICE PROFILE ENDPOINTS
# ============================================

@app.post("/profiles", response_model=models.VoiceProfileResponse)
async def create_profile(
    data: models.VoiceProfileCreate,
    db: Session = Depends(get_db),
):
    """Create a new voice profile."""
    try:
        return await profiles.create_profile(data, db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/profiles", response_model=List[models.VoiceProfileResponse])
async def list_profiles(db: Session = Depends(get_db)):
    """List all voice profiles."""
    return await profiles.list_profiles(db)


@app.post("/profiles/import", response_model=models.VoiceProfileResponse)
async def import_profile(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import a voice profile from a ZIP archive."""
    # Validate file size (max 100MB)
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    
    content = await _read_upload_bytes_or_400(
        file,
        max_size=MAX_FILE_SIZE,
        empty_detail="Uploaded profile archive is empty",
    )
    
    try:
        profile = await export_import.import_profile_from_zip(content, db)
        return profile
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/profiles/{profile_id}", response_model=models.VoiceProfileResponse)
async def get_profile(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Get a voice profile by ID."""
    profile = await profiles.get_profile(profile_id, db)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@app.put("/profiles/{profile_id}", response_model=models.VoiceProfileResponse)
async def update_profile(
    profile_id: str,
    data: models.VoiceProfileCreate,
    db: Session = Depends(get_db),
):
    """Update a voice profile."""
    profile = await profiles.update_profile(profile_id, data, db)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@app.delete("/profiles/{profile_id}")
async def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Delete a voice profile."""
    success = await profiles.delete_profile(profile_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"message": "Profile deleted successfully"}


@app.post("/profiles/{profile_id}/samples", response_model=models.ProfileSampleResponse)
async def add_profile_sample(
    profile_id: str,
    file: UploadFile = File(...),
    reference_text: str = Form(...),
    db: Session = Depends(get_db),
):
    """Add a sample to a voice profile."""
    # Save uploaded file to temporary location
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        content = await _read_upload_bytes_or_400(
            file,
            empty_detail="Uploaded audio sample is empty",
        )
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        sample = await profiles.add_profile_sample(
            profile_id,
            tmp_path,
            reference_text,
            db,
        )
        return sample
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/profiles/{profile_id}/samples", response_model=List[models.ProfileSampleResponse])
async def get_profile_samples(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Get all samples for a profile."""
    return await profiles.get_profile_samples(profile_id, db)


@app.delete("/profiles/samples/{sample_id}")
async def delete_profile_sample(
    sample_id: str,
    db: Session = Depends(get_db),
):
    """Delete a profile sample."""
    success = await profiles.delete_profile_sample(sample_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"message": "Sample deleted successfully"}


@app.put("/profiles/samples/{sample_id}", response_model=models.ProfileSampleResponse)
async def update_profile_sample(
    sample_id: str,
    data: models.ProfileSampleUpdate,
    db: Session = Depends(get_db),
):
    """Update a profile sample's reference text."""
    sample = await profiles.update_profile_sample(sample_id, data.reference_text, db)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    return sample


@app.post("/profiles/{profile_id}/avatar", response_model=models.VoiceProfileResponse)
async def upload_profile_avatar(
    profile_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload or update avatar image for a profile."""
    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
        content = await _read_upload_bytes_or_400(
            file,
            empty_detail="Uploaded avatar image is empty",
        )
        tmp.write(content)
        tmp_path = tmp.name

    try:
        profile = await profiles.upload_avatar(profile_id, tmp_path, db)
        return profile
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/profiles/{profile_id}/avatar")
async def get_profile_avatar(
    profile_id: str,
):
    """Get avatar image for a profile."""
    db = _new_db_session()
    try:
        profile = db.query(DBVoiceProfile).filter_by(id=profile_id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        if not profile.avatar_path:
            raise HTTPException(status_code=404, detail="No avatar found for this profile")
        avatar_path = Path(profile.avatar_path)
    finally:
        db.close()

    if not avatar_path.exists():
        raise HTTPException(status_code=404, detail="Avatar file not found")

    return FileResponse(avatar_path)


@app.delete("/profiles/{profile_id}/avatar")
async def delete_profile_avatar(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Delete avatar image for a profile."""
    success = await profiles.delete_avatar(profile_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Profile not found or no avatar to delete")
    return {"message": "Avatar deleted successfully"}


@app.get("/profiles/{profile_id}/export")
async def export_profile(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Export a voice profile as a ZIP archive."""
    try:
        # Get profile to get name for filename
        profile = await profiles.get_profile(profile_id, db)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        
        # Export to ZIP
        zip_bytes = export_import.export_profile_to_zip(profile_id, db)
        
        # Create safe filename
        safe_name = "".join(c for c in profile.name if c.isalnum() or c in (' ', '-', '_')).strip()
        if not safe_name:
            safe_name = "profile"
        filename = f"profile-{safe_name}.voicebox.zip"
        
        # Return as streaming response
        return StreamingResponse(
            io.BytesIO(zip_bytes),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# AUDIO CHANNEL ENDPOINTS
# ============================================

@app.get("/channels", response_model=List[models.AudioChannelResponse])
async def list_channels(db: Session = Depends(get_db)):
    """List all audio channels."""
    return await channels.list_channels(db)


@app.post("/channels", response_model=models.AudioChannelResponse)
async def create_channel(
    data: models.AudioChannelCreate,
    db: Session = Depends(get_db),
):
    """Create a new audio channel."""
    try:
        return await channels.create_channel(data, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/channels/{channel_id}", response_model=models.AudioChannelResponse)
async def get_channel(
    channel_id: str,
    db: Session = Depends(get_db),
):
    """Get an audio channel by ID."""
    channel = await channels.get_channel(channel_id, db)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@app.put("/channels/{channel_id}", response_model=models.AudioChannelResponse)
async def update_channel(
    channel_id: str,
    data: models.AudioChannelUpdate,
    db: Session = Depends(get_db),
):
    """Update an audio channel."""
    try:
        channel = await channels.update_channel(channel_id, data, db)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        return channel
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: str,
    db: Session = Depends(get_db),
):
    """Delete an audio channel."""
    try:
        success = await channels.delete_channel(channel_id, db)
        if not success:
            raise HTTPException(status_code=404, detail="Channel not found")
        return {"message": "Channel deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/channels/{channel_id}/voices")
async def get_channel_voices(
    channel_id: str,
    db: Session = Depends(get_db),
):
    """Get list of profile IDs assigned to a channel."""
    try:
        profile_ids = await channels.get_channel_voices(channel_id, db)
        return {"profile_ids": profile_ids}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/channels/{channel_id}/voices")
async def set_channel_voices(
    channel_id: str,
    data: models.ChannelVoiceAssignment,
    db: Session = Depends(get_db),
):
    """Set which voices are assigned to a channel."""
    try:
        await channels.set_channel_voices(channel_id, data, db)
        return {"message": "Channel voices updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/profiles/{profile_id}/channels")
async def get_profile_channels(
    profile_id: str,
    db: Session = Depends(get_db),
):
    """Get list of channel IDs assigned to a profile."""
    try:
        channel_ids = await channels.get_profile_channels(profile_id, db)
        return {"channel_ids": channel_ids}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/profiles/{profile_id}/channels")
async def set_profile_channels(
    profile_id: str,
    data: models.ProfileChannelAssignment,
    db: Session = Depends(get_db),
):
    """Set which channels a profile is assigned to."""
    try:
        await channels.set_profile_channels(profile_id, data, db)
        return {"message": "Profile channels updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================
# GENERATION ENDPOINTS
# ============================================

@app.post("/generate", response_model=models.GenerationResponse)
async def generate_speech(
    data: models.GenerationRequest,
    db: Session = Depends(get_db),
):
    """Generate speech from text using a voice profile."""
    task_manager = get_task_manager()
    if task_manager.get_model_operation_state() is not None:
        return _model_operation_conflict_response(task_manager, "generate", "tts")
    generation_id = str(uuid.uuid4())
    started_generation_task = False
    generation_failed = False

    try:
        # Start tracking generation
        task_manager.start_generation(
            task_id=generation_id,
            profile_id=data.profile_id,
            text=data.text,
        )
        started_generation_task = True

        # Get profile
        profile = await profiles.get_profile(data.profile_id, db)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        # Create voice prompt from profile
        voice_prompt = await profiles.create_voice_prompt_for_profile(
            data.profile_id,
            db,
        )

        # Generate audio
        tts_model = tts.get_tts_model()
        whisper_model = transcribe.get_whisper_model()

        if _is_cuda_single_model_mode() and whisper_model.is_loaded():
            logger.warning(
                "CUDA single-model mode: unloading Whisper before TTS generation request",
                extra={"tags": ["models", "memory", "single_model_mode"]},
            )
            transcribe.unload_whisper_model()

        # Load the requested model size if different from current (async to not block)
        defaults = _get_runtime_model_defaults(db)
        model_size = _resolve_runtime_tts_model_size(data.model_size or defaults.default_tts_model_size)

        if _is_cuda_single_model_mode() and model_size == "1.7B":
            loaded_tts_size = _get_loaded_tts_model_size(tts_model)
            if loaded_tts_size and loaded_tts_size != "1.7B":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": (
                            "Switching from Qwen TTS 0.6B to 1.7B in a live Colab CUDA session is blocked "
                            "for stability. Restart backend and activate 1.7B first."
                        ),
                        "error_code": "MODEL_SWITCH_REQUIRES_RESTART",
                    },
                )

        # Check if model needs to be downloaded first
        model_path = tts_model._get_model_path(model_size)
        if model_path.startswith("Qwen/"):
            # Model not cached - check if it exists remotely or needs download
            from huggingface_hub import constants as hf_constants
            repo_cache = Path(hf_constants.HF_HUB_CACHE) / ("models--" + model_path.replace("/", "--"))
            if not repo_cache.exists():
                # Start download in background
                model_name = f"qwen-tts-{model_size}"

                async def download_model_background():
                    try:
                        await tts_model.load_model_async(model_size)
                    except Exception as e:
                        task_manager.error_download(model_name, str(e))

                task_manager.start_download(model_name)
                asyncio.create_task(download_model_background())

                # Return explicit retryable error so clients don't misinterpret this as a successful generation.
                raise HTTPException(
                    status_code=503,
                    detail={
                        "message": f"Model {model_size} is being downloaded. Please wait and try again.",
                        "model_name": model_name,
                        "downloading": True,
                        "error_code": "MODEL_DOWNLOADING",
                    }
                )

        await tts_model.load_model_async(model_size)
        try:
            audio, sample_rate = await asyncio.wait_for(
                tts_model.generate(
                    data.text,
                    voice_prompt,
                    data.language,
                    data.seed,
                    data.instruct,
                ),
                timeout=SETTINGS.tts_generation_timeout_seconds,
            )
        except asyncio.TimeoutError as e:
            raise HTTPException(
                status_code=504,
                detail={
                    "message": (
                        "Audio generation timed out. Try shorter text/cards or retry after current work completes."
                    ),
                    "error_code": "GENERATION_TIMEOUT",
                },
            ) from e

        # Calculate duration
        duration = len(audio) / sample_rate

        # Save audio
        audio_path = config.get_generations_dir() / f"{generation_id}.wav"

        from .utils.audio import save_audio
        save_audio(audio, str(audio_path), sample_rate)

        # Create history entry
        generation = await history.create_generation(
            profile_id=data.profile_id,
            text=data.text,
            language=data.language,
            audio_path=str(audio_path),
            duration=duration,
            seed=data.seed,
            db=db,
            instruct=data.instruct,
        )
        
        return generation

    except HTTPException as e:
        if started_generation_task and e.status_code >= 400:
            generation_failed = True
            error_message, error_code = _extract_error_message_and_code(e.detail)
            task_manager.fail_generation(generation_id, error_message, error_code=error_code)
        raise
    except ValueError as e:
        if started_generation_task:
            generation_failed = True
            task_manager.fail_generation(generation_id, str(e), error_code="GENERATION_VALIDATION_ERROR")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        if _is_cuda_assert_error(e):
            if started_generation_task:
                generation_failed = True
                task_manager.fail_generation(
                    generation_id,
                    "CUDA runtime entered invalid state; restart backend process in Colab and retry.",
                    error_code="MODEL_GENERATE_CUDA_ASSERT",
                )
            logger.error(
                "MODEL_GENERATE_CUDA_ASSERT generation_id=%s profile_id=%s",
                generation_id,
                data.profile_id,
                extra={"tags": ["generate", "cuda_assert"]},
            )
            raise HTTPException(
                status_code=503,
                detail="CUDA runtime entered invalid state; restart backend process in Colab and retry.",
            ) from e
        if started_generation_task:
            generation_failed = True
            task_manager.fail_generation(generation_id, str(e), error_code="GENERATION_RUNTIME_ERROR")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if started_generation_task and not generation_failed:
            task_manager.complete_generation(generation_id)


# ============================================
# HISTORY ENDPOINTS
# ============================================

@app.get("/history", response_model=models.HistoryListResponse)
async def list_history(
    profile_id: Optional[str] = None,
    search: Optional[str] = None,
    origin: str = "all",
    story_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List generation history with optional filters."""
    try:
        query = models.HistoryQuery(
            profile_id=profile_id,
            search=search,
            origin=origin,
            story_id=story_id,
            limit=limit,
            offset=offset,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    return await history.list_generations(query, db)


@app.get("/history/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Get generation statistics."""
    return await history.get_generation_stats(db)


@app.post("/history/import")
async def import_generation(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import a generation from a ZIP archive."""
    # Validate file size (max 50MB)
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    
    content = await _read_upload_bytes_or_400(
        file,
        max_size=MAX_FILE_SIZE,
        empty_detail="Uploaded generation archive is empty",
    )
    
    try:
        result = await export_import.import_generation_from_zip(content, db)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history/{generation_id}", response_model=models.HistoryResponse)
async def get_generation(
    generation_id: str,
    db: Session = Depends(get_db),
):
    """Get a generation by ID."""
    generation = await history.get_history_generation(generation_id, db)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    return generation


@app.post("/history/bulk-delete", response_model=models.HistoryBulkDeleteResponse)
async def bulk_delete_history(
    data: models.HistoryBulkDeleteRequest,
    db: Session = Depends(get_db),
):
    """Bulk-delete generations using safe scope rules."""
    try:
        return await history.bulk_delete_generations(data, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/history/{generation_id}")
async def delete_generation(
    generation_id: str,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """Delete a generation."""
    result = await history.delete_generation(generation_id, db, force=force)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Generation not found")
    if result == "protected":
        raise HTTPException(
            status_code=409,
            detail="Generation is linked to one or more story cards and is protected.",
        )
    return {"message": "Generation deleted successfully"}


@app.get("/history/{generation_id}/export")
async def export_generation(
    generation_id: str,
    db: Session = Depends(get_db),
):
    """Export a generation as a ZIP archive."""
    try:
        # Get generation to create filename
        generation = db.query(DBGeneration).filter_by(id=generation_id).first()
        if not generation:
            raise HTTPException(status_code=404, detail="Generation not found")
        
        # Export to ZIP
        zip_bytes = export_import.export_generation_to_zip(generation_id, db)
        
        # Create safe filename from text
        safe_text = "".join(c for c in generation.text[:30] if c.isalnum() or c in (' ', '-', '_')).strip()
        if not safe_text:
            safe_text = "generation"
        filename = f"generation-{safe_text}.voicebox.zip"
        
        # Return as streaming response
        return StreamingResponse(
            io.BytesIO(zip_bytes),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history/{generation_id}/export-audio")
async def export_generation_audio(
    generation_id: str,
    db: Session = Depends(get_db),
):
    """Export only the audio file from a generation."""
    generation = db.query(DBGeneration).filter_by(id=generation_id).first()
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    
    audio_path = Path(generation.audio_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    # Create safe filename from text
    safe_text = "".join(c for c in generation.text[:30] if c.isalnum() or c in (' ', '-', '_')).strip()
    if not safe_text:
        safe_text = "generation"
    filename = f"{safe_text}.wav"
    
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


# ============================================
# TRANSCRIPTION ENDPOINTS
# ============================================

@app.post("/transcribe", response_model=models.TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    model_size: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Transcribe audio file to text."""
    # Save uploaded file to temporary location
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        content = await _read_upload_bytes_or_400(
            file,
            empty_detail="Uploaded audio for transcription is empty",
        )
        tmp.write(content)
        tmp_path = tmp.name

    selected_model_size = None
    stt_provider = _resolve_stt_provider()
    try:
        # Get audio duration
        from .utils.audio import load_audio
        audio, sr = load_audio(tmp_path)
        duration = len(audio) / sr

        if stt_provider == "groq":
            if not SETTINGS.groq_api_key:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "Groq STT is not configured. Set VOICEBOX_GROQ_API_KEY.",
                        "error_code": "STT_PROVIDER_NOT_CONFIGURED",
                    },
                )
            try:
                text = transcribe_audio_with_groq(
                    SETTINGS,
                    audio_path=tmp_path,
                    language=language,
                    model=SETTINGS.groq_stt_model,
                )
                return models.TranscriptionResponse(
                    text=text,
                    duration=duration,
                    provider="groq",
                    provider_model=SETTINGS.groq_stt_model,
                )
            except GroqSTTError as e:
                logger.error(
                    "STT_GROQ_ERROR code=%s model=%s detail=%s",
                    e.error_code,
                    SETTINGS.groq_stt_model,
                    str(e),
                    extra={"tags": ["transcribe", "groq", "error"]},
                )
                return JSONResponse(
                    status_code=e.status_code,
                    content={"detail": str(e), "error_code": e.error_code},
                )

        defaults = _get_runtime_model_defaults(db)
        selected_model_size = (model_size or defaults.default_whisper_model_size).strip().lower()
        if selected_model_size not in {"base", "small", "medium", "large"}:
            raise HTTPException(status_code=400, detail="Invalid whisper model_size")

        whisper_model = transcribe.get_whisper_model()
        tts_model = tts.get_tts_model()
        model_name = f"openai/whisper-{selected_model_size}"

        if _is_cuda_single_model_mode() and tts_model.is_loaded():
            logger.warning(
                "CUDA single-model mode: unloading TTS before Whisper transcription request",
                extra={"tags": ["models", "memory", "single_model_mode"]},
            )
            tts.unload_tts_model()

        # Check if model is cached
        from huggingface_hub import constants as hf_constants
        repo_cache = Path(hf_constants.HF_HUB_CACHE) / ("models--" + model_name.replace("/", "--"))
        if not repo_cache.exists():
            progress_model_name = f"whisper-{selected_model_size}"

            async def download_whisper_background():
                try:
                    await whisper_model.load_model_async(selected_model_size)
                except Exception as e:
                    get_task_manager().error_download(progress_model_name, str(e))

            get_task_manager().start_download(progress_model_name)
            asyncio.create_task(download_whisper_background())

            raise HTTPException(
                status_code=503,
                detail={
                    "message": f"Whisper model {selected_model_size} is being downloaded. Please wait and try again.",
                    "model_name": progress_model_name,
                    "downloading": True,
                    "error_code": "MODEL_DOWNLOADING",
                },
            )

        await whisper_model.load_model_async(selected_model_size)
        text = await whisper_model.transcribe(tmp_path, language)
        return models.TranscriptionResponse(
            text=text,
            duration=duration,
            provider="whisper_local",
            provider_model=f"whisper-{selected_model_size}",
        )
    except HTTPException:
        raise
    except Exception as e:
        if _is_cuda_assert_error(e):
            logger.error(
                "MODEL_TRANSCRIBE_CUDA_ASSERT model_size=%s",
                selected_model_size if 'selected_model_size' in locals() else "unknown",
                extra={"tags": ["transcribe", "cuda_assert"]},
            )
            raise HTTPException(
                status_code=503,
                detail="CUDA runtime entered invalid state; restart backend process in Colab and retry.",
            ) from e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ============================================
# STORY ENDPOINTS
# ============================================

@app.get("/stories", response_model=List[models.StoryResponse])
async def list_stories(db: Session = Depends(get_db)):
    """List all stories."""
    return await stories.list_stories(db)


@app.post("/stories", response_model=models.StoryResponse)
async def create_story(
    data: models.StoryCreate,
    db: Session = Depends(get_db),
):
    """Create a new story."""
    try:
        return await stories.create_story(data, db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/stories/render-from-history", response_model=models.StoryRenderJobResponse)
async def render_story_from_history(
    data: models.StoryRenderFromHistoryRequest,
    db: Session = Depends(get_db),
):
    """Create a background story render job from existing history generations."""
    try:
        return await stories.create_story_render_from_history(data, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stories/compose-roleplay", response_model=models.StoryRenderJobResponse)
async def compose_story_roleplay(
    data: models.StoryComposeWithGroqRequest,
    db: Session = Depends(get_db),
):
    """Use Groq to compose novel/roleplay lines and render them to audio."""
    try:
        return await stories.compose_story_with_groq(data, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/studio/director/suggestions", response_model=models.StudioDirectorSuggestionsResponse)
async def studio_director_suggestions(
    data: models.StudioDirectorSuggestionsRequest,
    db: Session = Depends(get_db),
):
    """Generate four Story Director preset suggestions from a character description."""
    try:
        return await studio_drafts.generate_studio_director_suggestions(data, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/studio/drafts", response_model=models.StudioDraftResponse)
async def create_studio_draft(
    data: models.StudioDraftCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a Studio draft from prompt and character mappings."""
    try:
        return await studio_drafts.create_studio_draft(data, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/studio/drafts", response_model=List[models.StudioDraftListItem])
async def list_studio_drafts(
    story_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List Studio drafts, optionally filtered by story."""
    return await studio_drafts.list_studio_drafts(db, story_id=story_id)


@app.get("/studio/drafts/{draft_id}", response_model=models.StudioDraftDetailResponse)
async def get_studio_draft(
    draft_id: str,
    db: Session = Depends(get_db),
):
    """Get Studio draft detail including cards."""
    draft = await studio_drafts.get_studio_draft(draft_id, db)
    if not draft:
        raise HTTPException(status_code=404, detail="Studio draft not found")
    return draft


@app.put("/studio/drafts/{draft_id}/lines", response_model=models.StudioDraftDetailResponse)
async def update_studio_draft_lines(
    draft_id: str,
    data: models.StudioDraftLinesUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update Studio draft cards (text, character, emotion, intensity, order)."""
    try:
        updated = await studio_drafts.update_studio_draft_lines(draft_id, data, db)
        if not updated:
            raise HTTPException(status_code=404, detail="Studio draft not found")
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/studio/drafts/{draft_id}/lines/delete", response_model=models.StudioDraftDetailResponse)
async def delete_studio_draft_lines(
    draft_id: str,
    data: models.StudioDraftLinesDeleteRequest,
    db: Session = Depends(get_db),
):
    """Delete one or more Studio draft cards."""
    try:
        updated = await studio_drafts.delete_studio_draft_lines(draft_id, data, db)
        if not updated:
            raise HTTPException(status_code=404, detail="Studio draft not found")
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/studio/drafts/{draft_id}/lines/{line_id}/preview", response_model=models.StudioPreviewResponse)
async def generate_studio_preview(
    draft_id: str,
    line_id: str,
    db: Session = Depends(get_db),
):
    """Generate or regenerate a short preview for one Studio card."""
    task_manager = get_task_manager()
    if task_manager.get_model_operation_state() is not None:
        return _model_operation_conflict_response(task_manager, "preview", "tts")
    try:
        return await studio_drafts.generate_studio_line_preview(draft_id, line_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/studio/drafts/{draft_id}/lines/{line_id}/preview/audio")
async def get_studio_preview_audio(
    draft_id: str,
    line_id: str,
):
    """Serve Studio card preview audio file."""
    db = _new_db_session()
    try:
        audio_path = await studio_drafts.get_studio_line_preview_audio_path(draft_id, line_id, db)
    finally:
        db.close()

    if not audio_path:
        raise HTTPException(status_code=404, detail="Preview audio not found")
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename=f"studio_preview_{line_id}.wav",
    )


@app.post("/studio/drafts/{draft_id}/render-final", response_model=models.StudioRenderFinalResponse)
async def render_studio_draft_final(
    draft_id: str,
    db: Session = Depends(get_db),
):
    """Launch final async story render from Studio draft cards."""
    try:
        result = await studio_drafts.render_studio_draft_final(draft_id, db)
        if not result:
            raise HTTPException(status_code=404, detail="Studio draft not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stories/jobs/{job_id}", response_model=models.StoryRenderStatusResponse)
async def get_story_render_job_status(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Get render job status and per-line progress."""
    status_data = await stories.get_story_render_status(job_id, db)
    if not status_data:
        raise HTTPException(status_code=404, detail="Story render job not found")
    return status_data


@app.get("/stories/{story_id}", response_model=models.StoryDetailResponse)
async def get_story(
    story_id: str,
    db: Session = Depends(get_db),
):
    """Get a story with all its items."""
    story = await stories.get_story(story_id, db)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@app.put("/stories/{story_id}", response_model=models.StoryResponse)
async def update_story(
    story_id: str,
    data: models.StoryCreate,
    db: Session = Depends(get_db),
):
    """Update a story."""
    story = await stories.update_story(story_id, data, db)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@app.delete("/stories/{story_id}")
async def delete_story(
    story_id: str,
    db: Session = Depends(get_db),
):
    """Delete a story."""
    success = await stories.delete_story(story_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Story not found")
    return {"message": "Story deleted successfully"}


@app.post("/stories/{story_id}/items", response_model=models.StoryItemDetail)
async def add_story_item(
    story_id: str,
    data: models.StoryItemCreate,
    db: Session = Depends(get_db),
):
    """Add a generation to a story."""
    item = await stories.add_item_to_story(story_id, data, db)
    if not item:
        raise HTTPException(status_code=404, detail="Story or generation not found")
    return item


@app.delete("/stories/{story_id}/items/{item_id}")
async def remove_story_item(
    story_id: str,
    item_id: str,
    db: Session = Depends(get_db),
):
    """Remove a story item from a story."""
    success = await stories.remove_item_from_story(story_id, item_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Story item not found")
    return {"message": "Item removed successfully"}


@app.put("/stories/{story_id}/items/times")
async def update_story_item_times(
    story_id: str,
    data: models.StoryItemBatchUpdate,
    db: Session = Depends(get_db),
):
    """Update story item timecodes."""
    success = await stories.update_story_item_times(story_id, data, db)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid timecode update request")
    return {"message": "Item timecodes updated successfully"}


@app.put("/stories/{story_id}/items/reorder", response_model=List[models.StoryItemDetail])
async def reorder_story_items(
    story_id: str,
    data: models.StoryItemReorder,
    db: Session = Depends(get_db),
):
    """Reorder story items and recalculate timecodes."""
    items = await stories.reorder_story_items(story_id, data.generation_ids, db)
    if items is None:
        raise HTTPException(status_code=400, detail="Invalid reorder request - ensure all generation IDs belong to this story")
    return items


@app.put("/stories/{story_id}/items/{item_id}/move", response_model=models.StoryItemDetail)
async def move_story_item(
    story_id: str,
    item_id: str,
    data: models.StoryItemMove,
    db: Session = Depends(get_db),
):
    """Move a story item (update position and/or track)."""
    item = await stories.move_story_item(story_id, item_id, data, db)
    if item is None:
        raise HTTPException(status_code=404, detail="Story item not found")
    return item


@app.put("/stories/{story_id}/items/{item_id}/trim", response_model=models.StoryItemDetail)
async def trim_story_item(
    story_id: str,
    item_id: str,
    data: models.StoryItemTrim,
    db: Session = Depends(get_db),
):
    """Trim a story item (update trim_start_ms and trim_end_ms)."""
    item = await stories.trim_story_item(story_id, item_id, data, db)
    if item is None:
        raise HTTPException(status_code=404, detail="Story item not found or invalid trim values")
    return item


@app.post("/stories/{story_id}/items/{item_id}/split", response_model=List[models.StoryItemDetail])
async def split_story_item(
    story_id: str,
    item_id: str,
    data: models.StoryItemSplit,
    db: Session = Depends(get_db),
):
    """Split a story item at a given time, creating two clips."""
    items = await stories.split_story_item(story_id, item_id, data, db)
    if items is None:
        raise HTTPException(status_code=404, detail="Story item not found or invalid split point")
    return items


@app.post("/stories/{story_id}/items/{item_id}/duplicate", response_model=models.StoryItemDetail)
async def duplicate_story_item(
    story_id: str,
    item_id: str,
    db: Session = Depends(get_db),
):
    """Duplicate a story item, creating a copy with all properties."""
    item = await stories.duplicate_story_item(story_id, item_id, db)
    if item is None:
        raise HTTPException(status_code=404, detail="Story item not found")
    return item


@app.get("/stories/{story_id}/export-audio")
async def export_story_audio(
    story_id: str,
    db: Session = Depends(get_db),
):
    """Export story as single mixed audio file with timecode-based mixing."""
    try:
        # Get story to create filename
        story = db.query(database.Story).filter_by(id=story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")
        
        # Export audio
        audio_bytes = await stories.export_story_audio(story_id, db)
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Story has no audio items")
        
        # Create safe filename
        safe_name = "".join(c for c in story.name if c.isalnum() or c in (' ', '-', '_')).strip()
        if not safe_name:
            safe_name = "story"
        filename = f"{safe_name}.wav"
        
        # Return as streaming response
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stories/{story_id}/audio")
async def get_story_mixed_audio(
    story_id: str,
):
    """Serve persisted story mixed audio file (from render job output)."""
    db = _new_db_session()
    try:
        story = db.query(DBStory).filter_by(id=story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        audio_path = await stories.get_story_audio_path(story_id, db)
        if not audio_path:
            raise HTTPException(status_code=404, detail="No persisted mixed audio found for this story")

        safe_name = "".join(c for c in story.name if c.isalnum() or c in (" ", "-", "_")).strip()
        if not safe_name:
            safe_name = "story"
    finally:
        db.close()

    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename=f"{safe_name}.wav",
    )


# ============================================
# FILE SERVING
# ============================================

@app.get("/audio/{generation_id}")
async def get_audio(generation_id: str):
    """Serve generated audio file."""
    db = _new_db_session()
    try:
        generation = db.query(DBGeneration).filter_by(id=generation_id).first()
        if not generation:
            raise HTTPException(status_code=404, detail="Generation not found")
        audio_path = Path(generation.audio_path)
    finally:
        db.close()

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename=f"generation_{generation_id}.wav",
    )


@app.get("/samples/{sample_id}")
async def get_sample_audio(sample_id: str):
    """Serve profile sample audio file."""
    db = _new_db_session()
    try:
        sample = db.query(DBProfileSample).filter_by(id=sample_id).first()
        if not sample:
            raise HTTPException(status_code=404, detail="Sample not found")
        audio_path = Path(sample.audio_path)
    finally:
        db.close()

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename=f"sample_{sample_id}.wav",
    )


# ============================================
# MODEL MANAGEMENT
# ============================================

@app.post("/models/load")
async def load_model(model_size: str = "1.7B"):
    """Manually load TTS model."""
    try:
        tts_model = tts.get_tts_model()
        await tts_model.load_model_async(model_size)
        return {"message": f"Model {model_size} loaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/models/unload")
async def unload_model():
    """Unload TTS model to free memory."""
    try:
        tts.unload_tts_model()
        return {"message": "Model unloaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/models/defaults", response_model=models.ModelDefaultsResponse)
async def get_model_defaults(db: Session = Depends(get_db)):
    """Get persisted runtime default model sizes."""
    return _get_runtime_model_defaults(db)


@app.put("/models/defaults", response_model=models.ModelDefaultsResponse)
async def update_model_defaults(
    data: models.ModelDefaultsUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update persisted runtime default model sizes."""
    return runtime_defaults.update_model_defaults(db, data)


@app.get("/models/runtime", response_model=models.RuntimeModelsResponse)
async def get_runtime_models(db: Session = Depends(get_db)):
    """Get currently loaded runtime models and configured defaults."""
    return runtime_defaults.get_runtime_models(db, settings=SETTINGS)


@app.post("/models/activate")
async def activate_model(data: models.ModelDownloadRequest):
    """Load a downloaded model into memory and make it active for runtime."""
    model_name = data.model_name
    warning_message: Optional[str] = None
    task_manager = get_task_manager()
    model_op_started = False
    model_op_completed = False
    model_op_error_code = "MODEL_ACTIVATE_RUNTIME_ERROR"
    model_op_error_message = f"Model activate failed: {model_name}"
    try:
        known_models = {
            "qwen-tts-1.7B",
            "qwen-tts-0.6B",
            "whisper-base",
            "whisper-small",
            "whisper-medium",
            "whisper-large",
        }
        if model_name not in known_models:
            raise HTTPException(status_code=400, detail=f"Unknown model: {model_name}")
        if _is_stt_remote_only_mode() and model_name.startswith("whisper-"):
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "Whisper local is disabled in this Colab profile. Transcription runs via Groq.",
                    "error_code": "STT_REMOTE_ONLY",
                },
            )
        if _is_cuda_single_model_mode() and model_name == "qwen-tts-0.6B":
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "Qwen TTS 0.6B is disabled in Colab/CUDA mode. Use Qwen TTS 1.7B.",
                    "error_code": "MODEL_SIZE_DISABLED_IN_COLAB",
                },
            )

        if _is_cuda_single_model_mode() and model_name == "qwen-tts-1.7B":
            loaded_tts_size = _get_loaded_tts_model_size(tts.get_tts_model())
            if loaded_tts_size and loaded_tts_size != "1.7B":
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": (
                            "Switching from Qwen TTS 0.6B to 1.7B in a live Colab CUDA session is blocked "
                            "for stability. Restart backend and activate 1.7B first."
                        ),
                        "error_code": "MODEL_SWITCH_REQUIRES_RESTART",
                    },
                )

        if not task_manager.start_model_operation("activate", model_name):
            return _model_operation_conflict_response(task_manager, "activate", model_name)
        model_op_started = True

        if _is_cuda_single_model_mode():
            if model_name.startswith("qwen-tts"):
                whisper_model = transcribe.get_whisper_model()
                if whisper_model.is_loaded():
                    transcribe.unload_whisper_model()
                    warning_message = (
                        "Whisper model was unloaded to free GPU memory. "
                        "In Colab CUDA mode, keep only one model loaded at a time."
                    )
                    logger.warning(
                        "CUDA single-model mode: unloaded Whisper before activating %s",
                        model_name,
                        extra={"tags": ["models", "memory", "single_model_mode"]},
                    )
            elif model_name.startswith("whisper-"):
                tts_model = tts.get_tts_model()
                if tts_model.is_loaded():
                    tts.unload_tts_model()
                    warning_message = (
                        "Qwen TTS model was unloaded to free GPU memory. "
                        "In Colab CUDA mode, keep only one model loaded at a time."
                    )
                    logger.warning(
                        "CUDA single-model mode: unloaded Qwen TTS before activating %s",
                        model_name,
                        extra={"tags": ["models", "memory", "single_model_mode"]},
                    )

        if model_name == "qwen-tts-1.7B":
            await tts.get_tts_model().load_model_async("1.7B")
            task_manager.complete_model_operation(f"Model activated: {model_name}")
            model_op_completed = True
            return {"message": "Model qwen-tts-1.7B activated", "warning": warning_message}
        if model_name == "qwen-tts-0.6B":
            await tts.get_tts_model().load_model_async("0.6B")
            task_manager.complete_model_operation(f"Model activated: {model_name}")
            model_op_completed = True
            return {"message": "Model qwen-tts-0.6B activated", "warning": warning_message}
        if model_name == "whisper-base":
            await transcribe.get_whisper_model().load_model_async("base")
            task_manager.complete_model_operation(f"Model activated: {model_name}")
            model_op_completed = True
            return {"message": "Model whisper-base activated", "warning": warning_message}
        if model_name == "whisper-small":
            await transcribe.get_whisper_model().load_model_async("small")
            task_manager.complete_model_operation(f"Model activated: {model_name}")
            model_op_completed = True
            return {"message": "Model whisper-small activated", "warning": warning_message}
        if model_name == "whisper-medium":
            await transcribe.get_whisper_model().load_model_async("medium")
            task_manager.complete_model_operation(f"Model activated: {model_name}")
            model_op_completed = True
            return {"message": "Model whisper-medium activated", "warning": warning_message}
        if model_name == "whisper-large":
            await transcribe.get_whisper_model().load_model_async("large")
            task_manager.complete_model_operation(f"Model activated: {model_name}")
            model_op_completed = True
            return {"message": "Model whisper-large activated", "warning": warning_message}
    except Exception as e:
        backend_type = get_backend_type()
        tts_model = tts.get_tts_model()
        device = getattr(tts_model, "device", None)
        torch_dtype = getattr(tts_model, "torch_dtype", None)
        error_text = str(e)
        normalized_error = error_text.lower()

        logger.exception(
            "Model activation failed: model=%s backend=%s device=%s dtype=%s",
            model_name,
            backend_type,
            device,
            torch_dtype,
            extra={"tags": ["models", "activate", "error"]},
        )

        if "device-side assert" in normalized_error:
            model_op_error_code = "MODEL_ACTIVATE_CUDA_ASSERT"
            model_op_error_message = (
                "CUDA runtime entered invalid state; restart backend process in Colab and retry."
            )
            logger.error(
                "MODEL_ACTIVATE_CUDA_ASSERT model=%s backend=%s device=%s dtype=%s",
                model_name,
                backend_type,
                device,
                torch_dtype,
                extra={"tags": ["models", "activate", "cuda_assert"]},
            )
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "CUDA runtime entered invalid state; restart backend process in Colab and retry.",
                    "error_code": "MODEL_ACTIVATE_CUDA_ASSERT",
                },
            )

        return JSONResponse(
            status_code=500,
            content={
                "detail": error_text,
                "error_code": "MODEL_ACTIVATE_RUNTIME_ERROR",
            },
        )
    finally:
        if model_op_started and not model_op_completed:
            # Some branches return JSONResponse on errors; ensure lock is released and event recorded.
            task_manager.fail_model_operation(model_op_error_message, error_code=model_op_error_code)


@app.get("/models/progress/{model_name}")
async def get_model_progress(model_name: str):
    """Get model download progress via Server-Sent Events."""
    from fastapi.responses import StreamingResponse
    
    progress_manager = get_progress_manager()
    
    async def event_generator():
        """Generate SSE events for progress updates."""
        async for event in progress_manager.subscribe(model_name):
            yield event
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/models/progress-snapshot/{model_name}")
async def get_model_progress_snapshot(model_name: str):
    """Get latest model download progress as JSON (polling-friendly)."""
    progress_manager = get_progress_manager()
    return progress_manager.get_progress(model_name)


@app.get("/models/status", response_model=models.ModelStatusListResponse)
async def get_model_status():
    """Get status of all available models."""
    from huggingface_hub import constants as hf_constants
    from pathlib import Path
    
    backend_type = get_backend_type()
    task_manager = get_task_manager()
    stt_remote_only = _is_stt_remote_only_mode()
    stt_remote_reason = "Disabled in Colab profile (STT remote via Groq)"
    
    # Get set of currently downloading model names
    active_download_names = {
        task.model_name
        for task in task_manager.get_active_downloads()
        if task.status in {"downloading", "extracting"}
    }
    
    # Try to import scan_cache_dir (might not be available in older versions)
    try:
        from huggingface_hub import scan_cache_dir
        use_scan_cache = True
    except ImportError:
        use_scan_cache = False
    
    def check_tts_loaded(model_size: str):
        """Check if TTS model is loaded with specific size."""
        try:
            tts_model = tts.get_tts_model()
            return tts_model.is_loaded() and getattr(tts_model, 'model_size', None) == model_size
        except Exception:
            return False
    
    def check_whisper_loaded(model_size: str):
        """Check if Whisper model is loaded with specific size."""
        try:
            whisper_model = transcribe.get_whisper_model()
            return whisper_model.is_loaded() and getattr(whisper_model, 'model_size', None) == model_size
        except Exception:
            return False
    
    # Use backend-specific model IDs
    if backend_type == "mlx":
        tts_1_7b_id = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
        tts_0_6b_id = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"  # Fallback to 1.7B
        # MLX backend uses openai/whisper-* models, not mlx-community
        whisper_base_id = "openai/whisper-base"
        whisper_small_id = "openai/whisper-small"
        whisper_medium_id = "openai/whisper-medium"
        whisper_large_id = "openai/whisper-large"
    else:
        tts_1_7b_id = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
        tts_0_6b_id = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        whisper_base_id = "openai/whisper-base"
        whisper_small_id = "openai/whisper-small"
        whisper_medium_id = "openai/whisper-medium"
        whisper_large_id = "openai/whisper-large"
    
    model_configs = [
        {
            "model_name": "qwen-tts-1.7B",
            "display_name": "Qwen TTS 1.7B",
            "hf_repo_id": tts_1_7b_id,
            "model_size": "1.7B",
            "check_loaded": lambda: check_tts_loaded("1.7B"),
        },
        {
            "model_name": "qwen-tts-0.6B",
            "display_name": "Qwen TTS 0.6B",
            "hf_repo_id": tts_0_6b_id,
            "model_size": "0.6B",
            "check_loaded": lambda: check_tts_loaded("0.6B"),
        },
        {
            "model_name": "whisper-base",
            "display_name": "Whisper Base",
            "hf_repo_id": whisper_base_id,
            "model_size": "base",
            "check_loaded": lambda: check_whisper_loaded("base"),
        },
        {
            "model_name": "whisper-small",
            "display_name": "Whisper Small",
            "hf_repo_id": whisper_small_id,
            "model_size": "small",
            "check_loaded": lambda: check_whisper_loaded("small"),
        },
        {
            "model_name": "whisper-medium",
            "display_name": "Whisper Medium",
            "hf_repo_id": whisper_medium_id,
            "model_size": "medium",
            "check_loaded": lambda: check_whisper_loaded("medium"),
        },
        {
            "model_name": "whisper-large",
            "display_name": "Whisper Large",
            "hf_repo_id": whisper_large_id,
            "model_size": "large",
            "check_loaded": lambda: check_whisper_loaded("large"),
        },
    ]
    if _is_cuda_single_model_mode():
        model_configs = [cfg for cfg in model_configs if cfg["model_name"] != "qwen-tts-0.6B"]
    
    # Build a mapping of model_name -> hf_repo_id so we can check if shared repos are downloading
    model_to_repo = {cfg["model_name"]: cfg["hf_repo_id"] for cfg in model_configs}
    
    # Get the set of hf_repo_ids that are currently being downloaded
    # This handles the case where multiple models share the same repo (e.g., 0.6B and 1.7B on MLX)
    active_download_repos = {model_to_repo.get(name) for name in active_download_names if name in model_to_repo}
    
    # Get HuggingFace cache info (if available)
    cache_info = None
    if use_scan_cache:
        try:
            cache_info = scan_cache_dir()
        except Exception:
            # Function failed, continue without it
            pass
    
    statuses = []
    
    for config in model_configs:
        try:
            downloaded = False
            size_mb = None
            loaded = False
            
            # Method 1: Try using scan_cache_dir if available
            if cache_info:
                repo_id = config["hf_repo_id"]
                for repo in cache_info.repos:
                    if repo.repo_id == repo_id:
                        # Check if actual model weight files exist (not just config files)
                        # scan_cache_dir only shows completed files, so check if any are model weights
                        has_model_weights = False
                        for rev in repo.revisions:
                            for f in rev.files:
                                fname = f.file_name.lower()
                                if fname.endswith(('.safetensors', '.bin', '.pt', '.pth', '.npz')):
                                    has_model_weights = True
                                    break
                            if has_model_weights:
                                break
                        
                        # Also check for .incomplete files in blobs directory (downloads in progress)
                        has_incomplete = False
                        try:
                            cache_dir = hf_constants.HF_HUB_CACHE
                            blobs_dir = Path(cache_dir) / ("models--" + repo_id.replace("/", "--")) / "blobs"
                            if blobs_dir.exists():
                                has_incomplete = any(blobs_dir.glob("*.incomplete"))
                        except Exception:
                            pass
                        
                        # Only mark as downloaded if we have model weights AND no incomplete files
                        if has_model_weights and not has_incomplete:
                            downloaded = True
                            # Calculate size from cache info
                            try:
                                total_size = sum(revision.size_on_disk for revision in repo.revisions)
                                size_mb = total_size / (1024 * 1024)
                            except Exception:
                                pass
                        break
            
            # Method 2: Fallback to checking cache directory directly (using HuggingFace's OS-specific cache location)
            if not downloaded:
                try:
                    cache_dir = hf_constants.HF_HUB_CACHE
                    repo_cache = Path(cache_dir) / ("models--" + config["hf_repo_id"].replace("/", "--"))
                    
                    if repo_cache.exists():
                        # Check for .incomplete files - if any exist, download is still in progress
                        blobs_dir = repo_cache / "blobs"
                        has_incomplete = blobs_dir.exists() and any(blobs_dir.glob("*.incomplete"))
                        
                        if not has_incomplete:
                            # Check for actual model weight files (not just index files)
                            # in the snapshots directory (symlinks to completed blobs)
                            snapshots_dir = repo_cache / "snapshots"
                            has_model_files = False
                            if snapshots_dir.exists():
                                has_model_files = (
                                    any(snapshots_dir.rglob("*.bin")) or
                                    any(snapshots_dir.rglob("*.safetensors")) or
                                    any(snapshots_dir.rglob("*.pt")) or
                                    any(snapshots_dir.rglob("*.pth")) or
                                    any(snapshots_dir.rglob("*.npz"))
                                )
                            
                            if has_model_files:
                                downloaded = True
                                # Calculate size (exclude .incomplete files)
                                try:
                                    total_size = sum(
                                        f.stat().st_size for f in repo_cache.rglob("*") 
                                        if f.is_file() and not f.name.endswith('.incomplete')
                                    )
                                    size_mb = total_size / (1024 * 1024)
                                except Exception:
                                    pass
                except Exception:
                    pass
            
            # Method 3 removed - checking for config.json is too lenient
            # Methods 1 and 2 properly verify that model weight files exist
            
            # Check if loaded in memory
            try:
                loaded = config["check_loaded"]()
            except Exception:
                loaded = False
            
            # Check if this model (or its shared repo) is currently being downloaded
            is_downloading = config["hf_repo_id"] in active_download_repos
            
            # If downloading, don't report as downloaded (partial files exist)
            if is_downloading:
                downloaded = False
                size_mb = None  # Don't show partial size during download
            
            statuses.append(models.ModelStatus(
                model_name=config["model_name"],
                display_name=config["display_name"],
                downloaded=downloaded,
                downloading=is_downloading,
                size_mb=size_mb,
                loaded=loaded,
                disabled=stt_remote_only and config["model_name"].startswith("whisper-"),
                disabled_reason=(
                    stt_remote_reason
                    if stt_remote_only and config["model_name"].startswith("whisper-")
                    else None
                ),
            ))
        except Exception as e:
            # If check fails, try to at least check if loaded
            try:
                loaded = config["check_loaded"]()
            except Exception:
                loaded = False
            
            # Check if this model (or its shared repo) is currently being downloaded
            is_downloading = config["hf_repo_id"] in active_download_repos
            
            statuses.append(models.ModelStatus(
                model_name=config["model_name"],
                display_name=config["display_name"],
                downloaded=False,  # Assume not downloaded if check failed
                downloading=is_downloading,
                size_mb=None,
                loaded=loaded,
                disabled=stt_remote_only and config["model_name"].startswith("whisper-"),
                disabled_reason=(
                    stt_remote_reason
                    if stt_remote_only and config["model_name"].startswith("whisper-")
                    else None
                ),
            ))
    
    return models.ModelStatusListResponse(models=statuses)


@app.post("/models/download")
async def trigger_model_download(request: models.ModelDownloadRequest):
    """Trigger download of a specific model."""
    import asyncio
    
    task_manager = get_task_manager()
    progress_manager = get_progress_manager()
    
    model_configs = {
        "qwen-tts-1.7B": {
            "model_size": "1.7B",
            "load_func": lambda: tts.get_tts_model().load_model("1.7B"),
        },
        "qwen-tts-0.6B": {
            "model_size": "0.6B",
            "load_func": lambda: tts.get_tts_model().load_model("0.6B"),
        },
        "whisper-base": {
            "model_size": "base",
            "load_func": lambda: transcribe.get_whisper_model().load_model("base"),
        },
        "whisper-small": {
            "model_size": "small",
            "load_func": lambda: transcribe.get_whisper_model().load_model("small"),
        },
        "whisper-medium": {
            "model_size": "medium",
            "load_func": lambda: transcribe.get_whisper_model().load_model("medium"),
        },
        "whisper-large": {
            "model_size": "large",
            "load_func": lambda: transcribe.get_whisper_model().load_model("large"),
        },
    }
    
    if request.model_name not in model_configs:
        raise HTTPException(status_code=400, detail=f"Unknown model: {request.model_name}")
    if _is_stt_remote_only_mode() and request.model_name.startswith("whisper-"):
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Whisper local is disabled in this Colab profile. Transcription runs via Groq.",
                "error_code": "STT_REMOTE_ONLY",
            },
        )
    if _is_cuda_single_model_mode() and request.model_name == "qwen-tts-0.6B":
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Qwen TTS 0.6B is disabled in Colab/CUDA mode. Use Qwen TTS 1.7B.",
                "error_code": "MODEL_SIZE_DISABLED_IN_COLAB",
            },
        )

    if not task_manager.start_model_operation("download", request.model_name):
        return _model_operation_conflict_response(task_manager, "download", request.model_name)
    
    config = model_configs[request.model_name]
    
    async def download_in_background():
        """Download model in background without blocking the HTTP request."""
        try:
            # Call the load function (which may be async)
            result = config["load_func"]()
            # If it's a coroutine, await it
            if asyncio.iscoroutine(result):
                await result
            task_manager.complete_download(
                request.model_name,
                message=f"Model download completed: {request.model_name}",
            )
            task_manager.complete_model_operation(
                message=f"Model download completed: {request.model_name}",
            )
        except Exception as e:
            task_manager.error_download(
                request.model_name,
                str(e),
                error_code="MODEL_DOWNLOAD_FAILED",
            )
            task_manager.fail_model_operation(str(e), error_code="MODEL_DOWNLOAD_FAILED")

    try:
        # Start tracking download
        task_manager.start_download(request.model_name)
        
        # Initialize progress state so SSE endpoint has initial data to send.
        # This fixes a race condition where the frontend connects to SSE before
        # any progress callbacks have fired (especially for large models like Qwen
        # where huggingface_hub takes time to fetch metadata for all files).
        progress_manager.update_progress(
            model_name=request.model_name,
            current=0,
            total=0,  # Will be updated once actual total is known
            filename="Connecting to HuggingFace...",
            status="downloading",
        )

        # Start download in background task (don't await)
        asyncio.create_task(download_in_background())
    except Exception as e:
        task_manager.error_download(
            request.model_name,
            str(e),
            error_code="MODEL_DOWNLOAD_START_FAILED",
        )
        task_manager.fail_model_operation(str(e), error_code="MODEL_DOWNLOAD_START_FAILED")
        raise HTTPException(status_code=500, detail=str(e))

    # Return immediately - frontend should poll progress endpoint
    return {"message": f"Model {request.model_name} download started"}


@app.delete("/models/{model_name}")
async def delete_model(model_name: str):
    """Delete a downloaded model from the HuggingFace cache."""
    import shutil
    from huggingface_hub import constants as hf_constants
    task_manager = get_task_manager()
    model_op_started = False
    model_op_completed = False
    model_op_error_code = "MODEL_DELETE_FAILED"
    model_op_error_message = f"Model delete failed: {model_name}"
    
    # Map model names to HuggingFace repo IDs
    model_configs = {
        "qwen-tts-1.7B": {
            "hf_repo_id": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            "model_size": "1.7B",
            "model_type": "tts",
        },
        "qwen-tts-0.6B": {
            "hf_repo_id": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            "model_size": "0.6B",
            "model_type": "tts",
        },
        "whisper-base": {
            "hf_repo_id": "openai/whisper-base",
            "model_size": "base",
            "model_type": "whisper",
        },
        "whisper-small": {
            "hf_repo_id": "openai/whisper-small",
            "model_size": "small",
            "model_type": "whisper",
        },
        "whisper-medium": {
            "hf_repo_id": "openai/whisper-medium",
            "model_size": "medium",
            "model_type": "whisper",
        },
        "whisper-large": {
            "hf_repo_id": "openai/whisper-large",
            "model_size": "large",
            "model_type": "whisper",
        },
    }
    
    if model_name not in model_configs:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_name}")
    if _is_stt_remote_only_mode() and model_name.startswith("whisper-"):
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Whisper local is disabled in this Colab profile. Transcription runs via Groq.",
                "error_code": "STT_REMOTE_ONLY",
            },
        )
    if _is_cuda_single_model_mode() and model_name == "qwen-tts-0.6B":
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Qwen TTS 0.6B is disabled in Colab/CUDA mode. Delete is not required.",
                "error_code": "MODEL_SIZE_DISABLED_IN_COLAB",
            },
        )
    
    if not task_manager.start_model_operation("delete", model_name):
        return _model_operation_conflict_response(task_manager, "delete", model_name)
    model_op_started = True

    config = model_configs[model_name]
    hf_repo_id = config["hf_repo_id"]
    
    try:
        # Check if model is loaded and unload it first
        if config["model_type"] == "tts":
            tts_model = tts.get_tts_model()
            if tts_model.is_loaded() and tts_model.model_size == config["model_size"]:
                tts.unload_tts_model()
        elif config["model_type"] == "whisper":
            whisper_model = transcribe.get_whisper_model()
            if whisper_model.is_loaded() and whisper_model.model_size == config["model_size"]:
                transcribe.unload_whisper_model()
        
        # Find and delete the cache directory (using HuggingFace's OS-specific cache location)
        cache_dir = hf_constants.HF_HUB_CACHE
        repo_cache_dir = Path(cache_dir) / ("models--" + hf_repo_id.replace("/", "--"))
        
        # Check if the cache directory exists
        if not repo_cache_dir.exists():
            raise HTTPException(status_code=404, detail=f"Model {model_name} not found in cache")
        
        # Delete the entire cache directory for this model
        try:
            shutil.rmtree(repo_cache_dir)
        except OSError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete model cache directory: {str(e)}"
            )
        
        task_manager.complete_model_operation(message=f"Model deleted: {model_name}")
        model_op_completed = True
        return {"message": f"Model {model_name} deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {str(e)}")
    finally:
        if model_op_started and not model_op_completed:
            task_manager.fail_model_operation(
                model_op_error_message,
                error_code=model_op_error_code,
            )


@app.post("/cache/clear")
async def clear_cache():
    """Clear all voice prompt caches (memory and disk)."""
    try:
        deleted_count = clear_voice_prompt_cache()
        return {
            "message": f"Voice prompt cache cleared successfully",
            "files_deleted": deleted_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


# ============================================
# TASK MANAGEMENT
# ============================================


def _collect_active_task_payload() -> tuple[
    List[models.ActiveDownloadTask],
    List[models.ActiveGenerationTask],
    List[models.ActiveStoryRenderTask],
]:
    task_manager = get_task_manager()
    progress_manager = get_progress_manager()

    # Get active downloads from both task manager and progress manager.
    active_downloads: List[models.ActiveDownloadTask] = []
    task_manager_downloads = task_manager.get_active_downloads()
    progress_active = progress_manager.get_all_active()

    download_map = {task.model_name: task for task in task_manager_downloads}
    progress_map = {p["model_name"]: p for p in progress_active}

    all_model_names = set(download_map.keys()) | set(progress_map.keys())
    for model_name in all_model_names:
        task = download_map.get(model_name)
        progress = progress_map.get(model_name)

        if task:
            active_downloads.append(
                models.ActiveDownloadTask(
                    model_name=model_name,
                    status=task.status,
                    started_at=task.started_at,
                )
            )
        elif progress:
            timestamp_str = progress.get("timestamp")
            if timestamp_str:
                try:
                    started_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    started_at = datetime.utcnow()
            else:
                started_at = datetime.utcnow()

            active_downloads.append(
                models.ActiveDownloadTask(
                    model_name=model_name,
                    status=progress.get("status", "downloading"),
                    started_at=started_at,
                )
            )

    active_generations: List[models.ActiveGenerationTask] = []
    for gen_task in task_manager.get_active_generations():
        active_generations.append(
            models.ActiveGenerationTask(
                task_id=gen_task.task_id,
                profile_id=gen_task.profile_id,
                text_preview=gen_task.text_preview,
                started_at=gen_task.started_at,
            )
        )

    active_story_renders: List[models.ActiveStoryRenderTask] = []
    for render_task in task_manager.get_active_story_renders():
        active_story_renders.append(
            models.ActiveStoryRenderTask(
                job_id=render_task.job_id,
                story_id=render_task.story_id,
                status=render_task.status,
                total_lines=render_task.total_lines,
                processed_lines=render_task.processed_lines,
                started_at=render_task.started_at,
            )
        )

    return active_downloads, active_generations, active_story_renders


def _to_task_terminal_event_model(event) -> models.TaskTerminalEvent:
    return models.TaskTerminalEvent(
        id=event.id,
        kind=event.kind,
        state=event.state,
        entity_id=event.entity_id,
        message=event.message,
        error_code=event.error_code,
        created_at=event.created_at,
    )


@app.get("/tasks/active", response_model=models.ActiveTasksResponse)
async def get_active_tasks():
    """Return all currently active downloads and generations."""
    active_downloads, active_generations, active_story_renders = _collect_active_task_payload()

    return models.ActiveTasksResponse(
        downloads=active_downloads,
        generations=active_generations,
        story_renders=active_story_renders,
    )


@app.get("/tasks/summary", response_model=models.ActiveTasksSummaryResponse)
async def get_active_tasks_summary():
    """Compact active task summary suitable for lightweight polling."""
    task_manager = get_task_manager()
    active_downloads, active_generations, active_story_renders = _collect_active_task_payload()
    model_op = task_manager.get_model_operation_state()
    last_terminal_event = task_manager.get_last_terminal_event()
    return models.ActiveTasksSummaryResponse(
        downloads_active=len(active_downloads),
        generations_active=len(active_generations),
        story_renders_active=len(active_story_renders),
        has_active_tasks=bool(active_downloads or active_generations or active_story_renders),
        downloading_models=sorted([task.model_name for task in active_downloads]),
        model_ops_busy=model_op is not None,
        model_op_kind=model_op.kind if model_op else None,
        model_op_model_name=model_op.model_name if model_op else None,
        model_op_started_at=model_op.started_at if model_op else None,
        last_terminal_event=_to_task_terminal_event_model(last_terminal_event)
        if last_terminal_event
        else None,
    )


@app.get("/tasks/events", response_model=models.TaskEventsResponse)
async def get_task_events(
    limit: int = 30,
    since_id: Optional[int] = None,
):
    """Return terminal task events for frontend operational state."""
    task_manager = get_task_manager()
    events = task_manager.list_terminal_events(since_id=since_id, limit=limit)
    serialized = [_to_task_terminal_event_model(event) for event in events]
    last_id = serialized[-1].id if serialized else (since_id or 0)
    return models.TaskEventsResponse(events=serialized, last_id=last_id)


@app.post("/stories/jobs/{job_id}/cancel", response_model=models.TaskCancelStoryRendersResponse)
async def cancel_story_render_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Request cancellation for a running story render job."""
    job = db.query(DBStoryRenderJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Story render job not found")

    task_manager = get_task_manager()
    active_before = len(task_manager.get_active_story_renders())
    cancelled = task_manager.request_story_render_cancel(job_id)
    return models.TaskCancelStoryRendersResponse(
        cancelled_job_ids=[job_id] if cancelled else [],
        active_before=active_before,
        message=(
            f"Cancellation requested for story render job {job_id}."
            if cancelled
            else f"Story render job {job_id} is not currently running."
        ),
    )


@app.post("/tasks/story-renders/cancel", response_model=models.TaskCancelStoryRendersResponse)
async def cancel_all_active_story_renders():
    """Request cancellation for all running story render jobs."""
    task_manager = get_task_manager()
    active_before = len(task_manager.get_active_story_renders())
    cancelled_ids = task_manager.request_cancel_all_story_renders()
    return models.TaskCancelStoryRendersResponse(
        cancelled_job_ids=cancelled_ids,
        active_before=active_before,
        message=(
            f"Cancellation requested for {len(cancelled_ids)} active story render job(s)."
            if cancelled_ids
            else "No active story render jobs to cancel."
        ),
    )


@app.post("/server/runtime/reset", response_model=models.RuntimeResetResponse)
async def reset_server_runtime():
    """
    Reset runtime state without killing the process.
    Useful in Colab when GPU memory/task state gets inconsistent.
    """
    task_manager = get_task_manager()
    if task_manager.get_model_operation_state() is not None:
        return _model_operation_conflict_response(task_manager, "reset_runtime", "server")

    cancelled_story_render_ids = task_manager.request_cancel_all_story_renders()
    cleared_generation_ids = task_manager.clear_active_generations(
        reason="Generation cleared by runtime reset.",
        error_code="TASK_RESET_BY_OPERATOR",
    )

    tts_model = tts.get_tts_model()
    whisper_model = transcribe.get_whisper_model()
    tts_was_loaded = tts_model.is_loaded()
    whisper_was_loaded = whisper_model.is_loaded()

    try:
        if tts_was_loaded:
            tts.unload_tts_model()
        if whisper_was_loaded:
            transcribe.unload_whisper_model()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Runtime reset failed: {e}") from e

    logger.warning(
        "Runtime reset requested: cancelled_story_renders=%s cleared_generations=%s",
        len(cancelled_story_render_ids),
        len(cleared_generation_ids),
        extra={"tags": ["runtime", "control", "reset"]},
    )
    return models.RuntimeResetResponse(
        message="Runtime reset requested. Active renders are being cancelled and loaded models were unloaded.",
        cancelled_story_render_ids=cancelled_story_render_ids,
        cleared_generation_ids=cleared_generation_ids,
        tts_was_loaded=tts_was_loaded,
        whisper_was_loaded=whisper_was_loaded,
    )


# ============================================
# STARTUP & SHUTDOWN
# ============================================

def _get_gpu_status() -> str:
    """Get GPU availability status."""
    backend_type = get_backend_type()
    if torch.cuda.is_available():
        return f"CUDA ({torch.cuda.get_device_name(0)})"
    elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        return "MPS (Apple Silicon)"
    elif backend_type == "mlx":
        return "Metal (Apple Silicon via MLX)"
    return "None (CPU only)"


@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    runtime_logs.initialize_runtime_logs()
    logger.info("voicebox API starting up...")
    logger.info("Colab profile: %s", SETTINGS.colab_profile)
    logger.info("API key protection enabled: %s", bool(SETTINGS.api_key))
    logger.info("TTS provider: %s", "qwen_local")
    logger.info(
        "STT provider: %s",
        "groq_remote" if _resolve_stt_provider() == "groq" else "whisper_local",
    )
    database.init_db()
    logger.info("Database initialized at %s", database._db_path)
    backend_type = get_backend_type()
    logger.info("Backend: %s", backend_type.upper())
    logger.info("GPU available: %s", _get_gpu_status())

    # Initialize progress manager with main event loop for thread-safe operations
    try:
        progress_manager = get_progress_manager()
        progress_manager._set_main_loop(asyncio.get_running_loop())
        logger.info("Progress manager initialized with event loop")
    except Exception as e:
        logger.warning("Could not initialize progress manager event loop: %s", e)

    # Ensure HuggingFace cache directory exists
    try:
        from huggingface_hub import constants as hf_constants
        cache_dir = Path(hf_constants.HF_HUB_CACHE)
        cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("HuggingFace cache directory: %s", cache_dir)
    except Exception as e:
        logger.warning("Could not create HuggingFace cache directory: %s", e)
        logger.warning(
            "Model downloads may fail. Please ensure the directory exists and has write permissions."
        )


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    logger.info("voicebox API shutting down...")
    # Unload models to free memory
    tts.unload_tts_model()
    transcribe.unload_whisper_model()


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="voicebox backend server")
    parser.add_argument(
        "--host",
        type=str,
        default=SETTINGS.host,
        help="Host to bind to (use 0.0.0.0 for remote access)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=SETTINGS.port,
        help="Port to bind to",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(SETTINGS.data_dir) if SETTINGS.data_dir else None,
        help="Data directory for database, profiles, and generated audio",
    )
    args = parser.parse_args()

    # Set data directory if provided
    if args.data_dir:
        config.set_data_dir(args.data_dir)

    # Initialize database after data directory is set
    database.init_db()

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=False,  # Disable reload in production
    )
