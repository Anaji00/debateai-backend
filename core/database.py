# core/database.py
# Central SQLAlchemy setup: engine, SessionLocal, Base
# All models across the app must import THIS Base.

import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base

# Use environment variable for DATABASE_URL; sqlite for local dev
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# For SQLite + multithreaded FastAPI, set check_same_thread=False
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# Create the SQLAlchemy engine
engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine, 
    future=True, 
    expire_on_commit=False,
)

# Base class for all models
Base = declarative_base()

# Optional: enable WAL & sane sync level in dev when using SQLite
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # WAL reduces writer blocks on readers; NORMAL is fine for dev durability
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()

# Dependency for FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
