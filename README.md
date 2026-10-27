# Capacity Connect v2.0

Phase 1 foundation for the competency-driven learning platform.

## Start locally

1. Start Docker Desktop. Copy `.env.example` to `.env`, set `POSTGRES_PASSWORD` and `AUTH_JWT_SECRET`, and generate a private valid Fernet `MFA_ENCRYPTION_KEY` before signing in to trainer/employer/admin accounts. Docker Compose starts Mailpit for local-only verification and recovery email capture; no real email is sent.
2. From this directory, run `docker compose up --build`.
3. Open the Next.js app at `http://localhost:3000`. The API liveness endpoint is `http://localhost:8000/health`; the database readiness endpoint is `http://localhost:8000/ready`.
4. For local account verification, open the Mailpit inbox at `http://localhost:8025` and use the latest verification link. Password reset messages are captured there too.

The login page checks API/database readiness and shows the startup command if the backend is unavailable. Docker Desktop must be running; the web-only development server cannot perform registration or sign-in without the API and PostgreSQL. Local Compose defaults route SMTP to the Mailpit inbox, so account verification works without an external provider. Mailpit is a development email sink only; configure an approved SMTP provider for deployed environments. Privileged accounts cannot sign in until MFA encryption is configured and MFA enrollment is complete.

## API development and test baseline

Use a separate Python 3.11 virtual environment for the API and its tests; server dependencies stay in `apps/api/requirements.txt`, and test-only dependencies stay in `apps/api/requirements-dev.txt`. From this repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -r apps/api/requirements-dev.txt
python -m pip check
Push-Location apps/api
try { python -m pytest -q } finally { Pop-Location }
.\scripts\verify_migrations.ps1
.\scripts\test_auth_flows.ps1
```

The web production/type-check/build baseline is `npm.cmd run build` from `apps/web`. This is not a browser journey, accessibility scan, or UI unit-test substitute. See [`docs/implementation/CC-01-baseline.md`](./docs/implementation/CC-01-baseline.md) and the [`CC-01 per-function requirements matrix`](./docs/implementation/cc-01-traceability.csv) for measured scope, evidence, real gaps, and baseline results.

## Web workspaces

After sign-in, the web app shows a responsive workspace menu for the roles returned by the authenticated account endpoint. Desktop navigation uses a sidebar; smaller screens use a horizontally scrollable menu. Links point only to implemented routes, and public passport-share and credential-verification pages remain outside the signed-in shell. The API remains responsible for authorizing every protected action.

PostgreSQL 15 is provided by the pgvector image. On the first initialization of an empty database volume, PostgreSQL runs the numbered SQL files in `db/migrations` in order. Initialization scripts do not rerun against an existing data volume; apply later migrations explicitly or through a migration runner.

The default password in Compose is for local development only. Set a private value in `.env` before using the stack outside a local machine. Do not commit `.env`.

If `.env` was created before Mailpit was added, update `SMTP_HOST=mailpit`, `SMTP_PORT=1025`, `SMTP_FROM=no-reply@capacity-connect.local`, and `SMTP_USE_STARTTLS=false`; Compose cannot override values already present in that file. The local Mailpit inbox is loopback-only and does not negotiate TLS or accept authentication, so keep these settings local to development. For external SMTP, use `SMTP_USE_STARTTLS=true` (the default in the API) and configure valid provider credentials as required. Restart the stack with `docker compose up --build` and open `http://localhost:8025` to retrieve verification mail.

## API authentication and roles

The API supports public trainee and employer registration, login, current-user lookup, trainer applications, and admin review of trainer applications and employer verification. Public registration cannot grant trainer or admin roles: trainer access requires admin approval, and the initial admin must be provisioned manually by a trusted operator. Passwords require at least 12 characters including uppercase, lowercase, and numeric characters, and are stored as salted PBKDF2-HMAC-SHA256 hashes.

Before starting Compose, copy `.env.example` to `.env` and replace `AUTH_JWT_SECRET` with a private random value of at least 32 characters. For example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Do not commit `.env`.

Email verification and account recovery use short-lived, single-use random tokens; only token hashes are stored. Verification links expire after 24 hours; reset links expire after 30 minutes. The browser receives tokens in URL fragments, and the verification/reset pages remove them from the address bar before submitting them. New password accounts remain pending until the mailbox is verified. Password reset increments the account token version, invalidating previously issued access and MFA challenge tokens. Local Compose sends verification and recovery messages to Mailpit; for deployment, configure an approved SMTP provider using `SMTP_HOST`, `SMTP_PORT` (STARTTLS), and `SMTP_FROM`; set `SMTP_USERNAME` and `SMTP_PASSWORD` when authentication is required. The SMTP sender uses TLS and a bounded timeout. Email requests are rate-limited to three per address and 20 per client IP per purpose in a rolling hour.

Google sign-in uses the OpenID Connect authorization-code flow with PKCE, a one-use state and nonce, verified Google ID tokens, and a short-lived one-use browser exchange code. New Google identities create learner accounts only. A Google-verified email can link to an existing account with the same email without granting new roles; Trainer, Employer, and Admin accounts still require MFA. Employer registration continues to use the standard form. To enable Google sign-in locally, create an OAuth client in Google Cloud Console, add `http://localhost:8000/api/v1/auth/google/callback` as an authorized redirect URI, then set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the private `.env`. Keep `GOOGLE_REDIRECT_URI` exactly equal to that URI and restart Compose. Apply migration 017 before using the flow on an existing database. Never commit or paste the client secret. Google sign-in is visibly available but will report that configuration is missing until both credentials are set.

Trainer, employer, and admin roles require TOTP multi-factor authentication. Sign-in issues a five-minute, purpose-limited MFA challenge or a ten-minute setup token; neither is accepted by protected API routes. MFA secrets are Fernet-encrypted with `MFA_ENCRYPTION_KEY`, which must be a valid Fernet key and kept stable/backed up outside the repository. Generate one inside the API environment with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Do not commit the value. Ten one-time recovery codes are displayed after enrollment; only keyed hashes are stored. Five invalid MFA attempts trigger a 15-minute cooldown. Accepted TOTP time steps are not reusable, challenge tokens are single-use, and enabling MFA increments the account token version to invalidate old sessions. Learner MFA remains optional and can be enrolled or disabled from `/account/security`; disabling requires the current password plus a fresh authenticator or unused recovery code, then invalidates existing sessions. Trainer, employer, and admin accounts cannot disable mandatory MFA. Accounts with multiple granted roles receive a role chooser; the UI offers only roles returned by the authenticated account. Trusted-device recognition, recovery-code regeneration, and self-service MFA reset are not implemented.

Login failure counts are tracked in PostgreSQL by normalized email and client IP over a rolling 15-minute window. Each failure adds a progressive delay (capped at 30 seconds); after three failures, login requires a Google reCAPTCHA token. Accounts are never hard-locked. Set both `CAPTCHA_SITE_KEY` and `CAPTCHA_SECRET_KEY` to enable CAPTCHA. If the threshold is reached without CAPTCHA configured, login fails closed with HTTP 503 rather than bypassing the challenge. The API uses the direct connection address; do not trust forwarded IP headers unless a trusted proxy configuration is explicitly added.

To provision the first admin, create the operator account through the verified registration flow, then run this SQL as a database operator:

