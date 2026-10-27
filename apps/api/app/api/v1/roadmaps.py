import io
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from psycopg.rows import dict_row
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.api.v1.auth import require_role
from app.api.v1.courses import _eligible_courses
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.schemas.roadmaps import RoadmapRequest
from app.services.profile_progress import calculate_role_progress
from app.services.roadmaps import build_course_roadmap, roadmap_fingerprint

router = APIRouter(prefix="/api/v1", tags=["Learning roadmap"])
REPLAN_INTERVAL_DAYS = 7
FINISH_DATE_CHANGE_THRESHOLD = 0.15


def _role_requirements(
    cursor: psycopg.Cursor, learner_id: UUID, role_id: UUID
) -> list[dict[str, Any]]:
    return cursor.execute(
        """
        SELECT c.id AS competency_id, c.canonical_name AS skill_name,
               rc.required_level, rc.importance, COALESCE(lc.level, 0) AS current_level
        FROM role_competencies rc
        JOIN competencies c ON c.id = rc.competency_id AND c.active
        LEFT JOIN learner_competencies lc
          ON lc.user_id = %s AND lc.competency_id = c.id
        WHERE rc.role_id = %s
        ORDER BY rc.importance DESC, c.canonical_name
        """,
        (learner_id, role_id),
    ).fetchall()


def _roadmap_inputs(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    role_id: UUID,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int], str]:
    requirements = _role_requirements(cursor, learner_id, role_id)
    if not requirements:
        raise HTTPException(status_code=409, detail="This target role has no competency requirements.")
    courses = [dict(row) for row in _eligible_courses(cursor)]
    course_ids = [row["course_version_id"] for row in courses]
    prerequisites: dict[str, list[dict[str, Any]]] = {}
    if course_ids:
        rows = cursor.execute(
            """
            SELECT cp.course_version_id, cp.prerequisite_competency_id AS competency_id,
                   c.canonical_name AS skill_name, cp.minimum_level
            FROM course_prerequisites cp
            JOIN competencies c ON c.id = cp.prerequisite_competency_id
            WHERE cp.course_version_id = ANY(%s)
            ORDER BY cp.course_version_id, c.canonical_name
            """,
            (course_ids,),
        ).fetchall()
        for row in rows:
            prerequisites.setdefault(str(row["course_version_id"]), []).append(
                {
                    "competency_id": str(row["competency_id"]),
                    "skill_name": row["skill_name"],
                    "minimum_level": int(row["minimum_level"]),
                }
            )
    for course in courses:
        course["course_version_id"] = str(course["course_version_id"])
        course["duration_hours"] = float(course["duration_hours"])
        course["skills"] = [
            {
                **skill,
                "competency_id": str(skill["competency_id"]),
                "level_taught": int(skill["level_taught"]),
            }
            for skill in course["skills"]
        ]
        course["prerequisites"] = prerequisites.get(course["course_version_id"], [])
    level_rows = cursor.execute(
        """
        SELECT competency_id, level
        FROM learner_competencies
        WHERE user_id = %s AND level IS NOT NULL
        """,
        (learner_id,),
    ).fetchall()
    current_levels = {
        str(row["competency_id"]): int(row["level"]) for row in level_rows
    }
    fingerprint = roadmap_fingerprint(str(role_id), requirements, courses)
    return requirements, courses, current_levels, fingerprint


def _settings(cursor: psycopg.Cursor, learner_id: UUID) -> dict[str, Any] | None:
    row = cursor.execute(
        """
        SELECT s.role_id, r.name AS role_name, s.weekly_study_hours,
               s.budget_cents, s.strategy::text AS strategy,
               s.target_finish_date, s.ready_threshold
        FROM learner_roadmap_settings s
        JOIN role_catalog r ON r.id = s.role_id
        WHERE s.learner_id = %s
        """,
        (learner_id,),
    ).fetchone()
    if not row:
        return None
    return {
        **row,
        "role_id": str(row["role_id"]),
        "weekly_study_hours": float(row["weekly_study_hours"]),
        "target_finish_date": (
            row["target_finish_date"].isoformat() if row["target_finish_date"] else None
        ),
    }


