# backend/schemas.py
# NOTE: Keeps your original class/field names for compatibility.
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Literal
from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict

# -------------------------
# Auth / User
# -------------------------
class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    username: str = Field(..., min_length=1)
    email: EmailStr

class UserCreate(UserBase):
    password: str = Field(..., min_length=6)

class User(UserBase):
    pass

class Token(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    access_token: str
    token_type: str = "bearer"

# -------------------------
# Primitives
# -------------------------
class HistoryItem(BaseModel):
    """One chat message in prior history."""
    model_config = ConfigDict(from_attributes=True)
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)

    @field_validator("content")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "").strip()

# -------------------------
# Versus (two speakers)
# -------------------------
class VersusStartRequest(BaseModel):
    """Start a NEW Versus session and stream first turn."""
    model_config = ConfigDict(from_attributes=True)
    c1: str = Field(..., min_length=1, description="Canonical lowercase name of character 1")
    c2: str = Field(..., min_length=1, description="Canonical lowercase name of character 2")
    topic: str = Field(..., min_length=1)
    history: Optional[List[HistoryItem]] = None

    @field_validator("c1", "c2", "topic")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "").strip()

class VersusInjectRequest(BaseModel):
    """Inject user message into existing Versus session and stream a reply."""
    model_config = ConfigDict(from_attributes=True)
    session_id: int
    user_inject: str = Field(..., min_length=1)
    addressed_to: Optional[List[str]] = Field(
        None,
        description="Optional list of canonical speaker ids to address; only used for inject."
    )

    @field_validator("user_inject")
    @classmethod
    def _trim_msg(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("addressed_to")
    @classmethod
    def _norm_list(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        return [(s or "").strip().lower() for s in v if (s or "").strip()]

# -------------------------
# Solo (one speaker)
# -------------------------
class SoloStartRequest(BaseModel):
    """Start a NEW Solo session (one character) and stream a single turn."""
    model_config = ConfigDict(from_attributes=True)
    character: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1)
    history: Optional[List[HistoryItem]] = None

    @field_validator("character", "topic")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "").strip()

class SoloInjectRequest(BaseModel):
    """Inject user message into existing Solo session and stream reply."""
    model_config = ConfigDict(from_attributes=True)
    session_id: int
    user_inject: str = Field(..., min_length=1)

    @field_validator("user_inject")
    @classmethod
    def _trim_msg(cls, v: str) -> str:
        return (v or "").strip()

# -------------------------
# Devil’s Advocate (one speaker against a thesis)
# -------------------------
class DevilStartRequest(BaseModel):
    """Start a NEW Devil’s Advocate session; streams a single turn."""
    model_config = ConfigDict(from_attributes=True)
    character: str = Field(..., min_length=1)
    thesis: str = Field(..., min_length=1)
    history: Optional[List[HistoryItem]] = None

    @field_validator("character", "thesis")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "").strip()

class DevilInjectRequest(BaseModel):
    """Inject user message into existing Devil’s Advocate session and stream reply."""
    model_config = ConfigDict(from_attributes=True)
    session_id: int
    user_inject: str = Field(..., min_length=1)

    @field_validator("user_inject")
    @classmethod
    def _trim_msg(cls, v: str) -> str:
        return (v or "").strip()

# -------------------------
# DTOs / Responses (generic)
# -------------------------
class TurnDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    turn_id: int
    session_id: int
    speaker: str
    message: str

class VoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    turn_id: int
    filename: Optional[str] = None
    audio_url: Optional[str] = None

class SessionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    topic: str
    character_1: Optional[str] = None
    character_2: Optional[str] = None
    created_at: datetime

class SummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    session_id: int
    summary: Dict[str, str]

class GradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    session_id: int
    grading: Dict[str, str]

# -------------------------
# ORM-backed Response Models (used by /debate/sessions)
# -------------------------
class DebateTurnResponse(BaseModel):
    """Mirror of models.debate_models.DebateTurn for response serialization."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: int
    speaker: str
    message: str
    audio_path: Optional[str] = None
    timestamp: datetime

class DebateSessionResponse(BaseModel):
    """Mirror of models.debate_models.DebateSession including nested turns."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    topic: str
    character_1: Optional[str] = None
    character_2: Optional[str] = None
    created_at: datetime
    turns: List[DebateTurnResponse] = Field(default_factory=list)
