"""
core/db.py — Neo4j driver singleton
Provides a typed query runner that returns plain dicts.
"""
from __future__ import annotations
import time
from typing import Any
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from config import get_settings
import logging

logger = logging.getLogger(__name__)
_driver: Driver | None = None

_RETRYABLE = (ServiceUnavailable, SessionExpired)
_MAX_RETRIES = 3
_RETRY_DELAY = 5  # seconds


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        s = get_settings()
        _driver = GraphDatabase.driver(
            s.neo4j_uri,
            auth=(s.neo4j_user, s.neo4j_password),
            max_connection_lifetime=1800,   # recycle connections after 30 min
            keep_alive=True,
        )
        _driver.verify_connectivity()
        logger.info("Neo4j driver connected to %s", s.neo4j_uri)
    return _driver


def _reset_driver():
    global _driver
    if _driver:
        try:
            _driver.close()
        except Exception:
            pass
        _driver = None


def run_query(cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Execute a Cypher query and return a list of plain dicts.

    Retries up to _MAX_RETRIES times on connection errors, recreating the
    driver on each attempt so stale connections don't block recovery.
    """
    params = params or {}
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with get_driver().session() as session:
                result = session.run(cypher, params)
                return [record.data() for record in result]
        except _RETRYABLE as exc:
            logger.warning(
                "Neo4j transient error (attempt %d/%d): %s — reconnecting…",
                attempt, _MAX_RETRIES, exc,
            )
            _reset_driver()
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
            else:
                raise


def run_query_single(cypher: str, params: dict[str, Any] | None = None) -> dict | None:
    """Return the first record or None."""
    rows = run_query(cypher, params)
    return rows[0] if rows else None


def close_driver():
    global _driver
    if _driver:
        _driver.close()
        _driver = None
