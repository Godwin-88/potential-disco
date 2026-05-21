"""
modules/compliance.py — Corporate Compliance Checker Module

Endpoints:
  POST /api/compliance/check              — action description → risk assessment
  GET  /api/compliance/obligations/{act}  — all obligations/penalties under an Act
  GET  /api/compliance/acts               — list all Acts in the knowledge graph
  POST /api/compliance/multi              — check multiple actions in one call

Pipeline (different from Q&A GraphRAG):
  1. CLASSIFY  — map action_type to known statutory triggers in the graph
  2. TRAVERSE  — pull all Sections, Obligations, Penalties, Deadlines from
                 matching Acts; walk up to constitutional basis
  3. SCREEN    — deterministic rule checks (amount thresholds, role constraints,
                 disclosure requirements) — NO LLM for this stage
  4. LLM RISK  — structured prompt → risk_level, findings[], required_actions[],
                 liability_exposure, cited_sections[]
  5. RETURN    — ComplianceResult with risk badge + full statutory citations
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
router = APIRouter(prefix="/api/compliance", tags=["Compliance Checker"])

# ─────────────────────────────────────────────────────────────────────────────
# Action type → statutory trigger mapping
# Keys are action_type values the UI sends.
# Values are lists of Act short titles + relevant section keywords to seed
# the graph traversal with.
# ─────────────────────────────────────────────────────────────────────────────

ACTION_TRIGGERS: dict[str, dict] = {
    "related_party_transaction": {
        "acts":     ["Companies Act", "Capital Markets Act", "Banking Act"],
        "keywords": ["related party", "conflict of interest", "disclosure",
                     "director interest", "substantial shareholder"],
        "risk_floor": "medium",
    },
    "share_buyback": {
        "acts":     ["Companies Act"],
        "keywords": ["share buyback", "purchase of own shares", "treasury shares",
                     "solvency", "distributable profits"],
        "risk_floor": "medium",
    },
    "foreign_investment": {
        "acts":     ["Companies Act", "Investment Promotion Act",
                     "Foreign Investments Protection Act", "Capital Markets Act"],
        "keywords": ["foreign investor", "ownership limit", "restricted sector",
                     "approval", "notification"],
        "risk_floor": "medium",
    },
    "esop": {
        "acts":     ["Companies Act", "Income Tax Act", "Capital Markets Act"],
        "keywords": ["employee share", "share option", "option scheme",
                     "vesting", "tax treatment"],
        "risk_floor": "low",
    },
    "dividend_declaration": {
        "acts":     ["Companies Act", "Income Tax Act"],
        "keywords": ["dividend", "distributable profits", "solvency test",
                     "withholding tax", "retained earnings"],
        "risk_floor": "low",
    },
    "director_appointment": {
        "acts":     ["Companies Act", "Capital Markets Act"],
        "keywords": ["director", "fit and proper", "disqualification",
                     "notification", "register"],
        "risk_floor": "low",
    },
    "company_winding_up": {
        "acts":     ["Companies Act", "Insolvency Act"],
        "keywords": ["winding up", "liquidation", "insolvency", "creditors",
                     "petition", "statutory demand"],
        "risk_floor": "high",
    },
    "data_processing": {
        "acts":     ["Data Protection Act"],
        "keywords": ["personal data", "consent", "data controller",
                     "data processor", "registration", "breach notification"],
        "risk_floor": "medium",
    },
    "merger_acquisition": {
        "acts":     ["Companies Act", "Competition Act", "Capital Markets Act"],
        "keywords": ["merger", "acquisition", "takeover", "Competition Authority",
                     "approval", "notification threshold"],
        "risk_floor": "high",
    },
    "general": {
        "acts":     [],
        "keywords": [],
        "risk_floor": "low",
    },
}

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

class ComplianceRequest(BaseModel):
    action_type: str = Field(
        ...,
        description="One of the known action type keys, or 'general'",
        examples=["related_party_transaction"],
    )
    description: str = Field(
        ..., min_length=10, max_length=2000,
        description="Detailed plain-English description of the proposed action",
        examples=[
            "ABC Ltd wishes to appoint its CEO's spouse as sole IT supplier "
            "at Ksh 8M/year without board approval or shareholder disclosure."
        ],
    )
    company_type: str = Field(
        default="private",
        description="private | public | listed | ngo | foreign_branch",
    )
    transaction_amount_kes: float | None = Field(
        default=None,
        description="Transaction value in KES if applicable (triggers amount-based rules)",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "action_type": "related_party_transaction",
                "description": "CEO's spouse to be sole supplier at Ksh 8M/year without board vote.",
                "company_type": "private",
                "transaction_amount_kes": 8_000_000,
            }
        }


class FindingItem(BaseModel):
    severity:       str          # "low" | "medium" | "high" | "critical"
    finding:        str          # human-readable finding
    section:        str | None   # e.g. "Section 142"
    act:            str | None   # e.g. "Companies Act 2015"
    obligation:     str | None   # what the company must do
    penalty:        str | None   # what happens if they don't


class ComplianceResult(BaseModel):
    risk_level:        str                # "low" | "medium" | "high" | "critical"
    risk_summary:      str                # 2-sentence headline
    findings:          list[FindingItem]
    required_actions:  list[str]          # ordered action checklist
    liability_exposure: str               # narrative paragraph
    cited_sections:    list[dict]         # [{act, section, text_excerpt}]
    constitutional_basis: list[str]       # relevant Articles
    applicable_institutions: list[str]   # CMA, CBK, CAK etc. that must be notified
    timestamp:         str
    disclaimer: str = (
        "This compliance assessment is generated by AI over the Lex Kenya knowledge "
        "graph and does not constitute legal advice. Engage a qualified Kenyan advocate "
        "before acting on this assessment."
    )


class MultiComplianceRequest(BaseModel):
    actions: list[ComplianceRequest] = Field(..., max_length=5)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 + 2 — Graph traversal for statutory obligations
# ─────────────────────────────────────────────────────────────────────────────

OBLIGATION_TRAVERSAL_CYPHER = """
// Pull all Sections with matching keywords from the relevant Acts,
// together with their obligations, penalties, deadlines, and
// constitutional basis — all in one traversal.
MATCH (act:Act)
WHERE any(name IN $act_names
          WHERE toLower(act.short_title) CONTAINS toLower(name)
             OR toLower(act.name)        CONTAINS toLower(name))

