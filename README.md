# DebateAI Backend

This is the backend for DebateAI, a FastAPI-based application that allows users to engage in text and voice debates with AI-powered characters. The application supports various debate formats, persists conversation history, and generates dynamic audio responses.

## Features

*   **User Authentication**: Secure user registration and login using JWT access tokens.
*   **Dynamic AI Personas**: A wide range of characters to debate with, from historical figures to pop-culture icons, each with a unique personality defined by detailed system prompts.
*   **Solo Debate Mode**: A user can have a one-on-one conversation with any available AI character.
*   **Versus Debate Mode**: Two AI characters debate each other on a given topic, with the ability for a user to inject comments to steer the conversation.
*   **Text-to-Speech (TTS)**: AI responses can be converted to voice using a high-quality voice cloning model (Coqui XTTS-v2).
*   **Database Integration**: Debate sessions and turns are saved to a SQLite database using SQLAlchemy ORM, allowing for persistent debate histories.
*   **Debate Management**: API endpoints to reset sessions, summarize debates, and modify or delete individual turns.

## Tech Stack

*   **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
*   **Database**: [SQLite](https://www.sqlite.org/index.html) with [SQLAlchemy](https://www.sqlalchemy.org/)
*   **Data Validation**: [Pydantic](https://docs.pydantic.dev/)
*   **Authentication**: [Passlib](https://passlib.readthedocs.io/en/stable/) for password hashing, [python-jose](https://python-jose.readthedocs.io/en/latest/) for JWT.
*   **AI Language Model**: [OpenAI API](https://openai.com/docs) (GPT-4o)
*   **Voice Synthesis**: [Coqui TTS](https://github.com/coqui-ai/TTS)
*   **Environment Variables**: [python-dotenv](https://github.com/theskumar/python-dotenv)

## Setup and Installation

Follow these steps to get the backend server running locally.

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd DebateAi/backend
```

### 2. Create and Activate a Virtual Environment

It's highly recommended to use a virtual environment to manage project dependencies.

```bash
# For Windows
python -m venv venv
.\venv\Scripts\activate

# For macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

Create a `requirements.txt` file with the following content:

```txt
fastapi
uvicorn[standard]
sqlalchemy
pydantic[email]
python-jose[cryptography]
passlib[bcrypt]
python-dotenv
openai
TTS
torch
torchaudio
```

Then, install the packages:

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a file named `.env` in the `backend` directory and add your API keys:

```
OPENAI_API_KEY="sk-..."
ELEVENLABS_API_KEY="sk-..."
```

### 5. Running the Application

Start the development server using Uvicorn:

```bash
uvicorn main:app --reload
```

The `--reload` flag automatically restarts the server when you make code changes. The API will be available at `http://127.0.0.1:8000`.

You can access the interactive API documentation (provided by Swagger UI) at `http://127.0.0.1:8000/docs`.