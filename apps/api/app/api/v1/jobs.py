from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from app.api.v1.auth import require_role
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.schemas.job_explorer import (
    ExternalApplicationReport,
    InterviewEvaluationRequest,
    JobAlertRequest,
)
from app.services.interview_coach import (
    evaluate_interview_answer_with_star,
    generate_interview_questions_for_job,
)
from app.services.job_explorer import (
    MINIMUM_RESPONSE_SAMPLE,
    score_job_match,
    summarize_response_time,
)

router = APIRouter(prefix="/api/v1", tags=["Job explorer"])



def _job_rows(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    *,
    search: str | None,
    location: str | None,
    job_type: str | None,
    experience_min: float | None,
    experience_max: float | None,
    salary_min_cents: int | None,
    competency_ids: list[UUID],
    saved_only: bool,
    job_id: UUID | None = None,
) -> list[dict[str, Any]]:
    return cursor.execute(
        """
        SELECT j.id, j.employer_id, j.role_id, j.title, j.description,
               j.source_name, j.source_url, j.source_observed_at,
               j.location, j.job_type, j.experience_min_years, j.experience_max_years,
               j.salary_min_cents, j.salary_max_cents, j.salary_currency,
               j.external_apply_url, j.created_at,
               ep.company_name, ep.website AS company_website, ep.industry AS company_industry,
               COALESCE(saved.saved, false) AS saved,
               COALESCE(requirements.skills, '[]'::jsonb) AS requirements,
               response.median_hours, response.response_count
        FROM jobs j
        LEFT JOIN employer_profiles ep ON ep.user_id = j.employer_id
        LEFT JOIN LATERAL (
          SELECT true AS saved FROM learner_saved_jobs s
          WHERE s.learner_id = %s AND s.job_id = j.id
        ) saved ON true
        LEFT JOIN LATERAL (
          SELECT jsonb_agg(
            jsonb_build_object(
              'competency_id', skills.competency_id,
              'skill_name', skills.skill_name,
              'required_level', skills.required_level,
              'importance', skills.importance,
              'current_level', skills.current_level
            ) ORDER BY skills.importance DESC, skills.skill_name
          ) AS skills
          FROM (
            SELECT c.id AS competency_id, c.canonical_name AS skill_name,
                   jr.required_level, jr.importance,
                   COALESCE(lc.level, 0) AS current_level
            FROM job_required_competencies jr
            JOIN competencies c ON c.id = jr.competency_id AND c.active
            LEFT JOIN learner_competencies lc
              ON lc.user_id = %s AND lc.competency_id = c.id
            WHERE jr.job_id = j.id
            UNION ALL
            SELECT c.id AS competency_id, c.canonical_name AS skill_name,
                   rc.required_level, rc.importance,
                   COALESCE(lc.level, 0) AS current_level
            FROM role_competencies rc
            JOIN competencies c ON c.id = rc.competency_id AND c.active
            LEFT JOIN learner_competencies lc
              ON lc.user_id = %s AND lc.competency_id = c.id
            WHERE rc.role_id = j.role_id
              AND NOT EXISTS (
                SELECT 1 FROM job_required_competencies jr
                WHERE jr.job_id = j.id
              )
          ) skills
        ) requirements ON true
        LEFT JOIN LATERAL (
          SELECT percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY extract(epoch FROM (a.last_employer_activity_at - a.applied_at)) / 3600
                 ) AS median_hours,
                 count(*)::integer AS response_count
          FROM applications a
          WHERE a.job_id = j.id
            AND a.last_employer_activity_at IS NOT NULL
            AND a.last_employer_activity_at >= a.applied_at
            AND a.status IN ('heard_back', 'interview', 'offer', 'rejected')
        ) response ON true
        WHERE j.active = true
          AND (%s::uuid IS NULL OR j.id = %s)
          AND (
            %s IS NULL OR
            j.title ILIKE %s OR
            COALESCE(j.description, '') ILIKE %s OR
            COALESCE(ep.company_name, '') ILIKE %s
          )
          AND (%s IS NULL OR COALESCE(j.location, '') ILIKE %s)
          AND (%s IS NULL OR j.job_type = %s)
          AND (%s::numeric IS NULL OR j.experience_max_years IS NULL OR j.experience_max_years >= %s)
          AND (%s::numeric IS NULL OR j.experience_min_years IS NULL OR j.experience_min_years <= %s)
          AND (%s::bigint IS NULL OR j.salary_max_cents IS NULL OR j.salary_max_cents >= %s)
          AND (
            cardinality(%s::uuid[]) = 0 OR EXISTS (
              SELECT 1 FROM job_required_competencies jr_filter
              WHERE jr_filter.job_id = j.id
                AND jr_filter.competency_id = ANY(%s)
            )
          )
          AND (NOT %s OR EXISTS (
            SELECT 1 FROM learner_saved_jobs s
            WHERE s.learner_id = %s AND s.job_id = j.id
          ))
        ORDER BY j.created_at DESC, j.id
        LIMIT 200
        """,
        (
            learner_id,
            learner_id,
            learner_id,
            job_id,
            job_id,
            search,
            f"%{search}%" if search else None,
            f"%{search}%" if search else None,
            f"%{search}%" if search else None,
            location,
            f"%{location}%" if location else None,
            job_type,
            job_type,
            experience_min,
            experience_min,
            experience_max,
            experience_max,
            salary_min_cents,
            salary_min_cents,
            competency_ids,
            competency_ids,
            saved_only,
            learner_id,
        ),
    ).fetchall()


