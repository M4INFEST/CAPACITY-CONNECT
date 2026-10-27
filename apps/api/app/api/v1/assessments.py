import json
import os
import random
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.v1.auth import require_role
from app.api.v1.credentials import issue_attempt_credentials
from app.db import get_connection
from app.schemas.assessments import (
    AssessmentCreateRequest,
    AssessmentEventRequest,
    AssessmentPolicyRequest,
    AssessmentPracticeRequest,
    AssessmentQuestionDecisionRequest,
    AssessmentQuestionRequest,
    AssessmentResponseRequest,
    AssessmentStartRequest,
    AssessmentSubmitRequest,
)
from app.schemas.auth import UserResponse
from app.services.assessments import (
    estimate_level_range,
    level_for_rating,
    should_stop_early,
    update_elo,
    update_uncertainty,
)
from app.services.profile_progress import (
    capture_profile_baseline,
    update_profile_after_assessment,
)

router = APIRouter(prefix="/api/v1", tags=["Adaptive assessment"])


def _learner_id(user: UserResponse) -> UUID:
    return UUID(user.id)


def _load_attempt(
    cursor: psycopg.Cursor,
    attempt_id: UUID,
    user: UserResponse,
    *,
    lock: bool = False,
) -> dict[str, Any]:
    attempt = cursor.execute(
        f"""
        SELECT aa.id, aa.assessment_id, aa.learner_id, aa.enrollment_id,
               aa.started_at, aa.submitted_at, aa.level_min, aa.level_max,
               aa.confidence, aa.provisional, aa.evidence_tier, aa.status,
               aa.deadline_at, aa.explanation, aa.integrity_flag_count,
               a.title AS assessment_title, a.min_questions, a.max_questions,
               a.target_level, a.time_limit_minutes, a.course_version_id
        FROM assessment_attempts aa
        JOIN assessments a ON a.id = aa.assessment_id
        WHERE aa.id = %s
        {"FOR UPDATE OF aa" if lock else ""}
        """,
        (attempt_id,),
    ).fetchone()
    if not attempt:
        raise HTTPException(status_code=404, detail="Assessment attempt not found")
    if str(attempt["learner_id"]) != user.id:
        raise HTTPException(status_code=403, detail="You cannot access this assessment attempt")
    return attempt


def _effective_minimum(cursor: psycopg.Cursor, attempt: dict[str, Any]) -> int:
    bank_count = cursor.execute(
        """
        SELECT count(*) AS count
        FROM assessment_questions
        WHERE assessment_id = %s AND active AND moderation_status = 'approved'
        """,
        (attempt["assessment_id"],),
    ).fetchone()["count"]
    return min(attempt["min_questions"], bank_count)


def _approved_question_count(cursor: psycopg.Cursor, assessment_id: UUID) -> int:
    return cursor.execute(
        """
        SELECT count(*) AS count
        FROM assessment_questions
        WHERE assessment_id = %s AND active AND moderation_status = 'approved'
        """,
        (assessment_id,),
    ).fetchone()["count"]


def _answer_matches(answer: Any, answer_key: Any, question_type: str) -> bool:
    if question_type == "multi_select":
        if not isinstance(answer, list) or not isinstance(answer_key, list):
            return False
        return sorted(_canonical_answer(item) for item in answer) == sorted(
            _canonical_answer(item) for item in answer_key
        )
    if question_type in {"short_answer", "scenario", "code_task"}:
        return _canonical_answer(answer, normalize_text=True) == _canonical_answer(
            answer_key, normalize_text=True
        )
    return _canonical_answer(answer) == _canonical_answer(answer_key)


