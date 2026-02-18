from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import ModelDefaultsUpdateRequest
from backend.runtime_defaults import get_model_defaults, update_model_defaults
from backend.settings import BackendSettings


def _settings() -> BackendSettings:
    return BackendSettings(
        api_key=None,
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


def test_runtime_defaults_fallback_and_update() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    db = session_local()
    try:
        defaults = get_model_defaults(db, settings=_settings())
        assert defaults.default_tts_model_size == "1.7B"
        assert defaults.default_whisper_model_size == "base"

        saved = update_model_defaults(
            db,
            ModelDefaultsUpdateRequest(
                default_tts_model_size="0.6B",
                default_whisper_model_size="small",
            ),
        )
        assert saved.default_tts_model_size == "0.6B"
        assert saved.default_whisper_model_size == "small"

        loaded = get_model_defaults(db, settings=_settings())
        assert loaded.default_tts_model_size == "0.6B"
        assert loaded.default_whisper_model_size == "small"
    finally:
        db.close()
