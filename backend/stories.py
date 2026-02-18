"""
Story management module.
"""

from typing import List, Optional, Dict
from datetime import datetime
import uuid
import tempfile
from pathlib import Path
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import ValidationError

from .models import (
    StoryCreate,
    StoryResponse,
    StoryDetailResponse,
    StoryItemDetail,
    StoryItemCreate,
    StoryItemBatchUpdate,
    StoryItemMove,
    StoryItemTrim,
    StoryItemSplit,
    StoryRenderFromHistoryRequest,
    StoryLineSpec,
    StoryRenderJobResponse,
    StoryRenderStatusResponse,
    StoryRenderLineStatus,
    StoryComposeWithGroqRequest,
    EmotionType,
)
from .database import (
    Story as DBStory,
    StoryItem as DBStoryItem,
    Generation as DBGeneration,
    VoiceProfile as DBVoiceProfile,
    StoryRenderJob as DBStoryRenderJob,
    StoryScriptLine as DBStoryScriptLine,
)
from . import history, profiles, tts, config, database as db_module
from .settings import load_settings
from .utils.audio import load_audio, save_audio
from .utils.tasks import get_task_manager
from .utils.groq import (
    GroqAPIError,
    maybe_generate_emotion_instruction_with_groq,
    compose_story_lines_with_groq,
    list_available_groq_models,
)
import numpy as np


def _story_render_error_code(error: Exception) -> str:
    message = str(error).lower()
    if "profile" in message and "not found" in message:
        return "PROFILE_NOT_FOUND"
    if "sample" in message and "not found" in message:
        return "PROFILE_SAMPLE_MISSING"
    if "cuda" in message:
        return "STORY_RENDER_CUDA_ERROR"
    if "model" in message and "download" in message:
        return "MODEL_DOWNLOADING"
    return "STORY_RENDER_LINE_FAILED"
	
	
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


