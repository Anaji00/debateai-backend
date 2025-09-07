# coding from scratch lets run it
# ----------------------------------------------------------------------
# Debate API router — ENTERPRISE-READY, split start/inject per mode
# ----------------------------------------------------------------------
# Key changes vs your old file:
# 1) Split /versus into /versus/start and /versus/inject (no more reading
#    session_id from a StartRequest), fixing the crash you saw.
# 2) Normalized endpoints:
#      /solo/start, /solo/inject
#      /versus/start, /versus/inject
#      /da/start, /da/inject
# 3) Still streams NDJSON events: session -> turn -> (delta...)* -> endturn
# 4) Solo/DA start require `character`; Versus start requires c1,c2,topic.
# 5) Inject routes take session_id + user_inject (+ addressed_to for versus).
# 6) RAG behavior preserved; sources event emitted before deltas when available.

from __future__ import annotations

# --- stdlib / third-party
import asyncio, os, json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, AsyncIterator

from fastapi import (
    APIRouter, Depends, UploadFile, File, Form, Query,
    status, Body, HTTPException
)
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

# --- local deps (kept exactly as you used them)
from core.database import get_db, SessionLocal
import schemas
from models.debate_models import DebateSession, DebateTurn
from services.voice_engine import synthesize, STATIC_DIR
from services.name_map import to_alias, to_canonical
from utils.config import get_openai_async_client
from services.debate_engine import DebateEngine
from services.rag_store import (
    add_doc as rag_add,
    delete_all_for_owner as rag_delete,
    list_docs as rag_list,
    query as rag_query,
    start_sweeper as rag_start_sweeper,
    touch_session as rag_touch
)

# ----------------------------------------------------------------------
# wiring
# ----------------------------------------------------------------------
router = APIRouter()
llm = get_openai_async_client()
engine = DebateEngine(llm)  # your custom prompt/LLM wrapper

# ----------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------
def _jsonl(obj: dict) -> str:
    """Serialize a dict as one NDJSON line."""
    return json.dumps(obj, ensure_ascii=False) + "\n"

def _no_buffer_headers(resp: StreamingResponse):
    """Disable buffering for streaming."""
    resp.headers["Cache-Control"] = "no-cache, no-transform"
    resp.headers["Content-Type"] = "application/x-ndjson; charset=utf-8"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Connection"] = "keep-alive"

async def _safe_stream(gen: AsyncIterator[str]) -> AsyncIterator[str]:
    """
    Convert generator errors into a final JSONL error line so the client
    doesn't see an abrupt connection drop.
    """
    try:
        async for chunk in gen:
            # Important: always yield strings that END WITH '\n'
            yield chunk
    except asyncio.CancelledError:
        # client navigated away or aborted fetch; emit a soft error then re-raise
        try:
            yield _jsonl({"type": "error", "message": "stream cancelled"})
        except Exception:
            pass
        raise
    except Exception as e:
        # surface the error as the last JSONL line (keeps the protocol consistent)
        try:
            yield _jsonl({"type": "error", "message": f"{type(e).__name__}: {e}"})
        except Exception:
            pass

def safe_filename(base: str) -> str:
    return (base or "").strip().replace(" ", "_").lower()

def fs_to_web(fs_path: str) -> str:
    """Map a filesystem path under STATIC_DIR to a web URL path."""
    p = Path(fs_path).resolve()
    static_root = Path(STATIC_DIR).resolve()
    try:
        rel = p.relative_to(static_root)
        return f"/static/{rel.as_posix()}"
    except Exception:
        return p.as_posix()

def _insert_user_turn(db: Session, session_id: int, text: str):
    """Persist a user message as a DebateTurn (helps rebuilding history)."""
    if not (text or "").strip():
        return None
    t = DebateTurn(
        speaker="user",
        message=text.strip(),
        audio_path=None,
        session_id=session_id,
        timestamp=datetime.utcnow(),
    )
    db.add(t); db.commit(); db.refresh(t)
    return t

def _chunk_for_stream(text: str, max_len: int = 300) -> Iterable[str]:
    """Chunk assistant text into small deltas; here we just slice every N chars."""
    text = (text or "").strip()
    if not text:
        return []
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        j = min(i + max_len, n)
        out.append(text[i:j])
        i = j
    return out

