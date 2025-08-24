# schemas.py
# ✅ Streaming-only Pydantic schemas for DebateAI (ChatGPT-style)
# - History is always a list of {role, content} items
# - Supports Versus, Solo, and Devil’s Advocate start/inject flows
# - Includes basic User/Token + response types
# - Pydantic v2 style config (ConfigDict)

# Import necessary types for defining the schemas.
from datetime import datetime
from typing import List, Optional, Dict

# Import the core components from Pydantic for creating schemas.
from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict


# ========================
# 🔐 User / Auth
# ========================

# This section defines schemas related to user accounts and authentication.

# Defines the basic fields for a user.
class UserBase(BaseModel):
    # This configuration allows the Pydantic model to read data from ORM objects (like SQLAlchemy models).
    model_config = ConfigDict(from_attributes=True)
    username: str
    # EmailStr is a special Pydantic type that validates the field is a valid email address.
    email: EmailStr

# Defines the fields needed to create a new user, inheriting from UserBase and adding a password.
class UserCreate(UserBase):
    password: str

# Defines the fields for a user that are safe to return from an API (no password).
class User(UserBase):
    pass

# Defines the structure of the authentication token response.
class Token(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    access_token: str
    token_type: str


# ========================
# 🧱 Common primitives
# ========================

# This schema represents a single message in a conversation history.
class HistoryItem(BaseModel):
    """
    Chat-style message used by all streaming endpoints.
    role: 'user' | 'assistant'
    content: message text
    """
    model_config = ConfigDict(from_attributes=True)

    # The role of the message sender, e.g., 'user' or 'assistant'.
    role: str
    # The text content of the message.
    content: str

    # This is a validator. It runs automatically when a HistoryItem is created.
    @field_validator("role")
    @classmethod
    def normalize_role(cls, v: str) -> str:
        # It cleans up the 'role' string and ensures it's one of the allowed values.
        v = (v or "").strip().lower()
        if v not in {"user", "assistant"}:
            raise ValueError("role must be 'user' or 'assistant'")
        return v

    @field_validator("content")
    @classmethod
    def ensure_content(cls, v: str) -> str:
        # This validator simply removes leading/trailing whitespace from the content.
        return (v or "").strip()


# ========================
# 🧠 Streaming Debate Requests
# ========================

# --- Versus (two speakers) ---

# Schema for a request to start a new 1-vs-1 debate.
class VersusStartRequest(BaseModel):
    """
    Start a NEW Versus session and stream first two turns (c1 then c2).
    """
    model_config = ConfigDict(from_attributes=True)

    c1: str   # canonical lowercase (e.g., "thanos")
    c2: str   # canonical lowercase (e.g., "donald trump")
    topic: str
    # The debate can optionally start with a pre-existing conversation history.
    history: Optional[List[HistoryItem]] = None

    # This validator applies to the 'c1', 'c2', and 'topic' fields.
    @field_validator("c1", "c2", "topic")
    @classmethod
    def trim(cls, v: str) -> str:
        # It removes any leading/trailing whitespace.
        return (v or "").strip()

# Schema for a request to inject a user's message into an ongoing 1-vs-1 debate.
class VersusInjectRequest(BaseModel):
    """
    Inject a user message into an existing Versus session and stream both replies.
    """
    model_config = ConfigDict(from_attributes=True)

    # The ID of the session to add the message to.
    session_id: int
    # The user's new message.
    user_inject: str
    addressed_to: Optional[List[str]] = None  # canonical ids (optional)

    @field_validator("user_inject")
    @classmethod
    def trim_text(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("addressed_to")
    @classmethod
    def norm_list(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        # This cleans up a list of strings, making them lowercase and removing whitespace.
        if v is None:
            return None
        return [ (s or "").strip().lower() for s in v if (s or "").strip() ]


# --- Solo (one speaker) ---

# Schema for a request to start a new debate against a single AI character.
class SoloStartRequest(BaseModel):
    """
    Start a NEW Solo session with one character; streams a single turn.
    """
    model_config = ConfigDict(from_attributes=True)

    character: str                  # canonical lowercase
    topic: str
    history: Optional[List[HistoryItem]] = None

    @field_validator("character", "topic")
    @classmethod
    def trim_text(cls, v: str) -> str:
        return (v or "").strip()

# Schema for injecting a user message into an ongoing solo debate.
class SoloInjectRequest(BaseModel):
    """
    Inject a user message into an existing Solo session and stream one reply.
    """
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    user_inject: str

    @field_validator("user_inject")
    @classmethod
    def trim_text(cls, v: str) -> str:
        return (v or "").strip()


# --- Devil's Advocate (one speaker challenges user's thesis) ---

# Schema to start a new "Devil's Advocate" debate, where the AI challenges the user's statement.
class DevilStartRequest(BaseModel):
    """
    Start a NEW Devil’s Advocate session; one character challenges the thesis.
    """
    model_config = ConfigDict(from_attributes=True)

    character: str                  # canonical lowercase
    # The user's initial statement or argument that the AI will challenge.
    thesis: str
    history: Optional[List[HistoryItem]] = None

    @field_validator("character", "thesis")
    @classmethod
    def trim_text(cls, v: str) -> str:
        return (v or "").strip()

# Schema to inject a user's reply into an ongoing "Devil's Advocate" debate.
class DevilInjectRequest(BaseModel):
    """
    Inject a user message into an existing Devil’s Advocate session and stream one reply.
    """
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    user_inject: str

    @field_validator("user_inject")
    @classmethod
    def trim_text(cls, v: str) -> str:
        return (v or "").strip()


# ========================
# 🧾 Response Schemas
# ========================

# This section defines schemas for the data that our API sends back to the client.

# Schema for a single turn within a debate.
class DebateTurnSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    speaker: str
    message: str
    # The path to the audio file is optional, as it might not be generated yet.
    audio_path: Optional[str] = None
    timestamp: datetime
    session_id: Optional[int] = None

# Schema for a complete debate session, including its metadata and all turns.
class DebateSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic: str
    # Characters are optional, useful for different debate modes.
    character_1: Optional[str] = None
    character_2: Optional[str] = None
    created_at: datetime
    # A session contains a list of turns, each matching the DebateTurnSchema.
    turns: List[DebateTurnSchema]

# Schema for the response from the text-to-speech endpoint.
class VoiceResponse(BaseModel):
    """
    Used by /voice/{turn_id} endpoint when returning a data URL.
    """
    model_config = ConfigDict(from_attributes=True)

    # The ID of the turn for which audio was generated.
    turn_id: int
    # The URL where the client can fetch the audio file.
    audio_url: str
