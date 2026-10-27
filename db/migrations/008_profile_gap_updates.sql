UPDATE competencies
SET freshness_half_life_days = CASE
  WHEN canonical_name IN (
    'Django', 'FastAPI', 'Kubernetes', 'Node.js', 'React', 'Vue.js'
  ) THEN 365
  WHEN canonical_name IN (
    'C', 'C#', 'C++', 'Git', 'HTML', 'Java', 'JavaScript', 'PostgreSQL',
    'Python', 'SQL', 'TypeScript'
  ) THEN 1825
  ELSE COALESCE(freshness_half_life_days, 730)
END
WHERE freshness_half_life_days IS NULL;

UPDATE learner_competencies lc
SET last_evidence_at = (
  SELECT max(e.created_at)
  FROM evidence e
  WHERE e.user_id = lc.user_id AND e.competency_id = lc.competency_id
    AND e.verification IN ('provisional', 'verified')
)
WHERE lc.last_evidence_at IS NULL
  AND EXISTS (
    SELECT 1 FROM evidence e
    WHERE e.user_id = lc.user_id AND e.competency_id = lc.competency_id
      AND e.verification IN ('provisional', 'verified')
  );

CREATE TABLE assessment_skill_profile_updates (
  attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id),
  evidence_id uuid NOT NULL REFERENCES evidence(id),
  credential_id uuid REFERENCES credentials(id),
  previous_level smallint CHECK (previous_level BETWEEN 1 AND 5),
  updated_level smallint NOT NULL CHECK (updated_level BETWEEN 1 AND 5),
  evidence_quality text NOT NULL CHECK (evidence_quality IN ('provisional', 'verified')),
  score numeric(5,4) NOT NULL CHECK (score BETWEEN 0 AND 1),
  average_question_difficulty numeric(4,2) NOT NULL
    CHECK (average_question_difficulty BETWEEN 1 AND 5),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (attempt_id, competency_id)
);

CREATE TABLE learner_readiness_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES role_catalog(id),
  readiness_before numeric(5,2) NOT NULL CHECK (readiness_before BETWEEN 0 AND 100),
  readiness_after numeric(5,2) NOT NULL CHECK (readiness_after BETWEEN 0 AND 100),
  skill_changes jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (attempt_id, role_id)
);
CREATE INDEX learner_readiness_snapshots_history_idx
  ON learner_readiness_snapshots (learner_id, role_id, created_at DESC);

CREATE TABLE learner_freshness_acknowledgements (
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id) ON DELETE CASCADE,
  acknowledged_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (learner_id, competency_id)
);
