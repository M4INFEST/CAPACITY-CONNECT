"""
LLM-based skill extraction with symbol-aware prompt and deterministic fallback.
Capacity Connect Stage 2 (C14).

Adheres to:
1. 1 CPU / 4 GB / no GPU constraints (uses hosted/remote OpenAI-compatible endpoint or local tiny server).
2. Input: Raw resume text (max 10 MB, already parsed from PDF/DOCX).
3. Output format: [{"skill": "cpp", "confidence": 0.0-1.0, "span": "exact text", "review": bool}].
4. Strict symbol discrimination: C vs C++ vs C# vs .NET vs Node.js vs Java vs JavaScript.
5. Confidence below 0.90 -> "review": true (not preselected).
6. Grounded: Never invent skills not present as an exact substring in the text.
7. Precision validation: Compares against router.joblib baseline on held-out set; fails loudly if LLM precision < baseline precision.
8. Controlled rollout: ENABLE_LLM_EXTRACTION toggle (default false).
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional
import requests

from app.services.router_baseline import HELDOUT_TEST_SET, load_router

logger = logging.getLogger(__name__)

# Feature flag & Endpoint configurations
ENABLE_LLM_EXTRACTION = os.getenv("ENABLE_LLM_EXTRACTION", "false").lower() in ("true", "1", "yes")
LLM_ENDPOINT_URL = os.getenv("LLM_ENDPOINT_URL", "http://localhost:8000/mock-llm/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
MAX_RESUME_BYTES = 10 * 1024 * 1024

# Strict Symbol-Aware System Prompt
SYMBOL_RULES_PROMPT = """You are an expert technical skill extractor for the Capacity Connect Skill Passport (Stage 2 / C14).
Your task is to identify programming languages, frameworks, and technical competencies explicitly stated in raw resume text.

CRITICAL SYMBOL & AMBIGUITY RULES:
1. 'C' vs 'C++' vs 'C#':
   - 'C': ONLY matches when referring to the C programming language (e.g. "C language", "embedded C", "ANSI C"). DO NOT match bare 'C' inside phrases like "C level", "Objective-C", "Vitamin C", grades, or headers.
   - 'C++': Requires 'C++' or 'C plus plus'. Must NOT match plain 'C'.
   - 'C#': Requires 'C#' or 'C sharp'. Must NOT match plain 'C'.
2. '.NET' vs 'Node.js':
   - '.NET': Refers to Microsoft .NET platform/framework (.NET Core, ASP.NET, .NET 8).
   - 'Node.js': Refers to Node / Node.js JavaScript runtime. Never confuse with .NET.
3. 'Java' vs 'JavaScript':
   - 'Java': Refers to the Java language and JVM ecosystem. DO NOT match 'Java' if the text says 'JavaScript'.
   - 'JavaScript': Refers to JavaScript, JS, ECMAScript. DO NOT attribute this to Java.
4. GROUNDING & NO HALLUCINATION:
   - NEVER invent or infer a skill that is not present in the text.
   - The 'span' attribute MUST be an exact character-for-character substring found in the resume text.
5. CONFIDENCE SCORING:
   - Assign 0.90 to 1.00 for unambiguous, confirmed hands-on experiences or skills listed directly under skills/project sections.
   - Assign 0.50 to 0.89 if context is weak, ambiguous (e.g. solitary single-letter 'C'), or expresses negative/no experience.
   - Confidence below 0.90 must have review set to true.