MATCH (act)<-[:PART_OF*1..3]-(section:Section)
WHERE any(kw IN $keywords
          WHERE toLower(coalesce(section.text,'') + ' ' +
                        coalesce(section.title,'')) CONTAINS kw)

// Obligations and penalties hanging off the section
OPTIONAL MATCH (section)-[:IMPOSES]->(obl:Obligation)
OPTIONAL MATCH (section)-[:IMPOSES]->(pen:Penalty)
OPTIONAL MATCH (section)-[:DEFINED_IN]-(dl:Deadline)

// Constitutional basis of the Act
OPTIONAL MATCH (act)-[:ENACTED_UNDER]->(article:Article)-[:PART_OF]->(ch:Chapter)

// Amendments — prefer the latest version
OPTIONAL MATCH (amend:Amendment)-[:AMENDS]->(section)

// Cases that have interpreted this section (top 3 most recent)
OPTIONAL MATCH (c:Case)-[:CITES|INTERPRETS]->(section)
OPTIONAL MATCH (c)-[:DECIDED_BY]->(court:Court)

RETURN
    act.short_title                                        AS act_name,
    act.year                                               AS act_year,
    section.number                                         AS section_number,
    section.title                                          AS section_title,
    coalesce(section.text, section.content, '')            AS section_text,
    collect(DISTINCT obl.text)[..4]                        AS obligations,
    collect(DISTINCT {
        text:   pen.text,
        amount: pen.amount,
        unit:   pen.unit,
        type:   pen.type
    })[..4]                                                AS penalties,
    collect(DISTINCT dl.text)[..2]                         AS deadlines,
    article.number                                         AS constitutional_article,
    article.title                                          AS constitutional_article_title,
    collect(DISTINCT {
        name:     c.name,
        citation: c.citation,
        court:    court.name,
        year:     c.year,
        outcome:  c.outcome
    })[..3]                                                AS interpreting_cases,
    collect(DISTINCT amend.description)[..2]               AS recent_amendments
ORDER BY act.year DESC, section.number ASC
LIMIT 30
"""

INSTITUTION_LOOKUP_CYPHER = """
// Find which regulatory institutions oversee this action
MATCH (inst:Institution)
WHERE any(kw IN $keywords
          WHERE toLower(inst.name) CONTAINS kw
             OR toLower(coalesce(inst.mandate,'')) CONTAINS kw)
