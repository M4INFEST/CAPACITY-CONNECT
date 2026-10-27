ALTER TABLE learner_preferences
  ADD COLUMN prioritize_paid boolean NOT NULL DEFAULT false;

ALTER TABLE course_versions
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN delivery_format text NOT NULL DEFAULT 'self_paced'
    CHECK (delivery_format IN ('self_paced', 'instructor_led', 'blended'));

CREATE TABLE course_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_version_id uuid NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
  review_text text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_version_id, learner_id)
);
CREATE INDEX course_reviews_version_idx ON course_reviews (course_version_id);

CREATE TABLE course_wishlist (
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_version_id uuid NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (learner_id, course_version_id)
);

CREATE TABLE external_courses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title text NOT NULL,
  description text,
  provider text NOT NULL,
  provider_domain text NOT NULL,
  course_url text NOT NULL,
  duration_hours numeric(6,2) CHECK (duration_hours > 0),
  price_cents integer NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
  difficulty smallint CHECK (difficulty BETWEEN 1 AND 5),
  language text NOT NULL DEFAULT 'en',
  verified_at timestamptz,
  active boolean NOT NULL DEFAULT false,
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (course_url ~ '^https://')
);

CREATE TABLE external_course_competencies (
  external_course_id uuid NOT NULL REFERENCES external_courses(id) ON DELETE CASCADE,
  competency_id uuid NOT NULL REFERENCES competencies(id),
  level_taught smallint NOT NULL CHECK (level_taught BETWEEN 1 AND 5),
  PRIMARY KEY (external_course_id, competency_id)
);

CREATE TABLE external_course_completions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_course_id uuid NOT NULL REFERENCES external_courses(id),
  learner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  certificate_id text NOT NULL,
  certificate_url text NOT NULL CHECK (certificate_url ~ '^https://'),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'verified', 'rejected')),
  review_reason text,
  submitted_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz,
  reviewed_by uuid REFERENCES users(id),
  UNIQUE (external_course_id, learner_id, certificate_id)
);
CREATE INDEX external_course_completions_queue_idx
  ON external_course_completions (status, submitted_at);

INSERT INTO role_competencies (role_id, competency_id, required_level, importance)
SELECT r.id, c.id, req.required_level, req.importance
FROM (
  VALUES
    ('Software Engineer', 'Git', 3, 0.80::numeric),
    ('Software Engineer', 'JavaScript', 3, 0.75::numeric),
    ('Software Engineer', 'Python', 3, 0.75::numeric),
    ('Software Engineer', 'SQL', 2, 0.60::numeric),
    ('Software Engineer', 'TypeScript', 3, 0.70::numeric),
    ('Software Engineer', 'Docker', 2, 0.65::numeric),
    ('Data Analyst', 'Python', 3, 0.80::numeric),
    ('Data Analyst', 'SQL', 4, 0.90::numeric),
    ('Data Analyst', 'PostgreSQL', 3, 0.70::numeric),
    ('Data Analyst', 'Git', 2, 0.55::numeric),
    ('Product Manager', 'SQL', 2, 0.65::numeric),
    ('Product Manager', 'Python', 1, 0.35::numeric),
    ('Product Manager', 'Git', 1, 0.25::numeric)
) AS req(role_name, competency_name, required_level, importance)
JOIN role_catalog r ON r.name = req.role_name
JOIN competencies c ON c.canonical_name = req.competency_name
ON CONFLICT (role_id, competency_id) DO NOTHING;
