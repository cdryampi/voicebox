from pydantic import ValidationError

from backend.auth import is_request_authorized
from backend.models import (
    CapabilitiesResponse,
    ModelDefaultsUpdateRequest,
    StoryRenderFromHistoryRequest,
)
from backend.settings import BackendSettings
from backend.stories import build_emotion_instruction


def _settings(api_key: str | None) -> BackendSettings:
    return BackendSettings(
        api_key=api_key,
        allowed_origins=["*"],
        host="127.0.0.1",
        port=17493,
        data_dir=None,
        colab_profile=False,
        use_groq_instruct=False,
        groq_api_key=None,
        groq_model="llama-3.1-8b-instant",
        groq_models=["llama-3.1-8b-instant"],
        groq_timeout_seconds=20,
        default_model_size="1.7B",
        default_whisper_model_size="base",
        db_pool_size=5,
        db_max_overflow=10,
        db_pool_timeout_seconds=30,
        db_pool_recycle_seconds=1800,
        db_connect_timeout_seconds=30.0,
        db_use_null_pool=False,
    )


def test_build_emotion_instruction_clamps_intensity() -> None:
    instruction = build_emotion_instruction("happy", 5.0, "Luna")
    assert "happy" not in instruction.lower()  # description is style-based, not raw label
    assert "1.00" in instruction


def test_api_key_auth_behaviour() -> None:
    assert is_request_authorized(_settings(None), None)
    assert is_request_authorized(_settings("abc"), "Bearer abc")
    assert not is_request_authorized(_settings("abc"), "Bearer wrong")
    assert not is_request_authorized(_settings("abc"), None)


def test_story_render_request_validation_for_intensity() -> None:
    payload = {
        "name": "Story",
        "character_mappings": [
            {
                "character_name": "Narrator",
                "profile_id": "profile-1",
                "default_emotion": "neutral",
                "default_emotion_intensity": 0.5,
            }
        ],
        "lines": [
            {
                "source_generation_id": "gen-1",
                "character_name": "Narrator",
                "emotion": "happy",
                "emotion_intensity": 1.5,
            }
        ],
    }

    try:
        StoryRenderFromHistoryRequest.model_validate(payload)
        assert False, "Expected validation to fail"
    except ValidationError as exc:
        assert "emotion_intensity" in str(exc)


def test_capabilities_defaults() -> None:
    caps = CapabilitiesResponse()
    assert caps.studio_batch_delete is True
    assert caps.model_progress_snapshot is True
    assert caps.runtime_defaults is True


def test_model_defaults_payload_validation() -> None:
    payload = ModelDefaultsUpdateRequest(
        default_tts_model_size="0.6B",
        default_whisper_model_size="small",
    )
    assert payload.default_tts_model_size == "0.6B"
