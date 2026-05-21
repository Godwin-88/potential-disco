"""
modules/predictor.py — Court Ruling Predictor Module

Endpoints:
  POST /api/predict/outcome              — case profile → outcome probabilities
  GET  /api/predict/precedents           — most relevant cases for a profile
  GET  /api/predict/case/{case_id}/network — citation network around a case
  GET  /api/predict/courts               — list all courts with case counts
  GET  /api/predict/principles           — legal principles established in the graph

Pipeline:
  1. PROFILE MATCH  — find structurally similar past cases via Cypher
                      (same court + dispute type + claimant type filters)
  2. PRINCIPLE PULL — retrieve LegalPrinciples established by matching cases
  3. AUTHORITY RANK — weight cases by court hierarchy level (PageRank proxy)
  4. FREQUENCY CALC — compute outcome probability distribution from matched cases
  5. CITATION GRAPH — build ego network of top precedents (who cites who)
  6. LLM ANALYSIS   — narrative explanation of the prediction with caveats
  7. RETURN         — PredictionResult with probabilities + ranked precedent list

Design note: this module deliberately uses "outcome frequency in similar past cases"
framing — NOT a predictive model. That is both more honest and more legally defensible.
The LLM prompt reinforces this framing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from config import get_settings
from core.db import run_query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/predict", tags=["Ruling Predictor"])


# ─────────────────────────────────────────────────────────────────────────────
# Court hierarchy — used for authority weighting
# ─────────────────────────────────────────────────────────────────────────────

COURT_WEIGHTS: dict[str, float] = {
    "supreme court":                         5.0,
    "court of appeal":                       4.0,
    "high court":                            3.0,
    "employment and labour relations court": 2.5,
    "environment and land court":            2.5,
    "magistrate":                            1.0,
}


def _court_weight(court_name: str) -> float:
    name_lower = (court_name or "").lower()
    for key, w in COURT_WEIGHTS.items():
        if key in name_lower:
            return w
    return 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    court: str = Field(
        ...,
        description="Target court name (must match Court nodes in the graph)",
        examples=["Court of Appeal"],
    )
    dispute_type: str = Field(
        ...,
        description="Category of dispute",
        examples=["shareholder_oppression"],
    )
    claimant_type: str = Field(
        ...,
        description="Who is bringing the claim",
        examples=["minority_shareholder"],
    )
    remedy_sought: str = Field(
        ...,
        description="Relief or remedy being requested",
        examples=["damages"],
    )
    additional_facts: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional free-text facts to refine the precedent search",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "court":           "Court of Appeal",
                "dispute_type":    "shareholder_oppression",
                "claimant_type":   "minority_shareholder",
                "remedy_sought":   "winding_up",
                "additional_facts": "Majority shareholders excluded minority from management and diverted company profits.",
            }
        }


class PrecedentCase(BaseModel):
    case_name:       str
    citation:        str | None
    court:           str | None
    year:            int | None
    outcome:         str | None
    outcome_category: str | None    # "claimant_success" | "partial" | "dismissed"
    authority_weight: float
    summary:         str | None
    established_principles: list[str]
    cited_sections:  list[str]
    similarity_basis: str           # why this case was matched


class OutcomeBucket(BaseModel):
    category:    str   # "claimant_success" | "partial_remedy" | "dismissed" | "settled"
    count:       int
    percentage:  float
    weight_adjusted_pct: float     # weighted by court authority


class PredictionResult(BaseModel):
    target_court:     str
    dispute_type:     str
    claimant_type:    str
    remedy_sought:    str
    cases_analysed:   int
    outcome_distribution: list[OutcomeBucket]
    most_likely_outcome:  str
    confidence:       str          # "high" | "medium" | "low" (based on sample size)
    top_precedents:   list[PrecedentCase]
    governing_principles: list[str]
    narrative:        str          # LLM-generated analysis
    key_factors:      list[str]    # factors that swing outcomes per the LLM
    timestamp:        str
    disclaimer: str = (
        "Outcome frequencies are based on historical cases in the Lex Kenya knowledge "
        "graph. They reflect past patterns only and are not predictive of future rulings. "
        "This is not legal advice. The outcome of any specific case depends on its unique "
        "facts, the judge assigned, and quality of legal representation."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Profile matching queries
# ─────────────────────────────────────────────────────────────────────────────

# Primary: exact court + dispute type + claimant type match
PRIMARY_MATCH_CYPHER = """
MATCH (c:Case)-[:DECIDED_BY]->(court:Court)
WHERE toLower(court.name) CONTAINS toLower($court)
  AND toLower(coalesce(c.dispute_type, c.tags, '')) CONTAINS toLower($dispute_type)
  AND toLower(coalesce(c.claimant_type, c.parties, c.tags, '')) CONTAINS toLower($claimant_type)

