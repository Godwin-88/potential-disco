"""
Import nodes, relationships, and indexes into a local Neo4j instance from neo4j_dump.json.
Run AFTER starting the Docker container:
    docker compose -f docker-compose.neo4j.yml up -d
    python3 neo4j_import.py
"""
import json
import os
import sys
import time

from neo4j import GraphDatabase

LOCAL_URI      = "bolt://localhost:7688"
LOCAL_USER     = "neo4j"
LOCAL_PASSWORD = "localpassword"
DUMP_FILE      = os.path.join(os.path.dirname(__file__), "neo4j_dump.json")
BATCH          = 200


def wait_for_neo4j(driver, retries=30, delay=2):
    for i in range(retries):
        try:
            with driver.session() as s:
                s.run("RETURN 1")
            return
        except Exception:
            print(f"  Waiting for Neo4j... ({i+1}/{retries})", end="\r", flush=True)
            time.sleep(delay)
    raise RuntimeError("Neo4j did not become ready in time.")


def create_constraints_and_indexes(session):
    """Recreate RANGE, FULLTEXT, and VECTOR indexes."""
    stmts = [
        # ── RANGE (unique ID per label) ────────────────────────────────────
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Constitution)    REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Chapter)         REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Article)         REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Clause)          REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Act)             REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Section)         REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Regulation)      REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Case)            REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Court)           REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Institution)     REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:LegalConcept)    REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:LegalPrinciple)  REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Right)           REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Obligation)      REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Penalty)         REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Provision)       REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Part)            REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Schedule)        REQUIRE n.id IS UNIQUE",
        # ── FULLTEXT ───────────────────────────────────────────────────────
        "CREATE FULLTEXT INDEX article_text IF NOT EXISTS FOR (n:Article) ON EACH [n.text, n.heading]",
        "CREATE FULLTEXT INDEX case_text    IF NOT EXISTS FOR (n:Case)    ON EACH [n.summary, n.headnote, n.title]",
        "CREATE FULLTEXT INDEX concept_text IF NOT EXISTS FOR (n:LegalConcept) ON EACH [n.name, n.definition]",
        "CREATE FULLTEXT INDEX part_text    IF NOT EXISTS FOR (n:Part)    ON EACH [n.title]",
        "CREATE FULLTEXT INDEX penalty_text IF NOT EXISTS FOR (n:Penalty) ON EACH [n.text]",
        "CREATE FULLTEXT INDEX right_text   IF NOT EXISTS FOR (n:Right)   ON EACH [n.name]",
        "CREATE FULLTEXT INDEX schedule_text IF NOT EXISTS FOR (n:Schedule) ON EACH [n.text, n.name]",
        "CREATE FULLTEXT INDEX section_text IF NOT EXISTS FOR (n:Section) ON EACH [n.text, n.heading]",
        (
            "CREATE FULLTEXT INDEX legal_fulltext IF NOT EXISTS "
            "FOR (n:Section|Article|Case|Clause|Provision|Schedule|Right|Penalty) "
            "ON EACH [n.text, n.heading, n.title, n.summary, n.headnote, n.content, n.name]"
        ),
        # ── VECTOR (1024-dim, cosine) ──────────────────────────────────────
        "CREATE VECTOR INDEX legal_embeddings_act          IF NOT EXISTS FOR (n:Act)          ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX legal_embeddings_article      IF NOT EXISTS FOR (n:Article)      ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX legal_embeddings_case         IF NOT EXISTS FOR (n:Case)         ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX legal_embeddings_clause       IF NOT EXISTS FOR (n:Clause)       ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX legal_embeddings_legalconcept IF NOT EXISTS FOR (n:LegalConcept) ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX legal_embeddings_penalty      IF NOT EXISTS FOR (n:Penalty)      ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX legal_embeddings_provision    IF NOT EXISTS FOR (n:Provision)    ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX legal_embeddings_right        IF NOT EXISTS FOR (n:Right)        ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX legal_embeddings_schedule     IF NOT EXISTS FOR (n:Schedule)     ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX legal_embeddings_section      IF NOT EXISTS FOR (n:Section)      ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}",
    ]
    for stmt in stmts:
        try:
            session.run(stmt)
        except Exception as e:
            print(f"  [warn] {e}")


