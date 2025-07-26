# This file defines the Pydantic models (schemas) for data validation and serialization.
# These schemas define the shape of the data for API requests and responses.

from pydantic import BaseModel, EmailStr # Import BaseModel for creating schemas and EmailStr for email validation.
from datetime import datetime # Import datetime for handling timestamps.
from typing import Optional, List
# --- User Schemas ---

# Base schema for user attributes. This is inherited by other user-related schemas to avoid repetition.
class UserBase(BaseModel):
    username: str
    email: EmailStr # Using EmailStr provides automatic email format validation.

# Schema for creating a new user. It inherits from UserBase and adds the password field.
class UserCreate(UserBase):
    password: str

# Schema for reading/returning user data. It inherits from UserBase but does NOT include the password.
# This is crucial for security to avoid leaking password hashes in API responses.
class User(UserBase):
    class Config:
        orm_mode = True # This allows the Pydantic model to read data from SQLAlchemy ORM objects.

# --- Token Schemas ---
# Schema for the JWT access token response.
class Token(BaseModel):
    access_token: str
    token_type: str

# --- Debate Schemas ---

# Schema for the request body of the /solo endpoint.
class SoloDebateRequest(BaseModel):
    character: str
    user_input: str
    history: list
    with_voice: bool = False

# Schema for the request body of the /versus endpoint.
class VersusDebateRequest(BaseModel):
    c1: str
    c2: str
    topic: str
    user_inject: str = ""
    history: list = []
    session_id: Optional[int] = None


class DebateTurnBase(BaseModel):
    speaker: str
    message: str
    audio_path: Optional[str] = None
    timestamp: datetime

    class Config:
        orm_mode = True

class DebateSessionBase(BaseModel):
    id: int
    topic: str
    character_1: str
    character_2: str
    created_at: datetime
    turns: List[DebateTurnBase] = []

    class Config:
        orm_mode = True