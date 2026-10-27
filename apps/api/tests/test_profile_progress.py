import unittest

from app.services.profile_progress import (
    calculate_role_progress,
    freshness_badge,
    gap_priority,
)


class ProfileProgressTests(unittest.TestCase):
    def test_readiness_uses_importance_and_caps_credit_at_required_level(self) -> None:
        readiness, gaps = calculate_role_progress(
            [
                {
                    "skill_name": "Python",
                    "required_level": 4,
                    "current_level": 2,
                    "importance": 0.8,
                },
                {
                    "skill_name": "Git",
                    "required_level": 2,
                    "current_level": 5,
                    "importance": 0.2,
                },
            ]
        )

        self.assertEqual(readiness, 60.0)
        self.assertEqual(gaps[0]["gap_score"], 1.6)
        self.assertEqual(gaps[0]["priority"], "critical")
        self.assertEqual(gaps[1]["priority"], "nice_to_have")

    def test_gap_groups_follow_weighted_gap_bands(self) -> None:
        self.assertEqual(gap_priority(1.5), "critical")
        self.assertEqual(gap_priority(0.75), "high")
        self.assertEqual(gap_priority(0.1), "medium")
        self.assertEqual(gap_priority(0), "nice_to_have")

    def test_freshness_is_separate_and_based_on_skill_half_life(self) -> None:
        self.assertEqual(freshness_badge(180, 365), "current")
        self.assertEqual(freshness_badge(500, 365), "aging")
        self.assertEqual(freshness_badge(800, 365), "stale")
        self.assertEqual(freshness_badge(None, 365), "stale")


if __name__ == "__main__":
    unittest.main()
