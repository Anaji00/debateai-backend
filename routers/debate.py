# Standard library imports
import os
import uuid
from datetime import datetime
from typing import Optional

# Third-party imports
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_

# Local application imports
from dependencies import get_db
import schemas
from models.debate_models import DebateSession, DebateTurn
from services.debate_engine import DebateEngine
from services.voice_engine import synthesize_xtts
from utils.config import get_openai_client

# --- Router and Engine Initialization ---
router = APIRouter()
engine = DebateEngine(get_openai_client())

# --- Endpoints ---

@router.post("/solo", status_code=status.HTTP_200_OK)
def solo_debate(request: schemas.SoloDebateRequest):
    """
    Handles a solo debate turn where a user interacts with a single AI character.

    Receives the character, user input, and conversation history. It generates a
    text response from the character and optionally synthesizes it into speech.

    Args:
        request: A `SoloDebateRequest` schema containing the debate details.
    """
    try:
        # Prepare the list of messages for the debate engine, including the new user input.
        messages = engine.generate_solo_debate(
            request.character, request.history + [{"role": "user", "content": request.user_input }]
        )
        # Generate a reply from the debate engine based on the messages.
        reply = engine.generate_response(messages)

        audio_url = None
        # Check if the user requested a voice response.
        if request.with_voice:
            # Create a unique, URL-safe filename for the audio file.
            filename = f"{request.character.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}.wav"
            # Synthesize the audio from the reply text.
            path = synthesize_xtts(reply, request.character, filename)
            # If the audio file was created successfully, construct its URL.
            if path:
                audio_url = f"/static/audio/{filename}"

        # Return the generated reply and the audio URL (if any).
        return {
            "reply": reply,
            "audio_url": audio_url
        }
    except Exception as e:
        # Catch any exceptions and raise an HTTP 500 error.
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/versus", response_model=schemas.DebateSessionBase, status_code=status.HTTP_200_OK)
def versus(request: schemas.VersusDebateRequest, db: Session = Depends(get_db)):
    """
    Manages a "versus" debate between two AI characters on a specific topic.

    It finds an existing debate session or creates a new one. Then, it generates
    a turn for each character, synthesizes their responses to audio, and saves
    the turns to the database.

    Args:
        request: A `VersusDebateRequest` schema with characters, topic, and history.
        db: The database session dependency.

    Returns:
        The updated `DebateSession` object with the new turns.
    """
    try:
        # --- Find or Create Debate Session ---
        if request.session_id:
            session = db.query(DebateSession).filter_by(id=request.session_id).first()
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
            # Look for an existing session with the same topic and characters (in any order).
            session = db.query(DebateSession).filter_by(
            ).filter( # Changed filter_by to filter and moved topic here
                DebateSession.topic == request.topic,
                or_( # Check for characters in either order to find existing sessions robustly.
                    (DebateSession.character_1 == request.c1) & (DebateSession.character_2 == request.c2),
                    (DebateSession.character_1 == request.c2) & (DebateSession.character_2 == request.c1)
                )
            ).first()

        # If no session exists, create a new one.
        if not session:
            # Create a new SQLAlchemy DebateSession model instance.
            session = DebateSession(
                topic = request.topic,
                character_1 = request.c1,
                character_2 = request.c2,
            )
            db.add(session)
            db.commit()
            db.refresh(session)

        # --- Generate Debate Turns ---
        history = request.history.copy()
        # Add user's injection to the history if it's not already there.
        if request.user_inject.strip() and not any(s == "You" and request.user_inject in t for s, t in history):
            history.append(("You", request.user_inject.strip()))
            
        # Each character takes a turn to speak.
        for speaker, opponent in [(request.c1, request.c2), (request.c2, request.c1)]:
            messages = engine.generate_versus_debate(
                speaker, opponent, request.topic, history
            )
            reply = engine.generate_response(messages)
            history.append((speaker, reply))
            filename = f"{speaker.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}.wav"
            audio_path = synthesize_xtts(reply, speaker, filename)

            # Create a new DebateTurn record and add it to the database session.
            turn = DebateTurn(
                speaker=speaker,
                message=reply,
                session_id=session.id, # FIX: Added missing comma
                audio_path=audio_path if audio_path else None, # FIX: Added missing comma
                timestamp=datetime.utcnow()
            )
            db.add(turn)
        db.commit() # Commit all the new turns to the database.
        db.refresh(session) # Refresh the session to load the new turns.
        return session
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    

