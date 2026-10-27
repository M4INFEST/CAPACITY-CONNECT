from dataclasses import dataclass


@dataclass(frozen=True)
class RoleGap:
    role_id: str
    role_name: str
    competency_id: str
    skill_name: str
    current_level: int
    required_level: int
    importance: float

    @property
    def gap(self) -> int:
        return max(0, self.required_level - self.current_level)

    @property
    def critical(self) -> bool:
        return self.importance >= 0.75


def score_course(
    duration_hours: float | None,
    course_skills: list[dict[str, object]],
    role_gaps: list[RoleGap],
) -> tuple[float, list[dict[str, object]]]:
    if duration_hours is None or duration_hours <= 0:
        return 0.0, []

    taught_levels = {
        str(skill["competency_id"]): int(skill["level_taught"] or 0)
        for skill in course_skills
    }
    reasons: list[dict[str, object]] = []
    weighted_gap_closed = 0.0
    for gap in role_gaps:
        taught_level = taught_levels.get(gap.competency_id)
        if taught_level is None or gap.gap <= 0:
            continue
        levels_closed = min(gap.gap, max(0, taught_level - gap.current_level))
        if levels_closed <= 0:
            continue
        weighted_gap_closed += levels_closed * gap.importance
        reasons.append(
            {
                "role_id": gap.role_id,
                "role_name": gap.role_name,
                "competency_id": gap.competency_id,
                "skill_name": gap.skill_name,
                "levels_closed": levels_closed,
                "required_gap": gap.gap,
                "critical": gap.critical,
                "importance": gap.importance,
                "level_taught": taught_level,
            }
        )

    score = weighted_gap_closed / duration_hours
    reasons.sort(
        key=lambda reason: (
            not bool(reason["critical"]),
            -float(reason["importance"]),
            str(reason["skill_name"]).casefold(),
        )
    )
    return round(score, 4), reasons


def reason_summary(reasons: list[dict[str, object]], duration_hours: float) -> str:
    if not reasons:
        return "This course does not close a current gap for your selected target roles."
    top = reasons[0]
    critical = "a critical" if top["critical"] else "a"
    return (
        f"Closes {top['levels_closed']} level(s) of {critical} "
        f"{top['skill_name']} gap for {top['role_name']} in "
        f"{duration_hours:g} study hour(s)."
    )


def affordability_order(price_cents: int, prioritize_paid: bool) -> int:
    if prioritize_paid:
        return 0
    if price_cents == 0:
        return 0
    if price_cents <= 50_000:
        return 1
    return 2
