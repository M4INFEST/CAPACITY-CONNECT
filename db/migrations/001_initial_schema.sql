CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE app_role AS ENUM ('trainee', 'trainer', 'employer', 'admin');
CREATE TYPE evidence_status AS ENUM ('claimed', 'provisional', 'verified');
CREATE TYPE course_version_status AS ENUM
  ('draft', 'pending_approval', 'approved', 'published', 'rejected', 'archived');
CREATE TYPE approval_status AS ENUM
  ('pending', 'approved', 'needs_info', 'rejected', 'withdrawn');
CREATE TYPE approval_mode AS ENUM ('strict', 'scaled');
CREATE TYPE application_status AS ENUM
  ('applied', 'heard_back', 'interview', 'offer', 'no_reply', 'likely_closed', 'rejected');

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL,
  password_hash text,
  email_verified_at timestamptz,
  mfa_enabled boolean NOT NULL DEFAULT false,
  account_status text NOT NULL DEFAULT 'pending'
    CHECK (account_status IN ('pending', 'active', 'suspended', 'deleted')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_lower_uq ON users (lower(email));

CREATE TABLE user_roles (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role app_role NOT NULL,
  granted_at timestamptz NOT NULL DEFAULT now(),
  granted_by uuid REFERENCES users(id),
  PRIMARY KEY (user_id, role)
);

CREATE TABLE learner_preferences (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  weekly_study_hours numeric(5,2) CHECK (weekly_study_hours >= 0),
  budget_cents integer CHECK (budget_cents >= 0),
  learning_format text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE trainer_applications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  status approval_status NOT NULL DEFAULT 'pending',
  expertise text[] NOT NULL DEFAULT '{}',
  submitted_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz,
  reviewed_by uuid REFERENCES users(id),
  review_reason text
);

CREATE TABLE employer_profiles (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  company_name text NOT NULL,
  website text,
  industry text,
  verification_level smallint NOT NULL DEFAULT 0 CHECK (verification_level BETWEEN 0 AND 2),
  verified_at timestamptz
);

CREATE TABLE approval_policy (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  mode approval_mode NOT NULL DEFAULT 'strict',
  updated_by uuid REFERENCES users(id),
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO approval_policy (singleton, mode) VALUES (true, 'strict');

CREATE TABLE audit_events (
  id bigserial PRIMARY KEY,
  actor_id uuid REFERENCES users(id),
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid,
  details jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE competencies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id uuid REFERENCES competencies(id),
  canonical_name text NOT NULL UNIQUE,
  description text,
  level_descriptors jsonb NOT NULL DEFAULT '{}',
  freshness_half_life_days integer CHECK (freshness_half_life_days > 0),
  embedding vector(384),
  active boolean NOT NULL DEFAULT true
);

CREATE TABLE competency_aliases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  competency_id uuid NOT NULL REFERENCES competencies(id) ON DELETE CASCADE,
  alias text NOT NULL,
  symbol_sensitive boolean NOT NULL DEFAULT false,
  must_not_match text[] NOT NULL DEFAULT '{}',
  UNIQUE (competency_id, alias)
);

CREATE TABLE learner_competencies (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id),
  level smallint CHECK (level BETWEEN 1 AND 5),
  status evidence_status NOT NULL DEFAULT 'claimed',
  freshness text NOT NULL DEFAULT 'current'
    CHECK (freshness IN ('current', 'aging', 'stale')),
  last_evidence_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, competency_id)
);

CREATE TABLE evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  competency_id uuid REFERENCES competencies(id),
  source_type text NOT NULL
    CHECK (source_type IN ('resume', 'project', 'work_history', 'credential',
                           'assessment', 'reference', 'manual')),
  verification text NOT NULL DEFAULT 'unverified'
    CHECK (verification IN ('unverified', 'provisional', 'verified', 'rejected')),
  source_url text,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE resume_uploads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  storage_key text NOT NULL,
  sha256 char(64) NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 10485760),
  uploaded_at timestamptz NOT NULL DEFAULT now(),
  delete_after timestamptz
);

CREATE TABLE resume_extraction_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  upload_id uuid NOT NULL REFERENCES resume_uploads(id) ON DELETE CASCADE,
  extractor_version text NOT NULL,
  status text NOT NULL DEFAULT 'review_required'
    CHECK (status IN ('review_required', 'confirmed', 'discarded', 'failed')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE extracted_skill_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES resume_extraction_runs(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id),
  confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  review_status text NOT NULL DEFAULT 'pending'
    CHECK (review_status IN ('pending', 'accepted', 'edited', 'rejected')),
  matched_alias text,
  UNIQUE (run_id, competency_id)
);

