import hashlib
import math
import secrets
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.v1.auth import current_user, require_role
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.schemas.courses import (
    CheckpointAnswerRequest,
    CourseEnrollmentRequest,
    DiscussionPostRequest,
    LearningSubmissionRequest,
    LessonHeartbeatRequest,
    LessonNotesRequest,
    SponsorshipCodeRequest,
    SubmissionDecisionRequest,
)

router = APIRouter(prefix="/api/v1", tags=["Enroll and learn"])


def _get_enrollment(
    cursor: psycopg.Cursor,
    enrollment_id: UUID,
    user: UserResponse,
    *,
    lock: bool = False,
) -> dict[str, Any]:
    row = cursor.execute(
        f"""
        SELECT e.id, e.learner_id, e.course_version_id, e.status, e.funding_type,
               e.enrolled_at, cv.title AS course_title, c.trainer_id
        FROM enrollments e
        JOIN course_versions cv ON cv.id = e.course_version_id
        JOIN courses c ON c.id = cv.course_id
        WHERE e.id = %s
        {"FOR UPDATE OF e" if lock else ""}
        """,
        (enrollment_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    if user.id not in {str(row["learner_id"]), str(row["trainer_id"])} and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="You cannot access this enrollment")
    if row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="This enrollment has been cancelled")
    return row


def _get_lesson_for_enrollment(
    cursor: psycopg.Cursor, enrollment: dict[str, Any], lesson_id: UUID
) -> dict[str, Any]:
    lesson = cursor.execute(
        """
        SELECT id, title, content, content_ref, sort_order, duration_seconds,
               assessment_required
        FROM lessons
        WHERE id = %s AND course_version_id = %s
        """,
        (lesson_id, enrollment["course_version_id"]),
    ).fetchone()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found in this course")
    return lesson


def _checkpoint_question(question: Any) -> tuple[dict[str, Any], Any]:
    if not isinstance(question, dict):
        raise HTTPException(status_code=409, detail="This checkpoint is not configured correctly")
    answer_key = next(
        (
            question[key]
            for key in ("answer_key", "correct_answer", "answer")
            if key in question
        ),
        None,
    )
    if answer_key is None:
        raise HTTPException(status_code=409, detail="This checkpoint has no answer key")
    safe_keys = {"prompt", "question", "text", "options", "type"}
    public_question = {key: question[key] for key in safe_keys if key in question}
    return public_question, answer_key


def _refresh_lesson_completion(
    cursor: psycopg.Cursor, enrollment_id: UUID, lesson: dict[str, Any]
) -> bool:
    progress = cursor.execute(
        """
        SELECT active_seconds, completed_at
        FROM lesson_progress
        WHERE enrollment_id = %s AND lesson_id = %s
        FOR UPDATE
        """,
        (enrollment_id, lesson["id"]),
    ).fetchone()
    if not progress:
        return False
    checkpoint_count = cursor.execute(
        "SELECT count(*) AS count FROM lesson_checkpoints WHERE lesson_id = %s",
        (lesson["id"],),
    ).fetchone()["count"]
    required_answers = min(3, checkpoint_count)
    answered_count = cursor.execute(
        """
        SELECT count(DISTINCT checkpoint_id) AS count
        FROM checkpoint_attempts
        WHERE learner_id = (
          SELECT learner_id FROM enrollments WHERE id = %s
        )
        AND checkpoint_id IN (
          SELECT id FROM lesson_checkpoints WHERE lesson_id = %s
        )
        """,
        (enrollment_id, lesson["id"]),
    ).fetchone()["count"]
    enough_viewing = progress["active_seconds"] >= max(
        1, math.ceil(lesson["duration_seconds"] * 0.8)
    )
    enough_answers = (
        not lesson["assessment_required"]
        or (checkpoint_count >= 2 and answered_count >= required_answers)
    )
    if enough_viewing and enough_answers and progress["completed_at"] is None:
        cursor.execute(
            """
            UPDATE lesson_progress
            SET completed_at = now(), updated_at = now()
            WHERE enrollment_id = %s AND lesson_id = %s
            """,
            (enrollment_id, lesson["id"]),
        )
        cursor.execute(
            """
            UPDATE enrollments e
            SET status = 'completed', completed_at = now()
            WHERE e.id = %s
              AND NOT EXISTS (
                SELECT 1 FROM lessons l
                LEFT JOIN lesson_progress lp
                  ON lp.lesson_id = l.id AND lp.enrollment_id = e.id
                WHERE l.course_version_id = e.course_version_id
                  AND lp.completed_at IS NULL
              )
              AND EXISTS (
                SELECT 1 FROM lessons l WHERE l.course_version_id = e.course_version_id
              )
            """,
            (enrollment_id,),
        )
    return bool(enough_viewing and enough_answers)


