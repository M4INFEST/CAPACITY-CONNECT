from datetime import datetime
from typing import Any

MINIMUM_DEMAND_SAMPLE = 10


def _priority(
    *,
    current_level: int,
    required_level: int,
    importance: float,
    has_employer_goal: bool,
) -> str:
    if has_employer_goal:
        return "critical"
    if current_level >= required_level:
        return "complete"
    weighted_gap = importance * (required_level - current_level) / required_level
    if weighted_gap >= 0.5:
        return "critical"
    if weighted_gap >= 0.25:
        return "high"
    if weighted_gap > 0:
        return "medium"
    return "nice_to_have"


def build_job_gap_report(
    rows: list[dict[str, Any]],
    proposed_levels: dict[str, int] | None = None,
) -> dict[str, Any]:
    proposed_levels = proposed_levels or {}
    roles: dict[str, dict[str, Any]] = {}
    for row in rows:
        role_id = str(row["role_id"])
        role = roles.setdefault(
            role_id,
            {
                "role_id": role_id,
                "role_name": row["role_name"],
                "skills": [],
                "weighted_score": 0.0,
                "total_weight": 0.0,
                "last_observed_at": None,
                "market_sample_count": 0,
            },
        )
        competency_id = str(row["competency_id"])
        required = int(row["required_level"])
        current = max(
            0,
            min(
                required,
                proposed_levels.get(competency_id, int(row["current_level"])),
            ),
        )
        importance = float(row["importance"])
        sample_size = int(row["sample_size"]) if row.get("sample_size") is not None else None
        demand_score = (
            float(row["demand_score"])
            if row.get("demand_score") is not None
            else None
        )
        demand_available = (
            sample_size is not None
            and sample_size >= MINIMUM_DEMAND_SAMPLE
            and demand_score is not None
        )
        demand_weight = max(0.1, demand_score) if demand_available else 1.0
        employer_goal_level = (
            int(row["employer_goal_level"])
            if row.get("employer_goal_level") is not None
            else None
        )
        has_employer_goal = employer_goal_level is not None and current < employer_goal_level
        effective_weight = importance * demand_weight * (2.0 if has_employer_goal else 1.0)
        role["total_weight"] += effective_weight
        role["weighted_score"] += effective_weight * current / required
        role["market_sample_count"] = max(
            role["market_sample_count"], sample_size or 0
        )

        observed_at = row.get("observed_at")
        if isinstance(observed_at, datetime):
            observed_at = observed_at.isoformat()
        if observed_at and (
            role["last_observed_at"] is None
            or str(observed_at) > role["last_observed_at"]
        ):
            role["last_observed_at"] = str(observed_at)

        role["skills"].append(
            {
                "competency_id": competency_id,
                "skill_name": row["skill_name"],
                "current_level": current,
                "required_level": required,
                "gap_levels": max(0, required - current),
                "priority": _priority(
                    current_level=current,
                    required_level=required,
                    importance=effective_weight,
                    has_employer_goal=has_employer_goal,
                ),
                "employer_feedback_goal": (
                    {
                        "target_level": employer_goal_level,
                        "note": row["employer_goal_note"],
                    }
                    if has_employer_goal
                    else None
                ),
                "course_href": "/learning",
                "demand": {
                    "status": "available" if demand_available else "not_enough_data",
                    "score": demand_score if demand_available else None,
                    "source": row.get("source_name"),
                    "source_url": row.get("source_url"),
                    "observed_at": observed_at,
                    "sample_size": sample_size,
                    "minimum_sample_size": MINIMUM_DEMAND_SAMPLE,
                    "source_type": (row.get("provenance") or {}).get("source_type"),
                },
            }
        )

    reports = []
    for role in roles.values():
        total_weight = role.pop("total_weight")
        weighted_score = role.pop("weighted_score")
        role["match_percentage"] = (
            round(weighted_score / total_weight * 100, 1) if total_weight else 0.0
        )
        role["skills"].sort(
            key=lambda skill: (
                skill["priority"] != "critical",
                skill["priority"] != "high",
                skill["skill_name"].casefold(),
            )
        )
        reports.append(role)
    reports.sort(key=lambda role: role["role_name"].casefold())
    return {
        "minimum_demand_sample_size": MINIMUM_DEMAND_SAMPLE,
        "roles": reports,
    }


def simulate_job_gap(
    rows: list[dict[str, Any]],
    competency_id: str,
    proposed_level: int,
) -> dict[str, Any]:
    current = build_job_gap_report(rows)
    matching = [row for row in rows if str(row["competency_id"]) == competency_id]
    if not matching:
        raise ValueError("The selected competency is not part of this role.")
    simulated = build_job_gap_report(
        rows,
        {competency_id: proposed_level},
    )
    before = current["roles"][0]["match_percentage"]
    after = simulated["roles"][0]["match_percentage"]
    return {
        "before_match_percentage": before,
        "after_match_percentage": after,
        "change_percentage_points": round(after - before, 1),
        "report": simulated["roles"][0],
    }