```sql
INSERT INTO user_roles (user_id, role)
SELECT id, 'admin'::app_role FROM users WHERE lower(email) = lower('operator@example.com')
ON CONFLICT DO NOTHING;
```

Employer verification progresses manually from level 0 (registered, no candidate data) to level 1 (non-free email matches the company website domain) to level 2 (admin-verified business). Admins can only advance one level at a time, and the reviewer and reason are persisted in verification and audit logs. Full candidate-profile access must be gated on level 2 when those endpoints are added.

Level 1 additionally requires the employer's mailbox to have completed email verification; matching the company domain alone does not prove mailbox ownership. Mailpit is a local-only email sink; no external SMTP provider is configured by default. Deployment behind a proxy needs an explicit trusted-proxy setup.

Migration `015_identity_verification_mfa.sql` adds email token/rate-limit records, MFA secret and recovery-code storage, one-use MFA challenges, and account token-versioning. PostgreSQL initialization scripts do not run again on an existing volume. After migrations 001–014 are present, apply it once with:

```powershell
docker compose exec -T db psql --set ON_ERROR_STOP=1 -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/015_identity_verification_mfa.sql
```

Migration `017_google_oauth.sql` adds expiring OAuth state/PKCE records, Google identity links, and one-use sign-in exchange codes. It follows the existing `016_privacy_preferences.sql`. On an existing database that has already applied migration 016, apply migration 017 after rebuilding the API/web containers:

```powershell
docker compose exec -T db psql --set ON_ERROR_STOP=1 -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/017_google_oauth.sql
```

CC-02 implementation checkpoint: email verification and reset, fail-closed mandatory MFA for privileged roles, optional learner MFA management, assigned-role selection, trainer applications/admin review, local Mailpit email capture, and Google OIDC sign-in are implemented. Google creates learner accounts only and only links an existing account when Google verifies the same email; privileged roles still require MFA. Validation passes 90 API tests (11 database-dependent tests skipped in the ordinary run), 11 disposable-PostgreSQL authentication-flow tests, `pip check`, Compose configuration validation, and the Next.js production build (26 routes). SMTP is mocked in flow tests, Google token verification is mocked, and live provider credentials are not configured. Migration smoke validation is currently blocked because the existing `016_privacy_preferences.sql` file is zero bytes; I left it untouched and numbered the Google migration 017. Privacy preference UI/schema and the final privacy notice are not implemented. Initial-admin provisioning in an already-used database, real email/Google provider verification, the full four-role browser authorization matrix, recovery-code regeneration, self-service MFA reset, and release-readiness evidence remain unverified. The API suite command is `Set-Location apps\\api; python -m pytest -q tests`; the disposable auth-flow command is `scripts\\test_auth_flows.ps1` from the project root. The build command is `npm run build` from `apps\\web`.

## Skill Passport (Stage 2, Fix R14/R13)

The API and web app now provide the three-step target-role, resume, and skill-review flow. Resume extraction accepts PDF and DOCX files up to 10 MB. Text is extracted in memory; the original file is not persisted. Image-only/scanned PDFs are not supported. The parser rejects encrypted PDFs and oversized documents.

The initial taxonomy seed in `db/migrations/003_skill_passport.sql` contains common development skills and starter target roles. It includes symbol-aware aliases for C, C++, C#, Java, JavaScript, .NET, and Node.js. Add reviewed entries to `competencies` and `competency_aliases` as the taxonomy expands. Confidence is a deterministic matching heuristic, not a calibrated ML probability: exact taxonomy aliases start at 0.96, while the ambiguous standalone C match requires manual review unless software-development context is nearby. Skills below 0.90 confidence are not preselected. Resume-confirmed skills are saved as `claimed` with unverified resume evidence; they are never presented as verified.

The matcher is a focused port of the boundary-aware, longest-phrase taxonomy approach used by `skill-extractor/python/skill_extractor/matcher.py`; extraction reuses the context-window and one-tap review flow from `extractor.py`. The old project is not imported at runtime. Model embeddings and its trained classifier are intentionally not included, so the confidence scores and precision target must be validated against a golden resume set before production use.

Share links have unguessable tokens, store only a SHA-256 token hash, default to 14-day expiry, support 7/14/30/90 days and section selection, optional view limits, optional Level 2 employer sign-in, access logs, and revocation. The raw token is returned only when a link is created. Public links use the read-only `/share/{token}` page.

The Stage 2 web experience now has dedicated trainee pages: `/passport` (overview), `/passport/resume` (upload and learner review), `/passport/skills` (add or update claimed self-ratings), `/passport/preferences` (study time, budget, format and paid-course preference), `/passport/share` (section selection, expiry, view limits, employer sign-in, access log and revocation), and `/passport/challenge` (assessment entry). The signed-in workspace navigation links to each page. The root page remains the first-login target-role onboarding wizard and links into these dedicated tools. Challenge assessments continue through `/assessment`.

Resume skill extraction in the API currently accepts text-based PDF and DOCX only; image/scanned resume OCR is not available. The new resume review page keeps pending review metadata in session storage so a refresh in the same browser session does not discard the review; it does not store the uploaded document. Verified skill levels cannot be overwritten by learner self-ratings. Personal-data download/deletion workflows are not yet implemented. These pages use existing API capabilities and do not imply that the full Stage 2/CC-03 acceptance gate or its labeled-resume precision benchmark is complete.

For an existing PostgreSQL volume, apply the passport migration after migration 002:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/003_skill_passport.sql
```

The frontend calls the API from the browser. Set `NEXT_PUBLIC_API_URL` to a browser-reachable API URL and `WEB_ORIGINS` to the frontend origin if they differ from the local defaults.

## AI Course Picks (Stage 3)

The `/learning` page stores weekly hours, an optional rupee budget, learning format, and whether paid courses should be prioritized. It recommends only course versions whose status is `published` and which have an approved `course_approval_requests` record. Recommendations use the selected role competencies and current passport levels: for each course, the service sums the importance-weighted skill levels it can close and divides by course duration. Each card names the role gap and shows the score inputs. Results are not generated by a black-box career model.

The catalog includes course search and filters, version details, syllabus/outcomes, current learner ratings, prerequisites and unmet-prerequisite warnings, a wishlist, and comparison of two or three versions. Free and low-cost courses (up to ₹500) are sorted first unless paid courses are prioritized. External resources are shown only after an admin verifies an HTTPS URL on a supported provider domain; external resources are optional.

Learners can submit a certificate ID and provider-domain URL for admin review. The domain is checked before submission, but credit is not granted until an admin checks the certificate and approves it. Approval records verified evidence and updates the covered competency levels; rejection records no credit. The admin decision is an attestation, not an automated provider API check. The separate Challenge-test credit path belongs to the assessment stage and is not implemented yet.

Migration `004_course_picks.sql` adds learner preferences, course reviews and wishlists, verified external resource and certificate-review tables, and starter role-to-skill requirements. No sample published courses are invented or exposed; the catalog stays empty until approved course versions are published. On an existing database, apply it with:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/004_course_picks.sql
```

## Enroll and learn (Stage 4)

The course detail flow now supports enrollment in approved, published course versions. Free courses enroll immediately. Learners can also redeem an administrator-issued organization seat code; only a SHA-256 hash is stored, and a code can be limited to a course, number of seats, and expiry. Unmet prerequisites are shown before enrollment and require explicit acknowledgement. Enrollments remain attached to the version selected at enrollment.

