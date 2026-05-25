"""
Export all nodes and relationships from a remote Neo4j AuraDB instance to JSON.
Run: python3 neo4j_export.py
Output: neo4j_dump.json
"""
import json
import os
import sys
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

URI      = os.getenv("NEO4J_URI")
USER     = os.getenv("NEO4J_USER")
PASSWORD = os.getenv("NEO4J_PASSWORD")

BATCH = 500


def export(driver):
    dump = {"nodes": [], "relationships": []}

    with driver.session() as s:
        # --- nodes ---
        node_count = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        print(f"Exporting {node_count} nodes...", flush=True)
        exported = 0
        skip = 0
        while True:
            rows = s.run(
                "MATCH (n) RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS props "
                "ORDER BY eid SKIP $skip LIMIT $limit",
                skip=skip, limit=BATCH,
            ).data()
            if not rows:
                break
            for row in rows:
                props = row["props"]
                # Convert embedding lists (they come back as lists already)
                dump["nodes"].append({
                    "eid": row["eid"],
                    "labels": row["labels"],
                    "props": props,
                })
            exported += len(rows)
            print(f"  nodes: {exported}/{node_count}", end="\r", flush=True)
            if len(rows) < BATCH:
                break
            skip += BATCH
        print()

        # --- relationships ---
        rel_count = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"Exporting {rel_count} relationships...", flush=True)
        exported = 0
        skip = 0
        while True:
            rows = s.run(
                "MATCH (a)-[r]->(b) "
                "RETURN elementId(r) AS eid, type(r) AS type, properties(r) AS props, "
                "elementId(a) AS src, elementId(b) AS tgt "
                "ORDER BY eid SKIP $skip LIMIT $limit",
                skip=skip, limit=BATCH,
            ).data()
            if not rows:
                break
            for row in rows:
                dump["relationships"].append({
                    "eid": row["eid"],
                    "type": row["type"],
                    "props": row["props"],
                    "src": row["src"],
                    "tgt": row["tgt"],
                })
            exported += len(rows)
            print(f"  rels: {exported}/{rel_count}", end="\r", flush=True)
            if len(rows) < BATCH:
                break
            skip += BATCH
        print()

    return dump


def main():
    out = os.path.join(os.path.dirname(__file__), "neo4j_dump.json")
    print(f"Connecting to {URI} ...")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        dump = export(driver)
    finally:
        driver.close()

    print(f"Writing {out} ...")
    with open(out, "w") as f:
        json.dump(dump, f)

    size_mb = os.path.getsize(out) / 1024 / 1024
    print(f"Done. {len(dump['nodes'])} nodes, {len(dump['relationships'])} rels — {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
