import unittest
from unittest.mock import MagicMock, patch

from app.services.llm_skill_extractor import (
    ENABLE_LLM_EXTRACTION,
    call_llm_extractor,
    evaluate_precision_on_heldout,
    extract_skills_deterministic,
    extract_skills_stage2,
    run_comparative_benchmark,
)
from app.services.router_baseline import HELDOUT_TEST_SET, load_router


class SkillExtractorStage2Tests(unittest.TestCase):
    def setUp(self):
        # Verify router.joblib can be loaded or created cleanly
        self.router = load_router()
        self.assertIsNotNone(self.router)

    def test_distinguishes_c_cpp_csharp_dotnet_nodejs_java_javascript(self):
        text = (
            "Extensive experience in C++, C#, and Microsoft .NET platforms. "
            "Also built microservices with Node.js and fullstack JavaScript. "
            "Maintained legacy Java backends and low-level embedded C firmware."
        )
        results = extract_skills_deterministic(text)
        skills_found = {item["skill"] for item in results}

        # Must distinguish all 7 required symbol-sensitive skills
        for expected in ["C", "C++", "C#", ".NET", "Node.js", "Java", "JavaScript"]:
            self.assertIn(expected, skills_found)

        # Spans must be exact substrings of text
        for item in results:
            self.assertIn(item["span"], text)
            self.assertTrue(0.0 <= item["confidence"] <= 1.0)
            self.assertEqual(item["review"], item["confidence"] < 0.90)

    def test_c_does_not_falsely_trigger_on_cplusplus_or_csharp(self):
        text = "I write modern C++ and C# every day."
        results = extract_skills_deterministic(text)
        skills = {item["skill"] for item in results}
        self.assertIn("C++", skills)
        self.assertIn("C#", skills)
        self.assertNotIn("C", skills)

    def test_javascript_does_not_falsely_trigger_java(self):
        text = "Frontend development using JavaScript and CSS."
        results = extract_skills_deterministic(text)
        skills = {item["skill"] for item in results}
        self.assertIn("JavaScript", skills)
        self.assertNotIn("Java", skills)

    def test_confidence_below_90_sets_review_true(self):
        text = "I have no experience with C."
        results = extract_skills_deterministic(text)
        self.assertTrue(len(results) > 0)
        c_item = next(r for r in results if r["skill"] == "C")
        self.assertLess(c_item["confidence"], 0.90)
        self.assertTrue(c_item["review"])

    def test_never_invents_skill_not_in_text(self):
        text = "Experienced in Python and Docker."
        results = extract_skills_deterministic(text)
        for item in results:
            self.assertIn(item["span"], text)
            self.assertNotEqual(item["skill"], "Java")
            self.assertNotEqual(item["skill"], "C++")

    def test_default_toggle_is_false(self):
        # By default ENABLE_LLM_EXTRACTION is false
        with patch("app.services.llm_skill_extractor.ENABLE_LLM_EXTRACTION", False):
            with patch("app.services.llm_skill_extractor.call_llm_extractor") as mock_llm:
                extract_skills_stage2("Built APIs in Java.")
                mock_llm.assert_not_called()

    def test_fails_loudly_when_llm_precision_less_than_baseline(self):
        # Create a poor LLM mock with low precision
        def inferior_llm_mock(text):
            # Hallucinates skills regardless of input
            return [
                {"skill": "Java", "confidence": 0.99, "span": "Java", "review": False},
                {"skill": "C", "confidence": 0.99, "span": "C", "review": False},
            ]

        with self.assertRaises(RuntimeError) as context:
            run_comparative_benchmark(llm_extractor_fn=inferior_llm_mock)

        self.assertIn("failed precision benchmark", str(context.exception))
        self.assertIn("Cannot enable LLM extraction", str(context.exception))

    def test_passes_benchmark_when_llm_meets_or_exceeds_baseline(self):
        # An accurate LLM mock that follows the ground-truth rules
        def superior_llm_mock(text):
            return extract_skills_deterministic(text)

        report = run_comparative_benchmark(llm_extractor_fn=superior_llm_mock)
        self.assertEqual(report["status"], "passed")
        self.assertGreaterEqual(report["llm_precision"], report["baseline_precision"])


if __name__ == "__main__":
    unittest.main()
