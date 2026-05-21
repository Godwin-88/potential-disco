"""
core/retrieval.py — Tier 1 retrieval improvements

Three enhancements over the baseline cosine-only vector search:

1. QUERY REWRITING
   The user's question is rewritten into three legal framings by the LLM:
   - original question (unchanged)
   - statute-focused framing  ("Which section of which Act…")
   - case-focused framing     ("Which court decisions have held…")
   All three are embedded and searched independently; results are pooled.

2. HYBRID SEARCH  (Dense + Sparse)
   - Dense  : existing vector index (semantic similarity)
   - Sparse : Neo4j full-text index (BM25-style exact term matching)
   Legal text has precise terminology (section numbers, "fiduciary", "eKLR")
   that BM25 handles better than dense vectors.

3. RECIPROCAL RANK FUSION (RRF)
   The multiple ranked lists (vector × 3 rewrites + BM25) are merged via RRF
   which is robust to score-scale differences between retrieval methods.

4. CITATION BOOST
   After fusion, scores are propagated one hop through CITES/PART_OF edges:
   if Case A is a strong hit and it cites Section X, Section X's score rises.
   This surfaces the statutory basis of retrieved cases automatically.
"""
from __future__ import annotations

import logging
from typing import Any

from config import get_settings
from core.db import run_query
from core.embeddings import embed_text
from core.llm import call_llm

logger = logging.getLogger(__name__)

# ── Full-text index query ─────────────────────────────────────────────────────

FULLTEXT_SEARCH_CYPHER = """
CALL db.index.fulltext.queryNodes($index_name, $query_string, {limit: $top_k})
YIELD node, score
RETURN
    elementId(node)                                                        AS node_id,
    labels(node)[0]                                                        AS label,
    coalesce(node.name, node.title, node.heading, node.number, node.id)   AS title,
    coalesce(node.text, node.content, node.summary, node.headnote, '')    AS text,
    score                                                                   AS bm25_score
"""

# ── Vector search (reused from graphrag.py) ───────────────────────────────────

VECTOR_SEARCH_CYPHER = """
CALL db.index.vector.queryNodes($index_name, $top_k, $query_vector)
YIELD node, score
RETURN
    elementId(node)                                                        AS node_id,
    labels(node)[0]                                                        AS label,
    coalesce(node.name, node.title, node.heading, node.number, node.id)   AS title,
    coalesce(node.text, node.content, node.summary, node.headnote, '')    AS text,
    score                                                                   AS vector_score
ORDER BY score DESC
LIMIT $top_k
"""

# ── Citation propagation ──────────────────────────────────────────────────────

CITATION_NEIGHBOURS_CYPHER = """
UNWIND $node_ids AS nid
MATCH (n) WHERE elementId(n) = nid
OPTIONAL MATCH (n)-[:CITES]->(cited)
OPTIONAL MATCH (n)-[:PART_OF]->(parent)
OPTIONAL MATCH (citing)-[:CITES]->(n)
RETURN
    nid                             AS source_id,
    collect(DISTINCT elementId(cited))   AS cites,
    collect(DISTINCT elementId(parent))  AS part_of,
    collect(DISTINCT elementId(citing))  AS cited_by
"""

# ── Query rewriting prompt ────────────────────────────────────────────────────

REWRITE_SYSTEM = """You are a Kenyan legal research assistant.
Given a user question, produce exactly three alternative phrasings as a JSON array.
Return ONLY the JSON array — no explanation, no markdown."""

REWRITE_USER = """Original question: {question}

Produce a JSON array of exactly 3 strings:
[
  "<statute-focused framing: which section / Act covers this?>",
  "<case-focused framing: which court decisions / judgments apply?>",
  "<constitutional framing: which constitutional article is the basis?>"
]"""


# ── Public functions ──────────────────────────────────────────────────────────

