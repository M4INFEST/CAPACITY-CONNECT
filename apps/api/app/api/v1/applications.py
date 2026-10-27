import io
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.v1.auth import require_role
from app.db import get_connection
from app.schemas.applications import ApplicationStatusUpdate, ApplicationSubmission
from app.schemas.auth import UserResponse
from app.services.application_preparation import match_resume_keywords

router = APIRouter(prefix="/api/v1", tags=["Applications"])
CONSENT_VERSION = "application-profile-share-v1"
ALLOWED_STATUS_TRANSITIONS = {
    "applied": {"heard_back", "interview", "offer", "no_reply"},
    "heard_back": {"interview", "offer", "no_reply"},
    "interview": {"heard_back", "offer", "no_reply"},
    "no_reply": {"heard_back", "interview", "offer"},
    "offer": set(),
    "rejected": set(),
}


def _application_job(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    job_id: UUID,
) -> dict[str, Any]:
    job = cursor.execute(
        """
        SELECT j.id, j.title, j.description, j.role_id, j.employer_id,
               j.external_apply_url, ep.company_name
        FROM jobs j
        LEFT JOIN employer_profiles ep ON ep.user_id = j.employer_id
        WHERE j.id = %s AND j.active
        """,
        (job_id,),
    ).fetchone()
    if not job:
        raise HTTPException(status_code=404, detail="Active job not found.")
    existing = cursor.execute(
        """
        SELECT id, withdrawn_at
        FROM applications
        WHERE learner_id = %s AND job_id = %s
        """,
        (learner_id, job_id),
    ).fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                "An application already exists for this job. "
                "Open My applications to track it or review its withdrawn status."
            ),
        )
    return dict(job)


def _job_requirements(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    job: dict[str, Any],
) -> list[dict[str, Any]]:
    return cursor.execute(
        """
        SELECT c.id AS competency_id, c.canonical_name AS skill_name,
               jr.required_level, jr.importance, COALESCE(lc.level, 0) AS current_level
        FROM job_required_competencies jr
        JOIN competencies c ON c.id = jr.competency_id AND c.active
        LEFT JOIN learner_competencies lc
          ON lc.user_id = %s AND lc.competency_id = c.id
        WHERE jr.job_id = %s
        UNION ALL
        SELECT c.id AS competency_id, c.canonical_name AS skill_name,
               rc.required_level, rc.importance, COALESCE(lc.level, 0) AS current_level
        FROM role_competencies rc
        JOIN competencies c ON c.id = rc.competency_id AND c.active
        LEFT JOIN learner_competencies lc
          ON lc.user_id = %s AND lc.competency_id = c.id
        WHERE rc.role_id = %s
          AND NOT EXISTS (
            SELECT 1 FROM job_required_competencies jr WHERE jr.job_id = %s
          )
        ORDER BY importance DESC, skill_name
        """,
        (
            learner_id,
            job["id"],
            learner_id,
            job["role_id"],
            job["id"],
        ),
    ).fetchall()