@router.post("/courses/{course_version_id}/enroll", status_code=201)
def enroll_in_course(
    course_version_id: UUID,
    payload: CourseEnrollmentRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        course = cursor.execute(
            """
            SELECT cv.id, cv.title, cv.price_cents
            FROM course_versions cv
            WHERE cv.id = %s
              AND cv.status = 'published'
              AND EXISTS (
                SELECT 1 FROM course_approval_requests car
                WHERE car.course_version_id = cv.id AND car.status = 'approved'
              )
            """,
            (course_version_id,),
        ).fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="Approved published course not found")

        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{learner_id}:{course_version_id}",),
        )
        existing = cursor.execute(
            """
            SELECT id, status, funding_type FROM enrollments
            WHERE learner_id = %s AND course_version_id = %s
            FOR UPDATE
            """,
            (learner_id, course_version_id),
        ).fetchone()
        if existing and existing["status"] != "cancelled":
            return {
                "enrollment_id": str(existing["id"]),
                "course_title": course["title"],
                "status": existing["status"],
                "funding_type": existing["funding_type"],
            }

        prerequisites = cursor.execute(
            """
            SELECT comp.canonical_name AS skill_name, cp.minimum_level,
                   COALESCE(lc.level, 0) AS current_level
            FROM course_prerequisites cp
            JOIN competencies comp ON comp.id = cp.prerequisite_competency_id
            LEFT JOIN learner_competencies lc
              ON lc.user_id = %s AND lc.competency_id = cp.prerequisite_competency_id
            WHERE cp.course_version_id = %s
              AND COALESCE(lc.level, 0) < cp.minimum_level
            """,
            (learner_id, course_version_id),
        ).fetchall()
        if prerequisites and not payload.acknowledge_prerequisites:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Review or acknowledge the unmet prerequisites before enrolling.",
                    "prerequisites": prerequisites,
                },
            )

        if payload.sponsorship_code:
            code_hash = hashlib.sha256(payload.sponsorship_code.encode()).hexdigest()
            code = cursor.execute(
                """
                SELECT id, max_uses, expires_at
                FROM learning_sponsorship_codes
                WHERE code_hash = %s AND active = true
                  AND (course_version_id IS NULL OR course_version_id = %s)
                  AND (expires_at IS NULL OR expires_at > now())
                FOR UPDATE
                """,
                (code_hash, course_version_id),
            ).fetchone()
            if not code:
                raise HTTPException(status_code=422, detail="Sponsorship code is invalid or expired")
            redeemed = cursor.execute(
                """
                SELECT count(*) AS count
                FROM learning_sponsorship_redemptions
                WHERE code_id = %s
                """,
                (code["id"],),
            ).fetchone()["count"]
            already_redeemed = cursor.execute(
                """
                SELECT 1 FROM learning_sponsorship_redemptions
                WHERE code_id = %s AND learner_id = %s
                """,
                (code["id"], learner_id),
            ).fetchone()
            if redeemed >= code["max_uses"] and not already_redeemed:
                raise HTTPException(status_code=409, detail="Sponsorship code has no seats remaining")
            funding_type = "sponsored"
            code_id = code["id"]
        else:
            if course["price_cents"] > 0:
                raise HTTPException(
                    status_code=503,
                    detail="Paid checkout is not configured. Use a valid sponsorship code or choose a free course.",
                )
            funding_type = "free"
            code_id = None

        if existing:
            cursor.execute(
                "DELETE FROM learning_sponsorship_redemptions WHERE enrollment_id = %s",
                (existing["id"],),
            )
            enrollment = cursor.execute(
                """
                UPDATE enrollments
                SET status = 'active', completed_at = NULL, enrolled_at = now(),
                    funding_type = %s, sponsorship_code_id = %s
                WHERE id = %s
                RETURNING id
                """,
                (funding_type, code_id, existing["id"]),
            ).fetchone()
        else:
            enrollment = cursor.execute(
                """
                INSERT INTO enrollments
                  (learner_id, course_version_id, funding_type, sponsorship_code_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (learner_id, course_version_id, funding_type, code_id),
            ).fetchone()
        if code_id:
            cursor.execute(
                """
                INSERT INTO learning_sponsorship_redemptions
                  (code_id, enrollment_id, learner_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (code_id, learner_id)
                DO UPDATE SET enrollment_id = EXCLUDED.enrollment_id,
                              redeemed_at = now()
                """,
                (code_id, enrollment["id"], learner_id),
            )
        return {
            "enrollment_id": str(enrollment["id"]),
            "course_title": course["title"],
            "status": "active",
            "funding_type": funding_type,
        }


@router.get("/learning/enrollments")
def list_my_enrollments(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT e.id, e.course_version_id, e.status, e.funding_type,
                   e.enrolled_at, e.completed_at, cv.title AS course_title,
                   cv.description, cv.version,
                   count(DISTINCT l.id)::integer AS lesson_count,
                   (count(DISTINCT lp.lesson_id) FILTER
                     (WHERE lp.completed_at IS NOT NULL))::integer AS completed_lessons,
                   max(lp.updated_at) AS last_activity
            FROM enrollments e
            JOIN course_versions cv ON cv.id = e.course_version_id
            LEFT JOIN lessons l ON l.course_version_id = cv.id
            LEFT JOIN lesson_progress lp
              ON lp.lesson_id = l.id AND lp.enrollment_id = e.id
            WHERE e.learner_id = %s AND e.status != 'cancelled'
            GROUP BY e.id, cv.id
            ORDER BY e.enrolled_at DESC
            """,
            (UUID(user.id),),
        ).fetchall()
    return [
        {
            **row,
            "id": str(row["id"]),
            "course_version_id": str(row["course_version_id"]),
            "enrolled_at": row["enrolled_at"].isoformat(),
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            "last_activity": row["last_activity"].isoformat() if row["last_activity"] else None,
            "progress_percent": (
                round(row["completed_lessons"] * 100 / row["lesson_count"])
                if row["lesson_count"]
                else 0
            ),
        }
        for row in rows
    ]


@router.get("/learning/enrollments/{enrollment_id}")
def get_learning_course(
    enrollment_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        enrollment = _get_enrollment(cursor, enrollment_id, user)
        lessons = cursor.execute(
            """
            SELECT l.id, l.title, l.sort_order, l.duration_seconds,
                   l.assessment_required,
                   COALESCE(lp.last_position_seconds, 0) AS last_position_seconds,
                   COALESCE(lp.active_seconds, 0) AS active_seconds,
                   (lp.completed_at IS NOT NULL) AS completed,
                   count(DISTINCT lc.id)::integer AS checkpoint_count,
                   count(DISTINCT ca.checkpoint_id)::integer AS answered_checkpoints
            FROM lessons l
            LEFT JOIN lesson_progress lp
              ON lp.lesson_id = l.id AND lp.enrollment_id = %s
            LEFT JOIN lesson_checkpoints lc ON lc.lesson_id = l.id
            LEFT JOIN checkpoint_attempts ca
              ON ca.checkpoint_id = lc.id AND ca.learner_id = %s
            WHERE l.course_version_id = %s
            GROUP BY l.id, lp.last_position_seconds, lp.active_seconds, lp.completed_at
            ORDER BY l.sort_order
            """,
            (enrollment_id, UUID(user.id), enrollment["course_version_id"]),
        ).fetchall()
        lesson_payload = [
            {
                **lesson,
                "id": str(lesson["id"]),
                "required_answers": min(3, lesson["checkpoint_count"]),
            }
            for lesson in lessons
        ]
        total = len(lesson_payload)
        completed = sum(1 for lesson in lesson_payload if lesson["completed"])
    return {
        "enrollment_id": str(enrollment["id"]),
        "course_version_id": str(enrollment["course_version_id"]),
        "course_title": enrollment["course_title"],
        "status": enrollment["status"],
        "funding_type": enrollment["funding_type"],
        "lessons": lesson_payload,
        "progress_percent": round(completed * 100 / total) if total else 0,
        "assessment_unlocked": total > 0 and completed == total,
        "assessment_message": (
            "Stage 5 assessment unlocks after all required lessons are complete."
            if total > 0 and completed == total
            else "Complete all required lessons to unlock the Stage 5 assessment."
        ),
    }


@router.get("/learning/enrollments/{enrollment_id}/lessons/{lesson_id}")
def get_lesson(
    enrollment_id: UUID,
    lesson_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        enrollment = _get_enrollment(cursor, enrollment_id, user)
        lesson = _get_lesson_for_enrollment(cursor, enrollment, lesson_id)
        progress = cursor.execute(
            """
            SELECT last_position_seconds, active_seconds, notes, completed_at
            FROM lesson_progress
            WHERE enrollment_id = %s AND lesson_id = %s
            """,
            (enrollment_id, lesson_id),
        ).fetchone()
        rows = cursor.execute(
            """
            SELECT id, question, sort_order
            FROM lesson_checkpoints
            WHERE lesson_id = %s
            ORDER BY sort_order, id
            LIMIT 3
            """,
            (lesson_id,),
        ).fetchall()
        checkpoints = []
        for row in rows:
            question, _ = _checkpoint_question(row["question"])
            answer = cursor.execute(
                """
                SELECT correct FROM checkpoint_attempts
                WHERE learner_id = %s AND checkpoint_id = %s
                ORDER BY answered_at DESC LIMIT 1
                """,
                (UUID(user.id), row["id"]),
            ).fetchone()
            checkpoints.append(
                {
                    "id": str(row["id"]),
                    "question": question,
                    "answered": answer is not None,
                    "correct": answer["correct"] if answer else None,
                }
            )
        if lesson["assessment_required"] and not 2 <= len(checkpoints) <= 3:
            raise HTTPException(
                status_code=409,
                detail="This lesson needs two or three checkpoints before it can be opened.",
            )
        return {
            **lesson,
            "id": str(lesson["id"]),
            "enrollment_id": str(enrollment_id),
            "last_position_seconds": progress["last_position_seconds"] if progress else 0,
            "active_seconds": progress["active_seconds"] if progress else 0,
            "notes": progress["notes"] if progress else "",
            "completed": bool(progress and progress["completed_at"]),
            "checkpoints": checkpoints,
            "required_view_seconds": max(1, math.ceil(lesson["duration_seconds"] * 0.8)),
        }


@router.post("/learning/enrollments/{enrollment_id}/lessons/{lesson_id}/heartbeat")
def update_lesson_progress(
    enrollment_id: UUID,
    lesson_id: UUID,
    payload: LessonHeartbeatRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        enrollment = _get_enrollment(cursor, enrollment_id, user)
        lesson = _get_lesson_for_enrollment(cursor, enrollment, lesson_id)
        cursor.execute(
            """
            INSERT INTO lesson_progress
              (enrollment_id, lesson_id, last_position_seconds, active_seconds, last_heartbeat_at)
            VALUES (%s, %s, 0, 0, now())
            ON CONFLICT (enrollment_id, lesson_id) DO UPDATE
            SET active_seconds = lesson_progress.active_seconds + CASE
                  WHEN now() - lesson_progress.last_heartbeat_at
                    BETWEEN interval '10 seconds' AND interval '30 seconds'
                  THEN floor(extract(epoch FROM (now() - lesson_progress.last_heartbeat_at)))::integer
                  ELSE 0
                END,
                last_position_seconds = LEAST(
                  %s,
                  GREATEST(
                    lesson_progress.last_position_seconds,
                    LEAST(
                      %s,
                      lesson_progress.last_position_seconds + CASE
                        WHEN now() - lesson_progress.last_heartbeat_at
                          BETWEEN interval '10 seconds' AND interval '30 seconds'
                        THEN floor(extract(epoch FROM (now() - lesson_progress.last_heartbeat_at)))::integer
                        ELSE 0
                      END
                    )
                  )
                ),
                last_heartbeat_at = now(),
                updated_at = now()
            """,
            (
                enrollment_id,
                lesson_id,
                lesson["duration_seconds"],
                min(payload.last_position_seconds, lesson["duration_seconds"]),
            ),
        )
        completed = _refresh_lesson_completion(cursor, enrollment_id, lesson)
        progress = cursor.execute(
            """
            SELECT last_position_seconds, active_seconds
            FROM lesson_progress
            WHERE enrollment_id = %s AND lesson_id = %s
            """,
            (enrollment_id, lesson_id),
        ).fetchone()
    return {**progress, "completed": completed}


@router.put("/learning/enrollments/{enrollment_id}/lessons/{lesson_id}/notes")
def save_lesson_notes(
    enrollment_id: UUID,
    lesson_id: UUID,
    payload: LessonNotesRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        enrollment = _get_enrollment(cursor, enrollment_id, user)
        _get_lesson_for_enrollment(cursor, enrollment, lesson_id)
        cursor.execute(
            """
            INSERT INTO lesson_progress (enrollment_id, lesson_id, notes)
            VALUES (%s, %s, %s)
            ON CONFLICT (enrollment_id, lesson_id) DO UPDATE
            SET notes = EXCLUDED.notes, updated_at = now()
            """,
            (enrollment_id, lesson_id, payload.notes),
        )
    return {"status": "saved"}


@router.post(
    "/learning/enrollments/{enrollment_id}/lessons/{lesson_id}/checkpoints/{checkpoint_id}"
)
def answer_checkpoint(
    enrollment_id: UUID,
    lesson_id: UUID,
    checkpoint_id: UUID,
    payload: CheckpointAnswerRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, bool]:
    with connection.cursor(row_factory=dict_row) as cursor:
        enrollment = _get_enrollment(cursor, enrollment_id, user)
        lesson = _get_lesson_for_enrollment(cursor, enrollment, lesson_id)
        checkpoint = cursor.execute(
            """
            SELECT question FROM lesson_checkpoints
            WHERE id = %s AND lesson_id = %s
            """,
            (checkpoint_id, lesson_id),
        ).fetchone()
        if not checkpoint:
            raise HTTPException(status_code=404, detail="Checkpoint not found")
        _, expected = _checkpoint_question(checkpoint["question"])
        correct = payload.answer == expected
        cursor.execute(
            """
            INSERT INTO checkpoint_attempts
              (learner_id, checkpoint_id, answer, correct)
            VALUES (%s, %s, %s, %s)
            """,
            (UUID(user.id), checkpoint_id, Jsonb({"answer": payload.answer}), correct),
        )
        completed = _refresh_lesson_completion(cursor, enrollment_id, lesson)
    return {"correct": correct, "lesson_completed": completed}


@router.post("/learning/enrollments/{enrollment_id}/submissions", status_code=201)
def submit_learning_work(
    enrollment_id: UUID,
    payload: LearningSubmissionRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        enrollment = _get_enrollment(cursor, enrollment_id, user)
        if payload.lesson_id:
            _get_lesson_for_enrollment(cursor, enrollment, payload.lesson_id)
        if not payload.submission_url and not payload.submission_text:
            raise HTTPException(status_code=422, detail="Provide a project link or written submission")
        row = cursor.execute(
            """
            INSERT INTO learning_submissions
              (enrollment_id, lesson_id, learner_id, submission_type, title,
               submission_url, submission_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                enrollment_id,
                payload.lesson_id,
                UUID(user.id),
                payload.submission_type,
                payload.title.strip(),
                str(payload.submission_url) if payload.submission_url else None,
                payload.submission_text,
            ),
        ).fetchone()
    return {"submission_id": str(row["id"]), "status": "submitted"}


@router.get("/learning/enrollments/{enrollment_id}/submissions")
def list_learning_work(
    enrollment_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        _get_enrollment(cursor, enrollment_id, user)
        rows = cursor.execute(
            """
            SELECT id, lesson_id, submission_type, title, submission_url,
                   submission_text, status, trainer_feedback, submitted_at, reviewed_at
            FROM learning_submissions
            WHERE enrollment_id = %s AND learner_id = %s
            ORDER BY submitted_at DESC
            """,
            (enrollment_id, UUID(user.id)),
        ).fetchall()
    return [
        {
            **row,
            "id": str(row["id"]),
            "lesson_id": str(row["lesson_id"]) if row["lesson_id"] else None,
            "submitted_at": row["submitted_at"].isoformat(),
            "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
        }
        for row in rows
    ]


@router.get("/learning/enrollments/{enrollment_id}/discussion")
def list_discussion(
    enrollment_id: UUID,
    user: UserResponse = Depends(current_user),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        _get_enrollment(cursor, enrollment_id, user)
        rows = cursor.execute(
            """
            SELECT d.id, d.parent_id, d.author_id, u.email AS author,
                   d.body, d.created_at,
                   CASE WHEN d.author_id = %s THEN 'you' ELSE 'course team' END AS author_role
            FROM learning_discussions d
            JOIN users u ON u.id = d.author_id
            WHERE d.enrollment_id = %s
            ORDER BY d.created_at
            """,
            (UUID(user.id), enrollment_id),
        ).fetchall()
    return [
        {
            **row,
            "id": str(row["id"]),
            "parent_id": str(row["parent_id"]) if row["parent_id"] else None,
            "author_id": str(row["author_id"]),
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


@router.post("/learning/enrollments/{enrollment_id}/discussion", status_code=201)
def post_discussion(
    enrollment_id: UUID,
    payload: DiscussionPostRequest,
    user: UserResponse = Depends(current_user),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        enrollment = _get_enrollment(cursor, enrollment_id, user)
        if payload.parent_id:
            parent = cursor.execute(
                """
                SELECT id, author_id FROM learning_discussions
                WHERE id = %s AND enrollment_id = %s
                """,
                (payload.parent_id, enrollment_id),
            ).fetchone()
            if not parent:
                raise HTTPException(status_code=404, detail="Discussion message not found")
            if str(enrollment["trainer_id"]) != user.id:
                raise HTTPException(status_code=403, detail="Only the course trainer can reply to a question")
            if str(parent["author_id"]) != str(enrollment["learner_id"]):
                raise HTTPException(status_code=409, detail="Trainer replies must attach to the learner's original question")
        elif str(enrollment["learner_id"]) != user.id:
            raise HTTPException(status_code=422, detail="Trainer replies must refer to a learner question")
        row = cursor.execute(
            """
            INSERT INTO learning_discussions (enrollment_id, author_id, parent_id, body)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (enrollment_id, UUID(user.id), payload.parent_id, payload.body),
        ).fetchone()
    return {"message_id": str(row["id"]), "status": "posted"}


@router.get("/trainer/learning/submissions")
def trainer_submissions(
    trainer: UserResponse = Depends(require_role("trainer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT s.id, s.enrollment_id, s.learner_id, learner.email AS learner,
                   cv.title AS course_title, s.submission_type, s.title,
                   s.submission_url, s.submission_text, s.status, s.submitted_at
            FROM learning_submissions s
            JOIN enrollments e ON e.id = s.enrollment_id
            JOIN course_versions cv ON cv.id = e.course_version_id
            JOIN courses c ON c.id = cv.course_id
            JOIN users learner ON learner.id = s.learner_id
            WHERE c.trainer_id = %s AND s.status = 'submitted'
            ORDER BY s.submitted_at
            """,
            (UUID(trainer.id),),
        ).fetchall()
    return [
        {
            **row,
            "id": str(row["id"]),
            "enrollment_id": str(row["enrollment_id"]),
            "learner_id": str(row["learner_id"]),
            "submitted_at": row["submitted_at"].isoformat(),
        }
        for row in rows
    ]


@router.get("/trainer/learning/discussion")
def trainer_discussion_questions(
    trainer: UserResponse = Depends(require_role("trainer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT d.id, d.enrollment_id, e.learner_id, learner.email AS learner,
                   cv.title AS course_title, d.body, d.created_at
            FROM learning_discussions d
            JOIN enrollments e ON e.id = d.enrollment_id
            JOIN course_versions cv ON cv.id = e.course_version_id
            JOIN courses c ON c.id = cv.course_id
            JOIN users learner ON learner.id = e.learner_id
            WHERE c.trainer_id = %s
              AND d.parent_id IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM learning_discussions reply
                WHERE reply.parent_id = d.id
              )
            ORDER BY d.created_at
            """,
            (UUID(trainer.id),),
        ).fetchall()
    return [
        {
            **row,
            "id": str(row["id"]),
            "enrollment_id": str(row["enrollment_id"]),
            "learner_id": str(row["learner_id"]),
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


@router.post("/trainer/learning/submissions/{submission_id}/decision")
def decide_learning_submission(
    submission_id: UUID,
    payload: SubmissionDecisionRequest,
    trainer: UserResponse = Depends(require_role("trainer")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        submission = cursor.execute(
            """
            SELECT s.id, s.status
            FROM learning_submissions s
            JOIN enrollments e ON e.id = s.enrollment_id
            JOIN course_versions cv ON cv.id = e.course_version_id
            JOIN courses c ON c.id = cv.course_id
            WHERE s.id = %s AND c.trainer_id = %s
            FOR UPDATE OF s
            """,
            (submission_id, UUID(trainer.id)),
        ).fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        if submission["status"] != "submitted":
            raise HTTPException(status_code=409, detail="Submission has already been reviewed")
        cursor.execute(
            """
            UPDATE learning_submissions
            SET status = %s, trainer_feedback = %s, reviewed_by = %s, reviewed_at = now()
            WHERE id = %s
            """,
            (payload.decision, payload.trainer_feedback, UUID(trainer.id), submission_id),
        )
    return {"submission_id": str(submission_id), "status": payload.decision}


@router.post("/admin/learning/sponsorship-codes", status_code=201)
def create_sponsorship_code(
    payload: SponsorshipCodeRequest,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    raw_code = secrets.token_urlsafe(18).replace("-", "").replace("_", "").upper()
    code_hash = hashlib.sha256(raw_code.encode()).hexdigest()
    with connection.cursor(row_factory=dict_row) as cursor:
        if payload.course_version_id:
            course = cursor.execute(
                """
                SELECT 1 FROM course_versions
                WHERE id = %s AND status = 'published'
                  AND EXISTS (
                    SELECT 1 FROM course_approval_requests car
                    WHERE car.course_version_id = course_versions.id
                      AND car.status = 'approved'
                  )
                """,
                (payload.course_version_id,),
            ).fetchone()
            if not course:
                raise HTTPException(status_code=404, detail="Published course version not found")
        row = cursor.execute(
            """
            INSERT INTO learning_sponsorship_codes
              (code_hash, code_hint, course_version_id, max_uses, expires_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, max_uses, expires_at
            """,
            (
                code_hash,
                raw_code[-4:],
                payload.course_version_id,
                payload.max_uses,
                payload.expires_at,
                UUID(admin.id),
            ),
        ).fetchone()
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'learning_sponsorship_code_created',
                    'learning_sponsorship_code', %s, %s)
            """,
            (
                UUID(admin.id),
                row["id"],
                Jsonb(
                    {
                        "course_version_id": (
                            str(payload.course_version_id)
                            if payload.course_version_id
                            else None
                        ),
                        "max_uses": payload.max_uses,
                        "expires_at": (
                            payload.expires_at.isoformat()
                            if payload.expires_at
                            else None
                        ),
                        "code_hint": raw_code[-4:],
                    }
                ),
            ),
        )
    return {
        "id": str(row["id"]),
        "code": raw_code,
        "max_uses": row["max_uses"],
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "message": "Copy this code now; it is not stored in recoverable form.",
    }
