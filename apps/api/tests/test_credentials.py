import unittest
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

from app.api.v1.credentials import (
    _credential_pdf,
    _public_payload,
    _qr_drawing,
    issue_attempt_credentials,
)


class CursorStub:
    def __init__(self, skill_rows: list[dict[str, object]]) -> None:
        self.skill_rows = skill_rows
        self.query_count = 0
        self.fetchone_count = 0

    def execute(self, *_: object) -> "CursorStub":
        self.query_count += 1
        return self

    def fetchall(self) -> list[dict[str, object]]:
        return self.skill_rows

    def fetchone(self) -> dict[str, UUID] | None:
        self.fetchone_count += 1
        if self.fetchone_count == 1:
            return {"id": UUID("75d775ee-e949-43d5-8b16-c148b3f0ea44")}
        if self.fetchone_count == 2:
            return {"id": UUID("a4f5a1e0-5c80-4bc0-bcb4-ae35b87b7a77")}
        return None


class CredentialIssuanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cursor = Mock()
        self.attempt = {
            "evidence_tier": "self_check",
            "status": "submitted",
            "level_min": 4,
            "target_level": 3,
        }

    def test_self_check_never_issues_credentials(self) -> None:
        self.assertEqual(issue_attempt_credentials(self.cursor, self.attempt), [])
        self.cursor.execute.assert_not_called()

    def test_failing_assessment_never_issues_credentials(self) -> None:
        attempt = {**self.attempt, "evidence_tier": "verified", "level_min": 2}
        self.assertEqual(issue_attempt_credentials(self.cursor, attempt), [])
        self.cursor.execute.assert_not_called()

    def test_qualifying_verified_attempt_issues_skill_credential(self) -> None:
        cursor = CursorStub(
            [
                {
                    "competency_id": UUID("95464486-5224-4ad6-a06b-f0fe901c7740"),
                    "practical_count": 1,
                    "knowledge_count": 1,
                    "scored_count": 2,
                    "question_count": 2,
                    "rating": 1600,
                    "uncertainty": 60,
                }
            ]
        )
        attempt = {
            **self.attempt,
            "evidence_tier": "verified",
            "id": UUID("15e4ac00-a4e8-46fd-b2c7-60a432620e37"),
            "learner_id": UUID("60859f22-c38e-4da7-946f-e3bf2f5f6b8d"),
            "course_version_id": UUID("78819a2b-1f49-431d-8b23-3022be294cc1"),
        }

        result = issue_attempt_credentials(cursor, attempt)

        self.assertEqual(result, ["a4f5a1e0-5c80-4bc0-bcb4-ae35b87b7a77"])
        self.assertEqual(cursor.query_count, 5)


class CredentialArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.credential = {
            "credential_id": "a4f5a1e0-5c80-4bc0-bcb4-ae35b87b7a77",
            "holder": "Learner 12345678",
            "course": "Data foundations",
            "skill": "Data analysis",
            "level": 3,
            "evidence_tier": "verified",
            "issued_at": "2026-10-23T00:00:00+00:00",
            "expires_at": None,
            "status": "valid",
            "verification_url": "https://example.test/verify/a4f5a1e0-5c80-4bc0-bcb4-ae35b87b7a77",
        }

    def test_public_payload_exposes_only_verification_fields(self) -> None:
        row = {
            "id": UUID(self.credential["credential_id"]),
            "course_title": "Data foundations",
            "skill_name": "Data analysis",
            "level": 3,
            "evidence_tier": "verified",
            "issued_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
            "expires_at": None,
            "status": "valid",
        }
        payload = _public_payload(row)
        self.assertNotIn("email", payload)
        self.assertNotIn("learner_id", payload)
        self.assertEqual(payload["evidence_tier"], "verified")

    def test_pdf_and_qr_artifacts_are_generated(self) -> None:
        from reportlab.graphics import renderSVG

        pdf = _credential_pdf(self.credential)
        drawing = _qr_drawing(self.credential["verification_url"])
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(drawing.width, 0)
        self.assertGreater(drawing.height, 0)
        self.assertIn("<svg", renderSVG.drawToString(drawing))


if __name__ == "__main__":
    unittest.main()
