import io
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.api.v1.auth import require_role
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.services.job_gap_analysis import build_job_gap_report, simulate_job_gap

router = APIRouter(prefix="/api/v1", tags=["Job gap analysis"])


class WhatIfRequest(BaseModel):
    role_id: UUID
    competency_id: UUID
    proposed_level: int = Field(ge=0, le=5)


class MarketObservationInput(BaseModel):
    role_id: UUID
    competency_id: UUID
    source_type: Literal[
        "open_dataset",
        "licensed_feed",
        "employer_published",
        "platform_jobs",
    ]
    source_name: str = Field(min_length=2, max_length=200)
    source_url: HttpUrl | None = None
    observed_at: datetime
    sample_size: int = Field(ge=0)
    demand_score: float | None = Field(default=None, ge=0, le=1)
    permission_confirmed: Literal[True]

    @field_validator("source_url")
    @classmethod
    def source_url_must_use_https(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and value.scheme != "https":
            raise ValueError("Market-data source URLs must use HTTPS.")
        return value

    @field_validator("observed_at")
    @classmethod
    def observation_date_must_be_current_and_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Observation dates must include a timezone.")
        if value.astimezone(timezone.utc) > datetime.now(timezone.utc):
            raise ValueError("Observation dates cannot be in the future.")
        return value


class MarketObservationBatch(BaseModel):
    observations: list[MarketObservationInput] = Field(min_length=1, max_length=500)


def _gap_rows(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    role_id: UUID | None = None,
) -> list[dict[str, Any]]:
    rows = cursor.execute(
        """
        SELECT r.id AS role_id, r.name AS role_name,
               c.id AS competency_id, c.canonical_name AS skill_name,
               rc.required_level, rc.importance,
               COALESCE(lc.level, 0) AS current_level,
               demand.source_name, demand.source_url, demand.observed_at,
               demand.sample_size, demand.demand_score, demand.provenance,
               feedback.target_level AS employer_goal_level,
               feedback.feedback_note AS employer_goal_note
        FROM learner_target_roles tr
        JOIN role_catalog r ON r.id = tr.role_id AND r.active
        JOIN role_competencies rc ON rc.role_id = r.id
        JOIN competencies c ON c.id = rc.competency_id AND c.active
        LEFT JOIN learner_competencies lc
          ON lc.user_id = tr.user_id AND lc.competency_id = c.id
        LEFT JOIN LATERAL (
          SELECT d.source_name, d.source_url, d.observed_at, d.sample_size,
                 d.demand_score, d.provenance
          FROM demand_observations d
          WHERE d.role_id = r.id AND d.competency_id = c.id
            AND d.licensed_or_open = true
          ORDER BY d.observed_at DESC, d.id DESC
          LIMIT 1
        ) demand ON true
        LEFT JOIN LATERAL (
          SELECT g.target_level, g.feedback_note
          FROM employer_feedback_goals g
          WHERE g.learner_id = tr.user_id
            AND g.role_id = r.id
            AND g.competency_id = c.id
            AND g.completed_at IS NULL
          ORDER BY g.created_at DESC
          LIMIT 1
        ) feedback ON true
        WHERE tr.user_id = %s
          AND (%s::uuid IS NULL OR r.id = %s)
        ORDER BY r.name, rc.importance DESC, c.canonical_name
        """,
        (learner_id, role_id, role_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _report_data(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    role_id: UUID | None,
) -> dict[str, Any]:
    rows = _gap_rows(cursor, learner_id, role_id)
    if role_id is not None and not rows:
        selected = cursor.execute(
            """
            SELECT 1 FROM learner_target_roles
            WHERE user_id = %s AND role_id = %s
            """,
            (learner_id, role_id),
        ).fetchone()
        if not selected:
            raise HTTPException(
                status_code=404,
                detail="Choose this role in your Skill Passport before viewing its gap report.",
            )
    return build_job_gap_report(rows)


@router.get("/jobs/gap-analysis")
def get_job_gap_analysis(
    role_id: UUID | None = Query(default=None),
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        report = _report_data(cursor, UUID(user.id), role_id)
    return report


@router.post("/jobs/gap-analysis/what-if")
def simulate_job_gap_analysis(
    payload: WhatIfRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = _gap_rows(cursor, UUID(user.id), payload.role_id)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Choose this role in your Skill Passport before simulating a skill change.",
        )
    try:
        return simulate_job_gap(
            rows,
            str(payload.competency_id),
            payload.proposed_level,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/jobs/gap-analysis/export.pdf")
def export_job_gap_analysis(
    role_id: UUID | None = Query(default=None),
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> StreamingResponse:
    with connection.cursor(row_factory=dict_row) as cursor:
        report = _report_data(cursor, UUID(user.id), role_id)
    if not report["roles"]:
        raise HTTPException(status_code=404, detail="Select a target role before exporting.")
    output = io.BytesIO()
    page = canvas.Canvas(output, pagesize=A4)
    _, height = A4
    for role_index, role in enumerate(report["roles"]):
        if role_index:
            page.showPage()
        page.setTitle(f"Job gap report - {role['role_name']}")
        page.setFont("Helvetica-Bold", 18)
        page.drawString(42, height - 48, f"Job gap report: {role['role_name']}")
        page.setFont("Helvetica", 10)
        page.drawString(
            42,
            height - 68,
            f"Passport match: {role['match_percentage']:.1f}% · "
            f"Market observations through: {role['last_observed_at'] or 'No market data'}",
        )
        y = height - 100
        for skill in role["skills"]:
            if y < 80:
                page.showPage()
                y = height - 48
            demand = skill["demand"]
            demand_text = (
                f"{demand['score'] * 100:.0f}% · {demand['source'] or 'Source unavailable'} · "
                f"{demand['observed_at'] or 'date unavailable'} · "
                f"sample {demand['sample_size'] if demand['sample_size'] is not None else 'unknown'}"
                if demand["status"] == "available"
                else (
                    "Not enough data · "
                    f"{demand['source'] or 'source unavailable'} · "
                    f"{demand['observed_at'] or 'date unavailable'} · "
                    f"sample {demand['sample_size'] if demand['sample_size'] is not None else 'unknown'}"
                )
            )
            page.setFont("Helvetica-Bold", 11)
            page.drawString(
                42,
                y,
                f"{skill['skill_name']}: level {skill['current_level']}/{skill['required_level']} "
                f"· {skill['priority']}",
            )
            y -= 16
            page.setFont("Helvetica", 9)
            page.drawString(54, y, f"Demand: {demand_text}")
            y -= 20
        page.setFont("Helvetica", 8)
        page.drawString(
            42,
            32,
            f"Market demand is shown only with at least {report['minimum_demand_sample_size']} observations.",
        )
    page.save()
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="capacity-connect-job-gaps.pdf"'},
    )


@router.post("/admin/market-demand/observations", status_code=201)
def import_market_observations(
    payload: MarketObservationBatch,
    user: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, int]:
    with connection.cursor(row_factory=dict_row) as cursor:
        for observation in payload.observations:
            valid_pair = cursor.execute(
                """
                SELECT 1
                FROM role_competencies rc
                JOIN role_catalog r ON r.id = rc.role_id AND r.active
                JOIN competencies c ON c.id = rc.competency_id AND c.active
                WHERE rc.role_id = %s AND rc.competency_id = %s
                """,
                (observation.role_id, observation.competency_id),
            ).fetchone()
            if not valid_pair:
                raise HTTPException(
                    status_code=422,
                    detail="Each observation must match an active role competency.",
                )
            cursor.execute(
                """
                INSERT INTO demand_observations
                  (role_id, competency_id, source_name, source_url, observed_at,
                   sample_size, licensed_or_open, demand_score, provenance)
                VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s)
                """,
                (
                    observation.role_id,
                    observation.competency_id,
                    observation.source_name.strip(),
                    str(observation.source_url) if observation.source_url else None,
                    observation.observed_at,
                    observation.sample_size,
                    observation.demand_score,
                    Jsonb(
                        {
                            "source_type": observation.source_type,
                            "permission_confirmed": observation.permission_confirmed,
                            "imported_by": user.id,
                        }
                    ),
                ),
            )
    return {"imported": len(payload.observations)}


class EmployerFeedbackGoalRequest(BaseModel):
    application_id: UUID
    competency_id: UUID
    target_level: int = Field(ge=1, le=5)
    feedback_note: str = Field(min_length=3, max_length=1000)


@router.post("/employer/feedback-goals", status_code=201)
def create_employer_feedback_goal(
    payload: EmployerFeedbackGoalRequest,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    if user.employer_verification_level != 2:
        raise HTTPException(
            status_code=403,
            detail="Level 2 employer verification is required to set learner feedback goals.",
        )
    with connection.cursor(row_factory=dict_row) as cursor:
        application = cursor.execute(
            """
            SELECT a.learner_id, j.role_id
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.id = %s AND j.employer_id = %s AND j.active
              AND a.status NOT IN ('likely_closed', 'rejected')
            """,
            (payload.application_id, UUID(user.id)),
        ).fetchone()
        if not application or not application["role_id"]:
            raise HTTPException(
                status_code=404,
                detail="An active application for one of your role-linked jobs is required.",
            )
        role_competency = cursor.execute(
            """
            SELECT 1 FROM role_competencies
            WHERE role_id = %s AND competency_id = %s
            """,
            (application["role_id"], payload.competency_id),
        ).fetchone()
        if not role_competency:
            raise HTTPException(
                status_code=422,
                detail="Feedback goals must refer to a competency required by this job's role.",
            )
        goal = cursor.execute(
            """
            INSERT INTO employer_feedback_goals
              (application_id, employer_id, learner_id, role_id,
               competency_id, target_level, feedback_note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                payload.application_id,
                UUID(user.id),
                application["learner_id"],
                application["role_id"],
                payload.competency_id,
                payload.target_level,
                payload.feedback_note.strip(),
            ),
        ).fetchone()
    return {"id": str(goal["id"]), "status": "active"}
