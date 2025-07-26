from fastapi import FastAPI # Import the main FastAPI class.
from fastapi.middleware.cors import CORSMiddleware # Import middleware for handling Cross-Origin Resource Sharing.
from routers import auth, debate # Import the router objects from your routers module.
from core.database import Base, engine # Import the Base and engine from your database configuration.
from models import user, debate_models # Import your SQLAlchemy models to ensure they are known to the Base.
 
# This line creates all the database tables defined by your SQLAlchemy models (e.g., the User table).
# It checks if the tables exist before creating them, so it's safe to run every time the application starts.
Base.metadata.create_all(bind=engine)
 
# Create an instance of the FastAPI application.
app = FastAPI(title="DebateAI API")
 
# --- Middleware ---
# Add the CORS middleware to the application.
# This allows your frontend (e.g., a React app) to make requests to this backend.
app.add_middleware(
    CORSMiddleware,
    # SECURITY WARNING: allow_origins=["*"] is insecure for production.
    # For production, you should restrict this to your frontend's domain,
    # e.g., allow_origins=["https://your-frontend-domain.com"].
    allow_origins=["*"], # Defines which origins are allowed to make requests.
    allow_credentials=True, # Allows cookies to be included in requests.
    allow_methods=["*"], # Allows all HTTP methods (GET, POST, etc.).
    allow_headers=["*"], # Allows all request headers.
)
 
# --- Routers ---
# Include the routers in the main FastAPI app.
# This makes the endpoints defined in auth.py and debate.py available.
app.include_router(auth.router, prefix = "/auth", tags = ["Auth"])
app.include_router(debate.router, prefix = "/debate", tags = ["Debate"])
