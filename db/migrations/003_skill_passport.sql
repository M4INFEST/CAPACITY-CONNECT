CREATE TABLE learner_target_roles (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES role_catalog(id) ON DELETE CASCADE,
  selected_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role_id)
);
CREATE INDEX learner_target_roles_user_idx ON learner_target_roles (user_id);

INSERT INTO role_catalog (name, description)
VALUES
  ('Data Analyst', 'Analyzes data to support evidence-based decisions.'),
  ('Product Manager', 'Guides product strategy, discovery, and delivery.'),
  ('Software Engineer', 'Designs, builds, tests, and maintains software.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO competencies (canonical_name, description)
VALUES
  ('C', 'C programming language'),
  ('C#', 'C sharp programming language'),
  ('C++', 'C plus plus programming language'),
  ('CSS', 'Cascading Style Sheets'),
  ('Django', 'Python web framework'),
  ('Docker', 'Container platform'),
  ('FastAPI', 'Python web API framework'),
  ('Git', 'Distributed version control'),
  ('HTML', 'HyperText Markup Language'),
  ('Java', 'Java programming language'),
  ('JavaScript', 'JavaScript programming language'),
  ('Kubernetes', 'Container orchestration platform'),
  ('Microsoft .NET', '.NET development platform'),
  ('Node.js', 'JavaScript runtime'),
  ('PostgreSQL', 'Relational database'),
  ('Python', 'Python programming language'),
  ('React', 'JavaScript UI library'),
  ('SQL', 'Structured Query Language'),
  ('TypeScript', 'Typed JavaScript'),
  ('Vue.js', 'JavaScript UI framework')
ON CONFLICT (canonical_name) DO NOTHING;

INSERT INTO competency_aliases
  (competency_id, alias, symbol_sensitive, must_not_match)
SELECT c.id, a.alias, a.symbol_sensitive, a.must_not_match
FROM (
  VALUES
    ('C', 'C', true, ARRAY['++', '#', ' sharp', ' plus plus', ' #', ' ++']::text[]),
    ('C#', 'C#', true, ARRAY[]::text[]),
    ('C#', 'C sharp', false, ARRAY[]::text[]),
    ('C++', 'C++', true, ARRAY[]::text[]),
    ('C++', 'C plus plus', false, ARRAY[]::text[]),
    ('CSS', 'CSS', false, ARRAY[]::text[]),
    ('Django', 'Django', false, ARRAY[]::text[]),
    ('Docker', 'Docker', false, ARRAY[]::text[]),
    ('FastAPI', 'FastAPI', false, ARRAY[]::text[]),
    ('Git', 'Git', false, ARRAY[]::text[]),
    ('HTML', 'HTML', false, ARRAY[]::text[]),
    ('Java', 'Java', false, ARRAY[]::text[]),
    ('JavaScript', 'JavaScript', false, ARRAY[]::text[]),
    ('JavaScript', 'JS', true, ARRAY[]::text[]),
    ('Kubernetes', 'Kubernetes', false, ARRAY[]::text[]),
    ('Kubernetes', 'K8s', true, ARRAY[]::text[]),
    ('Microsoft .NET', '.NET', true, ARRAY[]::text[]),
    ('Microsoft .NET', 'dotnet', true, ARRAY[]::text[]),
    ('Node.js', 'Node.js', true, ARRAY[]::text[]),
    ('PostgreSQL', 'PostgreSQL', false, ARRAY[]::text[]),
    ('PostgreSQL', 'Postgres', false, ARRAY[]::text[]),
    ('Python', 'Python', false, ARRAY[]::text[]),
    ('React', 'React', false, ARRAY[]::text[]),
    ('SQL', 'SQL', false, ARRAY[]::text[]),
    ('TypeScript', 'TypeScript', false, ARRAY[]::text[]),
    ('TypeScript', 'TS', true, ARRAY[]::text[]),
    ('Vue.js', 'Vue.js', true, ARRAY[]::text[])
) AS a(canonical_name, alias, symbol_sensitive, must_not_match)
JOIN competencies c ON c.canonical_name = a.canonical_name
ON CONFLICT (competency_id, alias) DO NOTHING;
