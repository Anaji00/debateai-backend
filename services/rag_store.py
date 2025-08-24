"""
In-memory Retrieval-Augmented Generation (RAG) vector store.

This module provides a simple, in-memory database for text that can be searched
based on meaning, not just keywords. This is a core part of a RAG system, which
helps a language model (like GPT) answer questions using information from specific
documents you provide.

How it works:
1.  Documents (text or PDF) are broken into smaller, manageable chunks.
2.  Each chunk is converted into a numerical representation called an "embedding"
    using a special AI model (SentenceTransformer). These numbers capture the
    semantic meaning of the text.
3.  The embeddings are stored in a FAISS index, which is a library designed for
    very fast similarity searches on large sets of vectors.
4.  When you ask a question (a "query"), it's also converted into an embedding,
    and FAISS finds the text chunks with the most similar embeddings.

This whole system is "session-based," meaning each user's debate has its own
separate, temporary document store. To prevent memory from filling up, a
background "sweeper" automatically cleans up data from sessions that have been
inactive for a while (Time-To-Live or TTL).
"""
import time
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import faiss  # The library for efficient similarity search
from sentence_transformers import SentenceTransformer # The model for creating text embeddings
from pypdf import PdfReader # A library to read text from PDF files
import threading # Used for thread-safety and the background sweeper
from io import BytesIO # Used to treat raw bytes (like a file upload) as a file
 
# --- Configuration ---
# The ID of the pre-trained model from Hugging Face that we'll use to create embeddings.
# 'all-MiniLM-L6-v2' is a good, lightweight model for general purpose use.
EMB_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
# The number of dimensions in the vectors (embeddings) produced by the model.
# This must match the model's output. For 'all-MiniLM-L6-v2', it's 384.
EMB_DIM = 384
# Default time-to-live for inactive sessions, in seconds.
# Here, it's set to 2 hours (2 * 60 minutes * 60 seconds).
DEFAULT_TTL_SECS = 2 * 60 * 60
 
# --- Lazy Model Loading ---
# We don't want to load the AI model the moment the application starts, because it
# can slow down startup and consume memory even if it's not used. "Lazy loading"
# means we wait until the model is actually needed for the first time.

# Global variable to hold the model instance. It starts as None.
_model = None
# A "lock" is used to prevent a race condition in multi-threaded applications.
# If two requests try to load the model at the exact same time, the lock ensures
# that only one does the loading, while the other waits.
_model_lock = threading.Lock()

def _get_model():
    """Lazily loads and returns the SentenceTransformer model in a thread-safe way."""
    global _model
    # If the model hasn't been loaded yet...
    if _model is None:
        # Acquire the lock. This blocks other threads until the 'with' block is exited.
        with _model_lock:
            # Check again inside the lock, in case another thread loaded it
            # while this one was waiting for the lock. This is called a double-checked lock.
            if _model is None:
                # Load the model and assign it to the global variable.
                _model = SentenceTransformer(EMB_MODEL_ID)
    return _model

# --- Helper Functions ---
 
def _now() -> float:
    """Returns the current time as a Unix timestamp (seconds since 1970-01-01)."""
    return time.time()

def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> List[str]:
    """
    Splits a long text into smaller, overlapping chunks.
    This is crucial for RAG because models have a limited context window.
    Overlapping chunks helps ensure that a sentence or idea isn't cut in half
    at the boundary between two chunks, preserving context.

    Args:
        text: The input text to chunk.
        chunk_size: The maximum size of each chunk in characters.
        overlap: The number of characters from the end of one chunk to include
                 at the beginning of the next.

    Returns:
        A list of text chunks.
    """
    # First, normalize whitespace to handle different text formats consistently.
    text = " ".join((text or "").split())
    out, i, n = [], 0, len(text)
    while i < n:
        # The end of the next chunk is the minimum of (start + chunk_size) or the end of the text.
        j = min(i + chunk_size, n)
        out.append(text[i:j])
        # Move the starting point for the next chunk back by the overlap amount.
        i = j - overlap
    # Filter out any empty chunks that might have been created.
    return [c for c in out if c.strip()]

def _pdf_to_text_bytes(data: bytes) -> str:
    """Extracts all text from a PDF file provided as raw bytes."""
    # BytesIO allows pypdf to read the in-memory bytes as if it were a file on disk.
    reader = PdfReader(BytesIO(data))
    pages = []
    for p in reader.pages:
        try:
            # Extract text from each page.
            pages.append(p.extract_text() or "")
        except Exception:
            # If a page fails to extract for any reason, append an empty string
            # to avoid crashing the whole process.
            pages.append("")
    return "\n".join(pages)

def _embed(texts: List[str]) -> np.ndarray:
    """
    Converts a list of text strings into a NumPy array of embeddings.

    Args:
        texts: A list of strings to embed.

    Returns:
        A NumPy array of shape (n_texts, EMB_DIM) with float32 embeddings.
        Each row is a vector representing the meaning of a string.
    """
    # `normalize_embeddings=True` is important for FAISS's IndexFlatIP. It scales
    # the vectors to have a length of 1, which allows using the fast Inner Product (IP)
    # search to find the most similar vectors (cosine similarity).
    X = _get_model().encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    # FAISS works with float32 arrays.
    return X.astype("float32")

# --- In-Memory Store Management ---
# This global dictionary holds all the data for active debate sessions.
# The key is the session_id (an integer), and the value is another dictionary
# containing that session's specific data (FAISS index, text chunks, etc.).
_STORES: Dict[int, Dict[str, Any]] = {}
# A Re-entrant Lock is used here. In a web server, each request might be handled
_STORES_LOCK = threading.RLock()

