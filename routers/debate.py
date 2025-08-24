# coding from scratch lets run it 

# Import necessary libraries and modules.
# openai for interacting with the OpenAI API asynchronously.
from openai import AsyncOpenAI # Imports the asynchronous client for OpenAI API.
# asyncio for asynchronous programming, os for file system operations, json for data serialization.
import asyncio, os, json # Imports standard libraries for async, OS interaction, and JSON.
# datetime for timestamping.
from datetime import datetime # Imports the datetime class for working with dates and times.
# typing for type hints like List and Optional.
from typing import List, Optional # Imports types for creating clear function signatures.
# FastAPI components for building the API.
from fastapi import ( # Imports core FastAPI classes for creating API endpoints.
    APIRouter, Depends, UploadFile, File, Form, Query,
    FastAPI, status, Body, HTTPException
)
# StreamingResponse for sending server-sent events.
from fastapi.responses import StreamingResponse # Used to stream data to the client.
# SQLAlchemy components for database interaction.
from sqlalchemy.orm import Session # Manages database sessions.
from sqlalchemy import or_ # Allows for OR conditions in database queries.

# Local dependencies for the application.
# get_db for database session management.
from dependencies import get_db # A function that provides a database session to endpoints.
# schemas for data validation (Pydantic models).
import schemas # Imports Pydantic models that define the shape of API data.
# Database models for debate sessions and turns.
from models.debate_models import DebateSession, DebateTurn # Imports SQLAlchemy models for database tables.
# Custom services for specific functionalities.
# synthesize for text-to-speech conversion.
from services.voice_engine import synthesize, STATIC_DIR # Imports the text-to-speech function.
# to_alias and to_canonical for mapping character names.
from services.name_map import to_alias, to_canonical # Imports functions for name mapping.
# get_openai_async_client for getting a configured OpenAI client.
from utils.config import get_openai_async_client # Imports a helper to get the OpenAI client.
# Path for handling file system paths.
from pathlib import Path # Provides an object-oriented way to handle filesystem paths.
# DebateEngine for generating debate prompts.
from services.debate_engine import DebateEngine # Imports the main logic for debate generation.

# In memory RAG
# These functions manage a temporary document store for the duration of a debate session.
from services.rag_store import ( # Imports functions for Retrieval-Augmented Generation.
    add_doc as rag_add,
    delete_all_for_owner as rag_delete,
    list_docs as rag_list,
    query as rag_query,
    start_sweeper as rag_start_sweeper,
    touch_session as rag_touch
)
# Defines a function to generate a tactical line for the RAG model.
def _rag_tactic_line(mode: str, cite_style: str) -> str:
    """
    Build a one-liner that tells the model HOW to use the uploaded excerpts,
    tailored by the adaptive mode and the persona's cite_style.
    """
    # Syntax: `(variable or default_value)` provides a fallback if the variable is None or empty.
    cite_style = (cite_style or "none").lower() # Normalize cite_style to lowercase.
    mode = (mode or "persona_paraphrase").lower() # Normalize mode to lowercase.

    # Syntax: `if/elif/else` block to choose the right tactic based on mode and style.
    if mode == "evidence_cite": # Check if the mode is to cite evidence.
        if cite_style == "brand": # Check if the citation style is 'brand'.
            # brand: name-drop outlets/authors in-character, never brackets
            # Returns a specific instruction for the language model.
            return ("Lean on the strongest lines from the excerpts and casually name-drop outlets or authors "
                    "(e.g., 'even the Journal says…'); no brackets.")
        elif cite_style == "inline": # Check if the citation style is 'inline'.
            # inline: short quotes or attributions woven into prose, no formatting
            return ("Pull short phrases and attribute inline in prose (e.g., 'as the Journal reported'); "
                    "keep it natural, no brackets.")
        elif cite_style == "brackets": # Check if the citation style is 'brackets'.
            # (not in your map now, but safe to support later)
            return ("Quote short phrases and add bracket references like [Title ▸ chunk N] when it helps.")
        else:  # none # Fallback for any other citation style.
            return ("Paraphrase the strongest claims from the excerpts with confident language; no explicit attribution.")
    elif mode == "weaponize_spin": # Check if the mode is to spin contradictory evidence.
        return ("If the excerpts cut against you, spin them: reframe their meaning, question credibility or bias, "
                "cherry-pick favorable bits, or pivot to your opponent’s record—stay aggressive and on topic.")
    else:  # persona_paraphrase # Default mode is to paraphrase naturally.
        return ("Paraphrase and fold the material into your worldview naturally; keep it in-character and on topic.")