OPTIONAL MATCH (c)-[:ESTABLISHES]->(p:LegalPrinciple)
OPTIONAL MATCH (c)-[:CITES]->(s:Section)-[:PART_OF*1..2]->(act:Act)
OPTIONAL MATCH (newer:Case)-[:OVERRULES]->(c)

RETURN
    c.name                                          AS case_name,
    c.citation                                      AS citation,
    court.name                                      AS court,
    c.year                                          AS year,
    coalesce(c.outcome, c.decision, '')             AS outcome,
    coalesce(c.outcome_category, '')                AS outcome_category,
    coalesce(c.summary, c.headnote, '')             AS summary,
    collect(DISTINCT p.name)[..5]                   AS established_principles,
    collect(DISTINCT s.number + ' (' + coalesce(act.short_title,'') + ')')[..5] AS cited_sections,
    newer.name                                      AS overruled_by,
    'exact_match'                                   AS match_type
ORDER BY c.year DESC
LIMIT 20
"""

# Fallback 1: same court + dispute type (relax claimant filter)
FALLBACK_1_CYPHER = """
MATCH (c:Case)-[:DECIDED_BY]->(court:Court)
WHERE toLower(court.name) CONTAINS toLower($court)
  AND toLower(coalesce(c.dispute_type, c.tags, '')) CONTAINS toLower($dispute_type)

OPTIONAL MATCH (c)-[:ESTABLISHES]->(p:LegalPrinciple)
OPTIONAL MATCH (c)-[:CITES]->(s:Section)-[:PART_OF*1..2]->(act:Act)
OPTIONAL MATCH (newer:Case)-[:OVERRULES]->(c)

RETURN
    c.name                                          AS case_name,
    c.citation                                      AS citation,
    court.name                                      AS court,
    c.year                                          AS year,
    coalesce(c.outcome, c.decision, '')             AS outcome,
    coalesce(c.outcome_category, '')                AS outcome_category,
    coalesce(c.summary, c.headnote, '')             AS summary,
    collect(DISTINCT p.name)[..5]                   AS established_principles,
    collect(DISTINCT s.number + ' (' + coalesce(act.short_title,'') + ')')[..5] AS cited_sections,
    newer.name                                      AS overruled_by,
    'dispute_type_match'                            AS match_type
ORDER BY c.year DESC
LIMIT 20
"""

# Fallback 2: same dispute type across all courts (cross-court precedent)
FALLBACK_2_CYPHER = """
MATCH (c:Case)-[:DECIDED_BY]->(court:Court)
WHERE toLower(coalesce(c.dispute_type, c.tags, '')) CONTAINS toLower($dispute_type)

OPTIONAL MATCH (c)-[:ESTABLISHES]->(p:LegalPrinciple)
OPTIONAL MATCH (c)-[:CITES]->(s:Section)-[:PART_OF*1..2]->(act:Act)
OPTIONAL MATCH (newer:Case)-[:OVERRULES]->(c)

RETURN
    c.name                                          AS case_name,
    c.citation                                      AS citation,
    court.name                                      AS court,
    c.year                                          AS year,
    coalesce(c.outcome, c.decision, '')             AS outcome,
    coalesce(c.outcome_category, '')                AS outcome_category,
    coalesce(c.summary, c.headnote, '')             AS summary,
    collect(DISTINCT p.name)[..5]                   AS established_principles,
    collect(DISTINCT s.number + ' (' + coalesce(act.short_title,'') + ')')[..5] AS cited_sections,
    newer.name                                      AS overruled_by,
    'cross_court_match'                             AS match_type
