"""
core/embeddings.py — Embedding service

Backends (set EMBEDDING_BACKEND in .env):
  - "local"       → sentence-transformers running on-device (fastest for bulk,
                    no API keys, no rate limits) — RECOMMENDED for backfill
                    pip install sentence-transformers
                    Default model: BAAI/bge-m3 (1024-dim), auto-downloaded on first run.
  - "huggingface" → HF Inference API (no GPU needed, but slow + rate-limited)
  - "anthropic"   → Voyage-3 (1024-dim)
  - "gemini"      → text-embedding-004 (768-dim)
  - "openai"      → text-embedding-3-small (1536-dim)

VECTOR_DIMENSIONS must match your chosen model:
  BGE-M3 (local/hf)      → 1024
  BGE-base-en-v1.5       → 768
  BGE-small-en-v1.5      → 384
  text-embedding-004     → 768
  text-embedding-3-small → 1536
"""
from __future__ import annotations
import logging
from config import get_settings

logger = logging.getLogger(__name__)

# Module-level cache so the model is loaded once per process
_local_model = None


def embed_text(text: str) -> list[float]:
    """Return a float vector for the given text (single item)."""
    s = get_settings()
    backend = s.embedding_backend.lower()

    if backend == "local":
        return _embed_local_batch([text], s)[0]
    elif backend == "huggingface":
        return _embed_huggingface(text, s)
    elif backend == "anthropic":
        return _embed_voyage(text, s.anthropic_api_key)
    elif backend == "gemini":
        return _embed_gemini(text, s.gemini_api_key)
    elif backend == "openai":
        return _embed_openai(text, s.openai_api_key)
    else:
        raise ValueError(f"Unknown embedding backend: {backend}")


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts efficiently.
    The 'local' backend encodes the entire batch in one forward pass —
    much faster than calling embed_text() in a loop.
    """
    if not texts:
        return []
    s = get_settings()
    backend = s.embedding_backend.lower()

    if backend == "local":
        return _embed_local_batch(texts, s)
    # All other backends are serial (API rate limits make true batching risky)
    return [embed_text(t) for t in texts]


# ──────────────────────────────────────────────────────────────────────────────
# Local backend — sentence-transformers (on-device, no API, true batching)
# ──────────────────────────────────────────────────────────────────────────────

def _embed_local_batch(texts: list[str], s) -> list[list[float]]:
    """
    Run sentence-transformers on the local CPU/GPU.
    Model is cached in memory after the first call.

    Install: pip install sentence-transformers
    The model (~570 MB for BGE-M3) is downloaded from HF Hub on first use
    and cached in ~/.cache/huggingface/hub/.
    """
    global _local_model
    if _local_model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is not installed.\n"
                "Run: pip install sentence-transformers"
            )
        model_name = s.hf_embedding_model  # reuse the same model name from .env
        logger.info("Loading local embedding model '%s' (first call only)…", model_name)
        _local_model = SentenceTransformer(model_name)
        logger.info("Model loaded. Embedding dimension: %d", _local_model.get_sentence_embedding_dimension())

    vectors = _local_model.encode(
        texts,
        batch_size=64,          # tune up/down depending on your RAM
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 100,
    )
    return [v.tolist() for v in vectors]


# ──────────────────────────────────────────────────────────────────────────────
# HuggingFace Inference API (remote, free tier)
# ──────────────────────────────────────────────────────────────────────────────

def _embed_huggingface(text: str, s) -> list[float]:
    """HF Inference API — any feature-extraction model (e.g. BAAI/bge-m3)."""
    import httpx
    url = f"{s.hf_embedding_endpoint.rstrip('/')}/{s.hf_embedding_model}"
    headers = {"Authorization": f"Bearer {s.hf_api_token}"}
    response = httpx.post(url, headers=headers, json={"inputs": text}, timeout=30.0)
    response.raise_for_status()
    result = response.json()
    # HF returns [[...]] for batch input or [...] for a single string
    if isinstance(result, list) and result and isinstance(result[0], list):
        return result[0]
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Cloud backends
# ──────────────────────────────────────────────────────────────────────────────

def _embed_voyage(text: str, api_key: str) -> list[float]:
    """Anthropic Voyage-3 via the voyage-ai client."""
    try:
        import voyageai
        client = voyageai.Client(api_key=api_key)
        result = client.embed([text], model="voyage-3", input_type="query")
        return result.embeddings[0]
    except ImportError:
        logger.warning("voyageai package not found, falling back to mock embedding")
        return _mock_embedding(1024)


def _embed_gemini(text: str, api_key: str) -> list[float]:
    """Google text-embedding-004."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_query",
    )
    return result["embedding"]


def _embed_openai(text: str, api_key: str) -> list[float]:
    """OpenAI text-embedding-3-small."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(model="text-embedding-3-small", input=text)
    return response.data[0].embedding


def _mock_embedding(dim: int) -> list[float]:
    """Zero vector for local dev without API keys. Do not use in production."""
    return [0.0] * dim
