from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.v1.auth import current_user, require_role
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.schemas.courses import (
    CompareCoursesRequest,
    ExternalCompletionDecision,
    ExternalCompletionRequest,
    ExternalCourseRequest,
    LearningPreferencesRequest,
    WishlistRequest,
)
from app.services.course_recommendations import (
    RoleGap,
    affordability_order,
    reason_summary,
    score_course,
)

router = APIRouter(prefix="/api/v1", tags=["AI course picks"])
PROVIDER_DOMAINS = {
    "coursera.org",
    "udemy.com",
    "edx.org",
    "stepik.org",
    "khanacademy.org",
    "pluralsight.com",
    "linkedin.com",
}


def _get_preferences(cursor: psycopg.Cursor, user_id: UUID) -> dict[str, object]:
    row = cursor.execute(
        """
        SELECT weekly_study_hours, budget_cents, learning_format, prioritize_paid
        FROM learner_preferences
        WHERE user_id = %s
        """,
        (user_id,),
    ).fetchone()
    if row:
        return row
    return {
        "weekly_study_hours": None,
        "budget_cents": None,
        "learning_format": "self_paced",
        "prioritize_paid": False,
    }


def _role_gaps(
    cursor: psycopg.Cursor, user_id: UUID
) -> tuple[list[RoleGap], list[dict[str, str]]]:
    targets = cursor.execute(
        """
        SELECT r.id, r.name
        FROM learner_target_roles tr
        JOIN role_catalog r ON r.id = tr.role_id
        WHERE tr.user_id = %s AND r.active = true
        ORDER BY r.name
        """,
        (user_id,),
    ).fetchall()
    if not targets:
        return [], []

    role_ids = [row["id"] for row in targets]
    requirements = cursor.execute(
        """
        SELECT r.id AS role_id, r.name AS role_name, c.id AS competency_id,
               c.canonical_name AS skill_name, rc.required_level,
               rc.importance, COALESCE(lc.level, 0) AS current_level
        FROM role_competencies rc
        JOIN role_catalog r ON r.id = rc.role_id
        JOIN competencies c ON c.id = rc.competency_id
        LEFT JOIN learner_competencies lc
          ON lc.user_id = %s AND lc.competency_id = c.id
        WHERE rc.role_id = ANY(%s) AND r.active = true
        ORDER BY r.name, rc.importance DESC
        """,
        (user_id, role_ids),
    ).fetchall()
    gaps = [
        RoleGap(
            role_id=str(row["role_id"]),
            role_name=row["role_name"],
            competency_id=str(row["competency_id"]),
            skill_name=row["skill_name"],
            current_level=int(row["current_level"]),
            required_level=row["required_level"],
            importance=float(row["importance"]),
        )
        for row in requirements
        if int(row["current_level"]) < row["required_level"]
    ]
    return gaps, [
        {"role_id": str(row["id"]), "name": row["name"]}
        for row in targets
    ]


def _eligible_courses(cursor: psycopg.Cursor) -> list[dict[str, Any]]:
    return cursor.execute(
        """
        SELECT cv.id AS course_version_id, cv.course_id, cv.version, cv.title,
               cv.description, cv.price_cents, cv.duration_hours, cv.content,
               cv.delivery_format, cv.updated_at, c.trainer_id,
               u.email AS trainer_email,
               COALESCE(review.rating, 0)::float AS rating,
               COALESCE(review.review_count, 0)::integer AS review_count,
               COALESCE(
                 jsonb_agg(
                   jsonb_build_object(
                     'competency_id', cvc.competency_id,
                     'skill_name', comp.canonical_name,
                     'level_taught', cvc.level_taught
                   )
                 ) FILTER (WHERE cvc.competency_id IS NOT NULL),
                 '[]'::jsonb
               ) AS skills
        FROM course_versions cv
        JOIN courses c ON c.id = cv.course_id
        JOIN users u ON u.id = c.trainer_id
        LEFT JOIN course_version_competencies cvc
          ON cvc.course_version_id = cv.id
        LEFT JOIN competencies comp ON comp.id = cvc.competency_id
        LEFT JOIN LATERAL (
          SELECT avg(cr.rating)::float AS rating, count(*) AS review_count
          FROM course_reviews cr
          WHERE cr.course_version_id = cv.id
        ) review ON true
        WHERE cv.status = 'published'
          AND cv.duration_hours > 0
          AND EXISTS (
            SELECT 1 FROM course_approval_requests car
            WHERE car.course_version_id = cv.id
              AND car.status = 'approved'
          )
        GROUP BY cv.id, c.trainer_id, u.email, review.rating, review.review_count
        """,
    ).fetchall()