def batched(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def import_nodes(session, nodes):
    total = len(nodes)
    done = 0
    for batch in batched(nodes, BATCH):
        session.run(
            """
            UNWIND $rows AS row
            CALL apoc.merge.node(row.labels, {id: row.props.id}, row.props, {}) YIELD node
            RETURN count(node)
            """,
            rows=[{"labels": n["labels"], "props": n["props"], "eid": n["eid"]} for n in batch],
        )
        done += len(batch)
        print(f"  nodes: {done}/{total}", end="\r", flush=True)
    print()


def import_nodes_no_apoc(session, nodes):
    """Fallback: one MERGE per label type in batches (no APOC)."""
    from collections import defaultdict
    by_label = defaultdict(list)
    for n in nodes:
        key = tuple(sorted(n["labels"]))
        by_label[key].append(n)

    total = len(nodes)
    done = 0
    for labels, group in by_label.items():
        label_str = ":".join(f"`{l}`" for l in labels)
        for batch in batched(group, BATCH):
            session.run(
                f"""
                UNWIND $rows AS row
                MERGE (n:{label_str} {{id: row.props.id}})
                SET n = row.props
                """,
                rows=[{"props": n["props"]} for n in batch],
            )
            done += len(batch)
            print(f"  nodes: {done}/{total}", end="\r", flush=True)
    print()


def import_relationships(session, rels, eid_to_id):
    total = len(rels)
    done = 0
    from collections import defaultdict
    by_type = defaultdict(list)
    for r in rels:
        by_type[r["type"]].append(r)

    for rel_type, group in by_type.items():
        for batch in batched(group, BATCH):
            rows = []
            for r in batch:
                src_id = eid_to_id.get(r["src"])
                tgt_id = eid_to_id.get(r["tgt"])
                if src_id is None or tgt_id is None:
                    continue
                rows.append({"src": src_id, "tgt": tgt_id, "props": r["props"]})
            if not rows:
                continue
            session.run(
                f"""
                UNWIND $rows AS row
                MATCH (a {{id: row.src}}), (b {{id: row.tgt}})
                MERGE (a)-[r:`{rel_type}`]->(b)
                SET r = row.props
                """,
                rows=rows,
            )
            done += len(batch)
            print(f"  rels: {done}/{total}", end="\r", flush=True)
    print()


def check_apoc(session):
    try:
        session.run("RETURN apoc.version() AS v").single()
        return True
    except Exception:
        return False


def main():
    if not os.path.exists(DUMP_FILE):
        print(f"Dump file not found: {DUMP_FILE}")
        print("Run neo4j_export.py first.")
        sys.exit(1)

    print(f"Loading {DUMP_FILE} ...")
    with open(DUMP_FILE) as f:
        dump = json.load(f)

    nodes = dump["nodes"]
    rels  = dump["relationships"]
    print(f"  {len(nodes)} nodes, {len(rels)} relationships")

    # Build eid → id map for relationship wiring
    eid_to_id = {n["eid"]: n["props"].get("id") for n in nodes if "id" in n["props"]}

    print(f"Connecting to {LOCAL_URI} ...")
    driver = GraphDatabase.driver(LOCAL_URI, auth=(LOCAL_USER, LOCAL_PASSWORD))
    wait_for_neo4j(driver)
    print("Connected.")

    with driver.session() as s:
        has_apoc = check_apoc(s)
        print(f"APOC available: {has_apoc}")

        print("Creating constraints and indexes...")
        create_constraints_and_indexes(s)

        print(f"Importing nodes...")
        if has_apoc:
            import_nodes(s, nodes)
        else:
            import_nodes_no_apoc(s, nodes)

        print(f"Importing relationships...")
        import_relationships(s, rels, eid_to_id)

        # Verify
        n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        r = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"\nVerification: {n} nodes, {r} relationships in local DB")

    driver.close()
    print("Import complete.")


if __name__ == "__main__":
    main()