def _application_preview(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    job_id: UUID,
) -> dict[str, Any]:
    job = _application_job(cursor, learner_id, job_id)
    requirements = [dict(row) for row in _job_requirements(cursor, learner_id, job)]
    claims = cursor.execute(
        """
        SELECT rc.id AS claim_id, rc.claim_text, rc.metric_prompt,
               rc.user_provided_metric, rc.approved_at,
               e.source_type, e.verification, c.canonical_name AS skill_name
        FROM resume_claims rc
        JOIN evidence e ON e.id = rc.evidence_id AND e.user_id = rc.user_id
        LEFT JOIN competencies c ON c.id = e.competency_id
        WHERE rc.user_id = %s AND rc.approved_at IS NOT NULL
          AND e.verification != 'rejected'
        ORDER BY rc.created_at DESC, rc.id
        """,
        (learner_id,),
    ).fetchall()
    verified_credentials = cursor.execute(
        """
        SELECT cr.id, cr.level, cr.evidence_tier, cr.issued_at,
               comp.canonical_name AS skill_name, cv.title AS course_title
        FROM credentials cr
        JOIN competencies comp ON comp.id = cr.competency_id
        LEFT JOIN course_versions cv ON cv.id = cr.course_version_id
        WHERE cr.learner_id = %s AND cr.evidence_tier = 'verified'
          AND cr.revoked_at IS NULL
          AND (cr.expires_at IS NULL OR cr.expires_at > now())
        ORDER BY comp.canonical_name, cr.issued_at DESC
        """,
        (learner_id,),
    ).fetchall()
    skills = cursor.execute(
        """
        SELECT c.id AS competency_id, c.canonical_name AS skill_name, lc.level,
               lc.status::text AS evidence_status
        FROM learner_competencies lc
        JOIN competencies c ON c.id = lc.competency_id AND c.active
        WHERE lc.user_id = %s AND lc.level IS NOT NULL
        ORDER BY lc.status = 'verified' DESC, c.canonical_name
        """,
        (learner_id,),
    ).fetchall()
    questions = cursor.execute(
        """
        SELECT id, prompt, answer_type, options, required, sort_order
        FROM job_application_questions
        WHERE job_id = %s AND active
        ORDER BY sort_order, id
        """,
        (job["id"],),
    ).fetchall()
    approved_lines = [row["claim_text"] for row in claims]
    keyword_check = match_resume_keywords(
        job["description"] or "",
        requirements,
        approved_lines,
    )
    return {
        "job": {
            "job_id": str(job["id"]),
            "title": job["title"],
            "company_name": job["company_name"] or "Platform employer",
        },
        "claims": [
            {
                "claim_id": str(row["claim_id"]),
                "claim_text": row["claim_text"],
                "metric_prompt": row["metric_prompt"],
                "user_provided_metric": row["user_provided_metric"],
                "source_type": row["source_type"],
                "verification": row["verification"],
                "skill_name": row["skill_name"],
                "approved_by_learner": True,
            }
            for row in claims
        ],
        "verified_credentials": [
            {
                "credential_id": str(row["id"]),
                "skill_name": row["skill_name"],
                "level": row["level"],
                "course_title": row["course_title"],
                "issued_at": row["issued_at"].isoformat(),
                "evidence_tier": row["evidence_tier"],
            }
            for row in verified_credentials
        ],
        "skills": [
            {
                "competency_id": str(row["competency_id"]),
                "skill_name": row["skill_name"],
                "level": row["level"],
                "evidence_status": row["evidence_status"],
            }
            for row in skills
        ],
        "questions": [
            {
                "question_id": str(row["id"]),
                "prompt": row["prompt"],
                "answer_type": row["answer_type"],
                "options": row["options"],
                "required": row["required"],
            }
            for row in questions
        ],
        "keyword_check": keyword_check,
        "profile_share_consent_required": True,
        "consent_version": CONSENT_VERSION,
    }