def _course_prerequisites(
    cursor: psycopg.Cursor, user_id: UUID, course_version_id: UUID
) -> list[dict[str, object]]:
    rows = cursor.execute(
        """
        SELECT c.id AS competency_id, c.canonical_name AS skill_name,
               cp.minimum_level, COALESCE(lc.level, 0) AS current_level
        FROM course_prerequisites cp
        JOIN competencies c ON c.id = cp.prerequisite_competency_id
        LEFT JOIN learner_competencies lc
          ON lc.user_id = %s AND lc.competency_id = c.id
        WHERE cp.course_version_id = %s
        ORDER BY c.canonical_name
        """,
        (user_id, course_version_id),
    ).fetchall()
    return [
        {
            "skill_id": str(row["competency_id"]),
            "skill_name": row["skill_name"],
            "minimum_level": row["minimum_level"],
            "current_level": row["current_level"],
            "is_met": row["current_level"] >= row["minimum_level"],
        }
        for row in rows
    ]


def _course_payload(
    cursor: psycopg.Cursor,
    row: dict[str, Any],
    user_id: UUID,
    gaps: list[RoleGap],
    prioritize_paid: bool,
) -> dict[str, object]:
    score, reasons = score_course(
        float(row["duration_hours"]) if row["duration_hours"] is not None else None,
        row["skills"],
        gaps,
    )
    content = row["content"] if isinstance(row["content"], dict) else {}
    wishlist = cursor.execute(
        """
        SELECT 1 FROM course_wishlist
        WHERE learner_id = %s AND course_version_id = %s
        """,
        (user_id, row["course_version_id"]),
    ).fetchone()
    duration = (
        float(row["duration_hours"]) if row["duration_hours"] is not None else None
    )
    prerequisites = _course_prerequisites(
        cursor, user_id, row["course_version_id"]
    )
    reviews = cursor.execute(
        """
        SELECT rating, review_text, created_at
        FROM course_reviews
        WHERE course_version_id = %s
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (row["course_version_id"],),
    ).fetchall()
    return {
        "course_version_id": str(row["course_version_id"]),
        "course_id": str(row["course_id"]),
        "version": row["version"],
        "title": row["title"],
        "description": row["description"],
        "duration_hours": duration,
        "price_cents": row["price_cents"],
        "price_label": "Free" if row["price_cents"] == 0 else f"₹{row['price_cents'] / 100:,.2f}",
        "delivery_format": row["delivery_format"],
        "rating": float(row["rating"]),
        "review_count": row["review_count"],
        "trainer_id": str(row["trainer_id"]),
        "trainer": row["trainer_email"],
        "updated_at": row["updated_at"].isoformat(),
        "skills": row["skills"],
        "gap_closed_per_hour": score,
        "reasons": reasons,
        "reason_summary": reason_summary(reasons, duration or 0),
        "prerequisites": [
            {**item, "current_level": int(item["current_level"])}
            for item in prerequisites
        ],
        "unmet_prerequisites": [
            item for item in prerequisites if not item["is_met"]
        ],
        "reviews": [
            {
                "rating": review["rating"],
                "review_text": review["review_text"],
                "created_at": review["created_at"].isoformat(),
            }
            for review in reviews
        ],
        "wishlist": wishlist is not None,
        "syllabus": content.get("syllabus", []),
        "learning_outcomes": content.get("learning_outcomes", []),
        "prioritize_paid": prioritize_paid,
        "sort_price_tier": affordability_order(
            row["price_cents"], prioritize_paid
        ),
    }


@router.get("/learning/preferences")
def get_learning_preferences(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        return _get_preferences(cursor, UUID(user.id))


@router.put("/learning/preferences")
def save_learning_preferences(
    payload: LearningPreferencesRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """
            INSERT INTO learner_preferences
              (user_id, weekly_study_hours, budget_cents, learning_format, prioritize_paid)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
            SET weekly_study_hours = EXCLUDED.weekly_study_hours,
                budget_cents = EXCLUDED.budget_cents,
                learning_format = EXCLUDED.learning_format,
                prioritize_paid = EXCLUDED.prioritize_paid,
                updated_at = now()
            RETURNING weekly_study_hours, budget_cents, learning_format, prioritize_paid
            """,
            (
                UUID(user.id),
                payload.weekly_study_hours,
                payload.budget_cents,
                payload.learning_format,
                payload.prioritize_paid,
            ),
        ).fetchone()
    return row


@router.get("/courses/recommendations")
def course_recommendations(
    skill_id: UUID | None = None,
    level: int | None = Query(default=None, ge=1, le=5),
    max_price_cents: int | None = Query(default=None, ge=0),
    min_duration_hours: float | None = Query(default=None, ge=0),
    max_duration_hours: float | None = Query(default=None, gt=0),
    trainer_id: UUID | None = None,
    min_rating: float | None = Query(default=None, ge=0, le=5),
    search: str | None = Query(default=None, max_length=200),
    connection: psycopg.Connection = Depends(get_connection),
    user: UserResponse = Depends(require_role("trainee")),
) -> dict[str, object]:
    if (
        min_duration_hours is not None
        and max_duration_hours is not None
        and min_duration_hours > max_duration_hours
    ):
        raise HTTPException(status_code=422, detail="Minimum duration exceeds maximum duration")

    with connection.cursor(row_factory=dict_row) as cursor:
        gaps, roles = _role_gaps(cursor, UUID(user.id))
        preferences = _get_preferences(cursor, UUID(user.id))
        published = _eligible_courses(cursor)
        recommendations = [
            _course_payload(
                cursor,
                course,
                UUID(user.id),
                gaps,
                bool(preferences["prioritize_paid"]),
            )
            for course in published
        ]
        if skill_id is not None:
            recommendations = [
                course
                for course in recommendations
                if any(skill["competency_id"] == str(skill_id) for skill in course["skills"])
            ]
        if level is not None:
            recommendations = [
                course
                for course in recommendations
                if any(skill["level_taught"] == level for skill in course["skills"])
            ]
        effective_budget = preferences["budget_cents"]
        if effective_budget is not None:
            max_price_cents = (
                int(effective_budget)
                if max_price_cents is None
                else min(max_price_cents, int(effective_budget))
            )
        if max_price_cents is not None:
            recommendations = [
                course
                for course in recommendations
                if course["price_cents"] <= max_price_cents
            ]
        if min_duration_hours is not None:
            recommendations = [
                course
                for course in recommendations
                if course["duration_hours"] is not None
                and course["duration_hours"] >= min_duration_hours
            ]
        if max_duration_hours is not None:
            recommendations = [
                course
                for course in recommendations
                if course["duration_hours"] is not None
                and course["duration_hours"] <= max_duration_hours
            ]
        if trainer_id is not None:
            recommendations = [
                course
                for course in recommendations
                if course["trainer_id"] == str(trainer_id)
            ]
        if min_rating is not None:
            recommendations = [
                course for course in recommendations if course["rating"] >= min_rating
            ]
        if search:
            term = search.casefold().strip()
            recommendations = [
                course
                for course in recommendations
                if term in str(course["title"]).casefold()
                or term in str(course["description"] or "").casefold()
                or any(
                    term in str(skill["skill_name"]).casefold()
                    for skill in course["skills"]
                )
            ]
        recommendations = [
            course for course in recommendations if course["reasons"]
        ]
        recommendations.sort(
            key=lambda course: (
                course["sort_price_tier"],
                course["delivery_format"] != preferences["learning_format"],
                -float(course["gap_closed_per_hour"]),
                -float(course["rating"]),
                str(course["title"]).casefold(),
            )
        )
        for course in recommendations:
            course.pop("sort_price_tier", None)
            course.pop("prioritize_paid", None)
    return {
        "target_roles": roles,
        "learning_preferences": preferences,
        "recommendations": recommendations,
        "message": (
            None
            if roles
            else "Choose at least one target role to get gap-based course recommendations."
        ),
    }


@router.get("/course-versions/{course_version_id}")
def get_course_detail(
    course_version_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = _eligible_courses(cursor)
        row = next(
            (
                item
                for item in rows
                if item["course_version_id"] == course_version_id
            ),
            None,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Published course version not found")
        gaps, roles = _role_gaps(cursor, UUID(user.id))
        preferences = _get_preferences(cursor, UUID(user.id))
        detail = _course_payload(
            cursor,
            row,
            UUID(user.id),
            gaps,
            bool(preferences["prioritize_paid"]),
        )
        detail["target_roles"] = roles
        detail["pretest_available_during_enrollment"] = False
    return detail


@router.post("/courses/compare")
def compare_courses(
    payload: CompareCoursesRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        eligible = _eligible_courses(cursor)
        by_id = {row["course_version_id"]: row for row in eligible}
        if any(course_id not in by_id for course_id in payload.course_version_ids):
            raise HTTPException(
                status_code=404,
                detail="Compare only currently published and approved course versions",
            )
        gaps, _ = _role_gaps(cursor, UUID(user.id))
        preferences = _get_preferences(cursor, UUID(user.id))
        courses = [
            _course_payload(
                cursor,
                by_id[course_id],
                UUID(user.id),
                gaps,
                bool(preferences["prioritize_paid"]),
            )
            for course_id in payload.course_version_ids
        ]
    return {"courses": courses}


@router.get("/courses/wishlist")
def get_wishlist(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        eligible = _eligible_courses(cursor)
        wishlisted = cursor.execute(
            """
            SELECT course_version_id FROM course_wishlist
            WHERE learner_id = %s ORDER BY created_at DESC
            """,
            (UUID(user.id),),
        ).fetchall()
        eligible_by_id = {row["course_version_id"]: row for row in eligible}
        gaps, _ = _role_gaps(cursor, UUID(user.id))
        preferences = _get_preferences(cursor, UUID(user.id))
        results = [
            _course_payload(
                cursor,
                eligible_by_id[row["course_version_id"]],
                UUID(user.id),
                gaps,
                bool(preferences["prioritize_paid"]),
            )
            for row in wishlisted
            if row["course_version_id"] in eligible_by_id
        ]
    for course in results:
        course.pop("sort_price_tier", None)
        course.pop("prioritize_paid", None)
    return results


@router.put("/courses/wishlist")
def add_to_wishlist(
    payload: WishlistRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        eligible = cursor.execute(
            """
            SELECT cv.id
            FROM course_versions cv
            WHERE cv.id = %s AND cv.status = 'published'
              AND EXISTS (
                SELECT 1 FROM course_approval_requests car
                WHERE car.course_version_id = cv.id AND car.status = 'approved'
              )
            """,
            (payload.course_version_id,),
        ).fetchone()
        if not eligible:
            raise HTTPException(status_code=404, detail="Published course version not found")
        cursor.execute(
            """
            INSERT INTO course_wishlist (learner_id, course_version_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (UUID(user.id), payload.course_version_id),
        )
    return {"course_version_id": str(payload.course_version_id), "status": "saved"}


@router.delete("/courses/wishlist/{course_version_id}", status_code=204)
def remove_from_wishlist(
    course_version_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM course_wishlist
            WHERE learner_id = %s AND course_version_id = %s
            """,
            (UUID(user.id), course_version_id),
        )


@router.get("/external-courses")
def list_external_courses(
    skill_id: UUID | None = None,
    max_price_cents: int | None = Query(default=None, ge=0),
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        preferences = _get_preferences(cursor, UUID(user.id))
        if preferences["budget_cents"] is not None:
            max_price_cents = (
                int(preferences["budget_cents"])
                if max_price_cents is None
                else min(max_price_cents, int(preferences["budget_cents"]))
            )
        rows = cursor.execute(
            """
            SELECT ec.id, ec.title, ec.description, ec.provider, ec.provider_domain,
                   ec.course_url, ec.duration_hours, ec.price_cents, ec.difficulty,
                   ec.language, ec.verified_at,
                   COALESCE(jsonb_agg(jsonb_build_object(
                     'competency_id', ecc.competency_id,
                     'skill_name', c.canonical_name,
                     'level_taught', ecc.level_taught
                   )) FILTER (WHERE ecc.competency_id IS NOT NULL), '[]'::jsonb) AS skills
            FROM external_courses ec
            LEFT JOIN external_course_competencies ecc ON ecc.external_course_id = ec.id
            LEFT JOIN competencies c ON c.id = ecc.competency_id
            WHERE ec.active = true AND ec.verified_at IS NOT NULL
            GROUP BY ec.id
            ORDER BY ec.price_cents, ec.title
            """
        ).fetchall()
    results = [
        {
            **row,
            "id": str(row["id"]),
            "duration_hours": (
                float(row["duration_hours"]) if row["duration_hours"] is not None else None
            ),
            "verified_at": row["verified_at"].isoformat(),
            "external": True,
            "credit_policy": "Optional resource only. Credit requires a valid provider certificate check or passing challenge test.",
        }
        for row in rows
        if (max_price_cents is None or row["price_cents"] <= max_price_cents)
        and (
            skill_id is None
            or any(
                skill["competency_id"] == str(skill_id) for skill in row["skills"]
            )
        )
    ]
    return results


@router.post("/courses/sync-live")
def trigger_live_courses_sync(
    limit: int = Query(default=15, ge=1, le=50),
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    """Triggers live ingestion of real courses from Coursera into the external_courses catalog."""
    from app.services.live_integrations import sync_live_courses_into_db
    return sync_live_courses_into_db(connection, limit=limit)


@router.post("/courses/webhook")
def receive_course_update_webhook(
    payload: dict[str, Any],
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    """Receives webhook updates from learning platforms/apps and saves them into external_courses."""
    title = payload.get("title", "").strip()
    course_url = payload.get("course_url") or payload.get("url")
    provider = payload.get("provider", "External Provider")
    provider_domain = payload.get("provider_domain", "learning.local")
    description = payload.get("description", "")
    duration_hours = payload.get("duration_hours", 10.0)
    price_cents = payload.get("price_cents", 0)

    if not title or not course_url:
        raise HTTPException(status_code=422, detail="Webhook payload must provide 'title' and 'course_url'")

    with connection.cursor(row_factory=dict_row) as cursor:
        existing = cursor.execute("SELECT id FROM external_courses WHERE course_url = %s", (course_url,)).fetchone()
        if existing:
            cursor.execute(
                """
                UPDATE external_courses
                SET title = %s, description = %s, price_cents = %s, verified_at = now()
                WHERE id = %s
                """,
                (title, description, price_cents, existing["id"]),
            )
            course_id = existing["id"]
            action = "updated"
        else:
            inserted = cursor.execute(
                """
                INSERT INTO external_courses (
                    title, description, provider, provider_domain, course_url,
                    duration_hours, price_cents, difficulty, language, active, verified_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'intermediate', 'English', true, now())
                RETURNING id
                """,
                (title, description, provider, provider_domain, course_url, duration_hours, price_cents),
            ).fetchone()
            course_id = inserted["id"]
            action = "created"

        connection.commit()

    return {"status": "success", "action": action, "course_id": str(course_id)}


@router.post("/external-courses/{external_course_id}/completion", status_code=202)
def submit_external_completion(
    external_course_id: UUID,
    payload: ExternalCompletionRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        course = cursor.execute(
            """
            SELECT provider_domain
            FROM external_courses
            WHERE id = %s AND active = true AND verified_at IS NOT NULL
            """,
            (external_course_id,),
        ).fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="Verified external course not found")
        certificate_host = (
            urlsplit(str(payload.certificate_url)).hostname or ""
        ).lower().removeprefix("www.")
        provider_domain = course["provider_domain"].lower().removeprefix("www.")
        if not (
            certificate_host == provider_domain
            or certificate_host.endswith(f".{provider_domain}")
        ):
            raise HTTPException(
                status_code=422,
                detail="Certificate URL must be on the external course provider's domain",
            )
        existing = cursor.execute(
            """
            SELECT id, status FROM external_course_completions
            WHERE external_course_id = %s AND learner_id = %s
              AND certificate_id = %s
            """,
            (external_course_id, UUID(user.id), payload.certificate_id),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Certificate submission already exists with status {existing['status']}",
            )
        completion = cursor.execute(
            """
            INSERT INTO external_course_completions
              (external_course_id, learner_id, certificate_id, certificate_url)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                external_course_id,
                UUID(user.id),
                payload.certificate_id,
                str(payload.certificate_url),
            ),
        ).fetchone()
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'external_course_certificate_submitted',
                    'external_course_completion', %s, %s)
            """,
            (
                UUID(user.id),
                completion["id"],
                Jsonb({"external_course_id": str(external_course_id)}),
            ),
        )
    return {
        "completion_id": str(completion["id"]),
        "status": "pending",
        "message": "No competency credit is granted until an admin verifies the certificate.",
    }


@router.get("/external-course-completions")
def list_own_external_completions(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT ecc.id, ecc.external_course_id, ec.title AS course_title,
                   ec.provider, ecc.certificate_id, ecc.status,
                   ecc.review_reason, ecc.submitted_at, ecc.reviewed_at
            FROM external_course_completions ecc
            JOIN external_courses ec ON ec.id = ecc.external_course_id
            WHERE ecc.learner_id = %s
            ORDER BY ecc.submitted_at DESC
            """,
            (UUID(user.id),),
        ).fetchall()
    return [
        {
            **row,
            "id": str(row["id"]),
            "external_course_id": str(row["external_course_id"]),
            "submitted_at": row["submitted_at"].isoformat(),
            "reviewed_at": (
                row["reviewed_at"].isoformat() if row["reviewed_at"] else None
            ),
        }
        for row in rows
    ]


