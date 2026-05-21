"""
core/scraper.py — Kenya Law web scraper

Scrapes judgments from new.kenyalaw.org (AKN format) across five courts
and writes them into the Neo4j knowledge graph with full CITES edges.

URL structure (confirmed from existing graph data):
  Individual: https://new.kenyalaw.org/akn/ke/judgment/{court}/{year}/{number}/eng@{date}
  Listing:    https://new.kenyalaw.org/judgments/?court={COURT_CODE}&page={n}
              https://new.kenyalaw.org/search/?type=judgment&court={COURT_CODE}

Anti-blocking:
  Uses httpx with Chrome-like headers. Optionally uses cloudscraper
  (pip install cloudscraper) if installed — preferred for Cloudflare bypass.

Idempotent:
  Existing case URLs are loaded from Neo4j before every run.
  Cases already in the graph are silently skipped.

CITES edge extraction:
  Article references  — "Article N" / "Art. N" patterns
  Section references  — "section N of the X Act" patterns
  Act references      — matches against Act titles in the graph
  Case references     — [YEAR] eKLR / [YEAR] KLR citation patterns
"""
from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

# ── Court registry ─────────────────────────────────────────────────────────────

COURTS = {
    "kesc":   "Supreme Court of Kenya",
    "keca":   "Court of Appeal",
    "kehc":   "High Court",
    "keelrc": "Employment and Labour Relations Court",
    "keelc":  "Environment and Land Court",
}

# Listing page URL — kenyalaw.org uses this pattern for paginated results
LISTING_URL = "https://new.kenyalaw.org/judgments/?court={court}&page={page}"
# Alternative search endpoint (tried if listing returns nothing)
SEARCH_URL  = "https://new.kenyalaw.org/search/?type=judgment&court={court}&page={page}"
# AKN base
AKN_BASE    = "https://new.kenyalaw.org/akn/ke/judgment"

# ── Regex patterns for citation extraction ─────────────────────────────────────

RE_ARTICLE  = re.compile(r'\bArticle\s+(\d+[A-Za-z]?(?:\(\d+\))?)', re.IGNORECASE)
RE_SECTION  = re.compile(
    r'\bsection\s+(\d+[A-Za-z]?(?:\(\d+\))?)\s+of\s+(?:the\s+)?([A-Z][^\.,]{4,60}?(?:Act|Regulation|Rules))',
    re.IGNORECASE,
)
RE_CITATION = re.compile(r'\[(\d{4})\]\s+(?:e?KLR|KLR|EKLR)', re.IGNORECASE)
RE_AKN_HREF = re.compile(r'/akn/ke/judgment/([^/"]+)/(\d{4})/(\d+)/eng@[\d-]+')
RE_DATE_URL = re.compile(r'eng@(\d{4}-\d{2}-\d{2})')


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ScrapedCase:
    url:         str
    court_code:  str
    year:        int
    number:      int
    title:       str      = ""
    citation:    str      = ""
    case_number: str      = ""
    date:        str      = ""
    outcome:     str      = ""
    judges:      str      = ""
    summary:     str      = ""
    headnote:    str      = ""
    domains:     str      = ""
    full_text:   str      = ""

    # Extracted references for CITES edges
    cited_articles:  list[str] = field(default_factory=list)   # article numbers
    cited_sections:  list[dict] = field(default_factory=list)  # [{number, act_title}]
    cited_act_titles: list[str] = field(default_factory=list)
    cited_case_citations: list[str] = field(default_factory=list)


@dataclass
class ScrapeRun:
    started_at:   str = ""
    completed_at: str = ""
    courts:       list[str] = field(default_factory=list)
    new_cases:    int = 0
    skipped:      int = 0
    errors:       int = 0
    status:       str = "pending"   # pending | running | completed | failed
    log:          list[str] = field(default_factory=list)


# ── HTTP client ────────────────────────────────────────────────────────────────

def _make_client():
    """
    Return an HTTP client with Chrome-like headers.
    Prefers cloudscraper (better Cloudflare bypass) over plain httpx.
    """
    try:
        import cloudscraper
        cs = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        logger.info("Using cloudscraper for requests")
        return cs, "cloudscraper"
    except ImportError:
        pass

    import httpx
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    client = httpx.Client(headers=headers, follow_redirects=True, timeout=30.0)
    return client, "httpx"


def _get(client, client_type: str, url: str) -> str | None:
    """Fetch URL, return HTML text or None on error."""
    try:
        if client_type == "cloudscraper":
            resp = client.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.text
            logger.warning("HTTP %d for %s", resp.status_code, url)
            return None
        else:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text
            logger.warning("HTTP %d for %s", resp.status_code, url)
            return None
    except Exception as e:
        logger.error("GET %s failed: %s", url, e)
        return None


