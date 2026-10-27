CREATE TABLE learner_role_match_feedback (
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES role_catalog(id) ON DELETE CASCADE,
  feedback text NOT NULL CHECK (feedback IN ('interested', 'not_interested')),
  reason text CHECK (reason IS NULL OR length(reason) <= 500),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (learner_id, role_id)
);
CREATE INDEX learner_role_match_feedback_role_idx
  ON learner_role_match_feedback (role_id, feedback);

CREATE INDEX role_match_runs_learner_recent_idx
  ON role_match_runs (learner_id, created_at DESC);
