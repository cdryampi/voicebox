"""
Centralized runtime settings for backend deployment profiles.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_int(value: Optional[str], default: int, minimum: int = 1) -> int:
    if value is None:
        return default
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _parse_float(value: Optional[str], default: float, minimum: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class BackendSettings:
    api_key: Optional[str]
    allowed_origins: List[str]
    host: str
    port: int
    data_dir: Optional[Path]
    colab_profile: bool
    use_groq_instruct: bool
    groq_api_key: Optional[str]
    groq_model: str
    groq_models: List[str]
    groq_timeout_seconds: int
    default_model_size: str
    default_whisper_model_size: str
    db_pool_size: int
    db_max_overflow: int
    db_pool_timeout_seconds: int
    db_pool_recycle_seconds: int
    db_connect_timeout_seconds: float
    db_use_null_pool: bool


def load_settings() -> BackendSettings:
    # Load .env from project root and current working dir (no override).
    project_root_env = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(project_root_env, override=False)
    load_dotenv(Path.cwd() / ".env", override=False)

    colab_profile = _parse_bool(os.getenv("VOICEBOX_COLAB_PROFILE"), default=False)

    allowed_origins = _parse_csv(os.getenv("VOICEBOX_ALLOWED_ORIGINS"))
    if not allowed_origins:
        if colab_profile:
            # In remote Colab mode prefer explicit origins to avoid CORS issues with credentials.
            allowed_origins = [
                "http://localhost:5173",
                "http://localhost:5174",
                "http://127.0.0.1:5173",
                "http://127.0.0.1:5174",
            ]
        else:
            # Preserve compatibility with current local behavior.
            allowed_origins = ["*"]

    host_default = "0.0.0.0" if colab_profile else "127.0.0.1"
    default_model_size = "0.6B" if colab_profile else "1.7B"
    default_db_pool_size = 20 if colab_profile else 5
    default_db_max_overflow = 40 if colab_profile else 10
    default_db_pool_timeout = 120 if colab_profile else 30
    default_db_pool_recycle = 1800
    default_db_connect_timeout = 60.0 if colab_profile else 30.0
    default_db_use_null_pool = True if colab_profile else False
    default_whisper_model_size = os.getenv("VOICEBOX_DEFAULT_WHISPER_MODEL_SIZE", "base")
    if default_whisper_model_size not in {"base", "small", "medium", "large"}:
        default_whisper_model_size = "base"

    data_dir_env = os.getenv("VOICEBOX_DATA_DIR")
    data_dir = Path(data_dir_env).expanduser() if data_dir_env else None

    groq_models = _parse_csv(os.getenv("VOICEBOX_GROQ_MODELS"))
    if not groq_models:
        groq_models = [
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ]

    groq_model = os.getenv("VOICEBOX_GROQ_MODEL", "llama-3.1-8b-instant")
    if groq_model not in groq_models:
        groq_models = [groq_model, *groq_models]

    return BackendSettings(
        api_key=os.getenv("VOICEBOX_API_KEY"),
        allowed_origins=allowed_origins,
        host=os.getenv("VOICEBOX_HOST", host_default),
        port=int(os.getenv("VOICEBOX_PORT", "17493")),
        data_dir=data_dir,
        colab_profile=colab_profile,
        use_groq_instruct=_parse_bool(os.getenv("VOICEBOX_USE_GROQ_INSTRUCT"), default=False),
        groq_api_key=os.getenv("VOICEBOX_GROQ_API_KEY") or os.getenv("GROQ_API_KEY"),
        groq_model=groq_model,
        groq_models=groq_models,
        groq_timeout_seconds=int(os.getenv("VOICEBOX_GROQ_TIMEOUT_SECONDS", "20")),
        default_model_size=os.getenv("VOICEBOX_DEFAULT_MODEL_SIZE", default_model_size),
        default_whisper_model_size=default_whisper_model_size,
        db_pool_size=_parse_int(
            os.getenv("VOICEBOX_DB_POOL_SIZE"),
            default=default_db_pool_size,
            minimum=1,
        ),
        db_max_overflow=_parse_int(
            os.getenv("VOICEBOX_DB_MAX_OVERFLOW"),
            default=default_db_max_overflow,
            minimum=0,
        ),
        db_pool_timeout_seconds=_parse_int(
            os.getenv("VOICEBOX_DB_POOL_TIMEOUT_SECONDS"),
            default=default_db_pool_timeout,
            minimum=1,
        ),
        db_pool_recycle_seconds=_parse_int(
            os.getenv("VOICEBOX_DB_POOL_RECYCLE_SECONDS"),
            default=default_db_pool_recycle,
            minimum=30,
        ),
        db_connect_timeout_seconds=_parse_float(
            os.getenv("VOICEBOX_DB_CONNECT_TIMEOUT_SECONDS"),
            default=default_db_connect_timeout,
            minimum=1.0,
        ),
        db_use_null_pool=_parse_bool(
            os.getenv("VOICEBOX_DB_USE_NULL_POOL"),
            default=default_db_use_null_pool,
        ),
    )
