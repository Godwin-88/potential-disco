"""
core/graphrag.py — GraphRAG Retrieval Pipeline (full Tier 1 → 2 → 3)

Pipeline stages
───────────────
TIER 1 — Retrieval (core/retrieval.py)
  1a. QUERY REWRITE  — LLM generates 3 legal framings of the question
  1b. HYBRID SEARCH  — dense vector (all framings) + BM25 sparse search
  1c. RRF MERGE      — Reciprocal Rank Fusion across all ranked lists
  1d. GRAPH EXPAND   — traverse citation/hierarchy graph from each seed node
  1e. CITATION BOOST — propagate scores through CITES/PART_OF edges

TIER 2 — Re-ranking & Diversity (core/reranker.py, core/consistency.py)
  2a. CROSS-ENCODER  — joint (query, passage) scoring with ms-marco-MiniLM
  2b. COMMUNITY SEL  — round-robin selection across legal communities
  2c. SELF-CONSIST.  — run LLM N times, synthesise consensus answer

TIER 3 — Deep Understanding (core/subgraph.py)
  3a. SUBGRAPH SUMM  — LLM summarises each node's 2-hop neighbourhood
  3b. CONTEXT PACK   — pack enriched summaries into context string
  3c. LLM REASON     — grounded generation with full citation chain

Every tier can be toggled independently via .env flags.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from config import get_settings
from core.db import run_query
from core.retrieval import hybrid_search, apply_citation_boost
from core.reranker import cross_encode, community_select
from core.consistency import consistent_answer
from core.subgraph import summarise_nodes

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class LegalNode:
    node_id: str
    label: str
    title: str
    text: str
    act_or_chapter: str
    authority_score: float = 0.0
    vector_score: float = 0.0
    rrf_score: float = 0.0
    ce_score: float = 0.0
    final_score: float = 0.0
    summary: str = ""      # populated by Tier 3 subgraph summariser

    def citation_tag(self) -> str:
        if self.label == "Article":
            return f"Constitution, {self.title}"
        elif self.label == "Section":
            return f"{self.act_or_chapter}, {self.title}"
        elif self.label == "Case":
            return self.title
        elif self.label in ("LegalPrinciple", "LegalConcept"):
            return f"Principle: {self.title}"
        return self.title


@dataclass
class CitedAnswer:
    answer: str
    sources: list[dict]
    citation_chains: list[dict]
    context_nodes: int
    query: str
    consensus_level: str = "high"
    disputed_points: list[str] = field(default_factory=list)
    retrieval_stats: dict = field(default_factory=dict)


# ── Authority scoring ──────────────────────────────────────────────────────────

AUTHORITY_WEIGHTS: dict[str, float] = {
    "Constitution":          1.00,
    "Chapter":               0.95,
    "Article":               0.90,
    "Clause":                0.85,
    "Provision":             0.82,
    "Act":                   0.80,
    "Section":               0.75,
    "Part":                  0.70,
    "Subsection":            0.70,
    "Penalty":               0.70,
    "Paragraph":             0.65,
    "Schedule":              0.62,
    "Regulation":            0.60,
    "Amendment":             0.55,
    "LegalNotice":           0.50,
    "Case":                  0.72,
    "LegalPrinciple":        0.68,
    "LegalConcept":          0.50,
    "Right":                 0.85,
    "Obligation":            0.75,
}

COURT_HIERARCHY: dict[str, float] = {
    "Supreme Court":                         0.20,
    "Court of Appeal":                       0.15,
    "High Court":                            0.10,
    "Employment and Labour Relations Court": 0.08,
    "Environment and Land Court":            0.08,
}


def _authority_score(label: str, expansion: dict) -> float:
    base = AUTHORITY_WEIGHTS.get(label, 0.40)
    if label == "Case":
        court_name = expansion.get("court", "")
        for court_key, bonus in COURT_HIERARCHY.items():
            if court_key.lower() in (court_name or "").lower():
                base += bonus
                break
    return min(base, 1.0)


# ── Graph expansion (unchanged from original) ──────────────────────────────────

SECTION_EXPANSION_CYPHER = """
MATCH (s) WHERE elementId(s) = $node_id
OPTIONAL MATCH (s)-[:PART_OF]->(part:Part)-[:PART_OF]->(act:Act)
OPTIONAL MATCH (s)-[:PART_OF]->(act2:Act)
WITH s, coalesce(act, act2) AS act
OPTIONAL MATCH (act)-[:DERIVES_AUTHORITY_FROM]->(article:Article)-[:PART_OF]->(ch:Chapter)
OPTIONAL MATCH (act)-[:ENACTED_UNDER]->(article2:Article)
OPTIONAL MATCH (s)-[:IMPOSES]->(pen:Penalty)
OPTIONAL MATCH (s)-[:IMPOSES]->(obl:Obligation)
OPTIONAL MATCH (amend:Amendment)-[:AMENDS]->(s)
OPTIONAL MATCH (c:Case)-[:CITES|INTERPRETS]->(s)
OPTIONAL MATCH (c)-[:DECIDED_BY]->(court:Court)
OPTIONAL MATCH (c)-[:OVERRULES]->(older:Case)
RETURN
    s.number                            AS section_number,
    coalesce(s.heading, s.title, '')    AS section_title,
    coalesce(act.title, '')             AS act_name,
    act.enacted_year                    AS act_year,
    coalesce(article.number, article2.number)   AS constitutional_article,
    coalesce(article.heading, article2.heading) AS constitutional_article_title,
    ch.title                            AS chapter_name,
    collect(DISTINCT {text: pen.text})[..5]         AS penalties,
    collect(DISTINCT {text: obl.text})[..5]         AS obligations,
    collect(DISTINCT {
        name: c.title, citation: c.citation, year: c.year,
        outcome: c.outcome, court: court.name, overrules: older.title
    })[..5]                             AS citing_cases,
    collect(DISTINCT amend.description)[..3] AS amendments