@router.get("/jobs/{job_id:uuid}/application-preview")
def get_application_preview(
    job_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        return _application_preview(cursor, UUID(user.id), job_id)


@router.post("/jobs/{job_id:uuid}/applications", status_code=201)
def submit_application(
    job_id: UUID,
    payload: ApplicationSubmission,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        preview = _application_preview(cursor, learner_id, job_id)
        claim_ids = {UUID(claim["claim_id"]) for claim in preview["claims"]}
        for line in payload.resume_lines:
            if not line.approved_by_learner:
                raise HTTPException(
                    status_code=422,
                    detail="Every resume line must be reviewed and approved by you.",
                )
            if line.claim_id is not None and line.claim_id not in claim_ids:
                raise HTTPException(
                    status_code=422,
                    detail="Resume lines may reference only your approved Passport claims.",
                )

        credential_ids = set(payload.selected_credential_ids)
        available_credential_ids = {
            UUID(item["credential_id"]) for item in preview["verified_credentials"]
        }
        if not credential_ids.issubset(available_credential_ids):
            raise HTTPException(
                status_code=422,
                detail="Only your current, verified credentials may be attached.",
            )

        question_by_id = {
            UUID(question["question_id"]): question
            for question in preview["questions"]
        }
        if not set(payload.extra_answers).issubset(question_by_id):
            raise HTTPException(
                status_code=422,
                detail="An answer refers to a question that is not on this job.",
            )
        for question_id, question in question_by_id.items():
            answer = payload.extra_answers.get(question_id)
            if question["required"] and (answer is None or answer == ""):
                raise HTTPException(
                    status_code=422,
                    detail=f"Answer the required question: {question['prompt']}",
                )
            if answer is None or answer == "":
                continue
            if question["answer_type"] == "yes_no" and not isinstance(answer, bool):
                raise HTTPException(
                    status_code=422,
                    detail=f"Answer the question using yes or no: {question['prompt']}",
                )
            if question["answer_type"] == "single_choice" and answer not in question["options"]:
                raise HTTPException(
                    status_code=422,
                    detail=f"Choose one of the listed options: {question['prompt']}",
                )
            if question["answer_type"] == "text" and (
                not isinstance(answer, str) or len(answer) > 2000
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"Text answers must be at most 2,000 characters: {question['prompt']}",
                )

        skills_snapshot = {
            "resume_lines": [
                {
                    "claim_id": str(line.claim_id) if line.claim_id else None,
                    "text": line.text,
                    "approved_by_learner": line.approved_by_learner,
                }
                for line in payload.resume_lines
            ],
            "claimed_skills": [
                skill
                for skill in preview["skills"]
                if skill["evidence_status"] != "verified"
            ],
            "verified_skills": [
                skill
                for skill in preview["skills"]
                if skill["evidence_status"] == "verified"
            ],
            "verified_credentials": [
                credential
                for credential in preview["verified_credentials"]
                if UUID(credential["credential_id"]) in credential_ids
            ],
        }
        resume_text = "\n".join(
            line.text for line in payload.resume_lines if line.approved_by_learner
        )
        questions_snapshot = {
            str(question_id): answer
            for question_id, answer in payload.extra_answers.items()
        }
        application = cursor.execute(
            """
            INSERT INTO applications
              (learner_id, job_id, status, application_snapshot,
               profile_share_consent_at, profile_share_consent_version,
               resume_text, cover_letter, extra_answers)
            VALUES (%s, %s, 'applied', %s, now(), %s, %s, %s, %s)
            ON CONFLICT (learner_id, job_id) DO NOTHING
            RETURNING id, applied_at
            """,
            (
                learner_id,
                job_id,
                Jsonb(skills_snapshot),
                CONSENT_VERSION,
                resume_text,
                payload.cover_letter,
                Jsonb(questions_snapshot),
            ),
        ).fetchone()
        if not application:
            raise HTTPException(
                status_code=409,
                detail="An application for this job already exists.",
            )
        cursor.execute(
            """
            INSERT INTO application_status_events
              (application_id, actor_id, actor_role, status, note)
            VALUES (%s, %s, 'trainee', 'applied', 'Learner submitted application')
            """,
            (application["id"], learner_id),
        )
    return {
        "application_id": str(application["id"]),
        "job_id": str(job_id),
        "status": "applied",
        "applied_at": application["applied_at"].isoformat(),
        "message": "Application submitted. Your selected profile details were shared with the employer.",
    }


@router.get("/applications")
def list_my_applications(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT a.id AS application_id, a.status,
                   a.withdrawn_at, a.applied_at, a.last_employer_activity_at,
                   a.likely_closed_at, j.id AS job_id, j.title AS job_title,
                   j.location, j.job_type, ep.company_name,
                   COALESCE(history.events, '[]'::jsonb) AS status_history
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            LEFT JOIN employer_profiles ep ON ep.user_id = j.employer_id
            LEFT JOIN LATERAL (
              SELECT jsonb_agg(
                jsonb_build_object(
                  'status', e.status, 'actor_role', e.actor_role,
                  'note', e.note, 'created_at', e.created_at
                ) ORDER BY e.created_at
              ) AS events
              FROM application_status_events e
              WHERE e.application_id = a.id
            ) history ON true
            WHERE a.learner_id = %s
            ORDER BY a.applied_at DESC
            """,
            (learner_id,),
        ).fetchall()
    return {
        "applications": [
            {
                **row,
                "application_id": str(row["application_id"]),
                "job_id": str(row["job_id"]),
                "status": "withdrawn" if row["withdrawn_at"] else row["status"],
                "applied_at": row["applied_at"].isoformat(),
                "last_employer_activity_at": row["last_employer_activity_at"].isoformat()
                if row["last_employer_activity_at"]
                else None,
                "likely_closed_at": row["likely_closed_at"].isoformat()
                if row["likely_closed_at"]
                else None,
                "withdrawn_at": row["withdrawn_at"].isoformat()
                if row["withdrawn_at"]
                else None,
                "status_history": [
                    {
                        **event,
                        "created_at": event["created_at"].isoformat()
                        if hasattr(event["created_at"], "isoformat")
                        else event["created_at"],
                    }
                    for event in row["status_history"]
                ],
            }
            for row in rows
        ]
    }


@router.post("/applications/{application_id:uuid}/status")
def update_application_status(
    application_id: UUID,
    payload: ApplicationStatusUpdate,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        application = cursor.execute(
            """
            SELECT status, withdrawn_at
            FROM applications
            WHERE id = %s AND learner_id = %s
            FOR UPDATE
            """,
            (application_id, learner_id),
        ).fetchone()
        if not application:
            raise HTTPException(status_code=404, detail="Application not found.")
        if application["withdrawn_at"] is not None:
            raise HTTPException(status_code=409, detail="Withdrawn applications cannot be updated.")
        if payload.status not in ALLOWED_STATUS_TRANSITIONS.get(application["status"], set()):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot update an application from {application['status']} to {payload.status}.",
            )
        cursor.execute(
            "UPDATE applications SET status = %s WHERE id = %s",
            (payload.status, application_id),
        )
        cursor.execute(
            """
            INSERT INTO application_status_events
              (application_id, actor_id, actor_role, status, note)
            VALUES (%s, %s, 'trainee', %s, %s)
            """,
            (application_id, learner_id, payload.status, payload.note),
        )
    return {"application_id": str(application_id), "status": payload.status}


@router.post("/applications/{application_id:uuid}/withdraw")
def withdraw_application(
    application_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        application = cursor.execute(
            """
            UPDATE applications
            SET withdrawn_at = now()
            WHERE id = %s AND learner_id = %s AND withdrawn_at IS NULL
              AND status NOT IN ('offer', 'rejected')
            RETURNING id
            """,
            (application_id, learner_id),
        ).fetchone()
        if not application:
            raise HTTPException(
                status_code=409,
                detail="Application not found or cannot be withdrawn at its current status.",
            )
        cursor.execute(
            """
            INSERT INTO application_status_events
              (application_id, actor_id, actor_role, status, note)
            VALUES (%s, %s, 'trainee', 'withdrawn', 'Learner withdrew application')
            """,
            (application_id, learner_id),
        )
    return {"application_id": str(application_id), "status": "withdrawn"}


@router.get("/applications/{application_id:uuid}/resume.txt")
def export_application_resume(
    application_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> StreamingResponse:
    with connection.cursor(row_factory=dict_row) as cursor:
        application = cursor.execute(
            """
            SELECT a.resume_text, j.title
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.id = %s AND a.learner_id = %s
            """,
            (application_id, UUID(user.id)),
        ).fetchone()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    content = io.BytesIO(application["resume_text"].encode("utf-8"))
    safe_title = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in application["title"]
    ).strip("_")[:60] or "application"
    return StreamingResponse(
        content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}-resume.txt"'
        },
    )
