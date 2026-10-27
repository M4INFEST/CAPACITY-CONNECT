from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.services.assessments import estimate_level_range, level_for_rating


def freshness_badge(age_days: float | None, half_life_days: int) -> str:
    if age_days is None:
        return "stale"
    if age_days <= half_life_days:
        return "current"
    if age_days <= half_life_days * 2:
        return "aging"
    return "stale"


def gap_priority(weighted_gap: float) -> str:
    if weighted_gap >= 1.5:
        return "critical"
    if weighted_gap >= 0.75:
        return "high"
    if weighted_gap > 0:
        return "medium"
    return "nice_to_have"


def calculate_role_progress(
    requirements: list[dict[str, Any]],
) -> tuple[float, list[dict[str, Any]]]:
    importance_total = sum(float(row["importance"]) for row in requirements)
    readiness_points = 0.0
    items: list[dict[str, Any]] = []
    for row in requirements:
        required = int(row["required_level"])
        current = int(row["current_level"])
        importance = float(row["importance"])
        readiness_points += min(current / required, 1.0) * importance
        level_gap = max(0, required - current)
        weighted_gap = level_gap * importance
        items.append(
            {
                **row,
                "current_level": current,
                "required_level": required,
                "importance": importance,
                "gap_levels": level_gap,
                "gap_score": round(weighted_gap, 4),
                "priority": gap_priority(weighted_gap),
            }
        )
    readiness = (
        round(readiness_points * 100 / importance_total, 2)
        if importance_total
        else 0.0
    )
    return readiness, items