"""

ARTICLE_EXPANSION_CYPHER = """
MATCH (a) WHERE elementId(a) = $node_id
OPTIONAL MATCH (a)-[:PART_OF]->(ch:Chapter)-[:PART_OF]->(const:Constitution)
OPTIONAL MATCH (a)-[:GUARANTEES]->(right:Right)
OPTIONAL MATCH (a)-[:DEFINES]->(concept:LegalConcept)
OPTIONAL MATCH (act:Act)-[:DERIVES_AUTHORITY_FROM]->(a)
OPTIONAL MATCH (act2:Act)-[:ENACTED_UNDER]->(a)
OPTIONAL MATCH (inst:Institution)-[:ESTABLISHED_BY]->(a)
OPTIONAL MATCH (c:Case)-[:CITES|INTERPRETS]->(a)
OPTIONAL MATCH (c)-[:DECIDED_BY]->(court:Court)
OPTIONAL MATCH (c)-[:ESTABLISHES]->(principle:LegalPrinciple)
RETURN
    a.number                                  AS article_number,
    coalesce(a.heading, a.title, '')          AS article_title,
    ch.title                                  AS chapter_name,
    collect(DISTINCT right.name)[..5]         AS guaranteed_rights,
    collect(DISTINCT concept.name)[..5]       AS defined_concepts,
    collect(DISTINCT {
        name: coalesce(act.title, act2.title),
        year: coalesce(act.enacted_year, act2.enacted_year)
    })[..5]                                   AS derived_acts,
    collect(DISTINCT inst.name)[..5]          AS institutions_established,
    collect(DISTINCT {
        name: c.title, citation: c.citation,
        year: c.year, court: court.name, principle: principle.name
    })[..5]                                   AS interpreting_cases
"""

CASE_EXPANSION_CYPHER = """
MATCH (c) WHERE elementId(c) = $node_id
OPTIONAL MATCH (c)-[:DECIDED_BY]->(court:Court)
OPTIONAL MATCH (c)-[:CITES]->(cited_section:Section)-[:PART_OF*1..2]->(act:Act)
OPTIONAL MATCH (c)-[:CITES]->(cited_article:Article)
OPTIONAL MATCH (c)-[:CITES]->(cited_case:Case)
OPTIONAL MATCH (c)-[:ESTABLISHES]->(principle:LegalPrinciple)
OPTIONAL MATCH (c)-[:OVERRULES]->(overruled:Case)
OPTIONAL MATCH (newer:Case)-[:OVERRULES]->(c)
OPTIONAL MATCH (newer)-[:DECIDED_BY]->(newer_court:Court)
RETURN
    coalesce(c.title, '')               AS case_name,
    c.citation                          AS citation,
    c.year                              AS year,
    c.outcome                           AS outcome,
    coalesce(c.summary, c.headnote, '') AS summary,
    court.name                          AS court,
    court.hierarchy_level               AS court_level,
    collect(DISTINCT {number: cited_section.number, act: act.title})[..6]  AS cited_sections,
    collect(DISTINCT {number: cited_article.number, title: cited_article.heading})[..4] AS cited_articles,
    collect(DISTINCT {name: cited_case.title, citation: cited_case.citation})[..4] AS cited_cases,
    collect(DISTINCT principle.name)[..4]  AS established_principles,
    overruled.title                     AS overrules_case,
    {name: newer.title, citation: newer.citation, court: newer_court.name} AS overruled_by_case