# Create an APIRouter instance. This helps in organizing endpoints into separate files.
router = APIRouter() # Creates a router object to group related API endpoints.

# Initialize the OpenAI async client using a helper function.
llm = get_openai_async_client() # Gets an instance of the async OpenAI client.
engine = DebateEngine(llm) # Creates an instance of our custom DebateEngine.
# Helpers for later

# Defines a helper function to format a dictionary as a JSONL string (JSON line).
def _jsonl(obj: dict) -> str:
    # `json.dumps` serializes a Python dictionary to a JSON formatted string.
    return json.dumps(obj, ensure_ascii=False) + "\n"

# Defines a helper to set headers for disabling buffering in streaming responses.
def _no_buffer_headers(resp: StreamingResponse):
    # This is useful for server-sent events to ensure data is sent immediately.
    resp.headers["Cache-Control"] = "no-cache, no-transform"
    resp.headers["X-Accel-Buffering"] = "no"

# Defines a helper to create a safe filename by cleaning a string.
def safe_filename(base: str) -> str:
    # It strips whitespace, replaces spaces with underscores, and converts to lowercase.
    return (base or "").strip().replace(" ", "_").lower()

# Defines a helper to convert a filesystem path to a web-accessible URL.
def fs_to_web(fs_path: str) -> str:
    # `Path` from `pathlib` makes path manipulation easier and cross-platform.
    p = Path(fs_path).resolve() # Get the absolute path.
    static_root = Path(STATIC_DIR).resolve() # Get the absolute path of the static directory.
    try:
        # Try to get the path relative to the static directory.
        rel = p.relative_to(static_root)
        # Format it as a URL. `.as_posix()` ensures forward slashes.
        return f"/static/{rel.as_posix()}"
    except Exception:
        # If it's not in the static directory, return the raw path.
        return p.as_posix()

