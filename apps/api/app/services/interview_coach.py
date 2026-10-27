import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an expert interview coach and hiring manager.
Your job is to evaluate a candidate's answer to an interview question using the STAR framework (Situation, Task, Action, Result)
and provide actionable feedback to help them succeed in landing the job.

Scoring criteria (0-100 scale):
- Relevance Score (0-100): How directly and accurately the answer addresses the job requirement and question.
  * 90-100: Flawless alignment with role expectations and question premise.
  * 70-89: Solid answer with slight gaps or secondary tangents.
  * 50-69: Partially answers question, missing key specifics.
  * 0-49: Off-topic or fails to demonstrate required competence.
- Confidence Score (0-100): Structure, clarity, professional vocabulary, and assertiveness.
  * 90-100: Structured (clear Situation, Task, Action, quantifiable Result), crisp, professional.
  * 70-89: Coherent and organized, but minor hesitation or informal phrasing.
  * 50-69: Rambling or passive description of what happened.
  * 0-49: Fragmented or disorganized.
- Final Score: Weighted combination emphasizing concrete results and actions taken.

You must return a JSON object with EXACTLY this structure:
{
  "relevance_score": number,
  "confidence_score": number,
  "final_score": number,
  "strengths": ["bullet 1", "bullet 2"],
  "improvements": ["bullet 1", "bullet 2"],
  "rewritten_answer": {
    "star": "Full rewrite following Situation, Task, Action, and Result with quantifiable outcomes",
    "concise": "High-impact 2-sentence elevator response suitable for the live interview"
  }
}
"""

def generate_interview_questions_for_job(
    job_title: str,
    company_name: str,
    job_description: str,
    required_skills: list[str],
) -> list[dict[str, Any]]:
    questions = [
        {
            "id": 1,
            "category": "Behavioral (STAR)",
            "skill": required_skills[0] if required_skills else "Problem Solving",
            "question": f"Describe a complex project at work or university involving {required_skills[0] if required_skills else 'your core technical skills'}. What was the situation, your specific role, and the measured outcome?",
            "hints": "Structure your answer using Situation, Task, Action, and quantifiable Result (STAR).",
            "ideal_elements": [
                "Defined business or user problem clearly",
                "Explicit personal actions rather than team generalizations",
                "Quantified metrics (e.g., % latency reduction, time saved, revenue impact)",
            ],
        },
        {
            "id": 2,
            "category": "Technical Architecture",
            "skill": required_skills[1] if len(required_skills) > 1 else (required_skills[0] if required_skills else "System Design"),
            "question": f"How have you applied {required_skills[1] if len(required_skills) > 1 else 'best architectural practices'} to ensure high performance, security, and scalability under production load?",
            "hints": "Discuss trade-offs, caching, concurrency, or database indexing considerations.",
            "ideal_elements": [
                "Identified bottlenecks and trade-offs",
                "Selected appropriate design patterns or algorithms",
                "Validated performance with benchmarking or monitoring",
            ],
        },
        {
            "id": 3,
            "category": "Collaboration & Conflict",
            "skill": "Teamwork & Delivery",
            "question": f"At {company_name or 'a fast-paced team'}, priorities can shift rapidly. Tell me about a time you had a technical disagreement with a colleague or stakeholder. How did you resolve it?",
            "hints": "Focus on data-driven decision making, empathy, and collective team success.",
            "ideal_elements": [
                "Maintained objective, professional stance",
                "Used data, prototypes, or user needs to decide path",
                "Delivered project on schedule while preserving strong relationships",
            ],
        },
    ]
    return questions


def evaluate_interview_answer_with_star(
    question: str,
    user_answer: str,
    required_skill: str,
) -> dict[str, Any]:
    user_answer = (user_answer or "").strip()
    if not user_answer:
        return {
            "relevance_score": 0.0,
            "confidence_score": 0.0,
            "final_score": 0.0,
            "strengths": [],
            "improvements": ["Please provide an answer to receive feedback."],
            "rewritten_answer": {
                "star": "No response provided to rewrite.",
                "concise": "No response provided.",
            },
        }

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            prompt = f"""
Evaluate this interview answer for a candidate targeting skill: {required_skill}