def rewrite_query(question: str) -> list[str]:
    """
    Ask the LLM to produce 3 legal framings of the question.
    Returns [statute_framing, case_framing, constitutional_framing].
    Falls back to [question] on any error so the pipeline always continues.
    """
    s = get_settings()
    if not s.enable_query_rewriting:
        return []
    try:
        import json
        raw = call_llm(
            user=REWRITE_USER.format(question=question),
            system=REWRITE_SYSTEM,
            max_tokens=300,
            temperature=0.2,
            json_mode=True,
        )
        rewrites = json.loads(raw)
        if isinstance(rewrites, list):
            return [str(r) for r in rewrites if r][:3]
    except Exception as e:
        logger.warning("Query rewriting failed (%s) — using original only", e)
    return []


def vector_search(query_text: str, top_k: int) -> list[dict]:
    """Embed query_text and run vector search."""
    s = get_settings()
    vec = embed_text(query_text)
    rows = run_query(VECTOR_SEARCH_CYPHER, {
        "index_name":  s.vector_index_name,
        "top_k":       top_k,
        "query_vector": vec,
    })
    return rows


def bm25_search(query_text: str, top_k: int) -> list[dict]:
    """
    Full-text BM25 search via Neo4j full-text index.
    Requires the 'legal_fulltext' index to exist (created by setup_vector_index.py).
    Gracefully returns [] if the index doesn't exist yet.
    """
    s = get_settings()
    if not s.enable_bm25_hybrid:
        return []
    try:
        # Escape Lucene special characters, keep quoted phrases for section numbers
        safe_query = _escape_lucene(query_text)
        rows = run_query(FULLTEXT_SEARCH_CYPHER, {
            "index_name":  s.fulltext_index_name,
            "query_string": safe_query,
            "top_k":       top_k,
        })
        return rows
    except Exception as e:
        logger.warning("BM25 search failed (%s) — continuing with vector only", e)
        return []


def hybrid_search(question: str, top_k: int) -> list[dict]:
    """
    Full Tier 1 retrieval:
      1. Rewrite question into legal framings
      2. Vector search for original + all rewrites
      3. BM25 search on original question
      4. Merge with RRF
      5. Return top_k merged candidates with merged_score field
    """
    # Step 1 — collect all query variants
    rewrites = rewrite_query(question)
    all_queries = [question] + rewrites
    logger.info("Retrieval: %d query variants (original + %d rewrites)", len(all_queries), len(rewrites))

    # Step 2 — vector search for each variant
    ranked_lists: list[list[str]] = []
    node_metadata: dict[str, dict] = {}   # node_id → best metadata seen

    for q in all_queries:
        hits = vector_search(q, top_k)
        ranked_list = []
        for h in hits:
            nid = h["node_id"]
            ranked_list.append(nid)
            if nid not in node_metadata:
                node_metadata[nid] = {
                    "node_id":      nid,
                    "label":        h.get("label", ""),
                    "title":        h.get("title", ""),
                    "text":         h.get("text", ""),
                    "vector_score": h.get("vector_score", 0.0),
                    "bm25_score":   0.0,
                }
        ranked_lists.append(ranked_list)
        logger.debug("Vector search (%s…): %d hits", q[:40], len(hits))

    # Step 3 — BM25 search
    bm25_hits = bm25_search(question, top_k)
    bm25_list = []
    for h in bm25_hits:
        nid = h["node_id"]
        bm25_list.append(nid)
        if nid not in node_metadata:
            node_metadata[nid] = {
                "node_id":      nid,
                "label":        h.get("label", ""),
                "title":        h.get("title", ""),
                "text":         h.get("text", ""),
                "vector_score": 0.0,
                "bm25_score":   h.get("bm25_score", 0.0),
            }
        else:
            node_metadata[nid]["bm25_score"] = h.get("bm25_score", 0.0)
    if bm25_list:
        ranked_lists.append(bm25_list)
        logger.debug("BM25 search: %d hits", len(bm25_hits))

    # Step 4 — RRF merge
    rrf_scores = _reciprocal_rank_fusion(ranked_lists)

    # Step 5 — Attach scores, return top_k
    results = []
    for node_id, rrf_score in rrf_scores[:top_k * 2]:   # keep buffer for citation boost
        meta = node_metadata.get(node_id, {"node_id": node_id, "label": "", "title": "", "text": ""})
        meta["rrf_score"] = rrf_score
        results.append(meta)

    logger.info("Hybrid search: %d unique candidates after RRF", len(results))
    return results