@router.get("/admin/external-course-completions")
def list_external_completion_submissions(
    _: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT ecc.id, ecc.learner_id, learner.email AS learner_email,
                   ecc.external_course_id, ec.title AS course_title,
                   ec.provider, ec.provider_domain, ecc.certificate_id,
                   ecc.certificate_url, ecc.status, ecc.submitted_at
            FROM external_course_completions ecc
            JOIN users learner ON learner.id = ecc.learner_id
            JOIN external_courses ec ON ec.id = ecc.external_course_id
            WHERE ecc.status = 'pending'
            ORDER BY ecc.submitted_at
            """
        ).fetchall()
    return [
        {
            **row,
            "id": str(row["id"]),
            "learner_id": str(row["learner_id"]),
            "external_course_id": str(row["external_course_id"]),
            "submitted_at": row["submitted_at"].isoformat(),
        }
        for row in rows
    ]


@router.post("/admin/external-course-completions/{completion_id}/decision")
def decide_external_completion(
    completion_id: UUID,
    payload: ExternalCompletionDecision,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        completion = cursor.execute(
            """
            SELECT ecc.id, ecc.learner_id, ecc.external_course_id,
                   ecc.certificate_id, ecc.certificate_url, ecc.status,
                   ec.provider_domain
            FROM external_course_completions ecc
            JOIN external_courses ec ON ec.id = ecc.external_course_id
            WHERE ecc.id = %s
            FOR UPDATE OF ecc
            """,
            (completion_id,),
        ).fetchone()
        if not completion:
            raise HTTPException(status_code=404, detail="Certificate submission not found")
        if completion["status"] != "pending":
            raise HTTPException(status_code=409, detail="Certificate submission was already reviewed")

        course_skills = cursor.execute(
            """
            SELECT competency_id, level_taught
            FROM external_course_competencies
            WHERE external_course_id = %s
            """,
            (completion["external_course_id"],),
        ).fetchall()
        if payload.decision == "verified":
            certificate_host = (
                urlsplit(completion["certificate_url"]).hostname or ""
            ).lower().removeprefix("www.")
            provider_domain = completion["provider_domain"].lower().removeprefix("www.")
            if not (
                certificate_host == provider_domain
                or certificate_host.endswith(f".{provider_domain}")
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Certificate link no longer matches the registered provider domain",
                )
            if not course_skills:
                raise HTTPException(
                    status_code=409,
                    detail="This external course has no verified competency mapping",
                )
            cursor.executemany(
                """
                INSERT INTO learner_competencies (user_id, competency_id, level, status)
                VALUES (%s, %s, %s, 'verified')
                ON CONFLICT (user_id, competency_id) DO UPDATE
                SET level = GREATEST(
                      COALESCE(learner_competencies.level, 0),
                      EXCLUDED.level
                    ),
                    status = 'verified',
                    freshness = 'current',
                    last_evidence_at = now(),
                    updated_at = now()
                """,
                [
                    (
                        completion["learner_id"],
                        skill["competency_id"],
                        skill["level_taught"],
                    )
                    for skill in course_skills
                ],
            )
            for skill in course_skills:
                cursor.execute(
                    """
                    INSERT INTO evidence
                      (user_id, competency_id, source_type, verification,
                       source_url, metadata)
                    VALUES (%s, %s, 'credential', 'verified', %s, %s)
                    """,
                    (
                        completion["learner_id"],
                        skill["competency_id"],
                        completion["certificate_url"],
                        Jsonb(
                            {
                                "external_completion_id": str(completion_id),
                                "external_course_id": str(completion["external_course_id"]),
                                "certificate_id": completion["certificate_id"],
                                "verified_by": str(admin.id),
                                "review_reason": payload.review_reason,
                            }
                        ),
                    ),
                )

        cursor.execute(
            """
            UPDATE external_course_completions
            SET status = %s, review_reason = %s, reviewed_at = now(), reviewed_by = %s
            WHERE id = %s
            """,
            (
                payload.decision,
                payload.review_reason,
                UUID(admin.id),
                completion_id,
            ),
        )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, %s, 'external_course_completion', %s, %s)
            """,
            (
                UUID(admin.id),
                f"external_course_completion_{payload.decision}",
                completion_id,
                Jsonb({"reason": payload.review_reason}),
            ),
        )
    return {"completion_id": str(completion_id), "status": payload.decision}