"""

GENERIC_EXPANSION_CYPHER = """
MATCH (n) WHERE elementId(n) = $node_id
OPTIONAL MATCH (n)-[r]-(neighbour)
RETURN
    labels(n)[0]                                                         AS label,
    coalesce(n.name, n.title, n.heading, n.number, n.text)               AS title,
    collect(DISTINCT {
        rel:   type(r),
        label: labels(neighbour)[0],
        title: coalesce(neighbour.name, neighbour.title, neighbour.heading, neighbour.number)
    })[..8]                                                              AS neighbours
"""

EXPANSION_QUERIES = {
    "Section":  SECTION_EXPANSION_CYPHER,
    "Article":  ARTICLE_EXPANSION_CYPHER,
    "Case":     CASE_EXPANSION_CYPHER,
}


def _expand_node(node_id: str, label: str) -> dict:
    cypher = EXPANSION_QUERIES.get(label, GENERIC_EXPANSION_CYPHER)
    rows = run_query(cypher, {"node_id": node_id})
    return rows[0] if rows else {}


# ── Context packing ────────────────────────────────────────────────────────────

def _pack_context(nodes: list[LegalNode], expansions: dict[str, dict],
                  summaries: dict[str, str]) -> str:
    parts: list[str] = ["=== LEGAL KNOWLEDGE GRAPH CONTEXT ===\n"]

    for i, node in enumerate(nodes, 1):
        exp = expansions.get(node.node_id, {})
        parts.append(f"[SOURCE {i}] {node.label.upper()} — {node.citation_tag()}")
        parts.append(
            f"Authority: {node.authority_score:.2f}  "
            f"Relevance: {node.vector_score:.2f}  "
            f"RRF: {node.rrf_score:.4f}"
        )

        # Use subgraph summary if available, else raw text
        display_text = summaries.get(node.node_id) or node.text
        if display_text:
            parts.append(f"Content: {display_text[:900]}")

        # Expansion details (label-specific)
        if node.label == "Section":
            if exp.get("act_name"):
                parts.append(f"Parent Act: {exp['act_name']} ({exp.get('act_year','')})")
            if exp.get("constitutional_article"):
                parts.append(
                    f"Constitutional basis: Article {exp['constitutional_article']} "
                    f"— {exp.get('constitutional_article_title','')} ({exp.get('chapter_name','')})"
                )
            for pen in (exp.get("penalties") or []):
                if pen.get("text"):
                    parts.append(f"Penalty: {pen['text']}")
            for case in (exp.get("citing_cases") or []):
                if case.get("name"):
                    parts.append(
                        f"Citing case: {case['name']} [{case.get('citation','')}] "
                        f"({case.get('court','')}, {case.get('year','')}) — {case.get('outcome','')}"
                    )

        elif node.label == "Article":
            if exp.get("chapter_name"):
                parts.append(f"Chapter: {exp['chapter_name']}")
            for right in (exp.get("guaranteed_rights") or []):
                if right:
                    parts.append(f"Right guaranteed: {right}")
            for case in (exp.get("interpreting_cases") or []):
                if case.get("name"):
                    parts.append(
                        f"Interpreting case: {case['name']} [{case.get('citation','')}] "
                        f"({case.get('court','')}) — principle: {case.get('principle','')}"
                    )

        elif node.label == "Case":
            if exp.get("court"):
                parts.append(f"Court: {exp['court']} | Year: {exp.get('year','')} | Outcome: {exp.get('outcome','')}")
            for sec in (exp.get("cited_sections") or []):
                if sec.get("number"):
                    parts.append(f"Cites section: {sec['number']} ({sec.get('act','')})")
            for p in (exp.get("established_principles") or []):
                if p:
                    parts.append(f"Established principle: {p}")
            if exp.get("overrules_case"):
                parts.append(f"Overrules: {exp['overrules_case']}")
            ob = exp.get("overruled_by_case") or {}
            if ob.get("name"):
                parts.append(f"⚠ OVERRULED BY: {ob['name']} [{ob.get('citation','')}] ({ob.get('court','')})")

        parts.append("")

    return "\n".join(parts)


# ── LLM prompts ───────────────────────────────────────────────────────────────

QA_SYSTEM_PROMPT = """You are Lex Kenya, a precise legal research assistant specialising
in Kenyan law. You answer questions about the Constitution of Kenya 2010, corporate and
commercial statutes, regulations, and case law from Kenyan courts.

