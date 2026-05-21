"""
core/reranker.py — Tier 2 re-ranking

Two independent improvements after the Tier 1 candidate pool is assembled:

1. CROSS-ENCODER RE-RANKING
   A small cross-encoder model (ms-marco-MiniLM-L-6-v2, ~80 MB) scores
   (query, passage) pairs jointly — unlike cosine similarity it sees both
   texts at once, catching relevance signals that embeddings miss.
   Requires: pip install sentence-transformers

   Gracefully degrades to score passthrough if the package is not installed.

2. COMMUNITY-AWARE CONTEXT SELECTION
   After re-ranking, the top-N nodes are selected to maximise coverage across
   different legal "communities" (Acts, constitutional domains, case law areas).
   This prevents all 8 context slots being filled by nodes from the same Act.

   Strategy:
     a) Try Neo4j GDS Weakly Connected Components to find communities
     b) Fall back to label-based grouping if GDS is unavailable (Aura Free)
     c) Round-robin selection across communities until max_citations filled
"""
from __future__ import annotations

import logging
from collections import defaultdict

from config import get_settings
from core.db import run_query

logger = logging.getLogger(__name__)

# Cross-encoder model cache
_cross_encoder = None


# ── Cross-encoder re-ranking ──────────────────────────────────────────────────

def cross_encode(query: str, candidates: list[dict]) -> list[dict]:
    """
    Score each candidate against the query using a cross-encoder.
    Adds 'ce_score' to each candidate dict and re-sorts.
    Falls back gracefully if sentence-transformers is not installed.
    """
    s = get_settings()
    if not s.enable_cross_encoder or not candidates:
        for c in candidates:
            c.setdefault("ce_score", c.get("boosted_score", c.get("rrf_score", 0.0)))
        return candidates

    model = _load_cross_encoder(s.cross_encoder_model)
    if model is None:
        for c in candidates:
            c.setdefault("ce_score", c.get("boosted_score", c.get("rrf_score", 0.0)))
        return candidates

    pairs = [(query, _passage(c)) for c in candidates]
    try:
        scores = model.predict(pairs, show_progress_bar=False)
        for c, score in zip(candidates, scores):
            c["ce_score"] = float(score)
        candidates.sort(key=lambda x: x["ce_score"], reverse=True)
        logger.info("Cross-encoder scored %d candidates", len(candidates))
    except Exception as e:
        logger.warning("Cross-encoder scoring failed: %s", e)
        for c in candidates:
            c.setdefault("ce_score", c.get("boosted_score", 0.0))

    return candidates


def _load_cross_encoder(model_name: str):
    global _cross_encoder
    if _cross_encoder is not None:
        return _cross_encoder
    try:
        from sentence_transformers import CrossEncoder
        logger.info("Loading cross-encoder '%s'…", model_name)
        _cross_encoder = CrossEncoder(model_name, max_length=512)
        return _cross_encoder
    except ImportError:
        logger.warning(
            "sentence-transformers not installed — cross-encoder disabled.\n"
            "Run: pip install sentence-transformers"
        )
        return None
    except Exception as e:
        logger.warning("Failed to load cross-encoder: %s", e)
        return None


def _passage(candidate: dict) -> str:
    """Build a compact passage string from a candidate's metadata."""
    parts = []
    label = candidate.get("label", "")
    title = candidate.get("title", "")
    text  = candidate.get("text", "")
    if label and title:
        parts.append(f"[{label}] {title}")
    if text:
        parts.append(text[:400])
    return " ".join(parts) if parts else title or ""


# ── Community-aware context selection ────────────────────────────────────────

def community_select(candidates: list[dict], max_citations: int) -> list[dict]:
    """
    Select up to max_citations nodes ensuring diversity across legal communities.

    Algorithm:
      1. Assign each node a community_id via GDS WCC or label-based fallback
      2. Sort nodes within each community by their ranking score
      3. Round-robin pick one node per community until max_citations reached

    This ensures the context window covers multiple Acts/domains rather than
    being saturated by nodes from one Act.
    """
    s = get_settings()
    if not s.enable_community_packing or len(candidates) <= max_citations:
        return candidates[:max_citations]

    # Assign communities
    communities = _assign_communities(candidates)

    # Group by community
    buckets: dict[str, list[dict]] = defaultdict(list)
    for node in candidates:
        cid = communities.get(node["node_id"], node.get("label", "unknown"))
        buckets[cid].append(node)

    # Sort each bucket by score (best first)
    score_key = lambda x: x.get("ce_score", x.get("boosted_score", x.get("rrf_score", 0.0)))
    for bucket in buckets.values():
        bucket.sort(key=score_key, reverse=True)

    # Round-robin across communities
    selected: list[dict] = []
    community_order = sorted(buckets.keys(),
                             key=lambda cid: score_key(buckets[cid][0]),
                             reverse=True)
    pointers = {cid: 0 for cid in community_order}

    while len(selected) < max_citations:
        added_this_round = False
        for cid in community_order:
            if len(selected) >= max_citations:
                break
            idx = pointers[cid]
            if idx < len(buckets[cid]):
                selected.append(buckets[cid][idx])
                pointers[cid] += 1
                added_this_round = True
        if not added_this_round:
            break

    logger.info(
        "Community selection: %d candidates → %d selected across %d communities",
        len(candidates), len(selected), len(buckets),
    )
    return selected


def _assign_communities(candidates: list[dict]) -> dict[str, str]:
    """
    Try GDS WCC for structural communities; fall back to act/label grouping.
    Returns {node_id: community_id}.
    """
    node_ids = [c["node_id"] for c in candidates]

    # Attempt GDS Weakly Connected Components
    try:
        rows = run_query("""
            MATCH (n) WHERE elementId(n) IN $ids
            CALL gds.wcc.stream({
                nodeQuery: 'MATCH (n) WHERE elementId(n) IN $ids RETURN id(n) AS id',
                relationshipQuery: 'MATCH (a)-[:PART_OF|CITES|DERIVES_AUTHORITY_FROM]->(b)
                                    WHERE elementId(a) IN $ids AND elementId(b) IN $ids
                                    RETURN id(a) AS source, id(b) AS target'
            })
            YIELD nodeId, componentId
            RETURN toString(nodeId) AS node_id, toString(componentId) AS community_id
        """, {"ids": node_ids})
        if rows:
            return {r["node_id"]: r["community_id"] for r in rows}
    except Exception:
        pass  # GDS not available on Aura Free — use fallback

    # Fallback: assign community by Act ancestry or label
    return _label_based_communities(candidates)


def _label_based_communities(candidates: list[dict]) -> dict[str, str]:
    """
    Fetch the parent Act (or Chapter for constitutional nodes) for each node
    and use that as the community ID. Nodes with no Act default to their label.
    """
    node_ids = [c["node_id"] for c in candidates]
    try:
        rows = run_query("""
            UNWIND $ids AS nid
            MATCH (n) WHERE elementId(n) = nid
            OPTIONAL MATCH (n)-[:PART_OF*1..4]->(act:Act)
            OPTIONAL MATCH (n)-[:PART_OF*1..4]->(ch:Chapter)
            RETURN
                nid AS node_id,
                coalesce(act.title, ch.title, labels(n)[0], 'unknown') AS community_id
        """, {"ids": node_ids})
        return {r["node_id"]: r["community_id"] for r in rows}
    except Exception as e:
        logger.warning("Label-based community assignment failed: %s", e)
        return {c["node_id"]: c.get("label", "unknown") for c in candidates}