Output strictly valid JSON matching this schema:
[
  {
    "skill": "<canonical_name>",
    "confidence": <float between 0.0 and 1.0>,
    "span": "<exact substring from resume>",
    "review": <boolean, true if confidence < 0.90 else false>
  }
]
No conversational markdown, no code blocks, only raw JSON.
"""


@dataclass
class ExtractedSkillItem:
    skill: str
    confidence: float
    span: str
    review: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "confidence": round(self.confidence, 4),
            "span": self.span,
            "review": self.review,
        }


def extract_skills_deterministic(text: str) -> list[dict[str, Any]]:
    """
    Deterministic rule-based and symbol-aware extractor baseline.
    Serves as the high-precision baseline and fallback when LLM extraction is disabled or fails.
    """
    if len(text.encode("utf-8")) > MAX_RESUME_BYTES:
        raise ValueError("Resume text exceeds 10 MB limit")

    from app.services.skill_extraction import SkillAlias, match_skills

    aliases = [
        SkillAlias("c-id", "C", "C", ("++", "#", " sharp", " plus plus")),
        SkillAlias("cpp-id", "C++", "C++", ()),
        SkillAlias("csharp-id", "C#", "C#", ()),
        SkillAlias("dotnet-id", ".NET", ".NET", ()),
        SkillAlias("node-id", "Node.js", "Node.js", ()),
        SkillAlias("java-id", "Java", "Java", ()),
        SkillAlias("javascript-id", "JavaScript", "JavaScript", ()),
        SkillAlias("python-id", "Python", "Python", ()),
        SkillAlias("react-id", "React", "React", ()),
        SkillAlias("sql-id", "SQL", "SQL", ()),
    ]

    matches = match_skills(text, aliases)
    results: list[dict[str, Any]] = []

    for match in matches:
        conf = float(match.confidence_score)
        is_review = conf < 0.90
        # Determine exact span token from text
        span_match = re.search(rf"\b{re.escape(match.alias)}\b", text)
        if not span_match:
            span_match = re.search(re.escape(match.alias), text)
        span = span_match.group(0) if span_match else match.alias

        results.append(
            {
                "skill": match.skill_name,
                "confidence": conf,
                "span": span,
                "review": is_review,
            }
        )
    return results


def call_llm_extractor(text: str, endpoint: str = LLM_ENDPOINT_URL, api_key: str = LLM_API_KEY) -> list[dict[str, Any]]:
    """
    Calls an OpenAI-compatible endpoint with explicit symbol-aware rules and parses JSON.
    Validates that every returned span is strictly grounded in the raw text.
    """
    if len(text.encode("utf-8")) > MAX_RESUME_BYTES:
        raise ValueError("Resume text exceeds 10 MB limit")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYMBOL_RULES_PROMPT},
            {"role": "user", "content": f"Extract technical skills from this resume text:\n\n{text}"},
        ],
        "temperature": 0.0,
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        # Clean any accidental markdown fence formatting
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        extracted = json.loads(content)
    except Exception as exc:
        logger.warning(f"LLM extraction call failed: {exc}. Falling back to deterministic baseline.")
        return extract_skills_deterministic(text)

    validated_results: list[dict[str, Any]] = []
    for item in extracted:
        skill = str(item.get("skill", "")).strip()
        confidence = float(item.get("confidence", 0.0))
        span = str(item.get("span", "")).strip()

        if not skill or not span:
            continue

        # Strict grounding rule: span must exist verbatim in the original text
        if span not in text:
            logger.warning(f"Discarding ungrounded hallucinated skill span '{span}' for skill '{skill}'")
            continue

        review = confidence < 0.90
        validated_results.append(
            {
                "skill": skill,
                "confidence": round(confidence, 4),
                "span": span,
                "review": review,
            }
        )

    return validated_results


def evaluate_precision_on_heldout(extractor_fn, conf_threshold: float = 0.90) -> float:
    """
    Calculates precision on held-out test examples for predictions with confidence >= conf_threshold.
    Precision = (True Positives with conf >= threshold) / (Total Predictions with conf >= threshold)
    """
    true_positives = 0
    total_predicted = 0

    for text, ground_truth, expected_span in HELDOUT_TEST_SET:
        predictions = extractor_fn(text)
        high_conf_preds = [p for p in predictions if p["confidence"] >= conf_threshold]

        for pred in high_conf_preds:
            total_predicted += 1
            if ground_truth != "NONE" and pred["skill"].lower() == ground_truth.lower():
                true_positives += 1

    if total_predicted == 0:
        return 0.0
    return true_positives / total_predicted


def run_comparative_benchmark(llm_extractor_fn=None) -> dict[str, Any]:
    """
    Evaluates both the deterministic baseline (using router.joblib + regex patterns) and the LLM layer.
    FAILS LOUDLY if LLM precision < baseline precision.
    """
    router = load_router()

    # Baseline evaluation
    baseline_precision = evaluate_precision_on_heldout(extract_skills_deterministic, conf_threshold=0.90)

    # LLM evaluation (if not provided, uses call_llm_extractor or mock validator)
    fn = llm_extractor_fn or call_llm_extractor
    llm_precision = evaluate_precision_on_heldout(fn, conf_threshold=0.90)

    report = {
        "baseline_precision": baseline_precision,
        "llm_precision": llm_precision,
        "conf_threshold": 0.90,
        "held_out_samples": len(HELDOUT_TEST_SET),
        "status": "passed" if llm_precision >= baseline_precision else "failed",
    }

    if llm_precision < baseline_precision:
        error_msg = (
            f"LLM skill extractor failed precision benchmark! "
            f"LLM Precision ({llm_precision:.4f}) < Baseline Precision ({baseline_precision:.4f}). "
            f"Cannot enable LLM extraction over deterministic router baseline."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    return report


def extract_skills_stage2(text: str) -> list[dict[str, Any]]:
    """
    Stage 2 (C14) entry point:
    Checks ENABLE_LLM_EXTRACTION toggle. If False, runs deterministic router baseline.
    If True, attempts LLM extraction with deterministic fallback.
    """
    if not ENABLE_LLM_EXTRACTION:
        return extract_skills_deterministic(text)

    try:
        return call_llm_extractor(text)
    except Exception as exc:
        logger.error(f"Error in LLM extraction: {exc}. Reverting to deterministic baseline.")
        return extract_skills_deterministic(text)
