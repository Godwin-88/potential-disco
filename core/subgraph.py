"""
core/subgraph.py — Tier 3: Subgraph summarisation

Instead of packing raw node text into the LLM context, each node's 2-hop
neighbourhood is summarised by the LLM into a single dense structured string:

  "Section 142 Companies Act 2015 prohibits a director from voting on board
   resolutions in which they have a direct or indirect personal interest.
   Interpreted by the High Court in ABC v XYZ [2019] eKLR to cover indirect
   shareholding. Penalty: personal liability + potential voiding of transaction."

This compresses ~8 nodes worth of raw text into richer, denser context that
the final LLM can reason over more reliably.

The summariser is DISABLED by default (each node = 1 extra LLM call).
Enable with ENABLE_SUBGRAPH_SUMMARY=true in .env.

Also exposes export_citation_pairs() for fine-tuning BGE-M3 (see finetune/).
"""
from __future__ import annotations

import logging
from typing import Any

from core.db import run_query
from core.llm import call_llm
from config import get_settings

logger = logging.getLogger(__name__)

# ── 2-hop neighbourhood query ─────────────────────────────────────────────────

NEIGHBOURHOOD_CYPHER = """
MATCH (n) WHERE elementId(n) = $node_id

// Immediate neighbours (1 hop)
OPTIONAL MATCH (n)-[r1]-(nb1)
WITH n, collect(DISTINCT {
    rel:   type(r1),
    dir:   CASE WHEN startNode(r1) = n THEN 'out' ELSE 'in' END,
    label: labels(nb1)[0],
    title: coalesce(nb1.title, nb1.name, nb1.heading, nb1.number, ''),
    text:  coalesce(nb1.text, nb1.summary, nb1.headnote, '')[..200]
})[..12] AS hop1

// Parent act for context
OPTIONAL MATCH (n)-[:PART_OF*1..4]->(act:Act)
OPTIONAL MATCH (n)-[:PART_OF*1..4]->(ch:Chapter)

RETURN
    labels(n)[0]                                                       AS label,
    coalesce(n.title, n.name, n.heading, n.number, '')                 AS title,
    coalesce(n.text, n.content, n.summary, n.headnote, '')[..600]      AS text,
    coalesce(act.title, '')                                            AS act_title,
    coalesce(ch.title, '')                                             AS chapter_title,
    hop1
"""

# ── Summarisation prompt ──────────────────────────────────────────────────────

SUMMARISE_SYSTEM = """You are a Kenyan legal text analyst. Given a legal node and its
graph neighbourhood, produce a single dense paragraph (3-5 sentences) that captures:
1. What this provision/case/concept says (the rule)
2. Its legal authority source (which Act / constitutional article)
3. How it has been applied or interpreted (relevant cases if any)
4. Practical consequence: penalty, obligation, or right created

Be precise. Use legal terminology. Include section numbers and case citations inline."""

SUMMARISE_USER = """Node type: {label}
Title: {title}
{act_context}

Full text:
{text}

Graph neighbourhood (related nodes):
{neighbours}

Write a single dense paragraph summarising this node for use in legal Q&A context."""


def summarise_node(node_id: str) -> str:
    """
    Fetch a node's 2-hop neighbourhood and produce an LLM summary.
    Returns the summary string, or falls back to raw text on error.
    """
    s = get_settings()

    rows = run_query(NEIGHBOURHOOD_CYPHER, {"node_id": node_id})
    if not rows:
        return ""

    row = rows[0]
    label    = row.get("label", "")
    title    = row.get("title", "")
    text     = row.get("text", "")
    hop1     = row.get("hop1") or []

    act_context = ""
    if row.get("act_title"):
        act_context = f"Parent Act: {row['act_title']}"
    elif row.get("chapter_title"):
        act_context = f"Chapter: {row['chapter_title']} (Constitution of Kenya 2010)"

    # Format neighbourhood
    nb_lines = []
    for nb in hop1[:10]:
        if not nb.get("title"):
            continue
        direction = "→" if nb.get("dir") == "out" else "←"
        nb_lines.append(
            f"  {direction} [{nb.get('rel','')}] {nb.get('label','')} "
            f"'{nb.get('title','')}': {nb.get('text','')[:100]}"
        )
    neighbours_text = "\n".join(nb_lines) if nb_lines else "None"

    try:
        summary = call_llm(
            user=SUMMARISE_USER.format(
                label=label,
                title=title,
                act_context=act_context,
                text=text or "(no text)",
                neighbours=neighbours_text,
            ),
            system=SUMMARISE_SYSTEM,
            max_tokens=300,
            temperature=0.0,
        )
        return summary.strip()
    except Exception as e:
        logger.warning("Subgraph summarisation failed for %s: %s", node_id, e)
        return text  # fall back to raw text


