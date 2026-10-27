import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.v1.auth import current_user, require_role
from app.core.settings import jwt_secret
from app.db import get_connection
from app.schemas.auth import UserResponse
from app.schemas.passport import (
    ConfirmSkillsRequest,
    CreateShareLinkRequest,
    ManualSkillRequest,
    TargetRolesRequest,
)
from app.services.skill_extraction import (
    MAX_UPLOAD_BYTES,
    SkillAlias,
    extract_document_text,
    match_skills,
)
from app.services.llm_skill_extractor import extract_skills_stage2

router = APIRouter(prefix="/api/v1", tags=["skill passport"])
optional_bearer = HTTPBearer(auto_error=False)
MAX_CANDIDATES = 200


def _read_client_ip(request: Request) -> str:
    if request.client is None:
        raise HTTPException(status_code=400, detail="Unable to determine client address")
    return request.client.host


def _row_to_candidate(row: dict[str, object]) -> dict[str, object]:
    confidence = float(row["confidence"])
    return {
        "candidate_id": str(row["id"]),
        "skill_id": str(row["competency_id"]),
        "skill_name": row["canonical_name"],
        "matched_alias": row["matched_alias"],
        "confidence_score": confidence,
        "requires_manual_review": confidence < 0.9,
        "review_status": row["review_status"],
        "context": row.get("context", ""),
    }


def _taxonomy_aliases(connection: psycopg.Connection) -> list[SkillAlias]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT c.id, c.canonical_name, c.canonical_name AS alias,
                   ARRAY[]::text[] AS must_not_match
            FROM competencies c
            WHERE c.active = true
            UNION ALL
            SELECT c.id, c.canonical_name, a.alias, a.must_not_match
            FROM competency_aliases a
            JOIN competencies c ON c.id = a.competency_id
            WHERE c.active = true
            ORDER BY canonical_name, alias
            """
        ).fetchall()
    return [
        SkillAlias(
            competency_id=str(row["id"]),
            skill_name=row["canonical_name"],
            alias=row["alias"],
            must_not_match=tuple(row["must_not_match"] or ()),
        )
        for row in rows
    ]


@router.get("/passport/taxonomy")
def get_taxonomy(
    _: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, str]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT id, canonical_name
            FROM competencies
            WHERE active = true
            ORDER BY canonical_name
            """
        ).fetchall()
    return [
        {"skill_id": str(row["id"]), "skill_name": row["canonical_name"]}
        for row in rows
    ]