# RAG tactic helper (place ABOVE the routes that call it)
def _rag_tactic_line(mode: str, cite_style: str) -> str:
    """
    Build a one-liner that tells the model HOW to use uploaded excerpts,
    tailored by an adaptive mode and a citation style.
    mode: "evidence_cite" | "weaponize_spin" | "persona_paraphrase" (default)
    cite_style: "brand" | "inline" | "brackets" | "none" (default)
    """
    cite_style = (cite_style or "none").lower().strip()
    mode = (mode or "persona_paraphrase").lower().strip()

    if mode == "evidence_cite":
        if cite_style == "brand":
            # casual name-drops, no brackets
            return ("Lean on the strongest lines from the excerpts and casually name-drop outlets or authors "
                    "(e.g., 'even the Journal says…'); no brackets.")
        elif cite_style == "inline":
            # short attributions woven into prose
            return ("Pull short phrases and attribute inline in prose (e.g., 'as the Journal reported'); "
                    "keep it natural, no brackets.")
        elif cite_style == "brackets":
            # explicit refs if you add them in your UI later
            return ("Quote short phrases and add bracket references like [Title ▸ chunk N] when it helps.")
        else:  # none
            return ("Paraphrase the strongest claims from the excerpts with confident language; no explicit attribution.")
    elif mode == "weaponize_spin":
        return ("If the excerpts cut against you, spin them: reframe their meaning, question credibility or bias, "
                "cherry-pick favorable bits, or pivot to your opponent’s record—stay aggressive and on topic.")
    else:  # persona_paraphrase
        return ("Paraphrase and fold the material into your worldview naturally; keep it in-character and on topic.")

# ----------------------------------------------------------------------
# RAG endpoints (unchanged paths)
# ----------------------------------------------------------------------
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

@router.get("/docs/list", status_code=status.HTTP_200_OK)
async def list_docs(session_id: int = Query(...)):
    docs = rag_list(session_id)
    rag_touch(session_id)
    return {"ok": True, "docs": docs}

@router.delete("/docs/owner/{session_id}/{owner}", status_code=status.HTTP_200_OK)
async def delete_docs(session_id: int, owner: str):
    rag_delete(session_id, to_canonical(owner))
    rag_touch(session_id)
    return {"ok": True}

# ----------------------------------------------------------------------
# SOLO
# ----------------------------------------------------------------------
@router.post("/solo/start", status_code=status.HTTP_200_OK)
async def solo_start(req: schemas.SoloStartRequest):
    """
    Solo start: creates a session, emits a `session` event,
    then streams one assistant turn from `character`.
    """
    try:
        character = to_canonical(req.character)
        topic = (req.topic or "").strip()

        # Build seed history (ensure one user message with topic exists)
        history = [{"role": h.role, "content": h.content} for h in (req.history or [])]
        if topic and not any(h["role"] == "user" for h in history):
            history.append({"role": "user", "content": topic})

        with SessionLocal() as db0:
            session_row = DebateSession(topic=topic, character_1=character, character_2=None)
            db0.add(session_row); db0.commit(); db0.refresh(session_row)
            session_id = session_row.id
            if topic:
                _insert_user_turn(db0, session_id, topic)
        rag_touch(session_id)
        
        async def stream():
            db = SessionLocal()
            try:
                # 1) session id
                yield _jsonl({"type": "session", "session_id": session_id})

                # 2) create turn row
                turn = DebateTurn(
                    speaker=character, message="", audio_path=None,
                    session_id=session_id, timestamp=datetime.utcnow()
                )
                db.add(turn); db.commit(); db.refresh(turn)
                yield _jsonl({"type": "turn", "turn_id": turn.id, "speaker": character})

                # 3) RAG
                qtext = history[-1]["content"] if (history and history[-1]["role"] == "user") else (topic or "")
                sources = rag_query(session_id, query_text=qtext, allowed_owners=[], k=4)
                if sources:
                    yield _jsonl({"type":"sources","turn_id":turn.id,"speaker":character,"items":sources})

                # 4) LLM messages
                messages = engine.generate_solo_debate(character, history)

                # 5) Adaptive RAG guidance
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
                    tactic_line = _rag_tactic_line(decision["mode"], decision["cite_style"])
                    messages.append({"role": "system", "content": "Uploaded excerpts:\n\n" + blob + "\n\nGuidance: " + tactic_line})

                yield _jsonl({"type": "debug", "msg": "passed-if-sources-block"})
            # 6) stream deltas
                reply_acc: List[str] = []
                try:
                    s = await engine.async_client.chat.completions.create(
                        model="gpt-4o-mini", messages=messages,
                        temperature=0.9, stream=True, max_tokens=600)
                    async for chunk in s:
                        token = getattr(chunk.choices[0].delta, "content", None)
                        if not token: continue
                        reply_acc.append(token)
                        # chunk down to char granularity for smoother UI
                        for ch in token:
                            yield _jsonl({"type":"delta","turn_id":turn.id,"speaker":character,"delta":ch})
                            await asyncio.sleep(0)
                except Exception as e:
                    yield _jsonl({"type":"error","message":f"Error for {character}: {e}"})

                # 7) finalize
                final_text = "".join(reply_acc).strip()
                turn.message = final_text; db.commit()
                yield _jsonl({"type":"endturn","turn_id":turn.id,"speaker":character})
            finally:
                db.close()

        resp = StreamingResponse(_safe_stream(stream()), media_type="application/x-ndjson; charset=utf-8")
        _no_buffer_headers(resp); return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/solo/inject", status_code=status.HTTP_200_OK)