STRICT RULES:
1. Base every statement EXCLUSIVELY on the [SOURCE] blocks provided. Do not use general
   legal knowledge if it contradicts or extends beyond those sources.
2. Cite sources inline using the format [SOURCE N] after every factual claim.
3. If a case has been marked "OVERRULED BY", note this prominently and rely on the
   overruling case instead.
4. If the sources are insufficient to answer, say so clearly — do not fabricate.
5. Structure your answer as:
   a) Direct answer (2–4 sentences)
   b) Legal basis (statute sections and articles relied on)
   c) Relevant case law (cases that interpret or apply the law)
   d) Important caveats or limitations
6. Use plain English accessible to a non-lawyer, but preserve legal terms of art with
   brief explanations in parentheses.
7. Never give advice — state what the law provides, not what a person should do."""

QA_USER_TEMPLATE = """{context}

=== QUESTION ===
{question}

Answer based strictly on the sources above. Cite [SOURCE N] after every claim."""


# ── Source list builder ────────────────────────────────────────────────────────

def _build_source_list(nodes: list[LegalNode], expansions: dict[str, dict]) -> list[dict]:
    sources = []
    for n in nodes:
        exp = expansions.get(n.node_id, {})
        src: dict[str, Any] = {
            "label":            n.label,
            "title":            n.title,
            "citation_tag":     n.citation_tag(),
            "authority_score":  round(n.authority_score, 3),
            "relevance_score":  round(n.vector_score, 3),
            "rrf_score":        round(n.rrf_score, 4),
        }
        if n.label == "Section":
            src["act"]              = exp.get("act_name")
            src["act_year"]         = exp.get("act_year")
            src["section_number"]   = exp.get("section_number")
            src["constitutional_article"] = exp.get("constitutional_article")
        elif n.label == "Article":
            src["chapter"]          = exp.get("chapter_name")
            src["article_number"]   = exp.get("article_number")
        elif n.label == "Case":
            src["court"]            = exp.get("court")
            src["year"]             = exp.get("year")
            src["citation"]         = exp.get("citation") or n.title
            src["outcome"]          = exp.get("outcome")
            src["overruled_by"]     = (exp.get("overruled_by_case") or {}).get("name")
        sources.append(src)
    return sources


# ── Public API ─────────────────────────────────────────────────────────────────

def retrieve_and_answer(question: str, top_k: int | None = None) -> CitedAnswer:
    """
    Full GraphRAG pipeline: Tier 1 → Tier 2 → Tier 3 → LLM → return.

    Args:
        question: Natural language legal question.
        top_k:    Override the default vector_top_k from settings.

    Returns:
        CitedAnswer with answer, sources, citation chains, and retrieval stats.
    """
    s = get_settings()
    k = top_k or s.vector_top_k

    logger.info("GraphRAG pipeline | question='%s'", question[:80])
    stats: dict[str, Any] = {}

    # ── TIER 1: Hybrid retrieval ──────────────────────────────────────────────
    raw_candidates = hybrid_search(question, top_k=k)
    stats["candidates_before_boost"] = len(raw_candidates)

    if not raw_candidates:
        logger.warning("Hybrid search returned 0 results")
        return CitedAnswer(
            answer="I could not find relevant legal sources in the knowledge graph for this question.",
            sources=[], citation_chains=[], context_nodes=0, query=question,
        )

    boosted = apply_citation_boost(raw_candidates)
    stats["candidates_after_boost"] = len(boosted)

    # ── Expand each candidate for authority scoring ───────────────────────────
    expansions: dict[str, dict] = {}
    nodes_raw: list[LegalNode] = []

    for cand in boosted[:s.max_citations * 3]:   # expand a buffer larger than max_citations
        node_id = cand["node_id"]
        label   = cand.get("label", "Unknown")
        exp     = _expand_node(node_id, label)
        expansions[node_id] = exp

        auth = _authority_score(label, exp)
        node = LegalNode(
            node_id=node_id,
            label=label,
            title=cand.get("title", ""),
            text=cand.get("text", ""),
            act_or_chapter=exp.get("act_name") or exp.get("chapter_name") or exp.get("act_title") or "",
            authority_score=auth,
            vector_score=cand.get("vector_score", 0.0),
            rrf_score=cand.get("rrf_score", cand.get("boosted_score", 0.0)),
        )
        nodes_raw.append(node)

    # ── TIER 2a: Cross-encoder re-ranking ─────────────────────────────────────
    ce_input = [{"node_id": n.node_id, "text": n.text, "title": n.title,
                 "label": n.label, "rrf_score": n.rrf_score,
                 "boosted_score": n.rrf_score} for n in nodes_raw]
    ce_output = cross_encode(question, ce_input)
    ce_scores = {r["node_id"]: r.get("ce_score", 0.0) for r in ce_output}

    for node in nodes_raw:
        node.ce_score = ce_scores.get(node.node_id, 0.0)
        # Combined final score: authority + rrf + cross-encoder
        node.final_score = (
            0.35 * node.authority_score +
            0.30 * node.rrf_score * 20 +    # scale RRF (typically ~0.02) to ~0.4
            0.35 * (node.ce_score + 10) / 20  # normalise cross-encoder from [-10,10] → [0,1]
        )

    nodes_raw.sort(key=lambda n: n.final_score, reverse=True)

    # ── TIER 2b: Community-aware selection ────────────────────────────────────
    ce_sel_input = [{"node_id": n.node_id, "label": n.label, "ce_score": n.ce_score,
                     "boosted_score": n.final_score, "rrf_score": n.rrf_score,
                     "text": n.text, "title": n.title} for n in nodes_raw]
    selected_meta = community_select(ce_sel_input, s.max_citations)
    selected_ids  = {m["node_id"] for m in selected_meta}
    top_nodes     = [n for n in nodes_raw if n.node_id in selected_ids][:s.max_citations]

    stats["nodes_after_community_select"] = len(top_nodes)
    logger.info("Top %d nodes selected for context", len(top_nodes))

    # ── TIER 3: Subgraph summarisation ────────────────────────────────────────
    node_dicts = [{"node_id": n.node_id, "text": n.text} for n in top_nodes]
    summaries = summarise_nodes(node_dicts)
    for node in top_nodes:
        node.summary = summaries.get(node.node_id, "")

    # ── Context packing ───────────────────────────────────────────────────────
    context = _pack_context(top_nodes, expansions, summaries)

    # ── TIER 2c / LLM reasoning with self-consistency ────────────────────────
    consistency_result = consistent_answer(
        context=context,
        question=question,
        qa_system_prompt=QA_SYSTEM_PROMPT,
        qa_user_template=QA_USER_TEMPLATE,
    )

    answer_text      = consistency_result["answer"]
    consensus_level  = consistency_result.get("consensus_level", "high")
    disputed_points  = consistency_result.get("disputed_points", [])

    # ── Sources & citation chains ─────────────────────────────────────────────
    sources = _build_source_list(top_nodes, expansions)

    citation_chains = [
        {
            "source_index": i + 1,
            "node":         n.citation_tag(),
            "final_score":  round(n.final_score, 4),
            "expansion_summary": {
                key: val for key, val in (expansions.get(n.node_id) or {}).items()
                if val and key not in ("amendments",)
            },
        }
        for i, n in enumerate(top_nodes)
    ]

    stats["retrieval_tiers"] = {
        "query_rewriting":   s.enable_query_rewriting,
        "bm25_hybrid":       s.enable_bm25_hybrid,
        "citation_boost":    s.enable_citation_boost,
        "cross_encoder":     s.enable_cross_encoder,
        "community_packing": s.enable_community_packing,
        "subgraph_summary":  s.enable_subgraph_summary,
        "self_consistency":  s.self_consistency_runs,
    }

    return CitedAnswer(
        answer=answer_text,
        sources=sources,
        citation_chains=citation_chains,
        context_nodes=len(top_nodes),
        query=question,
        consensus_level=consensus_level,
        disputed_points=disputed_points,
        retrieval_stats=stats,
    )
