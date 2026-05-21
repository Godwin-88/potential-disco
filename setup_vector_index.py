"""
setup_vector_index.py — Lex Kenya vector index setup & embedding backfill
─────────────────────────────────────────────────────────────────────────
Run ONCE (or re-run safely — only unembedded nodes are processed).

Steps:
  1. Create vector indexes on Neo4j for all embeddable node types
  2. Backfill embeddings for every node that lacks one
  3. Verify all indexes are ONLINE

Usage:
    python setup_vector_index.py              # embed everything
    python setup_vector_index.py --dry-run    # preview, no writes
    python setup_vector_index.py --labels Section Case
    python setup_vector_index.py --batch-size 128   # larger batches for local backend

Node types embedded (from live graph inspection):
    High value  : Section (1903), Case (997), Clause (949), Provision (1031),
                  Article (264), Penalty (327)
    Medium value: Schedule (25), Right (26), LegalConcept (28)
    Low value   : Act (19) — title-only but useful for act-level retrieval

Embedding backends (set EMBEDDING_BACKEND in .env):
    "local"       → sentence-transformers on-device — FASTEST for bulk backfill
                    pip install sentence-transformers
    "huggingface" → HF Inference API — slow, rate-limited, no install needed
"""
import sys
import time
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import get_settings
from core.db import run_query, get_driver
from core.embeddings import embed_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

s = get_settings()


# ── Node type registry ────────────────────────────────────────────────────────
# Each entry defines:
#   fetch_cypher : pulls node_id + props (may JOIN for extra context)
#   text_fn      : builds the string to embed from those props
#
# Property names are taken from the live graph:
#   Section   : number, heading, text
#   Article   : number, heading, text
#   Case      : title, citation, year, outcome, summary, headnote, domains
#   Clause    : number, text
#   Provision : letter, text
#   Penalty   : text
#   Schedule  : name, ordinal, text
#   Right     : name, article_number
#   LegalConcept: name, domain
#   Act       : title, cap, enacted_year

FETCH_CYPHER = {
    "Section": """
        MATCH (n:Section) WHERE n.embedding IS NULL
          AND (n.text IS NOT NULL OR n.heading IS NOT NULL)
        OPTIONAL MATCH (n)-[:PART_OF*1..3]->(act:Act)
        RETURN elementId(n) AS node_id,
               n {.*, act_title: act.title} AS props
        LIMIT {batch_size}
    """,

    "Article": """
        MATCH (n:Article) WHERE n.embedding IS NULL
          AND (n.text IS NOT NULL OR n.heading IS NOT NULL)
        RETURN elementId(n) AS node_id, n {.*} AS props
        LIMIT {batch_size}
    """,

    "Case": """
        MATCH (n:Case) WHERE n.embedding IS NULL
          AND (n.title IS NOT NULL OR n.summary IS NOT NULL OR n.headnote IS NOT NULL)
        OPTIONAL MATCH (n)-[:DECIDED_BY]->(court:Court)
        RETURN elementId(n) AS node_id,
               n {.*, court_name: court.name} AS props
        LIMIT {batch_size}
    """,

    "Clause": """
        MATCH (n:Clause) WHERE n.embedding IS NULL AND n.text IS NOT NULL
        OPTIONAL MATCH (n)-[:PART_OF]->(section:Section)
        RETURN elementId(n) AS node_id,
               n {.*, section_heading: section.heading,
                       section_number: section.number} AS props
        LIMIT {batch_size}
    """,

    "Provision": """
        MATCH (n:Provision) WHERE n.embedding IS NULL AND n.text IS NOT NULL
        OPTIONAL MATCH (n)-[:PART_OF]->(parent)
        RETURN elementId(n) AS node_id,
               n {.*, parent_number: coalesce(parent.number, parent.heading)} AS props
        LIMIT {batch_size}
    """,

    "Penalty": """
        MATCH (n:Penalty) WHERE n.embedding IS NULL AND n.text IS NOT NULL
        OPTIONAL MATCH (src)-[:IMPOSES]->(n)
        OPTIONAL MATCH (src)-[:PART_OF*1..3]->(act:Act)
        RETURN elementId(n) AS node_id,
               n {.*, section_number: src.number, act_title: act.title} AS props
        LIMIT {batch_size}
    """,

    "Schedule": """
        MATCH (n:Schedule) WHERE n.embedding IS NULL
          AND (n.text IS NOT NULL OR n.name IS NOT NULL)
        OPTIONAL MATCH (n)-[:PART_OF]->(act:Act)
        RETURN elementId(n) AS node_id,
               n {.*, act_title: act.title} AS props
        LIMIT {batch_size}
    """,

    "Right": """
        MATCH (n:Right) WHERE n.embedding IS NULL AND n.name IS NOT NULL
        OPTIONAL MATCH (n)<-[:GUARANTEES]-(article:Article)
        RETURN elementId(n) AS node_id,
               n {.*, article_heading: article.heading} AS props
        LIMIT {batch_size}
    """,

    "LegalConcept": """
        MATCH (n:LegalConcept) WHERE n.embedding IS NULL AND n.name IS NOT NULL
        RETURN elementId(n) AS node_id, properties(n) AS props
        LIMIT {batch_size}
    """,

    "Act": """
        MATCH (n:Act) WHERE n.embedding IS NULL AND n.title IS NOT NULL
        RETURN elementId(n) AS node_id, properties(n) AS props
        LIMIT {batch_size}
    """,
}


