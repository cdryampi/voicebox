"""
SQLite database ORM using SQLAlchemy.
"""

from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
import uuid
from pathlib import Path

from . import config

Base = declarative_base()


class VoiceProfile(Base):
    """Voice profile database model."""
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)
    description = Column(Text)
    language = Column(String, default="en")
    avatar_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProfileSample(Base):
    """Voice profile sample database model."""
    __tablename__ = "profile_samples"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    audio_path = Column(String, nullable=False)
    reference_text = Column(Text, nullable=False)


class Generation(Base):
    """Generation history database model."""
    __tablename__ = "generations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    text = Column(Text, nullable=False)
    language = Column(String, default="en")
    audio_path = Column(String, nullable=False)
    duration = Column(Float, nullable=False)
    seed = Column(Integer)
    instruct = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Story(Base):
    """Story database model."""
    __tablename__ = "stories"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StoryItem(Base):
    """Story item database model (links generations to stories)."""
    __tablename__ = "story_items"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    story_id = Column(String, ForeignKey("stories.id"), nullable=False)
    generation_id = Column(String, ForeignKey("generations.id"), nullable=False)
    start_time_ms = Column(Integer, nullable=False, default=0)  # Milliseconds from story start
    track = Column(Integer, nullable=False, default=0)  # Track number (0 = main track)
    trim_start_ms = Column(Integer, nullable=False, default=0)  # Milliseconds trimmed from start
    trim_end_ms = Column(Integer, nullable=False, default=0)  # Milliseconds trimmed from end
    created_at = Column(DateTime, default=datetime.utcnow)


class StoryRenderJob(Base):
    """Background render job for story generation from history lines."""
    __tablename__ = "story_render_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    story_id = Column(String, ForeignKey("stories.id"), nullable=False)
    status = Column(String, nullable=False, default="queued")
    total_lines = Column(Integer, nullable=False, default=0)
    processed_lines = Column(Integer, nullable=False, default=0)
    error_summary = Column(Text, nullable=True)
    output_audio_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class StoryScriptLine(Base):
    """Per-line status for story render jobs."""
    __tablename__ = "story_script_lines"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("story_render_jobs.id"), nullable=False)
    story_id = Column(String, ForeignKey("stories.id"), nullable=False)
    order_index = Column(Integer, nullable=False)
    source_generation_id = Column(String, ForeignKey("generations.id"), nullable=False)
    generated_generation_id = Column(String, ForeignKey("generations.id"), nullable=True)
    character_name = Column(String, nullable=False)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    text = Column(Text, nullable=False)
    emotion = Column(String, nullable=False, default="neutral")
    emotion_intensity = Column(Float, nullable=False, default=0.5)
    resolved_instruct = Column(Text, nullable=True)
    track = Column(Integer, nullable=False, default=0)
    start_time_ms = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="queued")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StudioDraft(Base):
    """Studio draft generated by LLM for iterative review."""
    __tablename__ = "studio_drafts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    story_id = Column(String, ForeignKey("stories.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    prompt = Column(Text, nullable=False)
    mode = Column(String, nullable=False, default="roleplay")
    language = Column(String, nullable=False, default="en")
    llm_model = Column(String, nullable=False)
    model_size = Column(String, nullable=True)
    gap_ms = Column(Integer, nullable=False, default=200)
    continue_on_error = Column(Boolean, nullable=False, default=True)
    status = Column(String, nullable=False, default="draft")
    limits_json = Column(Text, nullable=False)
    character_mappings_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StudioDraftLine(Base):
    """Editable line/card inside a Studio draft."""
    __tablename__ = "studio_draft_lines"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id = Column(String, ForeignKey("studio_drafts.id"), nullable=False)
    order_index = Column(Integer, nullable=False, default=0)
    character_name = Column(String, nullable=False)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    text = Column(Text, nullable=False)
    emotion = Column(String, nullable=False, default="neutral")
    emotion_intensity = Column(Float, nullable=False, default=0.5)
    truncated = Column(Boolean, nullable=False, default=False)
    preview_audio_path = Column(String, nullable=True)
    preview_duration = Column(Float, nullable=True)
    preview_status = Column(String, nullable=False, default="idle")
    preview_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Project(Base):
    """Audio studio project database model."""
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    data = Column(Text)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AudioChannel(Base):
    """Audio channel (bus) database model."""
    __tablename__ = "audio_channels"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChannelDeviceMapping(Base):
    """Mapping between channels and OS audio devices."""
    __tablename__ = "channel_device_mappings"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(String, ForeignKey("audio_channels.id"), nullable=False)
    device_id = Column(String, nullable=False)  # OS device identifier