Question:
{question}

Candidate Answer:
{user_answer}
"""
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            data = json.loads(response.choices[0].message.content or "{}")
            return {
                "relevance_score": float(data.get("relevance_score", 70)),
                "confidence_score": float(data.get("confidence_score", 70)),
                "final_score": float(data.get("final_score", 70)),
                "strengths": data.get("strengths", []),
                "improvements": data.get("improvements", []),
                "rewritten_answer": data.get("rewritten_answer", {}),
            }
        except Exception as err:
            logger.warning("OpenAI evaluation failed, using heuristic STAR evaluator: %s", err)

    words = user_answer.split()
    word_count = len(words)
    
    action_verbs = {
        "built", "designed", "architected", "implemented", "deployed", "spearheaded",
        "created", "optimized", "refactored", "automated", "resolved", "led", "developed"
    }
    found_verbs = [w.lower().strip(",.") for w in words if w.lower().strip(",.") in action_verbs]
    unique_verbs = list(dict.fromkeys(found_verbs))
    
    has_metrics = any(char.isdigit() or char in "%" for char in user_answer)
    result_keywords = {"improved", "reduced", "increased", "resulted", "achieved", "delivered", "outcome", "boosted"}
    found_results = [w.lower().strip(",.") for w in words if w.lower().strip(",.") in result_keywords]

    has_situation = any(k in user_answer.lower() for k in ["when", "during", "project", "company", "client", "problem"])
    has_task = any(k in user_answer.lower() for k in ["tasked", "goal", "needed to", "objective", "responsible for"])
    has_action = len(found_verbs) > 0
    has_outcome = has_metrics or len(found_results) > 0

    rel_score = 60.0
    if len(words) >= 30:
        rel_score += 15.0
    if required_skill.lower() in user_answer.lower():
        rel_score += 15.0
    if len(found_verbs) >= 2:
        rel_score += 10.0
    rel_score = min(rel_score, 95.0)

    conf_score = 55.0
    if has_situation and has_action:
        conf_score += 15.0
    if has_outcome:
        conf_score += 20.0
    if word_count > 60:
        conf_score += 10.0
    conf_score = min(conf_score, 92.0)

    final_score = round(0.55 * rel_score + 0.45 * conf_score, 1)

    strengths = []
    if len(unique_verbs) >= 1:
        strengths.append(f"Strong active ownership demonstrated using verbs: {', '.join(unique_verbs[:3])}.")
    if has_outcome:
        strengths.append("Included clear results and business/technical impact.")
    if word_count >= 40:
        strengths.append("Thorough depth and clear explanation of the engineering process.")
    if not strengths:
        strengths.append("Direct answer that addresses the core prompt.")

    improvements = []
    if not has_outcome or not has_metrics:
        improvements.append("Quantify your result: Add specific metrics like percentage latency reduction or users impacted.")
    if len(found_verbs) < 2:
        improvements.append("Emphasize personal agency: Highlight specific technical decisions you personally made.")
    if word_count < 40:
        improvements.append("Elaborate on the Situation and Task before detailing your technical action.")

    star_rewrite = (
        f"Situation & Task: In my previous project involving {required_skill}, we encountered performance and scalability bottlenecks that directly impacted users. "
        f"Action: I systematically {found_verbs[0] if found_verbs else 'analyzed'} the codebase, {found_verbs[1] if len(found_verbs) > 1 else 'engineered'} a decoupled architecture, "
        f"and automated automated integration test suites. "
        f"Result: This resulted in a 40% reduction in response latency and zero downtime deployment, ensuring full delivery on schedule."
    )
    concise_rewrite = (
        f"I led the {required_skill} implementation by diagnosing core bottlenecks and deploying an optimized solution, "
        f"delivering measurable stability and a 40% performance boost."
    )

    return {
        "relevance_score": rel_score,
        "confidence_score": conf_score,
        "final_score": final_score,
        "strengths": strengths[:3],
        "improvements": improvements[:3],
        "rewritten_answer": {
            "star": star_rewrite,
            "concise": concise_rewrite,
        },
    }
