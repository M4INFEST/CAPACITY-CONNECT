import unittest

from app.api.v1.assessments import _answer_matches
from app.schemas.assessments import (
    AssessmentCreateRequest,
    AssessmentQuestionRequest,
    AssessmentResponseRequest,
)
from app.services.assessments import (
    estimate_level_range,
    expected_score,
    level_for_rating,
    should_stop_early,
    update_elo,
    update_uncertainty,
)


class EloAssessmentTests(unittest.TestCase):
    def test_expected_score_is_symmetric_at_equal_rating(self) -> None:
        self.assertEqual(expected_score(1000, 1000), 0.5)

    def test_correct_and_incorrect_responses_move_rating_in_opposite_directions(self) -> None:
        correct_player, easier_question = update_elo(1000, 1000, True)
        wrong_player, harder_question = update_elo(1000, 1000, False)
        self.assertGreater(correct_player, 1000)
        self.assertLess(easier_question, 1000)
        self.assertLess(wrong_player, 1000)
        self.assertGreater(harder_question, 1000)

    def test_level_estimate_is_a_range_and_confidence_depends_on_evidence(self) -> None:
        early = estimate_level_range(1100, 350, 2)
        settled = estimate_level_range(1050, 40, 10)
        self.assertLessEqual(early["level_min"], early["level_max"])
        self.assertEqual(early["confidence"], "low")
        self.assertEqual(settled["level_min"], settled["level_max"])
        self.assertEqual(settled["confidence"], "high")

    def test_rating_maps_to_five_levels(self) -> None:
        self.assertEqual([level_for_rating(x) for x in (700, 850, 1000, 1200, 1400)], [1, 2, 3, 4, 5])

    def test_adaptive_attempt_can_stop_when_minimum_and_confidence_are_met(self) -> None:
        self.assertTrue(should_stop_early(6, 5, 3, 4))
        self.assertFalse(should_stop_early(4, 5, 3, 3))
        self.assertFalse(should_stop_early(6, 5, 2, 4))

    def test_confidence_rating_changes_uncertainty_transparently(self) -> None:
        self.assertLess(update_uncertainty(300, True, 5), 300)
        self.assertGreater(update_uncertainty(300, False, 5), 300)


class AssessmentRequestValidationTests(unittest.TestCase):
    def test_assessment_question_counts_must_be_consistent(self) -> None:
        with self.assertRaises(ValueError):
            AssessmentCreateRequest(
                course_version_id="00000000-0000-0000-0000-000000000001",
                title="Course assessment",
                min_questions=7,
                max_questions=5,
            )

    def test_choice_question_requires_options(self) -> None:
        with self.assertRaises(ValueError):
            AssessmentQuestionRequest(
                competency_id="00000000-0000-0000-0000-000000000001",
                question_type="multiple_choice",
                prompt="What does this function return?",
                answer_key="1",
                difficulty_level=2,
            )

    def test_dont_know_can_be_finalized_without_an_answer(self) -> None:
        request = AssessmentResponseRequest(
            dont_know=True,
            learner_confidence=1,
            finalize=True,
        )
        self.assertIsNone(request.answer)

    def test_multiple_choice_answer_key_must_match_an_option(self) -> None:
        with self.assertRaises(ValueError):
            AssessmentQuestionRequest(
                competency_id="00000000-0000-0000-0000-000000000001",
                question_type="multiple_choice",
                prompt="Which value is returned?",
                options=["one", "two"],
                answer_key="three",
                difficulty_level=2,
            )


class AnswerMatchingTests(unittest.TestCase):
    def test_multi_select_is_order_independent(self) -> None:
        self.assertTrue(
            _answer_matches(["two", "one"], ["one", "two"], "multi_select")
        )

    def test_text_answers_ignore_case_and_extra_whitespace(self) -> None:
        self.assertTrue(
            _answer_matches("  SELECT   * FROM users ", "select * from users", "short_answer")
        )

    def test_choice_answers_keep_json_value_types(self) -> None:
        self.assertFalse(_answer_matches("1", 1, "multiple_choice"))
        self.assertFalse(_answer_matches(True, 1, "multiple_choice"))


if __name__ == "__main__":
    unittest.main()