ORDER BY c.year DESC
LIMIT 20
"""

# Keyword fallback — uses additional_facts if provided
KEYWORD_FALLBACK_CYPHER = """
MATCH (c:Case)-[:DECIDED_BY]->(court:Court)
WHERE any(kw IN $keywords
          WHERE toLower(coalesce(c.summary, c.headnote, c.name, '')) CONTAINS kw)

OPTIONAL MATCH (c)-[:ESTABLISHES]->(p:LegalPrinciple)
OPTIONAL MATCH (newer:Case)-[:OVERRULES]->(c)

RETURN
    c.name                                          AS case_name,
    c.citation                                      AS citation,
    court.name                                      AS court,
    c.year                                          AS year,
    coalesce(c.outcome, c.decision, '')             AS outcome,
    coalesce(c.outcome_category, '')                AS outcome_category,
    coalesce(c.summary, c.headnote, '')             AS summary,
    collect(DISTINCT p.name)[..4]                   AS established_principles,
    []                                              AS cited_sections,
    newer.name                                      AS overruled_by,
    'keyword_match'                                 AS match_type
ORDER BY c.year DESC
LIMIT 15
"""


def _match_cases(req: PredictRequest) -> list[dict]:
    """
    Try matching queries in priority order.
    Returns the best non-empty result set with a similarity_basis label.
    """
    params_primary = {
        "court":        req.court,
        "dispute_type": req.dispute_type,
        "claimant_type": req.claimant_type,
    }

    # 1. Exact match
    rows = run_query(PRIMARY_MATCH_CYPHER, params_primary)
    if rows:
        logger.info("Predictor: exact match — %d cases", len(rows))
        return rows

    # 2. Relax claimant
    rows = run_query(FALLBACK_1_CYPHER, {
        "court":        req.court,
        "dispute_type": req.dispute_type,
    })
    if rows:
        logger.info("Predictor: dispute_type match — %d cases", len(rows))
        return rows

    # 3. Cross-court
    rows = run_query(FALLBACK_2_CYPHER, {"dispute_type": req.dispute_type})
    if rows:
        logger.info("Predictor: cross-court match — %d cases", len(rows))
        return rows

    # 4. Keyword fallback from additional_facts
    if req.additional_facts:
        keywords = [
            w.lower().strip(".,;:()")
            for w in req.additional_facts.split()
            if len(w) > 4
        ][:15]
        rows = run_query(KEYWORD_FALLBACK_CYPHER, {"keywords": keywords})
        if rows:
            logger.info("Predictor: keyword match — %d cases", len(rows))
            return rows

    return []


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 + 4 — Authority weighting + outcome frequency
# ─────────────────────────────────────────────────────────────────────────────

# Normalise raw outcome strings to one of four canonical categories
OUTCOME_NORMALISATION: list[tuple[list[str], str]] = [
    (["success", "allowed", "granted", "upheld", "awarded", "claimant succeed",
      "appeal allowed", "judgment for claimant", "plaintiff succeed",
      "petition granted"], "claimant_success"),
    (["partial", "partly", "some relief", "limited damages",
      "reduced", "modified"], "partial_remedy"),
    (["dismissed", "failed", "denied", "rejected", "struck out",
      "no order", "appeal dismissed", "defendant succeed",
      "respondent succeed"], "dismissed"),
    (["settled", "consent", "withdrawn", "discontinued"], "settled"),
]


def _normalise_outcome(outcome_raw: str, outcome_category_raw: str) -> str:
    """Map free-text outcome to one of four canonical buckets."""
    text = (outcome_raw + " " + outcome_category_raw).lower()
    for keywords, category in OUTCOME_NORMALISATION:
        if any(kw in text for kw in keywords):
            return category
    return "unknown"


def _compute_distribution(cases: list[dict]) -> tuple[list[OutcomeBucket], str]:
    """
    Compute raw and authority-weighted outcome distribution.
    Returns (buckets, most_likely_outcome).
    """
    bucket_counts:   dict[str, int]   = {}
    bucket_weighted: dict[str, float] = {}

    for c in cases:
        # Skip overruled cases from the frequency count
        if c.get("overruled_by"):
            continue

        cat = _normalise_outcome(
            c.get("outcome", ""),
            c.get("outcome_category", ""),
        )
        weight = _court_weight(c.get("court", ""))

        bucket_counts[cat]   = bucket_counts.get(cat, 0) + 1
        bucket_weighted[cat] = bucket_weighted.get(cat, 0.0) + weight

    total_cases    = sum(bucket_counts.values()) or 1
    total_weighted = sum(bucket_weighted.values()) or 1.0

    categories = ["claimant_success", "partial_remedy", "dismissed", "settled", "unknown"]
    buckets = []
    for cat in categories:
        count = bucket_counts.get(cat, 0)
        if count == 0:
            continue
        buckets.append(OutcomeBucket(
            category=cat,
            count=count,
            percentage=round(count / total_cases * 100, 1),
            weight_adjusted_pct=round(bucket_weighted.get(cat, 0) / total_weighted * 100, 1),
        ))

    buckets.sort(key=lambda b: b.weight_adjusted_pct, reverse=True)
    most_likely = buckets[0].category if buckets else "unknown"
    return buckets, most_likely


def _confidence_level(n: int) -> str:
    if n >= 15:  return "high"
    if n >= 6:   return "medium"
    return "low"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Legal principles from matched cases
# ─────────────────────────────────────────────────────────────────────────────

def _extract_principles(cases: list[dict]) -> list[str]:
    seen = set()
    principles = []
    for c in cases:
        for p in (c.get("established_principles") or []):
            if p and p not in seen:
                seen.add(p)
                principles.append(p)
    return principles[:10]


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5 — Citation ego network
# ─────────────────────────────────────────────────────────────────────────────

CITATION_NETWORK_CYPHER = """
MATCH (c:Case)
WHERE c.citation IN $citations OR c.name IN $case_names

