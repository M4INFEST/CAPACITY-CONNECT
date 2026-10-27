from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.v1.auth import require_role
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.schemas.employer_review import (
    CompareApplicantsRequest,
    EmployerApplicationNote,
    EmployerApplicationStatusUpdate,
    EmployerCompanyProfileUpdate,
    EmployerJobActiveUpdate,
    EmployerJobInput,
)
from app.services.employer_review import score_applicant_match

router = APIRouter(prefix="/api/v1/employer", tags=["Employer review"])
MAX_PROFILE_VIEWS_PER_24_HOURS = 50
EMPLOYER_TRANSITIONS = {
    "applied": {"shortlisted", "interview", "rejected"},
    "heard_back": {"shortlisted", "interview", "rejected"},
    "no_reply": {"shortlisted", "interview", "rejected"},
    "shortlisted": {"interview", "rejected"},
    "interview": {"offer", "rejected"},
    "offer": set(),
    "rejected": set(),
    "placed": set(),
    "likely_closed": {"shortlisted", "interview", "rejected"},
}


def _verified_employer(user: UserResponse) -> UUID:
    if user.employer_verification_level != 2:
        raise HTTPException(
            status_code=403,
            detail="Employer review access requires Level 2 business verification.",
        )
    return UUID(user.id)


def _owned_job(cursor: psycopg.Cursor, employer_id: UUID, job_id: UUID) -> dict[str, Any]:
    job = cursor.execute(
        """
        SELECT id, title, active, role_id
        FROM jobs
        WHERE id = %s AND employer_id = %s
        """,
        (job_id, employer_id),
    ).fetchone()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return dict(job)


