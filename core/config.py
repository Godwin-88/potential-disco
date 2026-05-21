"""
config.py — Centralised settings for Lex Kenya API
Supports: anthropic, gemini, openai, openai_compatible (Groq, etc.), 
          and Hugging Face Inference API for embeddings
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Neo4j
    neo4j_uri: str = "neo4j+s://4830d4c5.databases.neo4j.io"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "GcOcvDBDjTDTMYKdjji3IwYX2Kf3IGFB-J_jLCgegPU"

    # LLM backends
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    
    # OpenAI-compatible endpoint (Groq, OpenRouter, Together, LocalAI)
    openai_compatible_base_url: str = "https://api.groq.com/openai/v1"
    openai_compatible_api_key: str = ""
    openai_compatible_model: str = "llama3-8b-8192"

    # Hugging Face Inference API (for embeddings)
    hf_api_token: str = ""  # Get from https://huggingface.co/settings/tokens
    hf_embedding_model: str = "BAAI/bge-m3"
    hf_embedding_endpoint: str = "https://api-inference.huggingface.co/pipeline/feature-extraction"

    # Backend selection
    # LLM: "anthropic" | "gemini" | "openai" | "openai_compatible"
    # Embeddings: "openai" | "huggingface" | "local" (sentence-transformers)
    llm_backend: str = "openai_compatible"
    embedding_backend: str = "huggingface"

    # Vector index — MUST match your embedding model's output dimension
    vector_index_name: str = "legal_embeddings"
    vector_dimensions: int = 1024  # BGE-M3 = 1024 | MiniLM = 384 | mpnet = 768

    # Retrieval tuning
    max_citations: int = 8
    vector_top_k: int = 5
    graph_hop_depth: int = 2

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # ── Tier 1: Retrieval improvements ───────────────────────────────────────
    enable_query_rewriting: bool = True
    enable_bm25_hybrid: bool = True
    enable_citation_boost: bool = True
    fulltext_index_name: str = "legal_fulltext"

    # ── Tier 2: Re-ranking ────────────────────────────────────────────────────
    enable_cross_encoder: bool = True
    enable_community_packing: bool = True
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # ── Tier 2: Self-consistency ──────────────────────────────────────────────
    # Set to 1 to disable (single run, cheapest). 3 = recommended.
    self_consistency_runs: int = 1

    # ── Tier 3: Subgraph summarisation ────────────────────────────────────────
    # Costs 1 extra LLM call per node — disable for low-latency deployments
    enable_subgraph_summary: bool = False

    # ── Scraper ───────────────────────────────────────────────────────────────
    scraper_delay_seconds: float = 1.5   # politeness delay between requests
    scraper_max_pages: int = 10           # listing pages per court per run
    scraper_max_cases: int = 200          # hard cap per triggered run

    # ── Auth — MVP1: Supabase ─────────────────────────────────────────────────
    # Copy from: Supabase → Settings → API → JWT Settings → JWT Secret
    supabase_jwt_secret: str = ""

    # ── Auth — MVP2: Self-hosted JWT (uncomment in core/auth.py to activate) ─
    # auth_jwt_secret: str = "lex-kenya-dev-secret-change-in-prod"
    # auth_token_expire_days: int = 7

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()