// Cases that this set cites
OPTIONAL MATCH (c)-[:CITES]->(cited:Case)

// Cases that cite back into this set
OPTIONAL MATCH (citing:Case)-[:CITES]->(c)

// Overruling relationships
OPTIONAL MATCH (c)-[:OVERRULES]->(overruled:Case)

RETURN
    c.name            AS source,
    c.citation        AS source_citation,
    collect(DISTINCT {name: cited.name,    citation: cited.citation,    rel: 'CITES'})    AS outgoing,
    collect(DISTINCT {name: citing.name,   citation: citing.citation,   rel: 'CITED_BY'}) AS incoming,
    collect(DISTINCT {name: overruled.name, citation: overruled.citation, rel: 'OVERRULES'}) AS overrules
"""


def _build_citation_network(top_cases: list[dict]) -> dict:
    citations  = [c["citation"]  for c in top_cases if c.get("citation")]
    case_names = [c["case_name"] for c in top_cases if c.get("case_name")]

    if not citations and not case_names:
        return {"nodes": [], "edges": []}

    rows = run_query(CITATION_NETWORK_CYPHER, {
        "citations":  citations,
        "case_names": case_names,
    })

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()

    for row in rows:
        src = row.get("source_citation") or row.get("source") or ""
        if src and src not in seen_nodes:
            nodes.append({"id": src, "label": row.get("source", src), "type": "primary"})
            seen_nodes.add(src)

        for rel_list, edge_type in [
            (row.get("outgoing", []),  "CITES"),
            (row.get("incoming", []),  "CITED_BY"),
            (row.get("overrules", []), "OVERRULES"),
        ]:
            for target in (rel_list or []):
                if not target.get("name"):
                    continue
                tgt_id = target.get("citation") or target["name"]
                if tgt_id not in seen_nodes:
                    nodes.append({"id": tgt_id, "label": target["name"], "type": "related"})
                    seen_nodes.add(tgt_id)
                edges.append({
                    "from": src if edge_type in ("CITES", "OVERRULES") else tgt_id,
                    "to":   tgt_id if edge_type in ("CITES", "OVERRULES") else src,
                    "type": edge_type,
                })

    return {"nodes": nodes, "edges": edges}


# ─────────────────────────────────────────────────────────────────────────────
# Stage 6 — LLM narrative
# ─────────────────────────────────────────────────────────────────────────────

PREDICTOR_SYSTEM_PROMPT = """You are a Kenyan legal research analyst embedded in the
Lex Kenya platform. You explain precedent patterns — you do NOT predict court outcomes.

