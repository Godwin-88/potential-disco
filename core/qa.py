"""
modules/qa.py — Q&A Module
Endpoints:
  POST /api/qa/ask        — natural language question → cited legal answer
  GET  /api/qa/trace/{id} — full citation chain for a previous answer
  GET  /api/qa/graph      — visual subgraph for the last answer (for UI)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.graphrag import retrieve_and_answer, CitedAnswer
from core.db import run_query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/qa", tags=["Q&A"])

# ──────────────────────────────────────────────
# In-memory answer store (swap for Redis in prod)
# ──────────────────────────────────────────────
_answer_store: dict[str, dict] = {}


# ──────────────────────────────────────────────
# Request / Response schemas
# ──────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        examples=["What are the requirements to incorporate a private company in Kenya?"]
    )
    max_citations: int = Field(default=8, ge=1, le=15)
    jurisdiction: str = Field(
        default="Kenya",
        description="Reserved for future multi-jurisdiction support"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "question": "Can a director of a Kenyan company vote on a matter where they have a personal interest?",
                "max_citations": 8
            }
        }


class SourceItem(BaseModel):
    label: str
    title: str
    citation_tag: str
    authority_score: float
    relevance_score: float
    act: str | None = None
    act_year: int | None = None
    section_number: str | None = None
    constitutional_article: str | None = None
    chapter: str | None = None
    article_number: str | None = None
    court: str | None = None
    year: int | None = None
    citation: str | None = None
    outcome: str | None = None
    overruled_by: str | None = None


class AskResponse(BaseModel):
    answer_id: str
    question: str
    answer: str
    sources: list[SourceItem]
    context_nodes: int
    timestamp: str
    consensus_level: str = "high"
    disputed_points: list[str] = []
    retrieval_stats: dict = {}
    disclaimer: str = (
        "This is AI-assisted legal research based on the Lex Kenya knowledge graph. "
        "It does not constitute legal advice. Consult a qualified Kenyan advocate for "
        "advice specific to your situation."
    )


class TraceResponse(BaseModel):
    answer_id: str
    question: str
    citation_chains: list[dict]
    graph_nodes: list[dict]
    graph_edges: list[dict]


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a legal question",
    description=(
        "Submit a natural language question about Kenyan law. "
        "The GraphRAG pipeline retrieves semantically similar nodes, "
        "expands the citation graph, ranks by authority, and returns "
        "an LLM-generated answer grounded in cited sources."
    )
)
async def ask(req: AskRequest) -> AskResponse:
    logger.info("Q&A ask | question='%s'", req.question[:80])

    try:
        result: CitedAnswer = retrieve_and_answer(
            question=req.question,
            top_k=req.max_citations,
        )
    except Exception as e:
        logger.exception("GraphRAG pipeline failed")
        raise HTTPException(status_code=500, detail=f"Retrieval pipeline error: {str(e)}")

    answer_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    # Persist for /trace lookups
    _answer_store[answer_id] = {
        "question":        result.query,
        "answer":          result.answer,
        "sources":         result.sources,
        "citation_chains": result.citation_chains,
        "context_nodes":   result.context_nodes,
        "timestamp":       timestamp,
    }

    return AskResponse(
        answer_id=answer_id,
        question=result.query,
        answer=result.answer,
        sources=[SourceItem(**s) for s in result.sources],
        context_nodes=result.context_nodes,
        timestamp=timestamp,
        consensus_level=result.consensus_level,
        disputed_points=result.disputed_points,
        retrieval_stats=result.retrieval_stats,
    )


@router.get(
    "/trace/{answer_id}",
    response_model=TraceResponse,
    summary="Get full citation chain for an answer",
    description=(
        "Given an answer_id from /ask, returns the full provenance chain: "
        "every source node, its expansion data, and the graph edges between them "
        "so the frontend can render a citation graph."
    )
)
async def trace(answer_id: str) -> TraceResponse:
    stored = _answer_store.get(answer_id)
    if not stored:
        raise HTTPException(
            status_code=404,
            detail=f"Answer ID '{answer_id}' not found. Answers are kept for the session lifetime."
        )

    # Build a lightweight graph representation for the UI
    # Nodes = sources, edges = relationships between them in the KG
    sources = stored["sources"]
    chains  = stored["citation_chains"]

    # Collect citation relationships between the returned sources
    citation_titles = [s.get("citation_tag") or s.get("title") for s in sources]
    graph_nodes = [
        {
            "id":    s.get("citation_tag") or s.get("title"),
            "label": s.get("label"),
            "title": s.get("title"),
            "score": s.get("authority_score"),
        }
        for s in sources
    ]

    # Pull direct edges between returned nodes from Neo4j
    graph_edges = _fetch_edges_between_sources(sources)

    return TraceResponse(
        answer_id=answer_id,
        question=stored["question"],
        citation_chains=chains,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
    )


@router.get(
    "/suggest",
    summary="Suggest related questions",
    description="Given a seed question, return related questions the user might want to ask next."
)
async def suggest(
    q: str = Query(..., min_length=5, description="The original question")
) -> dict[str, Any]:
    """
    Uses the knowledge graph to surface related legal concepts
    and frames them as follow-up questions.
    No LLM call — pure graph traversal for speed.
    """
    # Find the most central LegalConcepts and LegalPrinciples
    # near the answer space (heuristic: keyword match on concept names)
    keywords = [w.lower() for w in q.split() if len(w) > 4]
    if not keywords:
        return {"suggestions": []}

    cypher = """
    MATCH (n)
    WHERE (n:LegalConcept OR n:LegalPrinciple OR n:Act)
      AND any(kw IN $keywords WHERE toLower(coalesce(n.name, n.title, '')) CONTAINS kw)
    OPTIONAL MATCH (n)<-[:DEFINES|ESTABLISHES|APPLIES_TO]-(source)
    RETURN
        labels(n)[0]    AS label,
        coalesce(n.name, n.title) AS name,
        count(source)   AS connections
    ORDER BY connections DESC
    LIMIT 6
    """
    rows = run_query(cypher, {"keywords": keywords})

    suggestions = []
    for row in rows:
        name = row.get("name") or ""
        label = row.get("label") or ""
        if label == "Act":
            suggestions.append(f"What are the key obligations under the {name}?")
        elif label == "LegalPrinciple":
            suggestions.append(f"How have Kenyan courts applied the principle of {name}?")
        elif label == "LegalConcept":
            suggestions.append(f"How is '{name}' defined and applied in Kenyan corporate law?")

    return {"suggestions": suggestions[:5], "seed_question": q}


# ──────────────────────────────────────────────
# Helper — edges between returned source nodes
# ──────────────────────────────────────────────

def _fetch_edges_between_sources(sources: list[dict]) -> list[dict]:
    """
    Pull relationship edges between source nodes for graph visualisation.
    Uses case citation strings and section numbers for matching.
    """
    case_citations = [
        s["citation"] for s in sources
        if s.get("label") == "Case" and s.get("citation")
    ]
    section_numbers = [
        s["section_number"] for s in sources
        if s.get("label") == "Section" and s.get("section_number")
    ]

    if not case_citations and not section_numbers:
        return []

    cypher = """
    // Edges between cases (citations and overrulings)
    OPTIONAL MATCH (c1:Case)-[r1:CITES|OVERRULES]->(c2:Case)
    WHERE c1.citation IN $case_citations AND c2.citation IN $case_citations

    // Edges from cases to sections
    OPTIONAL MATCH (c3:Case)-[r2:CITES|INTERPRETS]->(s:Section)
    WHERE c3.citation IN $case_citations AND s.number IN $section_numbers

    WITH
        collect(DISTINCT {
            from:  c1.citation,
            to:    c2.citation,
            type:  type(r1)
        }) AS case_case_edges,
        collect(DISTINCT {
            from:  c3.citation,
            to:    s.number,
            type:  type(r2)
        }) AS case_section_edges

    RETURN case_case_edges + case_section_edges AS edges
    """
    rows = run_query(cypher, {
        "case_citations":  case_citations,
        "section_numbers": section_numbers,
    })

    if rows and rows[0].get("edges"):
        return [e for e in rows[0]["edges"] if e.get("from") and e.get("to")]
    return []
