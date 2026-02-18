"""
Generation history management module.
"""

from collections import defaultdict
from typing import Dict, List, Optional, Set
from datetime import datetime
import uuid
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import (
    GenerationResponse,
    HistoryQuery,
    HistoryResponse,
    HistoryListResponse,
    HistoryStoryLink,
    HistoryBulkDeleteRequest,
    HistoryBulkDeleteResponse,
)
from .database import (
    Generation as DBGeneration,
    VoiceProfile as DBVoiceProfile,
    StoryItem as DBStoryItem,
    Story as DBStory,
)
from . import config


def _get_generations_dir() -> Path:
    """Get generations directory from config."""
    return config.get_generations_dir()


async def create_generation(
    profile_id: str,
    text: str,
    language: str,
    audio_path: str,
    duration: float,
    seed: Optional[int],
    db: Session,
    instruct: Optional[str] = None,
) -> GenerationResponse:
    """
    Create a new generation history entry.

    Args:
        profile_id: Profile ID used for generation
        text: Generated text
        language: Language code
        audio_path: Path where audio was saved
        duration: Audio duration in seconds
        seed: Random seed used (if any)
        db: Database session
        instruct: Natural language instruction used (if any)

    Returns:
        Created generation entry
    """
    db_generation = DBGeneration(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        text=text,
        language=language,
        audio_path=audio_path,
        duration=duration,
        seed=seed,
        instruct=instruct,
        created_at=datetime.utcnow(),
    )

    db.add(db_generation)
    db.commit()
    db.refresh(db_generation)

    return GenerationResponse.model_validate(db_generation)


async def get_generation(
    generation_id: str,
    db: Session,
) -> Optional[GenerationResponse]:
    """
    Get a generation by ID.
    
    Args:
        generation_id: Generation ID
        db: Database session
        
    Returns:
        Generation or None if not found
    """
    generation = db.query(DBGeneration).filter_by(id=generation_id).first()
    if not generation:
        return None
    
    return GenerationResponse.model_validate(generation)


def _get_story_links_for_generation_ids(
    generation_ids: List[str],
    db: Session,
) -> Dict[str, List[HistoryStoryLink]]:
    """Return per-generation story linkage summaries."""
    if not generation_ids:
        return {}

    rows = (
        db.query(
            DBStoryItem.generation_id.label("generation_id"),
            DBStoryItem.story_id.label("story_id"),
            DBStory.name.label("story_name"),
            func.count(DBStoryItem.id).label("item_count"),
        )
        .join(DBStory, DBStory.id == DBStoryItem.story_id)
        .filter(DBStoryItem.generation_id.in_(generation_ids))
        .group_by(DBStoryItem.generation_id, DBStoryItem.story_id, DBStory.name)
        .all()
    )

    links_by_generation: Dict[str, List[HistoryStoryLink]] = defaultdict(list)
    for row in rows:
        links_by_generation[row.generation_id].append(
            HistoryStoryLink(
                story_id=row.story_id,
                story_name=row.story_name,
                item_count=int(row.item_count or 0),
            )
        )

    for generation_id in links_by_generation:
        links_by_generation[generation_id].sort(
            key=lambda link: (-link.item_count, link.story_name.lower())
        )
    return links_by_generation


def _build_history_response(
    generation: DBGeneration,
    profile_name: str,
    links: List[HistoryStoryLink],
) -> HistoryResponse:
    linked_item_count = sum(link.item_count for link in links)
    return HistoryResponse(
        id=generation.id,
        profile_id=generation.profile_id,
        profile_name=profile_name,
        text=generation.text,
        language=generation.language,
        audio_path=generation.audio_path,
        duration=generation.duration,
        seed=generation.seed,
        instruct=generation.instruct,
        created_at=generation.created_at,
        is_orphan=len(links) == 0,
        linked_story_count=len(links),
        linked_item_count=linked_item_count,
        story_links=links,
    )