OPTIONAL MATCH (inst)-[:ESTABLISHED_BY]->(node)
RETURN
    inst.name                                          AS institution,
    inst.mandate                                       AS mandate,
    coalesce(node.number, node.name)                   AS established_by
LIMIT 8
"""

DIRECT_SECTION_LOOKUP_CYPHER = """
// Fallback: full-text keyword search across all sections
MATCH (section:Section)
WHERE any(kw IN $keywords
          WHERE toLower(coalesce(section.text,'') + ' ' +
                        coalesce(section.title,'')) CONTAINS kw)
OPTIONAL MATCH (section)-[:PART_OF*1..2]->(act:Act)
OPTIONAL MATCH (section)-[:IMPOSES]->(obl:Obligation)
OPTIONAL MATCH (section)-[:IMPOSES]->(pen:Penalty)
RETURN
    coalesce(act.short_title, act.name, 'Unknown Act') AS act_name,
    section.number                                      AS section_number,
    section.title                                       AS section_title,
    coalesce(section.text, section.content, '')         AS section_text,
    collect(DISTINCT obl.text)[..3]                     AS obligations,
    collect(DISTINCT pen.text)[..3]                     AS penalties
LIMIT 15
"""


def _fetch_statutory_context(action_type: str, description: str) -> dict[str, Any]:
    """
    Run the obligation traversal query seeded by the action type triggers
    plus keywords extracted from the description.
    """
    trigger = ACTION_TRIGGERS.get(action_type, ACTION_TRIGGERS["general"])
    act_names = trigger["acts"]
    base_keywords = trigger["keywords"]

    # Augment with significant words from the description (>5 chars)
    desc_keywords = [
        w.lower().strip(".,;:()")
        for w in description.split()
        if len(w) > 5
    ]
    all_keywords = list(set(base_keywords + desc_keywords))[:25]

    # Primary traversal
    rows: list[dict] = []
    if act_names:
        rows = run_query(OBLIGATION_TRAVERSAL_CYPHER, {
            "act_names": act_names,
            "keywords":  all_keywords,
        })

    # Fallback if primary returns nothing
    if not rows:
        rows = run_query(DIRECT_SECTION_LOOKUP_CYPHER, {
            "keywords": all_keywords,
        })

    # Institutions
    institutions = run_query(INSTITUTION_LOOKUP_CYPHER, {
        "keywords": base_keywords[:8],
    })

    return {
        "sections":     rows,
        "institutions": institutions,
        "keywords_used": all_keywords,
        "risk_floor":   trigger["risk_floor"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Deterministic rule screen
# ─────────────────────────────────────────────────────────────────────────────

def _deterministic_screen(
    req: ComplianceRequest,
    context: dict,
) -> list[dict]:
    """
    Emit pre-computed findings for well-known hard rules.
    No LLM involved — these are binary triggers that are always correct
    and make the risk assessment auditable.
    """
    findings: list[dict] = []
    amt = req.transaction_amount_kes or 0

    if req.action_type == "related_party_transaction":
        findings.append({
            "severity":  "high",
            "finding":   "Related-party transactions require director interest disclosure at a board meeting where the interested director may not vote (Companies Act 2015, §§ 142–144).",
            "section":   "§ 142–144",
            "act":       "Companies Act 2015",
            "obligation": "The interested director must declare their interest before the transaction is approved.",
            "penalty":   "Breach of fiduciary duty — personal liability under § 149; transaction may be voided.",
        })
        if req.company_type in ("public", "listed") or amt >= 5_000_000:
            findings.append({
                "severity":  "high",
                "finding":   "Shareholder disclosure required for material related-party transactions.",
                "section":   "§ 144",
                "act":       "Companies Act 2015",
                "obligation": "File disclosure with shareholders and, if listed, the Capital Markets Authority.",
                "penalty":   "CMA enforcement action; potential delisting.",
            })

    if req.action_type == "foreign_investment":
        if amt and amt >= 100_000_000:  # Ksh 100M threshold
            findings.append({
                "severity":  "high",
                "finding":   "Transaction exceeds the Competition Authority of Kenya merger notification threshold.",
                "section":   "§ 41–43",
                "act":       "Competition Act 2010",
                "obligation": "Notify the Competition Authority before completion.",
                "penalty":   "Transaction void; fine up to Ksh 10M or 10% of turnover.",
            })

    if req.action_type == "dividend_declaration":
        findings.append({
            "severity":  "medium",
            "finding":   "A dividend may only be declared out of distributable profits after passing the solvency test.",
            "section":   "§ 182",
            "act":       "Companies Act 2015",
            "obligation": "Directors must confirm solvency in writing before declaration.",
            "penalty":   "Directors personally liable for unlawful dividends.",
        })

    if req.action_type == "company_winding_up":
        findings.append({
            "severity":  "critical",
            "finding":   "Voluntary winding up requires a special resolution (75% shareholder vote) and a statutory declaration of solvency.",
            "section":   "§ 391–392",
            "act":       "Companies Act 2015",
            "obligation": "Pass special resolution; file declaration of solvency with the Registrar within 15 days.",
            "penalty":   "Failure to file: criminal liability on directors; fine up to Ksh 500,000.",
        })

    if req.action_type == "data_processing":
        findings.append({
            "severity":  "medium",
            "finding":   "Any organisation processing personal data of Kenyan residents must register with the Office of the Data Protection Commissioner.",
            "section":   "§ 15–17",
            "act":       "Data Protection Act 2019",
            "obligation": "Register as data controller/processor before processing begins.",
            "penalty":   "Fine up to Ksh 3M or imprisonment up to 10 years.",
        })

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — LLM risk assessment
# ─────────────────────────────────────────────────────────────────────────────

COMPLIANCE_SYSTEM_PROMPT = """You are a Kenyan corporate law compliance engine embedded in
the Lex Kenya platform. You analyse proposed business actions against Kenyan statute and
case law, then produce a structured compliance assessment.

