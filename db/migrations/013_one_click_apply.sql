ALTER TABLE applications
  ADD COLUMN application_snapshot jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN profile_share_consent_at timestamptz,
  ADD COLUMN profile_share_consent_version text,
  ADD COLUMN resume_text text NOT NULL DEFAULT '',
  ADD COLUMN cover_letter text,
  ADD COLUMN extra_answers jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN withdrawn_at timestamptz;

CREATE TABLE job_application_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  prompt text NOT NULL CHECK (length(trim(prompt)) BETWEEN 1 AND 1000),
  answer_type text NOT NULL CHECK (answer_type IN ('text', 'yes_no', 'single_choice')),
  options jsonb NOT NULL DEFAULT '[]',
  required boolean NOT NULL DEFAULT false,
  sort_order integer NOT NULL DEFAULT 0,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (answer_type = 'single_choice' AND jsonb_typeof(options) = 'array' AND jsonb_array_length(options) > 0)
    OR answer_type != 'single_choice'
  )
);
CREATE INDEX job_application_questions_active_idx
  ON job_application_questions (job_id, sort_order)
  WHERE active;

CREATE TABLE application_status_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id uuid NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  actor_id uuid REFERENCES users(id) ON DELETE SET NULL,
  actor_role text NOT NULL CHECK (actor_role IN ('trainee', 'employer', 'admin', 'system')),
  status text NOT NULL CHECK (
    status IN ('applied', 'heard_back', 'interview', 'offer', 'no_reply',
               'likely_closed', 'rejected', 'withdrawn')
  ),
  note text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX application_status_events_history_idx
  ON application_status_events (application_id, created_at DESC);