@router.get("/passport/roles")
def get_target_roles(
    _: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, str]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT id, name
            FROM role_catalog
            WHERE active = true
            ORDER BY name
            """
        ).fetchall()
    return [{"role_id": str(row["id"]), "name": row["name"]} for row in rows]


@router.put("/passport/target-roles")
def save_target_roles(
    payload: TargetRolesRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, list[str]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        if payload.role_ids:
            existing = cursor.execute(
                """
                SELECT id FROM role_catalog
                WHERE active = true AND id = ANY(%s)
                """,
                (payload.role_ids,),
            ).fetchall()
            if len(existing) != len(payload.role_ids):
                raise HTTPException(status_code=422, detail="One or more target roles are unavailable")
        cursor.execute("DELETE FROM learner_target_roles WHERE user_id = %s", (UUID(user.id),))
        for role_id in payload.role_ids:
            cursor.execute(
                """
                INSERT INTO learner_target_roles (user_id, role_id)
                VALUES (%s, %s)
                """,
                (UUID(user.id), role_id),
            )
    return {"role_ids": [str(role_id) for role_id in payload.role_ids]}


@router.post("/passport/extract", status_code=201)
async def extract_resume_skills(
    request: Request,
    file: UploadFile = File(...),
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    filename = file.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in {"pdf", "docx"}:
        raise HTTPException(status_code=415, detail="Upload a PDF or DOCX resume")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded resume is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Resume files may not exceed 10 MB")

    try:
        text = extract_document_text(filename, content)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    matches = match_skills(text, _taxonomy_aliases(connection))
    if len(matches) > MAX_CANDIDATES:
        raise HTTPException(
            status_code=422,
            detail=f"Resume matched more than {MAX_CANDIDATES} skills; shorten the document and retry",
        )
    digest = hashlib.sha256(content).hexdigest()
    with connection.cursor(row_factory=dict_row) as cursor:
        upload = cursor.execute(
            """
            INSERT INTO resume_uploads (user_id, storage_key, sha256, size_bytes, delete_after)
            VALUES (%s, %s, %s, %s, now())
            RETURNING id
            """,
            (UUID(user.id), f"ephemeral://{digest}", digest, len(content)),
        ).fetchone()
        run = cursor.execute(
            """
            INSERT INTO resume_extraction_runs (upload_id, extractor_version, status)
            VALUES (%s, 'taxonomy-r14-v1', 'review_required')
            RETURNING id
            """,
            (upload["id"],),
        ).fetchone()
        for match in matches:
            cursor.execute(
                """
                INSERT INTO extracted_skill_candidates
                  (run_id, competency_id, confidence, matched_alias)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (run_id, competency_id) DO UPDATE
                SET confidence = EXCLUDED.confidence,
                    matched_alias = EXCLUDED.matched_alias,
                    review_status = 'pending'
                """,
                (run["id"], UUID(match.competency_id), match.confidence_score, match.alias),
            )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'resume_skills_extracted', 'resume_extraction_run', %s, %s)
            """,
            (
                UUID(user.id),
                run["id"],
                Jsonb({"sha256": digest, "candidate_count": len(matches)}),
            ),
        )
        candidate_rows = cursor.execute(
            """
            SELECT c.id, c.competency_id, co.canonical_name, c.confidence,
                   c.matched_alias, c.review_status::text AS review_status
            FROM extracted_skill_candidates c
            JOIN competencies co ON co.id = c.competency_id
            WHERE c.run_id = %s
            ORDER BY co.canonical_name
            """,
            (run["id"],),
        ).fetchall()
    candidates = [
        {
            **_row_to_candidate(row),
            "context": next(
                (match.context for match in matches if match.competency_id == str(row["competency_id"])),
                "",
            ),
        }
        for row in candidate_rows
    ]
    return {
        "run_id": str(run["id"]),
        "filename": filename,
        "stored_file": False,
        "candidates": candidates,
    }