OUTPUT FORMAT — respond with a valid JSON object and nothing else:
{
  "risk_level": "low" | "medium" | "high" | "critical",
  "risk_summary": "<2-sentence headline describing the overall risk>",
  "additional_findings": [
    {
      "severity": "low|medium|high|critical",
      "finding": "<specific legal issue found>",
      "section": "<section number or null>",
      "act": "<Act name or null>",
      "obligation": "<what must be done>",
      "penalty": "<consequence of non-compliance or null>"
    }
  ],
  "required_actions": [
    "<ordered action 1>",
    "<ordered action 2>"
  ],
  "liability_exposure": "<paragraph describing personal/corporate liability>",
  "constitutional_basis": ["<Article X — Title>"],
  "notes": "<any caveats, e.g. 'depends on whether company is listed'>"
}

RULES:
1. Only cite Acts and sections that appear in the STATUTORY CONTEXT block.
2. Escalate risk_level to at least the floor stated in CONTEXT METADATA.
3. Do not duplicate findings already listed in DETERMINISTIC FINDINGS.
4. If the action is clearly lawful with no issues, return risk_level "low" and say so.
5. Always include at least one required_action even for low-risk assessments.
6. Return ONLY the JSON — no preamble, no markdown fences."""

COMPLIANCE_USER_TEMPLATE = """=== CONTEXT METADATA ===
Action type:       {action_type}
Company type:      {company_type}
Transaction (KES): {amount}
Risk floor:        {risk_floor}

=== DETERMINISTIC FINDINGS (do not duplicate) ===
{det_findings}

=== STATUTORY CONTEXT (sections retrieved from knowledge graph) ===
{statutory_context}

=== REGULATORY INSTITUTIONS ===
{institutions}

=== PROPOSED ACTION ===
{description}