Given a case profile and a set of matching historical cases from Kenyan courts,
produce a structured JSON analysis:

{
  "narrative": "<3-4 paragraph plain-English analysis of what the precedents show,
                 why the leading cases matter, and what distinguishes winning from
                 losing claims of this type. Do not say 'the court will' — say
                 'courts have tended to' or 'precedent suggests'>",
  "key_factors": [
    "<factor 1 that historically swings outcomes>",
    "<factor 2>",
    "<factor 3>"
  ],
  "strongest_precedent": "<case name and why it is the most relevant>",
  "risk_factors_for_claimant": [
    "<what weakens the claimant's position based on precedent>"
  ],
  "notes": "<any important caveats e.g. small sample size, conflicting decisions>"
}

RULES:
1. Only reference cases listed in MATCHED CASES below.
2. Flag any case marked OVERRULED and explain the significance.
3. If fewer than 5 cases are available, note the limited sample prominently.
4. Never say the claimant 'will win' or 'will lose'.
5. Return ONLY the JSON — no markdown, no preamble."""

PREDICTOR_USER_TEMPLATE = """=== CASE PROFILE ===
Court:          {court}
Dispute type:   {dispute_type}
Claimant:       {claimant_type}
Remedy sought:  {remedy_sought}
Additional facts: {additional_facts}

=== OUTCOME DISTRIBUTION ({n_cases} cases) ===
{distribution}

=== GOVERNING PRINCIPLES ===
{principles}

=== MATCHED CASES ===
{cases_text}