def _text_for_node(label: str, props: dict) -> str:
    """Build the richest possible text string for each node type."""
    if label == "Section":
        return (
            f"Section {props.get('number', '')} "
            f"{'of ' + props['act_title'] if props.get('act_title') else ''}. "
            f"{props.get('heading', '')}. "
            f"{props.get('text', '')}"
        ).strip()

    if label == "Article":
        return (
            f"Article {props.get('number', '')} of the Constitution of Kenya 2010 — "
            f"{props.get('heading', '')}. "
            f"{props.get('text', '')}"
        ).strip()

    if label == "Case":
        return (
            f"Case: {props.get('title', '')} [{props.get('citation', '')}]. "
            f"Court: {props.get('court_name', '')}. Year: {props.get('year', '')}. "
            f"Domains: {props.get('domains', '')}. "
            f"Outcome: {props.get('outcome', '')}. "
            f"{props.get('summary', '') or props.get('headnote', '')}"
        ).strip()

    if label == "Clause":
        return (
            f"Clause {props.get('number', '')} "
            f"(Section {props.get('section_number', '')} "
            f"{props.get('section_heading', '')}). "
            f"{props.get('text', '')}"
        ).strip()

    if label == "Provision":
        return (
            f"Provision ({props.get('letter', '')})"
            f"{' of ' + props['parent_number'] if props.get('parent_number') else ''}. "
            f"{props.get('text', '')}"
        ).strip()

    if label == "Penalty":
        parts = []
        if props.get("act_title"):
            parts.append(f"Penalty under {props['act_title']}")
        if props.get("section_number"):
            parts.append(f"Section {props['section_number']}")
        parts.append(props.get("text", ""))
        return ". ".join(p for p in parts if p).strip()

    if label == "Schedule":
        return (
            f"Schedule {props.get('ordinal', '')} — {props.get('name', '')} "
            f"{'(' + props['act_title'] + ')' if props.get('act_title') else ''}. "
            f"{props.get('text', '')}"
        ).strip()

    if label == "Right":
        return (
            f"Right: {props.get('name', '')}. "
            f"Guaranteed under Article {props.get('article_number', '')} "
            f"{props.get('article_heading', '')} of the Constitution of Kenya 2010."
        ).strip()

    if label == "LegalConcept":
        return (
            f"Legal concept: {props.get('name', '')}. "
            f"Domain: {props.get('domain', '')}."
        ).strip()

    if label == "Act":
        return (
            f"Act: {props.get('title', '')}. "
            f"Cap {props.get('cap', '')}. Enacted {props.get('enacted_year', '')}."
        ).strip()

    # Generic fallback
    return str(
        props.get("text") or props.get("name") or
        props.get("title") or props.get("heading") or ""
    )


# ── Index creation ─────────────────────────────────────────────────────────────

CREATE_INDEX_CYPHER = """
CREATE VECTOR INDEX {index_name} IF NOT EXISTS
FOR (n:{label})
ON (n.embedding)
OPTIONS {{
    indexConfig: {{
        `vector.dimensions`: {dims},
        `vector.similarity_function`: 'cosine'
    }}
}}
"""

WRITE_EMBEDDING_CYPHER = "MATCH (n) WHERE elementId(n) = $node_id SET n.embedding = $embedding"


def create_indexes(labels: list[str], dry_run: bool):
    for label in labels:
        index_name = f"{s.vector_index_name}_{label.lower()}"
        cypher = CREATE_INDEX_CYPHER.format(
            index_name=index_name, label=label, dims=s.vector_dimensions
        )
        logger.info("  Creating index '%s' (%d-dim) on :%s", index_name, s.vector_dimensions, label)
        if not dry_run:
            run_query(cypher)


def verify_indexes():
    rows = run_query(
        "SHOW INDEXES YIELD name, type, state WHERE type = 'VECTOR' RETURN name, state"
    )
    if not rows:
        logger.warning("  No vector indexes found.")
        return
    for row in rows:
        icon = "✓" if row.get("state") == "ONLINE" else "⚠"
        logger.info("  %s  %-45s  %s", icon, row.get("name"), row.get("state"))


