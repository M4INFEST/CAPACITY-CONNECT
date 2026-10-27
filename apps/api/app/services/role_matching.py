from typing import Any

MATCH_SCORING_VERSION = "weighted-v1"
MINIMUM_DEMAND_SAMPLE = 10


def score_role_matches(
    rows: list[dict[str, Any]],
    *,
    excluded_role_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded_role_ids = excluded_role_ids or set()
    roles: dict[str, dict[str, Any]] = {}
    for row in rows:
        role_id = str(row["role_id"])
        if role_id in excluded_role_ids:
            continue
        role = roles.setdefault(
            role_id,
            {
                "role_id": role_id,
                "role_name": row["role_name"],
                "description": row.get("description"),
                "competencies": [],
                "total_weight": 0.0,
                "matched_weight": 0.0,
                "market_weight": 0.0,
                "demand_weighted_sum": 0.0,
                "latest_observation": None,
                "demand_sources": [],
            },
        )
        required = int(row["required_level"])
        current = min(required, max(0, int(row["current_level"])))
        importance = float(row["importance"])
        sample_size = (
            int(row["sample_size"])
            if row.get("sample_size") is not None
            else None
        )
        demand_score = (
            min(1.0, max(0.0, float(row["demand_score"])))
            if row.get("demand_score") is not None
            else None
        )
        observed_at = row.get("observed_at")
        provenance = row.get("provenance") or {}
        demand_available = (
            sample_size is not None
            and sample_size >= MINIMUM_DEMAND_SAMPLE
            and demand_score is not None
        )

        # Market demand can adjust importance by at most 5%; it never substitutes for skill fit.
        demand_multiplier = (
            0.95 + demand_score * 0.1 if demand_available else 1.0
        )
        effective_weight = importance * demand_multiplier
        coverage = current / required
        role["total_weight"] += effective_weight
        role["matched_weight"] += effective_weight * coverage
        if demand_available:
            role["market_weight"] += importance
            role["demand_weighted_sum"] += importance * demand_score
            if observed_at and (
                role["latest_observation"] is None
                or str(observed_at) > str(role["latest_observation"])
            ):
                role["latest_observation"] = observed_at
            role["demand_sources"].append(
                {
                    "source_name": row.get("source_name"),
                    "source_url": row.get("source_url"),
                    "observed_at": observed_at.isoformat()
                    if hasattr(observed_at, "isoformat")
                    else observed_at,
                    "sample_size": sample_size,
                    "source_type": provenance.get("source_type"),
                }
            )

        role["competencies"].append(
            {
                "competency_id": str(row["competency_id"]),
                "skill_name": row["skill_name"],
                "current_level": current,
                "required_level": required,
                "importance": importance,
                "contribution": round(effective_weight * coverage, 5),
                "gap_levels": max(0, required - current),
                "demand": {
                    "status": "available" if demand_available else "not_enough_data",
                    "score": demand_score if demand_available else None,
                    "source_name": row.get("source_name"),
                    "source_url": row.get("source_url"),
                    "observed_at": row.get("observed_at").isoformat()
                    if hasattr(row.get("observed_at"), "isoformat")
                    else row.get("observed_at"),
                    "sample_size": sample_size,
                },
            }
        )

    matches: list[dict[str, Any]] = []
    for role in roles.values():
        total_weight = role.pop("total_weight")
        matched_weight = role.pop("matched_weight")
        market_weight = role.pop("market_weight")
        demand_weighted_sum = role.pop("demand_weighted_sum")
        demand_sources = role.pop("demand_sources")
        role["fit_score"] = round(
            matched_weight / total_weight * 100 if total_weight else 0.0, 1
        )
        # Calculate SHAP-style marginal contributions for each competency (from careerflow)
        shap_waterfall = []
        for comp in role["competencies"]:
            # Baseline expected coverage contribution
            impact = comp["contribution"] / total_weight * 100 if total_weight else 0.0
            gap_penalty = (comp["gap_levels"] / comp["required_level"]) * (comp["importance"] / total_weight * 100) if total_weight and comp["required_level"] else 0.0
            shap_waterfall.append({
                "skill_name": comp["skill_name"],
                "positive_gain": round(impact, 2),
                "gap_penalty": round(gap_penalty, 2),
                "net_impact": round(impact - gap_penalty, 2),
            })
        shap_waterfall.sort(key=lambda item: -item["net_impact"])

        role["explanation"] = {
            "method": "Multi-objective competency coverage & explainable SHAP-style attribution (CareerFlow Engine).",
            "scoring_version": MATCH_SCORING_VERSION,
            "formula": (
                "sum(importance × bounded demand multiplier × skill-level coverage) "
                "/ sum(importance × bounded demand multiplier)"
            ),
            "market_demand_weight": 5,
            "market_data_coverage": round(
                market_weight
                / sum(float(skill["importance"]) for skill in role["competencies"])
                * 100,
                1,
            )
            if role["competencies"]
            else 0.0,
            "average_demand_score": round(
                demand_weighted_sum / market_weight, 3
            )
            if market_weight
            else None,
            "latest_market_observation": (
                role["latest_observation"].isoformat()
                if hasattr(role["latest_observation"], "isoformat")
                else role["latest_observation"]
            ),
            "demand_sources": demand_sources,
            "shap_waterfall": shap_waterfall[:6],
        }

        role["competencies"].sort(
            key=lambda competency: (
                competency["gap_levels"] == 0,
                -competency["importance"],
                competency["skill_name"].casefold(),
            )
        )
        role["top_contributors"] = [
            competency
            for competency in role["competencies"]
            if competency["gap_levels"] == 0
        ][:3]
        role["largest_gaps"] = [
            competency
            for competency in role["competencies"]
            if competency["gap_levels"] > 0
        ][:3]
        matches.append(role)
    matches.sort(key=lambda role: (-role["fit_score"], role["role_name"].casefold()))

    if matches:
        anchor = {
            competency["competency_id"]
            for competency in matches[0]["competencies"]
        }
        for role in matches:
            skills = {
                competency["competency_id"] for competency in role["competencies"]
            }
            role["shared_competencies_with_top_match"] = len(skills & anchor)
            role["adjacent_roles"] = []
        for role in matches:
            adjacent = []
            role_skills = {
                competency["competency_id"] for competency in role["competencies"]
            }
            for candidate in matches:
                if candidate["role_id"] == role["role_id"]:
                    continue
                candidate_skills = {
                    competency["competency_id"]
                    for competency in candidate["competencies"]
                }
                union = role_skills | candidate_skills
                overlap = len(role_skills & candidate_skills) / len(union) if union else 0.0
                adjacent.append(
                    {
                        "role_id": candidate["role_id"],
                        "role_name": candidate["role_name"],
                        "shared_skill_similarity": round(overlap * 100, 1),
                        "fit_score": candidate["fit_score"],
                    }
                )
            role["adjacent_roles"] = sorted(
                adjacent,
                key=lambda item: (
                    -item["shared_skill_similarity"],
                    -item["fit_score"],
                    item["role_name"].casefold(),
                ),
            )[:3]
    return matches
