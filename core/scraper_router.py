"""
core/scraper_router.py — FastAPI router for user-triggered case law scraping

Endpoints:
  POST /api/scraper/run      — trigger a scrape run (async background task)
  GET  /api/scraper/status   — poll the current / last run status + live log
  GET  /api/scraper/history  — summary of all completed runs this session
  GET  /api/scraper/courts   — list available courts with their current case counts

The scraper runs as a FastAPI BackgroundTask so the POST returns immediately
with a run_id. The client polls /status for progress.

Only one scrape run is allowed at a time — a 409 is returned if one is running.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from core.scraper import COURTS, ScrapeRun, run_scrape

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scraper", tags=["Case Law Scraper"])

# ── In-process run store ───────────────────────────────────────────────────────

_current_run: dict[str, Any] | None = None   # the actively running job
_run_history: list[dict] = []                # completed runs (session lifetime)


# ── Request / Response schemas ─────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    courts: list[str] | None = Field(
        default=None,
        description=(
            "Court codes to scrape. Leave empty to scrape all five courts. "
            "Valid values: kesc, keca, kehc, keelrc, keelc"
        ),
        examples=[["kehc", "keca"]],
    )
    max_pages: int = Field(
        default=10, ge=1, le=50,
        description="Listing pages to fetch per court (1 page ≈ 10–20 cases)",
    )
    max_cases: int = Field(
        default=200, ge=1, le=1000,
        description="Hard cap on total new cases ingested in this run",
    )
    delay_seconds: float = Field(
        default=1.5, ge=0.5, le=10.0,
        description="Politeness delay between HTTP requests (seconds)",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "courts":        ["kehc", "keca"],
                "max_pages":     5,
                "max_cases":     100,
                "delay_seconds": 1.5,
            }
        }


class ScrapeStatusResponse(BaseModel):
    run_id:       str
    status:       str          # pending | running | completed | failed
    courts:       list[str]
    new_cases:    int
    errors:       int
    started_at:   str
    completed_at: str | None
    log:          list[str]    # live log lines


class ScrapeHistoryItem(BaseModel):
    run_id:      str
    status:      str
    courts:      list[str]
    new_cases:   int
    errors:      int
    started_at:  str
    completed_at: str | None


# ── Background task ────────────────────────────────────────────────────────────

def _run_background(run_id: str, req: ScrapeRequest):
    """Executed by FastAPI BackgroundTasks — runs the scraper and updates state."""
    global _current_run, _run_history

    def progress(msg: str):
        if _current_run and _current_run["run_id"] == run_id:
            _current_run["log"].append(msg)

    try:
        result: ScrapeRun = run_scrape(
            courts        = req.courts,
            max_pages     = req.max_pages,
            max_cases     = req.max_cases,
            delay         = req.delay_seconds,
            progress_cb   = progress,
        )
        if _current_run and _current_run["run_id"] == run_id:
            _current_run["status"]       = result.status
            _current_run["new_cases"]    = result.new_cases
            _current_run["errors"]       = result.errors
            _current_run["completed_at"] = result.completed_at
            _current_run["log"]          = result.log

        _run_history.append({
            "run_id":       run_id,
            "status":       result.status,
            "courts":       result.courts,
            "new_cases":    result.new_cases,
            "errors":       result.errors,
            "started_at":   result.started_at,
            "completed_at": result.completed_at,
        })

    except Exception as e:
        logger.exception("Background scrape run %s failed", run_id)
        if _current_run and _current_run["run_id"] == run_id:
            _current_run["status"]       = "failed"
            _current_run["completed_at"] = datetime.now(timezone.utc).isoformat()
            _current_run["log"].append(f"FATAL: {e}")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/run",
    response_model=ScrapeStatusResponse,
    status_code=202,
    summary="Trigger a case law scrape run",
    description=(
        "Launches an async background scrape of new.kenyalaw.org. "
        "Returns immediately with a run_id — poll GET /api/scraper/status for progress. "
        "Returns 409 if a scrape is already running."
    ),
)
async def trigger_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    global _current_run

    # Validate court codes
    if req.courts:
        invalid = [c for c in req.courts if c not in COURTS]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown court codes: {invalid}. Valid: {list(COURTS.keys())}",
            )

    # Reject if already running
    if _current_run and _current_run["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail=(
                f"A scrape run is already in progress (run_id={_current_run['run_id']}). "
                "Poll GET /api/scraper/status to monitor it."
            ),
        )

    run_id   = str(uuid.uuid4())
    now      = datetime.now(timezone.utc).isoformat()
    courts   = req.courts or list(COURTS.keys())

    _current_run = {
        "run_id":       run_id,
        "status":       "running",
        "courts":       courts,
        "new_cases":    0,
        "errors":       0,
        "started_at":   now,
        "completed_at": None,
        "log":          [f"Run {run_id} queued at {now}"],
    }

    background_tasks.add_task(_run_background, run_id, req)

    logger.info("Scrape run %s triggered | courts=%s max_pages=%d max_cases=%d",
                run_id, courts, req.max_pages, req.max_cases)

    return ScrapeStatusResponse(**_current_run)


@router.get(
    "/status",
    response_model=ScrapeStatusResponse,
    summary="Poll current scrape run status",
    description="Returns the status and live log of the current (or most recent) run.",
)
async def scrape_status():
    if not _current_run:
        raise HTTPException(status_code=404, detail="No scrape run has been triggered yet.")
    return ScrapeStatusResponse(**_current_run)


@router.get(
    "/history",
    response_model=list[ScrapeHistoryItem],
    summary="Scrape run history",
    description="Returns summary of all scrape runs this session (most recent first).",
)
async def scrape_history():
    return list(reversed(_run_history))


@router.get(
    "/courts",
    summary="Available courts with current case counts",
    description="Lists the five scrapable courts and how many cases each has in the graph.",
)
async def list_scrapable_courts():
    from core.db import run_query
    rows = run_query("""
        MATCH (c:Case)-[:DECIDED_BY]->(court:Court)
        RETURN court.name AS court_name, count(c) AS case_count,
               max(c.year) AS latest_year
        ORDER BY case_count DESC
    """)
    court_stats = {r["court_name"]: r for r in rows}

    return {
        "courts": [
            {
                "code":        code,
                "name":        name,
                "case_count":  court_stats.get(name, {}).get("case_count", 0),
                "latest_year": court_stats.get(name, {}).get("latest_year"),
            }
            for code, name in COURTS.items()
        ],
        "total_cases": sum(r.get("case_count", 0) for r in court_stats.values()),
    }
