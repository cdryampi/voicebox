"""
Studio draft pipeline for novel/roleplay iterative authoring.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from . import config, profiles, stories, tts
from .database import (
    ProfileSample as DBProfileSample,
    StudioDraft as DBStudioDraft,
    StudioDraftLine as DBStudioDraftLine,
    Story as DBStory,
    StoryRenderJob as DBStoryRenderJob,
    VoiceProfile as DBVoiceProfile,
)
from .models import (
    EmotionType,
    StoryCharacterMapping,
    StoryLineSpec,
    StudioDirectorSuggestion,
    StudioDirectorSuggestionsRequest,
    StudioDirectorSuggestionsResponse,
    StudioDraftListItem,
    StoryRenderFromHistoryRequest,
    StudioDraftCreateRequest,
    StudioDraftDetailResponse,
    StudioDraftLineResponse,
    StudioDraftLinesDeleteRequest,
    StudioDraftLinesUpdateRequest,
    StudioDraftResponse,
    StudioLimits,
    StudioPreviewResponse,
    StudioRenderFinalResponse,
)
from .settings import load_settings
from .utils.audio import save_audio
from .utils.groq import (
    GroqAPIError,
    compose_story_lines_with_groq,
    compose_studio_director_suggestions_with_groq,
    list_available_groq_models,
)
from .utils.tasks import get_task_manager


_ALLOWED_EMOTIONS: set[str] = {
    "neutral",
    "happy",
    "sad",
    "angry",
    "fearful",
    "surprised",
    "calm",
}

_EMOTION_GUIDANCE = {
    "neutral": "steady, clear, and natural",
    "happy": "warm, upbeat, and smiling",
    "sad": "soft, reflective, and emotionally heavy",
    "angry": "firm, tense, and energetic",
    "fearful": "nervous, shaky, and cautious",
    "surprised": "reactive, bright, and sudden",
    "calm": "slow, grounded, and soothing",
}

_SUPPORTED_LANGUAGES = {"zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"}


def _has_profile_samples(profile_id: str, db: Session) -> bool:
    return (
        db.query(DBProfileSample)
        .filter(DBProfileSample.profile_id == profile_id)
        .count()
        > 0
    )


def _create_failed_preflight_job(
    *,
    story_id: str,
    total_lines: int,
    message: str,
    code: str,
    db: Session,
) -> DBStoryRenderJob:
    job = DBStoryRenderJob(
        id=str(uuid.uuid4()),
        story_id=story_id,
        status="failed",
        total_lines=total_lines,
        processed_lines=0,
        error_summary=message[:1000],
        failure_phase="preflight",
        failure_code=code,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    return job


def _run_studio_render_preflight(
    draft: DBStudioDraft,
    lines: List[DBStudioDraftLine],
    character_mappings: List[StoryCharacterMapping],
    db: Session,
) -> tuple[bool, Optional[str], Optional[str]]:
    active_model_op = get_task_manager().get_model_operation_state()
    if active_model_op is not None:
        return (
            False,
            f"Model operation in progress: {active_model_op.kind} {active_model_op.model_name}",
            "MODEL_OPERATION_IN_PROGRESS",
        )

    if not lines:
        return False, "Draft has no lines to render", "STORY_RENDER_PREFLIGHT_NO_LINES"

    limits = _parse_limits_from_db(draft.limits_json)
    max_chars = limits.max_chars_per_line
    for idx, line in enumerate(lines):
        if not (line.text or "").strip():
            return (
                False,
                f"Line #{idx + 1} is empty",
                "STORY_RENDER_PREFLIGHT_EMPTY_LINE",
            )
        if len(line.text) > max_chars:
            return (
                False,
                f"Line #{idx + 1} exceeds max chars ({len(line.text)} > {max_chars})",
                "STORY_RENDER_PREFLIGHT_LINE_TOO_LONG",
            )

    settings = load_settings()
    model_size = "1.7B" if settings.colab_profile else (draft.model_size or settings.default_model_size)
    if model_size not in {"0.6B", "1.7B"}:
        return False, f"Unsupported model size: {model_size}", "STORY_RENDER_PREFLIGHT_MODEL_INVALID"

    tts_model = tts.get_tts_model()
    loaded_size = getattr(tts_model, "_current_model_size", None) or getattr(tts_model, "model_size", None)
    settings = load_settings()
    if (
        settings.colab_profile
        and model_size == "1.7B"
        and loaded_size
        and loaded_size != "1.7B"
    ):
        return (
            False,
            "Switching from Qwen TTS 0.6B to 1.7B in live Colab session requires backend restart",
            "MODEL_SWITCH_REQUIRES_RESTART",
        )

    mapping_profiles = {mapping.profile_id for mapping in character_mappings}
    line_profiles = {line.profile_id for line in lines}
    profile_ids = mapping_profiles | line_profiles
    for profile_id in profile_ids:
        profile = db.query(DBVoiceProfile).filter_by(id=profile_id).first()
        if not profile:
            return (
                False,
                f"Profile not found for render preflight: {profile_id}",
                "PROFILE_NOT_FOUND",
            )
        if not _has_profile_samples(profile_id, db):
            return (
                False,
                f"Profile has no reference samples: {profile.name}",
                "PROFILE_SAMPLE_MISSING",
            )

    return True, None, None


def _get_stories_output_dir() -> Path:
    """Resolve stories directory even if running with an older config module."""
    get_stories_dir = getattr(config, "get_stories_dir", None)
    if callable(get_stories_dir):
        try:
            path = Path(get_stories_dir())
            path.mkdir(parents=True, exist_ok=True)
            return path
        except Exception:
            pass

    get_data_dir = getattr(config, "get_data_dir", None)
    base_dir = Path(get_data_dir()) if callable(get_data_dir) else Path("data")
    path = base_dir / "stories"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_emotion(emotion: Optional[str]) -> EmotionType:
    value = (emotion or "neutral").strip().lower()
    if value in _ALLOWED_EMOTIONS:
        return value  # type: ignore[return-value]
    return "neutral"


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _resolve_limits(limits: Optional[StudioLimits]) -> StudioLimits:
    if not limits:
        return StudioLimits()
    # Re-validate and clamp against hard safe bounds.
    return StudioLimits(
        max_lines=min(80, max(1, int(limits.max_lines))),
        max_chars_per_line=min(1500, max(20, int(limits.max_chars_per_line))),
        preview_seconds=min(15, max(1, int(limits.preview_seconds))),
    )


def _preview_audio_url(draft_id: str, line_id: str) -> str:
    return f"/studio/drafts/{draft_id}/lines/{line_id}/preview/audio"


def _truncate_line_text(raw_text: str, max_chars: int) -> tuple[str, bool]:
    cleaned = raw_text.strip()
    if len(cleaned) <= max_chars:
        return cleaned, False

    window = cleaned[: max_chars + 1]
    preferred_breaks = [
        window.rfind(". "),
        window.rfind("? "),
        window.rfind("! "),
        window.rfind("; "),
        window.rfind(": "),
        window.rfind(", "),
        window.rfind(" "),
    ]
    cut_at = max(preferred_breaks)
    if cut_at < int(max_chars * 0.6):
        cut_at = max_chars
    else:
        cut_at += 1

    truncated = window[:cut_at].rstrip(" ,;:-")
    if not truncated:
        truncated = cleaned[:max_chars].rstrip()
    return truncated, True


def _parse_limits_from_db(raw_json: str) -> StudioLimits:
    try:
        parsed = json.loads(raw_json)
        if isinstance(parsed, dict):
            return _resolve_limits(StudioLimits.model_validate(parsed))
    except Exception:
        pass
    return StudioLimits()


def _parse_character_mappings(raw_json: str) -> List[StoryCharacterMapping]:
    mappings: List[StoryCharacterMapping] = []
    try:
        parsed = json.loads(raw_json)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    mappings.append(StoryCharacterMapping.model_validate(item))
    except Exception:
        pass
    return mappings


def _line_to_response(draft_id: str, line: DBStudioDraftLine) -> StudioDraftLineResponse:
    preview_url = None
    if line.preview_audio_path:
        preview_path = Path(line.preview_audio_path)
        if preview_path.exists():
            preview_url = _preview_audio_url(draft_id, line.id)

    return StudioDraftLineResponse(
        id=line.id,
        order_index=line.order_index,
        character_name=line.character_name,
        profile_id=line.profile_id,
        text=line.text,
        emotion=_normalize_emotion(line.emotion),
        emotion_intensity=_clamp01(line.emotion_intensity),
        truncated=bool(line.truncated),
        preview_status=line.preview_status,
        preview_audio_url=preview_url,
        preview_duration=line.preview_duration,
        preview_error=line.preview_error,
    )


def _draft_to_detail_response(draft: DBStudioDraft, lines: List[DBStudioDraftLine]) -> StudioDraftDetailResponse:
    limits = _parse_limits_from_db(draft.limits_json)
    character_mappings = _parse_character_mappings(draft.character_mappings_json)
    mode = draft.mode if draft.mode in {"novela", "roleplay"} else "roleplay"
    return StudioDraftDetailResponse(
        draft_id=draft.id,
        story_id=draft.story_id,
        name=draft.name,
        description=draft.description,
        prompt=draft.prompt,
        mode=mode,  # type: ignore[arg-type]
        language=draft.language,
        llm_model=draft.llm_model,
        model_size=draft.model_size,
        gap_ms=draft.gap_ms,
        continue_on_error=bool(draft.continue_on_error),
        status=draft.status,
        limits_applied=limits,
        character_mappings=character_mappings,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        lines=[_line_to_response(draft.id, line) for line in lines],
    )


def _sanitize_outline(
    raw_outline: object,
    *,
    fallback_prompt: str,
    fallback_description: Optional[str],
) -> List[str]:
    outline: List[str] = []
    if isinstance(raw_outline, list):
        for item in raw_outline:
            text = str(item).strip()
            if text:
                outline.append(text[:180])
    elif isinstance(raw_outline, str):
        for chunk in raw_outline.split("\n"):
            text = chunk.strip("-* ").strip()
            if text:
                outline.append(text[:180])

    if len(outline) >= 2:
        return outline[:4]

    fallback_source = fallback_description or fallback_prompt
    fragments = [
        part.strip()[:180]
        for part in fallback_source.split(".")
        if part.strip()
    ]
    if len(fragments) >= 2:
        return fragments[:4]

    short_prompt = fallback_prompt.strip()[:180]
    if short_prompt:
        return [short_prompt, "Emotional arc across short cards"]
    return ["Short story arc", "Emotion-focused card sequence"]


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _default_character_mappings(
    *,
    profile_id: str,
    character_description: str,
    protagonist_name: str = "Protagonista",
    narrator_name: str = "Narrador",
    protagonist_description: Optional[str] = None,
    narrator_description: Optional[str] = None,
) -> List[StoryCharacterMapping]:
    protagonist_label = protagonist_name.strip()[:100] or "Protagonista"
    narrator_label = narrator_name.strip()[:100] or "Narrador"
    if narrator_label == protagonist_label:
        narrator_label = "Narrador"

    protagonist_desc = (
        (protagonist_description or "").strip() or character_description.strip()
    )[:500]
    narrator_desc = (
        (narrator_description or "").strip()
        or "Narrador observador y coherente, enfocado en ritmo, contexto y continuidad emocional."
    )[:500]

    emotions: List[EmotionType] = [
        "neutral",
        "happy",
        "sad",
        "angry",
        "fearful",
        "surprised",
        "calm",
    ]
    return [
        StoryCharacterMapping(
            character_name=protagonist_label,
            profile_id=profile_id,
            description=protagonist_desc,
            emotion_palette=emotions,
            default_emotion="neutral",
            default_emotion_intensity=0.6,
            default_track=0,
        ),
        StoryCharacterMapping(
            character_name=narrator_label,
            profile_id=profile_id,
            description=narrator_desc,
            emotion_palette=emotions,
            default_emotion="calm",
            default_emotion_intensity=0.4,
            default_track=1,
        ),
    ]


async def generate_studio_director_suggestions(
    data: StudioDirectorSuggestionsRequest,
    db: Session,
) -> StudioDirectorSuggestionsResponse:
    settings = load_settings()
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not configured. Add it to .env or environment variables.")

    description = data.character_description.strip()
    if not description:
        raise ValueError("character_description is required")

    llm_model = data.llm_model or settings.groq_model
    allowed_models = list_available_groq_models(settings)
    if llm_model not in allowed_models:
        raise ValueError(f"Unknown llm_model '{llm_model}'. Use one of /llm/groq/models.")

    first_profile = (
        db.query(DBVoiceProfile)
        .order_by(DBVoiceProfile.created_at.asc())
        .first()
    )
    if not first_profile:
        raise ValueError("need at least one voice profile")

    target_cards = min(20, max(4, int(data.target_cards)))
    try:
        raw_suggestions = compose_studio_director_suggestions_with_groq(
            settings,
            character_description=description,
            story_name_hint=data.story_name_hint,
            mode=data.mode,
            language=data.language,
            target_cards=target_cards,
            model=llm_model,
        )
    except GroqAPIError as e:
        raise ValueError(f"Groq failed to generate story director suggestions: {e}") from e

    suggestions: List[StudioDirectorSuggestion] = []
    for idx, raw in enumerate(raw_suggestions):
        if len(suggestions) >= 4:
            break
        if not isinstance(raw, dict):
            continue

        title = str(raw.get("title", "")).strip()[:100]
        prompt = str(raw.get("prompt", "")).strip()[:4000]
        description_text = str(raw.get("description", "")).strip()[:500] or None
        if not title:
            title = f"Idea {idx + 1}"
        if not prompt:
            continue

        raw_mode = str(raw.get("mode", data.mode)).strip().lower()
        mode = raw_mode if raw_mode in {"novela", "roleplay"} else data.mode

        raw_language = str(raw.get("language", data.language)).strip().lower()
        language = raw_language if raw_language in _SUPPORTED_LANGUAGES else data.language

        raw_model_size = str(raw.get("model_size", data.model_size or "")).strip()
        model_size = raw_model_size if raw_model_size in {"0.6B", "1.7B"} else data.model_size

        raw_limits = raw.get("limits") if isinstance(raw.get("limits"), dict) else {}
        limits = StudioLimits(
            max_lines=min(80, max(1, _safe_int(raw_limits.get("max_lines"), target_cards))),
            max_chars_per_line=min(
                1500, max(20, _safe_int(raw_limits.get("max_chars_per_line"), 300))
            ),
            preview_seconds=min(15, max(1, _safe_int(raw_limits.get("preview_seconds"), 5))),
        )

        outline = _sanitize_outline(
            raw.get("preview_outline"),
            fallback_prompt=prompt,
            fallback_description=description_text,
        )
        if len(outline) < 2:
            continue

        character_mappings = _default_character_mappings(
            profile_id=first_profile.id,
            character_description=description,
            protagonist_name=str(raw.get("protagonist_name", "Protagonista")),
            narrator_name=str(raw.get("narrator_name", "Narrador")),
            protagonist_description=str(raw.get("protagonist_description", "")) or None,
            narrator_description=str(raw.get("narrator_description", "")) or None,
        )

        suggestions.append(
            StudioDirectorSuggestion(
                title=title,
                description=description_text,
                prompt=prompt,
                mode=mode,  # type: ignore[arg-type]
                language=language,
                model_size=model_size,
                limits=limits,
                character_mappings=character_mappings,
                preview_outline=outline[:4],
            )
        )

    if len(suggestions) < 4:
        raise ValueError("Groq did not return 4 valid suggestions. Try a different model or prompt.")

    return StudioDirectorSuggestionsResponse(suggestions=suggestions[:4])


async def create_studio_draft(
    data: StudioDraftCreateRequest,
    db: Session,
) -> StudioDraftResponse:
    settings = load_settings()
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not configured. Add it to .env or environment variables.")
    if not data.character_mappings:
        raise ValueError("At least one character mapping is required.")
    if len(data.character_mappings) > 10:
        raise ValueError("Character mappings must be between 1 and 10.")

    llm_model = data.llm_model or settings.groq_model
    allowed_models = list_available_groq_models(settings)
    if llm_model not in allowed_models:
        raise ValueError(f"Unknown llm_model '{llm_model}'. Use one of /llm/groq/models.")

    limits = _resolve_limits(data.limits)

    character_map: Dict[str, StoryCharacterMapping] = {}
    normalized_palettes: Dict[str, List[EmotionType]] = {}
    for mapping in data.character_mappings:
        if not (mapping.description or "").strip():
            raise ValueError(f"Character description is required for {mapping.character_name}")
        if mapping.character_name in character_map:
            raise ValueError(f"Duplicate character mapping: {mapping.character_name}")
        profile = db.query(DBVoiceProfile).filter_by(id=mapping.profile_id).first()
        if not profile:
            raise ValueError(
                f"Profile {mapping.profile_id} for character {mapping.character_name} not found"
            )
        palette = list(dict.fromkeys(mapping.emotion_palette or [mapping.default_emotion]))
        if mapping.default_emotion not in palette:
            palette.append(mapping.default_emotion)
        normalized_palettes[mapping.character_name] = [
            _normalize_emotion(emotion) for emotion in palette
        ]
        character_map[mapping.character_name] = mapping

    story: Optional[DBStory] = None
    if data.story_id:
        story = db.query(DBStory).filter_by(id=data.story_id).first()
        if not story:
            raise ValueError(f"Story not found: {data.story_id}")
    else:
        story = DBStory(
            id=str(uuid.uuid4()),
            name=data.name,
            description=data.description,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(story)
        db.flush()

    character_names = [m.character_name for m in data.character_mappings]
    character_descriptions = {
        m.character_name: (m.description or "").strip()
        for m in data.character_mappings
    }
    character_emotion_palettes = {
        m.character_name: normalized_palettes.get(m.character_name, [m.default_emotion])
        for m in data.character_mappings
    }
    try:
        composed_lines = compose_story_lines_with_groq(
            settings,
            prompt=data.prompt,
            mode=data.mode,
            language=data.language,
            characters=character_names,
            character_descriptions=character_descriptions,
            character_emotion_palettes=character_emotion_palettes,
            target_lines=limits.max_lines,
            max_chars_per_line=limits.max_chars_per_line,
            model=llm_model,
        )
    except GroqAPIError as e:
        raise ValueError(f"Groq failed to compose story lines: {e}") from e

    draft = DBStudioDraft(
        id=str(uuid.uuid4()),
        story_id=story.id,
        name=data.name,
        description=data.description,
        prompt=data.prompt,
        mode=data.mode,
        language=data.language,
        llm_model=llm_model,
        model_size=data.model_size,
        gap_ms=data.gap_ms,
        continue_on_error=data.continue_on_error,
        status="draft",
        limits_json=json.dumps(limits.model_dump()),
        character_mappings_json=json.dumps([m.model_dump() for m in data.character_mappings]),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(draft)
    db.flush()

    first_mapping = data.character_mappings[0]
    created = 0
    for raw in composed_lines:
        if created >= limits.max_lines:
            break
        if not isinstance(raw, dict):
            continue

        raw_character = str(raw.get("character_name", "")).strip()
        mapping = character_map.get(raw_character, first_mapping)
        character_name = mapping.character_name

        raw_text = str(raw.get("text", "")).strip()
        if not raw_text:
            continue
        text, truncated = _truncate_line_text(raw_text, limits.max_chars_per_line)

        raw_emotion = _normalize_emotion(str(raw.get("emotion", "neutral")))
        allowed_emotions = set(
            normalized_palettes.get(mapping.character_name, [mapping.default_emotion])
        )
        if raw_emotion not in allowed_emotions:
            raw_emotion = mapping.default_emotion
        raw_intensity = raw.get("emotion_intensity", mapping.default_emotion_intensity)
        try:
            intensity = _clamp01(float(raw_intensity))
        except (TypeError, ValueError):
            intensity = mapping.default_emotion_intensity

        db.add(
            DBStudioDraftLine(
                id=str(uuid.uuid4()),
                draft_id=draft.id,
                order_index=created,
                character_name=character_name,
                profile_id=mapping.profile_id,
                text=text,
                emotion=raw_emotion,
                emotion_intensity=intensity,
                truncated=truncated,
                preview_audio_path=None,
                preview_duration=None,
                preview_status="idle",
                preview_error=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        created += 1

    if created == 0:
        raise ValueError("Groq output did not include valid lines to create draft.")

    db.commit()

    return StudioDraftResponse(
        draft_id=draft.id,
        story_id=draft.story_id,
        line_count=created,
        status=draft.status,
        limits_applied=limits,
    )


async def list_studio_drafts(
    db: Session,
    story_id: Optional[str] = None,
) -> List[StudioDraftListItem]:
    query = db.query(DBStudioDraft)
    if story_id:
        query = query.filter_by(story_id=story_id)
    drafts = query.order_by(DBStudioDraft.updated_at.desc()).all()

    items: List[StudioDraftListItem] = []
    for draft in drafts:
        line_count = (
            db.query(DBStudioDraftLine)
            .filter_by(draft_id=draft.id)
            .count()
        )
        items.append(
            StudioDraftListItem(
                draft_id=draft.id,
                story_id=draft.story_id,
                name=draft.name,
                status=draft.status,
                line_count=line_count,
                created_at=draft.created_at,
                updated_at=draft.updated_at,
            )
        )

    return items


async def get_studio_draft(draft_id: str, db: Session) -> Optional[StudioDraftDetailResponse]:
    draft = db.query(DBStudioDraft).filter_by(id=draft_id).first()
    if not draft:
        return None
    lines = (
        db.query(DBStudioDraftLine)
        .filter_by(draft_id=draft.id)
        .order_by(DBStudioDraftLine.order_index.asc())
        .all()
    )
    return _draft_to_detail_response(draft, lines)


async def update_studio_draft_lines(
    draft_id: str,
    data: StudioDraftLinesUpdateRequest,
    db: Session,
) -> Optional[StudioDraftDetailResponse]:
    draft = db.query(DBStudioDraft).filter_by(id=draft_id).first()
    if not draft:
        return None

    limits = _parse_limits_from_db(draft.limits_json)
    lines = db.query(DBStudioDraftLine).filter_by(draft_id=draft_id).all()
    lines_by_id = {line.id: line for line in lines}

    mappings = _parse_character_mappings(draft.character_mappings_json)
    character_profile: Dict[str, str] = {m.character_name: m.profile_id for m in mappings}
    for line in lines:
        character_profile.setdefault(line.character_name, line.profile_id)

    for update in data.lines:
        line = lines_by_id.get(update.line_id)
        if not line:
            raise ValueError(f"Draft line not found: {update.line_id}")

        changed = False
        if update.character_name is not None:
            character_name = update.character_name.strip()
            if not character_name:
                raise ValueError("character_name cannot be empty")
            line.character_name = character_name
            if character_name in character_profile:
                line.profile_id = character_profile[character_name]
            changed = True

        if update.text is not None:
            raw_text = update.text.strip()
            if not raw_text:
                raise ValueError("text cannot be empty")
            line.text, line.truncated = _truncate_line_text(raw_text, limits.max_chars_per_line)
            changed = True

        if update.emotion is not None:
            line.emotion = _normalize_emotion(update.emotion)
            changed = True

        if update.emotion_intensity is not None:
            line.emotion_intensity = _clamp01(update.emotion_intensity)
            changed = True

        if update.order_index is not None:
            line.order_index = update.order_index
            changed = True

        if changed:
            line.preview_audio_path = None
            line.preview_duration = None
            line.preview_status = "idle"
            line.preview_error = None
            line.updated_at = datetime.utcnow()

    draft.updated_at = datetime.utcnow()
    db.commit()
    return await get_studio_draft(draft_id, db)


async def delete_studio_draft_lines(
    draft_id: str,
    data: StudioDraftLinesDeleteRequest,
    db: Session,
) -> Optional[StudioDraftDetailResponse]:
    draft = db.query(DBStudioDraft).filter_by(id=draft_id).first()
    if not draft:
        return None

    lines = (
        db.query(DBStudioDraftLine)
        .filter_by(draft_id=draft_id)
        .order_by(DBStudioDraftLine.order_index.asc())
        .all()
    )
    line_map = {line.id: line for line in lines}
    line_ids = {line_id.strip() for line_id in data.line_ids if line_id.strip()}
    if not line_ids:
        raise ValueError("No line_ids provided")

    missing = [line_id for line_id in line_ids if line_id not in line_map]
    if missing:
        raise ValueError(f"Draft line not found: {missing[0]}")

    for line in lines:
        if line.id in line_ids:
            db.delete(line)

    remaining = (
        db.query(DBStudioDraftLine)
        .filter_by(draft_id=draft_id)
        .order_by(DBStudioDraftLine.order_index.asc())
        .all()
    )
    for idx, line in enumerate(remaining):
        if line.order_index != idx:
            line.order_index = idx
            line.updated_at = datetime.utcnow()

    draft.updated_at = datetime.utcnow()
    db.commit()
    return await get_studio_draft(draft_id, db)


def _build_emotion_instruction(emotion: str, intensity: float, character_name: str) -> str:
    normalized_emotion = emotion if emotion in _EMOTION_GUIDANCE else "neutral"
    normalized_intensity = _clamp01(intensity)
    guidance = _EMOTION_GUIDANCE[normalized_emotion]
    return (
        f"{character_name} speaks in a {guidance} style "
        f"with emotional intensity {normalized_intensity:.2f}."
    )


async def generate_studio_line_preview(
    draft_id: str,
    line_id: str,
    db: Session,
) -> StudioPreviewResponse:
    draft = db.query(DBStudioDraft).filter_by(id=draft_id).first()
    if not draft:
        raise ValueError("Studio draft not found")

    line = db.query(DBStudioDraftLine).filter_by(id=line_id, draft_id=draft_id).first()
    if not line:
        raise ValueError("Draft line not found")

    limits = _parse_limits_from_db(draft.limits_json)
    settings = load_settings()

    line.preview_status = "generating"
    line.preview_error = None
    line.updated_at = datetime.utcnow()
    db.commit()

    try:
        tts_model = tts.get_tts_model()
        requested_model_size = "1.7B" if settings.colab_profile else (draft.model_size or settings.default_model_size)
        await tts_model.load_model_async(requested_model_size)

        voice_prompt = await profiles.create_voice_prompt_for_profile(line.profile_id, db)
        instruct = _build_emotion_instruction(line.emotion, line.emotion_intensity, line.character_name)
        audio, sample_rate = await tts_model.generate(
            text=line.text,
            voice_prompt=voice_prompt,
            language=draft.language,
            instruct=instruct,
        )

        max_samples = int(limits.preview_seconds * sample_rate)
        if max_samples > 0 and len(audio) > max_samples:
            audio = audio[:max_samples]

        preview_duration = len(audio) / sample_rate if sample_rate > 0 else 0.0

        preview_dir = _get_stories_output_dir() / "studio_previews" / draft.id
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / f"{line.id}.wav"
        save_audio(audio, str(preview_path), sample_rate)

        line.preview_audio_path = str(preview_path)
        line.preview_duration = preview_duration
        line.preview_status = "ready"
        line.preview_error = None
        line.updated_at = datetime.utcnow()
        draft.updated_at = datetime.utcnow()
        db.commit()

        return StudioPreviewResponse(
            line_id=line.id,
            status=line.preview_status,
            preview_audio_url=_preview_audio_url(draft.id, line.id),
            duration=preview_duration,
            error=None,
        )
    except Exception as e:
        line.preview_status = "error"
        line.preview_error = str(e)[:1000]
        line.updated_at = datetime.utcnow()
        draft.updated_at = datetime.utcnow()
        db.commit()
        raise ValueError(f"Preview generation failed: {e}") from e


async def get_studio_line_preview_audio_path(
    draft_id: str,
    line_id: str,
    db: Session,
) -> Optional[str]:
    line = db.query(DBStudioDraftLine).filter_by(id=line_id, draft_id=draft_id).first()
    if not line or not line.preview_audio_path:
        return None
    path = Path(line.preview_audio_path)
    if not path.exists():
        return None
    return str(path)


async def render_studio_draft_final(
    draft_id: str,
    db: Session,
) -> Optional[StudioRenderFinalResponse]:
    draft = db.query(DBStudioDraft).filter_by(id=draft_id).first()
    if not draft:
        return None

    lines = (
        db.query(DBStudioDraftLine)
        .filter_by(draft_id=draft_id)
        .order_by(DBStudioDraftLine.order_index.asc())
        .all()
    )
    if not lines:
        raise ValueError("Draft has no lines to render")

    character_mappings = _parse_character_mappings(draft.character_mappings_json)
    if not character_mappings:
        # Fallback mapping inferred from current draft lines.
        seen: Dict[str, str] = {}
        for line in lines:
            if line.character_name not in seen:
                seen[line.character_name] = line.profile_id
        character_mappings = [
            StoryCharacterMapping(character_name=name, profile_id=profile_id)
            for name, profile_id in seen.items()
        ]

    preflight_ok, preflight_message, preflight_code = _run_studio_render_preflight(
        draft=draft,
        lines=lines,
        character_mappings=character_mappings,
        db=db,
    )
    if not preflight_ok:
        failed_job = _create_failed_preflight_job(
            story_id=draft.story_id,
            total_lines=len(lines),
            message=preflight_message or "Story render preflight failed",
            code=preflight_code or "STORY_RENDER_PREFLIGHT_FAILED",
            db=db,
        )
        get_task_manager().complete_story_render(
            failed_job.id,
            status="failed",
            error=failed_job.error_summary,
            error_code=failed_job.failure_code,
        )
        draft.status = "render_failed"
        draft.updated_at = datetime.utcnow()
        db.commit()
        return StudioRenderFinalResponse(
            draft_id=draft.id,
            job_id=failed_job.id,
            story_id=failed_job.story_id,
            status=failed_job.status,
            total_lines=failed_job.total_lines,
        )

    line_specs: List[StoryLineSpec] = []
    for line in lines:
        line_specs.append(
            StoryLineSpec(
                source_generation_id=f"virtual:{uuid.uuid4()}",
                character_name=line.character_name,
                text_override=line.text,
                emotion=_normalize_emotion(line.emotion),
                emotion_intensity=_clamp01(line.emotion_intensity),
                track=None,
                start_time_ms=None,
            )
        )

    render_request = StoryRenderFromHistoryRequest(
        story_id=draft.story_id,
        name=draft.name,
        description=draft.description,
        model_size="1.7B" if load_settings().colab_profile else draft.model_size,
        language=draft.language,
        gap_ms=draft.gap_ms,
        continue_on_error=False,
        replace_existing_items=True,
        character_mappings=character_mappings,
        lines=line_specs,
    )
    job = await stories.create_story_render_from_history(render_request, db)

    draft.status = "render_queued"
    draft.updated_at = datetime.utcnow()
    db.commit()

    return StudioRenderFinalResponse(
        draft_id=draft.id,
        job_id=job.job_id,
        story_id=job.story_id,
        status=job.status,
        total_lines=job.total_lines,
    )