async def list_generations(
    query: HistoryQuery,
    db: Session,
) -> HistoryListResponse:
    """
    List generations with optional filters.
    
    Args:
        query: Query parameters (filters, pagination)
        db: Database session
        
    Returns:
        HistoryListResponse with items and total count
    """
    # Build base query with join to get profile name.
    q = db.query(
        DBGeneration,
        DBVoiceProfile.name.label("profile_name"),
    ).join(
        DBVoiceProfile,
        DBGeneration.profile_id == DBVoiceProfile.id,
    )

    # Apply profile filter.
    if query.profile_id:
        q = q.filter(DBGeneration.profile_id == query.profile_id)

    # Apply search filter (searches in text content).
    if query.search:
        search_pattern = f"%{query.search}%"
        q = q.filter(DBGeneration.text.like(search_pattern))

    linked_exists = (
        db.query(DBStoryItem.id)
        .filter(DBStoryItem.generation_id == DBGeneration.id)
        .exists()
    )

    # Apply origin filter.
    if query.origin == "orphan":
        q = q.filter(~linked_exists)
    elif query.origin == "linked":
        q = q.filter(linked_exists)

    # Optional collection filter by story.
    if query.story_id:
        in_story_exists = (
            db.query(DBStoryItem.id)
            .filter(
                DBStoryItem.story_id == query.story_id,
                DBStoryItem.generation_id == DBGeneration.id,
            )
            .exists()
        )
        q = q.filter(in_story_exists)

    # Get total count before pagination.
    total_count = q.count()

    # Apply ordering (newest first) and pagination.
    results = (
        q.order_by(DBGeneration.created_at.desc())
        .offset(query.offset)
        .limit(query.limit)
        .all()
    )

    generation_ids = [generation.id for generation, _profile_name in results]
    links_by_generation = _get_story_links_for_generation_ids(generation_ids, db)

    items: List[HistoryResponse] = []
    for generation, profile_name in results:
        links = links_by_generation.get(generation.id, [])
        items.append(_build_history_response(generation, profile_name, links))

    return HistoryListResponse(items=items, total=total_count)


async def get_history_generation(
    generation_id: str,
    db: Session,
) -> Optional[HistoryResponse]:
    """
    Get one generation enriched with profile/story linkage metadata.
    """
    result = (
        db.query(
            DBGeneration,
            DBVoiceProfile.name.label("profile_name"),
        )
        .join(DBVoiceProfile, DBGeneration.profile_id == DBVoiceProfile.id)
        .filter(DBGeneration.id == generation_id)
        .first()
    )
    if not result:
        return None

    generation, profile_name = result
    links_by_generation = _get_story_links_for_generation_ids([generation.id], db)
    return _build_history_response(generation, profile_name, links_by_generation.get(generation.id, []))


async def delete_generation(
    generation_id: str,
    db: Session,
    force: bool = False,
) -> str:
    """
    Delete a generation.
    
    Args:
        generation_id: Generation ID
        db: Database session
        
    Returns:
        "deleted", "not_found", or "protected"
    """
    generation = db.query(DBGeneration).filter_by(id=generation_id).first()
    if not generation:
        return "not_found"

    linked_item_count = db.query(func.count(DBStoryItem.id)).filter(
        DBStoryItem.generation_id == generation_id
    ).scalar() or 0
    if linked_item_count > 0 and not force:
        return "protected"

    if force and linked_item_count > 0:
        db.query(DBStoryItem).filter(DBStoryItem.generation_id == generation_id).delete(
            synchronize_session=False
        )

    audio_path = Path(generation.audio_path)
    if audio_path.exists():
        audio_path.unlink()

    db.delete(generation)
    db.commit()

    return "deleted"


def _delete_generation_record(
    generation: DBGeneration,
    *,
    delete_audio_files: bool,
) -> tuple[bool, Optional[str]]:
    """
    Delete generation audio file from disk if requested.

    Returns:
        (audio_deleted, error_message)
    """
    if not delete_audio_files:
        return False, None
    audio_path = Path(generation.audio_path)
    if not audio_path.exists():
        return False, f"Audio file missing for generation {generation.id}: {audio_path}"
    try:
        audio_path.unlink()
        return True, None
    except Exception as exc:  # pragma: no cover - filesystem/runtime dependent
        return False, f"Failed deleting audio for {generation.id}: {exc}"