def _serialize_job(row: dict[str, Any]) -> dict[str, Any]:
    requirements = row["requirements"] or []
    match = score_job_match(requirements)
    response = summarize_response_time(
        float(row["median_hours"]) if row["median_hours"] is not None else None,
        int(row["response_count"] or 0),
    )
    return {
        "job_id": str(row["id"]),
        "title": row["title"],
        "description": row["description"],
        "role_id": str(row["role_id"]) if row["role_id"] else None,
        "company": {
            "name": row["company_name"] or "Platform employer",
            "website": row["company_website"],
            "industry": row["company_industry"],
        },
        "location": row["location"],
        "job_type": row["job_type"],
        "experience_min_years": float(row["experience_min_years"])
        if row["experience_min_years"] is not None
        else None,
        "experience_max_years": float(row["experience_max_years"])
        if row["experience_max_years"] is not None
        else None,
        "salary_min_cents": row["salary_min_cents"],
        "salary_max_cents": row["salary_max_cents"],
        "salary_currency": row["salary_currency"],
        "external_apply_url": row["external_apply_url"],
        "created_at": row["created_at"].isoformat(),
        "source": {
            "name": row["source_name"],
            "url": row["source_url"],
            "observed_at": row["source_observed_at"].isoformat()
            if row["source_observed_at"]
            else None,
        },
        "saved": bool(row["saved"]),
        "required_skills": requirements,
        "match": match,
        "employer_responsiveness": response,
        "responsiveness_note": (
            "Median time to a recorded employer response."
            if response["status"] == "available"
            else f"Shown after at least {MINIMUM_RESPONSE_SAMPLE} recorded employer responses."
        ),
    }