CREATE TABLE resume_claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  evidence_id uuid NOT NULL REFERENCES evidence(id),
  claim_text text NOT NULL,
  metric_prompt text,
  user_provided_metric text,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE resume_drafts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_role text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE resume_draft_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id uuid NOT NULL REFERENCES resume_drafts(id) ON DELETE CASCADE,
  claim_id uuid NOT NULL REFERENCES resume_claims(id),
  line_text text NOT NULL,
  user_approved_at timestamptz,
  sort_order integer NOT NULL
);

CREATE TABLE courses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  trainer_id uuid NOT NULL REFERENCES users(id),
  title text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE course_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id uuid NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  version integer NOT NULL CHECK (version > 0),
  status course_version_status NOT NULL DEFAULT 'draft',
  title text NOT NULL,
  description text,
  price_cents integer NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
  duration_hours numeric(6,2) CHECK (duration_hours >= 0),
  content jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_id, version)
);

CREATE TABLE course_version_competencies (
  course_version_id uuid NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id),
  level_taught smallint CHECK (level_taught BETWEEN 1 AND 5),
  PRIMARY KEY (course_version_id, competency_id)
);

CREATE TABLE course_prerequisites (
  course_version_id uuid NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  prerequisite_competency_id uuid NOT NULL REFERENCES competencies(id),
  minimum_level smallint NOT NULL CHECK (minimum_level BETWEEN 1 AND 5),
  PRIMARY KEY (course_version_id, prerequisite_competency_id)
);

CREATE TABLE course_approval_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_version_id uuid NOT NULL REFERENCES course_versions(id),
  submitted_by uuid NOT NULL REFERENCES users(id),
  mode_at_submission approval_mode NOT NULL DEFAULT 'strict',
  risk_level text NOT NULL CHECK (risk_level IN ('low', 'high')),
  status approval_status NOT NULL DEFAULT 'pending',
  assigned_reviewer uuid REFERENCES users(id),
  decided_by uuid REFERENCES users(id),
  decision_note text,
  submitted_at timestamptz NOT NULL DEFAULT now(),
  decided_at timestamptz
);

CREATE TABLE course_approval_events (
  id bigserial PRIMARY KEY,
  request_id uuid NOT NULL REFERENCES course_approval_requests(id),
  actor_id uuid NOT NULL REFERENCES users(id),
  decision text NOT NULL,
  note text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE enrollments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id),
  course_version_id uuid NOT NULL REFERENCES course_versions(id),
  status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'completed', 'cancelled')),
  enrolled_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  UNIQUE (learner_id, course_version_id)
);

CREATE TABLE lessons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_version_id uuid NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  title text NOT NULL,
  content_ref text,
  sort_order integer NOT NULL
);

CREATE TABLE lesson_checkpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id uuid NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  question jsonb NOT NULL,
  sort_order integer NOT NULL
);

CREATE TABLE checkpoint_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id),
  checkpoint_id uuid NOT NULL REFERENCES lesson_checkpoints(id),
  answer jsonb NOT NULL,
  correct boolean NOT NULL,
  answered_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assessments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_version_id uuid REFERENCES course_versions(id),
  title text NOT NULL,
  active boolean NOT NULL DEFAULT true
);

CREATE TABLE assessment_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id),
  prompt text NOT NULL,
  answer_key jsonb NOT NULL,
  difficulty_level smallint NOT NULL CHECK (difficulty_level BETWEEN 1 AND 5),
  elo_rating integer NOT NULL DEFAULT 1000,
  response_count integer NOT NULL DEFAULT 0 CHECK (response_count >= 0),
  calibration_status text NOT NULL DEFAULT 'uncalibrated'
    CHECK (calibration_status IN ('uncalibrated', 'calibrated')),
  active boolean NOT NULL DEFAULT true
);

CREATE TABLE learner_skill_ratings (
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id),
  elo_rating integer NOT NULL DEFAULT 1000,
  uncertainty numeric(8,3) NOT NULL DEFAULT 350 CHECK (uncertainty >= 0),
  response_count integer NOT NULL DEFAULT 0 CHECK (response_count >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (learner_id, competency_id)
);

CREATE TABLE assessment_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessment_id uuid NOT NULL REFERENCES assessments(id),
  learner_id uuid NOT NULL REFERENCES users(id),
  started_at timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz,
  level_min smallint CHECK (level_min BETWEEN 1 AND 5),
  level_max smallint CHECK (level_max BETWEEN 1 AND 5),
  confidence text CHECK (confidence IN ('low', 'medium', 'high')),
  provisional boolean NOT NULL DEFAULT true,
  CHECK (level_min IS NULL OR level_max IS NULL OR level_min <= level_max)
);

