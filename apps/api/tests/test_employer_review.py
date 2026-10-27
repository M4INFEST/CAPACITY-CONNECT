import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.schemas.employer_review import (
    CompareApplicantsRequest,
    EmployerApplicationStatusUpdate,
    EmployerJobInput,
    JobQuestionInput,
)
from app.services.employer_review import score_applicant_match
from app.api.v1.employer_review import EMPLOYER_TRANSITIONS


class EmployerReviewScoringTests(unittest.TestCase):
    def test_fit_score_is_weighted_and_labels_evidence(self) -> None:
        python_id = str(uuid4())
        sql_id = str(uuid4())
        result = score_applicant_match(
            [
                {
                    "competency_id": python_id,
                    "skill_name": "Python",
                    "required_level": 4,
                    "importance": 0.75,
                },
                {
                    "competency_id": sql_id,
                    "skill_name": "SQL",
                    "required_level": 2,
                    "importance": 0.25,
                },
            ],
            {
                "verified_skills": [
                    {"competency_id": python_id, "skill_name": "Python", "level": 4}
                ],
                "claimed_skills": [
                    {"competency_id": sql_id, "skill_name": "SQL", "level": 1}
                ],
            },
        )

        self.assertEqual(result["match_percentage"], 87.5)
        self.assertEqual(result["scoring_version"], "employer-weighted-v1")
        self.assertEqual(result["skills"][0]["evidence_status"], "verified")
        self.assertEqual(result["skills"][1]["evidence_status"], "claimed")

    def test_score_does_not_trust_levels_above_five_or_unrequested_skills(self) -> None:
        skill_id = str(uuid4())
        result = score_applicant_match(
            [
                {
                    "competency_id": skill_id,
                    "skill_name": "Kubernetes",
                    "required_level": 3,
                    "importance": 1,
                }
            ],
            {
                "verified_skills": [
                    {"competency_id": skill_id, "level": 99},
                    {"competency_id": str(uuid4()), "level": 5},
                ]
            },
        )

        self.assertEqual(result["match_percentage"], 100.0)
        self.assertEqual(result["skills"][0]["current_level"], 3)

    def test_empty_requirements_have_a_clear_zero_score(self) -> None:
        result = score_applicant_match([], {})
        self.assertEqual(result["match_percentage"], 0.0)
        self.assertIn("importance-weighted", result["explanation"])


class EmployerReviewValidationTests(unittest.TestCase):
    def test_job_rejects_invalid_salary_ranges_and_duplicate_skills(self) -> None:
        skill_id = uuid4()
        common = {
            "title": "Platform engineer",
            "description": "Build and operate reliable platform systems for customers.",
        }
        with self.assertRaises(ValidationError):
            EmployerJobInput(**common, salary_min_cents=500, salary_max_cents=100)
        with self.assertRaises(ValidationError):
            EmployerJobInput(
                **common,
                requirements=[
                    {"competency_id": skill_id, "required_level": 3},
                    {"competency_id": skill_id, "required_level": 4},
                ],
            )

    def test_questions_validate_options_and_normalize_values(self) -> None:
        question = JobQuestionInput(
            prompt="  Which cloud provider? ",
            answer_type="single_choice",
            options=[" AWS ", "Azure"],
        )
        self.assertEqual(question.prompt, "Which cloud provider?")
        self.assertEqual(question.options, ["AWS", "Azure"])
        with self.assertRaises(ValidationError):
            JobQuestionInput(prompt="Choose", answer_type="single_choice")
        with self.assertRaises(ValidationError):
            JobQuestionInput(
                prompt="Choose",
                answer_type="text",
                options=["AWS"],
            )

    def test_rejection_requires_a_neutral_reason(self) -> None:
        with self.assertRaises(ValidationError):
            EmployerApplicationStatusUpdate(status="rejected")
        rejected = EmployerApplicationStatusUpdate(
            status="rejected",
            rejection_reason="position_filled",
        )
        self.assertEqual(rejected.rejection_reason, "position_filled")

    def test_pipeline_transitions_never_move_rejected_candidates_forward(self) -> None:
        self.assertIn("shortlisted", EMPLOYER_TRANSITIONS["applied"])
        self.assertIn("offer", EMPLOYER_TRANSITIONS["interview"])
        self.assertEqual(EMPLOYER_TRANSITIONS["rejected"], set())

    def test_compare_requires_two_or_three_distinct_applications(self) -> None:
        first, second = uuid4(), uuid4()
        self.assertEqual(
            len(CompareApplicantsRequest(application_ids=[first, second]).application_ids),
            2,
        )
        with self.assertRaises(ValidationError):
            CompareApplicantsRequest(application_ids=[first, first])
        with self.assertRaises(ValidationError):
            CompareApplicantsRequest(application_ids=[first])


if __name__ == "__main__":
    unittest.main()