@router.get("/jobs")
def list_jobs(
    q: str | None = Query(default=None, max_length=200),
    location: str | None = Query(default=None, max_length=200),
    job_type: Literal["full_time", "part_time", "contract", "internship"] | None = None,
    experience_min: float | None = Query(default=None, ge=0, le=60),
    experience_max: float | None = Query(default=None, ge=0, le=60),
    salary_min_cents: int | None = Query(default=None, ge=0),
    competency_ids: list[UUID] = Query(default=[]),
    saved_only: bool = False,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    if (
        experience_min is not None
        and experience_max is not None
        and experience_min > experience_max
    ):
        raise HTTPException(status_code=422, detail="Minimum experience cannot exceed maximum.")
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = _job_rows(
            cursor,
            UUID(user.id),
            search=q.strip() if q else None,
            location=location.strip() if location else None,
            job_type=job_type,
            experience_min=experience_min,
            experience_max=experience_max,
            salary_min_cents=salary_min_cents,
            competency_ids=competency_ids,
            saved_only=saved_only,
        )
    jobs = [_serialize_job(dict(row)) for row in rows]
    jobs.sort(
        key=lambda job: (
            {"apply_now": 0, "almost_there": 1, "learn_first": 2}[
                job["match"]["recommendation_group"]
            ],
            -job["match"]["match_percentage"],
            job["title"].casefold(),
        )
    )
    return {
        "jobs": jobs,
        "counts": {
            group: sum(job["match"]["recommendation_group"] == group for job in jobs)
            for group in ("apply_now", "almost_there", "learn_first")
        },
        "result_limit": 200,
    }


@router.get("/jobs/saved")
def list_saved_jobs(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = _job_rows(
            cursor,
            UUID(user.id),
            search=None,
            location=None,
            job_type=None,
            experience_min=None,
            experience_max=None,
            salary_min_cents=None,
            competency_ids=[],
            saved_only=True,
        )
    return {"jobs": [_serialize_job(dict(row)) for row in rows]}


@router.get("/jobs/{job_id:uuid}")
def get_job_detail(
    job_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = _job_rows(
            cursor,
            UUID(user.id),
            search=None,
            location=None,
            job_type=None,
            experience_min=None,
            experience_max=None,
            salary_min_cents=None,
            competency_ids=[],
            saved_only=False,
            job_id=job_id,
        )
    if not rows:
        raise HTTPException(status_code=404, detail="Active job not found.")
    return {"job": _serialize_job(dict(rows[0]))}


@router.put("/jobs/{job_id:uuid}/saved")
def save_job(
    job_id: UUID,
    saved: bool = Query(...),
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        active = cursor.execute(
            "SELECT 1 FROM jobs WHERE id = %s AND active",
            (job_id,),
        ).fetchone()
        if not active:
            raise HTTPException(status_code=404, detail="Active job not found.")
        if saved:
            cursor.execute(
                """
                INSERT INTO learner_saved_jobs (learner_id, job_id)
                VALUES (%s, %s) ON CONFLICT DO NOTHING
                """,
                (learner_id, job_id),
            )
        else:
            cursor.execute(
                "DELETE FROM learner_saved_jobs WHERE learner_id = %s AND job_id = %s",
                (learner_id, job_id),
            )
    return {"job_id": str(job_id), "saved": saved}


@router.get("/jobs/alerts")
def list_job_alerts(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT a.id, a.role_id, r.name AS role_name, a.location, a.job_type,
                   a.min_salary_cents, a.competency_ids, a.enabled, a.updated_at
            FROM learner_job_alerts a
            LEFT JOIN role_catalog r ON r.id = a.role_id
            WHERE a.learner_id = %s
            ORDER BY a.updated_at DESC
            """,
            (UUID(user.id),),
        ).fetchall()
    return {
        "alerts": [
            {
                **row,
                "id": str(row["id"]),
                "role_id": str(row["role_id"]) if row["role_id"] else None,
                "competency_ids": [str(item) for item in row["competency_ids"]],
                "updated_at": row["updated_at"].isoformat(),
            }
            for row in rows
        ],
        "delivery_configured": False,
    }


@router.get("/jobs/skills")
def list_job_filter_skills(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT id, canonical_name
            FROM competencies
            WHERE active
            ORDER BY canonical_name
            """
        ).fetchall()
    return {
        "skills": [
            {"competency_id": str(row["id"]), "skill_name": row["canonical_name"]}
            for row in rows
        ]
    }


@router.post("/jobs/alerts", status_code=201)
def create_job_alert(
    payload: JobAlertRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        if payload.role_id and not cursor.execute(
            "SELECT 1 FROM role_catalog WHERE id = %s AND active",
            (payload.role_id,),
        ).fetchone():
            raise HTTPException(status_code=422, detail="Select an active role.")
        if payload.competency_ids:
            valid_count = cursor.execute(
                "SELECT count(*) AS count FROM competencies WHERE id = ANY(%s) AND active",
                (payload.competency_ids,),
            ).fetchone()["count"]
            if valid_count != len(set(payload.competency_ids)):
                raise HTTPException(status_code=422, detail="One or more selected skills are inactive.")
        alert = cursor.execute(
            """
            INSERT INTO learner_job_alerts
              (learner_id, role_id, location, job_type, min_salary_cents,
               competency_ids, enabled)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, enabled
            """,
            (
                learner_id,
                payload.role_id,
                payload.location,
                payload.job_type,
                payload.min_salary_cents,
                payload.competency_ids,
                payload.enabled,
            ),
        ).fetchone()
    return {
        "id": str(alert["id"]),
        "enabled": alert["enabled"],
        "delivery_configured": False,
        "message": "Alert preference saved. Email delivery is not configured.",
    }


@router.delete("/jobs/alerts/{alert_id:uuid}")
def delete_job_alert(
    alert_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        deleted = cursor.execute(
            "DELETE FROM learner_job_alerts WHERE id = %s AND learner_id = %s RETURNING id",
            (alert_id, UUID(user.id)),
        ).fetchone()
    if not deleted:
        raise HTTPException(status_code=404, detail="Job alert not found.")
    return {"id": str(alert_id), "status": "deleted"}


@router.post("/jobs/{job_id:uuid}/external-application-report", status_code=201)
def report_external_application(
    job_id: UUID,
    payload: ExternalApplicationReport,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    if not payload.applied_externally:
        raise HTTPException(status_code=422, detail="Confirm that you applied before reporting.")
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        job = cursor.execute(
            """
            SELECT external_apply_url FROM jobs
            WHERE id = %s AND active
            """,
            (job_id,),
        ).fetchone()
        if not job or not job["external_apply_url"]:
            raise HTTPException(status_code=404, detail="Active external-apply job not found.")
        if str(payload.external_url).rstrip("/") != str(job["external_apply_url"]).rstrip("/"):
            raise HTTPException(
                status_code=422,
                detail="Reported URL must match this job's configured external application link.",
            )
        report = cursor.execute(
            """
            INSERT INTO external_job_application_reports (learner_id, job_id)
            VALUES (%s, %s)
            ON CONFLICT (learner_id, job_id)
            DO UPDATE SET reported_at = now()
            RETURNING id, reported_at
            """,
            (learner_id, job_id),
        ).fetchone()
    return {
        "report_id": str(report["id"]),
        "reported_at": report["reported_at"].isoformat(),
        "status": "self_reported",
    }


@router.get("/jobs/{job_id:uuid}/interview-prep")
def get_job_interview_prep(
    job_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        job = cursor.execute(
            """
            SELECT j.id, j.title, j.description, ep.company_name
            FROM jobs j
            LEFT JOIN employer_profiles ep ON ep.user_id = j.employer_id
            WHERE j.id = %s AND j.active
            """,
            (job_id,),
        ).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")

        # Fetch required competencies for job
        skills = cursor.execute(
            """
            SELECT c.canonical_name AS skill_name
            FROM job_required_competencies jr
            JOIN competencies c ON c.id = jr.competency_id AND c.active
            WHERE jr.job_id = %s
            ORDER BY jr.importance DESC
            LIMIT 6
            """,
            (job_id,),
        ).fetchall()
        
    skill_names = [s["skill_name"] for s in skills]
    questions = generate_interview_questions_for_job(
        job_title=job["title"],
        company_name=job["company_name"] or "Company",
        job_description=job["description"] or "",
        required_skills=skill_names,
    )
    return {
        "job_id": str(job_id),
        "job_title": job["title"],
        "company_name": job["company_name"] or "Company",
        "questions": questions,
    }


@router.post("/jobs/{job_id:uuid}/interview-evaluate")
def evaluate_job_interview_answer(
    job_id: UUID,
    payload: InterviewEvaluationRequest,
    user: UserResponse = Depends(require_role("trainee")),
) -> dict[str, Any]:
    feedback = evaluate_interview_answer_with_star(
        question=payload.question,
        user_answer=payload.user_answer,
        required_skill=payload.required_skill,
    )
    return {
        "job_id": str(job_id),
        "evaluation": feedback,
    }


@router.post("/jobs/sync-live")
def trigger_live_jobs_sync(
    limit: int = Query(default=15, ge=1, le=50),
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    """Triggers live ingestion of real job postings from Remotive & Arbeitnow into the database."""
    from app.services.live_integrations import sync_live_jobs_into_db
    return sync_live_jobs_into_db(connection, limit=limit)


@router.post("/jobs/webhook")
def receive_job_posting_webhook(
    payload: dict[str, Any],
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    """Receives webhook updates from job posting applications and persists them directly into PostgreSQL."""
    title = payload.get("title", "").strip()
    source_url = payload.get("source_url") or payload.get("url")
    description = payload.get("description", "")
    location = payload.get("location", "Remote")
    job_type = payload.get("job_type", "full_time")
    source_name = payload.get("source_name") or "Partner Webhook"
    salary_min = payload.get("salary_min_cents")
    salary_max = payload.get("salary_max_cents")

    if not title or not source_url:
        raise HTTPException(status_code=422, detail="Webhook payload must provide 'title' and 'source_url'")

    with connection.cursor(row_factory=dict_row) as cursor:
        existing = cursor.execute("SELECT id FROM jobs WHERE source_url = %s", (source_url,)).fetchone()
        if existing:
            cursor.execute(
                """
                UPDATE jobs
                SET title = %s, description = %s, location = %s, job_type = %s,
                    salary_min_cents = COALESCE(%s, salary_min_cents),
                    salary_max_cents = COALESCE(%s, salary_max_cents),
                    source_observed_at = now()
                WHERE id = %s
                """,
                (title, description, location, job_type, salary_min, salary_max, existing["id"]),
            )
            job_id = existing["id"]
            action = "updated"
        else:
            inserted = cursor.execute(
                """
                INSERT INTO jobs (
                    title, description, source_name, source_url, source_observed_at,
                    location, job_type, salary_min_cents, salary_max_cents, active
                )
                VALUES (%s, %s, %s, %s, now(), %s, %s, %s, %s, true)
                RETURNING id
                """,
                (title, description, source_name, source_url, location, job_type, salary_min, salary_max),
            ).fetchone()
            job_id = inserted["id"]
            action = "created"

        connection.commit()

    return {"status": "success", "action": action, "job_id": str(job_id)}