def _latest_roadmap(cursor: psycopg.Cursor, learner_id: UUID) -> dict[str, Any] | None:
    return cursor.execute(
        """
        SELECT rm.id, rm.version, rm.role_id, r.name AS role_name,
               rm.strategy::text AS strategy, rm.target_finish_date,
               rm.weekly_study_hours, rm.budget_cents, rm.fingerprint,
               rm.change_reason, rm.created_at
        FROM learner_roadmaps rm
        JOIN role_catalog r ON r.id = rm.role_id
        WHERE rm.learner_id = %s
        ORDER BY rm.version DESC
        LIMIT 1
        """,
        (learner_id,),
    ).fetchone()


def _milestone_rows(cursor: psycopg.Cursor, roadmap_id: UUID, learner_id: UUID) -> list[dict[str, Any]]:
    rows = cursor.execute(
        """
        SELECT m.id, m.step_order, m.course_version_id, m.course_title,
               m.duration_hours, m.price_cents, m.planned_start_date,
               m.planned_end_date,
               e.id AS enrollment_id, e.status AS enrollment_status
        FROM roadmap_milestones m
        JOIN learner_roadmaps rm ON rm.id = m.roadmap_id
        LEFT JOIN LATERAL (
          SELECT id, status
          FROM enrollments
          WHERE learner_id = %s AND course_version_id = m.course_version_id
            AND status != 'cancelled'
          ORDER BY completed_at DESC NULLS LAST, enrolled_at DESC
          LIMIT 1
        ) e ON true
        WHERE m.roadmap_id = %s
        ORDER BY m.step_order
        """,
        (learner_id, roadmap_id),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "step_order": row["step_order"],
            "course_version_id": str(row["course_version_id"]),
            "course_title": row["course_title"],
            "duration_hours": float(row["duration_hours"]),
            "price_cents": row["price_cents"],
            "planned_start_date": row["planned_start_date"].isoformat(),
            "planned_end_date": row["planned_end_date"].isoformat(),
            "status": (
                "completed"
                if row["enrollment_status"] == "completed"
                else "in_progress"
                if row["enrollment_status"] == "active"
                else "planned"
            ),
            "enrollment_id": str(row["enrollment_id"]) if row["enrollment_id"] else None,
        }
        for row in rows
    ]


def _finish_date_moved_more_than_threshold(
    existing: dict[str, Any],
    requested_date: date | None,
) -> bool:
    old_date = existing["target_finish_date"]
    if old_date is None or requested_date is None:
        return False
    old_date = old_date.date() if isinstance(old_date, datetime) else old_date
    baseline_days = max(1, (old_date - existing["created_at"].date()).days)
    moved_days = abs((requested_date - old_date).days)
    return moved_days / baseline_days > FINISH_DATE_CHANGE_THRESHOLD