Produce the JSON analysis."""


def _pack_cases_for_llm(cases: list[dict]) -> str:
    lines = []
    for i, c in enumerate(cases[:12], 1):
        overruled = f"  ⚠ OVERRULED BY: {c['overruled_by']}" if c.get("overruled_by") else ""
        lines.append(
            f"[{i}] {c.get('case_name','')} [{c.get('citation','')}]"
            f" | {c.get('court','')} | {c.get('year','')}"
            f" | Outcome: {c.get('outcome','unknown')}"
            f"{overruled}"
        )
        if c.get("summary"):
            lines.append(f"    Summary: {c['summary'][:250]}")
        for p in (c.get("established_principles") or []):
            if p:
                lines.append(f"    Principle: {p}")
        lines.append("")
    return "\n".join(lines)


def _call_predictor_llm(
    req: PredictRequest,
    cases: list[dict],
    distribution: list[OutcomeBucket],
    principles: list[str],
) -> dict:
    import json

    dist_text = "\n".join(
        f"  {b.category}: {b.count} cases ({b.percentage}%) "
        f"[weighted: {b.weight_adjusted_pct}%]"
        for b in distribution
    )

    prompt = PREDICTOR_USER_TEMPLATE.format(
        court=req.court,
        dispute_type=req.dispute_type,
        claimant_type=req.claimant_type,
        remedy_sought=req.remedy_sought,
        additional_facts=req.additional_facts or "None provided.",
        n_cases=len(cases),
        distribution=dist_text or "Insufficient data.",
        principles="\n".join(f"  • {p}" for p in principles) or "None identified.",
        cases_text=_pack_cases_for_llm(cases),
    )

    s = get_settings()
    if s.llm_backend == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=s.anthropic_api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=PREDICTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text
    elif s.llm_backend in ("openai", "openai_compatible"):
        import httpx
        headers = {
            "Authorization": f"Bearer {s.openai_compatible_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": s.openai_compatible_model,
            "messages": [
                {"role": "system", "content": PREDICTOR_SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            "max_tokens": 1500,
        }
        response = httpx.post(
            f"{s.openai_compatible_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
    else:
        import google.generativeai as genai
        genai.configure(api_key=s.gemini_api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro",
            system_instruction=PREDICTOR_SYSTEM_PROMPT,
        )
        raw = model.generate_content(prompt).text

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "narrative": "Analysis could not be parsed. Review matched cases directly.",
            "key_factors": [],
            "strongest_precedent": "",
            "risk_factors_for_claimant": [],
            "notes": "JSON parse error from LLM.",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/outcome",
    response_model=PredictionResult,
    summary="Analyse likely outcomes based on precedent",
    description=(
        "Given a case profile (court, dispute type, claimant type, remedy sought), "
        "retrieves structurally similar historical cases from the knowledge graph, "
        "computes authority-weighted outcome frequencies, and returns a precedent "
        "analysis with an LLM-generated narrative. This is NOT a prediction — it "
        "reflects historical patterns only."
    ),
)
async def predict_outcome(req: PredictRequest) -> PredictionResult:
    logger.info("Predictor | court=%s dispute=%s", req.court, req.dispute_type)

    # Stage 1 — match cases
    cases = _match_cases(req)

    if not cases:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No matching cases found for court='{req.court}', "
                f"dispute_type='{req.dispute_type}'. "
                "Try broadening the parameters or adding additional_facts."
            ),
        )

    # Stage 2 — extract principles
    principles = _extract_principles(cases)

    # Stage 3+4 — authority weight + frequency
    distribution, most_likely = _compute_distribution(cases)
    confidence = _confidence_level(len(cases))

    # Stage 5 — citation network (top 8 cases)
    top_cases = cases[:8]

    # Stage 6 — LLM narrative
    llm_out = _call_predictor_llm(req, cases, distribution, principles)

    # Build PrecedentCase objects for the response
    precedents = [
        PrecedentCase(
            case_name=c.get("case_name", ""),
            citation=c.get("citation"),
            court=c.get("court"),
            year=c.get("year"),
            outcome=c.get("outcome"),
            outcome_category=_normalise_outcome(
                c.get("outcome",""), c.get("outcome_category","")),
            authority_weight=_court_weight(c.get("court","")),
            summary=c.get("summary"),
            established_principles=c.get("established_principles") or [],
            cited_sections=c.get("cited_sections") or [],
            similarity_basis=c.get("match_type", "matched"),
        )
        for c in top_cases
    ]

    return PredictionResult(
        target_court=req.court,
        dispute_type=req.dispute_type,
        claimant_type=req.claimant_type,
        remedy_sought=req.remedy_sought,
        cases_analysed=len(cases),
        outcome_distribution=distribution,
        most_likely_outcome=most_likely,
        confidence=confidence,
        top_precedents=precedents,
        governing_principles=principles,
        narrative=llm_out.get("narrative", ""),
        key_factors=llm_out.get("key_factors", []),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/precedents",
    summary="Retrieve relevant precedents without full outcome analysis",
    description="Fast endpoint — no LLM call. Returns ranked matching cases only.",
)
async def get_precedents(
    court:        str = Query(..., description="Court name"),
    dispute_type: str = Query(..., description="Dispute category"),
    claimant_type: str = Query(default="", description="Optional claimant filter"),
    limit:        int = Query(default=10, ge=1, le=30),
) -> dict:
    req = PredictRequest(
        court=court,
        dispute_type=dispute_type,
        claimant_type=claimant_type or "any",
        remedy_sought="any",
    )
    cases = _match_cases(req)
    if not cases:
        raise HTTPException(status_code=404, detail="No matching precedents found.")

    distribution, most_likely = _compute_distribution(cases)
    return {
        "court":          court,
        "dispute_type":   dispute_type,
        "cases_found":    len(cases),
        "most_likely_outcome": most_likely,
        "outcome_distribution": [b.dict() for b in distribution],
        "precedents": [
            {
                "case_name":  c.get("case_name"),
                "citation":   c.get("citation"),
                "court":      c.get("court"),
                "year":       c.get("year"),
                "outcome":    c.get("outcome"),
                "outcome_category": _normalise_outcome(
                    c.get("outcome",""), c.get("outcome_category","")),
                "principles": c.get("established_principles"),
                "overruled_by": c.get("overruled_by"),
                "similarity_basis": c.get("match_type"),
            }
            for c in cases[:limit]
        ],
    }


@router.get(
    "/case/{case_citation}/network",
    summary="Citation network around a specific case",
    description=(
        "Returns the ego network of a case: what it cites, what cites it, "
        "what it overrules, and whether it has been overruled. "
        "Designed for graph visualisation in the frontend."
    ),
)
async def case_network(
    case_citation: str = Path(..., description="Case citation string e.g. '[2021] eKLR'"),
) -> dict:
    cypher = """
    MATCH (c:Case)
    WHERE c.citation = $citation OR c.name = $citation
    OPTIONAL MATCH (c)-[:DECIDED_BY]->(court:Court)

    // Outgoing citations
    OPTIONAL MATCH (c)-[:CITES]->(cited_case:Case)
    OPTIONAL MATCH (c)-[:CITES]->(cited_section:Section)-[:PART_OF*1..2]->(act:Act)
    OPTIONAL MATCH (c)-[:CITES]->(cited_article:Article)

    // Incoming citations
    OPTIONAL MATCH (citing_case:Case)-[:CITES]->(c)
    OPTIONAL MATCH (citing_case)-[:DECIDED_BY]->(citing_court:Court)

    // Interpretations and principles
    OPTIONAL MATCH (c)-[:INTERPRETS]->(interp)
    OPTIONAL MATCH (c)-[:ESTABLISHES]->(principle:LegalPrinciple)
    OPTIONAL MATCH (c)-[:OVERRULES]->(overruled:Case)
    OPTIONAL MATCH (newer:Case)-[:OVERRULES]->(c)

    RETURN
        c.name                AS case_name,
        c.citation            AS citation,
        court.name            AS court,
        c.year                AS year,
        c.outcome             AS outcome,
        c.summary             AS summary,
        collect(DISTINCT {
            name: cited_case.name, citation: cited_case.citation
        })[..10]              AS cites_cases,
        collect(DISTINCT {
            number: cited_section.number, act: act.short_title
        })[..10]              AS cites_sections,
        collect(DISTINCT {
            number: cited_article.number, title: cited_article.title
        })[..5]               AS cites_articles,
        collect(DISTINCT {
            name: citing_case.name, citation: citing_case.citation,
            court: citing_court.name
        })[..15]              AS cited_by,
        collect(DISTINCT principle.name)[..5] AS established_principles,
        overruled.name        AS overrules_case,
        newer.name            AS overruled_by
    LIMIT 1
    """
    rows = run_query(cypher, {"citation": case_citation})
    if not rows:
        raise HTTPException(status_code=404, detail=f"Case '{case_citation}' not found.")
    return rows[0]


@router.get(
    "/courts",
    summary="List all courts with their case counts",
)
async def list_courts() -> dict:
    cypher = """
    MATCH (c:Case)-[:DECIDED_BY]->(court:Court)
    RETURN
        court.name              AS court,
        count(c)                AS case_count,
        min(c.year)             AS earliest_year,
        max(c.year)             AS latest_year,
        collect(DISTINCT coalesce(c.dispute_type, ''))[..8] AS dispute_types
    ORDER BY case_count DESC
    """
    rows = run_query(cypher)
    return {"courts": rows, "total": len(rows)}


@router.get(
    "/principles",
    summary="All legal principles established in the knowledge graph",
    description="Returns LegalPrinciple nodes with the cases that established them.",
)
async def list_principles(
    search: str = Query(default="", description="Optional keyword filter"),
) -> dict:
    cypher = """
    MATCH (p:LegalPrinciple)
    WHERE $search = '' OR toLower(p.name) CONTAINS toLower($search)
    OPTIONAL MATCH (c:Case)-[:ESTABLISHES]->(p)
    OPTIONAL MATCH (c)-[:DECIDED_BY]->(court:Court)
    RETURN
        p.name                          AS principle,
        p.description                   AS description,
        collect(DISTINCT {
            name: c.name, citation: c.citation, court: court.name, year: c.year
        })[..5]                         AS established_by_cases
    ORDER BY size(collect(c)) DESC
    LIMIT 50
    """
    rows = run_query(cypher, {"search": search})
    return {"principles": rows, "total": len(rows)}
