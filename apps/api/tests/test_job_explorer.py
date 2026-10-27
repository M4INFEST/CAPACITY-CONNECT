import unittest

from pydantic import ValidationError

from app.schemas.job_explorer import ExternalApplicationReport, JobAlertRequest
from app.services.job_explorer import score_job_match, summarize_response_time


class JobExplorerScoringTests(unittest.TestCase):
    def test_job_match_is_weighted_and_groups_at_spec_thresholds(self) -> None:
        requirements = [
            {
                "competency_id": "sql",
                "skill_name": "SQL",
                "required_level": 4,
                "current_level": 4,
                "importance": 0.7,
            },
            {
                "competency_id": "python",
                "skill_name": "Python",
                "required_level": 4,
                "current_level": 2,
                "importance": 0.3,
            },
        ]

        result = score_job_match(requirements)

        self.assertEqual(result["match_percentage"], 85.0)
        self.assertEqual(result["recommendation_group"], "apply_now")
        self.assertEqual([item["skill_name"] for item in result["covered_skills"]], ["SQL"])
        self.assertEqual([item["skill_name"] for item in result["skill_gaps"]], ["Python"])

    def test_match_group_boundaries_are_inclusive_and_explicit(self) -> None:
        def one_skill(level: int) -> dict[str, object]:
            return score_job_match(
                [
                    {
                        "competency_id": "skill",
                        "skill_name": "Skill",
                        "required_level": 5,
                        "current_level": level,
                        "importance": 1.0,
                    }
                ]
            )

        self.assertEqual(one_skill(4)["recommendation_group"], "apply_now")
        self.assertEqual(one_skill(3)["recommendation_group"], "almost_there")
        self.assertEqual(one_skill(2)["recommendation_group"], "learn_first")

    def test_current_skill_level_is_capped_at_the_requirement(self) -> None:
        result = score_job_match(
            [
                {
                    "competency_id": "skill",
                    "skill_name": "Skill",
                    "required_level": 3,
                    "current_level": 5,
                    "importance": 1.0,
                }
            ]
        )

        self.assertEqual(result["match_percentage"], 100.0)
        self.assertEqual(result["covered_skills"][0]["current_level"], 3)

    def test_no_requirements_gives_zero_match_and_learn_first(self) -> None:
        result = score_job_match([])

        self.assertEqual(result["match_percentage"], 0.0)
        self.assertEqual(result["recommendation_group"], "learn_first")


class JobExplorerValidationTests(unittest.TestCase):
    def test_alert_requires_at_least_one_filter(self) -> None:
        with self.assertRaises(ValidationError):
            JobAlertRequest()

        alert = JobAlertRequest(location="  Bengaluru  ")
        self.assertEqual(alert.location, "Bengaluru")

    def test_external_application_report_requires_secure_url(self) -> None:
        with self.assertRaises(ValidationError):
            ExternalApplicationReport(
                applied_externally=True,
                external_url="http://example.org/apply",
            )

        report = ExternalApplicationReport(
            applied_externally=True,
            external_url="https://example.org/apply",
        )
        self.assertTrue(report.applied_externally)

    def test_responsiveness_is_hidden_below_three_observations(self) -> None:
        self.assertEqual(
            summarize_response_time(12.5, 2)["status"],
            "not_enough_data",
        )
        self.assertEqual(
            summarize_response_time(12.5, 3)["median_hours"],
            12.5,
        )


if __name__ == "__main__":
    unittest.main()
