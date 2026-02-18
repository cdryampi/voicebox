"""
Runtime model default persistence helpers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from .database import RuntimeSetting as DBRuntimeSetting
from .models import ModelDefaultsResponse, ModelDefaultsUpdateRequest, RuntimeModelsResponse
from .settings import BackendSettings, load_settings
from . import tts, transcribe

_KEY_DEFAULT_TTS_MODEL_SIZE = "default_tts_model_size"
_KEY_DEFAULT_WHISPER_MODEL_SIZE = "default_whisper_model_size"


def _get_setting_value(db: Session, key: str) -> Optional[str]:
    row = db.query(DBRuntimeSetting).filter_by(key=key).first()
    if not row:
        return None
    return row.value


def _upsert_setting_value(db: Session, key: str, value: str) -> None:
    row = db.query(DBRuntimeSetting).filter_by(key=key).first()
    if row:
        row.value = value
        row.updated_at = datetime.utcnow()
        return
    db.add(
        DBRuntimeSetting(
            key=key,
            value=value,
            updated_at=datetime.utcnow(),
        )
    )


def get_model_defaults(db: Session, settings: Optional[BackendSettings] = None) -> ModelDefaultsResponse:
    cfg = settings or load_settings()
    tts_default = _get_setting_value(db, _KEY_DEFAULT_TTS_MODEL_SIZE) or cfg.default_model_size
    whisper_default = (
        _get_setting_value(db, _KEY_DEFAULT_WHISPER_MODEL_SIZE) or cfg.default_whisper_model_size
    )

    # Guard against stale/invalid persisted values.
    if tts_default not in {"1.7B", "0.6B"}:
        tts_default = cfg.default_model_size if cfg.default_model_size in {"1.7B", "0.6B"} else "1.7B"
    if whisper_default not in {"base", "small", "medium", "large"}:
        whisper_default = (
            cfg.default_whisper_model_size
            if cfg.default_whisper_model_size in {"base", "small", "medium", "large"}
            else "base"
        )

    return ModelDefaultsResponse(
        default_tts_model_size=tts_default,  # type: ignore[arg-type]
        default_whisper_model_size=whisper_default,  # type: ignore[arg-type]
    )


def update_model_defaults(
    db: Session,
    data: ModelDefaultsUpdateRequest,
) -> ModelDefaultsResponse:
    _upsert_setting_value(db, _KEY_DEFAULT_TTS_MODEL_SIZE, data.default_tts_model_size)
    _upsert_setting_value(db, _KEY_DEFAULT_WHISPER_MODEL_SIZE, data.default_whisper_model_size)
    db.commit()
    return get_model_defaults(db)


def get_runtime_models(db: Session, settings: Optional[BackendSettings] = None) -> RuntimeModelsResponse:
    defaults = get_model_defaults(db, settings=settings)

    tts_backend = tts.get_tts_model()
    tts_size = getattr(tts_backend, "model_size", None) or getattr(tts_backend, "_current_model_size", None)
    if tts_size not in {"1.7B", "0.6B"}:
        tts_size = None

    whisper_backend = transcribe.get_whisper_model()
    whisper_size = getattr(whisper_backend, "model_size", None)
    if whisper_size not in {"base", "small", "medium", "large"}:
        whisper_size = None

    return RuntimeModelsResponse(
        tts_loaded_model_size=tts_size,  # type: ignore[arg-type]
        whisper_loaded_model_size=whisper_size,  # type: ignore[arg-type]
        defaults=defaults,
    )
