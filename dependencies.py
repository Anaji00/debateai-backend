# This file contains shared dependencies used across different routers.

from core.database import SessionLocal
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException
from crud import user as crud_user

# Dependency function to get a database session for a request.
# This pattern ensures the database session is always closed after the request is finished.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from fastapi import Cookie
from models import User

def get_current_user(session_token: str = Cookie(None), db: Session = Depends(get_db)) -> User:
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = crud_user.get_user_by_session_token(db, token=session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user
