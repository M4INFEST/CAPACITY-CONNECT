ALTER TABLE credentials
  ADD COLUMN course_version_id uuid REFERENCES course_versions(id),
  ADD COLUMN evidence_id uuid REFERENCES evidence(id),
  ADD COLUMN expires_at timestamptz;

CREATE UNIQUE INDEX credentials_attempt_competency_uq
  ON credentials (assessment_attempt_id, competency_id)
  WHERE assessment_attempt_id IS NOT NULL;

CREATE INDEX credentials_learner_issued_idx
  ON credentials (learner_id, issued_at DESC);
