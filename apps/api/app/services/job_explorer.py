from typing import Any

APPLY_NOW_THRESHOLD = 70.0
ALMOST_THERE_THRESHOLD = 50.0
MINIMUM_RESPONSE_SAMPLE = 3


def score_job_match(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    total_weight = 0.0
    matched_weight = 0.0
    covered: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for requirement in requirements:
        required = int(requirement["required_level"])
        if required < 1 or required > 5:
            raise ValueError("Job competency levels must be between 1 and 5.")
        current = min(required, max(0, int(requirement.get("current_level", 0))))
        importance = float(requirement.get("importance", 1.0))
        weight = max(0.0, min(1.0, importance))
        total_weight += weight
        matched_weight += weight * current / required
        item = {
            "competency_id": str(requirement["competency_id"]),
            "skill_name": requirement["skill_name"],
            "current_level": current,
            "required_level": required,
            "gap_levels": max(0, required - current),
            "importance": weight,
        }
        if current >= required:
            covered.append(item)
        else:
            gaps.append(item)
    match_percentage = round(
        matched_weight / total_weight * 100 if total_weight else 0.0,
        1,
    )
    group = (
        "apply_now"
        if match_percentage >= APPLY_NOW_THRESHOLD
        else "almost_there"
        if match_percentage >= ALMOST_THERE_THRESHOLD
        else "learn_first"
    )
    gaps.sort(key=lambda item: (-item["importance"], -item["gap_levels"], item["skill_name"].casefold()))
    return {
        "match_percentage": match_percentage,
        "recommendation_group": group,
        "covered_skills": covered,
        "skill_gaps": gaps,
        "explanation": (
            "Match is the importance-weighted share of required competency levels "
            "already demonstrated in your Passport."
        ),
    }


def summarize_response_time(
    median_hours: float | None,
    response_count: int,
) -> dict[str, Any]:
    if response_count < MINIMUM_RESPONSE_SAMPLE or median_hours is None:
        return {
            "status": "not_enough_data",
            "median_hours": None,
            "response_count": response_count,
            "minimum_sample_size": MINIMUM_RESPONSE_SAMPLE,
        }
    return {
        "status": "available",
        "median_hours": round(float(median_hours), 1),
        "response_count": response_count,
        "minimum_sample_size": MINIMUM_RESPONSE_SAMPLE,
    }