def summarise_nodes(nodes: list[dict]) -> dict[str, str]:
    """
    Summarise a list of candidate nodes.
    Returns {node_id: summary_text}.
    Only runs if ENABLE_SUBGRAPH_SUMMARY=true.
    """
    s = get_settings()
    summaries: dict[str, str] = {}

    if not s.enable_subgraph_summary:
        for node in nodes:
            summaries[node["node_id"]] = node.get("text", "")
        return summaries

    logger.info("Subgraph summarisation: %d nodes…", len(nodes))
    for node in nodes:
        nid = node["node_id"]
        summaries[nid] = summarise_node(nid)

    return summaries


# ── Citation pair export (for fine-tuning BGE-M3) ─────────────────────────────

CITATION_PAIRS_CYPHER = """
// Positive pairs: Case ↔ cited Section/Article
MATCH (c:Case)-[:CITES]->(target)
WHERE target:Section OR target:Article
OPTIONAL MATCH (c)-[:DECIDED_BY]->(court:Court)
OPTIONAL MATCH (target)-[:PART_OF*1..3]->(act:Act)
RETURN
    coalesce(c.summary, c.headnote, c.title, '')                            AS query_text,
    coalesce(target.text, target.content, '')                               AS pos_text,
    c.title                                                                 AS case_name,
    coalesce(act.title, '')                                                 AS act_name,
    coalesce(target.number, target.heading, '')                             AS target_ref,
    court.name                                                              AS court
ORDER BY rand()
LIMIT $limit
"""

HARD_NEGATIVE_CYPHER = """
// Hard negatives: same Act, different section (not cited by this case)
MATCH (c:Case)-[:CITES]->(cited:Section)-[:PART_OF*1..3]->(act:Act)
      <-[:PART_OF*1..3]-(neg:Section)
WHERE NOT (c)-[:CITES]->(neg)
  AND neg.text IS NOT NULL
  AND elementId(neg) <> elementId(cited)
WITH c, neg, rand() AS r
ORDER BY r
RETURN
    coalesce(c.summary, c.headnote, c.title, '') AS query_text,
    coalesce(neg.text, '')                        AS neg_text
LIMIT $limit
"""


def export_citation_pairs(limit: int = 5000) -> list[dict]:
    """
    Export training pairs for BGE-M3 fine-tuning.

    Returns a list of dicts:
      {
        "query":    str,   # case summary / question
        "positive": str,   # the section the case cites
        "negative": str,   # a hard negative (same Act, not cited)
      }

    These are fed to finetune/finetune_embeddings.py which trains with
    MultipleNegativesRankingLoss.
    """
    logger.info("Exporting citation pairs (limit=%d)…", limit)

    pos_rows = run_query(CITATION_PAIRS_CYPHER, {"limit": limit})
    neg_rows = run_query(HARD_NEGATIVE_CYPHER, {"limit": limit})

    # Build a pool of negatives (query_text → list of neg_texts)
    neg_pool: dict[str, list[str]] = {}
    for row in neg_rows:
        qt = row.get("query_text", "")
        nt = row.get("neg_text", "")
        if qt and nt:
            neg_pool.setdefault(qt, []).append(nt)

    pairs = []
    for row in pos_rows:
        query    = row.get("query_text", "").strip()
        positive = row.get("pos_text", "").strip()
        if not query or not positive:
            continue
        negatives = neg_pool.get(query, [])
        negative  = negatives[0] if negatives else ""
        pairs.append({
            "query":    query,
            "positive": positive,
            "negative": negative,
            "metadata": {
                "case":   row.get("case_name", ""),
                "act":    row.get("act_name", ""),
                "ref":    row.get("target_ref", ""),
                "court":  row.get("court", ""),
            },
        })

    logger.info("Exported %d citation pairs (%d with hard negatives)",
                len(pairs), sum(1 for p in pairs if p["negative"]))
    return pairs