CREATE TABLE assessment_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
  question_id uuid NOT NULL REFERENCES assessment_questions(id),
  answer jsonb,
  correct boolean,
  learner_confidence smallint CHECK (learner_confidence BETWEEN 1 AND 5),
  dont_know boolean NOT NULL DEFAULT false,
  answered_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (attempt_id, question_id)
);

CREATE TABLE credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id),
  competency_id uuid NOT NULL REFERENCES competencies(id),
  assessment_attempt_id uuid REFERENCES assessment_attempts(id),
  level smallint NOT NULL CHECK (level BETWEEN 1 AND 5),
  evidence_tier text NOT NULL
    CHECK (evidence_tier IN ('self_check', 'verified', 'proctored')),
  issued_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  revocation_reason text
);

CREATE TABLE role_catalog (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  description text,
  active boolean NOT NULL DEFAULT true
);

CREATE TABLE role_competencies (
  role_id uuid NOT NULL REFERENCES role_catalog(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id),
  required_level smallint NOT NULL CHECK (required_level BETWEEN 1 AND 5),
  importance numeric(6,5) NOT NULL CHECK (importance BETWEEN 0 AND 1),
  PRIMARY KEY (role_id, competency_id)
);

CREATE TABLE demand_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  role_id uuid NOT NULL REFERENCES role_catalog(id),
  competency_id uuid NOT NULL REFERENCES competencies(id),
  source_name text NOT NULL,
  source_url text,
  observed_at timestamptz NOT NULL,
  sample_size integer NOT NULL CHECK (sample_size >= 0),
  licensed_or_open boolean NOT NULL,
  demand_score numeric(8,5),
  provenance jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE role_match_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES role_catalog(id),
  scoring_version text NOT NULL,
  score numeric(6,5) NOT NULL CHECK (score BETWEEN 0 AND 1),
  component_scores jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE roadmap_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES role_catalog(id),
  version integer NOT NULL CHECK (version > 0),
  change_reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (learner_id, role_id, version)
);

CREATE TABLE roadmap_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  roadmap_version_id uuid NOT NULL REFERENCES roadmap_versions(id) ON DELETE CASCADE,
  course_version_id uuid REFERENCES course_versions(id),
  competency_id uuid REFERENCES competencies(id),
  due_at timestamptz,
  status text NOT NULL DEFAULT 'planned'
    CHECK (status IN ('planned', 'in_progress', 'completed', 'skipped')),
  CHECK (course_version_id IS NOT NULL OR competency_id IS NOT NULL)
);

CREATE TABLE jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  employer_id uuid REFERENCES users(id),
  role_id uuid REFERENCES role_catalog(id),
  title text NOT NULL,
  source_name text NOT NULL,
  source_url text,
  source_observed_at timestamptz,
  active boolean NOT NULL DEFAULT true
);

CREATE TABLE applications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES jobs(id),
  status application_status NOT NULL DEFAULT 'applied',
  applied_at timestamptz NOT NULL DEFAULT now(),
  last_employer_activity_at timestamptz,
  likely_closed_at timestamptz,
  UNIQUE (learner_id, job_id)
);

CREATE TABLE passport_share_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash char(64) NOT NULL UNIQUE,
  sections jsonb NOT NULL,
  expires_in_days smallint NOT NULL DEFAULT 14 CHECK (expires_in_days IN (7, 14, 30, 90)),
  expires_at timestamptz NOT NULL DEFAULT (now() + interval '14 days'),
  max_views integer CHECK (max_views > 0),
  require_verified_employer boolean NOT NULL DEFAULT false,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE share_access_logs (
  id bigserial PRIMARY KEY,
  share_link_id uuid NOT NULL REFERENCES passport_share_links(id) ON DELETE CASCADE,
  viewer_id uuid REFERENCES users(id),
  accessed_at timestamptz NOT NULL DEFAULT now(),
  outcome text NOT NULL,
  ip_hash char(64)
);

CREATE INDEX learner_competencies_competency_idx ON learner_competencies (competency_id);
CREATE INDEX evidence_user_created_idx ON evidence (user_id, created_at DESC);
CREATE INDEX course_versions_status_idx ON course_versions (status);
CREATE INDEX course_approval_queue_idx ON course_approval_requests (status, submitted_at);
CREATE INDEX assessment_questions_selection_idx
  ON assessment_questions (assessment_id, competency_id, active, elo_rating);
CREATE INDEX applications_status_applied_idx ON applications (status, applied_at);
CREATE INDEX demand_observations_role_competency_idx
  ON demand_observations (role_id, competency_id, observed_at DESC);
CREATE INDEX share_access_logs_link_accessed_idx
  ON share_access_logs (share_link_id, accessed_at DESC);