@router.delete("/reset", status_code=status.HTTP_200_OK)
def reset_debate_session(
    session_id: Optional[int] = None,
    topic: Optional[str] = None,
    c1: Optional[str] = None,
    c2: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Deletes a debate session from the database.

    The session can be identified either by its unique `session_id` or by the
    combination of `topic`, `c1`, and `c2`.

    Args:
        session_id: The ID of the session to delete.
        topic, c1, c2: The topic and characters of the session to delete.
        db: The database session dependency.
    """
    session_to_delete = None
    if session_id:
        # Find the session by its primary key (ID).
        session_to_delete = db.query(DebateSession).filter(DebateSession.id == session_id).first()
    elif topic and c1 and c2:
        # Find the session by topic and characters, checking both permutations.
        session_to_delete = db.query(DebateSession).filter(
            DebateSession.topic == topic,
            or_(
                (DebateSession.character_1 == c1) & (DebateSession.character_2 == c2),
                (DebateSession.character_1 == c2) & (DebateSession.character_2 == c1)
            )
        ).first() # FIX: Added missing parentheses to call the method.
    else:
        # If not enough parameters are provided, it's a bad request.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Either 'session_id' or all of 'topic', 'c1', and 'c2' must be provided."
        )

    if not session_to_delete:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    db.delete(session_to_delete)
    db.commit()
    return {"message": "Session deleted successfully"}
    

@router.get("/summary/{session_id}", status_code=status.HTTP_200_OK)
def get_summary(session_id: int, mode: str = "both", db: Session = Depends(get_db)):
    """
    Generates a summary or grade for a completed debate session.

    Args:
        session_id: The ID of the debate session to summarize.
        mode: The type of analysis to perform ('summary', 'grade', or 'both').
        db: The database session dependency.

    Returns:
        A dictionary containing the generated analysis text.
    """
    session = db.query(DebateSession).filter(DebateSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    
    try:
        # Build the prompt for the summary/grade. This can raise a ValueError if the mode is invalid.
        prompt = engine.build_summary_prompt(session, mode=mode) # FIX: Passed the 'mode' parameter.
        
        # Call the OpenAI API to generate the summary.
        response = get_openai_client().chat.completions.create(
            model="gpt-4o", # Using a consistent and modern model.
            messages=[
                {"role": "system", "content": "You are an expert debate analyst."}, # FIX: Added missing comma.
                {"role": "user", "content": prompt}
            ]
        )

        result = response.choices[0].message.content
        return {"result": result}
    except ValueError as e:
        # This catches an invalid 'mode' from build_summary_prompt.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        # Catch any other exceptions (e.g., from the OpenAI API call).
        # In a real app, you would want to log this error for debugging.
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to generate summary: {e}")
        

@router.put("/modify-turn/{turn_id}", status_code=status.HTTP_200_OK)
def modify_turn(turn_id: int, new_message: str = Body(..., embed=True), db: Session = Depends(get_db)):
    """
    Updates the text message of a specific debate turn.

    Args:
        turn_id: The ID of the turn to modify.
        new_message: The new text for the turn, provided in the request body.
        db: The database session dependency.

    Returns:
        A success message.
    """
    # FIX: Imported 'Body' and used 'embed=True' to expect a JSON body like {"new_message
    # Find the specific turn in the database using its ID.
    turn = db.query(DebateTurn).filter(DebateTurn.id == turn_id).first()
    if not turn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found")

    # Update the message content of the turn.
    turn.message = new_message
    db.commit()
    return {"message": "Turn updated successfully"}

@router.delete("/delete-turn/{turn_id}", status_code=status.HTTP_200_OK)
def delete_turn(turn_id: int, db: Session = Depends(get_db)):
    """
    Deletes a specific debate turn from the database.

    Args:
        turn_id: The ID of the turn to delete.
        db: The database session dependency.

    Returns:
        A success message.
    """
    # Find the specific turn in the database using its ID.
    turn = db.query(DebateTurn).filter(DebateTurn.id == turn_id).first()
    if not turn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found")

    db.delete(turn)
    db.commit()
    return {"message": "Turn deleted successfully"}

@router.post("/voice/{turn_id}", status_code=status.HTTP_200_OK)
def generate_voice(turn_id: int, db: Session = Depends(get_db)):
    """
    Generates or retrieves the audio for a specific debate turn.

    If the audio file already exists, it returns the URL. Otherwise, it
    synthesizes the audio, saves it, updates the turn record in the database,
    and then returns the URL.

    Args:
        turn_id: The ID of the turn to generate voice for.
        db: The database session dependency.
    """
    # Find the specific turn in the database using its ID.
    turn = db.query(DebateTurn).filter(DebateTurn.id == turn_id).first()
    if not turn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found")
    if turn.audio_path and os.path.exists(turn.audio_path):
        return {"audio_url": f"/static/audio/{os.path.basename(turn.audio_path)}"}
    filename = f"{turn.speaker.lower()}_{uuid.uuid4().hex[:6]}.wav"
    audio_path = synthesize_xtts(turn.message, turn.speaker, filename)
    turn.audio_path = audio_path
    db.commit()
    return {"audio_url": f"/static/audio/{filename}" if audio_path else None}