def _save_job_details(
    cursor: psycopg.Cursor,
    employer_id: UUID,
    payload: EmployerJobInput,
    job_id: UUID | None = None,
) -> dict[str, Any]:
    if payload.role_id:
        role = cursor.execute(
            "SELECT id FROM role_catalog WHERE id = %s AND active",
            (payload.role_id,),
        ).fetchone()
        if not role:
            raise HTTPException(status_code=422, detail="Select an active platform role.")
    competency_ids = [item.competency_id for item in payload.requirements]
    if competency_ids:
        found = cursor.execute(
            """
            SELECT id FROM competencies
            WHERE id = ANY(%s) AND active
            """,
            (competency_ids,),
        ).fetchall()
        if {row["id"] for row in found} != set(competency_ids):
            raise HTTPException(
                status_code=422,
                detail="Job requirements must use active platform competencies.",
            )

    values = (
        payload.role_id,
        payload.title,
        payload.description,
        payload.location,
        payload.job_type,
        payload.experience_min_years,
        payload.experience_max_years,
        payload.salary_min_cents,
        payload.salary_max_cents,
        payload.salary_currency,
        payload.active,
    )
    if job_id is None:
        job = cursor.execute(
            """
            INSERT INTO jobs (
              employer_id, role_id, title, source_name, source_observed_at,
              description, location, job_type, experience_min_years,
              experience_max_years, salary_min_cents, salary_max_cents,
              salary_currency, active
            )
            VALUES (%s, %s, %s, 'Employer supplied', now(), %s, %s, %s, %s,
                    %s, %s, %s, %s, %s)
            RETURNING id, title, active, role_id, created_at
            """,
            (employer_id, *values),
        ).fetchone()
        job_id = job["id"]
    else:
        _owned_job(cursor, employer_id, job_id)
        job = cursor.execute(
            """
            UPDATE jobs
            SET role_id = %s, title = %s, source_observed_at = now(),
                description = %s, location = %s, job_type = %s,
                experience_min_years = %s, experience_max_years = %s,
                salary_min_cents = %s, salary_max_cents = %s,
                salary_currency = %s, active = %s, updated_at = now()
            WHERE id = %s AND employer_id = %s
            RETURNING id, title, active, role_id, created_at
            """,
            (*values, job_id, employer_id),
        ).fetchone()

    cursor.execute("DELETE FROM job_required_competencies WHERE job_id = %s", (job_id,))
    if payload.requirements:
        cursor.executemany(
            """
            INSERT INTO job_required_competencies
              (job_id, competency_id, required_level, importance)
            VALUES (%s, %s, %s, %s)
            """,
            [
                (job_id, item.competency_id, item.required_level, item.importance)
                for item in payload.requirements
            ],
        )
    cursor.execute(
        "UPDATE job_application_questions SET active = false WHERE job_id = %s AND active",
        (job_id,),
    )
    for sort_order, question in enumerate(payload.questions):
        cursor.execute(
            """
            INSERT INTO job_application_questions
              (job_id, prompt, answer_type, options, required, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                question.prompt,
                question.answer_type,
                Jsonb(question.options),
                question.required,
                sort_order,
            ),
        )
    return {
        "job_id": str(job["id"]),
        "title": job["title"],
        "active": job["active"],
        "role_id": str(job["role_id"]) if job["role_id"] else None,
        "created_at": job["created_at"].isoformat(),
    }


def _requirements(cursor: psycopg.Cursor, job_id: UUID) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in cursor.execute(
            """
            SELECT c.id AS competency_id, c.canonical_name AS skill_name,
                   jr.required_level, jr.importance
            FROM job_required_competencies jr
            JOIN competencies c ON c.id = jr.competency_id AND c.active
            WHERE jr.job_id = %s
            UNION ALL
            SELECT c.id AS competency_id, c.canonical_name AS skill_name,
                   rc.required_level, rc.importance
            FROM jobs j
            JOIN role_competencies rc ON rc.role_id = j.role_id
            JOIN competencies c ON c.id = rc.competency_id AND c.active
            WHERE j.id = %s
              AND NOT EXISTS (
                SELECT 1 FROM job_required_competencies jr WHERE jr.job_id = j.id
              )
            ORDER BY importance DESC, skill_name
            """,
            (job_id, job_id),
        ).fetchall()
    ]


def _blind_applicant(
    application: dict[str, Any],
    requirements: list[dict[str, Any]],
    candidate_number: int,
) -> dict[str, Any]:
    snapshot = application["application_snapshot"]
    score = score_applicant_match(requirements, snapshot)
    verified = snapshot.get("verified_skills", [])
    claimed = snapshot.get("claimed_skills", [])
    credentials = snapshot.get("verified_credentials", [])
    return {
        "application_id": str(application["application_id"]),
        "candidate_code": f"Candidate {candidate_number:03d}",
        "status": str(application["status"]),
        "applied_at": application["applied_at"].isoformat(),
        "fit": score,
        "skills": {
            "verified": [
                {"skill_name": item["skill_name"], "level": item["level"]}
                for item in verified
            ],
            "claimed": [
                {"skill_name": item["skill_name"], "level": item["level"]}
                for item in claimed
            ],
        },
        "verified_credentials": [
            {
                "skill_name": item["skill_name"],
                "level": item["level"],
                "evidence_tier": item["evidence_tier"],
            }
            for item in credentials
        ],
        "free_text_answers_withheld_until_interview": True,
    }


def _application_for_employer(
    cursor: psycopg.Cursor,
    employer_id: UUID,
    application_id: UUID,
) -> dict[str, Any]:
    application = cursor.execute(
        """
        SELECT a.id AS application_id, a.job_id, a.status, a.applied_at,
               a.application_snapshot, a.extra_answers, a.profile_share_consent_at
        FROM applications a
        JOIN jobs j ON j.id = a.job_id
        WHERE a.id = %s AND j.employer_id = %s
          AND a.profile_share_consent_at IS NOT NULL
        FOR UPDATE OF a
        """,
        (application_id, employer_id),
    ).fetchone()
    if not application:
        raise HTTPException(
            status_code=404,
            detail="Consented application not found for one of your jobs.",
        )
    return dict(application)


def _log_profile_view(
    cursor: psycopg.Cursor,
    employer_id: UUID,
    application_id: UUID,
) -> None:
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))",
        (str(employer_id),),
    )
    count = cursor.execute(
        """
        SELECT count(*) AS views
        FROM employer_application_profile_views
        WHERE employer_id = %s
          AND viewed_at >= now() - interval '24 hours'
        """,
        (employer_id,),
    ).fetchone()["views"]
    if count >= MAX_PROFILE_VIEWS_PER_24_HOURS:
        raise HTTPException(
            status_code=429,
            detail="Daily candidate profile-view limit reached. Try again later.",
        )
    cursor.execute(
        """
        INSERT INTO employer_application_profile_views (employer_id, application_id)
        VALUES (%s, %s)
        """,
        (employer_id, application_id),
    )


@router.get("/dashboard")
def employer_dashboard(
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        counts = cursor.execute(
            """
            SELECT count(DISTINCT j.id) FILTER (WHERE j.active)::integer AS open_jobs,
                   count(DISTINCT j.id) FILTER (WHERE NOT j.active)::integer AS paused_jobs,
                   count(a.id) FILTER (WHERE a.status = 'applied'
                     AND a.profile_share_consent_at IS NOT NULL)::integer AS new_applicants,
                   count(a.id) FILTER (WHERE a.status = 'shortlisted')::integer AS shortlisted,
                   count(a.id) FILTER (WHERE a.status = 'interview')::integer AS interviewing,
                   count(a.id) FILTER (WHERE a.status = 'offer')::integer AS offers
            FROM jobs j
            LEFT JOIN applications a ON a.job_id = j.id
            WHERE j.employer_id = %s
            """,
            (employer_id,),
        ).fetchone()
        return {
            **counts,
            "verification_level": user.employer_verification_level,
            "company": cursor.execute(
                """
                SELECT company_name, website, industry, verification_level
                FROM employer_profiles WHERE user_id = %s
                """,
                (employer_id,),
            ).fetchone(),
        }


@router.get("/roles")
def employer_available_roles(
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, str]]:
    _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT id, name FROM role_catalog WHERE active ORDER BY name"
        ).fetchall()
    return [{"role_id": str(row["id"]), "name": row["name"]} for row in rows]


@router.get("/competencies")
def employer_available_competencies(
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, str]]:
    _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT id, canonical_name
            FROM competencies WHERE active
            ORDER BY canonical_name
            """
        ).fetchall()
    return [
        {"competency_id": str(row["id"]), "skill_name": row["canonical_name"]}
        for row in rows
    ]


