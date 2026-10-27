ALTER TABLE assessments
  ADD COLUMN time_limit_minutes integer NOT NULL DEFAULT 30
    CHECK (time_limit_minutes BETWEEN 5 AND 180),
  ADD COLUMN min_questions integer NOT NULL DEFAULT 5
    CHECK (min_questions BETWEEN 1 AND 50),
  ADD COLUMN max_questions integer NOT NULL DEFAULT 10
    CHECK (max_questions BETWEEN 1 AND 100),
  ADD COLUMN target_level smallint NOT NULL DEFAULT 3
    CHECK (target_level BETWEEN 1 AND 5),
  ADD CONSTRAINT assessments_question_range_check
    CHECK (min_questions <= max_questions);

ALTER TABLE assessment_questions
  ADD COLUMN question_type text NOT NULL DEFAULT 'multiple_choice'
    CHECK (question_type IN ('multiple_choice', 'multi_select', 'short_answer', 'scenario', 'code_task')),
  ADD COLUMN options jsonb NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(options) = 'array'),
  ADD COLUMN explanation text,
  ADD COLUMN estimated_time_seconds integer NOT NULL DEFAULT 90
    CHECK (estimated_time_seconds BETWEEN 10 AND 3600),
  ADD COLUMN moderation_status text NOT NULL DEFAULT 'pending'
    CHECK (moderation_status IN ('pending', 'approved', 'rejected')),
  ADD COLUMN moderated_by uuid REFERENCES users(id),
  ADD COLUMN moderation_note text,
  ADD COLUMN moderated_at timestamptz;

ALTER TABLE assessment_attempts
  ADD COLUMN enrollment_id uuid REFERENCES enrollments(id),
  ADD COLUMN evidence_tier text NOT NULL DEFAULT 'self_check'
    CHECK (evidence_tier IN ('self_check', 'verified')),
  ADD COLUMN status text NOT NULL DEFAULT 'in_progress'
    CHECK (status IN ('in_progress', 'submitted', 'expired')),
  ADD COLUMN deadline_at timestamptz,
  ADD COLUMN explanation text,
  ADD COLUMN integrity_flag_count integer NOT NULL DEFAULT 0
    CHECK (integrity_flag_count >= 0);

UPDATE assessment_questions
SET elo_rating = 700 + (difficulty_level * 100)
WHERE response_count = 0 AND elo_rating = 1000;

UPDATE assessment_attempts aa
SET deadline_at = aa.started_at + (a.time_limit_minutes * interval '1 minute')
FROM assessments a
WHERE aa.assessment_id = a.id AND aa.deadline_at IS NULL;

UPDATE assessment_attempts
SET status = 'submitted'
WHERE submitted_at IS NOT NULL;

WITH ranked_active_attempts AS (
  SELECT id,
         row_number() OVER (
           PARTITION BY learner_id
           ORDER BY started_at DESC, id DESC
         ) AS position
  FROM assessment_attempts
  WHERE status = 'in_progress'
)
UPDATE assessment_attempts aa
SET status = 'expired', submitted_at = COALESCE(aa.submitted_at, now())
FROM ranked_active_attempts ranked
WHERE ranked.id = aa.id AND ranked.position > 1;

ALTER TABLE assessment_responses
  ADD COLUMN submitted boolean NOT NULL DEFAULT false;

CREATE TABLE assessment_policy (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  attempts_per_week integer NOT NULL DEFAULT 3 CHECK (attempts_per_week BETWEEN 1 AND 50),
  updated_by uuid REFERENCES users(id),
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO assessment_policy (singleton) VALUES (true);

CREATE TABLE assessment_attempt_events (
  id bigserial PRIMARY KEY,
  attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
  event_type text NOT NULL CHECK (event_type IN ('tab_hidden', 'tab_visible', 'focus_lost')),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE assessment_practice_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
  question_id uuid NOT NULL REFERENCES assessment_questions(id),
  answer jsonb NOT NULL,
  correct boolean NOT NULL,
  attempted_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (attempt_id, question_id)
);

CREATE INDEX assessment_questions_approved_selection_idx
  ON assessment_questions (assessment_id, competency_id, elo_rating)
  WHERE active AND moderation_status = 'approved';
CREATE INDEX assessment_attempts_learner_week_idx
  ON assessment_attempts (learner_id, started_at DESC);
CREATE UNIQUE INDEX assessment_attempts_single_active_learner_idx
  ON assessment_attempts (learner_id)
  WHERE status = 'in_progress';
CREATE INDEX assessment_attempt_events_attempt_idx
  ON assessment_attempt_events (attempt_id, occurred_at);
CREATE INDEX assessment_practice_responses_attempt_idx
  ON assessment_practice_responses (attempt_id, attempted_at DESC);
