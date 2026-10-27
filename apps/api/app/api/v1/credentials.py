import io
import os
import textwrap
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from psycopg.rows import dict_row
from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from psycopg.types.json import Jsonb

from app.api.v1.auth import require_role
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.schemas.credentials import CredentialExpiryRequest, CredentialRevocationRequest
from app.services.assessments import estimate_level_range

router = APIRouter(prefix="/api/v1", tags=["Verifiable credentials"])


def issue_attempt_credentials(
    cursor: psycopg.Cursor,
    attempt: dict[str, Any],
) -> list[str]:
    if (
        attempt["evidence_tier"] != "verified"
        or attempt["status"] != "submitted"
        or attempt["level_min"] is None
        or attempt["level_min"] < attempt["target_level"]
    ):
        return []

    skill_rows = cursor.execute(
        """
        SELECT aq.competency_id,
               count(*) FILTER (
                 WHERE ar.dont_know = false
                   AND aq.question_type IN ('scenario', 'code_task')
               )::integer AS practical_count,
               count(*) FILTER (
                 WHERE ar.dont_know = false
                   AND aq.question_type NOT IN ('scenario', 'code_task')
               )::integer AS knowledge_count,
               count(*) FILTER (WHERE ar.dont_know = false)::integer AS scored_count,
               COALESCE(lsr.elo_rating, 1000) AS rating,
               COALESCE(lsr.uncertainty, 350)::float AS uncertainty
        FROM assessment_responses ar
        JOIN assessment_questions aq ON aq.id = ar.question_id
        LEFT JOIN learner_skill_ratings lsr
          ON lsr.learner_id = %s AND lsr.competency_id = aq.competency_id
        WHERE ar.attempt_id = %s AND ar.submitted
        GROUP BY aq.competency_id, lsr.elo_rating, lsr.uncertainty
        """,
        (attempt["learner_id"], attempt["id"]),
    ).fetchall()

    issued_ids: list[str] = []
    for skill in skill_rows:
        level_range = estimate_level_range(
            skill["rating"], skill["uncertainty"], skill["scored_count"]
        )
        if (
            skill["practical_count"] < 1
            or skill["knowledge_count"] < 1
            or level_range["level_min"] < attempt["target_level"]
            or level_range["level_max"] - level_range["level_min"] > 1
        ):
            continue

        evidence = cursor.execute(
            """
            INSERT INTO evidence
              (user_id, competency_id, source_type, verification, metadata)
            VALUES (%s, %s, 'assessment', 'verified', %s)
            RETURNING id
            """,
            (
                attempt["learner_id"],
                skill["competency_id"],
                Jsonb(
                    {
                        "assessment_attempt_id": str(attempt["id"]),
                        "evidence_tier": attempt["evidence_tier"],
                        "practical_response_count": skill["practical_count"],
                        "knowledge_response_count": skill["knowledge_count"],
                        "level_range": level_range,
                    }
                ),
            ),
        ).fetchone()
        credential = cursor.execute(
            """
            INSERT INTO credentials
              (learner_id, competency_id, assessment_attempt_id,
               course_version_id, evidence_id, level, evidence_tier)
            VALUES (%s, %s, %s, %s, %s, %s, 'verified')
            ON CONFLICT (assessment_attempt_id, competency_id)
              WHERE assessment_attempt_id IS NOT NULL
            DO NOTHING
            RETURNING id
            """,
            (
                attempt["learner_id"],
                skill["competency_id"],
                attempt["id"],
                attempt["course_version_id"],
                evidence["id"],
                level_range["level_min"],
            ),
        ).fetchone()
        if not credential:
            cursor.execute("DELETE FROM evidence WHERE id = %s", (evidence["id"],))
            continue

        cursor.execute(
            """
            INSERT INTO learner_competencies
              (user_id, competency_id, level, status, freshness, last_evidence_at)
            VALUES (%s, %s, %s, 'verified', 'current', now())
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
            (
                attempt["learner_id"],
                skill["competency_id"],
                level_range["level_min"],
            ),
        )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'credential_issued', 'credential', %s, %s)
            """,
            (
                attempt["learner_id"],
                credential["id"],
                Jsonb(
                    {
                        "assessment_attempt_id": str(attempt["id"]),
                        "competency_id": str(skill["competency_id"]),
                        "level": level_range["level_min"],
                        "evidence_tier": "verified",
                    }
                ),
            ),
        )
        issued_ids.append(str(credential["id"]))
    return issued_ids