async def create_story(
    data: StoryCreate,
    db: Session,
) -> StoryResponse:
    """
    Create a new story.

    Args:
        data: Story creation data
        db: Database session

    Returns:
        Created story
    """
    db_story = DBStory(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(db_story)
    db.commit()
    db.refresh(db_story)

    # Get item count
    item_count = db.query(func.count(DBStoryItem.id)).filter(
        DBStoryItem.story_id == db_story.id
    ).scalar()

    response = StoryResponse.model_validate(db_story)
    response.item_count = item_count
    return response


async def list_stories(
    db: Session,
) -> List[StoryResponse]:
    """
    List all stories.

    Args:
        db: Database session

    Returns:
        List of stories with item counts
    """
    stories = db.query(DBStory).order_by(DBStory.updated_at.desc()).all()
    
    result = []
    for story in stories:
        item_count = db.query(func.count(DBStoryItem.id)).filter(
            DBStoryItem.story_id == story.id
        ).scalar()
        
        response = StoryResponse.model_validate(story)
        response.item_count = item_count
        result.append(response)
    
    return result


async def get_story(
    story_id: str,
    db: Session,
) -> Optional[StoryDetailResponse]:
    """
    Get a story with all its items.

    Args:
        story_id: Story ID
        db: Database session

    Returns:
        Story with items or None if not found
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    # Get all items ordered by start_time_ms
    items = db.query(
        DBStoryItem,
        DBGeneration,
        DBVoiceProfile.name.label('profile_name')
    ).join(
        DBGeneration,
        DBStoryItem.generation_id == DBGeneration.id
    ).join(
        DBVoiceProfile,
        DBGeneration.profile_id == DBVoiceProfile.id
    ).filter(
        DBStoryItem.story_id == story_id
    ).order_by(DBStoryItem.start_time_ms).all()

    # Build item details
    item_details = []
    for item, generation, profile_name in items:
        item_detail = StoryItemDetail(
            id=item.id,
            story_id=item.story_id,
            generation_id=item.generation_id,
            start_time_ms=item.start_time_ms,
            track=item.track,
            trim_start_ms=getattr(item, 'trim_start_ms', 0),
            trim_end_ms=getattr(item, 'trim_end_ms', 0),
            created_at=item.created_at,
            profile_id=generation.profile_id,
            profile_name=profile_name,
            text=generation.text,
            language=generation.language,
            audio_path=generation.audio_path,
            duration=generation.duration,
            seed=generation.seed,
            instruct=generation.instruct,
            generation_created_at=generation.created_at,
        )
        item_details.append(item_detail)

    response = StoryDetailResponse.model_validate(story)
    response.items = item_details
    return response


async def update_story(
    story_id: str,
    data: StoryCreate,
    db: Session,
) -> Optional[StoryResponse]:
    """
    Update a story.

    Args:
        story_id: Story ID
        data: Update data
        db: Database session

    Returns:
        Updated story or None if not found
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    story.name = data.name
    story.description = data.description
    story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(story)

    # Get item count
    item_count = db.query(func.count(DBStoryItem.id)).filter(
        DBStoryItem.story_id == story.id
    ).scalar()

    response = StoryResponse.model_validate(story)
    response.item_count = item_count
    return response


async def delete_story(
    story_id: str,
    db: Session,
) -> bool:
    """
    Delete a story and all its items.

    Args:
        story_id: Story ID
        db: Database session

    Returns:
        True if deleted, False if not found
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return False

    # Delete all items
    db.query(DBStoryItem).filter_by(story_id=story_id).delete()

    # Delete story
    db.delete(story)
    db.commit()

    return True


async def add_item_to_story(
    story_id: str,
    data: StoryItemCreate,
    db: Session,
) -> Optional[StoryItemDetail]:
    """
    Add a generation to a story.

    Args:
        story_id: Story ID
        data: Item creation data
        db: Database session

    Returns:
        Created item detail or None if story/generation not found
    """
    # Verify story exists
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    # Verify generation exists
    generation = db.query(DBGeneration).filter_by(id=data.generation_id).first()
    if not generation:
        return None

    # Check if generation is already in story
    existing = db.query(DBStoryItem).filter_by(
        story_id=story_id,
        generation_id=data.generation_id
    ).first()
    if existing:
        # Return existing item
        profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()
        return StoryItemDetail(
            id=existing.id,
            story_id=existing.story_id,
            generation_id=existing.generation_id,
            start_time_ms=existing.start_time_ms,
            track=existing.track,
            trim_start_ms=getattr(existing, 'trim_start_ms', 0),
            trim_end_ms=getattr(existing, 'trim_end_ms', 0),
            created_at=existing.created_at,
            profile_id=generation.profile_id,
            profile_name=profile.name if profile else "Unknown",
            text=generation.text,
            language=generation.language,
            audio_path=generation.audio_path,
            duration=generation.duration,
            seed=generation.seed,
            instruct=generation.instruct,
            generation_created_at=generation.created_at,
        )

    # Calculate start_time_ms if not provided
    if data.start_time_ms is not None:
        start_time_ms = data.start_time_ms
    else:
        # Find the maximum end time (start_time_ms + duration_ms) of existing items
        existing_items = db.query(
            DBStoryItem,
            DBGeneration
        ).join(
            DBGeneration,
            DBStoryItem.generation_id == DBGeneration.id
        ).filter(
            DBStoryItem.story_id == story_id
        ).all()
        
        if not existing_items:
            # First item starts at 0
            start_time_ms = 0
        else:
            max_end_time_ms = 0
            for item, gen in existing_items:
                item_end_ms = item.start_time_ms + int(gen.duration * 1000)
                max_end_time_ms = max(max_end_time_ms, item_end_ms)
            
            # Add 200ms gap after the last item
            start_time_ms = max_end_time_ms + 200

    # Get track from data or default to 0
    track = data.track if data.track is not None else 0

    # Create item
    item = DBStoryItem(
        id=str(uuid.uuid4()),
        story_id=story_id,
        generation_id=data.generation_id,
        start_time_ms=start_time_ms,
        track=track,
        created_at=datetime.utcnow(),
    )

    db.add(item)
    
    # Update story updated_at
    story.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()

    return StoryItemDetail(
        id=item.id,
        story_id=item.story_id,
        generation_id=item.generation_id,
        start_time_ms=item.start_time_ms,
        track=item.track,
        trim_start_ms=getattr(item, 'trim_start_ms', 0),
        trim_end_ms=getattr(item, 'trim_end_ms', 0),
        created_at=item.created_at,
        profile_id=generation.profile_id,
        profile_name=profile.name if profile else "Unknown",
        text=generation.text,
        language=generation.language,
        audio_path=generation.audio_path,
        duration=generation.duration,
        seed=generation.seed,
        instruct=generation.instruct,
        generation_created_at=generation.created_at,
    )


async def move_story_item(
    story_id: str,
    item_id: str,
    data: StoryItemMove,
    db: Session,
) -> Optional[StoryItemDetail]:
    """
    Move a story item (update position and/or track).

    Args:
        story_id: Story ID
        item_id: Story item ID
        data: New position and track data
        db: Database session

    Returns:
        Updated item detail or None if not found
    """
    # Get the item
    item = db.query(DBStoryItem).filter_by(
        id=item_id,
        story_id=story_id,
    ).first()
    if not item:
        return None

    # Get the generation
    generation = db.query(DBGeneration).filter_by(id=item.generation_id).first()
    if not generation:
        return None

    # Update position and track
    item.start_time_ms = data.start_time_ms
    item.track = data.track

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()

    return StoryItemDetail(
        id=item.id,
        story_id=item.story_id,
        generation_id=item.generation_id,
        start_time_ms=item.start_time_ms,
        track=item.track,
        trim_start_ms=getattr(item, 'trim_start_ms', 0),
        trim_end_ms=getattr(item, 'trim_end_ms', 0),
        created_at=item.created_at,
        profile_id=generation.profile_id,
        profile_name=profile.name if profile else "Unknown",
        text=generation.text,
        language=generation.language,
        audio_path=generation.audio_path,
        duration=generation.duration,
        seed=generation.seed,
        instruct=generation.instruct,
        generation_created_at=generation.created_at,
    )


async def remove_item_from_story(
    story_id: str,
    item_id: str,
    db: Session,
) -> bool:
    """
    Remove a story item from a story.

    Args:
        story_id: Story ID
        item_id: Story item ID to remove
        db: Database session

    Returns:
        True if removed, False if not found
    """
    item = db.query(DBStoryItem).filter_by(
        id=item_id,
        story_id=story_id,
    ).first()
    if not item:
        return False

    # Delete item
    db.delete(item)

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    return True


async def trim_story_item(
    story_id: str,
    item_id: str,
    data: StoryItemTrim,
    db: Session,
) -> Optional[StoryItemDetail]:
    """
    Trim a story item (update trim_start_ms and trim_end_ms).

    Args:
        story_id: Story ID
        item_id: Story item ID
        data: Trim data (trim_start_ms, trim_end_ms)
        db: Database session

    Returns:
        Updated item detail or None if not found
    """
    # Get the item
    item = db.query(DBStoryItem).filter_by(
        id=item_id,
        story_id=story_id,
    ).first()
    if not item:
        return None

    # Get the generation
    generation = db.query(DBGeneration).filter_by(id=item.generation_id).first()
    if not generation:
        return None

    # Validate trim values don't exceed duration
    max_duration_ms = int(generation.duration * 1000)
    if data.trim_start_ms + data.trim_end_ms >= max_duration_ms:
        return None  # Invalid trim - would result in zero or negative duration

    # Update trim values
    item.trim_start_ms = data.trim_start_ms
    item.trim_end_ms = data.trim_end_ms

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()

    return StoryItemDetail(
        id=item.id,
        story_id=item.story_id,
        generation_id=item.generation_id,
        start_time_ms=item.start_time_ms,
        track=item.track,
        trim_start_ms=item.trim_start_ms,
        trim_end_ms=item.trim_end_ms,
        created_at=item.created_at,
        profile_id=generation.profile_id,
        profile_name=profile.name if profile else "Unknown",
        text=generation.text,
        language=generation.language,
        audio_path=generation.audio_path,
        duration=generation.duration,
        seed=generation.seed,
        instruct=generation.instruct,
        generation_created_at=generation.created_at,
    )


async def split_story_item(
    story_id: str,
    item_id: str,
    data: StoryItemSplit,
    db: Session,
) -> Optional[List[StoryItemDetail]]:
    """
    Split a story item at a given time, creating two clips.

    Args:
        story_id: Story ID
        item_id: Story item ID to split
        data: Split data (split_time_ms - time within clip to split at)
        db: Database session

    Returns:
        List of two updated item details (original and new) or None if not found/invalid
    """
    # Get the item
    item = db.query(DBStoryItem).filter_by(
        id=item_id,
        story_id=story_id,
    ).first()
    if not item:
        return None

    # Get the generation
    generation = db.query(DBGeneration).filter_by(id=item.generation_id).first()
    if not generation:
        return None

    # Calculate effective duration and validate split point
    current_trim_start = getattr(item, 'trim_start_ms', 0)
    current_trim_end = getattr(item, 'trim_end_ms', 0)
    original_duration_ms = int(generation.duration * 1000)
    effective_duration_ms = original_duration_ms - current_trim_start - current_trim_end

    # Validate split_time_ms is within the effective duration
    if data.split_time_ms <= 0 or data.split_time_ms >= effective_duration_ms:
        return None  # Invalid split point

    # Calculate the absolute time in the original audio where we're splitting
    absolute_split_ms = current_trim_start + data.split_time_ms

    # Update original clip: trim from the end
    item.trim_end_ms = original_duration_ms - absolute_split_ms

    # Create new clip: starts after the split, trimmed from the start
    new_item = DBStoryItem(
        id=str(uuid.uuid4()),
        story_id=story_id,
        generation_id=item.generation_id,  # Same generation, different trim
        start_time_ms=item.start_time_ms + data.split_time_ms,
        track=item.track,
        trim_start_ms=absolute_split_ms,
        trim_end_ms=current_trim_end,
        created_at=datetime.utcnow(),
    )

    db.add(new_item)

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)
    db.refresh(new_item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()
    profile_name = profile.name if profile else "Unknown"

    # Build response items
    original_item_detail = StoryItemDetail(
        id=item.id,
        story_id=item.story_id,
        generation_id=item.generation_id,
        start_time_ms=item.start_time_ms,
        track=item.track,
        trim_start_ms=item.trim_start_ms,
        trim_end_ms=item.trim_end_ms,
        created_at=item.created_at,
        profile_id=generation.profile_id,
        profile_name=profile_name,
        text=generation.text,
        language=generation.language,
        audio_path=generation.audio_path,
        duration=generation.duration,
        seed=generation.seed,
        instruct=generation.instruct,
        generation_created_at=generation.created_at,
    )

    new_item_detail = StoryItemDetail(
        id=new_item.id,
        story_id=new_item.story_id,
        generation_id=new_item.generation_id,
        start_time_ms=new_item.start_time_ms,
        track=new_item.track,
        trim_start_ms=new_item.trim_start_ms,
        trim_end_ms=new_item.trim_end_ms,
        created_at=new_item.created_at,
        profile_id=generation.profile_id,
        profile_name=profile_name,
        text=generation.text,
        language=generation.language,
        audio_path=generation.audio_path,
        duration=generation.duration,
        seed=generation.seed,
        instruct=generation.instruct,
        generation_created_at=generation.created_at,
    )

    return [original_item_detail, new_item_detail]


async def duplicate_story_item(
    story_id: str,
    item_id: str,
    db: Session,
) -> Optional[StoryItemDetail]:
    """
    Duplicate a story item, creating a copy with all properties.

    Args:
        story_id: Story ID
        item_id: Story item ID to duplicate
        db: Database session

    Returns:
        New item detail or None if not found
    """
    # Get the original item
    original_item = db.query(DBStoryItem).filter_by(
        id=item_id,
        story_id=story_id,
    ).first()
    if not original_item:
        return None

    # Get the generation
    generation = db.query(DBGeneration).filter_by(id=original_item.generation_id).first()
    if not generation:
        return None

    # Calculate effective duration
    current_trim_start = getattr(original_item, 'trim_start_ms', 0)
    current_trim_end = getattr(original_item, 'trim_end_ms', 0)
    original_duration_ms = int(generation.duration * 1000)
    effective_duration_ms = original_duration_ms - current_trim_start - current_trim_end

    # Create duplicate item - place it right after the original
    new_item = DBStoryItem(
        id=str(uuid.uuid4()),
        story_id=story_id,
        generation_id=original_item.generation_id,  # Same generation as original
        start_time_ms=original_item.start_time_ms + effective_duration_ms + 200,  # 200ms gap
        track=original_item.track,
        trim_start_ms=current_trim_start,
        trim_end_ms=current_trim_end,
        created_at=datetime.utcnow(),
    )

    db.add(new_item)

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(new_item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()

    return StoryItemDetail(
        id=new_item.id,
        story_id=new_item.story_id,
        generation_id=new_item.generation_id,
        start_time_ms=new_item.start_time_ms,
        track=new_item.track,
        trim_start_ms=new_item.trim_start_ms,
        trim_end_ms=new_item.trim_end_ms,
        created_at=new_item.created_at,
        profile_id=generation.profile_id,
        profile_name=profile.name if profile else "Unknown",
        text=generation.text,
        language=generation.language,
        audio_path=generation.audio_path,
        duration=generation.duration,
        seed=generation.seed,
        instruct=generation.instruct,
        generation_created_at=generation.created_at,
    )


async def update_story_item_times(
    story_id: str,
    data: StoryItemBatchUpdate,
    db: Session,
) -> bool:
    """
    Update story item timecodes.

    Args:
        story_id: Story ID
        data: Batch update data with timecodes
        db: Database session

    Returns:
        True if updated, False if story not found or invalid
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return False

    # Get all items for this story
    items = db.query(DBStoryItem).filter_by(story_id=story_id).all()
    item_map = {item.generation_id: item for item in items}

    # Verify all generation IDs belong to this story and update timecodes
    for update in data.updates:
        if update.generation_id not in item_map:
            return False
        item_map[update.generation_id].start_time_ms = update.start_time_ms

    # Update story updated_at
    story.updated_at = datetime.utcnow()

    db.commit()
    return True


async def reorder_story_items(
    story_id: str,
    generation_ids: List[str],
    db: Session,
    gap_ms: int = 200,
) -> Optional[List[StoryItemDetail]]:
    """
    Reorder story items and recalculate timecodes.

    Args:
        story_id: Story ID
        generation_ids: List of generation IDs in the desired order
        db: Database session
        gap_ms: Gap in milliseconds between items (default 200ms)

    Returns:
        Updated list of story items with new timecodes, or None if invalid
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    # Get all items for this story with their generation data
    items_with_gen = db.query(
        DBStoryItem,
        DBGeneration,
        DBVoiceProfile.name.label('profile_name')
    ).join(
        DBGeneration,
        DBStoryItem.generation_id == DBGeneration.id
    ).join(
        DBVoiceProfile,
        DBGeneration.profile_id == DBVoiceProfile.id
    ).filter(
        DBStoryItem.story_id == story_id
    ).all()

    # Create maps for quick lookup
    item_map = {item.generation_id: (item, gen, profile_name) for item, gen, profile_name in items_with_gen}

    # Verify all generation IDs belong to this story
    if set(generation_ids) != set(item_map.keys()):
        return None

    # Recalculate timecodes based on new order
    current_time_ms = 0
    updated_items = []

    for gen_id in generation_ids:
        item, generation, profile_name = item_map[gen_id]
        
        # Update the item's start time
        item.start_time_ms = current_time_ms
        
        # Calculate the duration in ms
        duration_ms = int(generation.duration * 1000)
        
        # Move to next position (current end + gap)
        current_time_ms += duration_ms + gap_ms

        # Build the response item
        updated_items.append(StoryItemDetail(
            id=item.id,
            story_id=item.story_id,
            generation_id=item.generation_id,
            start_time_ms=item.start_time_ms,
            track=item.track,
            trim_start_ms=getattr(item, 'trim_start_ms', 0),
            trim_end_ms=getattr(item, 'trim_end_ms', 0),
            created_at=item.created_at,
            profile_id=generation.profile_id,
            profile_name=profile_name,
            text=generation.text,
            language=generation.language,
            audio_path=generation.audio_path,
            duration=generation.duration,
            seed=generation.seed,
            instruct=generation.instruct,
            generation_created_at=generation.created_at,
        ))

    # Update story updated_at
    story.updated_at = datetime.utcnow()

    db.commit()
    return updated_items


async def export_story_audio(
    story_id: str,
    db: Session,
) -> Optional[bytes]:
    """
    Export story as single mixed audio file with timecode-based mixing.

    Args:
        story_id: Story ID
        db: Database session

    Returns:
        Audio file bytes or None if story not found
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    # Get all items ordered by start_time_ms
    items = db.query(
        DBStoryItem,
        DBGeneration
    ).join(
        DBGeneration,
        DBStoryItem.generation_id == DBGeneration.id
    ).filter(
        DBStoryItem.story_id == story_id
    ).order_by(DBStoryItem.start_time_ms).all()

    if not items:
        return None

    # Load all audio files and calculate total duration
    audio_data = []
    sample_rate = 24000  # Default sample rate

    for item, generation in items:
        audio_path = Path(generation.audio_path)
        if not audio_path.exists():
            continue

        try:
            audio, sr = load_audio(str(audio_path), sample_rate=sample_rate)
            sample_rate = sr  # Use actual sample rate from first file
            
            # Get trim values
            trim_start_ms = getattr(item, 'trim_start_ms', 0)
            trim_end_ms = getattr(item, 'trim_end_ms', 0)
            
            # Calculate effective duration
            original_duration_ms = int(generation.duration * 1000)
            effective_duration_ms = original_duration_ms - trim_start_ms - trim_end_ms
            
            # Slice audio based on trim values
            trim_start_sample = int((trim_start_ms / 1000.0) * sample_rate)
            trim_end_sample = int((trim_end_ms / 1000.0) * sample_rate)
            
            # Extract the trimmed portion
            if trim_end_ms > 0:
                trimmed_audio = audio[trim_start_sample:-trim_end_sample] if trim_end_sample > 0 else audio[trim_start_sample:]
            else:
                trimmed_audio = audio[trim_start_sample:]
            
            # Store audio with its timecode info
            start_time_ms = item.start_time_ms
            
            audio_data.append({
                'audio': trimmed_audio,
                'start_time_ms': start_time_ms,
                'duration_ms': effective_duration_ms,
            })
        except Exception:
            # Skip files that can't be loaded
            continue

    if not audio_data:
        return None

    # Calculate total duration: max(start_time_ms + duration_ms)
    max_end_time_ms = max(
        (data['start_time_ms'] + data['duration_ms'] for data in audio_data),
        default=0
    )
    
    # Convert to samples
    total_samples = int((max_end_time_ms / 1000.0) * sample_rate)
    
    # Create output buffer initialized to zeros
    final_audio = np.zeros(total_samples, dtype=np.float32)

    # Mix each audio segment at its timecode position
    for data in audio_data:
        audio = data['audio']
        start_time_ms = data['start_time_ms']
        
        # Calculate start sample index
        start_sample = int((start_time_ms / 1000.0) * sample_rate)
        
        # Ensure we don't exceed buffer bounds
        audio_length = len(audio)
        end_sample = min(start_sample + audio_length, total_samples)
        
        if start_sample < total_samples:
            # Trim audio if it extends beyond buffer
            audio_to_mix = audio[:end_sample - start_sample]
            
            # Mix: add audio to existing buffer (overlapping audio will sum)
            # Normalize to prevent clipping (simple approach: divide by max)
            final_audio[start_sample:end_sample] += audio_to_mix

    # Normalize to prevent clipping
    max_val = np.abs(final_audio).max()
    if max_val > 1.0:
        final_audio = final_audio / max_val

    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        save_audio(final_audio, tmp_path, sample_rate)

        # Read file bytes
        with open(tmp_path, 'rb') as f:
            audio_bytes = f.read()

        return audio_bytes
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


_EMOTION_GUIDANCE = {
    "neutral": "steady, clear, and natural",
    "happy": "warm, upbeat, and smiling",
    "sad": "soft, reflective, and emotionally heavy",
    "angry": "firm, tense, and energetic",
    "fearful": "nervous, shaky, and cautious",
    "surprised": "reactive, bright, and sudden",
    "calm": "slow, grounded, and soothing",
}

_ALLOWED_EMOTIONS: set[str] = {
    "neutral",
    "happy",
    "sad",
    "angry",
    "fearful",
    "surprised",
    "calm",
}

# Limit concurrent long-running story renders to reduce GPU OOM/instability on small GPUs (e.g. T4).
_STORY_RENDER_SEMAPHORE = asyncio.Semaphore(1)


def build_emotion_instruction(emotion: str, intensity: float, character_name: str) -> str:
    """Build a concise TTS performance instruction from normalized emotion input."""
    normalized_emotion = emotion if emotion in _EMOTION_GUIDANCE else "neutral"
    normalized_intensity = min(1.0, max(0.0, float(intensity)))
    guidance = _EMOTION_GUIDANCE[normalized_emotion]
    return (
        f"{character_name} speaks in a {guidance} style "
        f"with emotional intensity {normalized_intensity:.2f}."
    )


def _normalize_emotion(emotion: Optional[str]) -> EmotionType:
    value = (emotion or "neutral").strip().lower()
    if value in _ALLOWED_EMOTIONS:
        return value  # type: ignore[return-value]
    return "neutral"


async def compose_story_with_groq(
    data: StoryComposeWithGroqRequest,
    db: Session,
) -> StoryRenderJobResponse:
    """
    Use Groq LLM to compose emotional dialogue lines, then start audio render job.
    """
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

    character_names = [m.character_name for m in data.character_mappings]
    character_descriptions: Dict[str, str] = {}
    character_emotion_palettes: Dict[str, List[str]] = {}
    for mapping in data.character_mappings:
        description = (mapping.description or "").strip()
        if not description:
            raise ValueError(f"Character description is required for {mapping.character_name}")
        character_descriptions[mapping.character_name] = description
        palette = list(dict.fromkeys(mapping.emotion_palette or [mapping.default_emotion]))
        if mapping.default_emotion not in palette:
            palette.append(mapping.default_emotion)
        character_emotion_palettes[mapping.character_name] = [_normalize_emotion(e) for e in palette]
    try:
        composed_lines = compose_story_lines_with_groq(
            settings,
            prompt=data.prompt,
            mode=data.mode,
            language=data.language,
            characters=character_names,
            character_descriptions=character_descriptions,
            character_emotion_palettes=character_emotion_palettes,
            target_lines=data.target_lines,
            model=llm_model,
        )
    except GroqAPIError as e:
        raise ValueError(f"Groq failed to compose story lines: {e}") from e

    char_map = {m.character_name: m for m in data.character_mappings}
    line_specs: List[StoryLineSpec] = []

    for raw in composed_lines:
        if not isinstance(raw, dict):
            continue

        raw_character = str(raw.get("character_name", "")).strip()
        if raw_character not in char_map:
            # fallback: assign first configured character
            raw_character = data.character_mappings[0].character_name

        raw_text = str(raw.get("text", "")).strip()
        if not raw_text:
            continue
        # Keep line under schema max length to avoid pydantic validation crashes from LLM output.
        raw_text = raw_text[:5000]

        raw_emotion = _normalize_emotion(str(raw.get("emotion", "neutral")))
        allowed_emotions = set(
            character_emotion_palettes.get(
                raw_character,
                [char_map[raw_character].default_emotion],
            )
        )
        if raw_emotion not in allowed_emotions:
            raw_emotion = char_map[raw_character].default_emotion
        raw_intensity = raw.get("emotion_intensity", 0.5)
        try:
            intensity = min(1.0, max(0.0, float(raw_intensity)))
        except (ValueError, TypeError):
            intensity = 0.5

        try:
            line_specs.append(
                StoryLineSpec(
                    # Virtual source id for composed lines (not linked to existing history generation).
                    source_generation_id=f"virtual:{uuid.uuid4()}",
                    character_name=raw_character,
                    text_override=raw_text,
                    emotion=raw_emotion,
                    emotion_intensity=intensity,
                    track=None,
                    start_time_ms=None,
                )
            )
        except ValidationError:
            # Skip malformed lines from LLM output instead of failing request with 500.
            continue

    if not line_specs:
        raise ValueError("Groq output did not include valid lines to render.")

    render_request = StoryRenderFromHistoryRequest(
        name=data.name,
        description=data.description,
        model_size=data.model_size,
        language=data.language,
        gap_ms=data.gap_ms,
        continue_on_error=data.continue_on_error,
        character_mappings=data.character_mappings,
        lines=line_specs,
    )
    return await create_story_render_from_history(render_request, db)


async def create_story_render_from_history(
    data: StoryRenderFromHistoryRequest,
    db: Session,
) -> StoryRenderJobResponse:
    """
    Create an asynchronous render job from history items with character emotion controls.
    """
    character_map: Dict[str, dict] = {}

    for mapping in data.character_mappings:
        if mapping.character_name in character_map:
            raise ValueError(f"Duplicate character mapping: {mapping.character_name}")

        profile = db.query(DBVoiceProfile).filter_by(id=mapping.profile_id).first()
        if not profile:
            raise ValueError(
                f"Profile {mapping.profile_id} for character {mapping.character_name} not found"
            )

        palette = set(mapping.emotion_palette or [mapping.default_emotion])
        if mapping.default_emotion not in palette:
            palette.add(mapping.default_emotion)

        character_map[mapping.character_name] = {
            "profile_id": mapping.profile_id,
            "emotion_palette": palette,
            "default_emotion": mapping.default_emotion,
            "default_emotion_intensity": mapping.default_emotion_intensity,
            "default_track": mapping.default_track,
        }

    # Validate source generations and create story/job records.
    if data.story_id:
        story = db.query(DBStory).filter_by(id=data.story_id).first()
        if not story:
            raise ValueError(f"Story not found: {data.story_id}")
        story.name = data.name
        story.description = data.description
        story.updated_at = datetime.utcnow()

        if data.replace_existing_items:
            db.query(DBStoryItem).filter_by(story_id=story.id).delete()
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

    job = DBStoryRenderJob(
        id=str(uuid.uuid4()),
        story_id=story.id,
        status="queued",
        total_lines=len(data.lines),
        processed_lines=0,
        failure_phase=None,
        failure_code=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.flush()

    for idx, line in enumerate(data.lines):
        if line.character_name not in character_map:
            raise ValueError(f"Character mapping not found for line: {line.character_name}")

        source_generation = db.query(DBGeneration).filter_by(id=line.source_generation_id).first()
        is_virtual_source = line.source_generation_id.startswith("virtual:")
        if not source_generation and not is_virtual_source:
            raise ValueError(f"Source generation not found: {line.source_generation_id}")

        mapping = character_map[line.character_name]
        if line.text_override:
            text = line.text_override
        elif source_generation:
            text = source_generation.text
        else:
            raise ValueError(
                "text_override is required for virtual source lines "
                f"({line.source_generation_id})"
            )
        emotion = line.emotion or mapping["default_emotion"]
        if emotion not in mapping["emotion_palette"]:
            emotion = mapping["default_emotion"]
        emotion_intensity = (
            line.emotion_intensity
            if line.emotion_intensity is not None
            else mapping["default_emotion_intensity"]
        )
        track = line.track if line.track is not None else mapping["default_track"]
        start_time_ms = line.start_time_ms if line.start_time_ms is not None else -1

        db.add(
            DBStoryScriptLine(
                id=str(uuid.uuid4()),
                job_id=job.id,
                story_id=story.id,
                order_index=idx,
                source_generation_id=line.source_generation_id,
                generated_generation_id=None,
                character_name=line.character_name,
                profile_id=mapping["profile_id"],
                text=text,
                emotion=emotion,
                emotion_intensity=emotion_intensity,
                resolved_instruct=None,
                track=track,
                start_time_ms=start_time_ms,
                status="queued",
                error_message=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )

    db.commit()

    task_manager = get_task_manager()
    task_manager.start_story_render(job.id, story.id, len(data.lines))

    asyncio.create_task(
        _run_story_render_job_background(
            job_id=job.id,
            model_size=data.model_size,
            language=data.language,
            gap_ms=data.gap_ms,
            continue_on_error=data.continue_on_error,
        )
    )

    return StoryRenderJobResponse(
        job_id=job.id,
        story_id=story.id,
        status="queued",
        total_lines=len(data.lines),
    )


async def _run_story_render_job_background(
    job_id: str,
    model_size: Optional[str],
    language: str,
    gap_ms: int,
    continue_on_error: bool,
) -> None:
    """
    Execute story render job sequentially to avoid GPU OOM on smaller instances (e.g., T4).
    """
    settings = load_settings()
    task_manager = get_task_manager()
    if db_module.SessionLocal is None:
        task_manager.complete_story_render(
            job_id,
            status="failed",
            error="Database session not initialized",
            error_code="STORY_RENDER_DB_NOT_INITIALIZED",
        )
        return
    db = db_module.SessionLocal()
    errors: List[str] = []

    try:
        async with _STORY_RENDER_SEMAPHORE:
            job = db.query(DBStoryRenderJob).filter_by(id=job_id).first()
            if not job:
                task_manager.complete_story_render(
                    job_id,
                    status="failed",
                    error="Job not found",
                    error_code="STORY_RENDER_JOB_NOT_FOUND",
                )
                return

            job.status = "running"
            job.failure_phase = None
            job.failure_code = None
            job.updated_at = datetime.utcnow()
            db.commit()

            tts_model = tts.get_tts_model()
            requested_model_size = model_size or settings.default_model_size
            await tts_model.load_model_async(requested_model_size)

            script_lines = (
                db.query(DBStoryScriptLine)
                .filter_by(job_id=job_id)
                .order_by(DBStoryScriptLine.order_index.asc())
                .all()
            )

            current_time_ms = 0
            processed_lines = 0

            for line_ref in script_lines:
                line_id = line_ref.id
                line = db.query(DBStoryScriptLine).filter_by(id=line_id).first()
                if not line:
                    continue

                try:
                    line.status = "running"
                    line.updated_at = datetime.utcnow()
                    db.commit()

                    source_generation = db.query(DBGeneration).filter_by(id=line.source_generation_id).first()
                    if not source_generation and not line.source_generation_id.startswith("virtual:"):
                        raise ValueError(f"Source generation not found: {line.source_generation_id}")

                    fallback_instruct = build_emotion_instruction(
                        emotion=line.emotion,
                        intensity=line.emotion_intensity,
                        character_name=line.character_name,
                    )
                    resolved_instruct = maybe_generate_emotion_instruction_with_groq(
                        settings,
                        text=line.text,
                        character_name=line.character_name,
                        emotion=line.emotion,
                        intensity=line.emotion_intensity,
                        fallback_instruction=fallback_instruct,
                    )

                    voice_prompt = await profiles.create_voice_prompt_for_profile(line.profile_id, db)
                    audio, sample_rate = await tts_model.generate(
                        text=line.text,
                        voice_prompt=voice_prompt,
                        language=language,
                        instruct=resolved_instruct,
                    )

                    duration = len(audio) / sample_rate
                    audio_id = str(uuid.uuid4())
                    audio_path = config.get_generations_dir() / f"{audio_id}.wav"
                    save_audio(audio, str(audio_path), sample_rate)

                    generated = await history.create_generation(
                        profile_id=line.profile_id,
                        text=line.text,
                        language=language,
                        audio_path=str(audio_path),
                        duration=duration,
                        seed=None,
                        db=db,
                        instruct=resolved_instruct,
                    )

                    was_explicit_start = line.start_time_ms >= 0
                    start_time_ms = line.start_time_ms if was_explicit_start else current_time_ms
                    db.add(
                        DBStoryItem(
                            id=str(uuid.uuid4()),
                            story_id=job.story_id,
                            generation_id=generated.id,
                            start_time_ms=start_time_ms,
                            track=line.track,
                            trim_start_ms=0,
                            trim_end_ms=0,
                            created_at=datetime.utcnow(),
                        )
                    )

                    line.generated_generation_id = generated.id
                    line.resolved_instruct = resolved_instruct
                    line.status = "completed"
                    line.start_time_ms = start_time_ms
                    line.updated_at = datetime.utcnow()

                    processed_lines += 1
                    job.processed_lines = processed_lines
                    job.updated_at = datetime.utcnow()

                    # Only auto-place next line when current line is auto-placed.
                    end_time_ms = start_time_ms + int(duration * 1000)
                    if was_explicit_start:
                        current_time_ms = max(current_time_ms, end_time_ms + gap_ms)
                    else:
                        current_time_ms = end_time_ms + gap_ms

                    db.commit()
                    task_manager.update_story_render_progress(job_id, processed_lines)
                except Exception as line_error:
                    db.rollback()
                    line = db.query(DBStoryScriptLine).filter_by(id=line_id).first()
                    if line:
                        line.status = "failed"
                        line.error_message = str(line_error)[:1000]
                        line.updated_at = datetime.utcnow()
                    errors.append(f"line {line_ref.order_index}: {line_error}")
                    job = db.query(DBStoryRenderJob).filter_by(id=job_id).first()
                    if job:
                        job.updated_at = datetime.utcnow()
                    db.commit()
                    if not continue_on_error:
                        break

            job = db.query(DBStoryRenderJob).filter_by(id=job_id).first()
            if not job:
                return

            failed_lines = sum(1 for line in script_lines if line.status == "failed")
            if processed_lines == 0:
                job.status = "failed"
                job.failure_phase = "line_generation"
                job.failure_code = "STORY_RENDER_LINE_FAILED"
            elif errors:
                job.status = "partial_failed"
                job.failure_phase = "line_generation"
                job.failure_code = "STORY_RENDER_LINE_FAILED"
            else:
                job.status = "completed"
                job.failure_phase = None
                job.failure_code = None

            if errors:
                job.error_summary = " | ".join(errors[:5])

            if processed_lines > 0:
                try:
                    audio_bytes = await export_story_audio(job.story_id, db)
                    if audio_bytes:
                        story_dir = _get_stories_output_dir() / job.story_id
                        story_dir.mkdir(parents=True, exist_ok=True)
                        output_path = story_dir / "final_mix.wav"
                        output_path.write_bytes(audio_bytes)
                        job.output_audio_path = str(output_path)
                    elif job.status == "completed":
                        job.status = "failed"
                        job.failure_phase = "mix_export"
                        job.failure_code = "STORY_RENDER_MIX_EXPORT_FAILED"
                        job.error_summary = "Could not export final story mix audio."
                except Exception as mix_error:
                    job.status = "failed"
                    job.failure_phase = "mix_export"
                    job.failure_code = "STORY_RENDER_MIX_EXPORT_FAILED"
                    job.error_summary = str(mix_error)[:1000]

            job.completed_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            db.commit()

            task_manager.complete_story_render(
                job_id,
                status=job.status,
                error=job.error_summary,
                error_code=job.failure_code,
            )
    except Exception as job_error:
        db.rollback()
        job = db.query(DBStoryRenderJob).filter_by(id=job_id).first()
        if job:
            job.status = "failed"
            job.error_summary = str(job_error)[:1000]
            job.failure_phase = "line_generation"
            job.failure_code = _story_render_error_code(job_error)
            job.completed_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            db.commit()
        task_manager.complete_story_render(
            job_id,
            status="failed",
            error=str(job_error),
            error_code=_story_render_error_code(job_error),
        )
    finally:
        db.close()


async def get_story_render_status(
    job_id: str,
    db: Session,
) -> Optional[StoryRenderStatusResponse]:
    """Get status and per-line results for a render job."""
    job = db.query(DBStoryRenderJob).filter_by(id=job_id).first()
    if not job:
        return None

    lines = (
        db.query(DBStoryScriptLine)
        .filter_by(job_id=job_id)
        .order_by(DBStoryScriptLine.order_index.asc())
        .all()
    )

    line_statuses: List[StoryRenderLineStatus] = []
    for line in lines:
        emotion = line.emotion if line.emotion in _EMOTION_GUIDANCE else "neutral"
        line_statuses.append(
            StoryRenderLineStatus(
                id=line.id,
                order_index=line.order_index,
                source_generation_id=line.source_generation_id,
                generated_generation_id=line.generated_generation_id,
                character_name=line.character_name,
                profile_id=line.profile_id,
                text=line.text,
                emotion=emotion,
                emotion_intensity=line.emotion_intensity,
                resolved_instruct=line.resolved_instruct,
                track=line.track,
                start_time_ms=line.start_time_ms if line.start_time_ms >= 0 else 0,
                status=line.status,
                error_message=line.error_message,
            )
        )

    failed_lines = sum(1 for line in line_statuses if line.status == "failed")
    return StoryRenderStatusResponse(
        job_id=job.id,
        story_id=job.story_id,
        status=job.status,
        total_lines=job.total_lines,
        processed_lines=job.processed_lines,
        completed_lines=job.processed_lines,
        failed_lines=failed_lines,
        error_summary=job.error_summary,
        failure_phase=job.failure_phase,
        failure_code=job.failure_code,
        output_audio_path=job.output_audio_path,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        lines=line_statuses,
    )


async def get_story_audio_path(story_id: str, db: Session) -> Optional[Path]:
    """Get persisted mixed audio path for a story (if available)."""
    job = (
        db.query(DBStoryRenderJob)
        .filter(
            DBStoryRenderJob.story_id == story_id,
            DBStoryRenderJob.output_audio_path.isnot(None),
        )
        .order_by(DBStoryRenderJob.updated_at.desc())
        .first()
    )
    if not job or not job.output_audio_path:
        return None

    path = Path(job.output_audio_path)
    if not path.exists():
        return None
    return path