async def solo_inject(req: schemas.SoloInjectRequest):
    """
    Solo inject: append user's message and stream one assistant reply.
    """
    try:
        user_text = (req.user_inject or "").strip()

        with SessionLocal() as db0:
            session_row = db0.query(DebateSession).filter(DebateSession.id == req.session_id).first()
            if not session_row:
                raise HTTPException(status_code=404, detail="Session not found")
            
            character = to_canonical(session_row.character_1 or "assistant")
            session_id = session_row.id
            topic = session_row.topic or ""

            if user_text:
                _insert_user_turn(db0, session_id, user_text)

        # Rebuild history from DB
            turns = (
                db0.query(DebateTurn)
                .filter(DebateTurn.session_id == session_id)
                .order_by(DebateTurn.timestamp.asc()).all()
            )
            history: List[dict] = [{"role":"assistant","content":t.message}
                                for t in turns if (t.message or "").strip()]
            if user_text:
                history.append({"role":"user","content":user_text})
            rag_touch(session_id)

        async def stream():
            db = SessionLocal()
            try:
                turn = DebateTurn(
                    speaker=character, message="", audio_path=None,
                    session_id=session_id, timestamp=datetime.utcnow()
                )
                db.add(turn); db.commit(); db.refresh(turn)
                yield _jsonl({"type":"turn","turn_id":turn.id,"speaker":character})

                # RAG
                qtext = user_text or topic or ""
                sources = rag_query(session_id, query_text=qtext, allowed_owners=[], k=4)
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
                    tactic_line = _rag_tactic_line(decision["mode"], decision["cite_style"])
                    messages.append({"role": "system", "content": "Uploaded excerpts:\n\n" + blob + "\n\nGuidance: " + tactic_line})

            # stream deltas
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
            finally:
                db.close()
        resp = StreamingResponse(_safe_stream(stream()), media_type="application/x-ndjson; charset=utf-8")
        _no_buffer_headers(resp); return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------------------------------------------------