# ── Listing page parser ────────────────────────────────────────────────────────

def _parse_listing(html: str, existing_urls: set[str]) -> list[str]:
    """
    Extract AKN judgment URLs from a listing page.
    Returns new URLs not already in the graph.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
    except ImportError:
        # Fallback: regex extraction without BeautifulSoup
        found = RE_AKN_HREF.findall(html)
        urls = []
        for court_code, year, number in found:
            # Need to reconstruct full URL from AKN path
            # Find the full href in raw HTML
            pass
        # Raw regex on href attributes
        hrefs = re.findall(r'href="(/akn/ke/judgment/[^"]+)"', html)
        urls = []
        for href in hrefs:
            full = f"https://new.kenyalaw.org{href}"
            if full not in existing_urls:
                urls.append(full)
        return list(dict.fromkeys(urls))   # deduplicate, preserve order

    # BeautifulSoup path
    urls = []
    for a in soup.find_all("a", href=RE_AKN_HREF):
        href = a.get("href", "")
        if not href.startswith("http"):
            href = f"https://new.kenyalaw.org{href}"
        if href not in existing_urls:
            urls.append(href)

    return list(dict.fromkeys(urls))


def _has_next_page(html: str) -> bool:
    """Check whether the listing page has a 'next' pagination link."""
    return bool(
        re.search(r'rel=["\']next["\']', html, re.IGNORECASE) or
        re.search(r'class=["\'][^"\']*next[^"\']*["\']', html, re.IGNORECASE) or
        re.search(r'>\s*Next\s*<', html, re.IGNORECASE)
    )


# ── Case page parser ───────────────────────────────────────────────────────────

def _parse_case(html: str, url: str) -> ScrapedCase | None:
    """
    Parse an individual AKN case page.
    Returns a ScrapedCase or None if parsing fails badly.
    """
    m = RE_AKN_HREF.search(url)
    if not m:
        logger.warning("Cannot parse court/year/number from URL: %s", url)
        return None

    court_code = m.group(1).lower()
    year       = int(m.group(2))
    number     = int(m.group(3))

    case = ScrapedCase(url=url, court_code=court_code, year=year, number=number)

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        _parse_case_bs4(soup, case)
    except ImportError:
        _parse_case_regex(html, case)

    # Always extract citations from whatever text we have
    text_for_citations = case.full_text or case.summary or case.headnote
    if text_for_citations:
        _extract_citations(text_for_citations, case)

    # Default title if nothing was found
    if not case.title:
        case.title = f"{COURTS.get(court_code, court_code)} Judgment {year}/{number}"

    return case


def _parse_case_bs4(soup, case: ScrapedCase):
    """Extract case metadata using BeautifulSoup."""
    # Title — try multiple common patterns
    for selector in [
        "h1.judgment-title", "h1.akn-FRBRalias", ".case-title h1",
        "h1", ".judgment-header h1"
    ]:
        tag = soup.select_one(selector)
        if tag and tag.get_text(strip=True):
            case.title = tag.get_text(strip=True)
            break

    # Metadata table / dl elements
    for dt in soup.find_all(["dt", "th"]):
        key   = dt.get_text(strip=True).lower().rstrip(":")
        value_tag = dt.find_next_sibling(["dd", "td"])
        value = value_tag.get_text(strip=True) if value_tag else ""
        if not value:
            continue
        if "citation" in key:
            case.citation = value
        elif "case number" in key or "case no" in key:
            case.case_number = value
        elif "date" in key and "deliver" in key:
            case.date = value
        elif "judge" in key:
            case.judges = value
        elif "court" in key and not case.court_code:
            pass  # already set from URL

    # Try to extract from meta tags (some AKN sites use Dublin Core)
    for meta in soup.find_all("meta"):
        name    = meta.get("name", "") or meta.get("property", "")
        content = meta.get("content", "")
        if not content:
            continue
        if "title" in name.lower() and not case.title:
            case.title = content
        elif "date" in name.lower() and not case.date:
            case.date = content

    # Main judgment text — AKN structure uses <section> or .akn-judgment
    body = (
        soup.select_one(".akn-judgment") or
        soup.select_one("article.judgment") or
        soup.select_one("main") or
        soup.find("body")
    )
    if body:
        # Extract headnote (first substantial paragraph)
        paragraphs = body.find_all("p")
        if paragraphs:
            first_paras = " ".join(p.get_text(" ", strip=True) for p in paragraphs[:3])
            case.headnote = first_paras[:500]

        # Full text (capped at 8000 chars for citation extraction)
        case.full_text = body.get_text(" ", strip=True)[:8000]

    # Outcome — look for common patterns
    outcome_patterns = [
        r'(?:appeal|petition|application|suit)\s+(?:is\s+)?(?:hereby\s+)?(allowed|dismissed|granted|rejected|struck out)',
        r'(judgment|order)\s+(?:is\s+)?(?:entered\s+)?(?:for|in favour of)\s+(?:the\s+)?(plaintiff|claimant|appellant|respondent|defendant)',
    ]
    text_lower = (case.full_text or "").lower()
    for pat in outcome_patterns:
        m = re.search(pat, text_lower)
        if m:
            case.outcome = m.group(0)[:100]
            break


def _parse_case_regex(html: str, case: ScrapedCase):
    """Fallback regex parser when BeautifulSoup is unavailable."""
    # Title from <title> tag
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if m:
        case.title = re.sub(r'<[^>]+>', '', m.group(1)).strip()[:200]

    # Strip tags, extract text
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    case.full_text = text[:8000]
    case.headnote  = text[:500]

    # Basic citation pattern
    m = re.search(r'\[(\d{4})\]\s+(?:e?KLR|KLR)', text)
    if m:
        case.citation = m.group(0)


def _extract_citations(text: str, case: ScrapedCase):
    """Extract CITES references from judgment text."""
    # Articles
    case.cited_articles = list({m.group(1) for m in RE_ARTICLE.finditer(text)})

    # Section + Act references
    cited_sections = []
    for m in RE_SECTION.finditer(text):
        cited_sections.append({
            "number":    m.group(1),
            "act_title": m.group(2).strip(),
        })
    case.cited_sections = cited_sections

    # Case citations
    case.cited_case_citations = list({m.group(0) for m in RE_CITATION.finditer(text)})

    # Act title mentions (simple heuristic: look for known Acts)
    # We do the actual matching against graph Acts in the ingestor


# ── Neo4j ingestor ─────────────────────────────────────────────────────────────

UPSERT_CASE_CYPHER = """
MERGE (c:Case {url: $url})
SET
    c.title       = $title,
    c.citation    = $citation,
    c.case_number = $case_number,
    c.date        = $date,
    c.year        = $year,
    c.outcome     = $outcome,
    c.judges      = $judges,
    c.headnote    = $headnote,
    c.summary     = $summary,
    c.domains     = $domains,
    c.scraped_at  = $scraped_at
