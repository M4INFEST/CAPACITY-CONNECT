from typing import Any


def score_applicant_match(
    requirements: list[dict[str, Any]],
    skill_snapshot: dict[str, Any],
) -> dict[str, Any]:
    skill_levels: dict[str, int] = {}
    for key in ("verified_skills", "claimed_skills"):
        for skill in skill_snapshot.get(key, []):
            competency_id = str(skill.get("competency_id", ""))
            if competency_id:
                skill_levels[competency_id] = max(
                    skill_levels.get(competency_id, 0),
                    int(skill.get("level") or 0),
                )

    total_weight = 0.0
    matched_weight = 0.0
    details: list[dict[str, Any]] = []
    for requirement in requirements:
        required_level = int(requirement["required_level"])
        if required_level < 1 or required_level > 5:
            raise ValueError("Job competency levels must be between 1 and 5.")
        weight = max(0.0, min(1.0, float(requirement.get("importance", 1.0))))
        current_level = min(required_level, max(0, skill_levels.get(str(requirement["competency_id"]), 0)))
        total_weight += weight
        matched_weight += weight * current_level / required_level
        details.append(
            {
                "competency_id": str(requirement["competency_id"]),
                "skill_name": requirement["skill_name"],
                "required_level": required_level,
                "current_level": current_level,
                "importance": weight,
                "evidence_status": (
                    "verified"
                    if any(
                        str(skill.get("competency_id")) == str(requirement["competency_id"])
                        for skill in skill_snapshot.get("verified_skills", [])
                    )
                    else "claimed"
                ),
            }
        )

    details.sort(key=lambda item: (-item["importance"], item["skill_name"].casefold()))
    return {
        "match_percentage": round(matched_weight / total_weight * 100, 1) if total_weight else 0.0,
        "scoring_version": "employer-weighted-v1",
        "explanation": (
            "Fit is the importance-weighted share of required skill levels present in the "
            "learner-approved, consented Passport snapshot. Verified and claimed evidence are labeled separately."
        ),
        "skills": details,
    }