def _canonical_answer(value: Any, *, normalize_text: bool = False) -> str:
    normalized = _normalize_answer(value) if normalize_text else value
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _normalize_answer(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip()).casefold()
    if isinstance(value, list):
        return [_normalize_answer(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_answer(item) for key, item in value.items()}
    return value


def _attempt_metrics(
    cursor: psycopg.Cursor, attempt_id: UUID
) -> tuple[int, dict[str, int | str], int]:
    submitted = cursor.execute(
        """
        SELECT count(*) AS count
        FROM assessment_responses
        WHERE attempt_id = %s AND submitted
        """,
        (attempt_id,),
    ).fetchone()["count"]
    rows = cursor.execute(
        """
        SELECT COALESCE(lsr.elo_rating, 1000) AS rating,
               COALESCE(lsr.uncertainty, 350)::float AS uncertainty
        FROM assessment_responses ar
        JOIN assessment_questions aq ON aq.id = ar.question_id
        LEFT JOIN learner_skill_ratings lsr
          ON lsr.learner_id = (
            SELECT learner_id FROM assessment_attempts WHERE id = %s
          )
         AND lsr.competency_id = aq.competency_id
        WHERE ar.attempt_id = %s AND ar.submitted AND ar.dont_know = false
        GROUP BY aq.competency_id, lsr.elo_rating, lsr.uncertainty
        """,
        (attempt_id, attempt_id),
    ).fetchall()
    if not rows:
        return submitted, estimate_level_range(1000, 350, 0), 1000
    scored = cursor.execute(
        """
        SELECT count(*) AS count
        FROM assessment_responses
        WHERE attempt_id = %s AND submitted AND dont_know = false
        """,
        (attempt_id,),
    ).fetchone()["count"]
    rating = round(sum(row["rating"] for row in rows) / len(rows))
    uncertainty = sum(row["uncertainty"] for row in rows) / len(rows)
    return submitted, estimate_level_range(rating, uncertainty, scored), rating


def _next_question(
    cursor: psycopg.Cursor, attempt: dict[str, Any]
) -> dict[str, Any] | None:
    draft = cursor.execute(
        """
        SELECT aq.id, aq.competency_id, aq.question_type, aq.prompt, aq.options,
               aq.difficulty_level, aq.elo_rating, aq.calibration_status,
               aq.estimated_time_seconds, aq.explanation,
               comp.canonical_name AS skill_name
        FROM assessment_responses ar
        JOIN assessment_questions aq ON aq.id = ar.question_id
        JOIN competencies comp ON comp.id = aq.competency_id
        WHERE ar.attempt_id = %s AND ar.submitted = false
          AND aq.active AND aq.moderation_status = 'approved'
        LIMIT 1
        """,
        (attempt["id"],),
    ).fetchone()
    if draft:
        return draft

    answered = cursor.execute(
        """
        SELECT aq.competency_id, count(*) AS count
        FROM assessment_responses ar
        JOIN assessment_questions aq ON aq.id = ar.question_id
        WHERE ar.attempt_id = %s AND ar.submitted
        GROUP BY aq.competency_id
        """,
        (attempt["id"],),
    ).fetchall()
    answered_by_competency = {str(row["competency_id"]): row["count"] for row in answered}
    ratings = cursor.execute(
        """
        SELECT competency_id, elo_rating
        FROM learner_skill_ratings
        WHERE learner_id = %s
        """,
        (attempt["learner_id"],),
    ).fetchall()
    rating_by_competency = {
        str(row["competency_id"]): row["elo_rating"] for row in ratings
    }
    candidates = cursor.execute(
        """
        SELECT aq.id, aq.competency_id, aq.question_type, aq.prompt, aq.options,
               aq.difficulty_level, aq.elo_rating, aq.calibration_status,
               aq.estimated_time_seconds, aq.explanation,
               comp.canonical_name AS skill_name
        FROM assessment_questions aq
        JOIN competencies comp ON comp.id = aq.competency_id
        WHERE aq.assessment_id = %s AND aq.active
          AND aq.moderation_status = 'approved'
          AND NOT EXISTS (
            SELECT 1 FROM assessment_responses ar
            WHERE ar.attempt_id = %s AND ar.question_id = aq.id AND ar.submitted
          )
        """,
        (attempt["assessment_id"], attempt["id"]),
    ).fetchall()
    if not candidates:
        return None

    def selection_key(question: dict[str, Any]) -> tuple[int, float, int]:
        competency_id = str(question["competency_id"])
        learner_rating = rating_by_competency.get(competency_id, 1000)
        calibrated = question["calibration_status"] == "calibrated"
        estimated_question_rating = (
            question["elo_rating"]
            if calibrated
            else 700 + 100 * question["difficulty_level"]
        )
        # Optimal Item Response Selection: Maximize Fisher Information Gain
        # Equivalent to minimizing negative information gain:
        p = expected_score(learner_rating, estimated_question_rating, 1.2 if calibrated else 1.0)
        information_gain = p * (1.0 - p)
        neg_info = -round(information_gain, 4)

        return (
            answered_by_competency.get(competency_id, 0),
            neg_info,
            0 if calibrated else 1,
        )

    return min(candidates, key=selection_key)


def _public_question(question: dict[str, Any], attempt_id: UUID) -> dict[str, Any]:
    options = question["options"] or []
    if options:
        options = list(options)
        random.Random(f"{attempt_id}:{question['id']}").shuffle(options)
    return {
        "id": str(question["id"]),
        "competency_id": str(question["competency_id"]),
        "skill_name": question["skill_name"],
        "question_type": question["question_type"],
        "prompt": question["prompt"],
        "options": options,
        "difficulty_level": question["difficulty_level"],
        "calibration_status": question["calibration_status"],
        "estimated_time_seconds": question["estimated_time_seconds"],
    }


def _result_payload(
    cursor: psycopg.Cursor, attempt: dict[str, Any]
) -> dict[str, Any]:
    question_total, estimate, _ = _attempt_metrics(cursor, attempt["id"])
    breakdown_rows = cursor.execute(
        """
        SELECT aq.competency_id, comp.canonical_name AS skill_name,
               COALESCE(lsr.elo_rating, 1000) AS rating,
               COALESCE(lsr.uncertainty, 350)::float AS uncertainty,
               count(*)::integer AS question_count,
               count(*) FILTER (WHERE ar.dont_know = false)::integer AS scored_question_count,
               count(*) FILTER (WHERE ar.correct IS TRUE)::integer AS correct_count,
               count(*) FILTER (WHERE ar.correct IS FALSE OR ar.dont_know)::integer AS missed_count
        FROM assessment_responses ar
        JOIN assessment_questions aq ON aq.id = ar.question_id
        JOIN competencies comp ON comp.id = aq.competency_id
        LEFT JOIN learner_skill_ratings lsr
          ON lsr.learner_id = %s AND lsr.competency_id = aq.competency_id
        WHERE ar.attempt_id = %s AND ar.submitted
        GROUP BY aq.competency_id, comp.canonical_name, lsr.elo_rating, lsr.uncertainty
        ORDER BY comp.canonical_name
        """,
        (attempt["learner_id"], attempt["id"]),
    ).fetchall()
    breakdown = [
        {
            "competency_id": str(row["competency_id"]),
            "skill_name": row["skill_name"],
            "level": level_for_rating(row["rating"]),
            "level_range": estimate_level_range(
                row["rating"], row["uncertainty"], row["scored_question_count"]
            ),
            "question_count": row["question_count"],
            "correct_count": row["correct_count"],
            "missed_count": row["missed_count"],
        }
        for row in breakdown_rows
    ]
    weak_skills = [
        item
        for item in breakdown
        if item["missed_count"] > 0
    ]
    if weak_skills and attempt["course_version_id"]:
        competency_ids = [UUID(item["competency_id"]) for item in weak_skills]
        resources = cursor.execute(
            """
            SELECT DISTINCT cv.id, cv.title, cv.course_id
            FROM course_version_competencies cvc
            JOIN course_versions cv ON cv.id = cvc.course_version_id
            WHERE cvc.competency_id = ANY(%s)
              AND cv.status = 'published'
              AND EXISTS (
                SELECT 1 FROM course_approval_requests car
                WHERE car.course_version_id = cv.id AND car.status = 'approved'
              )
            ORDER BY cv.title
            LIMIT 5
            """,
            (competency_ids,),
        ).fetchall()
        practice_rows = cursor.execute(
            """
            SELECT aq.id, aq.prompt, aq.question_type, aq.options,
                   aq.calibration_status, comp.canonical_name AS skill_name
            FROM assessment_questions aq
            JOIN assessments a ON a.id = aq.assessment_id AND a.active
            JOIN competencies comp ON comp.id = aq.competency_id
            WHERE aq.competency_id = ANY(%s)
              AND aq.active AND aq.moderation_status = 'approved'
              AND NOT EXISTS (
                SELECT 1 FROM assessment_responses ar
                WHERE ar.attempt_id = %s AND ar.question_id = aq.id
              )
            ORDER BY (aq.calibration_status = 'calibrated') DESC, aq.id
            LIMIT 5
            """,
            (competency_ids, attempt["id"]),
        ).fetchall()
    else:
        resources = []
        practice_rows = []
    credential_rows = cursor.execute(
        """
        SELECT cr.id, cr.level, cr.evidence_tier, comp.canonical_name AS skill_name
        FROM credentials cr
        JOIN competencies comp ON comp.id = cr.competency_id
        WHERE cr.assessment_attempt_id = %s
        ORDER BY comp.canonical_name
        """,
        (attempt["id"],),
    ).fetchall()
    profile_changes = cursor.execute(
        """
        SELECT competency_id, previous_level, updated_level, evidence_quality,
               score, average_question_difficulty, credential_id
        FROM assessment_skill_profile_updates
        WHERE attempt_id = %s
        ORDER BY competency_id
        """,
        (attempt["id"],),
    ).fetchall()
    readiness_rows = cursor.execute(
        """
        SELECT s.role_id, r.name AS role_name, s.readiness_before,
               s.readiness_after,
               s.readiness_after - s.readiness_before AS readiness_delta
        FROM learner_readiness_snapshots s
        JOIN role_catalog r ON r.id = s.role_id
        WHERE s.attempt_id = %s
        ORDER BY r.name
        """,
        (attempt["id"],),
    ).fetchall()
    calibrated_questions = cursor.execute(
        """
        SELECT count(*)::integer AS count
        FROM assessment_responses ar
        JOIN assessment_questions aq ON aq.id = ar.question_id
        WHERE ar.attempt_id = %s AND ar.submitted
          AND aq.calibration_status = 'calibrated'
        """,
        (attempt["id"],),
    ).fetchone()["count"]
    target_level = attempt["target_level"]
    return {
        "attempt_id": str(attempt["id"]),
        "status": attempt["status"],
        "evidence_tier": attempt["evidence_tier"],
        "provisional": attempt["provisional"],
        "level_min": estimate["level_min"],
        "level_max": estimate["level_max"],
        "confidence": estimate["confidence"],
        "target_level": target_level,
        "pass": estimate["level_min"] >= target_level,
        "question_count": question_total,
        "calibrated_question_count": calibrated_questions,
        "integrity_flag_count": attempt["integrity_flag_count"],
        "explanation": attempt["explanation"],
        "credentials_issued": [
            {
                "credential_id": str(row["id"]),
                "skill_name": row["skill_name"],
                "level": row["level"],
                "evidence_tier": row["evidence_tier"],
                "verification_url": (
                    f"{os.getenv('WEB_PUBLIC_URL', 'http://localhost:3000').rstrip('/')}"
                    f"/verify/{row['id']}"
                ),
            }
            for row in credential_rows
        ],
        "profile_update": {
            "readiness_by_role": [
                {
                    "role_id": str(row["role_id"]),
                    "role_name": row["role_name"],
                    "readiness_before": float(row["readiness_before"]),
                    "readiness_after": float(row["readiness_after"]),
                    "readiness_delta": float(row["readiness_delta"]),
                }
                for row in readiness_rows
            ],
            "skill_changes": [
                {
                    "competency_id": str(row["competency_id"]),
                    "previous_level": row["previous_level"],
                    "updated_level": row["updated_level"],
                    "evidence_quality": row["evidence_quality"],
                    "score": float(row["score"]),
                    "average_question_difficulty": float(
                        row["average_question_difficulty"]
                    ),
                    "credential_id": (
                        str(row["credential_id"]) if row["credential_id"] else None
                    ),
                }
                for row in profile_changes
            ],
        },
        "breakdown": breakdown,
        "weak_skills": weak_skills,
        "recommended_courses": [
            {"course_version_id": str(row["id"]), "title": row["title"]}
            for row in resources
        ],
        "practice_questions": [
            {
                "id": str(row["id"]),
                "skill_name": row["skill_name"],
                "question_type": row["question_type"],
                "prompt": row["prompt"],
                "options": row["options"],
                "calibration_status": row["calibration_status"],
                "attempt": cursor.execute(
                    """
                    SELECT answer, correct
                    FROM assessment_practice_responses
                    WHERE attempt_id = %s AND question_id = %s
                    """,
                    (attempt["id"], row["id"]),
                ).fetchone(),
            }
            for row in practice_rows
        ],
        "message": (
            "This is a provisional estimate, not a credential. "
            "A verified level requires the separate evidence review."
        ),
    }


def _store_estimate(cursor: psycopg.Cursor, attempt: dict[str, Any]) -> None:
    _, estimate, _ = _attempt_metrics(cursor, attempt["id"])
    cursor.execute(
        """
        UPDATE assessment_attempts
        SET level_min = %s, level_max = %s, confidence = %s, provisional = true
        WHERE id = %s
        """,
        (
            estimate["level_min"],
            estimate["level_max"],
            estimate["confidence"],
            attempt["id"],
        ),
    )
    attempt["level_min"] = estimate["level_min"]
    attempt["level_max"] = estimate["level_max"]
    attempt["confidence"] = estimate["confidence"]
    attempt["provisional"] = True


def _expire_if_needed(
    cursor: psycopg.Cursor, attempt: dict[str, Any]
) -> dict[str, Any]:
    if (
        attempt["status"] == "in_progress"
        and attempt["deadline_at"] is not None
        and attempt["deadline_at"] <= datetime.now(timezone.utc)
    ):
        cursor.execute(
            """
            UPDATE assessment_attempts
            SET status = 'expired', submitted_at = now()
            WHERE id = %s AND status = 'in_progress'
            """,
            (attempt["id"],),
        )
        attempt["status"] = "expired"
        _store_estimate(cursor, attempt)
    return attempt


@router.get("/learning/enrollments/{enrollment_id}/assessment")
def get_enrollment_assessment(
    enrollment_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        enrollment = cursor.execute(
            """
            SELECT e.id, e.learner_id, e.course_version_id, e.status
            FROM enrollments e
            WHERE e.id = %s
            """,
            (enrollment_id,),
        ).fetchone()
        if not enrollment or str(enrollment["learner_id"]) != user.id:
            raise HTTPException(status_code=404, detail="Enrollment not found")
        lessons = cursor.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE lp.completed_at IS NOT NULL) AS completed
            FROM lessons l
            LEFT JOIN lesson_progress lp
              ON lp.lesson_id = l.id AND lp.enrollment_id = %s
            WHERE l.course_version_id = %s
            """,
            (enrollment_id, enrollment["course_version_id"]),
        ).fetchone()
        if not lessons["total"] or lessons["total"] != lessons["completed"]:
            return {
                "available": False,
                "message": "Complete all required lessons before starting the assessment.",
            }
        assessment = cursor.execute(
            """
            SELECT a.id, a.title, a.min_questions, a.max_questions, a.target_level,
                   a.time_limit_minutes,
                   count(aq.id)::integer AS approved_question_count,
                   count(aq.id) FILTER (
                     WHERE aq.question_type IN ('scenario', 'code_task')
                   )::integer AS practical_question_count
            FROM assessments a
            LEFT JOIN assessment_questions aq
              ON aq.assessment_id = a.id
             AND aq.active AND aq.moderation_status = 'approved'
            WHERE a.course_version_id = %s AND a.active
            GROUP BY a.id
            ORDER BY a.title
            LIMIT 1
            """,
            (enrollment["course_version_id"],),
        ).fetchone()
        if not assessment or not assessment["approved_question_count"]:
            return {
                "available": False,
                "message": "The trainer is preparing an admin-approved assessment question bank.",
            }
        active_attempt = cursor.execute(
            """
            SELECT id FROM assessment_attempts
            WHERE learner_id = %s AND assessment_id = %s AND status = 'in_progress'
            ORDER BY started_at DESC LIMIT 1
            """,
            (UUID(user.id), assessment["id"]),
        ).fetchone()
        remaining_attempts = cursor.execute(
            """
            SELECT p.attempts_per_week - count(aa.id)::integer AS remaining,
                   p.attempts_per_week
            FROM assessment_policy p
            LEFT JOIN assessment_attempts aa
              ON aa.learner_id = %s
             AND aa.started_at >= now() - interval '7 days'
            WHERE p.singleton = true
            GROUP BY p.attempts_per_week
            """,
            (UUID(user.id),),
        ).fetchone()
        return {
            "available": True,
            "assessment_id": str(assessment["id"]),
            "title": assessment["title"],
            "min_questions": min(
                assessment["min_questions"], assessment["approved_question_count"]
            ),
            "max_questions": min(
                assessment["max_questions"], assessment["approved_question_count"]
            ),
            "time_limit_minutes": assessment["time_limit_minutes"],
            "target_level": assessment["target_level"],
            "remaining_attempts": max(0, remaining_attempts["remaining"]),
            "active_attempt_id": str(active_attempt["id"]) if active_attempt else None,
            "verified_tier_available": assessment["practical_question_count"] > 0,
        }


@router.post("/learning/enrollments/{enrollment_id}/assessment-attempts", status_code=201)
def start_assessment_attempt(
    enrollment_id: UUID,
    payload: AssessmentStartRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = _learner_id(user)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))", (str(learner_id),))
        cursor.execute(
            """
            UPDATE assessment_attempts
            SET status = 'expired', submitted_at = now()
            WHERE learner_id = %s AND status = 'in_progress'
              AND deadline_at <= now()
            """,
            (learner_id,),
        )
        enrollment = cursor.execute(
            """
            SELECT e.id, e.learner_id, e.course_version_id
            FROM enrollments e
            WHERE e.id = %s
            """,
            (enrollment_id,),
        ).fetchone()
        if not enrollment or str(enrollment["learner_id"]) != user.id:
            raise HTTPException(status_code=404, detail="Enrollment not found")
        lesson_state = cursor.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE lp.completed_at IS NOT NULL) AS completed
            FROM lessons l
            LEFT JOIN lesson_progress lp
              ON lp.lesson_id = l.id AND lp.enrollment_id = %s
            WHERE l.course_version_id = %s
            """,
            (enrollment_id, enrollment["course_version_id"]),
        ).fetchone()
        if not lesson_state["total"] or lesson_state["total"] != lesson_state["completed"]:
            raise HTTPException(status_code=409, detail="Complete all required lessons first")
        assessment = cursor.execute(
            """
            SELECT a.id, a.title, a.time_limit_minutes, a.min_questions,
                   a.max_questions, a.target_level,
                   count(aq.id)::integer AS approved_question_count,
                   count(aq.id) FILTER (
                     WHERE aq.question_type IN ('scenario', 'code_task')
                   )::integer AS practical_question_count
            FROM assessments a
            LEFT JOIN assessment_questions aq
              ON aq.assessment_id = a.id
             AND aq.active AND aq.moderation_status = 'approved'
            WHERE a.course_version_id = %s AND a.active
            GROUP BY a.id
            ORDER BY a.title
            LIMIT 1
            """,
            (enrollment["course_version_id"],),
        ).fetchone()
        if not assessment or not assessment["approved_question_count"]:
            raise HTTPException(status_code=409, detail="No admin-approved assessment is available yet")
        if payload.evidence_tier == "verified" and not assessment["practical_question_count"]:
            raise HTTPException(
                status_code=409,
                detail="Verified assessment requires at least one approved scenario or code task.",
            )
        active_attempt = cursor.execute(
            """
            SELECT id, assessment_id FROM assessment_attempts
            WHERE learner_id = %s AND status = 'in_progress'
            FOR UPDATE
            """,
            (learner_id,),
        ).fetchone()
        if active_attempt:
            if active_attempt["assessment_id"] == assessment["id"]:
                return {
                    "attempt_id": str(active_attempt["id"]),
                    "status": "in_progress",
                    "message": "Resuming your active assessment attempt.",
                }
            raise HTTPException(
                status_code=409,
                detail="Finish or let your current assessment attempt expire before starting another.",
            )
        policy = cursor.execute(
            "SELECT attempts_per_week FROM assessment_policy WHERE singleton = true"
        ).fetchone()
        attempts_this_week = cursor.execute(
            """
            SELECT count(*)::integer AS count FROM assessment_attempts
            WHERE learner_id = %s AND started_at >= now() - interval '7 days'
            """,
            (learner_id,),
        ).fetchone()["count"]
        if attempts_this_week >= policy["attempts_per_week"]:
            raise HTTPException(
                status_code=429,
                detail="Your weekly assessment attempt limit has been reached.",
            )
        row = cursor.execute(
            """
            INSERT INTO assessment_attempts
              (assessment_id, learner_id, enrollment_id, evidence_tier, deadline_at)
            VALUES (
              %s, %s, %s, %s,
              now() + (%s * interval '1 minute')
            )
            RETURNING id, started_at, deadline_at
            """,
            (
                assessment["id"],
                learner_id,
                enrollment_id,
                payload.evidence_tier,
                assessment["time_limit_minutes"],
            ),
        ).fetchone()
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'assessment_attempt_started', 'assessment_attempt', %s, %s)
            """,
            (
                learner_id,
                row["id"],
                Jsonb(
                    {
                        "assessment_id": str(assessment["id"]),
                        "evidence_tier": payload.evidence_tier,
                        "enrollment_id": str(enrollment_id),
                    }
                ),
            ),
        )
    return {
        "attempt_id": str(row["id"]),
        "title": assessment["title"],
        "status": "in_progress",
        "evidence_tier": payload.evidence_tier,
        "started_at": row["started_at"].isoformat(),
        "deadline_at": row["deadline_at"].isoformat(),
        "time_limit_minutes": assessment["time_limit_minutes"],
        "min_questions": min(
            assessment["min_questions"], assessment["approved_question_count"]
        ),
        "max_questions": min(
            assessment["max_questions"], assessment["approved_question_count"]
        ),
        "integrity_notice": (
            "Responses are auto-saved. Tab switches are recorded for review and never cause an automatic fail."
        ),
    }


@router.get("/assessment-attempts/{attempt_id}")
def get_assessment_attempt(
    attempt_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        attempt = _load_attempt(cursor, attempt_id, user)
        attempt = _expire_if_needed(cursor, attempt)
        if attempt["status"] != "in_progress":
            return {
                "status": attempt["status"],
                "result": _result_payload(cursor, attempt),
            }
        count, estimate, _ = _attempt_metrics(cursor, attempt_id)
        bank_count = _approved_question_count(cursor, attempt["assessment_id"])
        maximum = min(attempt["max_questions"], bank_count)
        minimum = _effective_minimum(cursor, attempt)
        next_question = _next_question(cursor, attempt)
        early_stop = estimate["confidence"] != "low" and should_stop_early(
            count, minimum, int(estimate["level_min"]), int(estimate["level_max"])
        )
        can_submit = count >= minimum and (early_stop or count >= maximum or next_question is None)
        if count >= maximum or early_stop:
            next_question = None
        if next_question is not None:
            public_question = _public_question(next_question, attempt_id)
            draft = cursor.execute(
                """
                SELECT answer, learner_confidence, dont_know
                FROM assessment_responses
                WHERE attempt_id = %s AND question_id = %s AND submitted = false
                """,
                (attempt_id, next_question["id"]),
            ).fetchone()
            if draft:
                public_question["draft_answer"] = draft["answer"]
                public_question["draft_confidence"] = draft["learner_confidence"]
                public_question["draft_dont_know"] = draft["dont_know"]
        else:
            public_question = None
        return {
            "attempt_id": str(attempt_id),
            "assessment_title": attempt["assessment_title"],
            "status": attempt["status"],
            "evidence_tier": attempt["evidence_tier"],
            "deadline_at": attempt["deadline_at"].isoformat() if attempt["deadline_at"] else None,
            "answered_questions": count,
            "min_questions": minimum,
            "max_questions": maximum,
            "can_submit": can_submit,
            "provisional_estimate": estimate,
            "question": public_question,
            "integrity_notice": "Tab switches are logged for review and never cause an automatic fail.",
        }


@router.put("/assessment-attempts/{attempt_id}/responses/{question_id}")
def save_assessment_response(
    attempt_id: UUID,
    question_id: UUID,
    payload: AssessmentResponseRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        attempt = _load_attempt(cursor, attempt_id, user, lock=True)
        attempt = _expire_if_needed(cursor, attempt)
        if attempt["status"] != "in_progress":
            raise HTTPException(status_code=409, detail="This assessment attempt is no longer active")
        expected_question = _next_question(cursor, attempt)
        if not expected_question or expected_question["id"] != question_id:
            raise HTTPException(status_code=409, detail="This is not the current adaptive question")
        if payload.dont_know and not payload.finalize:
            raise HTTPException(status_code=422, detail="Finalize I don't know to record it without a penalty")
        if not payload.finalize:
            cursor.execute(
                """
                INSERT INTO assessment_responses
                  (attempt_id, question_id, answer, learner_confidence, dont_know, submitted)
                VALUES (%s, %s, %s, %s, false, false)
                ON CONFLICT (attempt_id, question_id) DO UPDATE
                SET answer = EXCLUDED.answer,
                    learner_confidence = EXCLUDED.learner_confidence
                WHERE assessment_responses.submitted = false
                """,
                (
                    attempt_id,
                    question_id,
                    Jsonb(payload.answer),
                    payload.learner_confidence,
                ),
            )
            return {"status": "saved", "finalized": False}

        existing = cursor.execute(
            """
            SELECT submitted FROM assessment_responses
            WHERE attempt_id = %s AND question_id = %s
            """,
            (attempt_id, question_id),
        ).fetchone()
        if existing and existing["submitted"]:
            raise HTTPException(status_code=409, detail="This answer was already finalized")
        correct: bool | None = None
        if not payload.dont_know:
            correct = _answer_matches(
                payload.answer,
                cursor.execute(
                    "SELECT answer_key FROM assessment_questions WHERE id = %s",
                    (question_id,),
                ).fetchone()["answer_key"],
                expected_question["question_type"],
            )
        cursor.execute(
            """
            INSERT INTO assessment_responses
              (attempt_id, question_id, answer, correct, learner_confidence, dont_know, submitted)
            VALUES (%s, %s, %s, %s, %s, %s, true)
            ON CONFLICT (attempt_id, question_id) DO UPDATE
            SET answer = EXCLUDED.answer,
                correct = EXCLUDED.correct,
                learner_confidence = EXCLUDED.learner_confidence,
                dont_know = EXCLUDED.dont_know,
                submitted = true,
                answered_at = now()
            WHERE assessment_responses.submitted = false
            """,
            (
                attempt_id,
                question_id,
                Jsonb(payload.answer) if payload.answer is not None else Jsonb(None),
                correct,
                payload.learner_confidence,
                payload.dont_know,
            ),
        )
        if not payload.dont_know:
            rating = cursor.execute(
                """
                SELECT elo_rating, uncertainty, response_count
                FROM learner_skill_ratings
                WHERE learner_id = %s AND competency_id = %s
                FOR UPDATE
                """,
                (attempt["learner_id"], expected_question["competency_id"]),
            ).fetchone()
            if not rating:
                cursor.execute(
                    """
                    INSERT INTO learner_skill_ratings
                      (learner_id, competency_id, elo_rating, uncertainty, response_count)
                    VALUES (%s, %s, 1000, 350, 0)
                    ON CONFLICT DO NOTHING
                    """,
                    (attempt["learner_id"], expected_question["competency_id"]),
                )
                rating = cursor.execute(
                    """
                    SELECT elo_rating, uncertainty, response_count
                    FROM learner_skill_ratings
                    WHERE learner_id = %s AND competency_id = %s
                    FOR UPDATE
                    """,
                    (attempt["learner_id"], expected_question["competency_id"]),
                ).fetchone()
            question_rating = cursor.execute(
                """
                SELECT elo_rating, response_count, calibration_status
                FROM assessment_questions
                WHERE id = %s
                FOR UPDATE
                """,
                (question_id,),
            ).fetchone()
            base_k = 24 if question_rating["calibration_status"] == "calibrated" else 8
            player_k = round(base_k * (0.75 + payload.learner_confidence * 0.1))
            next_player, next_question = update_elo(
                rating["elo_rating"],
                question_rating["elo_rating"],
                bool(correct),
                player_k=player_k,
                question_k=16,
            )
            next_uncertainty = update_uncertainty(
                float(rating["uncertainty"]),
                bool(correct),
                payload.learner_confidence,
            )
            cursor.execute(
                """
                UPDATE learner_skill_ratings
                SET elo_rating = %s, uncertainty = %s,
                    response_count = response_count + 1, updated_at = now()
                WHERE learner_id = %s AND competency_id = %s
                """,
                (
                    next_player,
                    next_uncertainty,
                    attempt["learner_id"],
                    expected_question["competency_id"],
                ),
            )
            cursor.execute(
                """
                UPDATE assessment_questions
                SET elo_rating = %s, response_count = response_count + 1,
                    calibration_status = CASE
                      WHEN response_count + 1 >= 10 THEN 'calibrated'
                      ELSE calibration_status
                    END
                WHERE id = %s
                """,
                (next_question, question_id),
            )
        submitted_count, estimate, _ = _attempt_metrics(cursor, attempt_id)
    return {
        "status": "saved",
        "finalized": True,
        "correct": correct,
        "dont_know": payload.dont_know,
        "answered_questions": submitted_count,
        "provisional_estimate": estimate,
        "message": (
            "I don't know was recorded without changing your skill or question rating."
            if payload.dont_know
            else "Answer recorded. Your next question adapts to your current estimate."
        ),
    }


@router.post("/assessment-attempts/{attempt_id}/events", status_code=201)
def record_assessment_event(
    attempt_id: UUID,
    payload: AssessmentEventRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        attempt = _load_attempt(cursor, attempt_id, user)
        if attempt["status"] != "in_progress":
            raise HTTPException(status_code=409, detail="Assessment attempt is no longer active")
        cursor.execute(
            """
            INSERT INTO assessment_attempt_events (attempt_id, event_type)
            VALUES (%s, %s)
            """,
            (attempt_id, payload.event_type),
        )
        if payload.event_type in {"tab_hidden", "focus_lost"}:
            cursor.execute(
                """
                UPDATE assessment_attempts
                SET integrity_flag_count = integrity_flag_count + 1
                WHERE id = %s
                """,
                (attempt_id,),
            )
    return {"status": "recorded", "effect": "review_flag_only"}


@router.post("/assessment-attempts/{attempt_id}/submit")
def submit_assessment_attempt(
    attempt_id: UUID,
    payload: AssessmentSubmitRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        attempt = _load_attempt(cursor, attempt_id, user, lock=True)
        attempt = _expire_if_needed(cursor, attempt)
        if attempt["status"] in {"submitted", "expired"}:
            return _result_payload(cursor, attempt)
        count = cursor.execute(
            """
            SELECT count(*) AS count FROM assessment_responses
            WHERE attempt_id = %s AND submitted
            """,
            (attempt_id,),
        ).fetchone()["count"]
        minimum = _effective_minimum(cursor, attempt)
        if count < minimum:
            raise HTTPException(
                status_code=409,
                detail=f"Answer at least {minimum} questions before submitting.",
            )
        if attempt["evidence_tier"] == "verified":
            practical = cursor.execute(
                """
                SELECT count(*) FILTER (WHERE ar.dont_know = false) AS count
                FROM assessment_responses ar
                JOIN assessment_questions aq ON aq.id = ar.question_id
                WHERE ar.attempt_id = %s AND ar.submitted
                  AND aq.question_type IN ('scenario', 'code_task')
                """,
                (attempt_id,),
            ).fetchone()["count"]
            if practical == 0 or len(payload.explanation) < 30:
                raise HTTPException(
                    status_code=422,
                    detail="Verified attempts require a completed practical question and a 30-character explanation.",
                )
        profile_baseline = capture_profile_baseline(cursor, attempt["learner_id"])
        cursor.execute(
            """
            UPDATE assessment_attempts
            SET status = 'submitted', submitted_at = now(), explanation = %s
            WHERE id = %s
            """,
            (payload.explanation, attempt_id),
        )
        attempt["status"] = "submitted"
        attempt["explanation"] = payload.explanation
        attempt["submitted_at"] = True
        _store_estimate(cursor, attempt)
        issue_attempt_credentials(cursor, attempt)
        update_profile_after_assessment(cursor, attempt, profile_baseline)
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'assessment_attempt_submitted', 'assessment_attempt', %s, %s)
            """,
            (
                _learner_id(user),
                attempt_id,
                Jsonb(
                    {
                        "evidence_tier": attempt["evidence_tier"],
                        "question_count": count,
                        "level_min": attempt["level_min"],
                        "level_max": attempt["level_max"],
                        "confidence": attempt["confidence"],
                    }
                ),
            ),
        )
        return _result_payload(cursor, attempt)