RETURN elementId(c) AS node_id
"""

MERGE_COURT_CYPHER = """
MERGE (court:Court {name: $court_name})
WITH court
MATCH (c:Case {url: $url})
MERGE (c)-[:DECIDED_BY]->(court)
"""

CITES_ARTICLE_CYPHER = """
MATCH (c:Case {url: $url})
MATCH (a:Article) WHERE a.number = $article_number
MERGE (c)-[:CITES]->(a)
"""

CITES_SECTION_CYPHER = """
MATCH (c:Case {url: $url})
MATCH (s:Section)
WHERE s.number = $section_number
  AND EXISTS {
    MATCH (s)-[:PART_OF*1..4]->(act:Act)
    WHERE toLower(act.title) CONTAINS toLower($act_title)
       OR toLower(coalesce(act.cap,'')) CONTAINS toLower($act_title)
  }
MERGE (c)-[:CITES]->(s)
"""

CITES_CASE_CYPHER = """
MATCH (c:Case {url: $url})
MATCH (target:Case)
WHERE target.citation CONTAINS $citation_fragment
  AND target.url <> $url
MERGE (c)-[:CITES]->(target)
"""

GET_EXISTING_URLS_CYPHER = "MATCH (c:Case) WHERE c.url IS NOT NULL RETURN c.url AS url"


def _get_existing_urls() -> set[str]:
    from core.db import run_query
    rows = run_query(GET_EXISTING_URLS_CYPHER)
    return {r["url"] for r in rows}


def ingest_case(case: ScrapedCase) -> bool:
    """
    Write a ScrapedCase to Neo4j. Returns True if successfully written.
    """
    from core.db import run_query

    now = datetime.now(timezone.utc).isoformat()

    try:
        # Upsert the Case node
        rows = run_query(UPSERT_CASE_CYPHER, {
            "url":         case.url,
            "title":       case.title,
            "citation":    case.citation,
            "case_number": case.case_number,
            "date":        case.date,
            "year":        case.year,
            "outcome":     case.outcome,
            "judges":      case.judges,
            "headnote":    case.headnote[:1000] if case.headnote else "",
            "summary":     case.summary[:2000] if case.summary else "",
            "domains":     case.domains,
            "scraped_at":  now,
        })

        # DECIDED_BY edge to Court
        court_name = COURTS.get(case.court_code, case.court_code)
        run_query(MERGE_COURT_CYPHER, {"url": case.url, "court_name": court_name})

        # CITES → Article
        for article_number in case.cited_articles:
            try:
                run_query(CITES_ARTICLE_CYPHER, {
                    "url": case.url, "article_number": article_number
                })
            except Exception:
                pass

        # CITES → Section
        for sec in case.cited_sections:
            try:
                run_query(CITES_SECTION_CYPHER, {
                    "url":            case.url,
                    "section_number": sec["number"],
                    "act_title":      sec["act_title"],
                })
            except Exception:
                pass

        # CITES → Case (by citation fragment)
        for citation in case.cited_case_citations:
            try:
                year_match = re.search(r'\[(\d{4})\]', citation)
                if year_match:
                    run_query(CITES_CASE_CYPHER, {
                        "url":               case.url,
                        "citation_fragment": citation[:20],
                    })
            except Exception:
                pass

        return True

    except Exception as e:
        logger.error("Failed to ingest case %s: %s", case.url, e)
        return False


# ── Main scraper ───────────────────────────────────────────────────────────────

def run_scrape(
    courts: list[str] | None = None,
    max_pages: int | None = None,
    max_cases: int | None = None,
    delay: float | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> ScrapeRun:
    """
    Main entry point. Scrapes kenyalaw.org and ingests new cases into Neo4j.

    Args:
        courts:      Court codes to scrape (default: all five).
        max_pages:   Listing pages per court (default: from config).
        max_cases:   Hard cap on total new cases per run (default: from config).
        delay:       Seconds between requests (default: from config).
        progress_cb: Optional callback(message) for live progress updates.

    Returns:
        ScrapeRun dataclass with counts and log.
    """
    from config import get_settings
    s = get_settings()

    target_courts = courts or list(COURTS.keys())
    max_pages     = max_pages or s.scraper_max_pages
    max_cases     = max_cases or s.scraper_max_cases
    delay         = delay     if delay is not None else s.scraper_delay_seconds

    run = ScrapeRun(
        started_at=datetime.now(timezone.utc).isoformat(),
        courts=target_courts,
        status="running",
    )

    def log(msg: str):
        logger.info(msg)
        run.log.append(msg)
        if progress_cb:
            progress_cb(msg)

    log(f"Scrape started | courts={target_courts} max_pages={max_pages} max_cases={max_cases}")

    # Load existing URLs (idempotency)
    try:
        existing_urls = _get_existing_urls()
        log(f"Existing cases in graph: {len(existing_urls)}")
    except Exception as e:
        log(f"WARNING: could not load existing URLs: {e}")
        existing_urls = set()

    client, client_type = _make_client()
    log(f"HTTP client: {client_type}")

    try:
        for court_code in target_courts:
            if run.new_cases >= max_cases:
                log(f"Max cases ({max_cases}) reached — stopping")
                break

            log(f"\n--- Court: {COURTS.get(court_code, court_code)} ({court_code}) ---")
            court_new = 0

            for page in range(1, max_pages + 1):
                if run.new_cases >= max_cases:
                    break

                url = LISTING_URL.format(court=court_code.upper(), page=page)
                html = _get(client, client_type, url)

                # Try alternative URL if first fails
                if not html:
                    url = SEARCH_URL.format(court=court_code.upper(), page=page)
                    html = _get(client, client_type, url)

                if not html:
                    log(f"  Page {page}: no response — moving to next court")
                    break

                case_urls = _parse_listing(html, existing_urls)
                log(f"  Page {page}: {len(case_urls)} new case URLs found")

                if not case_urls:
                    if not _has_next_page(html):
                        log(f"  No more pages for {court_code}")
                        break
                    time.sleep(delay)
                    continue

                for case_url in case_urls:
                    if run.new_cases >= max_cases:
                        break

                    time.sleep(delay)
                    case_html = _get(client, client_type, case_url)
                    if not case_html:
                        run.errors += 1
                        continue

                    scraped = _parse_case(case_html, case_url)
                    if not scraped:
                        run.errors += 1
                        continue

                    if ingest_case(scraped):
                        existing_urls.add(case_url)
                        run.new_cases += 1
                        court_new += 1
                        log(f"  ✓ [{run.new_cases}] {scraped.title[:70]}")
                    else:
                        run.errors += 1

                if not _has_next_page(html):
                    break
                time.sleep(delay)

            log(f"  {court_code}: {court_new} new cases ingested")

    except Exception as e:
        run.status = "failed"
        log(f"FATAL: {e}")
        logger.exception("Scrape run failed")
    else:
        run.status = "completed"

    finally:
        if client_type == "httpx":
            try:
                client.close()
            except Exception:
                pass

    run.completed_at = datetime.now(timezone.utc).isoformat()
    log(
        f"\nScrape complete | new={run.new_cases} "
        f"skipped={run.skipped} errors={run.errors} status={run.status}"
    )
    return run