@router.post("/passport/confirm")
def confirm_resume_skills(
    payload: ConfirmSkillsRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        run = cursor.execute(
            """
            SELECT r.id, r.status::text AS status, u.id AS owner_id
            FROM resume_extraction_runs r
            JOIN resume_uploads u ON u.id = r.upload_id
            WHERE r.id = %s
            FOR UPDATE OF r
            """,
            (payload.run_id,),
        ).fetchone()
        if not run or run["owner_id"] != UUID(user.id):
            raise HTTPException(status_code=404, detail="Extraction run not found")
        if run["status"] != "review_required":
            raise HTTPException(status_code=409, detail="Extraction run has already been reviewed")
        candidates = cursor.execute(
            """
            SELECT id, competency_id, confidence
            FROM extracted_skill_candidates
            WHERE run_id = %s
            FOR UPDATE
            """,
            (payload.run_id,),
        ).fetchall()
        expected_ids = {row["id"] for row in candidates}
        submitted_ids = {decision.candidate_id for decision in payload.decisions}
        if expected_ids != submitted_ids:
            raise HTTPException(
                status_code=422,
                detail="Review every extracted skill exactly once before confirming",
            )

        decision_by_id = {decision.candidate_id: decision for decision in payload.decisions}
        effective_competencies: set[UUID] = set()
        for candidate in candidates:
            decision = decision_by_id[candidate["id"]]
            if decision.decision == "rejected":
                continue
            competency_id = candidate["competency_id"]
            if decision.decision == "edited":
                valid_skill = cursor.execute(
                    """
                    SELECT id FROM competencies
                    WHERE id = %s AND active = true
                    """,
                    (decision.competency_id,),
                ).fetchone()
                if not valid_skill:
                    raise HTTPException(status_code=422, detail="Replacement skill is unavailable")
                competency_id = decision.competency_id
            if competency_id in effective_competencies:
                raise HTTPException(
                    status_code=422,
                    detail="A skill may only be confirmed once per extraction",
                )
            effective_competencies.add(competency_id)

        confirmed = []
        for decision in payload.decisions:
            candidate = next(row for row in candidates if row["id"] == decision.candidate_id)
            competency_id = candidate["competency_id"]
            if decision.decision == "edited":
                valid_skill = cursor.execute(
                    """
                    SELECT id FROM competencies
                    WHERE id = %s AND active = true
                    """,
                    (decision.competency_id,),
                ).fetchone()
                if not valid_skill:
                    raise HTTPException(status_code=422, detail="Replacement skill is unavailable")
                competency_id = decision.competency_id
            cursor.execute(
                """
                UPDATE extracted_skill_candidates
                SET competency_id = %s, review_status = %s
                WHERE id = %s
                """,
                (competency_id, decision.decision, decision.candidate_id),
            )
            if decision.decision == "rejected":
                continue
            cursor.execute(
                """
                INSERT INTO learner_competencies (user_id, competency_id, level, status)
                VALUES (%s, %s, %s, 'claimed')
                ON CONFLICT (user_id, competency_id) DO UPDATE
                SET level = COALESCE(EXCLUDED.level, learner_competencies.level),
                    status = CASE
                      WHEN learner_competencies.status = 'verified' THEN 'verified'::evidence_status
                      ELSE 'claimed'::evidence_status
                    END,
                    updated_at = now()
                """,
                (UUID(user.id), competency_id, decision.level),
            )
            evidence = cursor.execute(
                """
                INSERT INTO evidence
                  (user_id, competency_id, source_type, verification, metadata)
                VALUES (%s, %s, 'resume', 'unverified', %s)
                RETURNING id
                """,
                (
                    UUID(user.id),
                    competency_id,
                    Jsonb({"extraction_run_id": str(payload.run_id)}),
                ),
            ).fetchone()
            confirmed.append(
                {
                    "competency_id": str(competency_id),
                    "evidence_id": str(evidence["id"]),
                }
            )
        cursor.execute(
            """
            UPDATE resume_extraction_runs
            SET status = 'confirmed'
            WHERE id = %s
            """,
            (payload.run_id,),
        )
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'resume_skills_confirmed', 'resume_extraction_run', %s, %s)
            """,
            (
                UUID(user.id),
                payload.run_id,
                Jsonb({"accepted_count": len(confirmed)}),
            ),
        )
    return {"run_id": str(payload.run_id), "confirmed_skills": confirmed}


@router.post("/passport/skills", status_code=201)
def add_manual_skill(
    payload: ManualSkillRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        competency = cursor.execute(
            """
            SELECT id, canonical_name FROM competencies
            WHERE id = %s AND active = true
            """,
            (payload.competency_id,),
        ).fetchone()
        if not competency:
            raise HTTPException(status_code=404, detail="Skill not found in the taxonomy")
        cursor.execute(
            """
            INSERT INTO learner_competencies (user_id, competency_id, level, status)
            VALUES (%s, %s, %s, 'claimed')
            ON CONFLICT (user_id, competency_id) DO UPDATE
            SET level = EXCLUDED.level,
                status = CASE
                  WHEN learner_competencies.status = 'verified' THEN 'verified'::evidence_status
                  ELSE 'claimed'::evidence_status
                END,
                updated_at = now()
            """,
            (UUID(user.id), payload.competency_id, payload.level),
        )
        cursor.execute(
            """
            INSERT INTO evidence (user_id, competency_id, source_type, verification, metadata)
            VALUES (%s, %s, 'manual', 'unverified', %s)
            """,
            (
                UUID(user.id),
                payload.competency_id,
                Jsonb({"self_rated_level": payload.level}),
            ),
        )
    return {
        "skill_id": str(competency["id"]),
        "skill_name": competency["canonical_name"],
        "level": payload.level,
        "status": "claimed",
    }


@router.get("/passport")
def get_passport(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    with connection.cursor(row_factory=dict_row) as cursor:
        skills = cursor.execute(
            """
            SELECT c.id AS skill_id, c.canonical_name AS skill_name, lc.level,
                   lc.status::text AS status,
                   CASE
                     WHEN lc.last_evidence_at IS NULL THEN 'stale'
                     WHEN lc.last_evidence_at >= now() - (
                       COALESCE(c.freshness_half_life_days, 730) * interval '1 day'
                     ) THEN 'current'
                     WHEN lc.last_evidence_at >= now() - (
                       COALESCE(c.freshness_half_life_days, 730) * 2 * interval '1 day'
                     ) THEN 'aging'
                     ELSE 'stale'
                   END AS freshness,
                   lc.updated_at
            FROM learner_competencies lc
            JOIN competencies c ON c.id = lc.competency_id
            WHERE lc.user_id = %s
            ORDER BY c.canonical_name
            """,
            (UUID(user.id),),
        ).fetchall()
        roles = cursor.execute(
            """
            SELECT r.id AS role_id, r.name
            FROM learner_target_roles tr
            JOIN role_catalog r ON r.id = tr.role_id
            WHERE tr.user_id = %s
            ORDER BY r.name
            """,
            (UUID(user.id),),
        ).fetchall()
        evidence_rows = cursor.execute(
            """
            SELECT competency_id, source_type, verification, created_at
            FROM evidence
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (UUID(user.id),),
        ).fetchall()
    evidence_by_skill: dict[UUID, list[dict[str, object]]] = {}
    for evidence in evidence_rows:
        if evidence["competency_id"] is None:
            continue
        evidence_by_skill.setdefault(evidence["competency_id"], []).append(
            {
                "source_type": evidence["source_type"],
                "verification": evidence["verification"],
                "created_at": evidence["created_at"].isoformat(),
            }
        )
    return {
        "skills": [
            {
                **row,
                "skill_id": str(row["skill_id"]),
                "level": row["level"],
                "updated_at": row["updated_at"].isoformat(),
                "evidence": evidence_by_skill.get(row["skill_id"], []),
            }
            for row in skills
        ],
        "target_roles": [
            {"role_id": str(row["role_id"]), "name": row["name"]}
            for row in roles
        ],
    }