`/my-learning` provides the learner dashboard, lesson list, resume position, private notes, embedded knowledge checks, lab/project link or text submissions, trainer feedback status, and course discussion. Lesson completion requires active time (at least 80% of the configured duration) and answers to two or three configured checkpoints. The browser sends progress only while the page is visible and active; video time is counted only while the video is playing with audio enabled. The API caps each reported progress interval at 30 seconds. Trainers can review learner work and reply to discussion questions through the Stage 4 API.

To configure lesson checkpoints, each `lesson_checkpoints.question` JSON object must include a learner-visible `prompt` and `options` plus a server-only `answer_key`. The answer key is removed from lesson responses. Lesson rows should have two or three checkpoints and a suitable `duration_seconds`; lessons requiring no checkpoints can set `assessment_required` to false.

Payment processing is not enabled: there is no gateway account or webhook configured, so paid enrollment fails closed instead of pretending a payment succeeded. Create seat codes with the admin-only `POST /api/v1/admin/learning/sponsorship-codes` endpoint. Course pre-tests, file uploads, actual email reminders, refund processing, and mandatory version-upgrade decisions are not yet implemented.

Migration `005_learning_delivery.sql` adds sponsorship codes/redemptions, lesson content and progress, and learning submissions/discussions. For a database that already ran migrations 001–004, apply it after those migrations:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/005_learning_delivery.sql
```

## Adaptive assessment (Stage 5, Fixes R1/R2)

After all lessons in an enrollment are complete, trainees can open the adaptive assessment from **My Learning**. `/assessment` presents instructions, the timer, one question at a time, auto-saved drafts, confidence ratings, an “I don't know” choice, submission confirmation, a level range, competency breakdown, and weak-skill drills. Tab visibility/focus events are logged for review and never cause an automatic fail.

Trainers create an assessment and submit questions from `/trainer/assessments`. Question competencies must be mapped to that course version. Admins review content and answer keys at `/admin/assessment-review`; only active, approved questions are ever served. The question bank supports multiple choice, multi-select, short answer, scenario, and code task formats. Option order is deterministically shuffled per attempt/question so a refresh does not change the displayed choices; the adaptive selector prefers calibrated questions near the current learner rating and balances coverage across competencies.

The Elo implementation starts a question at `700 + 100 × trainer-set difficulty` (levels 1–5). Correct/incorrect scored answers update the learner rating (base K 24 for calibrated questions, 8 for uncalibrated, adjusted by the learner's confidence) and the question rating (K 16). Questions become calibrated after ten scored responses. “I don't know” is saved but changes neither rating nor scored-response count. The estimate maps rating bands to levels 1–5, reports the level range using learner uncertainty, and labels confidence low/medium/high based on range width and scored evidence. An attempt may ask extra questions until the range narrows or the configured maximum is reached. Admins set the rolling weekly attempt limit from the admin assessment page/API.

Self-checks never create credentials. The verified tier requires at least one practical scenario/code-task response and a written explanation. A passing verified attempt can issue a credential for each skill whose same-attempt knowledge and practical responses agree with a narrow enough level range. Other skills remain unverified; practice courses and questions for missed competencies are offered.

Migration `006_adaptive_assessments.sql` adds question moderation/type metadata, timed attempts, single-active-attempt enforcement, weekly policy, integrity events, and drill responses. Existing databases that have already applied migrations 001–005 should apply it with:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/006_adaptive_assessments.sql
```

Not yet implemented from the wider Stage 5 specification: proctored partner sessions, per-attempt generated parameterized datasets, automated answer-similarity checks, peer study groups, and the timed 48-hour trainer-to-backup-to-admin escalation worker (Fix R7). Short-answer/scenario/code items are currently compared with trainer-supplied answer keys; verified results remain provisional and should not be treated as a credential. Level cutoffs and confidence ranges are initial transparent heuristics, not psychometrically calibrated standards.

## Verifiable credentials (Stage 6, Fix R2)

The `/credentials` page lists a trainee's credentials, exposes PDF download and sharing links, and links to a public verification page. The public `/verify/{credential_id}` response contains only an anonymized holder label, course, skill, level, evidence tier, issue/expiry dates, status, and credential ID. PDF credentials include a QR code to that page. Set `WEB_PUBLIC_URL` to the externally reachable frontend origin before deploying so QR and sharing links do not point at localhost.

Only a passing `verified` assessment can issue credentials; self-check attempts never do. Issuance requires submitted knowledge and practical responses for the skill plus a narrow level range at or above the assessment target. Issuance saves verified evidence, updates the passport competency, and records an audit event in the assessment transaction. Proctored credentials are not available until a proctoring partner is integrated. Admins can set or clear optional expiry dates or revoke a credential with a required reason at `/admin/credentials`; a revoked credential remains publicly verifiable as revoked, and its competency returns to claimed unless another verified evidence record supports it.

Migration `007_verifiable_credentials.sql` adds evidence and course links, optional expiry, and duplicate-issuance protection. On an existing database that has applied migrations 001–006, apply it with:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/007_verifiable_credentials.sql
```

## Profile and gap update (Stage 7, Fix R15)

After an assessment submission, the API updates each affected skill from the learner's Elo rating (which incorporates response scores and question difficulty) and records the score, average question difficulty, evidence quality, previous level, and updated level. A skill with an issued verified credential is labeled verified; other assessment evidence remains provisional. A self-check cannot downgrade a previously verified skill. Readiness before and after the result is snapshotted for every selected target role, and the result page links to `/profile`.

The profile dashboard shows weighted readiness and recent trend per role, with each required skill grouped as Critical, High, Medium, or Nice to have. Gap score is `(required level - current level) × importance`, floored at zero. Current priority bands are Critical at 1.50+, High at 0.75–1.49, Medium above 0–0.74, and Nice to have at zero. Importance uses the configured `role_competencies.importance` values (the starter catalog contains reviewed seed weights; it is not yet a live job-posting frequency feed). Freshness is a separate badge based on the skill's configured half-life: current through one half-life, aging through two, and stale after that. It never lowers the skill level. Refreshers are suggested only for stale/aging skills required by a selected role; “I use this regularly” dismisses that suggestion without changing evidence or freshness.

Migration `008_profile_gap_updates.sql` assigns starter half-lives, backfills recency only from provisional/verified evidence, and adds readiness history, assessment profile updates, and refresher acknowledgements. Apply it after migrations 001–007 on an existing database:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/008_profile_gap_updates.sql
```

## Learning roadmap (Stage 8, Fix R17)

The trainee `/roadmap` page creates a prerequisite-aware sequence of published, admin-approved courses for a selected Passport role. Learners can optimize for fastest completion or lowest cost, set weekly study hours and an optional total budget, and view dated milestones, remaining skill gaps, readiness, version comparisons, and a PDF export. The 70% job-ready marker is informational and never blocks job access.

Roadmap versions remain stable when only planning preferences or the course catalog change; the UI shows a suggested adjustment instead. A new version is eligible after a milestone completes, the target role changes, or the finish date moves by more than 15%. Replanning is limited to once per seven days. Opening the roadmap checks whether an eligible refresh is due.

