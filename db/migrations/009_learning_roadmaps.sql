CREATE TYPE roadmap_strategy AS ENUM ('fastest', 'cheapest');

CREATE TABLE learner_roadmap_settings (
  learner_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES role_catalog(id),
  weekly_study_hours numeric(5,2) NOT NULL CHECK (weekly_study_hours BETWEEN 0.5 AND 80),
  budget_cents integer CHECK (budget_cents >= 0),
  strategy roadmap_strategy NOT NULL DEFAULT 'fastest',
  target_finish_date date,
  ready_threshold smallint NOT NULL DEFAULT 70 CHECK (ready_threshold BETWEEN 1 AND 100),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE learner_roadmaps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  version integer NOT NULL CHECK (version > 0),
  role_id uuid NOT NULL REFERENCES role_catalog(id),
  strategy roadmap_strategy NOT NULL,
  target_finish_date date,
  weekly_study_hours numeric(5,2) NOT NULL CHECK (weekly_study_hours BETWEEN 0.5 AND 80),
  budget_cents integer CHECK (budget_cents >= 0),
  fingerprint text NOT NULL,
  change_reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (learner_id, version)
);
CREATE INDEX learner_roadmaps_history_idx
  ON learner_roadmaps (learner_id, version DESC);

CREATE TABLE roadmap_milestones (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  roadmap_id uuid NOT NULL REFERENCES learner_roadmaps(id) ON DELETE CASCADE,
  step_order integer NOT NULL CHECK (step_order > 0),
  course_version_id uuid NOT NULL REFERENCES course_versions(id),
  course_title text NOT NULL,
  duration_hours numeric(6,2) NOT NULL CHECK (duration_hours > 0),
  price_cents integer NOT NULL CHECK (price_cents >= 0),
  planned_start_date date NOT NULL,
  planned_end_date date NOT NULL,
  UNIQUE (roadmap_id, step_order),
  UNIQUE (roadmap_id, course_version_id),
  CHECK (planned_start_date <= planned_end_date)
);