async def bulk_delete_generations(
    data: HistoryBulkDeleteRequest,
    db: Session,
) -> HistoryBulkDeleteResponse:
    """
    Bulk-delete generations using safe scopes.
    """
    if data.scope == "story" and not data.story_id:
        raise ValueError("story_id is required when scope='story'")

    if data.scope == "story" and not data.detach_story_items:
        if not data.dry_run:
            raise ValueError(
                "Story scope requires detach_story_items=true to avoid accidental data loss. "
                "Use dry_run=true for preview."
            )

    errors: List[str] = []
    requested_generations = 0
    deleted_generations = 0
    deleted_audio_files = 0
    protected_generations = 0
    deleted_story_items = 0
    retained_shared_generations = 0

    if data.scope == "all":
        candidate_rows = db.query(DBGeneration).all()
    elif data.scope == "orphans":
        linked_exists = (
            db.query(DBStoryItem.id)
            .filter(DBStoryItem.generation_id == DBGeneration.id)
            .exists()
        )
        candidate_rows = db.query(DBGeneration).filter(~linked_exists).all()
    else:
        # scope == "story"
        assert data.story_id is not None
        candidate_rows = (
            db.query(DBGeneration)
            .join(DBStoryItem, DBStoryItem.generation_id == DBGeneration.id)
            .filter(DBStoryItem.story_id == data.story_id)
            .distinct()
            .all()
        )

    candidate_ids: Set[str] = {row.id for row in candidate_rows}
    requested_generations = len(candidate_ids)

    if data.scope == "story" and data.story_id:
        story_item_rows = db.query(DBStoryItem).filter(DBStoryItem.story_id == data.story_id).all()
        deleted_story_items = len(story_item_rows) if (data.detach_story_items or data.dry_run) else 0

    if data.dry_run:
        if data.scope in {"all", "orphans"}:
            for generation_id in candidate_ids:
                refs = db.query(func.count(DBStoryItem.id)).filter(
                    DBStoryItem.generation_id == generation_id
                ).scalar() or 0
                if refs > 0:
                    protected_generations += 1
                else:
                    deleted_generations += 1
        else:
            assert data.story_id is not None
            for generation_id in candidate_ids:
                total_refs = db.query(func.count(DBStoryItem.id)).filter(
                    DBStoryItem.generation_id == generation_id
                ).scalar() or 0
                story_refs = db.query(func.count(DBStoryItem.id)).filter(
                    DBStoryItem.generation_id == generation_id,
                    DBStoryItem.story_id == data.story_id,
                ).scalar() or 0
                remaining_refs = max(0, total_refs - story_refs)
                if remaining_refs > 0:
                    retained_shared_generations += 1
                else:
                    deleted_generations += 1

        return HistoryBulkDeleteResponse(
            scope=data.scope,
            story_id=data.story_id,
            dry_run=True,
            requested_generations=requested_generations,
            deleted_generations=deleted_generations,
            deleted_audio_files=deleted_audio_files,
            protected_generations=protected_generations,
            deleted_story_items=deleted_story_items,
            retained_shared_generations=retained_shared_generations,
            errors=errors,
        )

    # Apply changes.
    try:
        if data.scope == "story" and data.story_id and data.detach_story_items:
            deleted_story_items = db.query(DBStoryItem).filter(
                DBStoryItem.story_id == data.story_id
            ).delete(synchronize_session=False)
            db.flush()

        for generation in candidate_rows:
            refs = db.query(func.count(DBStoryItem.id)).filter(
                DBStoryItem.generation_id == generation.id
            ).scalar() or 0

            if refs > 0:
                if data.scope == "story":
                    retained_shared_generations += 1
                else:
                    protected_generations += 1
                continue

            audio_deleted, maybe_error = _delete_generation_record(
                generation,
                delete_audio_files=True,
            )
            if audio_deleted:
                deleted_audio_files += 1
            if maybe_error:
                errors.append(maybe_error)

            db.delete(generation)
            deleted_generations += 1

        db.commit()
    except Exception:
        db.rollback()
        raise

    return HistoryBulkDeleteResponse(
        scope=data.scope,
        story_id=data.story_id,
        dry_run=False,
        requested_generations=requested_generations,
        deleted_generations=deleted_generations,
        deleted_audio_files=deleted_audio_files,
        protected_generations=protected_generations,
        deleted_story_items=deleted_story_items,
        retained_shared_generations=retained_shared_generations,
        errors=errors,
    )


async def delete_generations_by_profile(
    profile_id: str,
    db: Session,
) -> int:
    """
    Delete all generations for a profile.
    
    Args:
        profile_id: Profile ID
        db: Database session
        
    Returns:
        Number of generations deleted
    """
    generations = db.query(DBGeneration).filter_by(profile_id=profile_id).all()
    
    count = 0
    for generation in generations:
        # Delete audio file
        audio_path = Path(generation.audio_path)
        if audio_path.exists():
            audio_path.unlink()
        
        # Delete from database
        db.delete(generation)
        count += 1
    
    db.commit()
    
    return count


async def get_generation_stats(db: Session) -> dict:
    """
    Get generation statistics.
    
    Args:
        db: Database session
        
    Returns:
        Statistics dictionary
    """
    from sqlalchemy import func
    
    total = db.query(func.count(DBGeneration.id)).scalar()
    
    total_duration = db.query(func.sum(DBGeneration.duration)).scalar() or 0
    
    # Get generations by profile
    by_profile = db.query(
        DBGeneration.profile_id,
        func.count(DBGeneration.id).label('count')
    ).group_by(DBGeneration.profile_id).all()
    
    return {
        "total_generations": total,
        "total_duration_seconds": total_duration,
        "generations_by_profile": {
            profile_id: count for profile_id, count in by_profile
        },
    }
