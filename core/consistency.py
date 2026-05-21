"""
core/consistency.py — Tier 2: Self-consistency voting

Runs the LLM N times on the same context with temperature > 0 to generate
diverse candidate answers, then uses a fourth synthesis call to:
  - Identify the consensus position
  - Surface any factual disagreements between runs
  - Produce a single high-confidence answer with a reliability note

Why this works for legal Q&A:
  - Legal questions often have nuanced answers with multiple valid phrasings
  - When all N runs agree on the legal basis, confidence is high
  - When they disagree, the synthesis call flags it — better than silently
    returning one potentially wrong answer

Cost: N+1 LLM calls per query (disabled by default, toggle via config).
Set SELF_CONSISTENCY_RUNS=3 in .env; use SELF_CONSISTENCY_RUNS=1 to disable.
"""
from __future__ import annotations

import logging

from config import get_settings
from core.llm import call_llm

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM = """You are a Kenyan legal research supervisor.
You receive multiple independent legal research answers to the same question,
produced by different reasoning runs. Your job is to:
1. Identify where they agree (the consensus legal position)
2. Identify any factual or legal disagreements between them
3. Produce a single authoritative answer that reflects the consensus
4. Flag any genuine disagreements with [DISPUTED: ...] markers

Return a JSON object:
{
  "answer": "<the synthesised consensus answer with inline citations>",
  "consensus_level": "high" | "medium" | "low",
  "disputed_points": ["<point 1>", ...],
  "synthesis_note": "<one sentence explaining any caveats>"
}"""

SYNTHESIS_USER = """QUESTION: {question}

{runs_text}

Synthesise these into one high-confidence answer."""


def consistent_answer(
    context: str,
    question: str,
    qa_system_prompt: str,
    qa_user_template: str,
) -> dict:
    """
    Run the LLM N times with temperature > 0 then synthesise.

    Returns a dict:
      {
        "answer":          str,
        "consensus_level": "high"|"medium"|"low",
        "disputed_points": list[str],
        "synthesis_note":  str,
        "runs":            list[str],   # raw individual answers (for tracing)
      }

    If SELF_CONSISTENCY_RUNS <= 1, runs once at temperature=0 and skips synthesis.
    """
    s = get_settings()
    n_runs = s.self_consistency_runs

    prompt = qa_user_template.format(context=context, question=question)

    if n_runs <= 1:
        answer = call_llm(user=prompt, system=qa_system_prompt,
                          max_tokens=1500, temperature=0.0)
        return {
            "answer":          answer,
            "consensus_level": "high",
            "disputed_points": [],
            "synthesis_note":  "Single-run mode.",
            "runs":            [answer],
        }

    # Run N times with temperature 0.6
    logger.info("Self-consistency: running LLM %d times…", n_runs)
    runs: list[str] = []
    for i in range(n_runs):
        try:
            answer = call_llm(user=prompt, system=qa_system_prompt,
                              max_tokens=1500, temperature=0.6)
            runs.append(answer)
        except Exception as e:
            logger.warning("Consistency run %d failed: %s", i + 1, e)

    if not runs:
        raise RuntimeError("All self-consistency runs failed")

    if len(runs) == 1:
        return {
            "answer":          runs[0],
            "consensus_level": "low",
            "disputed_points": [],
            "synthesis_note":  "Only one run succeeded.",
            "runs":            runs,
        }

    # Synthesis call
    runs_text = "\n\n".join(
        f"=== RUN {i+1} ===\n{r}" for i, r in enumerate(runs)
    )
    try:
        import json
        raw = call_llm(
            user=SYNTHESIS_USER.format(question=question, runs_text=runs_text),
            system=SYNTHESIS_SYSTEM,
            max_tokens=1800,
            temperature=0.0,
            json_mode=True,
        )
        result = json.loads(raw)
        result["runs"] = runs
        return result
    except Exception as e:
        logger.warning("Synthesis call failed (%s) — returning best single run", e)
        return {
            "answer":          runs[0],
            "consensus_level": "low",
            "disputed_points": [],
            "synthesis_note":  f"Synthesis failed: {e}",
            "runs":            runs,
        }
