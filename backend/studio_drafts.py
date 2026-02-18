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
    StudioDraft as DBStudioDraft,
    StudioDraftLine as DBStudioDraftLine,
    Story as DBStory,
    VoiceProfile as DBVoiceProfile,
)
from .models import (
    EmotionType,
    StoryCharacterMapping,
    StoryLineSpec,
    StudioDraftListItem,
    StoryRenderFromHistoryRequest,
    StudioDraftCreateRequest,
    StudioDraftDetailResponse,
    StudioDraftLineResponse,
    StudioDraftLinesUpdateRequest,
    StudioDraftResponse,
    StudioLimits,
    StudioPreviewResponse,
    StudioRenderFinalResponse,
)
from .settings import load_settings
from .utils.audio import save_audio
from .utils.groq import GroqAPIError, compose_story_lines_with_groq, list_available_groq_models


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
        max_lines=min(40, max(2, int(limits.max_lines))),
        max_chars_per_line=min(1000, max(50, int(limits.max_chars_per_line))),
        preview_seconds=min(10, max(1, int(limits.preview_seconds))),
    )


def _preview_audio_url(draft_id: str, line_id: str) -> str:
    return f"/studio/drafts/{draft_id}/lines/{line_id}/preview/audio"


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
    try:
        composed_lines = compose_story_lines_with_groq(
            settings,
            prompt=data.prompt,
            mode=data.mode,
            language=data.language,
            characters=character_names,
            character_descriptions=character_descriptions,
            target_lines=limits.max_lines,
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
        truncated = len(raw_text) > limits.max_chars_per_line
        text = raw_text[: limits.max_chars_per_line]

        raw_emotion = _normalize_emotion(str(raw.get("emotion", "neutral")))
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
            line.truncated = len(raw_text) > limits.max_chars_per_line
            line.text = raw_text[: limits.max_chars_per_line]
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
        requested_model_size = draft.model_size or settings.default_model_size
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

        preview_dir = config.get_stories_dir() / "studio_previews" / draft.id
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
        model_size=draft.model_size,
        language=draft.language,
        gap_ms=draft.gap_ms,
        continue_on_error=bool(draft.continue_on_error),
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