def _create_roadmap(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    request: RoadmapRequest,
    reason: str,
) -> dict[str, Any]:
    requirements, courses, current_levels, fingerprint = _roadmap_inputs(
        cursor, learner_id, request.role_id
    )
    plan = build_course_roadmap(
        requirements=requirements,
        courses=courses,
        current_levels=current_levels,
        weekly_study_hours=request.weekly_study_hours,
        budget_cents=request.budget_cents,
        strategy=request.strategy,
        today=date.today(),
        target_finish_date=request.target_finish_date,
    )
    latest = _latest_roadmap(cursor, learner_id)
    version = int(latest["version"]) + 1 if latest else 1
    roadmap = cursor.execute(
        """
        INSERT INTO learner_roadmaps
          (learner_id, version, role_id, strategy, target_finish_date,
           weekly_study_hours, budget_cents, fingerprint, change_reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, version, created_at
        """,
        (
            learner_id,
            version,
            request.role_id,
            request.strategy,
            request.target_finish_date,
            request.weekly_study_hours,
            request.budget_cents,
            fingerprint,
            reason,
        ),
    ).fetchone()
    for milestone in plan["milestones"]:
        cursor.execute(
            """
            INSERT INTO roadmap_milestones
              (roadmap_id, step_order, course_version_id, course_title,
               duration_hours, price_cents, planned_start_date, planned_end_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                roadmap["id"],
                milestone["step_order"],
                UUID(milestone["course_version_id"]),
                milestone["course_title"],
                milestone["duration_hours"],
                milestone["price_cents"],
                date.fromisoformat(milestone["planned_start_date"]),
                date.fromisoformat(milestone["planned_end_date"]),
            ),
        )
    cursor.execute(
        """
        INSERT INTO learner_roadmap_settings
          (learner_id, role_id, weekly_study_hours, budget_cents,
           strategy, target_finish_date)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (learner_id) DO UPDATE
        SET role_id = EXCLUDED.role_id,
            weekly_study_hours = EXCLUDED.weekly_study_hours,
            budget_cents = EXCLUDED.budget_cents,
            strategy = EXCLUDED.strategy,
            target_finish_date = EXCLUDED.target_finish_date,
            updated_at = now()
        """,
        (
            learner_id,
            request.role_id,
            request.weekly_study_hours,
            request.budget_cents,
            request.strategy,
            request.target_finish_date,
        ),
    )
    return {
        "id": str(roadmap["id"]),
        "version": roadmap["version"],
        "created_at": roadmap["created_at"].isoformat(),
        "change_reason": reason,
        **plan,
    }


def _build_response(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    *,
    suggested_adjustment: str | None = None,
) -> dict[str, Any]:
    latest = _latest_roadmap(cursor, learner_id)
    settings = _settings(cursor, learner_id)
    if not latest or not settings:
        return {"roadmap": None, "settings": settings, "versions": [], "suggested_adjustment": None}

    requirements, _, _, fingerprint = _roadmap_inputs(
        cursor, learner_id, latest["role_id"]
    )
    milestones = _milestone_rows(cursor, latest["id"], learner_id)
    total_hours = sum(item["duration_hours"] for item in milestones)
    total_cost = sum(item["price_cents"] for item in milestones)
    readiness, _ = calculate_role_progress(requirements)
    ready_threshold = int(settings["ready_threshold"])
    all_steps_complete = bool(milestones) and all(
        item["status"] == "completed" for item in milestones
    )
    next_milestone = next(
        (item for item in milestones if item["status"] != "completed"),
        None,
    )
    versions = cursor.execute(
        """
        SELECT id, version, role_id, strategy::text AS strategy,
               target_finish_date, change_reason, created_at
        FROM learner_roadmaps
        WHERE learner_id = %s
        ORDER BY version DESC
        LIMIT 20
        """,
        (learner_id,),
    ).fetchall()
    previous = versions[1] if len(versions) > 1 else None
    comparison = None
    if previous:
        previous_courses = cursor.execute(
            """
            SELECT course_title FROM roadmap_milestones
            WHERE roadmap_id = %s ORDER BY step_order
            """,
            (previous["id"],),
        ).fetchall()
        current_titles = [item["course_title"] for item in milestones]
        previous_titles = [item["course_title"] for item in previous_courses]
        comparison = {
            "previous_version": previous["version"],
            "reason": latest["change_reason"],
            "added_courses": [item for item in current_titles if item not in previous_titles],
            "removed_courses": [item for item in previous_titles if item not in current_titles],
        }
    history = [
        {
            "version": row["version"],
            "role_id": str(row["role_id"]),
            "strategy": row["strategy"],
            "target_finish_date": (
                row["target_finish_date"].isoformat() if row["target_finish_date"] else None
            ),
            "change_reason": row["change_reason"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in versions
    ]
    if fingerprint != latest["fingerprint"] and not suggested_adjustment:
        suggested_adjustment = "Your skill gaps or approved course catalog changed. Your roadmap is unchanged; review a suggested adjustment."
    return {
        "roadmap": {
            "id": str(latest["id"]),
            "version": latest["version"],
            "role_id": str(latest["role_id"]),
            "role_name": latest["role_name"],
            "strategy": latest["strategy"],
            "target_finish_date": (
                latest["target_finish_date"].isoformat()
                if latest["target_finish_date"]
                else None
            ),
            "created_at": latest["created_at"].isoformat(),
            "change_reason": latest["change_reason"],
            "weekly_study_hours": float(latest["weekly_study_hours"]),
            "budget_cents": latest["budget_cents"],
            "readiness": readiness,
            "job_ready": readiness >= ready_threshold,
            "job_ready_threshold": ready_threshold,
            "milestones": milestones,
            "total_hours": round(total_hours, 2),
            "total_cost_cents": total_cost,
            "estimated_finish_date": (
                milestones[-1]["planned_end_date"]
                if milestones
                else date.today().isoformat()
            ),
            "schedule_over_capacity": (
                latest["target_finish_date"] is not None
                and (
                    date.fromisoformat(milestones[-1]["planned_end_date"])
                    if milestones
                    else date.today()
                )
                > latest["target_finish_date"]
            ),
            "completed_milestones": sum(
                item["status"] == "completed" for item in milestones
            ),
            "next_best_action": (
                {
                    "type": "course",
                    "course_version_id": next_milestone["course_version_id"],
                    "title": f"Start {next_milestone['course_title']}",
                    "href": "/learning",
                }
                if next_milestone
                else {
                    "type": "jobs" if readiness >= ready_threshold else "passport",
                    "title": (
                        "You are job ready. Continue to jobs whenever you choose."
                        if readiness >= ready_threshold
                        else "Choose another target role or refresh your skills."
                    ),
                    "href": "/profile" if readiness >= ready_threshold else "/",
                }
            ),
            "all_milestones_complete": all_steps_complete,
            "remaining_gaps": [
                {
                    "skill_name": row["skill_name"],
                    "current_level": int(row["current_level"]),
                    "required_level": int(row["required_level"]),
                }
                for row in requirements
                if int(row["current_level"]) < int(row["required_level"])
            ],
        },
        "settings": settings,
        "versions": history,
        "comparison": comparison,
        "suggested_adjustment": suggested_adjustment,
        "replan_available": _replan_interval_elapsed(latest["created_at"]),
    }


def _replan_interval_elapsed(created_at: datetime) -> bool:
    created_at_utc = (
        created_at.replace(tzinfo=timezone.utc)
        if created_at.tzinfo is None
        else created_at.astimezone(timezone.utc)
    )
    return (datetime.now(timezone.utc) - created_at_utc).days >= REPLAN_INTERVAL_DAYS


def _replan_reason(
    cursor: psycopg.Cursor,
    learner_id: UUID,
    latest: dict[str, Any],
    settings: dict[str, Any],
) -> str | None:
    if str(latest["role_id"]) != str(settings["role_id"]):
        return "Target role changed"
    requested_finish = settings["target_finish_date"]
    if isinstance(requested_finish, str):
        requested_finish = date.fromisoformat(requested_finish)
    if _finish_date_moved_more_than_threshold(latest, requested_finish):
        return "Target finish date moved by more than 15%"
    completed = cursor.execute(
        """
        SELECT EXISTS (
          SELECT 1
          FROM roadmap_milestones m
          JOIN enrollments e
            ON e.course_version_id = m.course_version_id
           AND e.learner_id = %s AND e.status = 'completed'
           AND e.completed_at > %s
           WHERE m.roadmap_id = %s
        ) AS completed
        """,
        (learner_id, latest["created_at"], latest["id"]),
    ).fetchone()["completed"]
    if completed:
        return "A course milestone was completed"
    return None


@router.get("/learning/roadmap")
def get_learning_roadmap(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        return _build_response(cursor, UUID(user.id))


@router.put("/learning/roadmap")
def save_learning_roadmap(
    payload: RoadmapRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        target_role = cursor.execute(
            """
            SELECT 1 FROM learner_target_roles
            WHERE user_id = %s AND role_id = %s
            """,
            (learner_id, payload.role_id),
        ).fetchone()
        if not target_role:
            raise HTTPException(
                status_code=422,
                detail="Choose a target role already selected in your Skill Passport.",
            )
        latest = _latest_roadmap(cursor, learner_id)
        if not latest:
            _create_roadmap(cursor, learner_id, payload, "Initial roadmap")
            return _build_response(cursor, learner_id)

        reason = _replan_reason(cursor, learner_id, latest, payload.model_dump())
        if reason is None:
            cursor.execute(
                """
                INSERT INTO learner_roadmap_settings
                  (learner_id, role_id, weekly_study_hours, budget_cents,
                   strategy, target_finish_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (learner_id) DO UPDATE
                SET role_id = EXCLUDED.role_id,
                    weekly_study_hours = EXCLUDED.weekly_study_hours,
                    budget_cents = EXCLUDED.budget_cents,
                    strategy = EXCLUDED.strategy,
                    target_finish_date = EXCLUDED.target_finish_date,
                    updated_at = now()
                """,
                (
                    learner_id,
                    payload.role_id,
                    payload.weekly_study_hours,
                    payload.budget_cents,
                    payload.strategy,
                    payload.target_finish_date,
                ),
            )
            result = _build_response(
                cursor,
                learner_id,
                suggested_adjustment=(
                    "Settings saved, but Fix R17 keeps the active roadmap stable until a target role changes, "
                    "a milestone completes, or the finish date moves by more than 15%."
                ),
            )
            return result

        last_replanned = latest["created_at"]
        if last_replanned.tzinfo is None:
            last_replanned = last_replanned.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last_replanned).days < REPLAN_INTERVAL_DAYS:
            cursor.execute(
                """
                INSERT INTO learner_roadmap_settings
                  (learner_id, role_id, weekly_study_hours, budget_cents,
                   strategy, target_finish_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (learner_id) DO UPDATE
                SET role_id = EXCLUDED.role_id,
                    weekly_study_hours = EXCLUDED.weekly_study_hours,
                    budget_cents = EXCLUDED.budget_cents,
                    strategy = EXCLUDED.strategy,
                    target_finish_date = EXCLUDED.target_finish_date,
                    updated_at = now()
                """,
                (
                    learner_id,
                    payload.role_id,
                    payload.weekly_study_hours,
                    payload.budget_cents,
                    payload.strategy,
                    payload.target_finish_date,
                ),
            )
            return _build_response(
                cursor,
                learner_id,
                suggested_adjustment=(
                    f"{reason}. Your roadmap was last replanned less than seven days ago, "
                    "so it is retained for now."
                ),
            )

        _create_roadmap(cursor, learner_id, payload, reason)
        return _build_response(cursor, learner_id)


@router.post("/learning/roadmap/refresh")
def refresh_learning_roadmap(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    learner_id = UUID(user.id)
    with connection.cursor(row_factory=dict_row) as cursor:
        latest = _latest_roadmap(cursor, learner_id)
        settings = _settings(cursor, learner_id)
        if not latest or not settings:
            return _build_response(cursor, learner_id)
        reason = _replan_reason(cursor, learner_id, latest, settings)
        if reason is None:
            return _build_response(cursor, learner_id)
        last_replanned = latest["created_at"]
        if last_replanned.tzinfo is None:
            last_replanned = last_replanned.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last_replanned).days < REPLAN_INTERVAL_DAYS:
            return _build_response(
                cursor,
                learner_id,
                suggested_adjustment=(
                    f"{reason}. Automatic replanning is limited to once every seven days."
                ),
            )
        payload = RoadmapRequest(
            role_id=UUID(settings["role_id"]),
            weekly_study_hours=settings["weekly_study_hours"],
            budget_cents=settings["budget_cents"],
            strategy=settings["strategy"],
            target_finish_date=(
                date.fromisoformat(settings["target_finish_date"])
                if settings["target_finish_date"]
                else None
            ),
        )
        _create_roadmap(cursor, learner_id, payload, reason)
        return _build_response(cursor, learner_id)


@router.get("/learning/roadmap/export.pdf")
def export_learning_roadmap(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> StreamingResponse:
    with connection.cursor(row_factory=dict_row) as cursor:
        data = _build_response(cursor, UUID(user.id))
    roadmap = data["roadmap"]
    if not roadmap:
        raise HTTPException(status_code=404, detail="Create a roadmap before exporting it.")
    output = io.BytesIO()
    page = canvas.Canvas(output, pagesize=A4)
    page.setTitle(f"Learning roadmap v{roadmap['version']} - {roadmap['role_name']}")
    page.setFont("Helvetica-Bold", 20)
    page.drawString(48, 795, f"Learning roadmap · {roadmap['role_name']}")
    page.setFont("Helvetica", 11)
    page.drawString(48, 774, f"Version {roadmap['version']} · {roadmap['strategy'].title()}")
    page.drawString(
        48,
        756,
        f"Readiness {roadmap['readiness']:.1f}% · Estimated finish {roadmap['estimated_finish_date']}",
    )
    y = 720
    for milestone in roadmap["milestones"]:
        if y < 100:
            page.showPage()
            y = 790
        page.setFont("Helvetica-Bold", 12)
        page.drawString(48, y, f"{milestone['step_order']}. {milestone['course_title']}")
        y -= 18
        page.setFont("Helvetica", 10)
        page.drawString(
            64,
            y,
            f"{milestone['planned_start_date']} to {milestone['planned_end_date']} · "
            f"{milestone['duration_hours']:g} hours · "
            f"INR {milestone['price_cents'] / 100:,.2f}",
        )
        y -= 26
    if not roadmap["milestones"]:
        page.drawString(48, y, "No approved courses currently cover the remaining role gaps.")
    page.setFont("Helvetica", 9)
    page.drawString(48, 42, "Skill freshness is informational and does not reduce proven levels.")
    page.save()
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="capacity-connect-roadmap.pdf"'},
    )