# VERSUS (two characters, both reply on start; both reply on inject)
# ----------------------------------------------------------------------
@router.post("/versus/start", status_code=status.HTTP_200_OK)
async def versus_start(req: schemas.VersusStartRequest):
    """
    Versus start: creates a session, emits `session`, then streams two turns:
    c1's opening, then c2's opening.
    """
    try:
        c1 = to_canonical(req.c1)
        c2 = to_canonical(req.c2)
        topic = (req.topic or "").strip()

        # seed history
        history = [{"role": h.role, "content": h.content} for h in (req.history or [])]
        if topic and not any(h["role"] == "user" for h in history):
            history.append({"role": "user", "content": topic})

        with SessionLocal() as db0:
            session_row = DebateSession(topic=topic, character_1=c1, character_2=c2)
            db0.add(session_row); db0.commit(); db0.refresh(session_row)
            session_id = session_row.id
            if topic:
                _insert_user_turn(db0, session_id, topic)
        rag_touch(session_id)

        async def stream():
            db = SessionLocal()
            try: 
                # session id first
                yield _jsonl({"type": "session", "session_id": session_id})

                # helper to render one speaker
                async def render_one(speaker: str, opponent: str, last_speaker: Optional[str]):
                    turn = DebateTurn(
                        speaker=speaker, message="", audio_path=None,
                        session_id=session_id, timestamp=datetime.utcnow()
                    )
                    db.add(turn); db.commit(); db.refresh(turn)
                    yield _jsonl({"type": "turn", "turn_id": turn.id, "speaker": speaker})

                    # RAG
                    # prefer user’s latest line; else topic + last assistant
                    if history and history[-1]["role"] == "user":
                        qtext = history[-1]["content"]
                    else:
                        last_assist = next((h["content"] for h in reversed(history) if h["role"] == "assistant"), "")
                        qtext = f"{topic}\n\n{last_assist}"

                    sources = rag_query(session_id, query_text=qtext, allowed_owners=[speaker, "shared"], k=4)
                    if sources:
                        yield _jsonl({"type": "sources", "turn_id": turn.id, "speaker": speaker, "items": sources})

                    messages = engine.generate_versus_debate(
                        speaker=speaker, opponent=opponent, topic=topic, history=history, last_speaker=last_speaker
                    )

                    if sources:
                        blob = "\n\n".join(
                            f"[{s['title']} ▸ chunk {s['chunk_index']}]\n{s['snippet']}"
                            for s in sources
                        )
                        profile = engine.rag_profile_for(speaker)
                        decision = await engine.decide_rag_mode(
                            current_speaker=speaker,
                            topic=topic,
                            history=history,
                            sources=sources,
                            default_mode=profile["mode"],
                            cite_style=profile["cite_style"],
                        )
                        tactic_line = _rag_tactic_line(decision["mode"], decision["cite_style"])
                        messages.append({
                            "role": "system",
                            "content": (
                                "Uploaded excerpts for this turn (treat as context; stay on the core debate topic):\n\n"
                                + blob + "\n\nGuidance: " + tactic_line
                            )
                        })

                    STOP_TOKENS = [f"\n{opponent.title()}:", "\nYou:", "\nUSER:", f"\n{speaker.title()}:"]

                    reply_acc: List[str] = []
                    try:
                        s = await engine.async_client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=messages,
                            stream=True,
                            temperature=0.9,
                            max_tokens=500,
                            stop=STOP_TOKENS
                        )
                        async for chunk in s:
                            token = getattr(chunk.choices[0].delta, "content", None)
                            if not token: continue
                            reply_acc.append(token)
                            for ch in token:
                                yield _jsonl({"type":"delta","turn_id":turn.id,"speaker":speaker,"delta":ch})
                                await asyncio.sleep(0)
                    except Exception as e:
                        yield _jsonl({"type": "error", "message": f"Error generating response for {speaker}: {e}"})

                    final_text = "".join(reply_acc).strip()
                    turn.message = final_text; db.commit()
                    yield _jsonl({"type":"endturn","turn_id":turn.id,"speaker":speaker})

                # c1 then c2
                async for line in render_one(c1, c2, None):
                    yield line
                async for line in render_one(c2, c1, c1):
                    yield line
            finally:
                db.close()

        resp = StreamingResponse(_safe_stream(stream()), media_type="application/x-ndjson; charset=utf-8")
        _no_buffer_headers(resp); return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/versus/inject", status_code=status.HTTP_200_OK)
