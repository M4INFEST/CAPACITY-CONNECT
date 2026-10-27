-- Short-lived state and exchange records for the Google OIDC flow.
CREATE TABLE auth_google_oauth_states (
  state_hash text PRIMARY KEY,
  nonce text NOT NULL,
  code_verifier text NOT NULL,
  client_ip inet NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_google_oauth_states_expiry_idx
  ON auth_google_oauth_states (expires_at)
  WHERE consumed_at IS NULL;
CREATE INDEX auth_google_oauth_states_ip_idx
  ON auth_google_oauth_states (client_ip, created_at DESC);

CREATE TABLE user_google_identities (
  google_sub text PRIMARY KEY,
  user_id uuid NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  email_snapshot text NOT NULL,
  linked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth_google_login_codes (
  code_hash text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_google_login_codes_expiry_idx
  ON auth_google_login_codes (expires_at)
  WHERE consumed_at IS NULL;
