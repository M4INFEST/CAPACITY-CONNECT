CREATE INDEX IF NOT EXISTS demand_observations_latest_idx
  ON demand_observations (role_id, competency_id, observed_at DESC);

CREATE TABLE employer_feedback_goals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id uuid NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  employer_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES role_catalog(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id) ON DELETE CASCADE,
  target_level smallint NOT NULL CHECK (target_level BETWEEN 1 AND 5),
  feedback_note text NOT NULL CHECK (length(trim(feedback_note)) BETWEEN 3 AND 1000),
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
CREATE INDEX employer_feedback_goals_active_idx
  ON employer_feedback_goals (learner_id, role_id, competency_id, created_at DESC)
  WHERE completed_at IS NULL;