async def versus_inject(req: schemas.VersusInjectRequest):
    """
    Versus inject: user speaks; then both characters reply in sequence.
    If `addressed_to` is provided (['c2'] for example), that speaker replies first.
    """
    try:
        user_text = (req.user_inject or ""). strip()

        with SessionLocal() as db0:
            session_row = db0.query(DebateSession).filter(DebateSession.id == req.session_id).first()
            if not session_row:
                raise HTTPException(status_code=404, detail="Session not found")
            c1 = to_canonical(session_row.character_1 or "speaker_1")
            c2 = to_canonical(session_row.character_2 or "speaker_2")
            topic = session_row.topic or ""
            session_id = session_row.id

            if user_text:
                _insert_user_turn(db0, session_id, user_text)

            # Build history from DB + this inject
            turns = (
                db0.query(DebateTurn)
                .filter(DebateTurn.session_id == session_id)
                .order_by(DebateTurn.timestamp.asc()).all()
            )
            history: List[dict] = [{"role":"assistant","content":t.message}
                                for t in turns if (t.message or "").strip()]
            if user_text:
                history.append({"role":"user","content":user_text})
            rag_touch(session_id)

            # decide reply order
            first, second = c1, c2
            addrs = [to_canonical(x) for x in (req.addressed_to or [])]
            if addrs:
                # if first addressed speaker is c2, swap order
                if addrs[0] == c2:
                    first, second = c2, c1

        async def stream():
            db = SessionLocal()
            try:
                async def render_one(speaker: str, opponent: str, last_speaker: Optional[str]):
                    turn = DebateTurn(
                        speaker=speaker, message="", audio_path=None,
                        session_id=session_id, timestamp=datetime.utcnow()
                    )
                    db.add(turn); db.commit(); db.refresh(turn)
                    yield _jsonl({"type": "turn", "turn_id": turn.id, "speaker": speaker})

                    # RAG
                    qtext = user_text or topic or ""
                    sources = rag_query(session_id, query_text=qtext, allowed_owners=[speaker, "shared"], k=4)
                    if sources:
                        yield _jsonl({"type": "sources", "turn_id": turn.id, "speaker": speaker, "items": sources})

                    messages = engine.generate_versus_debate(
                        speaker=speaker, opponent=opponent, topic=topic, history=history, last_speaker=last_speaker
                    )

                    if sources:
                        blob = "\n\n".join(
                            f"[{s['title']} ▸ chunk {s['chunk_index']}]\n{s['snippet']}"
                            for s in sources
                        )
                        profile = engine.rag_profile_for(speaker)
                        decision = await engine.decide_rag_mode(
                            current_speaker=speaker,
                            topic=topic,
                            history=history,
                            sources=sources,
                            default_mode=profile["mode"],
                            cite_style=profile["cite_style"],
                        )
                        tactic_line = _rag_tactic_line(decision["mode"], decision["cite_style"])
                        messages.append({
                            "role": "system",
                            "content": (
                                "Uploaded excerpts for this turn (treat as context; stay on the core debate topic):\n\n"
                                + blob + "\n\nGuidance: " + tactic_line
                            )
                        })

                    STOP_TOKENS = [f"\n{opponent.title()}:", "\nYou:", "\nUSER:", f"\n{speaker.title()}:"]

                    reply_acc: List[str] = []
                    try:
                        s = await engine.async_client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=messages,
                            stream=True,
                            temperature=0.9,
                            max_tokens=600,
                            stop=STOP_TOKENS
                        )
                        async for chunk in s:
                            token = getattr(chunk.choices[0].delta, "content", None)
                            if not token: continue
                            reply_acc.append(token)
                            for ch in token:
                                yield _jsonl({"type":"delta","turn_id":turn.id,"speaker":speaker,"delta":ch})
                                await asyncio.sleep(0)
                    except Exception as e:
                        yield _jsonl({"type":"error","message":f"Error for {speaker}: {e}"})

                    final_text = "".join(reply_acc).strip()
                    turn.message = final_text; db.commit()
                    yield _jsonl({"type":"endturn","turn_id":turn.id,"speaker":speaker})

                # render in decided order
                async for line in render_one(first, second, None):
                    yield line
                async for line in render_one(second, first, first):
                    yield line
            finally:
                db.close()

        resp = StreamingResponse(_safe_stream(stream()), media_type="application/x-ndjson; charset=utf-8")
        _no_buffer_headers(resp); return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------------------------------------------------
