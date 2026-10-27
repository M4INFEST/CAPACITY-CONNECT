import unittest
from datetime import date

from app.services.roadmaps import build_course_roadmap


def course(
    course_id: str,
    title: str,
    *,
    hours: float,
    price: int,
    skills: list[dict[str, object]],
    prerequisites: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "course_version_id": course_id,
        "title": title,
        "duration_hours": hours,
        "price_cents": price,
        "skills": skills,
        "prerequisites": prerequisites or [],
    }


class RoadmapPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requirements = [
            {
                "competency_id": "target",
                "skill_name": "Target skill",
                "required_level": 4,
                "current_level": 0,
                "importance": 1.0,
            }
        ]

    def build(self, *, strategy: str, courses: list[dict[str, object]], budget: int | None = None):
        return build_course_roadmap(
            requirements=self.requirements,
            courses=courses,
            current_levels={},
            weekly_study_hours=5,
            budget_cents=budget,
            strategy=strategy,
            today=date(2025, 1, 1),
            target_finish_date=None,
        )

    def test_prerequisite_course_is_planned_before_dependent_course(self) -> None:
        courses = [
            course(
                "advanced",
                "Advanced course",
                hours=3,
                price=100,
                skills=[{"competency_id": "target", "skill_name": "Target skill", "level_taught": 4}],
                prerequisites=[
                    {
                        "competency_id": "foundation",
                        "skill_name": "Foundation",
                        "minimum_level": 2,
                    }
                ],
            ),
            course(
                "foundation-course",
                "Foundation course",
                hours=2,
                price=50,
                skills=[{"competency_id": "foundation", "skill_name": "Foundation", "level_taught": 2}],
            ),
        ]

        result = self.build(strategy="fastest", courses=courses)

        self.assertEqual(
            [item["course_title"] for item in result["milestones"]],
            ["Foundation course", "Advanced course"],
        )
        self.assertTrue(result["complete"])

    def test_fastest_and_cheapest_strategies_choose_expected_course(self) -> None:
        courses = [
            course(
                "quick",
                "Quick course",
                hours=2,
                price=20_000,
                skills=[{"competency_id": "target", "skill_name": "Target skill", "level_taught": 2}],
            ),
            course(
                "complete",
                "Complete course",
                hours=8,
                price=5_000,
                skills=[{"competency_id": "target", "skill_name": "Target skill", "level_taught": 4}],
            ),
        ]

        fastest = self.build(strategy="fastest", courses=courses)
        cheapest = self.build(strategy="cheapest", courses=courses)

        self.assertEqual(fastest["milestones"][0]["course_title"], "Quick course")
        self.assertEqual(cheapest["milestones"][0]["course_title"], "Complete course")

    def test_budget_cap_keeps_unaffordable_course_out_and_reports_remaining_gap(self) -> None:
        courses = [
            course(
                "expensive",
                "Expensive course",
                hours=3,
                price=10_000,
                skills=[{"competency_id": "target", "skill_name": "Target skill", "level_taught": 4}],
            )
        ]

        result = self.build(strategy="cheapest", courses=courses, budget=1_000)

        self.assertEqual(result["milestones"], [])
        self.assertTrue(result["budget_limited"])
        self.assertEqual(result["remaining_gaps"][0]["gap_levels"], 4)

    def test_milestones_use_weekly_hours_to_assign_dates(self) -> None:
        courses = [
            course(
                "target-course",
                "Target course",
                hours=2,
                price=0,
                skills=[{"competency_id": "target", "skill_name": "Target skill", "level_taught": 4}],
            )
        ]

        result = self.build(strategy="fastest", courses=courses)

        self.assertEqual(result["milestones"][0]["planned_start_date"], "2025-01-01")
        self.assertEqual(result["milestones"][0]["planned_end_date"], "2025-01-03")
        self.assertEqual(result["estimated_finish_date"], "2025-01-04")


if __name__ == "__main__":
    unittest.main()
