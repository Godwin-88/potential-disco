"""
main.py — Lex Kenya API entry point

Run with:
    uvicorn main:app --reload --port 8000

Docs available at:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from core.db import get_driver, close_driver
from core.auth           import router as auth_router
from core.qa             import router as qa_router
from core.compliance     import router as compliance_router
from core.predictor      import router as predictor_router
from core.scraper_router import router as scraper_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect to Neo4j on startup, cleanly disconnect on shutdown."""
    logger.info("Starting Lex Kenya API...")
    get_driver()          # verifies connectivity — will raise if Neo4j is unreachable
    logger.info("Neo4j connected. API ready.")
    yield
    logger.info("Shutting down — closing Neo4j driver.")
    close_driver()


app = FastAPI(
    title="Lex Kenya — Legal Intelligence API",
    description=(
        "GraphRAG-powered API over a Neo4j knowledge graph of the "
        "Constitution of Kenya 2010, Kenyan corporate and commercial Acts, "
        "regulations, and case law from the five major Kenyan courts."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow the React/Streamlit frontend during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──
app.include_router(auth_router)
app.include_router(qa_router)
app.include_router(compliance_router)
app.include_router(predictor_router)
app.include_router(scraper_router)


@app.get("/", tags=["Health"])
async def root():
    s = get_settings()
    return {
        "service": "Lex Kenya Legal Intelligence API",
        "version": "1.0.0",
        "llm_backend":       s.llm_backend,
        "embedding_backend": s.embedding_backend,
        "vector_index":      s.vector_index_name,
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    """Liveness probe — checks Neo4j connectivity."""
    try:
        from core.db import run_query_single
        result = run_query_single("RETURN 1 AS ok")
        neo4j_ok = result is not None
    except Exception as e:
        return {"status": "degraded", "neo4j": str(e)}
    return {"status": "ok", "neo4j": neo4j_ok}


@app.get("/graph/stats", tags=["Graph"])
async def graph_stats():
    """Returns node and relationship counts from the knowledge graph."""
    from core.db import run_query
    node_counts = run_query("""
        CALL apoc.meta.stats()
        YIELD labels
        RETURN labels
    """)
    # Fallback if APOC not installed
    if not node_counts:
        node_counts = run_query("""
            MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count
            ORDER BY count DESC
        """)
    rel_counts = run_query("""
        MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS count
        ORDER BY count DESC LIMIT 20
    """)
    return {"nodes": node_counts, "relationships": rel_counts}
