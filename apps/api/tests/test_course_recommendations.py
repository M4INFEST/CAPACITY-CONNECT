import unittest

from app.services.course_recommendations import (
    RoleGap,
    affordability_order,
    reason_summary,
    score_course,
)


class CourseRecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gaps = [
            RoleGap(
                role_id="data-role",
                role_name="Data Analyst",
                competency_id="sql-id",
                skill_name="SQL",
                current_level=1,
                required_level=4,
                importance=0.9,
            ),
            RoleGap(
                role_id="data-role",
                role_name="Data Analyst",
                competency_id="python-id",
                skill_name="Python",
                current_level=2,
                required_level=3,
                importance=0.6,
            ),
        ]

    def test_score_counts_only_gap_levels_that_course_can_close(self) -> None:
        score, reasons = score_course(
            2,
            [
                {"competency_id": "sql-id", "level_taught": 3},
                {"competency_id": "python-id", "level_taught": 5},
            ],
            self.gaps,
        )

        self.assertEqual(score, 1.2)
        self.assertEqual([reason["skill_name"] for reason in reasons], ["SQL", "Python"])
        self.assertEqual(reasons[0]["levels_closed"], 2)
        self.assertTrue(reasons[0]["critical"])
        self.assertEqual(
            reason_summary(reasons, 2),
            "Closes 2 level(s) of a critical SQL gap for Data Analyst in 2 study hour(s).",
        )

    def test_course_with_only_non_gap_skills_has_no_recommendation_reason(self) -> None:
        score, reasons = score_course(
            4,
            [{"competency_id": "unneeded-skill", "level_taught": 5}],
            self.gaps,
        )

        self.assertEqual(score, 0)
        self.assertEqual(reasons, [])
        self.assertIn("does not close a current gap", reason_summary(reasons, 4))

    def test_zero_or_unknown_duration_cannot_be_ranked(self) -> None:
        skills = [{"competency_id": "sql-id", "level_taught": 4}]
        self.assertEqual(score_course(None, skills, self.gaps), (0.0, []))
        self.assertEqual(score_course(0, skills, self.gaps), (0.0, []))

    def test_low_cost_order_changes_only_when_paid_preference_is_set(self) -> None:
        self.assertLess(affordability_order(0, False), affordability_order(100_000, False))
        self.assertEqual(affordability_order(100_000, True), 0)


if __name__ == "__main__":
    unittest.main()