def _verification_url(credential_id: UUID) -> str:
    web_url = os.getenv("WEB_PUBLIC_URL", "http://localhost:3000").rstrip("/")
    return f"{web_url}/verify/{credential_id}"


def _credential_query() -> str:
    return """
        SELECT cr.id, cr.learner_id, cr.competency_id, cr.course_version_id,
               cr.assessment_attempt_id, cr.level, cr.evidence_tier,
               cr.issued_at, cr.expires_at, cr.revoked_at, cr.revocation_reason,
               cv.title AS course_title,
               comp.canonical_name AS skill_name,
               CASE
                 WHEN cr.revoked_at IS NOT NULL THEN 'revoked'
                 WHEN cr.expires_at IS NOT NULL AND cr.expires_at <= now()
                   THEN 'expired'
                 ELSE 'valid'
               END AS status
        FROM credentials cr
        JOIN competencies comp ON comp.id = cr.competency_id
        LEFT JOIN course_versions cv ON cv.id = cr.course_version_id
    """


def _public_payload(row: dict[str, Any]) -> dict[str, Any]:
    credential_id = str(row["id"])
    return {
        "credential_id": credential_id,
        "holder": f"Learner {credential_id[:8].upper()}",
        "course": row["course_title"],
        "skill": row["skill_name"],
        "level": row["level"],
        "evidence_tier": row["evidence_tier"],
        "issued_at": row["issued_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "status": row["status"],
        "verification_url": _verification_url(UUID(credential_id)),
    }


def _load_credential(
    cursor: psycopg.Cursor,
    credential_id: UUID,
    *,
    lock: bool = False,
) -> dict[str, Any]:
    row = cursor.execute(
        _credential_query()
        + """
        WHERE cr.id = %s
        """
        + ("FOR UPDATE OF cr" if lock else ""),
        (credential_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Credential not found")
    return row


def _qr_drawing(verification_url: str) -> Drawing:
    qr = QrCodeWidget(verification_url)
    bounds = qr.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(
        width,
        height,
        transform=[1, 0, 0, 1, -bounds[0], -bounds[1]],
    )
    drawing.add(qr)
    return drawing


def _credential_pdf(credential: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    page = canvas.Canvas(output, pagesize=A4)
    page.setTitle(f"Capacity Connect credential {credential['credential_id']}")
    page.setFont("Helvetica-Bold", 22)
    page.drawString(52, 785, "Capacity Connect")
    page.setFont("Helvetica-Bold", 18)
    page.drawString(52, 748, "Verifiable skill credential")
    page.setFont("Helvetica", 12)
    rows = [
        ("Credential ID", credential["credential_id"]),
        ("Holder", credential["holder"]),
        ("Course", credential["course"] or "Assessment"),
        ("Skill", credential["skill"]),
        ("Level", str(credential["level"])),
        ("Evidence tier", credential["evidence_tier"].replace("_", " ").title()),
        ("Issued", credential["issued_at"]),
        ("Expires", credential["expires_at"] or "No expiry"),
        ("Status", credential["status"].title()),
    ]
    y = 700
    for label, value in rows:
        page.setFont("Helvetica-Bold", 11)
        page.drawString(52, y, f"{label}:")
        page.setFont("Helvetica", 11)
        for line in textwrap.wrap(value, width=76) or [""]:
            page.drawString(160, y, line)
            y -= 16
        y -= 5
    page.setFont("Helvetica", 9)
    page.drawString(52, 105, "Scan the QR code or visit the URL to verify this credential.")
    page.drawString(52, 88, credential["verification_url"])
    renderPDF.draw(
        _qr_drawing(credential["verification_url"]),
        page,
        420,
        75,
    )
    page.showPage()
    page.save()
    return output.getvalue()


@router.get("/credentials")
def list_my_credentials(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            _credential_query()
            + """
            WHERE cr.learner_id = %s
            ORDER BY cr.issued_at DESC, cr.id
            """,
            (UUID(user.id),),
        ).fetchall()
    return [
        {
            **_public_payload(row),
            "assessment_attempt_id": (
                str(row["assessment_attempt_id"]) if row["assessment_attempt_id"] else None
            ),
            "revoked_at": row["revoked_at"].isoformat() if row["revoked_at"] else None,
            "revocation_reason": row["revocation_reason"],
        }
        for row in rows
    ]


@router.get("/credentials/{credential_id}/verify")
def verify_credential(
    credential_id: UUID,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = _load_credential(cursor, credential_id)
    return _public_payload(row)


@router.get("/credentials/{credential_id}/qr.svg")
def credential_qr(
    credential_id: UUID,
    connection: psycopg.Connection = Depends(get_connection),
) -> Response:
    with connection.cursor(row_factory=dict_row) as cursor:
        _load_credential(cursor, credential_id)
    svg = renderSVG.drawToString(_qr_drawing(_verification_url(credential_id)))
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/credentials/{credential_id}/download")
def download_credential(
    credential_id: UUID,
    connection: psycopg.Connection = Depends(get_connection),
) -> StreamingResponse:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = _load_credential(cursor, credential_id)
    credential = _public_payload(row)
    filename = f"capacity-connect-credential-{credential_id}.pdf"
    return StreamingResponse(
        io.BytesIO(_credential_pdf(credential)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/admin/credentials/{credential_id}/expiry")
def set_credential_expiry(
    credential_id: UUID,
    payload: CredentialExpiryRequest,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """
            UPDATE credentials
            SET expires_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (payload.expires_at, credential_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Credential not found")
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'credential_expiry_updated', 'credential', %s, %s)
            """,
            (
                UUID(admin.id),
                credential_id,
                Jsonb({
                    "expires_at": (
                        payload.expires_at.isoformat() if payload.expires_at else None
                    ),
                    "reason": payload.reason,
                }),
            ),
        )
        updated = _load_credential(cursor, credential_id)
    return _public_payload(updated)


@router.post("/admin/credentials/{credential_id}/revoke")
def revoke_credential(
    credential_id: UUID,
    payload: CredentialRevocationRequest,
    admin: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """
            SELECT learner_id, competency_id, evidence_id, revoked_at
            FROM credentials
            WHERE id = %s
            FOR UPDATE
            """,
            (credential_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Credential not found")
        if row["revoked_at"] is None:
            cursor.execute(
                """
                UPDATE credentials
                SET revoked_at = now(), revocation_reason = %s
                WHERE id = %s
                """,
                (payload.reason, credential_id),
            )
            if row["evidence_id"]:
                cursor.execute(
                    "UPDATE evidence SET verification = 'rejected' WHERE id = %s",
                    (row["evidence_id"],),
                )
            cursor.execute(
                """
                UPDATE learner_competencies
                SET status = 'claimed',
                    last_evidence_at = (
                      SELECT max(e.created_at)
                      FROM evidence e
                      WHERE e.user_id = %s AND e.competency_id = %s
                        AND e.verification IN ('provisional', 'verified')
                    ),
                    updated_at = now()
                WHERE user_id = %s AND competency_id = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM evidence
                    WHERE user_id = %s AND competency_id = %s
                      AND verification = 'verified'
                  )
                """,
                (
                    row["learner_id"],
                    row["competency_id"],
                    row["learner_id"],
                    row["competency_id"],
                    row["learner_id"],
                    row["competency_id"],
                ),
            )
            cursor.execute(
                """
                INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
                VALUES (%s, 'credential_revoked', 'credential', %s, %s)
                """,
                (UUID(admin.id), credential_id, Jsonb({"reason": payload.reason})),
            )
    return {"credential_id": str(credential_id), "status": "revoked"}


@router.get("/admin/credentials")
def list_credentials_for_admin(
    _: UserResponse = Depends(require_role("admin")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            _credential_query() + " ORDER BY cr.issued_at DESC, cr.id LIMIT 500"
        ).fetchall()
    return [
        {
            **_public_payload(row),
            "learner_id": str(row["learner_id"]),
            "assessment_attempt_id": (
                str(row["assessment_attempt_id"]) if row["assessment_attempt_id"] else None
            ),
            "revoked_at": row["revoked_at"].isoformat() if row["revoked_at"] else None,
            "revocation_reason": row["revocation_reason"],
        }
        for row in rows
    ]