@router.post("/assessment-attempts/{attempt_id}/practice/{question_id}")
def answer_practice_drill(
    attempt_id: UUID,
    question_id: UUID,
    payload: AssessmentPracticeRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        attempt = _load_attempt(cursor, attempt_id, user)
        if attempt["status"] == "in_progress":
            raise HTTPException(status_code=409, detail="Finish the assessment before starting practice drills")
        question = cursor.execute(
            """
            SELECT aq.id, aq.competency_id, aq.question_type, aq.answer_key,
                   aq.explanation, comp.canonical_name AS skill_name
            FROM assessment_questions aq
            JOIN competencies comp ON comp.id = aq.competency_id
            WHERE aq.id = %s AND aq.active AND aq.moderation_status = 'approved'
              AND EXISTS (
                SELECT 1
                FROM assessment_responses missed
                JOIN assessment_questions missed_question
                  ON missed_question.id = missed.question_id
                WHERE missed.attempt_id = %s
                  AND (missed.correct IS FALSE OR missed.dont_know)
                  AND missed_question.competency_id = aq.competency_id
              )
            """,
            (question_id, attempt_id),
        ).fetchone()
        if not question:
            raise HTTPException(status_code=404, detail="Practice question not found for a weak skill")
        correct = _answer_matches(payload.answer, question["answer_key"], question["question_type"])
        cursor.execute(
            """
            INSERT INTO assessment_practice_responses (attempt_id, question_id, answer, correct)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (attempt_id, question_id) DO UPDATE
            SET answer = EXCLUDED.answer, correct = EXCLUDED.correct, attempted_at = now()
            """,
            (attempt_id, question_id, Jsonb(payload.answer), correct),
        )
    return {
        "correct": correct,
        "skill_name": question["skill_name"],
        "explanation": question["explanation"],
        "message": "Practice response recorded. It does not alter assessment Elo or credentials.",
    }


@router.post("/trainer/assessments", status_code=201)
def create_trainer_assessment(
    payload: AssessmentCreateRequest,
    trainer: UserResponse = Depends(require_role("trainer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        course = cursor.execute(
            """
            SELECT cv.id FROM course_versions cv
            JOIN courses c ON c.id = cv.course_id
            WHERE cv.id = %s AND c.trainer_id = %s
            """,
            (payload.course_version_id, _learner_id(trainer)),
        ).fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="Course version not found for this trainer")
        assessment = cursor.execute(
            """
            INSERT INTO assessments
              (course_version_id, title, time_limit_minutes, min_questions, max_questions, target_level)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                payload.course_version_id,
                payload.title,
                payload.time_limit_minutes,
                payload.min_questions,
                payload.max_questions,
                payload.target_level,
            ),
        ).fetchone()
    return {"assessment_id": str(assessment["id"]), "status": "created"}


@router.get("/trainer/assessments/courses")
def trainer_assessment_courses(
    trainer: UserResponse = Depends(require_role("trainer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, str]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT cv.id, cv.title, cv.version
            FROM course_versions cv
            JOIN courses c ON c.id = cv.course_id
            WHERE c.trainer_id = %s AND cv.status = 'published'
              AND EXISTS (
                SELECT 1 FROM course_approval_requests car
                WHERE car.course_version_id = cv.id AND car.status = 'approved'
              )
            ORDER BY cv.title, cv.version
            """,
            (_learner_id(trainer),),
        ).fetchall()
    return [
        {"course_version_id": str(row["id"]), "title": row["title"], "version": row["version"]}
        for row in rows
    ]


@router.get("/trainer/assessments")
def list_trainer_assessments(
    trainer: UserResponse = Depends(require_role("trainer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT a.id, a.course_version_id, cv.title AS course_title,
                   a.title, a.min_questions, a.max_questions,
                   a.target_level, a.time_limit_minutes,
                   count(aq.id)::integer AS question_count,
                   count(aq.id) FILTER (
                     WHERE aq.moderation_status = 'approved'
                   )::integer AS approved_question_count,
                   count(aq.id) FILTER (
                     WHERE aq.moderation_status = 'pending'
                   )::integer AS pending_question_count
            FROM assessments a
            JOIN course_versions cv ON cv.id = a.course_version_id
            JOIN courses c ON c.id = cv.course_id
            LEFT JOIN assessment_questions aq ON aq.assessment_id = a.id
            WHERE c.trainer_id = %s
            GROUP BY a.id, cv.title
            ORDER BY cv.title, a.title
            """,
            (_learner_id(trainer),),
        ).fetchall()
    return [
        {
            **row,
            "id": str(row["id"]),
            "course_version_id": str(row["course_version_id"]),
        }
        for row in rows
    ]


@router.get("/trainer/assessments/{assessment_id}/competencies")
def trainer_assessment_competencies(
    assessment_id: UUID,
    trainer: UserResponse = Depends(require_role("trainer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, str]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        owned = cursor.execute(
            """
            SELECT cv.id FROM assessments a
            JOIN course_versions cv ON cv.id = a.course_version_id
            JOIN courses c ON c.id = cv.course_id
            WHERE a.id = %s AND c.trainer_id = %s
            """,
            (assessment_id, _learner_id(trainer)),
        ).fetchone()
        if not owned:
            raise HTTPException(status_code=404, detail="Assessment not found for this trainer")
        rows = cursor.execute(
            """
            SELECT DISTINCT comp.id, comp.canonical_name
            FROM course_version_competencies cvc
            JOIN competencies comp ON comp.id = cvc.competency_id
            WHERE cvc.course_version_id = %s
            ORDER BY comp.canonical_name
            """,
            (owned["id"],),
        ).fetchall()
    return [
        {"competency_id": str(row["id"]), "skill_name": row["canonical_name"]}
        for row in rows
    ]


@router.post("/trainer/assessments/{assessment_id}/questions", status_code=201)
def create_assessment_question(
    assessment_id: UUID,
    payload: AssessmentQuestionRequest,
    trainer: UserResponse = Depends(require_role("trainer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        owned = cursor.execute(
            """
            SELECT a.id
            FROM assessments a
            JOIN course_versions cv ON cv.id = a.course_version_id
            JOIN courses c ON c.id = cv.course_id
            WHERE a.id = %s AND c.trainer_id = %s
            """,
            (assessment_id, _learner_id(trainer)),
        ).fetchone()
        if not owned:
            raise HTTPException(status_code=404, detail="Assessment not found for this trainer")
        competency = cursor.execute(
            """
            SELECT comp.id
            FROM assessments a
            JOIN course_version_competencies cvc
              ON cvc.course_version_id = a.course_version_id
            JOIN competencies comp ON comp.id = cvc.competency_id
            WHERE a.id = %s AND comp.id = %s AND comp.active = true
            """,
            (assessment_id, payload.competency_id),
        ).fetchone()
        if not competency:
            raise HTTPException(status_code=404, detail="Competency not found")
        initial_rating = 700 + payload.difficulty_level * 100
        row = cursor.execute(
            """
            INSERT INTO assessment_questions
              (assessment_id, competency_id, prompt, answer_key, difficulty_level,
               elo_rating, question_type, options, explanation, estimated_time_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                assessment_id,
                payload.competency_id,
                payload.prompt,
                Jsonb(payload.answer_key),
                payload.difficulty_level,
                initial_rating,
                payload.question_type,
                Jsonb(payload.options),
                payload.explanation,
                payload.estimated_time_seconds,
            ),
        ).fetchone()
    return {
        "question_id": str(row["id"]),
        "moderation_status": "pending",
        "message": "An admin must approve this question before it appears in an assessment.",
    }


@router.get("/admin/assessment-questions")
def list_assessment_question_queue(
    _: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT aq.id, aq.assessment_id, a.title AS assessment_title,
                   aq.competency_id, comp.canonical_name AS skill_name,
                   aq.question_type, aq.prompt, aq.options, aq.difficulty_level,
                   aq.answer_key, aq.elo_rating, aq.calibration_status, aq.explanation,
                   aq.estimated_time_seconds, aq.moderation_status
            FROM assessment_questions aq
            JOIN assessments a ON a.id = aq.assessment_id
            JOIN competencies comp ON comp.id = aq.competency_id
            WHERE aq.moderation_status = 'pending'
            ORDER BY aq.id
            """
        ).fetchall()
    return [{**row, "id": str(row["id"]), "assessment_id": str(row["assessment_id"]),
             "competency_id": str(row["competency_id"])} for row in rows]


@router.post("/admin/assessment-questions/{question_id}/decision")
def moderate_assessment_question(
    question_id: UUID,
    payload: AssessmentQuestionDecisionRequest,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """
            UPDATE assessment_questions
            SET moderation_status = %s, moderated_by = %s,
                moderation_note = %s, moderated_at = now()
            WHERE id = %s AND moderation_status = 'pending'
            RETURNING id
            """,
            (
                payload.decision,
                _learner_id(admin),
                payload.moderation_note,
                question_id,
            ),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Pending assessment question not found")
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'assessment_question_moderated',
                    'assessment_question', %s, %s)
            """,
            (
                _learner_id(admin),
                question_id,
                Jsonb(
                    {
                        "decision": payload.decision,
                        "moderation_note": payload.moderation_note,
                    }
                ),
            ),
        )
    return {"question_id": str(question_id), "moderation_status": payload.decision}


@router.get("/admin/assessment-policy")
def get_assessment_policy(
    _: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, int]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "SELECT attempts_per_week FROM assessment_policy WHERE singleton = true"
        ).fetchone()
    return row


@router.put("/admin/assessment-policy")
def update_assessment_policy(
    payload: AssessmentPolicyRequest,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, int]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """
            UPDATE assessment_policy
            SET attempts_per_week = %s, updated_by = %s, updated_at = now()
            WHERE singleton = true
            RETURNING attempts_per_week
            """,
            (payload.attempts_per_week, _learner_id(admin)),
        ).fetchone()
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, details)
            VALUES (%s, 'assessment_policy_updated', 'assessment_policy', %s)
            """,
            (
                _learner_id(admin),
                Jsonb({"attempts_per_week": payload.attempts_per_week}),
            ),
        )
    return row


@router.post("/assessment/audit-code")
def audit_code_security(
    payload: dict[str, Any],
    user: UserResponse = Depends(require_role("trainee")),
) -> dict[str, Any]:
    """
    Validates input and output functions using VulnLLM-R reasoning and CWE security rules.
    Audits for SQL injection (CWE-89), XSS (CWE-79), Path Traversal (CWE-22), and info leaks (CWE-200).
    """
    from app.services.vulnllm_validator import audit_code_with_vulnllm_r

    code = payload.get("code", "").strip()
    target_name = payload.get("target_name", "Submitted Function")
    if not code:
        raise HTTPException(status_code=422, detail="Provide 'code' to audit.")

    report = audit_code_with_vulnllm_r(code, target_name=target_name)
    return report.to_dict()