# DEVIL'S ADVOCATE
# ----------------------------------------------------------------------
@router.post("/da/start", status_code=status.HTTP_200_OK)
async def da_start(req: schemas.DevilStartRequest):
    """
    Devil’s Advocate start: creates a session (topic=thesis), then streams one rebuttal.
    """
    try:
        character = to_canonical(req.character)  # must be provided by client
        thesis = (req.thesis or "").strip()

        # seed history
        history = [{"role": h.role, "content": h.content} for h in (req.history or [])]
        if thesis and not any(h["role"] == "user" for h in history):
            history.append({"role": "user", "content": thesis})

        with SessionLocal() as db0:
            session_row = DebateSession(topic=thesis, character_1=character, character_2=None)
            db0.add(session_row); db0.commit(); db0.refresh(session_row)
            session_id = session_row.id
            if thesis:
                _insert_user_turn(db0, session_id, thesis)
        rag_touch(session_id)

        async def stream():
            db = SessionLocal()
            try:
                yield _jsonl({"type": "session", "session_id": session_id})

                turn = DebateTurn(
                    speaker=character, message="", audio_path=None,
                    session_id=session_id, timestamp=datetime.utcnow()
                )
                db.add(turn); db.commit(); db.refresh(turn)
                yield _jsonl({"type": "turn", "turn_id": turn.id, "speaker": character})

                # RAG
                qtext = history[-1]["content"] if (history and history[-1]["role"] == "user") else thesis
                sources = rag_query(session_id, query_text=qtext or thesis, allowed_owners=[], k=4)
                if sources:
                    yield _jsonl({"type":"sources","turn_id":turn.id,"speaker":character,"items":sources})

                messages = engine.create_assistant_debate_messages(history=history, context="")

                if sources:
                    blob = "\n\n".join(
                        f"[{s['title']} ▸ chunk {s['chunk_index']}]\n{s['snippet']}"
                        for s in sources
                    )
                    profile = engine.rag_profile_for(character)
                    decision = await engine.decide_rag_mode(
                        current_speaker=character,
                        topic=thesis or qtext,
                        history=history,
                        sources=sources,
                        default_mode=profile["mode"],
                        cite_style=profile["cite_style"],
                    )
                    tactic_line = _rag_tactic_line(decision["mode"], decision["cite_style"])
                    messages.append({"role": "system", "content": "Uploaded excerpts:\n\n" + blob + "\n\nGuidance: " + tactic_line})

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

                turn.message = "".join(reply_acc).strip()
                db.commit()
                yield _jsonl({"type":"endturn","turn_id":turn.id,"speaker":character})
            finally:
                db.close()

        resp = StreamingResponse(_safe_stream(stream()), media_type="application/x-ndjson; charset=utf-8")
        _no_buffer_headers(resp); return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/da/inject", status_code=status.HTTP_200_OK)
async def da_inject(req: schemas.DevilInjectRequest):
    """
    Devil’s Advocate inject: append user message; stream one rebuttal.
    """
    try:
        user_text = (req.user_inject or "").strip()
        with SessionLocal() as db:
            session_row = db.query(DebateSession).filter(DebateSession.id == req.session_id).first()
            if not session_row:
                raise HTTPException(status_code=404, detail="Session not found")
            character = to_canonical(session_row.character_1 or "assistant")
            session_id = session_row.id
            topic = session_row.topic or ""
            if user_text:
                _insert_user_turn(db, session_id, user_text)
            turns = (
                db.query(DebateTurn)
                .filter(DebateTurn.session_id == session_id)
                .order_by(DebateTurn.timestamp.asc()).all()
            )
            history: List[dict] = [{"role":"assistant","content":t.message}
                                for t in turns if (t.message or "").strip()]
            if user_text:
                history.append({"role":"user","content":user_text})
        rag_touch(session_id)

        async def stream():
            db = SessionLocal()
            try:
                turn = DebateTurn(
                    speaker=character, message="", audio_path=None,
                    session_id=session_id, timestamp=datetime.utcnow()
                )
                db.add(turn); db.commit(); db.refresh(turn)
                yield _jsonl({"type":"turn","turn_id":turn.id,"speaker":character})

                qtext = user_text or topic or ""
                sources = rag_query(session_id, query_text=qtext, allowed_owners=[], k=4)
                if sources:
                    yield _jsonl({"type":"sources","turn_id":turn.id,"speaker":character,"items":sources})

                messages = engine.create_assistant_debate_messages(history=history, context="")

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
                    tactic_line = _rag_tactic_line(decision["mode"], decision["cite_style"])
                    messages.append({"role": "system", "content": "Uploaded excerpts:\n\n" + blob + "\n\nGuidance: " + tactic_line})

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
            finally:
                db.close()

        resp = StreamingResponse(_safe_stream(stream()), media_type="application/x-ndjson; charset=utf-8")
        _no_buffer_headers(resp); return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------------------------------------------------