def _get_or_create_store(session_id: int) -> Dict[str, Any]:
    """Retrieves or creates a new vector store for a given session ID."""
    with _STORES_LOCK:
        store = _STORES.get(session_id)
        if store is None:
            # Initialize a new store for the session.
            store = {
                "index": faiss.IndexFlatIP(EMB_DIM),
                "chunks": [],
                "dim": EMB_DIM,
                "last_used": _now(),
                "lock": threading.RLock(),
                
            }
            _STORES[session_id] = store
    return store

def touch_session(session_id: int):
    """Updates the 'last_used' timestamp of a session to keep it from being swept by the TTL cleaner."""
    with _STORES_LOCK:
        s = _STORES.get(session_id)
        if s:
            s["last_used"] = _now()


# --- Public API ---

def add_doc(session_id: int, *, owner: str, filename: str, file_bytes: bytes, title: Optional[str]) -> Dict[str, Any]:
    """
    Adds a document to a session's vector store.

    Args:
        session_id: The ID of the session.
        owner: The owner of the document (e.g., user ID or 'shared').
        filename: The original name of the file.
        file_bytes: The raw content of the file.
        title: An optional title for the document.

    Returns:
        A dictionary summarizing the added document.
    """
    store = _get_or_create_store(session_id)
    with store["lock"]:
        if filename.lower().endswith(".pdf"):
            text = _pdf_to_text_bytes(file_bytes)
        else:
            try:
                text = file_bytes.decode("utf-8", errors="ignore")
            except Exception:
                text = ""
        chunks = _chunk_text(text)
        if not chunks:
            store["last_used"] = _now()
            return {"owner": owner, "title": title or filename, "chunks": 0}
        
        # Embed the chunks and add them to the FAISS index.
        vecs = _embed(chunks)
        store["index"].add(vecs)
        
        # Append metadata for each chunk to the store's chunk list.
        base = len(store["chunks"])
        for i, c in enumerate(chunks):
            store["chunks"].append({
                "owner": owner,
                "title": title or filename,
                "filename": filename,
                "chunk_index": base + i,
                "text": c
            })

        store["last_used"] = _now()
        return {"owner": owner, "title": title or filename, "chunks": len(chunks)}

def list_docs(session_id: int) -> List[Dict[str, Any]]:
    """Lists all documents currently in the session's store, aggregated by owner and title."""
    store = _get_or_create_store(session_id)
    with store["lock"]:
        agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for c in store["chunks"]:
            key = (c["owner"], c["title"])
            d = agg.setdefault(key, {"title": c["title"], "owner": c["owner"], "chunks": 0})
            d["chunks"] += 1
        store["last_used"] = _now()
        return list(agg.values())
    
def delete_all_for_owner(session_id: int, owner: str):
    """Deletes all documents belonging to a specific owner within a session and rebuilds the index."""
    store = _get_or_create_store(session_id)
    with store["lock"]:
        # Filter out chunks belonging to the specified owner.
        keep = [c for c in store["chunks"] if c["owner"] != owner]
        texts = [c["text"] for c in keep]
        if texts:
            # If there are remaining chunks, rebuild the FAISS index from scratch.
            vecs = _embed(texts)
            store["index"] = faiss.IndexFlatIP(vecs.shape[1])
            store["index"].add(vecs)
        else:
            store["index"] = faiss.IndexFlatIP(store["dim"])
        store["chunks"] = keep
        store["last_used"] = _now()


def query(session_id: int, *, query_text: str, allowed_owners: List[str], k: int = 4) -> List[Dict[str, Any]]:
    """
    Performs a similarity search on the session's vector store.

    Args:
        session_id: The ID of the session to query.
        query_text: The text to search for.
        allowed_owners: A list of owner IDs whose documents are accessible.
        k: The number of top results to return.

    Returns:
        A list of the top k matching document chunks.
    """
    store = _get_or_create_store(session_id)
    with store["lock"]:
        if not store["chunks"]:
            store["last_used"] = _now()
            return []
        qv = _embed([query_text])
        D, I = store["index"].search(qv, min(k * 3, len(store["chunks"])))
        
        hits = []
        for idx in I[0]:
            if idx < 0:
                continue
            meta = store["chunks"][idx]
            # Filter results to only include chunks from allowed owners or 'shared' documents.
            if allowed_owners and (meta["owner"] not in allowed_owners and meta["owner"] != "shared"):
                continue
            hits.append({
                "title": meta["title"],
                "owner": meta["owner"],
                "filename": meta["filename"],
                "chunk_index": meta["chunk_index"],
                "snippet": meta["text"][:600],
            })
            if len(hits) >= k:
                break
        store["last_used"] = _now()
        return hits 
    
# --- TTL Sweeper ---
 
def start_sweeper(ttl_secs: int = DEFAULT_TTL_SECS, interval: int = 60):
    """
    Starts a background daemon thread to periodically clean up inactive sessions.

    Args:
        ttl_secs: The time-to-live in seconds. Sessions inactive for longer than this will be removed.
        interval: How often (in seconds) the sweeper should run.
    """
    def _run():
        while True:
            time.sleep(interval)
            cutoff = _now() - ttl_secs
            with _STORES_LOCK:
                to_del = [session_id for session_id, store in _STORES.items() if store.get("last_used", 0) < cutoff]
                for session_id in to_del:
                    del _STORES[session_id]
    
    # Create and start the sweeper thread as a daemon so it doesn't block program exit.
    t = threading.Thread(target=_run, daemon=True, name="RAG_Sweeper")
    t.start()