Migration `009_learning_roadmaps.sql` adds learner settings, version history, and milestone snapshots. Apply it after migrations 001–008 on an existing database:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/009_learning_roadmaps.sql
```

## Job gap analysis (Stage 9, Fix R3)

The trainee `/job-gaps` page compares Passport levels with the selected role's competency requirements, prioritizes larger gaps and active employer feedback goals, provides a what-if match simulator, links gaps to course picks, and exports a PDF report. Market demand changes role-match weighting only when a provenance-labeled observation has at least 10 samples. Smaller samples are shown as “Not enough data”; source name, URL, observation date, sample size, and source type remain attached to each observation.

The administrator-only `POST /api/v1/admin/market-demand/observations` endpoint accepts observations from open datasets, licensed feeds, employer-published feeds, or platform jobs. The importer requires an explicit permission confirmation and validates role/competency pairs. It does not scrape external websites or invent market figures. No upstream feed credentials or scheduled provider integrations are configured, so an administrator must import updated observations weekly.

Level 2 verified employers can set a feedback goal through `POST /api/v1/employer/feedback-goals` only for an active application to one of their role-linked jobs. Goals receive critical priority in the learner's report until the Passport reaches the requested level.

Migration `010_job_gap_analysis.sql` adds the latest-observation index and employer feedback goals. Apply it after migrations 001–009 on an existing database:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/010_job_gap_analysis.sql
```

## Role matching (Stage 10, Fix R4)

The trainee `/role-matches` page ranks active catalog roles by a transparent, importance-weighted match between Passport levels and role competency requirements. Scores include a bounded market-demand adjustment of at most five percent, and demand affects a score only when the latest provenance-labeled observation has at least 10 samples. Each result explains the scoring version, formula, skill contributors and gaps, market-data coverage, and source/date/sample size. Adjacent roles are identified by shared competency overlap, not presented as a career-transition prediction.

The current scorer is versioned as `weighted-v1`; no role classifier or learned model is integrated or served. The `/api/v1/role-matches/refresh` endpoint records score snapshots in `role_match_runs`. Learners can set a match as a target Passport role in one action or mark it “Not interested”; that feedback hides the role from future ranked results until the learner opts to include excluded roles. The stored scoring version and score snapshots support future evaluation and rollback. Any future candidate model must first run in shadow mode and pass a data gate and release review before serving; a production scoring-weight release should change each weight by no more than five percent.

Migration `011_role_match_feedback.sql` adds role-interest feedback and an index for recent match runs. Apply it after migrations 001–010 on an existing database:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/011_role_match_feedback.sql
```

## Job explorer (Stage 11, Fix R23)

The trainee `/jobs` page lists active platform jobs with search plus location, type, experience, salary, skill, and saved-job filters. Match percentages use the listed job requirements (or the catalog requirements for its linked role when a job-specific skill list is absent) and are grouped as Apply now (70% or higher), Almost there (50–69%), and Learn first (below 50%). Learners can bookmark jobs, create and delete filter-based alert preferences, view employer/company details, and open external application links. External applications are recorded only as an explicit learner self-report, not as an employer-confirmed application.

Employer responsiveness is the median time from application to a recorded employer response and is shown only after at least three response observations. There is no email delivery or alert scheduler configured, so alert filters are stored but no alert email is sent. The catalog is not seeded with fabricated job listings; only active records already entered by an employer or authorized operator appear.

Migration `012_job_explorer.sql` adds job details and skill requirements, saved-job records, alert preferences, and external-application self-reports. Apply it after migrations 001–011 on an existing database:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/012_job_explorer.sql
```

## One-click apply (Stage 12, Fix R20/R23)

The job detail's internal-application action opens an evidence-first preview. Only learner-approved resume claims and current verified credentials are offered; claimed and verified skills are shown separately. The learner edits every line, confirms each line, can add their own text, reviews a deterministic job-keyword check, answers any configured employer questions, and must give application-specific consent before submission. The optional cover-letter template uses only the learner's approved lines and selected verified credentials; it is editable and contains no generated experience claims. A measurable-results prompt is shown for resume lines and any known `resume_claims.metric_prompt`; metrics are included only when the learner supplies them.

The application snapshot includes only the submitted resume, optional cover letter, question answers, consented Passport skills, and credentials the learner selected. It does not include the login email or unrelated Passport sections. Duplicate applications are rejected. Learners can download a plain-text, single-column resume, track application history, withdraw eligible applications, and self-report Heard back, Interview, Offer, or No reply. These status updates are explicitly learner-reported and do not update the employer-response timestamp used by Stage 11 responsiveness statistics.