@router.get("/company")
def get_employer_company(
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        company = cursor.execute(
            """
            SELECT company_name, website, industry, verification_level
            FROM employer_profiles WHERE user_id = %s
            """,
            (employer_id,),
        ).fetchone()
    if not company:
        raise HTTPException(status_code=404, detail="Company profile not found.")
    return dict(company)


@router.put("/company")
def update_employer_company(
    payload: EmployerCompanyProfileUpdate,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str | None]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        current = cursor.execute(
            """
            SELECT company_name, website, verification_level
            FROM employer_profiles WHERE user_id = %s
            """,
            (employer_id,),
        ).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="Company profile not found.")
        normalized_website = str(payload.website) if payload.website else None
        identity_changed = (
            current["company_name"] != payload.company_name
            or current["website"] != normalized_website
        )
        company = cursor.execute(
            """
            UPDATE employer_profiles
            SET company_name = %s, website = %s, industry = %s,
                verification_level = CASE
                  WHEN company_name IS DISTINCT FROM %s OR website IS DISTINCT FROM %s
                  THEN 0 ELSE verification_level END,
                verified_at = CASE
                  WHEN company_name IS DISTINCT FROM %s OR website IS DISTINCT FROM %s
                  THEN NULL ELSE verified_at END
            WHERE user_id = %s
            RETURNING company_name, website, industry, verification_level
            """,
            (
                payload.company_name,
                normalized_website,
                payload.industry,
                payload.company_name,
                normalized_website,
                payload.company_name,
                normalized_website,
                employer_id,
            ),
        ).fetchone()
        if not company:
            raise HTTPException(status_code=404, detail="Company profile not found.")
        if identity_changed:
            cursor.execute(
                """
                INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
                VALUES (%s, 'employer_profile_updated', 'employer_profile', %s, %s)
                """,
                (
                    employer_id,
                    employer_id,
                    Jsonb(
                        {
                            "identity_changed": True,
                            "verification_reset": current["verification_level"] > 0,
                        }
                    ),
                ),
            )
    return dict(company)


