import unittest

from fastapi import HTTPException

from app.api.v1.learning import _checkpoint_question
from app.schemas.courses import (
    CheckpointAnswerRequest,
    CourseEnrollmentRequest,
    LearningSubmissionRequest,
)


class LearningDeliverySchemaTests(unittest.TestCase):
    def test_sponsorship_code_is_normalized(self) -> None:
        request = CourseEnrollmentRequest(sponsorship_code="  team-AB12  ")
        self.assertEqual(request.sponsorship_code, "TEAM-AB12")

    def test_checkpoint_accepts_scalar_and_multi_select_answers(self) -> None:
        self.assertEqual(CheckpointAnswerRequest(answer=2).answer, 2)
        self.assertEqual(
            CheckpointAnswerRequest(answer=["a", "b"]).answer,
            ["a", "b"],
        )

    def test_submission_requires_a_link_or_written_content(self) -> None:
        with self.assertRaises(ValueError):
            LearningSubmissionRequest(submission_type="project", title="Demo")
        submission = LearningSubmissionRequest(
            submission_type="project",
            title="Demo",
            submission_text="My project notes",
        )
        self.assertEqual(submission.submission_text, "My project notes")


class CheckpointSafetyTests(unittest.TestCase):
    def test_answer_key_and_explanation_are_not_returned_to_learner(self) -> None:
        public_question, answer_key = _checkpoint_question(
            {
                "prompt": "Choose a value",
                "options": ["one", "two"],
                "answer_key": "two",
                "explanation": "The second option is right",
            }
        )
        self.assertEqual(answer_key, "two")
        self.assertEqual(public_question, {"prompt": "Choose a value", "options": ["one", "two"]})

    def test_unconfigured_checkpoint_is_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            _checkpoint_question({"prompt": "No correct answer"})


if __name__ == "__main__":
    unittest.main()