Migration `013_one_click_apply.sql` adds application content/consent snapshots, employer question definitions, and application status history. Apply it after migrations 001–012 on an existing database:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/013_one_click_apply.sql
```

## Employer review (Stage 13, Fix R11/R21/R23)

Employers can create accounts from the shared sign-in page; all new employer accounts begin at verification level 0. Only Level 2 verified employers can publish or manage jobs, see candidate counts, or open consented applicant profiles. Company-name or website changes reset business verification and are audited, so admins must verify the changed identity again.

The `/employer` workspace provides pipeline counts, role/skill-based job posting, optional application questions, job pause/reopen, and applicant review. The `/employer/jobs/{job_id}` screen ranks only learners who explicitly consented during Stage 12. Fit is a versioned, importance-weighted match against the consented Passport skill snapshot; verified and claimed skills are labeled separately. Candidate names, emails, institutions, profile links, cover letters, resume text, and free-text answers are withheld in blind review. Profile reads and comparisons are logged and capped at 50 views per employer per rolling 24 hours. Employer notes and tags are private to that employer. Rejections require one of the neutral reasons `Position filled`, `Role changed`, or `Candidate withdrew`; skill-based rejection scorecards belong to Stage 14.

Stage 13 deliberately does not claim to provide secure email triage, outbound messaging, profile-export watermarking, or human-name/contact redaction. The platform has no configured email delivery, and blind review withholds free-text fields rather than attempting unreliable automatic identity redaction. These capabilities require additional privacy and delivery work before enabling.

Migration `014_employer_review.sql` adds the shortlist pipeline status, employer-private notes, and profile-view audit records. On an existing database apply it after migrations 001–013:

```powershell
docker compose exec -T db psql -U capacity_connect -d capacity_connect -f /docker-entrypoint-initdb.d/014_employer_review.sql
```

## Product delivery plan: 10 gated workstreams

This is the authoritative build plan for taking Capacity Connect from its current foundation to a production-piloted product. The product requirements are the supplied **Upgraded Specification v2.0**, not every proposed capability of every neighboring repository. Build forward from this Capacity Connect application; do not replace it with an unrelated repository or imply that a screen, model, integration, or deployment exists before its acceptance checks pass.

### Planning baseline

- **Product scope:** the specification's 18 stages, **92 screens and 182 functions**, delivered as 10 ordered engineering workstreams. Screen totals are planning coverage, not a promise to deliver 92 unrelated URLs; screens share page layouts, components, and authenticated journeys where that improves usability.
- **Existing foundation:** 14 SQL migrations; API modules and 14 API test modules covering authentication, passport extraction, course recommendations, learning delivery, assessments, credentials, profile progress, roadmaps, job gaps, role matching, jobs, applications, and employer review; a Next.js frontend covering a subset of those user journeys. The responsive role-aware workspace shell is an initial addition, not proof the whole product is complete.
- **Starting validation gap:** the web package has a production `build` script but no dedicated frontend unit, accessibility, or browser end-to-end test script; `e2e/` contains no product journey tests. Add and run these as part of the workstreams rather than describing a build as an end-to-end product test.
- **Delivery shape:** phases follow the spec: core learning and governed content first (stages 1–10 plus essential stages 17–18), hiring pilot second (11–15), outcomes and data-gated learning third (16 and remaining governance), then a controlled pilot/release.
- **Schedule assumption:** one full-time engineer, a five-day workweek, and a maximum of eight **active engineering hours** per counted workday. Estimates are planning ranges, not guaranteed completion dates. The summed workstream estimates are **64–99 engineer-days** (about **13–20 workweeks**); the sum of the individual hard caps is **792 active engineering hours**. Calendar time may increase for owner decisions, external integrations, data preparation, review and production rollout. Re-estimate when team size, deployment target, or external-service requirements are agreed.
- **Task status on publication:** all 10 workstreams below are **planned, not completed**. Existing functionality counts toward a workstream only after it passes that workstream's regression and acceptance gates.

### The 10 workstreams

| ID | Workstream | Specification coverage | Depends on | Estimate / hard active-time limit | Completion gate |
|---|---|---|---|---:|---|
| CC-01 | Product baseline, architecture and validation harness | Product-wide discovery and delivery foundations | None | 3–5 days / **40 h** | Spec traceability, architecture/ADR decisions, license and data register, reproducible API/web validation, and baseline coverage report are approved. |
| CC-02 | Identity, access, onboarding and account security | Stage 1; cross-cutting role/privacy controls | CC-01 | 5–8 days / **64 h** | Four-role authorization matrix passes API and browser tests; approval, recovery, verification and MFA states fail safely; no public trainer/admin escalation. |
| CC-03 | Skill Passport, evidence and resume intelligence | Stage 2 | CC-02 | 5–8 days / **64 h** | Learner-confirmed skill claims and privacy-preserving share flows work; the labeled resume benchmark reaches the specified precision gate. |
| CC-04 | Approved curriculum, trainer authoring and course picks | Stage 3; basic Stage 17 | CC-03 | 8–12 days / **96 h** | Recommendations explain gap-closed value; versioned training content cannot publish without approval; trainer and admin review flows pass. |
| CC-05 | Learning delivery, adaptive assessment, credentials and profile | Stages 4–7 | CC-04 | 8–12 days / **96 h** | Enrollment-to-assessment journey passes; calibration, evidence tiers, checkpoint and credential rules hold under adversarial and regression tests. |
| CC-06 | Roadmaps, job gaps and explainable role matching | Stages 8–10 | CC-05 | 5–8 days / **64 h** | Prerequisite-aware, stable roadmaps and transparent skill scores pass seeded-data/provenance, reproducibility and boundary tests. |
| CC-07 | Jobs, applications and learner job tracking | Stages 11–12 | CC-06 | 8–12 days / **96 h** | Only active jobs are visible; consented applications contain only learner-approved evidence; status, withdrawal and external self-report work end to end. |
| CC-08 | Verified-employer hiring, interviews and offers | Stages 13–15 | CC-07 | 6–10 days / **80 h** | Level-2 employer gates, blind review, interview scorecards, decisions, offers and status-only onboarding pass permission and privacy tests. |
| CC-09 | Trainer/admin governance, outcomes and model controls | Remaining Stages 16–18 | CC-02, CC-04, CC-05, CC-08 | 8–12 days / **96 h** | Audit-backed operations and versioned approvals work; outcomes stay segregated until the documented data gate and model release checklist pass. |
| CC-10 | Cross-platform hardening, pilot and production release | All stages and shared infrastructure | CC-01–CC-09 | 8–12 days / **96 h** | Critical user journeys pass release CI, accessibility and security gates; rollback, observability, operator runbooks, and pilot sign-off are ready. |

### Complete screen-to-workstream traceability

This screen inventory makes the 92-screen scope explicit and traceable. A route or screen may already exist; the named CC-ID is still accountable for verifying its end-to-end behavior and filling its gaps.

| Stage | CC-ID | Screens in the specification | Count |
|---|---|---|---:|
| 1. Access and approvals | CC-02 | Shared login; role selection; trainee registration; employer registration; trainer registration; email verification; forgot/reset password; trainer pending; Admin trainer queue; Admin trainer review; employer verification. | 11 |
| 2. Skill Passport | CC-03 | Onboarding wizard; Passport overview; resume upload and review; add/edit skill; shareable Passport; challenge-test entry. | 6 |
| 3. AI course picks | CC-04 | Learning goals; recommended courses; course detail; compare courses. | 4 |
| 4. Enroll and learn | CC-05 | Enrollment confirmation; payment or unavailable payment state; course home; lesson player; lab submission; course Q&A; learning dashboard. | 7 |
| 5. Adaptive assessment | CC-05 | Instructions; question page; submit confirmation; result and feedback; weak-skill drills. | 5 |
| 6. Verifiable credential | CC-05 | Credential issued; my credentials; public credential verification. | 3 |
| 7. Profile and gap update | CC-05 | Before/after summary; updated gap overview. | 2 |
| 8. Next-best learning path | CC-06 | Learning roadmap; roadmap settings; progress dashboard. | 3 |
| 9. Job gap analysis | CC-06 | Role gap report; what-if simulator; market demand view. | 3 |
| 10. Role matching | CC-06 | Matched roles; role detail; “why this fit” panel. | 3 |
| 11. Job explorer | CC-07 | Filterable job list; job detail; saved jobs; job-alert settings. | 4 |
| 12. One-click apply | CC-07 | Application preview; employer extra-questions form; confirmation and application tracker. | 3 |
| 13. Employer review | CC-08 | Employer dashboard; post/manage job; applicant list; candidate profile; compare candidates; company profile. | 6 |
| 14. Interview and decision | CC-08 | Interview scheduler; interview details; mock interview practice; scorecard; decision page; feedback and improvement plan. | 6 |
| 15. Offer and onboarding | CC-08 | Offer composer; offer view; status-only document checklist; onboarding course. | 4 |
| 16. Placement and model governance | CC-09 | Placement confirmation; 30-/90-day check-in; outcomes report. | 3 |
| 17. Trainer workspace and approvals | CC-04, CC-09 | Trainer dashboard; my courses; course builder; question-bank builder; submit for approval; learner-progress monitor; questions inbox; Admin content queue; Admin review page; reviewer assignment. | 10 |
| 18. Admin console | CC-09 | Admin dashboard; user management; roles and permissions; capacity dashboard; reports; audit log; platform settings; employer-verification queue; data-source register. | 9 |
| **Total** | **CC-01–CC-10** | **All specification screens have an accountable workstream.** | **92** |

**Time budget:** the rightmost estimate column is the maximum active-work budget for that workstream, not a guarantee. Record actual active hours against the workstream; pause the clock for awaited user decisions and external approvals, but record that blocked time and its cause separately. Review progress at approximately 50% and 75% of the workstream cap. If the cap is reached before the completion gate, **stop implementation and ask the product owner what caused the overrun**. Report remaining work, measured test/build output, blocker, risk, options and revised estimate; proceed past the cap only after the owner approves an explicit replan. Never silently drop a requirement, silently expand a budget, relabel a partial result as done, or claim that a deadline can be monitored without an active time-tracking mechanism.

### Workstream definitions and implementation gates

#### CC-01 — Product baseline, architecture and validation harness

**Scope:** Map every specification function to an existing route, API operation, table and test, or mark it as a real gap. Inspect the actual Capacity Connect code and proposed sibling-project components and licenses before reuse. Document system boundaries, role/data-flow diagrams, trusted actors, personal-data inventory, architecture decisions, dependency ownership, acceptance criteria and an ordered migration strategy. Record which hosted services, datasets, GPU hardware, email/payment provider and deployment account still require owner approval.

**Deliverables:** a reviewed requirements-to-test traceability matrix; architecture and threat-model decisions; a vetted reuse/provenance/license register; reproducible environment and migration verification; API, frontend and integration-test entry points; a baseline test/build report; per-task execution and token ledger.

**Exit validation:** a clean-checkout operator can follow documented commands to install dependencies, start PostgreSQL/API/web, apply migrations, run the API tests and build the web app. Test results explicitly distinguish passing, failing, skipped and infrastructure-blocked tests. Every stage/function has an owner, dependency, acceptance criterion and phase.

#### CC-02 — Identity, access, onboarding and account security

**Scope:** Complete the shared entry flow for **Trainee, Trainer, Employer and Admin**. Trainee/employer self-registration, trainer application and admin approval, safe operator-provisioned initial admin, account status/recovery, email verification, mandatory MFA for trainer/employer/admin, optional trainee MFA, role switching only for explicitly granted roles, employer verification levels, privacy/consent settings and accessibility. Public registration must never grant trainer/admin or verified-employer privileges.

**Implementation rule:** enforce authorization and employer verification at the API/data boundary, not just by hiding frontend navigation. Use the existing throttling/CAPTCHA protections and improve only with server-side behavior and regression tests. Store credential verifiers and short-lived recovery artifacts safely; deliver recovery tokens only through the approved, working verification channel. If email/MFA/CAPTCHA providers are not configured, show the honest unavailable/pending state and fail closed where required—never synthesize a successful verification or advertise MFA as enabled.

**Exit validation:** test each role against allowed and denied APIs, direct URL access, cross-account object IDs, pending/rejected trainers, level-0/level-1 employers, expired tokens, recovery, rate limiting and CAPTCHA-required states. Verify a public user cannot create admin/trainer permissions or view applicant information; check that every error is actionable without leaking secrets.

#### CC-03 — Skill Passport, evidence and resume intelligence

**Scope:** Finish target-role onboarding, PDF/DOCX parsing, taxonomy/alias maintenance, unambiguous versus ambiguous skill review, manual edits, claimed/provisional/verified distinctions, evidence provenance, expiry/limits/revocation for Passport shares, access logs, and fast-track challenge/evidence submission for experienced learners.

**Algorithm and reuse strategy:** keep the existing deterministic, symbol-aware, boundary/longest-phrase matcher as the safe baseline. Review the local `skill-extractor` behavior/license before extending; evaluate the local `resume-ner` DistilBERT/ONNX artifact as an **optional candidate**, not a required external service. Use a representative, consented, labeled golden set; split by person/source to prevent leakage; measure precision/recall by skill and resume format, confidence calibration, bias/error examples, throughput and memory. Never call extracted skills credentials or persist imported claims until the learner confirms. Do not upload identifiable resumes to a hosted model without a separately approved privacy/data-processing design.

**Exit validation:** at least **100 labeled resumes** and at least **90% precision for automatically preselected skills**; ambiguous/low-confidence skills remain unselected for human review. Add parser tests for encrypted, corrupt, image-only, malformed, oversized and symbol-sensitive (`C`, `C++`, `C#`, Java/JavaScript) inputs. Verify deleted/expired/revoked share links cannot disclose Passport data, and every shareable field is explicitly consented to.