# VOICE (on-demand TTS for a saved turn)
# ----------------------------------------------------------------------
@router.post("/voice/{turn_id}", status_code=status.HTTP_200_OK)
async def generate_voice(turn_id: int, db: Session = Depends(get_db)):
    """
    Generate audio for a specific saved turn.
    Maps canonical speaker -> alias for TTS.
    """
    turn = db.query(DebateTurn).filter_by(id=turn_id).first()
    if not turn:
        raise HTTPException(status_code=404, detail="Turn not found")

    # Return existing audio if present
    if turn.audio_path and os.path.exists(turn.audio_path):
        return {"audio_url": f"/static/audio/generated/{os.path.basename(turn.audio_path)}"}

    alias = to_alias(turn.speaker or "assistant")
    filename = f"{safe_filename(alias)}_{turn_id}.wav"
    fs_path = await synthesize(turn.message or "", alias, filename)
    if not fs_path:
        raise HTTPException(status_code=500, detail="TTS failed")

    turn.audio_path = fs_path
    db.commit()
    return {"audio_url": fs_to_web(fs_path)}

# ----------------------------------------------------------------------
# Sessions, reset, judge (summary/grade)
# ----------------------------------------------------------------------
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

# --------------------------- Judge: Summary ----------------------------------
@router.post("/summary", status_code=status.HTTP_200_OK)
async def summarize(
    payload: Dict = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """
    Summarize a session transcript into a structured JSON object.
    (Kept your original logic with minor cleanup)
    """
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
    p2 = to_canonical(session.character_2) if session.character_2 else "user"

    transcript = "\n".join(
        f"{(t.speaker or 'Unknown')}: {(t.message or '').strip()}"
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
        "weaknesses": { p1: [], p2: []},
        "open_questions": [],
    }

    messages = [
        {
            "role": "system",
            "content": (
                "You are an impartial debate judge and summarizer. "
                "Summarize only from the transcript. Do not add external facts. "
                "Capture positions, key points, best moments, weaknesses, and open questions. "
                "Return a single JSON object matching the provided keys exactly."
            ),
        },
        {
            "role": "user",
            "content": (
                f"STYLE: {style}\n\n"
                f"TOPIC: {session.topic}\n\n"
                f"PARTICIPANTS: {p1} vs {p2}\n\n"
                f"TRANSCRIPT:\n{transcript}\n\n"
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
            response_format={"type": "json_object"},
        )
        content = res.choices[0].message.content
        data = json.loads(content)
        return {"ok": True, "session_id": session.id, "summary": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------- Judge: Grade -----------------------------------
@router.post("/grade", status_code=status.HTTP_200_OK)
async def grade(
    payload: Dict = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """
    Grade one or both speakers in the session using a rubric.
    (Kept your weights/targets shape, fixed minor typos)
    """
    session_id = int(payload.get("session_id", 0))
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")

    target = (payload.get("target") or "user").strip().lower()
    style = (payload.get("style") or "balanced").strip().lower()
    weights = payload.get("weights") or {
        "clarity": 0.1,
        "logic": 0.4,
        "responsiveness": 0.2,
        "effectiveness": 0.3,
    }

    session = db.query(DebateSession).filter(DebateSession.id == session_id).first()
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
    p2 = to_canonical(session.character_2) if session.character_2 else "user"

    possible_targets = {"user": "user", p1.lower(): p1, (p2 or "").lower(): p2}
    targets = [x for x in {p1, p2} if x] if target == "all" else [possible_targets.get(target, "user")]

    transcript = "\n".join(
        f"{(t.speaker or 'Unknown')}: {(t.message or '').strip()}"
        for t in turns if (t.message or "").strip()
    )

    template_targets = {
        tgt: {
            "scores": {"clarity": 0, "evidence": 0, "logic": 0, "responsiveness": 0, "conciseness": 0},
            "overall": 0,
            "rationale": {"clarity": "", "evidence": "", "logic": "", "responsiveness": "", "conciseness": ""},
            "actionable_tips": [],
        } for tgt in targets
    }
    out_schema = {"targets": template_targets, "rubric": {"style": style, "weights": weights}}

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
        return {"ok": True, "session_id": session.id, "grading": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grade failed: {e}")
