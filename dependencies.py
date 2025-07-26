# This file contains shared dependencies used across different routers.

from core.database import SessionLocal

# Dependency function to get a database session for a request.
# This pattern ensures the database session is always closed after the request is finished.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()