CREATE TABLE auth_login_attempts (
  id bigserial PRIMARY KEY,
  email text NOT NULL,
  client_ip inet NOT NULL,
  succeeded boolean NOT NULL,
  attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_login_failures_email_idx
  ON auth_login_attempts (lower(email), attempted_at)
  WHERE succeeded = false;
CREATE INDEX auth_login_failures_ip_idx
  ON auth_login_attempts (client_ip, attempted_at)
  WHERE succeeded = false;

CREATE TABLE employer_verification_events (
  id bigserial PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES employer_profiles(user_id) ON DELETE CASCADE,
  previous_level smallint NOT NULL CHECK (previous_level BETWEEN 0 AND 2),
  new_level smallint NOT NULL CHECK (new_level BETWEEN 0 AND 2),
  reviewed_by uuid NOT NULL REFERENCES users(id),
  review_reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