@router.get("/jobs")
def list_employer_jobs(
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        jobs = cursor.execute(
            """
            SELECT j.id, j.title, j.active, j.location, j.job_type, j.created_at,
                   count(a.id) FILTER (WHERE a.profile_share_consent_at IS NOT NULL)::integer
                     AS applicant_count,
                   count(a.id) FILTER (WHERE a.status = 'applied'
                     AND a.profile_share_consent_at IS NOT NULL)::integer AS new_applicants
            FROM jobs j
            LEFT JOIN applications a ON a.job_id = j.id
            WHERE j.employer_id = %s
            GROUP BY j.id
            ORDER BY j.created_at DESC
            """,
            (employer_id,),
        ).fetchall()
    return {"jobs": [{**row, "job_id": str(row["id"]), "id": str(row["id"]), "created_at": row["created_at"].isoformat()} for row in jobs]}


@router.post("/jobs", status_code=201)
def create_employer_job(
    payload: EmployerJobInput,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        return _save_job_details(cursor, employer_id, payload)


@router.get("/jobs/{job_id:uuid}")
def get_employer_job(
    job_id: UUID,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        job = cursor.execute(
            """
            SELECT id, title, description, role_id, location, job_type,
                   experience_min_years, experience_max_years,
                   salary_min_cents, salary_max_cents, salary_currency, active
            FROM jobs WHERE id = %s AND employer_id = %s
            """,
            (job_id, employer_id),
        ).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        requirements = cursor.execute(
            """
            SELECT competency_id, required_level, importance
            FROM job_required_competencies
            WHERE job_id = %s
            """,
            (job_id,),
        ).fetchall()
        questions = cursor.execute(
            """
            SELECT prompt, answer_type, options, required
            FROM job_application_questions
            WHERE job_id = %s AND active
            ORDER BY sort_order, id
            """,
            (job_id,),
        ).fetchall()
    return {
        **job,
        "job_id": str(job["id"]),
        "role_id": str(job["role_id"]) if job["role_id"] else None,
        "requirements": [
            {
                "competency_id": str(item["competency_id"]),
                "required_level": item["required_level"],
                "importance": item["importance"],
            }
            for item in requirements
        ],
        "questions": [dict(question) for question in questions],
    }


@router.put("/jobs/{job_id:uuid}")
def update_employer_job(
    job_id: UUID,
    payload: EmployerJobInput,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        return _save_job_details(cursor, employer_id, payload, job_id)


@router.patch("/jobs/{job_id:uuid}/active")
def set_employer_job_active(
    job_id: UUID,
    payload: EmployerJobActiveUpdate,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        job = cursor.execute(
            """
            UPDATE jobs SET active = %s, updated_at = now()
            WHERE id = %s AND employer_id = %s
            RETURNING id, title, active
            """,
            (payload.active, job_id, employer_id),
        ).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, %s, 'job', %s, %s)
            """,
            (
                employer_id,
                "job_activated" if payload.active else "job_paused",
                job_id,
                Jsonb({"active": payload.active}),
            ),
        )
    return {"job_id": str(job["id"]), "title": job["title"], "active": job["active"]}


@router.get("/jobs/{job_id:uuid}/applicants")
def list_job_applicants(
    job_id: UUID,
    status: Literal[
        "applied", "heard_back", "no_reply", "shortlisted", "interview", "offer",
        "rejected", "placed", "likely_closed",
    ] | None = Query(default=None),
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        job = _owned_job(cursor, employer_id, job_id)
        requirements = _requirements(cursor, job_id)
        rows = cursor.execute(
            """
            SELECT a.id AS application_id, a.status, a.applied_at,
                   a.application_snapshot
            FROM applications a
            WHERE a.job_id = %s AND a.profile_share_consent_at IS NOT NULL
              AND a.withdrawn_at IS NULL
              AND (%s::application_status IS NULL OR a.status = %s)
            ORDER BY a.applied_at, a.id
            """,
            (job_id, status, status),
        ).fetchall()
        applicants = [
            _blind_applicant(row, requirements, index)
            for index, row in enumerate(rows, start=1)
        ]
    applicants.sort(
        key=lambda applicant: (
            -applicant["fit"]["match_percentage"],
            applicant["applied_at"],
        )
    )
    return {
        "job": {"job_id": str(job["id"]), "title": job["title"], "active": job["active"]},
        "scoring_version": "employer-weighted-v1",
        "scoring_explanation": (
            "Ranked by the importance-weighted level match for required competencies. "
            "Only consented applications are included; identity and free-text responses remain hidden."
        ),
        "applicants": applicants,
    }


@router.get("/applications/{application_id:uuid}")
def get_blind_applicant_profile(
    application_id: UUID,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        application = _application_for_employer(cursor, employer_id, application_id)
        _log_profile_view(cursor, employer_id, application_id)
        requirements = _requirements(cursor, application["job_id"])
        all_applications = cursor.execute(
            """
            SELECT id, applied_at FROM applications
            WHERE job_id = %s AND profile_share_consent_at IS NOT NULL
              AND withdrawn_at IS NULL
            ORDER BY applied_at, id
            """,
            (application["job_id"],),
        ).fetchall()
        candidate_number = next(
            index
            for index, row in enumerate(all_applications, start=1)
            if row["id"] == application_id
        )
        profile = _blind_applicant(application, requirements, candidate_number)
        job = _owned_job(cursor, employer_id, application["job_id"])
        profile["job"] = {"job_id": str(job["id"]), "title": job["title"]}
        note = cursor.execute(
            """
            SELECT note, tags, updated_at
            FROM employer_application_notes
            WHERE employer_id = %s AND application_id = %s
            """,
            (employer_id, application_id),
        ).fetchone()
        profile["employer_note"] = (
            {**note, "updated_at": note["updated_at"].isoformat()} if note else {"note": "", "tags": []}
        )
        profile["remaining_profile_views_today"] = max(
            0, MAX_PROFILE_VIEWS_PER_24_HOURS - int(cursor.execute(
                """
                SELECT count(*) AS views
                FROM employer_application_profile_views
                WHERE employer_id = %s
                  AND viewed_at >= now() - interval '24 hours'
                """,
                (employer_id,),
            ).fetchone()["views"])
        )
    return profile


@router.post("/jobs/{job_id:uuid}/compare")
def compare_blind_applicants(
    job_id: UUID,
    payload: CompareApplicantsRequest,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        _owned_job(cursor, employer_id, job_id)
        requirements = _requirements(cursor, job_id)
        rows = cursor.execute(
            """
            SELECT a.id AS application_id, a.job_id, a.status, a.applied_at,
                   a.application_snapshot, a.extra_answers, a.profile_share_consent_at
            FROM applications a
            WHERE a.id = ANY(%s) AND a.job_id = %s
              AND a.profile_share_consent_at IS NOT NULL AND a.withdrawn_at IS NULL
            ORDER BY a.applied_at, a.id
            FOR UPDATE
            """,
            (payload.application_ids, job_id),
        ).fetchall()
        if len(rows) != len(payload.application_ids):
            raise HTTPException(
                status_code=404,
                detail="All compared applicants must have consented to this job.",
            )
        for row in rows:
            _log_profile_view(cursor, employer_id, row["application_id"])
        applicants = [
            _blind_applicant(row, requirements, index)
            for index, row in enumerate(rows, start=1)
        ]
    return {
        "scoring_version": "employer-weighted-v1",
        "applicants": applicants,
    }


@router.put("/applications/{application_id:uuid}/note")
def save_employer_application_note(
    application_id: UUID,
    payload: EmployerApplicationNote,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        _application_for_employer(cursor, employer_id, application_id)
        note = cursor.execute(
            """
            INSERT INTO employer_application_notes
              (employer_id, application_id, note, tags, updated_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (employer_id, application_id)
            DO UPDATE SET note = EXCLUDED.note, tags = EXCLUDED.tags, updated_at = now()
            RETURNING note, tags, updated_at
            """,
            (employer_id, application_id, payload.note, payload.tags),
        ).fetchone()
    return {**note, "updated_at": note["updated_at"].isoformat()}


@router.post("/applications/{application_id:uuid}/status")
def update_employer_application_status(
    application_id: UUID,
    payload: EmployerApplicationStatusUpdate,
    user: UserResponse = Depends(require_role("employer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    employer_id = _verified_employer(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        application = cursor.execute(
            """
            SELECT a.status, a.withdrawn_at
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.id = %s AND j.employer_id = %s
              AND a.profile_share_consent_at IS NOT NULL
            FOR UPDATE OF a
            """,
            (application_id, employer_id),
        ).fetchone()
        if not application:
            raise HTTPException(status_code=404, detail="Consented application not found.")
        if application["withdrawn_at"] is not None:
            raise HTTPException(status_code=409, detail="Withdrawn applications cannot be advanced.")
        if payload.status not in EMPLOYER_TRANSITIONS.get(str(application["status"]), set()):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot move an application from {application['status']} to {payload.status}.",
            )
        event_note = payload.rejection_reason or payload.note
        cursor.execute(
            """
            UPDATE applications
            SET status = %s, last_employer_activity_at = now()
            WHERE id = %s
            """,
            (payload.status, application_id),
        )
        cursor.execute(
            """
            INSERT INTO application_status_events
              (application_id, actor_id, actor_role, status, note)
            VALUES (%s, %s, 'employer', %s, %s)
            """,
            (application_id, employer_id, payload.status, event_note),
        )
    return {"application_id": str(application_id), "status": payload.status}