#### CC-04 — Approved curriculum, trainer authoring and course picks

**Scope:** Build the course/module/lesson/version authoring experience, standard skill and level tags, prerequisites, drafts, change summaries, question-bank linking, validation checks, submissions, reviewer assignment, approval/revision/rejection, version history, rollback and learner preview. Default to strict Admin approval; trainers must never publish directly. Complete learner course search, details, comparison, goals/preferences, reviews/wishlist and approved-version recommendations.

**Recommendation:** preserve the current interpretable weighted **gap-closed per learner-hour** ranking with explicit skill, price, time, prerequisite and approval inputs. Define deterministic tie-breaking and cold-start behavior; compare any proposed learned ranker against the transparent baseline offline and in shadow mode. Explain each result using real approved course data; empty catalogues remain empty rather than being filled with fictitious courses.

**Exit validation:** test draft→submit→review→approved-version→learner-visible and change-request→draft flows, role isolation, concurrent version changes, malicious/broken external URLs, missing skill tags, duplicate/similar content warnings, and rollback. Assert that unapproved, withdrawn, broken, or unpublished versions never enter course picks; every displayed recommendation has an explainable target gap and verifiable inputs.

#### CC-05 — Learning delivery, adaptive assessment, credentials and profile

**Scope:** Complete free/sponsored enrollment, version-pinned learning, progress and notes, keyboard/screen-reader checkpoint flow, valid completion, labs/discussions, stuck/help escalation, attempt rules, adaptive assessment, targeted drills, credential issue/public verification/revocation, readiness history and distinct skill-freshness cues. Integrate payments only after a provider, webhook/signature validation, refund policy and production credentials are owner-approved; until then, keep paid flows clearly unavailable.

**Algorithms and safeguards:** preserve the current Elo-like selector as a transparent initial baseline; version its parameters and item-selection policy, use only approved questions, randomize parameterized inputs safely and log integrity events without auto-failing a learner for a tab switch. Calibrate only with scored observations and track uncertainty; publish a question as calibrated only after **at least 30 scored responses**, and report uncertainty when evidence is insufficient. Do not claim psychometric validation, real proctoring, or independent verified competency when the actual evidence/process is absent. Award verified credentials only when the assessment's required knowledge and practical evidence agree; self-checks never issue verified credentials. Recency changes freshness labels, not levels.

**Exit validation:** test checkpoint count/answer disclosure, hidden/inactive/muted/idle progress, resumption, duplicate/parallel attempts, answer autosave, option randomization, “I don’t know” without score penalty, confidence intervals, item calibration, cross-user data access, credentials after expiry/revocation and database transaction rollback. Compare policy outputs with a deterministic golden fixture and check every credential against its qualifying attempt/evidence.

#### CC-06 — Roadmaps, job gaps and explainable role matching

**Scope:** Deliver role gap reports, provenance-labeled market demand, what-if simulation, targeted course links, transparent role match details, role-interest feedback and versioned roadmap settings, progress, exports and “what changed/why” comparisons. Keep job exploration open below the informational 70% readiness marker.

**Algorithms and data rules:** use prerequisite-aware graph search with explicit objective functions and deterministic tie-breaking for shortest-duration/lowest-cost paths; preserve a feasible fastest-versus-cheapest distinction. Calculate fit from versioned, importance-weighted skill requirements and expose per-skill contributions and missing evidence. Demand can use only permitted open/licensed feeds, employer-published feeds or Capacity Connect jobs; capture license, collection date, source and sample count for each observation. Per the hardened specification, show **“Not enough data” below 50 postings**. Never scrape a prohibited source or make up sample sizes. Market evidence without sufficient coverage must not silently affect readiness or generate false-precision fit scores.