@router.post("/admin/external-courses", status_code=201)
def create_external_course(
    payload: ExternalCourseRequest,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    host = (urlsplit(str(payload.course_url)).hostname or "").lower().removeprefix("www.")
    provider_domain = payload.provider_domain.removeprefix("www.")
    if (
        provider_domain not in PROVIDER_DOMAINS
        or not (host == provider_domain or host.endswith(f".{provider_domain}"))
    ):
        raise HTTPException(
            status_code=422,
            detail="Course URL must use a supported provider's verified domain",
        )

    with connection.cursor(row_factory=dict_row) as cursor:
        competency_ids = list(payload.skills)
        found = cursor.execute(
            """
            SELECT id FROM competencies
            WHERE active = true AND id = ANY(%s)
            """,
            (competency_ids,),
        ).fetchall()
        if len(found) != len(competency_ids):
            raise HTTPException(status_code=422, detail="One or more skills are not in the taxonomy")
        course = cursor.execute(
            """
            INSERT INTO external_courses
              (title, description, provider, provider_domain, course_url,
               duration_hours, price_cents, difficulty, language, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                payload.title,
                payload.description,
                payload.provider,
                provider_domain,
                str(payload.course_url),
                payload.duration_hours,
                payload.price_cents,
                payload.difficulty,
                payload.language,
                UUID(admin.id),
            ),
        ).fetchone()
        for competency_id, level in payload.skills.items():
            cursor.execute(
                """
                INSERT INTO external_course_competencies
                  (external_course_id, competency_id, level_taught)
                VALUES (%s, %s, %s)
                """,
                (course["id"], competency_id, level),
            )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'external_course_submitted', 'external_course', %s, %s)
            """,
            (
                UUID(admin.id),
                course["id"],
                Jsonb({"provider_domain": provider_domain}),
            ),
        )
    return {"external_course_id": str(course["id"]), "status": "pending_verification"}


@router.post("/admin/external-courses/{external_course_id}/verify")
def verify_external_course(
    external_course_id: UUID,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        course = cursor.execute(
            """
            UPDATE external_courses
            SET active = true, verified_at = now()
            WHERE id = %s
            RETURNING id, provider_domain, course_url
            """,
            (external_course_id,),
        ).fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="External course not found")
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'external_course_verified', 'external_course', %s, %s)
            """,
            (
                UUID(admin.id),
                external_course_id,
                Jsonb({"provider_domain": course["provider_domain"]}),
            ),
        )
    return {"external_course_id": str(external_course_id), "status": "verified"}
