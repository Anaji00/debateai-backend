# backend/main.py
"""
Main application file for the DebateAI API.
Sets up CORS for the React dev server, serves static files, wires routers,
and exposes a simple /healthz endpoint. Ready for dev streaming.
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# --- DB bootstrap (kept your pattern) ---
from core.database import Base, engine  # if your module is `database.py`, update import to match
from models import User  # ensure models import so SQLAlchemy registers
from routers import auth, debate

# Create tables in dev (migration tool recommended for prod)
Base.metadata.create_all(bind=engine)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(
    title="DebateAI API",
    description="API for managing user authentication and debate sessions.",
    version="1.0.0",
)

# Allow your Vite dev server origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated audio, docs, etc.
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(debate.router, prefix="/debate", tags=["debate"])

# Health for dev/proxy/lb checks
@app.get("/healthz")
async def healthz():
    return {"ok": True}
