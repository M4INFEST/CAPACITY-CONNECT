CREATE TABLE learning_sponsorship_codes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code_hash char(64) NOT NULL UNIQUE,
  code_hint text NOT NULL,
  course_version_id uuid REFERENCES course_versions(id) ON DELETE CASCADE,
  max_uses integer NOT NULL CHECK (max_uses > 0),
  expires_at timestamptz,
  active boolean NOT NULL DEFAULT true,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE learning_sponsorship_redemptions (
  code_id uuid NOT NULL REFERENCES learning_sponsorship_codes(id),
  enrollment_id uuid NOT NULL UNIQUE REFERENCES enrollments(id) ON DELETE CASCADE,
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  redeemed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (code_id, learner_id)
);

ALTER TABLE enrollments
  ADD COLUMN funding_type text NOT NULL DEFAULT 'free'
    CHECK (funding_type IN ('free', 'sponsored')),
  ADD COLUMN sponsorship_code_id uuid REFERENCES learning_sponsorship_codes(id);

ALTER TABLE lessons
  ADD COLUMN content text,
  ADD COLUMN duration_seconds integer NOT NULL DEFAULT 60
    CHECK (duration_seconds BETWEEN 1 AND 86400),
  ADD COLUMN assessment_required boolean NOT NULL DEFAULT true;

CREATE TABLE lesson_progress (
  enrollment_id uuid NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
  lesson_id uuid NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  last_position_seconds integer NOT NULL DEFAULT 0 CHECK (last_position_seconds >= 0),
  active_seconds integer NOT NULL DEFAULT 0 CHECK (active_seconds >= 0),
  last_heartbeat_at timestamptz,
  notes text NOT NULL DEFAULT '',
  completed_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (enrollment_id, lesson_id)
);

CREATE TABLE learning_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id uuid NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
  lesson_id uuid REFERENCES lessons(id) ON DELETE SET NULL,
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  submission_type text NOT NULL CHECK (submission_type IN ('lab', 'project')),
  title text NOT NULL,
  submission_url text,
  submission_text text,
  status text NOT NULL DEFAULT 'submitted'
    CHECK (status IN ('submitted', 'reviewed', 'changes_requested')),
  trainer_feedback text,
  reviewed_by uuid REFERENCES users(id),
  submitted_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz,
  CHECK (submission_url IS NOT NULL OR submission_text IS NOT NULL)
);
CREATE INDEX learning_submissions_review_idx
  ON learning_submissions (status, submitted_at);

CREATE TABLE learning_discussions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id uuid NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
  author_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  parent_id uuid REFERENCES learning_discussions(id) ON DELETE CASCADE,
  body text NOT NULL CHECK (length(body) BETWEEN 1 AND 5000),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX learning_discussions_enrollment_idx
  ON learning_discussions (enrollment_id, created_at);
