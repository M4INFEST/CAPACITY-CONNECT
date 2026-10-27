import unittest

from pydantic import ValidationError

from app.schemas.applications import ApplicationResumeLine, ApplicationSubmission
from app.services.application_preparation import match_resume_keywords


class ApplicationPreparationTests(unittest.TestCase):
    def test_keyword_check_matches_selected_text_without_java_javascript_collision(self) -> None:
        result = match_resume_keywords(
            "Build Java and JavaScript services using SQL",
            [
                {"skill_name": "Java"},
                {"skill_name": "JavaScript"},
                {"skill_name": "SQL"},
            ],
            ["Built a JavaScript service and queried SQL databases."],
        )

        self.assertEqual(result["matched_required_skills"], ["JavaScript", "SQL"])
        self.assertEqual(result["missing_required_skills"], ["Java"])
        self.assertIn("build", result["missing_keywords"])

    def test_keyword_check_handles_symbol_skills(self) -> None:
        result = match_resume_keywords(
            "C++ C# development",
            [{"skill_name": "C++"}, {"skill_name": "C#"}],
            ["Maintained C++ and C# applications."],
        )

        self.assertEqual(set(result["matched_required_skills"]), {"C++", "C#"})

    def test_application_line_requires_explicit_learner_approval(self) -> None:
        with self.assertRaises(ValidationError):
            ApplicationResumeLine(text="Built a service")

        line = ApplicationResumeLine(text=" Built a service ", approved_by_learner=True)
        self.assertEqual(line.text, "Built a service")

    def test_application_requires_consent_and_at_least_one_line(self) -> None:
        with self.assertRaises(ValidationError):
            ApplicationSubmission(
                resume_lines=[{"text": "Built a service", "approved_by_learner": True}],
                share_profile_consent=False,
            )
        with self.assertRaises(ValidationError):
            ApplicationSubmission(
                resume_lines=[],
                share_profile_consent=True,
            )


if __name__ == "__main__":
    unittest.main()