**Exit validation:** fixture-test prerequisite cycles/unreachable goals, equal-cost path determinism, budget/hour limits, roadmap stability/replan cadence, zero and stale evidence, demand samples of 0/49/50, missing provenance, and role-score contribution totals. Recompute a sample score independently from its displayed inputs and verify the same version is reproducible.

#### CC-07 — Jobs, applications and learner job tracking

**Scope:** Finish Stage 11 active-job search, location/type/experience/salary/skill filters, job detail, saved jobs, job-alert preferences and externally applied/self-reported status. Finish Stage 12 application preview, learner-editable evidence-first resume, optional editable cover-letter template, employer questions, application-specific consent, submission receipt, application history, status self-reports and eligible withdrawal.

**Data-safety rule:** include only lines and verified credentials the learner reviewed, approved and selected for that application; clearly label claimed versus verified skills. Never invent achievements, qualifications, results, references or personal details. Store only the application-consented snapshot. Apply only to authorized, active opportunities; distinguish applicant self-reports from employer-confirmed statuses and observed responsiveness.

**Exit validation:** test internal and external application paths, job closure races, duplicate submissions, employer-required question validation, line-level approval, resume export format, withdrawal eligibility, consent revocation, cross-user read/write attempts and attempts to inject or infer fabricated résumé facts. Assert alert settings are not reported as delivered email until a scheduled delivery provider/job is configured and verified.

#### CC-08 — Verified-employer hiring, interviews and offers

**Scope:** Complete employer/company profile and verification, job management, blind applicant list/review/shortlist, candidate comparisons, per-view audits/limits, interviewer scheduling/details, private AI/mock interview practice, skill scorecards, decisions, rejection feedback, alternative peer practice, offer compose/accept/decline/expiry and a status-only onboarding checklist.

**Fairness/privacy rules:** gate identifiable candidate data on the required verification, applicant consent and purpose; keep blind review blind, withhold profile links and unsafe free text rather than claiming imperfect redaction is complete. The practice coach may comment on STAR structure, relevance, clarity and length, but must not generate a culture-fit score, protected-trait inference or hire prediction. Keep mock-interview results private to the learner. Never store identity, tax, bank or onboarding documents as a convenience feature.

**Exit validation:** run negative authorization tests for every employer level, another employer's jobs/applications, withdrawn consent, interview notes and offer actions; verify every sensitive profile view is audited and rate-limited. Test structured rejection reasons, missing scorecards, candidate feedback visibility, expiring/withdrawn offers, neutral feedback not generating skill goals, and public/learner/employer data minimization.

#### CC-09 — Trainer/admin governance, outcomes and model controls

**Scope:** Complete the remaining Stage 17 workspace: draft versioning, skill tagging, assessment/question-bank queues, assigned reviewer capacity, prechecks, clean version diffs, approval/revision/rejection audit, learner progress and support/escalation routing. Complete Stage 18 admin user/permission management, verification queues, reports, capacity dashboards, settings, searchable audit records, review health and licensed data-source register. Implement Stage 16 placement confirmation, consented 30-/90-day one-tap follow-ups, anonymized outcomes and privacy-aware reporting.

**Model release rules:** interpretable/versioned rules remain the production baseline. Any ML job/recommender runs offline or in shadow with access controls, a documented purpose, a separate model/data version, reproducible feature definitions, offline baseline, subgroup fairness/stability analysis, monitoring and rollback. **No outcome-trained model is eligible for release before at least 500 legitimately collected labeled outcomes and a complete, Admin-reviewed release checklist.** Data quantity alone is insufficient. Make no silent score/weight changes; retain an auditable version and bounded rollback path. Never use confidential, fabricated or unconsented training labels.

**Exit validation:** prove least-privilege roles, dual-control/reviewer policies, immutable/restricted audit handling, export authorization, redaction/retention expectations and report correctness using seeded test cases. Test that 499 eligible outcomes is blocked and 500 is only eligible for review—not auto-approved. Verify the shadow model cannot influence a user-visible score and a failing release or rollback leaves the current model unchanged.

#### CC-10 — Cross-platform hardening, pilot and production release

**Scope:** Build a repeatable staging/production deployment, secrets management, migration backups/forward and rollback strategy, monitoring/alerts, structured privacy-safe logs, incident/recovery procedures, backups/restore rehearsal, legal/licence/provider review, dataset refresh schedule and operator/learner/trainer/employer runbooks. Complete responsive layouts, keyboard-only paths, screen-reader labels, accessible errors and empty/loading states. Conduct a privacy impact review and an independent security review before real candidate data is processed.

**Release sequence:** test on synthetic/de-identified fixtures; run role-scoped E2E tests; pilot the Phase 1 learning loop without requiring employers; authorize a small, verified employer pilot for Phase 2 only after the owner approves; introduce Stage 16 outcomes collection only with explicit consent and retention policy; independently verify a model release before switching from shadow. Set production rollback and support ownership before activating external payment, email, MFA, CAPTCHA, market-data or model providers.

**Exit validation:** CI executes formatting/lint/type checks, API unit/integration/security tests, frontend tests, migration tests and browser E2E for every role and core critical path; test the production build and deployment artifact; run keyboard/screen-reader checks and agreed accessibility scans; restore a backup; exercise rollback; and verify no unresolved critical security/privacy issue, exposed secret, fabricated record or unaudited privileged action remains. Capture a signed go/no-go decision and unresolved accepted risks; no green build alone constitutes production approval.

### Algorithm selection and sibling-project reuse policy

| Product problem | Production starting point | Candidate improvements and acceptance evidence |
|---|---|---|
| Resume skill detection | Existing deterministic symbol-aware taxonomy matcher plus learner review | Evaluate `skill-extractor` and local `resume-ner` ONNX weights against a consented labeled benchmark. Ship a model only after the Stage 2 precision gate, error analysis, license review, privacy review and measured latency/memory checks. |
| Course recommendations | Explainable importance-weighted skill-gap closed per hour, with published-version and prerequisite guards | Offline NDCG/Recall/coverage and calibration against reviewed learner feedback; shadow-only until robust labels, feedback consent and rollback exist. Do not describe rules as an AI model. |
| Adaptive assessment | Approved item bank, versioned Elo-like updates and explicit uncertainty | Compare against a predeclared held-out reliability/calibration benchmark; prevent item leakage, repeat-attempt memorization and uncalibrated-item overconfidence. Never infer proctoring from tab-switch data. |
| Learning roadmap | Prerequisite-constrained graph search with explicit time/budget objective | Compare plans against an exhaustive/simple baseline on small fixtures; verify optimality where the algorithm claims it, deterministic tie breaks and no impossible prerequisites. |
| Roles/jobs/candidate fit | Versioned, inspectable weighted skill fit and provenance-constrained market adjustment | Use offline ranking metrics plus subgroup fairness and stability tests; shadow, review and roll back candidate models. No automated employment or cultural-fit decision. |
| Learning or hiring outcomes | Aggregate statistics and transparent operational reports | Separately gated shadow experiments only. Require permitted purpose, representative labels, data-quality/fairness review, minimum support, reproducible release artifacts and explicit human approval before any product-facing impact. |