def apply_citation_boost(
    candidates: list[dict],
    boost_factor: float = 0.15,
) -> list[dict]:
    """
    Propagate RRF scores one hop through CITES and PART_OF edges.

    For every candidate node:
      - Nodes it CITES get  +boost_factor * rrf_score
      - Nodes it is PART_OF get  +boost_factor * 0.5 * rrf_score
      - Nodes that CITE it get  +boost_factor * 0.3 * rrf_score

    New nodes discovered this way are added to the candidate pool.
    Returns candidates re-sorted by boosted_score.
    """
    s = get_settings()
    if not s.enable_citation_boost:
        for c in candidates:
            c["boosted_score"] = c.get("rrf_score", 0.0)
        return candidates

    node_ids = [c["node_id"] for c in candidates]
    scores: dict[str, float] = {c["node_id"]: c.get("rrf_score", 0.0) for c in candidates}

    try:
        rows = run_query(CITATION_NEIGHBOURS_CYPHER, {"node_ids": node_ids})
    except Exception as e:
        logger.warning("Citation boost query failed: %s", e)
        for c in candidates:
            c["boosted_score"] = c.get("rrf_score", 0.0)
        return candidates

    for row in rows:
        src_score = scores.get(row["source_id"], 0.0)
        for nid in (row.get("cites") or []):
            scores[nid] = scores.get(nid, 0.0) + boost_factor * src_score
        for nid in (row.get("part_of") or []):
            scores[nid] = scores.get(nid, 0.0) + boost_factor * 0.5 * src_score
        for nid in (row.get("cited_by") or []):
            scores[nid] = scores.get(nid, 0.0) + boost_factor * 0.3 * src_score

    # Re-attach boosted scores (and pull metadata for newly discovered nodes)
    existing_ids = {c["node_id"] for c in candidates}
    new_ids = [nid for nid in scores if nid not in existing_ids and scores[nid] > 0.005]

    all_candidates = list(candidates)
    if new_ids:
        new_meta = _fetch_node_metadata(new_ids[:20])   # cap to avoid huge batches
        all_candidates.extend(new_meta)

    for c in all_candidates:
        c["boosted_score"] = scores.get(c["node_id"], c.get("rrf_score", 0.0))

    all_candidates.sort(key=lambda x: x["boosted_score"], reverse=True)
    logger.info("After citation boost: %d candidates", len(all_candidates))
    return all_candidates


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Classic RRF: score(d) = Σ 1/(k + rank(d)) across all lists."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, node_id in enumerate(ranked):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _fetch_node_metadata(node_ids: list[str]) -> list[dict]:
    """Pull label + text for a list of node IDs (used after citation boost)."""
    if not node_ids:
        return []
    try:
        rows = run_query("""
            UNWIND $ids AS nid
            MATCH (n) WHERE elementId(n) = nid
            RETURN
                elementId(n) AS node_id,
                labels(n)[0] AS label,
                coalesce(n.name, n.title, n.heading, n.number, n.id, '') AS title,
                coalesce(n.text, n.content, n.summary, n.headnote, '')   AS text
        """, {"ids": node_ids})
        for r in rows:
            r.setdefault("vector_score", 0.0)
            r.setdefault("bm25_score",   0.0)
            r.setdefault("rrf_score",    0.0)
        return rows
    except Exception as e:
        logger.warning("_fetch_node_metadata failed: %s", e)
        return []


def _escape_lucene(text: str) -> str:
    """
    Escape Lucene special characters for Neo4j full-text queries.
    Keeps the query readable while preventing parse errors.
    """
    # Remove characters that break Lucene parsing
    special = r'\+-&|!(){}[]^"~*?:/'
    escaped = []
    for ch in text:
        if ch in special:
            escaped.append(f"\\{ch}")
        else:
            escaped.append(ch)
    return "".join(escaped)