@router.get("/passport/share")
def list_share_links(
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        records = cursor.execute(
            """
            SELECT id, sections, expires_in_days, expires_at, max_views,
                   require_verified_employer, revoked_at, created_at,
                   (SELECT count(*) FROM share_access_logs l
                    WHERE l.share_link_id = passport_share_links.id
                      AND l.outcome = 'viewed') AS view_count
            FROM passport_share_links
            WHERE learner_id = %s
            ORDER BY created_at DESC
            """,
            (UUID(user.id),),
        ).fetchall()
    return [
        {
            **record,
            "id": str(record["id"]),
            "expires_at": record["expires_at"].isoformat(),
            "revoked_at": record["revoked_at"].isoformat() if record["revoked_at"] else None,
            "created_at": record["created_at"].isoformat(),
        }
        for record in records
    ]


@router.post("/passport/share", status_code=201)
def create_share_link(
    payload: CreateShareLinkRequest,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    with connection.cursor(row_factory=dict_row) as cursor:
        record = cursor.execute(
            """
            INSERT INTO passport_share_links
              (learner_id, token_hash, sections, expires_in_days, expires_at,
               max_views, require_verified_employer)
            VALUES (%s, %s, %s, %s, now() + (%s * interval '1 day'), %s, %s)
            RETURNING id, expires_at
            """,
            (
                UUID(user.id),
                token_hash,
                Jsonb(payload.sections),
                payload.expires_in_days,
                payload.expires_in_days,
                payload.max_views,
                payload.require_verified_employer,
            ),
        ).fetchone()
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id, details)
            VALUES (%s, 'passport_share_created', 'passport_share_link', %s, %s)
            """,
            (
                UUID(user.id),
                record["id"],
                Jsonb(
                    {
                        "sections": payload.sections,
                        "expires_in_days": payload.expires_in_days,
                        "require_verified_employer": payload.require_verified_employer,
                    }
                ),
            ),
        )
    return {
        "share_id": str(record["id"]),
        "token": token,
        "expires_at": record["expires_at"].isoformat(),
        "sections": payload.sections,
    }


@router.delete("/passport/share/{share_id}", status_code=204)
def revoke_share_link(
    share_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    with connection.cursor(row_factory=dict_row) as cursor:
        record = cursor.execute(
            """
            UPDATE passport_share_links
            SET revoked_at = now()
            WHERE id = %s AND learner_id = %s AND revoked_at IS NULL
            RETURNING id
            """,
            (share_id, UUID(user.id)),
        ).fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="Active share link not found")
        cursor.execute(
            """
            INSERT INTO audit_events (actor_id, action, entity_type, entity_id)
            VALUES (%s, 'passport_share_revoked', 'passport_share_link', %s)
            """,
            (UUID(user.id), share_id),
        )


@router.get("/passport/shared/{token}")
def view_shared_passport(
    token: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    if len(token) > 128:
        raise HTTPException(status_code=404, detail="Share link is unavailable")
    try:
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    except UnicodeEncodeError as error:
        raise HTTPException(status_code=404, detail="Share link is unavailable") from error
    client_ip = _read_client_ip(request)
    viewer = current_user(credentials, connection) if credentials is not None else None

    with connection.cursor(row_factory=dict_row) as cursor:
        link = cursor.execute(
            """
            SELECT id, learner_id, sections, expires_at, max_views,
                   require_verified_employer, revoked_at
            FROM passport_share_links
            WHERE token_hash = %s
            FOR UPDATE
            """,
            (token_hash,),
        ).fetchone()
        if not link:
            raise HTTPException(status_code=404, detail="Share link is unavailable")
        if link["revoked_at"] is not None or link["expires_at"] <= datetime.now(timezone.utc):
            _log_share_access(cursor, link["id"], viewer, "unavailable", client_ip)
            connection.commit()
            raise HTTPException(status_code=404, detail="Share link is unavailable")
        if link["max_views"] is not None:
            views = cursor.execute(
                """
                SELECT count(*) AS count FROM share_access_logs
                WHERE share_link_id = %s AND outcome = 'viewed'
                """,
                (link["id"],),
            ).fetchone()["count"]
            if views >= link["max_views"]:
                _log_share_access(cursor, link["id"], viewer, "view_limit", client_ip)
                connection.commit()
                raise HTTPException(status_code=410, detail="Share link has reached its view limit")
        if link["require_verified_employer"]:
            if viewer is None or "employer" not in viewer.roles:
                _log_share_access(cursor, link["id"], viewer, "employer_sign_in_required", client_ip)
                connection.commit()
                raise HTTPException(status_code=401, detail="Sign in as a verified employer to view")
            if viewer.employer_verification_level != 2:
                _log_share_access(cursor, link["id"], viewer, "employer_verification_required", client_ip)
                connection.commit()
                raise HTTPException(status_code=403, detail="A Level 2 verified employer is required")

        sections = set(link["sections"])
        passport = _build_shared_passport(
            cursor, UUID(str(link["learner_id"])), sections
        )
        _log_share_access(cursor, link["id"], viewer, "viewed", client_ip)
        connection.commit()
    return {"sections": sorted(sections), "passport": passport}


def _build_shared_passport(
    cursor: psycopg.Cursor, learner_id: UUID, sections: set[str]
) -> dict[str, object]:
    result: dict[str, object] = {}
    if "skills" in sections:
        rows = cursor.execute(
            """
            SELECT c.canonical_name AS skill_name, lc.level, lc.status::text AS status,
                   CASE
                     WHEN lc.last_evidence_at IS NULL THEN 'stale'
                     WHEN lc.last_evidence_at >= now() - (
                       COALESCE(c.freshness_half_life_days, 730) * interval '1 day'
                     ) THEN 'current'
                     WHEN lc.last_evidence_at >= now() - (
                       COALESCE(c.freshness_half_life_days, 730) * 2 * interval '1 day'
                     ) THEN 'aging'
                     ELSE 'stale'
                   END AS freshness
            FROM learner_competencies lc
            JOIN competencies c ON c.id = lc.competency_id
            WHERE lc.user_id = %s ORDER BY c.canonical_name
            """,
            (learner_id,),
        ).fetchall()
        result["skills"] = rows
    if "evidence" in sections:
        rows = cursor.execute(
            """
            SELECT c.canonical_name AS skill_name, e.source_type,
                   e.verification, e.created_at
            FROM evidence e
            LEFT JOIN competencies c ON c.id = e.competency_id
            WHERE e.user_id = %s ORDER BY e.created_at DESC
            """,
            (learner_id,),
        ).fetchall()
        result["evidence"] = [
            {
                **row,
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
    if "target_roles" in sections:
        rows = cursor.execute(
            """
            SELECT r.name
            FROM learner_target_roles tr
            JOIN role_catalog r ON r.id = tr.role_id
            WHERE tr.user_id = %s ORDER BY r.name
            """,
            (learner_id,),
        ).fetchall()
        result["target_roles"] = [row["name"] for row in rows]
    if "credentials" in sections:
        rows = cursor.execute(
            """
            SELECT c.canonical_name AS skill_name, cr.level, cr.evidence_tier, cr.issued_at
            FROM credentials cr
            JOIN competencies c ON c.id = cr.competency_id
            WHERE cr.learner_id = %s AND cr.revoked_at IS NULL
            ORDER BY c.canonical_name
            """,
            (learner_id,),
        ).fetchall()
        result["credentials"] = [
            {
                **row,
                "issued_at": row["issued_at"].isoformat(),
            }
            for row in rows
        ]
    return result


def _log_share_access(
    cursor: psycopg.Cursor,
    share_link_id: UUID,
    viewer: UserResponse | None,
    outcome: str,
    client_ip: str,
) -> None:
    ip_hash = hmac.new(
        jwt_secret(), client_ip.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    cursor.execute(
        """
        INSERT INTO share_access_logs (share_link_id, viewer_id, outcome, ip_hash)
        VALUES (%s, %s, %s, %s)
        """,
        (
            share_link_id,
            UUID(viewer.id) if viewer is not None else None,
            outcome,
            ip_hash,
        ),
    )


@router.get("/passport/share/{share_id}/access-log")
def get_share_access_log(
    share_id: UUID,
    user: UserResponse = Depends(require_role("trainee")),
    connection: psycopg.Connection = Depends(get_connection),
) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        link = cursor.execute(
            """
            SELECT id FROM passport_share_links
            WHERE id = %s AND learner_id = %s
            """,
            (share_id, UUID(user.id)),
        ).fetchone()
        if not link:
            raise HTTPException(status_code=404, detail="Share link not found")
        records = cursor.execute(
            """
            SELECT viewer_id, accessed_at, outcome
            FROM share_access_logs
            WHERE share_link_id = %s
            ORDER BY accessed_at DESC
            """,
            (link["id"],),
        ).fetchall()
    return [
        {
            **record,
            "viewer_id": str(record["viewer_id"]) if record["viewer_id"] else None,
            "accessed_at": record["accessed_at"].isoformat(),
        }
        for record in records
    ]
