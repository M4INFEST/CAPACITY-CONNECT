from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row

from app.api.v1.auth import require_role
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.services.profile_progress import freshness_badge, role_readiness

router = APIRouter(prefix="/api/v1", tags=["Profile and gap updates"])

PRIORITY_ORDER = ("critical", "high", "medium", "nice_to_have")


@router.get("/passport/progress")
def get_profile_progress(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        current_roles = role_readiness(cursor, learner_id)
        history_rows = cursor.execute(
            """
            SELECT s.role_id, r.name AS role_name, s.readiness_before,
                   s.readiness_after,
                   s.readiness_after - s.readiness_before AS readiness_delta,
                   s.created_at
            FROM learner_readiness_snapshots s
            JOIN role_catalog r ON r.id = s.role_id
            WHERE s.learner_id = %s
            ORDER BY s.created_at DESC
            LIMIT 100
            """,
            (learner_id,),
        ).fetchall()
        skill_rows = cursor.execute(
            """
            SELECT lc.competency_id, c.canonical_name AS skill_name, lc.level,
                   lc.status::text AS status, lc.last_evidence_at,
                   COALESCE(c.freshness_half_life_days, 730) AS half_life_days,
                   CASE
                     WHEN lc.last_evidence_at IS NULL THEN NULL
                     ELSE GREATEST(
                       0,
                       extract(epoch FROM (now() - lc.last_evidence_at)) / 86400
                     )
                   END AS age_days,
                   EXISTS (
                     SELECT 1
                     FROM role_competencies rc
                     JOIN learner_target_roles tr ON tr.role_id = rc.role_id
                     WHERE tr.user_id = lc.user_id
                       AND rc.competency_id = lc.competency_id
                   ) AS role_required,
                   ack.acknowledged_at
            FROM learner_competencies lc
            JOIN competencies c ON c.id = lc.competency_id AND c.active
            LEFT JOIN learner_freshness_acknowledgements ack
              ON ack.learner_id = lc.user_id
             AND ack.competency_id = lc.competency_id
            WHERE lc.user_id = %s
            ORDER BY c.canonical_name
            """,
            (learner_id,),
        ).fetchall()
        latest_attempt = cursor.execute(
            """
            SELECT u.attempt_id
            FROM assessment_skill_profile_updates u
            JOIN assessment_attempts aa ON aa.id = u.attempt_id
            WHERE aa.learner_id = %s
            ORDER BY u.created_at DESC, u.attempt_id DESC
            LIMIT 1
            """,
            (learner_id,),
        ).fetchone()
        latest_changes = []
        latest_readiness = []
        if latest_attempt:
            latest_changes = cursor.execute(
                """
                SELECT u.competency_id, c.canonical_name AS skill_name,
                       u.previous_level, u.updated_level, u.evidence_quality,
                       u.score, u.average_question_difficulty, u.credential_id
                FROM assessment_skill_profile_updates u
                JOIN competencies c ON c.id = u.competency_id
                WHERE u.attempt_id = %s
                ORDER BY c.canonical_name
                """,
                (latest_attempt["attempt_id"],),
            ).fetchall()
            latest_readiness = cursor.execute(
                """
                SELECT s.role_id, r.name AS role_name, s.readiness_before,
                       s.readiness_after,
                       s.readiness_after - s.readiness_before AS readiness_delta
                FROM learner_readiness_snapshots s
                JOIN role_catalog r ON r.id = s.role_id
                WHERE s.attempt_id = %s
                ORDER BY r.name
                """,
                (latest_attempt["attempt_id"],),
            ).fetchall()

    history_by_role: dict[str, list[dict[str, Any]]] = {}
    for item in history_rows:
        history_by_role.setdefault(str(item["role_id"]), []).append(
            {
                "created_at": item["created_at"].isoformat(),
                "readiness_before": float(item["readiness_before"]),
                "readiness_after": float(item["readiness_after"]),
                "readiness_delta": float(item["readiness_delta"]),
            }
        )

    roles = []
    for role_id, role in current_roles.items():
        grouped = {priority: [] for priority in PRIORITY_ORDER}
        for gap in role["gaps"]:
            gap["competency_id"] = str(gap["competency_id"])
            grouped[gap["priority"]].append(gap)
        history = history_by_role.get(role_id, [])
        latest = history[0] if history else None
        roles.append(
            {
                "role_id": role_id,
                "role_name": role["role_name"],
                "readiness": role["readiness"],
                "readiness_trend": latest["readiness_delta"] if latest else None,
                "gap_groups": grouped,
                "history": history,
            }
        )

    skills = []
    for item in skill_rows:
        age_days = float(item["age_days"]) if item["age_days"] is not None else None
        half_life = int(item["half_life_days"])
        freshness = freshness_badge(age_days, half_life)
        acknowledged_at = item["acknowledged_at"]
        evidence_at = item["last_evidence_at"]
        acknowledged_since_evidence = (
            acknowledged_at is not None
            and evidence_at is not None
            and acknowledged_at >= evidence_at
        )
        role_required = bool(item["role_required"])
        skills.append(
            {
                "competency_id": str(item["competency_id"]),
                "skill_name": item["skill_name"],
                "level": item["level"],
                "status": item["status"],
                "last_evidence_at": evidence_at.isoformat() if evidence_at else None,
                "freshness": freshness,
                "half_life_days": half_life,
                "role_required": role_required,
                "suggest_refresher": (
                    role_required
                    and freshness != "current"
                    and not acknowledged_since_evidence
                ),
            }
        )

    return {
        "roles": roles,
        "skills": skills,
        "latest_update": {
            "attempt_id": str(latest_attempt["attempt_id"]) if latest_attempt else None,
            "readiness_by_role": [
                {
                    "role_id": str(item["role_id"]),
                    "role_name": item["role_name"],
                    "readiness_before": float(item["readiness_before"]),
                    "readiness_after": float(item["readiness_after"]),
                    "readiness_delta": float(item["readiness_delta"]),
                }
                for item in latest_readiness
            ],
            "skill_changes": [
                {
                    "competency_id": str(item["competency_id"]),
                    "skill_name": item["skill_name"],
                    "previous_level": item["previous_level"],
                    "updated_level": item["updated_level"],
                    "evidence_quality": item["evidence_quality"],
                    "score": float(item["score"]),
                    "average_question_difficulty": float(
                        item["average_question_difficulty"]
                    ),
                    "credential_id": (
                        str(item["credential_id"]) if item["credential_id"] else None
                    ),
                }
                for item in latest_changes
            ],
        },
    }


@router.post("/passport/skills/{competency_id}/freshness-acknowledgement")
def acknowledge_skill_freshness(
    competency_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        role_requirement = cursor.execute(
            """
            SELECT 1
            FROM learner_target_roles tr
            JOIN role_competencies rc ON rc.role_id = tr.role_id
            WHERE tr.user_id = %s AND rc.competency_id = %s
            LIMIT 1
            """,
            (learner_id, competency_id),
        ).fetchone()
        if not role_requirement:
            raise HTTPException(
                status_code=409,
                detail="A refresher can only be dismissed for a skill required by a target role.",
            )
        cursor.execute(
            """
            INSERT INTO learner_freshness_acknowledgements
              (learner_id, competency_id, acknowledged_at)
            VALUES (%s, %s, now())
            ON CONFLICT (learner_id, competency_id) DO UPDATE
            SET acknowledged_at = now()
            """,
            (learner_id, competency_id),
        )
    return {
        "competency_id": str(competency_id),
        "status": "acknowledged",
        "message": "Freshness is still shown separately; no skill level or evidence date was changed.",
    }
