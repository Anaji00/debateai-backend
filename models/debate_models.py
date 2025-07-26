# This file defines the SQLAlchemy models for storing debate sessions and turns.

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from core.database import Base

# Defines the 'debate_sessions' table in the database.
class DebateSession(Base):
    __tablename__ = "debate_sessions"

    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String, nullable=False)
    character_1 = Column(String, nullable=False)
    character_2 = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime)

    # Establishes a one-to-many relationship with DebateTurn.
    # 'cascade="all, delete-orphan"' ensures that when a session is deleted, all its turns are also deleted.
    turns = relationship("DebateTurn", back_populates="session", cascade="all, delete-orphan")

# Defines the 'debate_turns' table in the database.
class DebateTurn(Base):
    __tablename__ = "debate_turns"

    id = Column(Integer, primary_key=True, index=True)
    speaker = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    audio_path = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime)

    # Defines the foreign key relationship back to the debate_sessions table.
    session_id = Column(Integer, ForeignKey("debate_sessions.id"))
    session = relationship("DebateSession", back_populates="turns")