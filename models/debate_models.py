# debate_models.py
# This file defines the database structure for storing debate information.
# We use SQLAlchemy's Object-Relational Mapper (ORM), which lets us define
# database tables as Python classes. These classes are called "models".

# --- Imports ---
# We import the necessary building blocks from SQLAlchemy to define our models.
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

# `declarative_base()` returns a base class that our models will inherit from.
# This `Base` class holds the metadata about our tables and their mappings.
Base = declarative_base()

# --- DebateSession Model ---
# This class defines the `debate_sessions` table in the database.
# Each instance of this class will represent a single row in that table.
class DebateSession(Base):
    # `__tablename__` tells SQLAlchemy the name of the table to use in the database.
    __tablename__ = "debate_sessions"

    # --- Columns ---
    # Here we define the columns for the `debate_sessions` table.

    # `id` is the primary key. It's a unique integer for each session.
    # `autoincrement=True` means the database will automatically assign a new,
    # incrementing number for each new session.
    id = Column(Integer, primary_key=True, autoincrement=True)

    # `topic` stores the subject of the debate. `Text` is for long strings.
    # `nullable=False` means every session must have a topic.
    topic = Column(Text, nullable=False)

    # `character_1` and `character_2` store the names of the debaters.
    # `String(128)` is a text field with a maximum length of 128 characters.
    # `nullable=True` allows these to be empty, which is useful for modes like
    # "Solo" or "Devil's Advocate" where there might be only one AI character.
    character_1 = Column(String(128), nullable=True)  # canonical lowercase or None for solo/devil
    character_2 = Column(String(128), nullable=True)

    # `created_at` is a timestamp for when the session was created.
    # `default=datetime.utcnow` automatically sets the current time when a new
    # session is created.
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # --- Relationships ---
    # This line defines the connection between a `DebateSession` and its `DebateTurn`s.
    # It allows us to easily access all turns for a session (e.g., `my_session.turns`).
    # `back_populates="session"` links this to the `session` relationship in the `DebateTurn` model.
    # `cascade="all, delete-orphan"` means if a session is deleted, all of its associated turns are also deleted.
    turns = relationship("DebateTurn", back_populates="session", cascade="all, delete-orphan")

# --- DebateTurn Model ---
# This class defines the `debate_turns` table. Each instance represents one
# message or turn from a speaker within a debate session.
class DebateTurn(Base):
    __tablename__ = "debate_turns"

    # --- Columns ---

    # The unique ID for each turn in a debate.
    id = Column(Integer, primary_key=True, autoincrement=True)

    # `session_id` links this turn to a session. `ForeignKey` creates a link to the
    # `id` column in the `debate_sessions` table. This ensures every turn belongs to a session.
    session_id = Column(Integer, ForeignKey("debate_sessions.id"), nullable=False)

    # The name of the character who is speaking in this turn.
    speaker = Column(String(128), nullable=False)  # canonical lowercase

    # The actual text content of the speaker's message.
    message = Column(Text, nullable=False, default="")

    # The file path to the generated audio for this turn's message.
    # It's `nullable=True` because audio might not be generated yet or might not be saved as a file.
    audio_path = Column(Text, nullable=True)       # not used when returning data: URIs

    # A timestamp for when this specific turn was created.
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # --- Relationships ---
    # This creates the other side of the relationship, linking a turn back to its parent session.
    # It lets you easily get the session object from a turn object (e.g., `my_turn.session`).
    session = relationship("DebateSession", back_populates="turns")
