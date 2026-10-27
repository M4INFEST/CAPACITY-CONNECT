ALTER TABLE users
  ADD COLUMN auth_version integer NOT NULL DEFAULT 0 CHECK (auth_version >= 0);

CREATE TABLE auth_email_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose text NOT NULL CHECK (purpose IN ('email_verification', 'password_reset')),
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_email_tokens_user_purpose_idx
  ON auth_email_tokens (user_id, purpose, expires_at DESC)
  WHERE used_at IS NULL;

CREATE TABLE auth_email_delivery_attempts (
  id bigserial PRIMARY KEY,
  email_hash text NOT NULL,
  client_ip inet NOT NULL,
  purpose text NOT NULL CHECK (purpose IN ('registration', 'verification', 'password_reset')),
  attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_email_delivery_email_idx
  ON auth_email_delivery_attempts (purpose, email_hash, attempted_at DESC);
CREATE INDEX auth_email_delivery_ip_idx
  ON auth_email_delivery_attempts (purpose, client_ip, attempted_at DESC);

CREATE TABLE user_mfa (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  secret_ciphertext text,
  pending_secret_ciphertext text,
  failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
  locked_until timestamptz,
  last_totp_counter bigint,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_mfa_recovery_codes (
  id bigserial PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  used_at timestamptz,
  UNIQUE (user_id, code_hash)
);
CREATE INDEX user_mfa_recovery_codes_active_idx
  ON user_mfa_recovery_codes (user_id)
  WHERE used_at IS NULL;

CREATE TABLE auth_mfa_challenges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_mfa_challenges_expiry_idx
  ON auth_mfa_challenges (expires_at)
  WHERE consumed_at IS NULL;
