from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.api.v1.auth import require_role
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.services.role_matching import (
    MATCH_SCORING_VERSION,
    score_role_matches,
)

router = APIRouter(prefix="/api/v1", tags=["Role matching"])


class RoleMatchFeedbackRequest(BaseModel):
    feedback: Literal["not_interested", "interested"]
    reason: str | None = Field(default=None, max_length=500)


def _role_rows(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    include_not_interested: bool,
) -> list[dict[str, Any]]:
    return cursor.execute(
        """
        SELECT r.id AS role_id, r.name AS role_name, r.description,
               c.id AS competency_id, c.canonical_name AS skill_name,
               rc.required_level, rc.importance,
               COALESCE(lc.level, 0) AS current_level,
               demand.source_name, demand.source_url, demand.observed_at,
               demand.sample_size, demand.demand_score, demand.provenance
        FROM role_catalog r
        JOIN role_competencies rc ON rc.role_id = r.id
        JOIN competencies c ON c.id = rc.competency_id AND c.active
        LEFT JOIN learner_competencies lc
          ON lc.user_id = %s AND lc.competency_id = c.id
        LEFT JOIN LATERAL (
          SELECT d.source_name, d.source_url, d.observed_at, d.sample_size,
                 d.demand_score, d.provenance
          FROM demand_observations d
          WHERE d.role_id = r.id AND d.competency_id = c.id
            AND d.licensed_or_open = true
          ORDER BY d.observed_at DESC, d.id DESC
          LIMIT 1
        ) demand ON true
        WHERE r.active
          AND (%s OR NOT EXISTS (
            SELECT 1 FROM learner_role_match_feedback f
            WHERE f.learner_id = %s AND f.role_id = r.id
              AND f.feedback = 'not_interested'
          ))
        ORDER BY r.name, rc.importance DESC, c.canonical_name
        """,
        (learner_id, include_not_interested, learner_id),
    ).fetchall()


def _persist_match_run(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    matches: list[dict[str, Any]],
) -> None:
    for match in matches:
        cursor.execute(
            """
            INSERT INTO role_match_runs
              (learner_id, role_id, scoring_version, score, component_scores)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                learner_id,
                UUID(match["role_id"]),
                MATCH_SCORING_VERSION,
                match["fit_score"] / 100,
                Jsonb(
                    {
                        "method": match["explanation"]["method"],
                        "formula": match["explanation"]["formula"],
                        "market_demand_weight": match["explanation"]["market_demand_weight"],
                        "market_data_coverage": match["explanation"]["market_data_coverage"],
                        "average_demand_score": match["explanation"]["average_demand_score"],
                    }
                ),
            ),
        )


@router.post("/role-matches/refresh")
def refresh_role_matches(
    include_not_interested: bool = Query(default=False),
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = _role_rows(cursor, learner_id, include_not_interested)
        matches = score_role_matches(rows)
        _persist_match_run(cursor, learner_id, matches)
    return {
        "scoring_version": MATCH_SCORING_VERSION,
        "matches": matches,
        "model_status": "Only the transparent weighted score is active; no learned role model is integrated.",
    }


@router.get("/role-matches")
def get_role_matches(
    include_not_interested: bool = Query(default=False),
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = _role_rows(cursor, UUID(user.id), include_not_interested)
    matches = score_role_matches(rows)
    return {
        "scoring_version": MATCH_SCORING_VERSION,
        "matches": matches,
        "model_status": "Only the transparent weighted score is active; no learned role model is integrated.",
    }


@router.get("/role-matches/{role_id}")
def get_role_match_detail(
    role_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = _role_rows(cursor, UUID(user.id), True)
    matches = score_role_matches(rows)
    match = next((item for item in matches if item["role_id"] == str(role_id)), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Active role match not found.")
    return {"scoring_version": MATCH_SCORING_VERSION, "match": match}


@router.post("/role-matches/{role_id}/target", status_code=201)
def set_role_as_target(
    role_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        role = cursor.execute(
            "SELECT 1 FROM role_catalog WHERE id = %s AND active",
            (role_id,),
        ).fetchone()
        if not role:
            raise HTTPException(status_code=404, detail="Active role not found.")
        cursor.execute(
            """
            INSERT INTO learner_target_roles (user_id, role_id)
            VALUES (%s, %s)
            ON CONFLICT (user_id, role_id) DO NOTHING
            """,
            (learner_id, role_id),
        )
        cursor.execute(
            """
            INSERT INTO learner_role_match_feedback (learner_id, role_id, feedback)
            VALUES (%s, %s, 'interested')
            ON CONFLICT (learner_id, role_id)
            DO UPDATE SET feedback = 'interested', reason = NULL, updated_at = now()
            """,
            (learner_id, role_id),
        )
    return {"role_id": str(role_id), "status": "target"}


@router.post("/role-matches/{role_id}/feedback")
def set_role_match_feedback(
    role_id: UUID,
    payload: RoleMatchFeedbackRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        role = cursor.execute(
            "SELECT 1 FROM role_catalog WHERE id = %s AND active",
            (role_id,),
        ).fetchone()
        if not role:
            raise HTTPException(status_code=404, detail="Active role not found.")
        cursor.execute(
            """
            INSERT INTO learner_role_match_feedback
              (learner_id, role_id, feedback, reason)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (learner_id, role_id)
            DO UPDATE SET feedback = EXCLUDED.feedback,
                          reason = EXCLUDED.reason,
                          updated_at = now()
            """,
            (UUID(user.id), role_id, payload.feedback, payload.reason),
        )
    return {"role_id": str(role_id), "feedback": payload.feedback}
