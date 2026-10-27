import hashlib
import json
import math
from datetime import date, timedelta
from typing import Any


def roadmap_fingerprint(
    role_id: str,
    requirements: list[dict[str, Any]],
    courses: list[dict[str, Any]],
) -> str:
    payload = {
        "role_id": role_id,
        "requirements": sorted(
            (
                str(item["competency_id"]),
                int(item["required_level"]),
                int(item["current_level"]),
                round(float(item["importance"]), 5),
            )
            for item in requirements
        ),
        "courses": sorted(
            (
                str(item["course_version_id"]),
                round(float(item["duration_hours"]), 2),
                int(item["price_cents"]),
                sorted(
                    (str(skill["competency_id"]), int(skill["level_taught"]))
                    for skill in item["skills"]
                ),
                sorted(
                    (str(prerequisite["competency_id"]), int(prerequisite["minimum_level"]))
                    for prerequisite in item["prerequisites"]
                ),
            )
            for item in courses
        ),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _course_benefit(
    course: dict[str, Any],
    targets: dict[str, dict[str, Any]],
    levels: dict[str, int],
) -> float:
    taught = {
        str(skill["competency_id"]): int(skill["level_taught"])
        for skill in course["skills"]
    }
    benefit = 0.0
    for competency_id, target in targets.items():
        current = levels.get(competency_id, 0)
        closed = min(
            max(0, int(target["required_level"]) - current),
            max(0, taught.get(competency_id, current) - current),
        )
        benefit += closed * float(target["importance"])
    return benefit


def build_course_roadmap(
    *,
    requirements: list[dict[str, Any]],
    courses: list[dict[str, Any]],
    current_levels: dict[str, int],
    weekly_study_hours: float,
    budget_cents: int | None,
    strategy: str,
    today: date,
    target_finish_date: date | None,
) -> dict[str, Any]:
    levels = dict(current_levels)
    targets = {
        str(row["competency_id"]): dict(row)
        for row in requirements
        if int(row["current_level"]) < int(row["required_level"])
    }
    original_targets = dict(targets)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    total_hours = 0.0
    total_cost = 0
    budget_limited = False
    maximum_steps = min(30, len(courses))

    for _ in range(maximum_steps * 2 + 1):
        if len(selected) >= maximum_steps:
            break
        if all(
            levels.get(skill_id, 0) >= int(target["required_level"])
            for skill_id, target in original_targets.items()
        ):
            break

        eligible: list[tuple[float, float, int, str, dict[str, Any]]] = []
        blocked_prerequisites: dict[str, dict[str, Any]] = {}
        for course in courses:
            course_id = str(course["course_version_id"])
            if course_id in selected_ids:
                continue
            unmet = [
                prerequisite
                for prerequisite in course["prerequisites"]
                if levels.get(str(prerequisite["competency_id"]), 0)
                < int(prerequisite["minimum_level"])
            ]
            if unmet:
                for prerequisite in unmet:
                    competency_id = str(prerequisite["competency_id"])
                    current = levels.get(competency_id, 0)
                    required = int(prerequisite["minimum_level"])
                    if current < required:
                        existing = blocked_prerequisites.get(competency_id)
                        if existing is None or required > existing["required_level"]:
                            blocked_prerequisites[competency_id] = {
                                "competency_id": competency_id,
                                "skill_name": prerequisite["skill_name"],
                                "required_level": required,
                                "current_level": current,
                                "importance": max(
                                    float(target["importance"])
                                    for target in targets.values()
                                )
                                if targets
                                else 1.0,
                            }
                continue
            benefit = _course_benefit(course, targets, levels)
            if benefit <= 0:
                continue
            projected_cost = total_cost + int(course["price_cents"])
            if budget_cents is not None and projected_cost > budget_cents:
                budget_limited = True
                continue
            duration = float(course["duration_hours"])
            price = int(course["price_cents"])
            if strategy == "cheapest":
                key = (
                    price / benefit if price else 0.0,
                    duration / benefit,
                    price,
                    course["title"].casefold(),
                )
            else:
                key = (
                    duration / benefit,
                    price / benefit if price else 0.0,
                    price,
                    course["title"].casefold(),
                )
            eligible.append((*key[:2], price, str(course["title"]).casefold(), course))

        if not eligible and blocked_prerequisites:
            targets.update(blocked_prerequisites)
            continue
        if not eligible:
            break

        eligible.sort(key=lambda item: item[:-1])
        course = eligible[0][-1]
        selected_ids.add(str(course["course_version_id"]))
        selected.append(course)
        total_hours += float(course["duration_hours"])
        total_cost += int(course["price_cents"])
        for skill in course["skills"]:
            competency_id = str(skill["competency_id"])
            levels[competency_id] = max(
                levels.get(competency_id, 0), int(skill["level_taught"])
            )

    total_weeks = total_hours / weekly_study_hours if weekly_study_hours else 0
    finish_date = today + timedelta(days=math.ceil(total_weeks * 7))
    if target_finish_date:
        available_weeks = max(0, (target_finish_date - today).days / 7)
        schedule_scale = max(1.0, total_weeks / available_weeks) if available_weeks else math.inf
    else:
        schedule_scale = 1.0

    milestones = []
    elapsed_hours = 0.0
    for index, course in enumerate(selected, start=1):
        duration = float(course["duration_hours"])
        start_day = math.floor(elapsed_hours / weekly_study_hours * 7)
        elapsed_hours += duration
        end_day = max(start_day, math.ceil(elapsed_hours / weekly_study_hours * 7) - 1)
        milestones.append(
            {
                "step_order": index,
                "course_version_id": str(course["course_version_id"]),
                "course_title": course["title"],
                "duration_hours": duration,
                "price_cents": int(course["price_cents"]),
                "planned_start_date": (today + timedelta(days=start_day)).isoformat(),
                "planned_end_date": (today + timedelta(days=end_day)).isoformat(),
                "skills_closed": [
                    {
                        "skill_name": skill["skill_name"],
                        "level_taught": int(skill["level_taught"]),
                    }
                    for skill in course["skills"]
                    if str(skill["competency_id"]) in original_targets
                ],
                "prerequisites": [
                    {
                        "skill_name": item["skill_name"],
                        "minimum_level": int(item["minimum_level"]),
                    }
                    for item in course["prerequisites"]
                ],
            }
        )

    remaining = [
        {
            "competency_id": skill_id,
            "skill_name": target["skill_name"],
            "current_level": levels.get(skill_id, 0),
            "required_level": int(target["required_level"]),
            "gap_levels": max(0, int(target["required_level"]) - levels.get(skill_id, 0)),
        }
        for skill_id, target in original_targets.items()
        if levels.get(skill_id, 0) < int(target["required_level"])
    ]
    return {
        "milestones": milestones,
        "total_hours": round(total_hours, 2),
        "total_cost_cents": total_cost,
        "estimated_finish_date": finish_date.isoformat(),
        "target_finish_date": target_finish_date.isoformat() if target_finish_date else None,
        "schedule_over_capacity": schedule_scale > 1.0,
        "schedule_scale": round(schedule_scale, 2) if math.isfinite(schedule_scale) else None,
        "budget_limited": budget_limited,
        "remaining_gaps": remaining,
        "complete": not remaining,
    }