# Defines a function to insert a user's turn into the database.
def _insert_user_turn(db: Session, session_id: int, text: str):
    if not (text or "").strip():
        return None
    t = DebateTurn(
        speaker="User",
        message=text.strip(),
        audio_path=None,
        session_id=session_id,
        timestamp=datetime.utcnow(),
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


# Rag endpoint POST

@router.post("/docs/upload", status_code=status.HTTP_200_OK)
async def upload_doc(
    session_id: int = Form(...),
    owner: str = Form("shared"),
    title: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    owner = to_canonical(owner or "shared")
    content = await file.read()
    info = rag_add(session_id, owner=owner, filename=file.filename, file_bytes=content, title=title)
    rag_touch(session_id)
    return {"ok": True, "doc": info}

# Rag endpoint GET

@router.get("/docs/list", status_code=status.HTTP_200_OK)
async def list_docs(session_id: int = Query(...)):
    docs = rag_list(session_id)
    rag_touch(session_id)
    return {"ok": True, "docs": docs}

# Rag endpoint DELETE
@router.delete("/docs/owner/{session_id}/{owner}", status_code=status.HTTP_200_OK)
async def delete_docs(session_id: int, owner: str):
    rag_delete(session_id, to_canonical(owner))
    rag_touch(session_id)
    return {"ok": True}


# Solo endpoint vs character, post
@router.post("/solo/stream-start", status_code=status.HTTP_200_OK)
async def solo_stream_start(req: schemas.SoloStartRequest, db: Session = Depends(get_db)):
    """
    Solo start: creates a session, emits session event, then 1 streamed turn from the character.
    """
    try:
        character = to_canonical(req.character)
        topic = (req.topic or "").strip()

        # Build history (seed the topic as a user msg if none exists)
        history = [{"role": h.role, "content": h.content} for h in (req.history or [])]
        if topic and not any(h["role"] == "user" for h in history):
            history.append({"role": "user", "content": topic})

        session = DebateSession(topic=topic, character_1=character, character_2=None)
        db.add(session); db.commit(); db.refresh(session)
        rag_touch(session.id)

        if topic:
            _insert_user_turn(db, session.id, topic)
        async def stream():
            # tell client the session id
            yield _jsonl({"type": "session", "session_id": session.id})

            # DB turn row
            turn = DebateTurn(
                speaker=character, message="", audio_path=None,
                session_id=session.id, timestamp=datetime.utcnow()
            )
            db.add(turn); db.commit(); db.refresh(turn)

            yield _jsonl({"type": "turn", "turn_id": turn.id, "speaker": character})

            # --- RAG (global visibility in solo) ---
            qtext = history[-1]["content"] if (history and history[-1]["role"] == "user") else (topic or "")
            sources = rag_query(session.id, query_text=qtext, allowed_owners=[], k=4)
            if sources:
                yield _jsonl({"type":"sources","turn_id":turn.id,"speaker":character,"items":sources})

            messages = engine.generate_solo_debate(character, history)

            if sources:
                blob = "\n\n".join(
                    f"[{s['title']} ▸ chunk {s['chunk_index']}]\n{s['snippet']}"
                    for s in sources
                )
                profile = engine.rag_profile_for(character)
                decision = await engine.decide_rag_mode(
                    current_speaker=character,
                    topic=topic or qtext,
                    history=history,
                    sources=sources,
                    default_mode=profile["mode"],
                    cite_style=profile["cite_style"],
                )
                mode = decision["mode"]
                cite_style = decision["cite_style"]
                tactic_line = _rag_tactic_line(mode, cite_style)

                messages.append({
                    "role": "system",
                    "content": "Uploaded excerpts:\n\n" + blob + "\n\nGuidance: " + tactic_line
                })


            reply_acc: List[str] = []
            try:
                s = await engine.async_client.chat.completions.create(
                    model="gpt-4o-mini", messages=messages,
                    temperature=0.9, stream=True, max_tokens=600)
                async for chunk in s:
                    token = getattr(chunk.choices[0].delta, "content", None)
                    if not token: continue
                    reply_acc.append(token)
                    for ch in token:
                        yield _jsonl({"type":"delta","turn_id":turn.id,"speaker":character,"delta":ch})
                        await asyncio.sleep(0)
            except Exception as e:
                yield _jsonl({"type":"error","message":f"Error for {character}: {e}"})

            final_text = "".join(reply_acc).strip()
            turn.message = final_text; db.commit()
            yield _jsonl({"type":"endturn","turn_id":turn.id,"speaker":character})

        resp = StreamingResponse(stream(), media_type="text/plain; charset=utf-8")
        _no_buffer_headers(resp); return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/solo/stream-inject", status_code=status.HTTP_200_OK)
async def solo_stream_inject(req: schemas.SoloInjectRequest, db: Session = Depends(get_db)):
    """
    Solo inject: append user's new message to history and stream 1 rebuttal from the character.
    """
    try:
        session = db.query(DebateSession).filter(DebateSession.id == req.session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        character = to_canonical(session.character_1 or "assistant")
        user_text = (req.user_inject or "").strip()

        # rebuild minimal history from turns + this inject
        turns = (
            db.query(DebateTurn)
            .filter(DebateTurn.session_id == session.id)
            .order_by(DebateTurn.timestamp.asc()).all()
        )
        history: List[dict] = [{"role":"assistant","content":t.message}
                               for t in turns if (t.message or "").strip()]
        if user_text:
            history.append({"role":"user","content":user_text})
        rag_touch(session.id)
# inside solo_stream_inject.stream(), BEFORE creating the assistant DebateTurn
        if user_text:
            _insert_user_turn(db, session.id, user_text)


        async def stream():
            turn = DebateTurn(
                speaker=character, message="", audio_path=None,
                session_id=session.id, timestamp=datetime.utcnow()
            )
            db.add(turn); db.commit(); db.refresh(turn)
            yield _jsonl({"type":"turn","turn_id":turn.id,"speaker":character})

            # --- RAG ---
            qtext = user_text or session.topic or ""
            sources = rag_query(session.id, query_text=qtext, allowed_owners=[], k=4)
            if sources:
                yield _jsonl({"type":"sources","turn_id":turn.id,"speaker":character,"items":sources})

            messages = engine.generate_solo_debate(character, history)

            if sources:
                blob = "\n\n".join(
                    f"[{s['title']} ▸ chunk {s['chunk_index']}]\n{s['snippet']}"
                    for s in sources
                )
                profile = engine.rag_profile_for(character)
                decision = await engine.decide_rag_mode(
                    current_speaker=character,
                    topic=session.topic or qtext,
                    history=history,
                    sources=sources,
                    default_mode=profile["mode"],
                    cite_style=profile["cite_style"],
                )
                mode = decision["mode"]
                cite_style = decision["cite_style"]
                tactic_line = _rag_tactic_line(mode, cite_style)

                messages.append({
                    "role": "system",
                    "content": "Uploaded excerpts:\n\n" + blob + "\n\nGuidance: " + tactic_line
                })

            reply_acc: List[str] = []
            try:
                s = await engine.async_client.chat.completions.create(
                    model="gpt-4o-mini", messages=messages,
                    temperature=0.9, stream=True, max_tokens=600)
                async for chunk in s:
                    token = getattr(chunk.choices[0].delta, "content", None)
                    if not token: continue
                    reply_acc.append(token)
                    for ch in token:
                        yield _jsonl({"type":"delta","turn_id":turn.id,"speaker":character,"delta":ch})
                        await asyncio.sleep(0)
            except Exception as e:
                yield _jsonl({"type":"error","message":f"Error for {character}: {e}"})

            final_text = "".join(reply_acc).strip()
            turn.message = final_text; db.commit()
            yield _jsonl({"type":"endturn","turn_id":turn.id,"speaker":character})

        resp = StreamingResponse(stream(), media_type="text/plain; charset=utf-8")
        _no_buffer_headers(resp); return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Versus Endpoint
@router.post("/versus", status_code=status.HTTP_200_OK)
async def versus_debate(request: schemas.VersusStartRequest, db: Session = Depends(get_db)):
    try:
        new_session = False
        if request.session_id is not None:
            session = db.query(DebateSession).filter_by(id=request.session_id).first()
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
            if not (request.topic and request.c1 and request.c2):
                raise HTTPException(status_code=400, detail="Missing required fields")
            session = DebateSession(
                topic = request.topic.strip(),
                character_1 = to_canonical(request.c1),
                character_2 = to_canonical(request.c2)
            )
            db.add(session); db.commit(); db.refresh(session)
            new_session = True
        rag_touch(session.id)

        topic = (request.topic or session.topic or "").strip()
        c1 = to_canonical(request.c1 or session.character_1)
        c2 = to_canonical(request.c2 or session.character_2)

        # Normalize History

        raw_hist = list(request.history or [])
        history: List[dict] = []
        for item in raw_hist:
            if isinstance(item, dict):
                role = (item.get("role") or "assistant").strip().lower()
                content = (item.get("content") or "").strip()
                if role in {"user", "assistant"} and content:
                    history.append({"role": role, "content": content})

        # User inject 
        inject = (request.user_inject or "").strip()
        if inject:
            if not history or history[-1]["role"] != "user" or history[-1]["content"] != inject:
                history.append({"role": "user", "content": inject})

        # WHO SPEAKING?????
        turn_count = db.query(DebateTurn).filter_by(session_id=session.id).count()
        speaker, opponent = (c1, c2) if (turn_count % 2 == 0) else (c2, c1)

        async def debate_stream():
            if new_session:
                yield _jsonl({"type": "session", "session_id": session.id})
            if new_session and topic:
                _insert_user_turn(db, session.id, topic)
            if inject:
                _insert_user_turn(db, session.id, inject)


            spk = to_canonical(speaker)
            opp = to_canonical(opponent)

            # DB TURN ROW

            turn = DebateTurn(
                speaker = spk,
                message = "",
                audio_path = None,
                session_id = session.id,
                timestamp = datetime.utcnow()
            )
            db.add(turn); db.commit(); db.refresh(turn)

            yield _jsonl({"type": "turn", "turn_id": turn.id, "speaker": spk})

            # RAG, prefer last message, else fall back to topic + last assitant
            if history and history[-1]["role"] == "user":
                qtext = history[-1]["content"]
            else:
                last_assist = next((h["content"] for h in reversed(history) if h["role"] == "assistant"), "")
                qtext = f"{topic}\n\n{last_assist}"
            
            sources = rag_query(session.id, query_text=qtext, allowed_owners=[spk, "shared"], k = 4)
            if sources:
                yield _jsonl({"type": "sources", "turn_id": turn.id, "speaker": spk, "items": sources})

            messages = engine.generate_versus_debate(speaker, opponent, topic, history, last_speaker = None)
            if sources:
                blob = "\n\n".join(
                    f"[{s['title']} ▸ chunk {s['chunk_index']}]\n{s['snippet']}"
                    for s in sources
                )
                profile = engine.rag_profile_for(spk)
                decision = await engine.decide_rag_mode(
                    current_speaker=spk,
                    topic=topic,
                    history=history,
                    sources=sources,
                    default_mode=profile["mode"],
                    cite_style=profile["cite_style"],
                )
                mode = decision["mode"]
                cite_style = decision["cite_style"]
                tactic_line = _rag_tactic_line(mode, cite_style)
                
                messages.append({"role": "system", "content": (
                    "Uploaded excerpts for this turn (treat as context; stay on the core debate topic):\n\n"
                    + blob +
                    "\n\nGuidance: " + tactic_line
                )
                })



            STOP_TOKENS = [f"\n{opp.title()}:", "\nYou:", "\nUSER:", "\nAudience:", f"\n{spk.title()}:"]


            reply_acc: List[str] = []
            try:
                s = await engine.async_client.chat.completions.create(
                    model = "gpt-4o-mini",
                    messages = messages,
                    stream = True,
                    temperature = 0.9,
                    max_tokens = 500,
                    stop = STOP_TOKENS
                )
                async for chunk in s:
                    delta = chunk.choices[0].delta
                    token = getattr(delta, "content", None)
                    if not token:
                        continue
                    reply_acc.append(token)
                    for ch in token:
                        yield _jsonl({"type": "delta", "turn_id": turn.id, "speaker": spk, "delta": ch})
                        await asyncio.sleep(0)
            except Exception as e:
                yield _jsonl({"type": "error", "message": f"Error generating response for {spk}: {e}"})
            
            final_text = "".join(reply_acc).strip()
            turn.message = final_text
            db.commit()

            yield _jsonl({"type": "endturn", "turn_id": turn.id, "speaker": spk})

        resp = StreamingResponse(debate_stream(), media_type="text/plain; charset = utf-8")
        _no_buffer_headers(resp)
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# routes/debate.py (add this route)

@router.post("/devils-advocate/stream-start", status_code=status.HTTP_200_OK)
async def da_stream_start(req: schemas.DevilStartRequest, db: Session = Depends(get_db)):
    """
    Start a Devil’s Advocate session:
    - Creates a session with character_1 = Debate Assistant
    - Seeds the thesis as the first user message if needed
    - Streams one DA rebuttal using adaptive RAG (cite vs spin vs paraphrase)
    """
    try:
        character = to_canonical("Debate Assistant")  # must match your prompt key
        thesis = (req.thesis or "").strip()

        # Build history (seed thesis as a user msg if none exists)
        history = [{"role": h.role, "content": h.content} for h in (req.history or [])]
        if thesis and not any(h["role"] == "user" for h in history):
            history.append({"role": "user", "content": thesis})
        
        

        # Create session so the client can upload docs under this id
        session = DebateSession(topic=thesis, character_1=character, character_2=None)
        db.add(session); db.commit(); db.refresh(session)
        rag_touch(session.id)

        # inside da_stream_start.stream(), BEFORE creating the assistant DebateTurn
        if thesis:
            _insert_user_turn(db, session.id, thesis)


        async def stream():
            # tell client the session id
            yield _jsonl({"type": "session", "session_id": session.id})

            # DB turn row
            turn = DebateTurn(
                speaker=character, message="", audio_path=None,
                session_id=session.id, timestamp=datetime.utcnow()
            )
            db.add(turn); db.commit(); db.refresh(turn)

            yield _jsonl({"type": "turn", "turn_id": turn.id, "speaker": character})

            # --- RAG (global visibility for DA) ---
            qtext = history[-1]["content"] if (history and history[-1]["role"] == "user") else thesis
            sources = rag_query(session.id, query_text=qtext or thesis, allowed_owners=[], k=4)
            if sources:
                yield _jsonl({"type":"sources","turn_id":turn.id,"speaker":character,"items":sources})

            # Base DA messages (your DA persona prompt)
            messages = engine.create_assistant_debate_messages(history=history, context="")

            # Adaptive RAG: decide cite vs spin vs paraphrase and inject guidance
            if sources:
                blob = "\n\n".join(
                    f"[{s['title']} ▸ chunk {s['chunk_index']}]\n{s['snippet']}"
                    for s in sources
                )
                profile = engine.rag_profile_for(character)  # should resolve to Debate Assistant
                decision = await engine.decide_rag_mode(
                    current_speaker=character,
                    topic=thesis or qtext,
                    history=history,
                    sources=sources,
                    default_mode=profile["mode"],
                    cite_style=profile["cite_style"],
                )
                mode = decision["mode"]
                cite_style = decision["cite_style"]
                tactic_line = _rag_tactic_line(mode, cite_style)

                messages.append({
                    "role": "system",
                    "content": "Uploaded excerpts:\n\n" + blob + "\n\nGuidance: " + tactic_line
                })

            # ---- Stream LLM ----
            reply_acc: List[str] = []
            try:
                s = await engine.async_client.chat.completions.create(
                    model="gpt-4o-mini", messages=messages,
                    temperature=0.9, stream=True, max_tokens=600
                )
                async for chunk in s:
                    token = getattr(chunk.choices[0].delta, "content", None)
                    if not token: 
                        continue
                    reply_acc.append(token)
                    for ch in token:
                        yield _jsonl({"type":"delta","turn_id":turn.id,"speaker":character,"delta":ch})
                        await asyncio.sleep(0)
            except Exception as e:
                yield _jsonl({"type":"error","message":f"Error for {character}: {e}"})

            final_text = "".join(reply_acc).strip()
            turn.message = final_text; db.commit()
            yield _jsonl({"type":"endturn","turn_id":turn.id,"speaker":character})

        resp = StreamingResponse(stream(), media_type="text/plain; charset=utf-8")
        _no_buffer_headers(resp)
        return resp

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devils-advocate/stream-inject", status_code=status.HTTP_200_OK)
async def da_stream_inject(req: schemas.DevilInjectRequest, db: Session = Depends(get_db)):
    """
    Devil’s Advocate inject: append user reply as context and stream 1 DA rebuttal.
    """
    try:
        session = db.query(DebateSession).filter(DebateSession.id == req.session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        character = to_canonical("Debate Assistant")
        user_text = (req.user_inject or "").strip()
        # inside da_stream_start.stream(), BEFORE creating the assistant DebateTurn
        if user_text:
            _insert_user_turn(db, session.id, user_text)


        turns = (
            db.query(DebateTurn)
            .filter(DebateTurn.session_id == session.id)
            .order_by(DebateTurn.timestamp.asc()).all()
        )
        history: List[dict] = [{"role":"assistant","content":t.message}
                               for t in turns if (t.message or "").strip()]
        if user_text:
            history.append({"role":"user","content":user_text})
        rag_touch(session.id)

        async def stream():
            turn = DebateTurn(
                speaker=character, message="", audio_path=None,
                session_id=session.id, timestamp=datetime.utcnow()
            )
            db.add(turn); db.commit(); db.refresh(turn)
            yield _jsonl({"type":"turn","turn_id":turn.id,"speaker":character})

            # --- RAG (global) ---
            qtext = user_text or session.topic or ""
            sources = rag_query(session.id, query_text=qtext, allowed_owners=[], k=4)
            if sources:
                yield _jsonl({"type":"sources","turn_id":turn.id,"speaker":character,"items":sources})

            messages = engine.create_assistant_debate_messages(history=history, context="")


            if sources:
                blob = "\n\n".join(
                    f"[{s['title']} ▸ chunk {s['chunk_index']}]\n{s['snippet']}"
                    for s in sources
                )
                profile = engine.rag_profile_for(character)   # character == "debate assistant" canon
                decision = await engine.decide_rag_mode(
                    current_speaker=character,
                    topic=session.topic or qtext,
                    history=history,
                    sources=sources,
                    default_mode=profile["mode"],
                    cite_style=profile["cite_style"],
                )
                mode = decision["mode"]
                cite_style = decision["cite_style"]
                tactic_line = _rag_tactic_line(mode, cite_style)

                messages.append({
                    "role": "system",
                    "content": "Uploaded excerpts:\n\n" + blob + "\n\nGuidance: " + tactic_line
                })

            reply_acc: List[str] = []
            try:
                s = await engine.async_client.chat.completions.create(
                    model="gpt-4o-mini", messages=messages,
                    temperature=0.9, stream=True, max_tokens=600)
                async for chunk in s:
                    token = getattr(chunk.choices[0].delta, "content", None)
                    if not token: continue
                    reply_acc.append(token)
                    for ch in token:
                        yield _jsonl({"type":"delta","turn_id":turn.id,"speaker":character,"delta":ch})
                        await asyncio.sleep(0)
            except Exception as e:
                yield _jsonl({"type":"error","message":f"Error for {character}: {e}"})

            final_text = "".join(reply_acc).strip()
            turn.message = final_text; db.commit()
            yield _jsonl({"type":"endturn","turn_id":turn.id,"speaker":character})

        resp = StreamingResponse(stream(), media_type="text/plain; charset=utf-8")
        _no_buffer_headers(resp); return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =========================================================
# VOICE (on-demand TTS for a saved turn)
# =========================================================

@router.post("/voice/{turn_id}", status_code=status.HTTP_200_OK)
async def generate_voice(turn_id: int, db: Session = Depends(get_db)):
    """
    Generate audio for a specific saved turn.
    Maps stored canonical speaker -> alias for ElevenLabs.
    """
    turn = db.query(DebateTurn).filter_by(id=turn_id).first()
    if not turn:
        raise HTTPException(status_code=404, detail="Turn not found")

    if turn.audio_path and os.path.exists(turn.audio_path):
        return {"audio_url": f"/static/audio/generated/{os.path.basename(turn.audio_path)}"}

    alias = to_alias(turn.speaker)
    filename = f"{safe_filename(alias)}_{turn_id}.wav"
    fs_path = await synthesize(turn.message, alias, filename)
    if not fs_path:
        raise HTTPException(status_code=500, detail="TTS failed")

    turn.audio_path = fs_path
    db.commit()
    return {"audio_url": fs_to_web(fs_path)}

# =========================================================
# Sessions + maintenance
# =========================================================

@router.get("/sessions", response_model=List[schemas.DebateSessionResponse], status_code=status.HTTP_200_OK)
def get_all_sessions(db: Session = Depends(get_db)):
    try:
        sessions = db.query(DebateSession).all()
        for session in sessions:
            session.turns = (
                db.query(DebateTurn)
                .filter(DebateTurn.session_id == session.id)
                .order_by(DebateTurn.timestamp)
                .all()
            )
        return sessions
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve sessions: {str(e)}")

@router.delete("/reset", status_code=status.HTTP_200_OK)
def reset_debate_session(
    session_id: Optional[int] = None,
    topic: Optional[str] = None,
    c1: Optional[str] = None,
    c2: Optional[str] = None,
    db: Session = Depends(get_db)
):
    session_to_delete = None
    if session_id:
        session_to_delete = db.query(DebateSession).filter(DebateSession.id == session_id).first()
    elif topic and c1 and c2:
        session_to_delete = db.query(DebateSession).filter(
            DebateSession.topic == topic,
            or_(
                (DebateSession.character_1 == to_canonical(c1)) & (DebateSession.character_2 == to_canonical(c2)),
                (DebateSession.character_1 == to_canonical(c2)) & (DebateSession.character_2 == to_canonical(c1)),
            )
        ).first()
    else:
        raise HTTPException(status_code=400, detail="Either 'session_id' or all of 'topic', 'c1', and 'c2' must be provided.")

    if not session_to_delete:
        raise HTTPException(status_code=404, detail="Session not found")

    db.delete(session_to_delete)
    db.commit()
    return {"message": "Session deleted successfully"}

# =========================================================

from typing import Dict
# Summary
@router.post("/summary", status_code=status.HTTP_200_OK)
async def summarize(
    payload: Dict = Body(..., embed=True),
    db: Session = Depends(get_db),

):
    session_id = int(payload.get("session_id", 0))
    style = (payload.get("style") or "concise").lower()
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    
    session = db.query(DebateSession).filter_by(id=session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")



    turns = (
        db.query(DebateTurn)
        .filter(DebateTurn.session_id == session.id)
        .order_by(DebateTurn.timestamp.asc())
        .all()
    
    )
    if not turns:
        return {"ok": True, "session_id": session.id, "summary": {"topic": session.topic, "note": "No turns yet"}}
    
    p1 = to_canonical(session.character_1 or "assistant")
    p2 = to_canonical(session.character_2) if session.character_2 else "User"

    transcript = "\n".join(
        f"{(t.speaker or 'Unkown')}: {(t.message or'').strip()}"
        for t in turns if (t.message or "").strip()
    )

    json_schema_hint = {
        "topic": session.topic,
        "participants": [p for p in [p1, p2] if p],
        "by_participant": {
            p1: {"position": "", "key_points": []},
            p2: {"position": "", "key_points": []},
        },
        "neutral_summary": "",
        "strongest_moments": { p1: [], p2: []},
        "weaknessess": { p1: [], p2: []},
        "open_questions": [],
    }
    messages = [
        {
        "role": "system",
        "content": (
            "You are an impartial debate judge and summarizer. "
            "Summarize only from the transcript. Do not add external facts. "
            "Capture positions, key points, best moments, weaknesses, and open questions. Do not use moral judgement when summarizing."
            "Return a single JSON object matching the provided keys exactly."
            ),
        },
        {
            "role": "user",
            "content": (
                f"STYLE: {style}\n\n"
                f"TOPIC: {session.topic}\n\n"
                f"PARTICIPANTS: {p1} vs {p2}\n\n"
                f"TRANSCRIPT:\n" + transcript + "\n\n"
                "OUTPUT_JSON_TEMPLATE:\n" + json.dumps(json_schema_hint, ensure_ascii=False)
                
                ),
            },
    ]
    try:
        res = await engine.async_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
            stream=False,
            max_tokens=1000,
        )
        content = res.choices[0].message.content
        data = json.loads(content)
        return {"ok": True, "session_id": session.id, "summary": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

            
@router.post("/grade", status_code=status.HTTP_200_OK)
async def grade(
    payload: Dict = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    session_id = int(payload.get("session_id", 0))
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    
    target = (payload.get("target") or "user").strip().lower()
    style = (payload.get("style") or "balanced").strip().lower()
    weights = payload.get("weights"), {
        "clarity": 0.1,
        "logic": 0.4,
        "responsiveness": 0.2,
        "effectiveness": 0.3,
    }

    session = db.query(DebateSession).filter_by(DebateSessionid=session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    turns = (
        db.query(DebateTurn)
        .filter(DebateTurn.session_id == session.id)
        .order_by(DebateTurn.timestamp.asc())
        .all()
    )
    if not turns:
        return {"ok": True, "session_id": session.id, "grade": {"note": "No turns yet"}}
    
    p1 = to_canonical(session.character_1 or "assistant")
    p2 = to_canonical(session.character_2) if session.character_2 else "User"

    possible_targets = {
        "user": "User",
        p1.lower(): p1,
        (p2 or "").lower(): p2,
    }
    if target == "all":
        targets = [x for x in {p1, p2} if x]
    else:
        targets = [possible_targets.get(target, "User")]

    transcript = "\n".join(
        f"{(t.speaker or 'Unkown'): {(t.message or'').strip()}}"
        for t in turns if (t.message or "").strip()
        if (t.message or "").strip()
    
    )
    template_targets = {
        tgt: {
            "scores": {
                "clarity": 0,
                "evidence": 0,
                "logic": 0,
                "responsiveness": 0,
                "conciseness": 0,
            },
            "overall": 0,
            "rationale": {
                "clarity": "",
                "evidence": "",
                "logic": "",
                "responsiveness": "",
                "conciseness": "",
            },
            "actionable_tips": [],
        }
        for tgt in targets
    }

    out_schema = {
        "targets": template_targets,
        "rubric": {"style": style, "weights": weights},
    }

    # Judge prompt
    messages = [
        {
            "role": "system",
            "content": (
                "You are an impartial debate judge. Grade ONLY the specified target speakers. "
                "Use ONLY the transcript; do not import outside facts. "
                "For each target, output 0–10 per criterion (integers). "
                "Compute OVERALL as a weighted 0–100 using the provided weights "
                "(normalize weights if they do not sum to 1). "
                "Give brief, specific rationales and 2–5 actionable improvement tips. "
                "Return exactly one JSON object that matches the provided schema."
            ),
        },
        {
            "role": "user",
            "content": (
                f"STYLE: {style}\n"
                f"TARGETS: {', '.join(targets)}\n"
                f"WEIGHTS: {json.dumps(weights)}\n\n"
                "TRANSCRIPT:\n" + transcript + "\n\n"
                "OUTPUT_JSON_TEMPLATE:\n" + json.dumps(out_schema, ensure_ascii=False)
            ),
        },
    ]

    try:
        res = await engine.async_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=1400,
        )
        content = res.choices[0].message.content
        data = json.loads(content)
        return {
            "ok": True,
            "session_id": session.id,
            "grading": data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grade failed: {e}")