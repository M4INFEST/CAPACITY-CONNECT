ALTER TYPE application_status ADD VALUE IF NOT EXISTS 'shortlisted';

ALTER TABLE application_status_events
  DROP CONSTRAINT IF EXISTS application_status_events_status_check;
ALTER TABLE application_status_events
  ADD CONSTRAINT application_status_events_status_check
  CHECK (
    status IN ('applied', 'heard_back', 'interview', 'offer', 'no_reply',
               'likely_closed', 'rejected', 'withdrawn', 'shortlisted', 'placed')
  );

CREATE TABLE employer_application_notes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  employer_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  note text NOT NULL DEFAULT '' CHECK (length(note) <= 4000),
  tags text[] NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (employer_id, application_id)
);

CREATE TABLE employer_application_profile_views (
  id bigserial PRIMARY KEY,
  employer_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  viewed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX employer_application_profile_views_daily_idx
  ON employer_application_profile_views (employer_id, viewed_at DESC);