Produce the compliance assessment JSON."""


def _pack_statutory_context(sections: list[dict]) -> str:
    lines = []
    for s in sections:
        act  = s.get("act_name", "")
        sec  = s.get("section_number", "")
        title = s.get("section_title", "")
        text = (s.get("section_text") or "")[:300]
        obls = [o for o in (s.get("obligations") or []) if o]
        pens = [p for p in (s.get("penalties") or []) if isinstance(p, str) or (isinstance(p, dict) and p.get("text"))]

        lines.append(f"[{act} — {sec} {title}]")
        if text:
            lines.append(f"  Text: {text}")
        for o in obls:
            lines.append(f"  Obligation: {o}")
        for p in pens:
            txt = p if isinstance(p, str) else p.get("text", "")
            amt = p.get("amount", "") if isinstance(p, dict) else ""
            lines.append(f"  Penalty: {txt} {amt}".strip())
        if s.get("constitutional_article"):
            lines.append(
                f"  Constitutional basis: Article {s['constitutional_article']} "
                f"— {s.get('constitutional_article_title','')}"
            )
        lines.append("")
    return "\n".join(lines) if lines else "No specific sections retrieved."


def _pack_institutions(institutions: list[dict]) -> str:
    if not institutions:
        return "None identified."
    return "\n".join(
        f"  • {i.get('institution','')}: {i.get('mandate','')}"
        for i in institutions
    )


def _call_compliance_llm(prompt_user: str) -> dict:
    import json
    s = get_settings()

    if s.llm_backend == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=s.anthropic_api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=COMPLIANCE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt_user}],
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
                {"role": "system", "content": COMPLIANCE_SYSTEM_PROMPT},
                {"role": "user",   "content": prompt_user},
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
            system_instruction=COMPLIANCE_SYSTEM_PROMPT,
        )
        raw = model.generate_content(prompt_user).text

    # Strip markdown fences if the model adds them despite instructions
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s\nRaw: %s", e, raw[:200])
        return {
            "risk_level": "medium",
            "risk_summary": "Assessment could not be fully parsed. Manual review recommended.",
            "additional_findings": [],
            "required_actions": ["Consult a qualified Kenyan advocate for this action."],
            "liability_exposure": "Unable to determine automatically.",
            "constitutional_basis": [],
            "notes": f"JSON parse error: {str(e)}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5 — Result assembly
# ─────────────────────────────────────────────────────────────────────────────

def _assemble_result(
    req:         ComplianceRequest,
    det_findings: list[dict],
    llm_output:  dict,
    context:     dict,
) -> ComplianceResult:
    # Merge deterministic + LLM findings
    all_findings_raw = det_findings + llm_output.get("additional_findings", [])
    findings = [FindingItem(**f) for f in all_findings_raw]

    # Final risk level = max(deterministic floor, LLM assessment)
    risk_floor  = context["risk_floor"]
    llm_risk    = llm_output.get("risk_level", "low")
    final_risk  = max([risk_floor, llm_risk], key=lambda r: RISK_ORDER.get(r, 0))

    # Build cited sections list
    cited: list[dict] = []
    for s in context["sections"][:8]:
        if s.get("section_number"):
            cited.append({
                "act":          s.get("act_name"),
                "section":      s.get("section_number"),
                "title":        s.get("section_title"),
                "text_excerpt": (s.get("section_text") or "")[:200],
            })

    # Constitutional articles from both graph traversal and LLM
    const_basis = list({
        art for s in context["sections"]
        if s.get("constitutional_article")
        for art in [f"Article {s['constitutional_article']} — {s.get('constitutional_article_title','')}"]
    } | set(llm_output.get("constitutional_basis", [])))

    # Applicable institutions
    inst_names = [i.get("institution", "") for i in context["institutions"] if i.get("institution")]

    return ComplianceResult(
        risk_level=final_risk,
        risk_summary=llm_output.get("risk_summary", ""),
        findings=findings,
        required_actions=llm_output.get("required_actions", []),
        liability_exposure=llm_output.get("liability_exposure", ""),
        cited_sections=cited,
        constitutional_basis=const_basis,
        applicable_institutions=inst_names,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/check",
    response_model=ComplianceResult,
    summary="Check compliance of a proposed corporate action",
    description=(
        "Submit a proposed business action. The engine: (1) traverses the knowledge "
        "graph for all applicable obligations, penalties, and deadlines; "
        "(2) runs deterministic rule checks for known hard thresholds; "
        "(3) calls the LLM for nuanced risk analysis; "
        "(4) returns a merged, risk-ranked compliance assessment with full citations."
    ),
)
async def check_compliance(req: ComplianceRequest) -> ComplianceResult:
    logger.info("Compliance check | action=%s company=%s", req.action_type, req.company_type)

    # Stage 1+2 — graph traversal
    context = _fetch_statutory_context(req.action_type, req.description)

    # Stage 3 — deterministic screen
    det_findings = _deterministic_screen(req, context)

    # Stage 4 — LLM assessment
    statutory_text = _pack_statutory_context(context["sections"])
    institutions_text = _pack_institutions(context["institutions"])
    det_text = "\n".join(
        f"  [{f['severity'].upper()}] {f['finding']}" for f in det_findings
    ) or "None."

    prompt_user = COMPLIANCE_USER_TEMPLATE.format(
        action_type=req.action_type,
        company_type=req.company_type,
        amount=f"Ksh {req.transaction_amount_kes:,.0f}" if req.transaction_amount_kes else "Not specified",
        risk_floor=context["risk_floor"],
        det_findings=det_text,
        statutory_context=statutory_text,
        institutions=institutions_text,
        description=req.description,
    )

    llm_output = _call_compliance_llm(prompt_user)

    # Stage 5 — assemble
    result = _assemble_result(req, det_findings, llm_output, context)
    return result


@router.get(
    "/obligations/{act_name}",
    summary="All obligations and penalties under a specific Act",
    description="Returns every Section in the Act that imposes an Obligation or Penalty, with full text.",
)
async def get_obligations(
    act_name: str = Path(..., description="Act short title, e.g. 'Companies Act'"),
    company_type: str = Query(default="private", description="Filter relevance by company type"),
) -> dict:
    cypher = """
    MATCH (act:Act)
    WHERE toLower(act.short_title) CONTAINS toLower($act_name)
       OR toLower(act.name)        CONTAINS toLower($act_name)
    MATCH (act)<-[:PART_OF*1..3]-(section:Section)
    WHERE (section)-[:IMPOSES]->(:Obligation) OR (section)-[:IMPOSES]->(:Penalty)
    OPTIONAL MATCH (section)-[:IMPOSES]->(obl:Obligation)
    OPTIONAL MATCH (section)-[:IMPOSES]->(pen:Penalty)
    OPTIONAL MATCH (section)-[:DEFINED_IN]-(dl:Deadline)
    RETURN
        act.short_title                              AS act,
        act.year                                     AS year,
        section.number                               AS section,
        section.title                                AS title,
        coalesce(section.text,'')                    AS text,
        collect(DISTINCT obl.text)                   AS obligations,
        collect(DISTINCT {
            text:   pen.text,
            amount: pen.amount,
            unit:   pen.unit
        })                                           AS penalties,
        collect(DISTINCT dl.text)                    AS deadlines
    ORDER BY section.number
    LIMIT 50
    """
    rows = run_query(cypher, {"act_name": act_name})
    if not rows:
        raise HTTPException(status_code=404, detail=f"Act '{act_name}' not found in knowledge graph.")
    return {"act": act_name, "obligations_count": len(rows), "sections": rows}


@router.get(
    "/acts",
    summary="List all Acts in the knowledge graph",
)
async def list_acts() -> dict:
    cypher = """
    MATCH (act:Act)
    OPTIONAL MATCH (act)-[:ENACTED_UNDER]->(article:Article)
    OPTIONAL MATCH (act)<-[:PART_OF*1..3]-(s:Section)
    RETURN
        act.name                    AS name,
        act.short_title             AS short_title,
        act.year                    AS year,
        article.number              AS constitutional_article,
        count(DISTINCT s)           AS section_count
    ORDER BY act.year DESC, act.short_title
    """
    rows = run_query(cypher)
    return {"acts": rows, "total": len(rows)}


@router.post(
    "/multi",
    summary="Check multiple actions in one request",
    description="Run compliance checks on up to 5 actions. Useful for transaction structuring review.",
)
async def multi_check(req: MultiComplianceRequest) -> dict:
    if not req.actions:
        raise HTTPException(status_code=400, detail="Provide at least one action.")

    results = []
    for action in req.actions:
        context     = _fetch_statutory_context(action.action_type, action.description)
        det         = _deterministic_screen(action, context)
        stat_text   = _pack_statutory_context(context["sections"])
        inst_text   = _pack_institutions(context["institutions"])
        det_text    = "\n".join(f"  [{f['severity'].upper()}] {f['finding']}" for f in det) or "None."
        prompt_user = COMPLIANCE_USER_TEMPLATE.format(
            action_type=action.action_type,
            company_type=action.company_type,
            amount=f"Ksh {action.transaction_amount_kes:,.0f}" if action.transaction_amount_kes else "Not specified",
            risk_floor=context["risk_floor"],
            det_findings=det_text,
            statutory_context=stat_text,
            institutions=inst_text,
            description=action.description,
        )
        llm_out = _call_compliance_llm(prompt_user)
        result  = _assemble_result(action, det, llm_out, context)
        results.append({
            "action_type": action.action_type,
            "risk_level":  result.risk_level,
            "risk_summary": result.risk_summary,
            "finding_count": len(result.findings),
            "required_actions": result.required_actions,
        })

    overall_risk = max(results, key=lambda r: RISK_ORDER.get(r["risk_level"], 0))["risk_level"]
    return {
        "overall_risk": overall_risk,
        "action_count": len(results),
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