class ProfileChannelMapping(Base):
    """Mapping between voice profiles and audio channels (many-to-many)."""
    __tablename__ = "profile_channel_mappings"
    
    profile_id = Column(String, ForeignKey("profiles.id"), primary_key=True)
    channel_id = Column(String, ForeignKey("audio_channels.id"), primary_key=True)


# Database setup will be initialized in init_db()
engine = None
SessionLocal = None
_db_path = None


def init_db():
    """Initialize database tables."""
    global engine, SessionLocal, _db_path

    _db_path = config.get_db_path()
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{_db_path}",
        connect_args={"check_same_thread": False},
    )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Run migrations before creating tables
    _run_migrations(engine)
    
    Base.metadata.create_all(bind=engine)
    
    # Create default channel if it doesn't exist
    db = SessionLocal()
    try:
        default_channel = db.query(AudioChannel).filter(AudioChannel.is_default == True).first()
        if not default_channel:
            default_channel = AudioChannel(
                id=str(uuid.uuid4()),
                name="Default",
                is_default=True
            )
            db.add(default_channel)
            
            # Assign all existing profiles to default channel
            profiles = db.query(VoiceProfile).all()
            for profile in profiles:
                mapping = ProfileChannelMapping(
                    profile_id=profile.id,
                    channel_id=default_channel.id
                )
                db.add(mapping)
            
            db.commit()
    finally:
        db.close()


