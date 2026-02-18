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


def load_settings() -> BackendSettings:
    # Load .env from project root and current working dir (no override).
    project_root_env = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(project_root_env, override=False)
    load_dotenv(Path.cwd() / ".env", override=False)

    colab_profile = _parse_bool(os.getenv("VOICEBOX_COLAB_PROFILE"), default=False)

    allowed_origins = _parse_csv(os.getenv("VOICEBOX_ALLOWED_ORIGINS"))
    if not allowed_origins:
        # Preserve compatibility with current local behavior.
        allowed_origins = ["*"]

    host_default = "0.0.0.0" if colab_profile else "127.0.0.1"
    default_model_size = "0.6B" if colab_profile else "1.7B"

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
    )
