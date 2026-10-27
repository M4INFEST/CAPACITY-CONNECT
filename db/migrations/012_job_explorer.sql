ALTER TABLE jobs
  ADD COLUMN description text NOT NULL DEFAULT '',
  ADD COLUMN location text,
  ADD COLUMN job_type text
    CHECK (job_type IS NULL OR job_type IN ('full_time', 'part_time', 'contract', 'internship')),
  ADD COLUMN experience_min_years numeric(4,1)
    CHECK (experience_min_years IS NULL OR experience_min_years BETWEEN 0 AND 60),
  ADD COLUMN experience_max_years numeric(4,1)
    CHECK (experience_max_years IS NULL OR experience_max_years BETWEEN 0 AND 60),
  ADD COLUMN salary_min_cents bigint
    CHECK (salary_min_cents IS NULL OR salary_min_cents >= 0),
  ADD COLUMN salary_max_cents bigint
    CHECK (salary_max_cents IS NULL OR salary_max_cents >= 0),
  ADD COLUMN salary_currency char(3) NOT NULL DEFAULT 'INR',
  ADD COLUMN external_apply_url text
    CHECK (external_apply_url IS NULL OR external_apply_url ~ '^https://'),
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
  ADD CONSTRAINT jobs_experience_range_check
    CHECK (
      experience_min_years IS NULL OR experience_max_years IS NULL
      OR experience_min_years <= experience_max_years
    ),
  ADD CONSTRAINT jobs_salary_range_check
    CHECK (
      salary_min_cents IS NULL OR salary_max_cents IS NULL
      OR salary_min_cents <= salary_max_cents
    );

CREATE INDEX jobs_active_created_idx ON jobs (created_at DESC) WHERE active;
CREATE INDEX jobs_active_location_idx ON jobs (lower(location)) WHERE active;

CREATE TABLE job_required_competencies (
  job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id),
  required_level smallint NOT NULL CHECK (required_level BETWEEN 1 AND 5),
  importance numeric(6,5) NOT NULL DEFAULT 1 CHECK (importance BETWEEN 0 AND 1),
  PRIMARY KEY (job_id, competency_id)
);
CREATE INDEX job_required_competencies_skill_idx
  ON job_required_competencies (competency_id, job_id);

CREATE TABLE learner_saved_jobs (
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (learner_id, job_id)
);
CREATE INDEX learner_saved_jobs_recent_idx
  ON learner_saved_jobs (learner_id, created_at DESC);

CREATE TABLE learner_job_alerts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id uuid REFERENCES role_catalog(id) ON DELETE CASCADE,
  location text,
  job_type text
    CHECK (job_type IS NULL OR job_type IN ('full_time', 'part_time', 'contract', 'internship')),
  min_salary_cents bigint CHECK (min_salary_cents IS NULL OR min_salary_cents >= 0),
  competency_ids uuid[] NOT NULL DEFAULT '{}',
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT learner_job_alerts_role_id_learner_id_key UNIQUE (learner_id, role_id, location, job_type)
);
CREATE INDEX learner_job_alerts_enabled_idx
  ON learner_job_alerts (enabled, updated_at DESC) WHERE enabled;

CREATE TABLE external_job_application_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  reported_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (learner_id, job_id)
);
CREATE INDEX external_job_application_reports_recent_idx
  ON external_job_application_reports (learner_id, reported_at DESC);
