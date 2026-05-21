"""
finetune/export_pairs.py — Export training pairs from Neo4j for BGE-M3 fine-tuning

Extracts three types of training signal already encoded in the graph:

1. CASE → SECTION (CITES edge)
   Query  = case summary / headnote
   Positive = the section text the case cites
   Hard negative = a different section from the same Act (not cited)

2. CASE → ARTICLE (CITES edge)
   Query  = case summary
   Positive = the constitutional article text cited

3. QUESTION → SECTION (from QA pairs if available)
   Query  = legal question
   Positive = the most relevant section
   (uses any existing QA pairs stored as QAPair nodes, else skips)

Output: JSONL file at finetune/training_pairs.jsonl
  Each line: {"query": "...", "positive": "...", "negative": "..."}

Usage:
    cd /home/ed/projects/files
    python finetune/export_pairs.py --output finetune/training_pairs.jsonl --limit 5000

Then run finetune/finetune_embeddings.py to train.
"""
from __future__ import annotations

import json
import argparse
import logging
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.subgraph import export_citation_pairs
from core.db import run_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── Additional pair types ──────────────────────────────────────────────────────

CASE_ARTICLE_CYPHER = """
MATCH (c:Case)-[:CITES]->(a:Article)
WHERE c.summary IS NOT NULL OR c.headnote IS NOT NULL
RETURN
    coalesce(c.summary, c.headnote)  AS query_text,
    coalesce(a.text, a.content, '')  AS pos_text,
    c.title                          AS case_name,
    a.number                         AS article_number
ORDER BY rand()
LIMIT $limit
"""

# Hard negative for articles: different article in same chapter
ARTICLE_HARD_NEG_CYPHER = """
MATCH (c:Case)-[:CITES]->(a:Article)-[:PART_OF]->(ch:Chapter)
                                  <-[:PART_OF]-(neg:Article)
WHERE NOT (c)-[:CITES]->(neg) AND neg.text IS NOT NULL
  AND elementId(neg) <> elementId(a)
WITH c, neg, rand() AS r ORDER BY r
RETURN
    coalesce(c.summary, c.headnote) AS query_text,
    coalesce(neg.text, '')          AS neg_text
LIMIT $limit
"""

QA_PAIRS_CYPHER = """
MATCH (qa:QAPair)
WHERE qa.question IS NOT NULL AND qa.answer IS NOT NULL
RETURN qa.question AS query_text, qa.answer AS pos_text
LIMIT $limit
"""


def export_all_pairs(limit: int = 5000) -> list[dict]:
    """
    Export all training pair types from the graph.
    Returns deduplicated list of {query, positive, negative} dicts.
    """
    all_pairs: list[dict] = []
    seen_queries: set[str] = set()

    def add(pairs: list[dict]):
        for p in pairs:
            q = p.get("query", "").strip()
            if q and q not in seen_queries and len(q) > 30:
                seen_queries.add(q)
                all_pairs.append(p)

    # Type 1: Case → Section (main signal)
    logger.info("Exporting Case→Section citation pairs…")
    pairs1 = export_citation_pairs(limit=limit)
    add(pairs1)
    logger.info("  %d Case→Section pairs", len(pairs1))

    # Type 2: Case → Article
    logger.info("Exporting Case→Article citation pairs…")
    pos_rows  = run_query(CASE_ARTICLE_CYPHER, {"limit": limit})
    neg_rows  = run_query(ARTICLE_HARD_NEG_CYPHER, {"limit": limit})
    neg_pool  = {}
    for r in neg_rows:
        neg_pool.setdefault(r["query_text"], []).append(r["neg_text"])

    pairs2 = []
    for r in pos_rows:
        q = (r.get("query_text") or "").strip()
        p = (r.get("pos_text") or "").strip()
        if q and p:
            pairs2.append({
                "query":    q,
                "positive": p,
                "negative": (neg_pool.get(q, [""])[0]),
                "metadata": {"case": r.get("case_name",""), "article": r.get("article_number","")},
            })
    add(pairs2)
    logger.info("  %d Case→Article pairs", len(pairs2))

    # Type 3: QA pairs (if the graph has them from the fine-tuning notebook)
    logger.info("Checking for QAPair nodes…")
    try:
        qa_rows = run_query(QA_PAIRS_CYPHER, {"limit": limit})
        pairs3 = [
            {"query": r["query_text"].strip(), "positive": r["pos_text"].strip(), "negative": ""}
            for r in qa_rows
            if r.get("query_text") and r.get("pos_text")
        ]
        add(pairs3)
        logger.info("  %d QA pairs", len(pairs3))
    except Exception:
        logger.info("  No QAPair nodes found — skipping")

    logger.info("Total training pairs: %d (deduplicated)", len(all_pairs))
    return all_pairs


def write_jsonl(pairs: list[dict], output_path: str):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for pair in pairs:
            line = {
                "query":    pair["query"],
                "positive": pair["positive"],
                "negative": pair.get("negative", ""),
            }
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    logger.info("Wrote %d pairs to %s", len(pairs), path)


def main():
    parser = argparse.ArgumentParser(description="Export Neo4j citation pairs for BGE-M3 fine-tuning")
    parser.add_argument("--output", default="finetune/training_pairs.jsonl",
                        help="Output JSONL file path")
    parser.add_argument("--limit",  type=int, default=5000,
                        help="Max pairs per type (default 5000)")
    parser.add_argument("--stats",  action="store_true",
                        help="Print dataset statistics after export")
    args = parser.parse_args()

    pairs = export_all_pairs(limit=args.limit)
    write_jsonl(pairs, args.output)

    if args.stats:
        with_neg = sum(1 for p in pairs if p.get("negative"))
        logger.info("=== Dataset stats ===")
        logger.info("  Total pairs        : %d", len(pairs))
        logger.info("  With hard negatives: %d (%.0f%%)", with_neg, 100*with_neg/max(len(pairs),1))
        avg_q_len = sum(len(p["query"]) for p in pairs) / max(len(pairs), 1)
        avg_p_len = sum(len(p["positive"]) for p in pairs) / max(len(pairs), 1)
        logger.info("  Avg query length   : %.0f chars", avg_q_len)
        logger.info("  Avg positive length: %.0f chars", avg_p_len)


if __name__ == "__main__":
    main()
