import unittest

from app.services.job_gap_analysis import build_job_gap_report, simulate_job_gap


def row(
    competency_id: str,
    skill_name: str,
    *,
    level: int,
    required: int,
    importance: float = 1.0,
    sample_size: int | None = None,
    demand_score: float | None = None,
    employer_goal_level: int | None = None,
) -> dict[str, object]:
    return {
        "role_id": "role-1",
        "role_name": "Software Engineer",
        "competency_id": competency_id,
        "skill_name": skill_name,
        "current_level": level,
        "required_level": required,
        "importance": importance,
        "sample_size": sample_size,
        "demand_score": demand_score,
        "source_name": "Approved dataset" if sample_size is not None else None,
        "source_url": "https://example.org/source" if sample_size is not None else None,
        "observed_at": "2026-01-01T00:00:00+00:00" if sample_size is not None else None,
        "provenance": {"source_type": "open_dataset"} if sample_size is not None else {},
        "employer_goal_level": employer_goal_level,
        "employer_goal_note": "Improve SQL query design" if employer_goal_level else None,
    }


class JobGapAnalysisTests(unittest.TestCase):
    def test_provenance_is_shown_only_when_sample_meets_minimum(self) -> None:
        report = build_job_gap_report(
            [
                row(
                    "sql",
                    "SQL",
                    level=1,
                    required=4,
                    sample_size=9,
                    demand_score=0.8,
                ),
                row(
                    "python",
                    "Python",
                    level=2,
                    required=4,
                    sample_size=10,
                    demand_score=0.7,
                ),
            ]
        )

        skills = {skill["skill_name"]: skill for skill in report["roles"][0]["skills"]}
        self.assertEqual(skills["SQL"]["demand"]["status"], "not_enough_data")
        self.assertEqual(skills["Python"]["demand"]["status"], "available")
        self.assertEqual(skills["Python"]["demand"]["source"], "Approved dataset")

    def test_market_demand_gives_more_weight_to_high_demand_gaps(self) -> None:
        unweighted = build_job_gap_report(
            [
                row("sql", "SQL", level=1, required=4, importance=1.0),
                row("python", "Python", level=4, required=4, importance=1.0),
            ]
        )["roles"][0]["match_percentage"]
        weighted = build_job_gap_report(
            [
                row(
                    "sql",
                    "SQL",
                    level=1,
                    required=4,
                    importance=1.0,
                    sample_size=20,
                    demand_score=1.0,
                ),
                row(
                    "python",
                    "Python",
                    level=4,
                    required=4,
                    importance=1.0,
                    sample_size=20,
                    demand_score=0.25,
                ),
            ]
        )["roles"][0]["match_percentage"]

        self.assertLess(weighted, unweighted)
        self.assertEqual(weighted, 40.0)

    def test_employer_feedback_goal_gets_critical_priority(self) -> None:
        report = build_job_gap_report(
            [
                row(
                    "sql",
                    "SQL",
                    level=2,
                    required=4,
                    importance=0.2,
                    employer_goal_level=3,
                )
            ]
        )

        skill = report["roles"][0]["skills"][0]
        self.assertEqual(skill["priority"], "critical")
        self.assertEqual(skill["employer_feedback_goal"]["target_level"], 3)

    def test_what_if_returns_match_delta_for_selected_skill(self) -> None:
        rows = [
            row("sql", "SQL", level=1, required=4),
            row("python", "Python", level=2, required=4),
        ]

        result = simulate_job_gap(rows, "sql", 3)

        self.assertEqual(result["before_match_percentage"], 37.5)
        self.assertEqual(result["after_match_percentage"], 62.5)
        self.assertEqual(result["change_percentage_points"], 25.0)


if __name__ == "__main__":
    unittest.main()