def _run_migrations(engine):
    """Run database migrations."""
    from sqlalchemy import inspect, text
    
    inspector = inspect(engine)
    
    # Check if story_items table exists
    if 'story_items' not in inspector.get_table_names():
        return  # Table doesn't exist yet, will be created fresh
    
    # Get columns in story_items table
    columns = {col['name'] for col in inspector.get_columns('story_items')}
    
    # Migration: Remove position column and ensure start_time_ms exists
    # SQLite doesn't support DROP COLUMN easily, so we recreate the table
    if 'position' in columns:
        print("Migrating story_items: removing position column, using start_time_ms")
        
        with engine.connect() as conn:
            # Check if start_time_ms already exists
            has_start_time = 'start_time_ms' in columns
            
            if not has_start_time:
                # First, add the new column temporarily
                conn.execute(text("ALTER TABLE story_items ADD COLUMN start_time_ms INTEGER DEFAULT 0"))
                
                # Calculate timecodes from position ordering
                result = conn.execute(text("""
                    SELECT si.id, si.story_id, si.position, g.duration
                    FROM story_items si
                    JOIN generations g ON si.generation_id = g.id
                    ORDER BY si.story_id, si.position
                """))
                
                rows = result.fetchall()
                
                current_story_id = None
                current_time_ms = 0
                
                for row in rows:
                    item_id, story_id, position, duration = row
                    
                    if story_id != current_story_id:
                        current_story_id = story_id
                        current_time_ms = 0
                    
                    conn.execute(
                        text("UPDATE story_items SET start_time_ms = :time WHERE id = :id"),
                        {"time": current_time_ms, "id": item_id}
                    )
                    
                    current_time_ms += int(duration * 1000) + 200
                
                conn.commit()
            
            # Now recreate the table without the position column
            # 1. Create new table
            conn.execute(text("""
                CREATE TABLE story_items_new (
                    id VARCHAR PRIMARY KEY,
                    story_id VARCHAR NOT NULL,
                    generation_id VARCHAR NOT NULL,
                    start_time_ms INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME,
                    FOREIGN KEY (story_id) REFERENCES stories(id),
                    FOREIGN KEY (generation_id) REFERENCES generations(id)
                )
            """))
            
            # 2. Copy data
            conn.execute(text("""
                INSERT INTO story_items_new (id, story_id, generation_id, start_time_ms, created_at)
                SELECT id, story_id, generation_id, start_time_ms, created_at FROM story_items
            """))
            
            # 3. Drop old table
            conn.execute(text("DROP TABLE story_items"))
            
            # 4. Rename new table
            conn.execute(text("ALTER TABLE story_items_new RENAME TO story_items"))
            
            conn.commit()
            print("Migrated story_items table to use start_time_ms (removed position column)")
    
    # Migration: Add track column if it doesn't exist
    # Re-check columns after potential position migration
    columns = {col['name'] for col in inspector.get_columns('story_items')}
    if 'track' not in columns:
        print("Migrating story_items: adding track column")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE story_items ADD COLUMN track INTEGER NOT NULL DEFAULT 0"))
            conn.commit()
            print("Added track column to story_items")
    
    # Migration: Add trim columns if they don't exist
    # Re-check columns after potential track migration
    columns = {col['name'] for col in inspector.get_columns('story_items')}
    if 'trim_start_ms' not in columns:
        print("Migrating story_items: adding trim_start_ms column")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE story_items ADD COLUMN trim_start_ms INTEGER NOT NULL DEFAULT 0"))
            conn.commit()
            print("Added trim_start_ms column to story_items")
    
    columns = {col['name'] for col in inspector.get_columns('story_items')}
    if 'trim_end_ms' not in columns:
        print("Migrating story_items: adding trim_end_ms column")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE story_items ADD COLUMN trim_end_ms INTEGER NOT NULL DEFAULT 0"))
            conn.commit()
            print("Added trim_end_ms column to story_items")

    # Migration: Add avatar_path to profiles table
    if 'profiles' in inspector.get_table_names():
        columns = {col['name'] for col in inspector.get_columns('profiles')}
        if 'avatar_path' not in columns:
            print("Migrating profiles: adding avatar_path column")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE profiles ADD COLUMN avatar_path VARCHAR"))
                conn.commit()
                print("Added avatar_path column to profiles")

    # Migration: ensure story_render_jobs optional columns exist
    if 'story_render_jobs' in inspector.get_table_names():
        columns = {col['name'] for col in inspector.get_columns('story_render_jobs')}
        if 'output_audio_path' not in columns:
            print("Migrating story_render_jobs: adding output_audio_path column")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE story_render_jobs ADD COLUMN output_audio_path VARCHAR"))
                conn.commit()
        columns = {col['name'] for col in inspector.get_columns('story_render_jobs')}
        if 'completed_at' not in columns:
            print("Migrating story_render_jobs: adding completed_at column")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE story_render_jobs ADD COLUMN completed_at DATETIME"))
                conn.commit()

    # Migration: ensure studio_drafts optional columns exist
    if 'studio_drafts' in inspector.get_table_names():
        columns = {col['name'] for col in inspector.get_columns('studio_drafts')}
        if 'model_size' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE studio_drafts ADD COLUMN model_size VARCHAR"))
                conn.commit()
        columns = {col['name'] for col in inspector.get_columns('studio_drafts')}
        if 'gap_ms' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE studio_drafts ADD COLUMN gap_ms INTEGER NOT NULL DEFAULT 200"))
                conn.commit()
        columns = {col['name'] for col in inspector.get_columns('studio_drafts')}
        if 'continue_on_error' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE studio_drafts ADD COLUMN continue_on_error BOOLEAN NOT NULL DEFAULT 1"))
                conn.commit()
        columns = {col['name'] for col in inspector.get_columns('studio_drafts')}
        if 'character_mappings_json' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE studio_drafts ADD COLUMN character_mappings_json TEXT NOT NULL DEFAULT '[]'"))
                conn.commit()

    # Migration: ensure studio_draft_lines optional columns exist
    if 'studio_draft_lines' in inspector.get_table_names():
        columns = {col['name'] for col in inspector.get_columns('studio_draft_lines')}
        if 'truncated' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE studio_draft_lines ADD COLUMN truncated BOOLEAN NOT NULL DEFAULT 0"))
                conn.commit()


def get_db():
    """Get database session (generator for dependency injection)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