# ── Backfill ───────────────────────────────────────────────────────────────────

def backfill_label(label: str, batch_size: int, dry_run: bool) -> int:
    fetch_template = FETCH_CYPHER[label]
    fetch_cypher = fetch_template.replace("{batch_size}", str(batch_size))
    total = 0

    while True:
        rows = run_query(fetch_cypher)
        if not rows:
            break

        logger.info("  [%s] batch of %d nodes…", label, len(rows))

        # Build texts and filter empty ones
        items = []
        for row in rows:
            text = _text_for_node(label, row["props"]).strip()
            if text:
                items.append((row["node_id"], text))
            else:
                logger.debug("  Skipping empty node %s", row["node_id"])

        if not items:
            break

        if dry_run:
            for node_id, text in items[:3]:
                logger.info("  [DRY RUN] %s: %s…", node_id, text[:100])
            total += len(items)
        else:
            # True batch call — one forward pass for the whole batch (local backend)
            # or serial calls for API backends
            texts = [t for _, t in items]
            try:
                vectors = embed_batch(texts)
            except Exception as e:
                logger.error("  embed_batch failed: %s — retrying one-by-one", e)
                from core.embeddings import embed_text
                vectors = []
                for t in texts:
                    try:
                        vectors.append(embed_text(t))
                        time.sleep(0.1)
                    except Exception as e2:
                        logger.error("  Single embed failed: %s", e2)
                        vectors.append(None)

            for (node_id, _), vector in zip(items, vectors):
                if vector is None:
                    continue
                try:
                    run_query(WRITE_EMBEDDING_CYPHER, {"node_id": node_id, "embedding": vector})
                    total += 1
                except Exception as e:
                    logger.error("  Write failed for node %s: %s", node_id, e)

            # Small pause — only relevant for API backends
            if s.embedding_backend.lower() != "local":
                time.sleep(0.05)

        if len(rows) < batch_size:
            break   # last partial batch — done

    logger.info("  [%s] done — %d nodes embedded", label, total)
    return total


# ── Main ───────────────────────────────────────────────────────────────────────

ALL_LABELS = list(FETCH_CYPHER.keys())


def create_fulltext_index(dry_run: bool):
    """
    Create a full-text (BM25) index covering all major text-bearing node types.
    Required for Tier 1 hybrid retrieval.
    """
    cypher = """
    CREATE FULLTEXT INDEX legal_fulltext IF NOT EXISTS
    FOR (n:Section|Article|Case|Clause|Provision|Schedule|Right|Penalty)
    ON EACH [n.text, n.heading, n.title, n.summary, n.headnote, n.content, n.name]
    """
    logger.info("  Creating full-text index 'legal_fulltext'…")
    if not dry_run:
        run_query(cypher)
        logger.info("  Full-text index created (or already exists)")
    else:
        logger.info("  [DRY RUN] Would create full-text index")


def main():
    parser = argparse.ArgumentParser(description="Lex Kenya — vector index setup & backfill")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Preview without writing to Neo4j")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="Nodes per batch (default 64; use 128+ with local backend)")
    parser.add_argument("--labels",     nargs="*", default=None,
                        help=f"Labels to process (default: all). Options: {ALL_LABELS}")
    args = parser.parse_args()

    labels = args.labels if args.labels else ALL_LABELS

    # Validate label names
    invalid = [l for l in labels if l not in FETCH_CYPHER]
    if invalid:
        parser.error(f"Unknown labels: {invalid}. Valid: {ALL_LABELS}")

    logger.info("═══════════════════════════════════════════")
    logger.info("  Lex Kenya — Vector Index Setup")
    logger.info("  Embedding backend : %s", s.embedding_backend)
    logger.info("  Model             : %s", s.hf_embedding_model)
    logger.info("  Dimensions        : %d", s.vector_dimensions)
    logger.info("  Batch size        : %d", args.batch_size)
    logger.info("  Dry run           : %s", args.dry_run)
    logger.info("  Labels            : %s", labels)
    logger.info("═══════════════════════════════════════════")

    get_driver()

    logger.info("\n[1/4] Creating full-text index (for BM25 hybrid retrieval)…")
    create_fulltext_index(dry_run=args.dry_run)

    logger.info("\n[2/4] Creating vector indexes…")
    create_indexes(labels, dry_run=args.dry_run)

    logger.info("\n[3/4] Backfilling embeddings…")
    grand_total = 0
    for label in labels:
        grand_total += backfill_label(label, args.batch_size, dry_run=args.dry_run)
    logger.info("Grand total nodes embedded: %d", grand_total)

    logger.info("\n[4/4] Verifying indexes…")
    if not args.dry_run:
        verify_indexes()

    logger.info("\n✓ Done. Start the API with:  uvicorn main:app --reload")


if __name__ == "__main__":
    main()
