import unittest

from app.services.role_matching import score_role_matches


def competency(
    role_id: str,
    role_name: str,
    competency_id: str,
    skill_name: str,
    *,
    current: int,
    required: int,
    importance: float = 1.0,
    demand_score: float | None = None,
    sample_size: int | None = None,
) -> dict[str, object]:
    return {
        "role_id": role_id,
        "role_name": role_name,
        "description": f"{role_name} role",
        "competency_id": competency_id,
        "skill_name": skill_name,
        "current_level": current,
        "required_level": required,
        "importance": importance,
        "demand_score": demand_score,
        "sample_size": sample_size,
        "source_name": "Public skills dataset" if sample_size else None,
        "source_url": "https://example.org/data" if sample_size else None,
        "observed_at": "2026-10-01T00:00:00+00:00" if sample_size else None,
        "provenance": {"source_type": "open_dataset"} if sample_size else {},
    }


class RoleMatchingTests(unittest.TestCase):
    def test_scores_are_importance_weighted_and_explained(self) -> None:
        matches = score_role_matches(
            [
                competency("r1", "Analyst", "sql", "SQL", current=4, required=4, importance=0.9),
                competency("r1", "Analyst", "python", "Python", current=1, required=4, importance=0.1),
                competency("r2", "Engineer", "sql", "SQL", current=1, required=4, importance=0.1),
                competency("r2", "Engineer", "python", "Python", current=4, required=4, importance=0.9),
            ]
        )

        self.assertEqual([match["role_name"] for match in matches], ["Analyst", "Engineer"])
        self.assertEqual(matches[0]["fit_score"], 92.5)
        self.assertIn("formula", matches[0]["explanation"])
        self.assertEqual(matches[0]["explanation"]["scoring_version"], "weighted-v1")

    def test_low_sample_demand_is_not_used_to_change_score(self) -> None:
        without_data = score_role_matches(
            [competency("r1", "Analyst", "sql", "SQL", current=2, required=4)]
        )[0]
        low_sample = score_role_matches(
            [
                competency(
                    "r1",
                    "Analyst",
                    "sql",
                    "SQL",
                    current=2,
                    required=4,
                    demand_score=1,
                    sample_size=9,
                )
            ]
        )[0]

        self.assertEqual(without_data["fit_score"], low_sample["fit_score"])
        self.assertEqual(
            low_sample["competencies"][0]["demand"]["status"],
            "not_enough_data",
        )

    def test_reliable_demand_adjustment_is_bounded_and_can_change_rank(self) -> None:
        high_demand_gap = score_role_matches(
            [
                competency(
                    "r1", "Role A", "gap", "Gap", current=0, required=1,
                    sample_size=20, demand_score=1,
                ),
                competency(
                    "r1", "Role A", "strong", "Strong", current=1, required=1,
                    sample_size=20, demand_score=0,
                ),
            ]
        )[0]
        high_demand_strength = score_role_matches(
            [
                competency(
                    "r1", "Role B", "gap", "Gap", current=0, required=1,
                    sample_size=20, demand_score=0,
                ),
                competency(
                    "r1", "Role B", "strong", "Strong", current=1, required=1,
                    sample_size=20, demand_score=1,
                ),
            ]
        )[0]

        self.assertLess(high_demand_gap["fit_score"], high_demand_strength["fit_score"])
        self.assertLessEqual(
            high_demand_strength["fit_score"] - high_demand_gap["fit_score"],
            5.0,
        )

    def test_demand_multiplier_is_bounded_and_provenance_retained(self) -> None:
        match = score_role_matches(
            [
                competency(
                    "r1",
                    "Analyst",
                    "sql",
                    "SQL",
                    current=2,
                    required=4,
                    demand_score=2,
                    sample_size=20,
                )
            ]
        )[0]

        self.assertEqual(match["fit_score"], 50.0)
        self.assertEqual(match["explanation"]["average_demand_score"], 1.0)
        self.assertEqual(
            match["explanation"]["demand_sources"][0]["source_name"],
            "Public skills dataset",
        )

    def test_adjacent_roles_use_shared_competency_similarity(self) -> None:
        matches = score_role_matches(
            [
                competency("r1", "Analyst", "sql", "SQL", current=3, required=4),
                competency("r1", "Analyst", "python", "Python", current=3, required=4),
                competency("r2", "Engineer", "sql", "SQL", current=3, required=4),
                competency("r2", "Engineer", "python", "Python", current=3, required=4),
                competency("r3", "Designer", "figma", "Figma", current=3, required=4),
            ]
        )

        analyst = next(match for match in matches if match["role_name"] == "Analyst")
        self.assertEqual(analyst["adjacent_roles"][0]["role_name"], "Engineer")
        self.assertEqual(analyst["adjacent_roles"][0]["shared_skill_similarity"], 100.0)


if __name__ == "__main__":
    unittest.main()
