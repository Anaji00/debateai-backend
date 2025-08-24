"""
Main application file for the DebateAI API.
This file initializes the FastAPI application, configures middleware,
sets up database connections, and includes API routers.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routers.auth import router as auth_router
import os
 
from core.database import Base, engine
from models import User  # Importing User ensures its model is known to SQLAlchemy's Base
from routers import auth, debate
 
# This line creates all database tables defined by SQLAlchemy models that are
# subclasses of Base. It's safe for development but for production,
# a migration tool like Alembic is recommended.
Base.metadata.create_all(bind=engine)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


 
app = FastAPI(
    title="DebateAI API",
    description="API for managing user authentication and debate sessions.",
    version="1.0.0",
)

origins = [
    "http://localhost:5173",  # Vite frontend dev server
    "http://127.0.0.1:5173",  # sometimes needed
]
 
# Configure Cross-Origin Resource Sharing (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # The origin of your frontend app
    allow_credentials=True,  # Allow cookies to be sent with requests
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all request headers
)

# Mount static files for audio access
app.mount("/static", StaticFiles(directory="static"), name="static")
 
@app.get("/", tags=["Root"])
def read_root():
    """A simple health check endpoint to confirm the API is running."""
    return {"status": "ok", "message": "Welcome to the DebateAI API"}

# This is what activates the endpoints defined in auth.py
app.include_router(auth_router, prefix="/auth")
 
# Include API routers
app.include_router(debate.router, prefix="/debate", tags=["Debate"])