`AI-Resume-Analyzer`, `NextStep.AI`, `rankscript`, `pykt-toolkit`, `resume-ner`, `skill-extractor` and other neighboring repositories are **research inputs, not dependencies by default**. For any reuse, record the exact component/revision, owner, license/attribution obligations, security status, data inputs, Windows/Linux/GPU requirements, benchmark and maintenance plan before integrating it. Keep portable interfaces, vendor only code the project is entitled to use, and do not install or merge an entire project just to borrow an idea. Advanced algorithms are accepted only when they outperform an explicit baseline on a documented held-out set, improve a user outcome, meet latency/cost/privacy/fairness limits and can be disabled or rolled back.

### Per-task token and time budget protocol

Token quotas are **not inferable from repository size, engineering hours, or an assumed number of chat messages**. The model/provider/runtime determines the actual context window, metering and cost. No fixed token number in this README should be treated as a provider promise, and a tool or chat may only record actual usage if the execution environment exposes reliable counters.

Before each workstream begins, record its ID, owner, start date, approved hard hours, exact code scope, provider/model context capacity **as reported by that runtime**, cumulative input/output token cap **as approved by the owner and supported by available metering**, and the CI/acceptance commands. If token usage cannot be measured or bounded in the active tool, state that limitation and ask the owner to approve a **time-and-scope budget only**; do not claim a token budget is enforced. When counters exist, report input and output separately, plus any cost figure separately; do not equate context-window occupancy with cumulative billed tokens.

For a token-metered task, divide the approved task token cap into a planning allocation of **15% discovery/design, 60% implementation, 25% testing, review and handoff**. These are allocation guardrails inside the approved cap, not extra tokens. Warn the owner at **75%** actual consumption and state remaining budget; stop new implementation when the cap is exhausted. For every task, apply the stricter **active-hour cap** and the **measured token cap**—neither can silently replace the other. Budget pauses for user input, model-context compaction and tool work honestly; an unmetered continuation or fresh chat does not authorize resetting the approved total.

### Non-fallbackable execution and completion protocol

1. Select the first dependency-ready, owner-approved CC-ID. Confirm scope, non-goals, estimate, hard time cap, token-meter availability, privacy/security risks, test fixture and rollback plan **before** modifying production code.
2. Inspect current source, existing behavior, migration state, tests and worktree changes. Never overwrite another user's changes, invent credentials/data, commit secrets, or migrate sibling code without license and provenance review.
3. Implement one end-to-end vertical slice at a time: authorized API/data change, safe/idempotent migration if needed, role-aware responsive UI, clear error/empty/loading states, audit/consent behavior and automated regression coverage.
4. Run targeted validation after each slice. Run the entire applicable workstream matrix before closing it: API tests; frontend type/build/tests; role and cross-tenant denials; migration upgrade/rollback; browser journeys; keyboard/accessibility; and security/privacy checks. Report every skipped check and the reason. Never turn a blocked test into a pass-shaped fallback.
5. A failing test gets at most **two bounded diagnosis/fix/retest cycles inside the approved scope and remaining budgets**. If the failure persists, is security-sensitive, affects user data, requires a product trade-off/provider credential, or would exceed either approved cap, stop and ask the owner with the evidence and options. Do not loop indefinitely or silently substitute simpler behavior.
6. Mark a CC-ID **Done** only when its written exit gate is satisfied, its required evidence/tests are recorded, implementation state and known limitations are updated in this README, and the product owner has approved any external provider, dataset or release decision that it depends on. “Built,” “works on my screen,” and “production build passes” alone are not completion criteria.
7. At handoff, update the task’s status, implementation summary, actual elapsed active hours, actual measured token usage or explicit “not metered,” exact commands/results, skipped checks, known limitations, changed migrations/routes, owner decisions, evidence/PR/commit if one actually exists, and the next dependency-ready task. Preserve earlier completion evidence; append a correction when a later regression invalidates a prior claim.
8. On any scope/time/token overrun, stop before doing over-budget implementation. Tell the owner the cause, work completed, evidence, remaining work, risk, viable scope/schedule alternatives and additional budget needed. **Ask the owner and wait for approval; proceed only against the explicitly approved replan.** If approval is declined or unavailable, leave the task blocked with the tested partial state and instructions to resume—do not fabricate completeness or fall back to an unapproved solution.

### Workstream implementation and validation record

The following is the authoritative starting ledger. A check mark is reserved for work that has actually passed its exit gate; previous planning/navigation work does not automatically complete any workstream.

| ID | Status | Start | Actual active hours | Actual input/output tokens | CI/evidence | Blocker / next action |
|---|---|---|---:|---|---|---|
| CC-01 | Complete; time-accounting limitation accepted | 2026-10-26 | Not independently instrumented; 40-hour cap cannot be certified retrospectively | Token usage unavailable / no token cap | 76 API tests pass; `pip check` passes; Next.js production build passes; 14/14 migrations pass in a disposable database with 75/75 tables, pgvector, and roadmap constraints verified; all 182 functions classified in the traceability matrix. | Owner accepted closure with the unmetered-time limitation recorded. No sibling code/model integrated; license and production/pilot choices remain pre-release gates. |
| CC-02 | In progress; owner approved up to 64 hours | 2026-10-26 | Start checkpoint: 17:13 IST; active hours are approximate and not independently instrumented | Token usage unavailable / no token cap | 90 API tests pass; 11 database-dependent tests skip in the ordinary run; 11 disposable-PostgreSQL auth-flow tests pass; `pip check`, Compose config, and Next.js build pass. Migration smoke is blocked by the zero-byte `016_privacy_preferences.sql`; Google/SMTP providers are mocked/unconfigured. | Owner approved conservative privacy choices and optional controls, but implementation is pending. Resolve the empty migration without overwriting another actor's file, then complete the four-role authorization/browser matrix and real provider verification. Stop before 64 active hours and request approval before exceeding it. |
| CC-03 | Planned | Not started | — | Not metered / no task allocation | Labeled resume benchmark and Passport privacy gates pending | Depends on CC-02. |
| CC-04 | Planned | Not started | — | Not metered / no task allocation | Course approval, recommendation and trainer gates pending | Depends on CC-03. |
| CC-05 | Planned | Not started | — | Not metered / no task allocation | Enrollment, assessment and credential gates pending | Depends on CC-04. |
| CC-06 | Planned | Not started | — | Not metered / no task allocation | Roadmap, market provenance and scoring gates pending | Depends on CC-05. |
| CC-07 | Planned | Not started | — | Not metered / no task allocation | Job-to-application E2E and consent gates pending | Depends on CC-06. |
| CC-08 | Planned | Not started | — | Not metered / no task allocation | Employer privacy, interview and offer gates pending | Depends on CC-07. |
| CC-09 | Planned | Not started | — | Not metered / no task allocation | Admin, audit, outcome data and model-release gates pending | Depends on CC-02, CC-04, CC-05 and CC-08. |
| CC-10 | Planned | Not started | — | Not metered / no task allocation | Production, accessibility, rollback and pilot gates pending | Depends on CC-01–CC-09. |

When work starts, update **this ledger** at the start and close of each workstream and record any budget changes only after owner approval. CC-01 is closed with its elapsed active hours and cumulative token usage explicitly unmetered; no claim that either cap was met is made. CC-02 is using owner-approved approximate checkpoint-based time accounting; the runtime exposes no independent timer or cumulative token meter. Do not write unchecked future work as completed implementation. Do not promise automated reminders to the owner unless a real persistent scheduler, clock, delivery channel and authorization are installed and tested; without them, enforce the stop-and-ask checkpoint before proceeding within the active work session.