def role_readiness(
    cursor: psycopg.Cursor, learner_id: Any
) -> dict[str, dict[str, Any]]:
    rows = cursor.execute(
        """
        SELECT r.id AS role_id, r.name AS role_name, c.id AS competency_id,
               c.canonical_name AS skill_name, rc.required_level, rc.importance,
               COALESCE(lc.level, 0) AS current_level
        FROM learner_target_roles tr
        JOIN role_catalog r ON r.id = tr.role_id AND r.active
        JOIN role_competencies rc ON rc.role_id = r.id
        JOIN competencies c ON c.id = rc.competency_id AND c.active
        LEFT JOIN learner_competencies lc
          ON lc.user_id = tr.user_id AND lc.competency_id = c.id
        WHERE tr.user_id = %s
        ORDER BY r.name, rc.importance DESC, c.canonical_name
        """,
        (learner_id,),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    names: dict[str, str] = {}
    for row in rows:
        role_id = str(row["role_id"])
        names[role_id] = row["role_name"]
        grouped.setdefault(role_id, []).append(row)
    result: dict[str, dict[str, Any]] = {}
    for role_id, requirements in grouped.items():
        readiness, gaps = calculate_role_progress(requirements)
        result[role_id] = {
            "role_id": role_id,
            "role_name": names[role_id],
            "readiness": readiness,
            "gaps": gaps,
        }
    return result


def capture_profile_baseline(
    cursor: psycopg.Cursor, learner_id: Any
) -> dict[str, Any]:
    rows = cursor.execute(
        """
        SELECT competency_id, level, status::text AS status
        FROM learner_competencies
        WHERE user_id = %s
        """,
        (learner_id,),
    ).fetchall()
    return {
        "readiness": role_readiness(cursor, learner_id),
        "skills": {
            str(row["competency_id"]): {
                "level": row["level"],
                "status": row["status"],
            }
            for row in rows
        },
    }


def update_profile_after_assessment(
    cursor: psycopg.Cursor,
    attempt: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    learner_id = attempt["learner_id"]
    before = baseline["readiness"]
    rows = cursor.execute(
        """
        SELECT aq.competency_id, comp.canonical_name AS skill_name,
               count(*) FILTER (WHERE ar.dont_know = false)::integer AS scored_count,
               count(*) FILTER (
                 WHERE ar.dont_know = false AND ar.correct IS TRUE
               )::integer AS correct_count,
               count(*) FILTER (
                 WHERE ar.dont_know = false
                   AND aq.question_type IN ('scenario', 'code_task')
               )::integer AS practical_count,
               count(*) FILTER (
                 WHERE ar.dont_know = false
                   AND aq.question_type NOT IN ('scenario', 'code_task')
               )::integer AS knowledge_count,
               avg(aq.difficulty_level) FILTER (
                 WHERE ar.dont_know = false
               )::float AS average_question_difficulty,
               COALESCE(lsr.elo_rating, 1000) AS rating,
               COALESCE(lsr.uncertainty, 350)::float AS uncertainty
        FROM assessment_responses ar
        JOIN assessment_questions aq ON aq.id = ar.question_id
        JOIN competencies comp ON comp.id = aq.competency_id
        LEFT JOIN learner_skill_ratings lsr
          ON lsr.learner_id = %s AND lsr.competency_id = aq.competency_id
        WHERE ar.attempt_id = %s AND ar.submitted
        GROUP BY aq.competency_id, comp.canonical_name,
                 lsr.elo_rating, lsr.uncertainty
        HAVING count(*) FILTER (WHERE ar.dont_know = false) > 0
        """,
        (learner_id, attempt["id"]),
    ).fetchall()

    changes: list[dict[str, Any]] = []
    for row in rows:
        rating_range = estimate_level_range(
            row["rating"], row["uncertainty"], row["scored_count"]
        )
        updated_level = level_for_rating(row["rating"])
        credential = cursor.execute(
            """
            SELECT id, evidence_id, level
            FROM credentials
            WHERE assessment_attempt_id = %s AND competency_id = %s
            """,
            (attempt["id"], row["competency_id"]),
        ).fetchone()
        previous = baseline["skills"].get(str(row["competency_id"]))
        quality = "verified" if credential else "provisional"

        if credential:
            evidence_id = credential["evidence_id"]
            if evidence_id is None:
                evidence = cursor.execute(
                    """
                    INSERT INTO evidence
                      (user_id, competency_id, source_type, verification, metadata)
                    VALUES (%s, %s, 'assessment', 'verified', %s)
                    RETURNING id
                    """,
                    (
                        learner_id,
                        row["competency_id"],
                        Jsonb({"assessment_attempt_id": str(attempt["id"])}),
                    ),
                ).fetchone()
                evidence_id = evidence["id"]
                cursor.execute(
                    "UPDATE credentials SET evidence_id = %s WHERE id = %s",
                    (evidence_id, credential["id"]),
                )
            updated_level = max(
                int(credential["level"]),
                int(previous["level"] or 0) if previous and previous["status"] == "verified" else 0,
            )
        else:
            if previous and previous["status"] == "verified":
                updated_level = int(previous["level"])
            evidence = cursor.execute(
                """
                INSERT INTO evidence
                  (user_id, competency_id, source_type, verification, metadata)
                VALUES (%s, %s, 'assessment', 'provisional', %s)
                RETURNING id
                """,
                (
                    learner_id,
                    row["competency_id"],
                    Jsonb(
                        {
                            "assessment_attempt_id": str(attempt["id"]),
                            "evidence_tier": attempt["evidence_tier"],
                            "correct_count": row["correct_count"],
                            "scored_count": row["scored_count"],
                            "average_question_difficulty": round(
                                row["average_question_difficulty"], 2
                            ),
                            "elo_level_range": rating_range,
                        }
                    ),
                ),
            ).fetchone()
            evidence_id = evidence["id"]

        if not (previous and previous["status"] == "verified" and not credential):
            cursor.execute(
                """
                INSERT INTO learner_competencies
                  (user_id, competency_id, level, status, freshness, last_evidence_at)
                VALUES (%s, %s, %s, %s::evidence_status, 'current', now())
                ON CONFLICT (user_id, competency_id) DO UPDATE
                SET level = EXCLUDED.level,
                    status = EXCLUDED.status,
                    freshness = 'current',
                    last_evidence_at = now(),
                    updated_at = now()
                """,
                (
                    learner_id,
                    row["competency_id"],
                    updated_level,
                    quality,
                ),
            )

        score = row["correct_count"] / row["scored_count"]
        cursor.execute(
            """
            INSERT INTO assessment_skill_profile_updates
              (attempt_id, competency_id, evidence_id, credential_id,
               previous_level, updated_level, evidence_quality, score,
               average_question_difficulty)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (attempt_id, competency_id) DO NOTHING
            """,
            (
                attempt["id"],
                row["competency_id"],
                evidence_id,
                credential["id"] if credential else None,
                previous["level"] if previous else None,
                updated_level,
                quality,
                score,
                row["average_question_difficulty"],
            ),
        )
        changes.append(
            {
                "competency_id": str(row["competency_id"]),
                "skill_name": row["skill_name"],
                "previous_level": previous["level"] if previous else None,
                "updated_level": updated_level,
                "evidence_quality": quality,
                "score": round(score, 4),
                "average_question_difficulty": round(
                    row["average_question_difficulty"], 2
                ),
                "level_range": rating_range,
                "credential_id": str(credential["id"]) if credential else None,
            }
        )

    after = role_readiness(cursor, learner_id)
    for role_id, role_after in after.items():
        role_before = before.get(role_id)
        cursor.execute(
            """
            INSERT INTO learner_readiness_snapshots
              (attempt_id, learner_id, role_id, readiness_before,
               readiness_after, skill_changes)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (attempt_id, role_id) DO NOTHING
            """,
            (
                attempt["id"],
                learner_id,
                role_after["role_id"],
                role_before["readiness"] if role_before else 0,
                role_after["readiness"],
                Jsonb(changes),
            ),
        )

    return {
        "readiness_before": before,
        "readiness_after": after,
        "skill_changes": changes,
    }
