# CC-01 — Product Baseline and Architecture Inventory

**Status:** Complete; the owner accepted the unmetered active-time limitation. CC-02 remains paused.  
**Specification:** Owner-supplied `Upgraded_Specification_v2.pdf`, pages 14–30.  
**Baseline date:** 2026-10-26.  
**Authorization:** Owner approved CC-01 under a **40 active engineering hour** maximum, with time-and-scope accounting only.  
**Token metering:** Cumulative model input/output token usage is unavailable in this tool; **no task token count or enforced token cap is claimed**.  
**Evidence rule:** A route, database column or test module existing is not proof every specification requirement is implemented. Each workstream must independently pass its acceptance gates.

## Executive baseline

Capacity Connect is a real Next.js/FastAPI/PostgreSQL application, not an empty project. The inspected source includes **21 Next.js `page.tsx` routes, 121 API route declarations, 14 ordered SQL migrations and 13 API test modules**. The Next.js production build/type check succeeds. The API regression suite passes after installing the declared API dependencies and test runner in an isolated Python 3.11 environment.

The supplied specification contains **92 named screens and 182 numbered functions across 18 stages**. The source currently contains 21 frontend page modules, some of which serve multiple screens. The companion [per-function traceability matrix](./cc-01-traceability.csv) records **all 182 individual specification function descriptions**, their page and stage, relevant UI/API/database/test evidence, and an initial implementation/gap classification. A classification of partial explicitly does not claim acceptance.

## Architecture as found

```text
Next.js 15.5.28 / React 19 browser UI
    ├── browser requests with bearer JWT ──> FastAPI 0.115.12 API
    └── browser readiness check ──────────> FastAPI /ready
                                                └── PostgreSQL 15 + pgvector

Numbered SQL migrations 001–014 initialize the database on first creation.
```

- The web app stores its bearer JWT in `sessionStorage` and calls the API directly from the browser. This is an existing architectural decision and a cross-cutting XSS/token-exposure risk to include in the security review; CC-01 does not claim to eliminate it.
- FastAPI is divided among authentication, passports, learning, assessments, credentials, roadmaps, job gaps, role matching, jobs, applications and employer-review modules. PostgreSQL migrations define the persistent data model.
- Compose defines `db`, `api` and `web`; its PostgreSQL data volume is persistent. Migration smoke testing must use a separate disposable database and must never reset the user's Compose volume.
- API server packages are declared in `apps/api/requirements.txt`. A dev-only [requirements-dev.txt](../../apps/api/requirements-dev.txt) now makes pytest installation reproducible without adding the test runner to the production image. The web package pins Next.js/React and currently defines `dev`, `build` and `start` scripts only.
- The inspected project has no root `LICENSE`, CI workflow, API `pyproject.toml`, product migration-history runner, frontend unit-test/accessibility-test script, or browser E2E test file. Product license, production hosting, operational ownership and release approval are real decisions, not inferred from a successful build.

## Stage-by-stage source evidence and gaps

**Partial — acceptance required:** supporting source/schema/test evidence exists, but at least one requirement needs additional implementation, behavioral verification or acceptance tests. **Gap — no dedicated workflow:** the required stage-level product workflow was not found. The CSV contains individual requirement IDs for every function.

| Stage | Screens / functions | Existing web routes | Supporting API, migration and test | Baseline classification |
|---|---:|---|---|---|
| 1. Access and approvals | 11 / 12 | `/` | `auth.py`; `001–002`; `test_auth_security.py` | Partial. Registration, login, throttling, trainer applications and admin decisions exist. `email_verified_at` and `mfa_enabled` columns do not implement email delivery, verification, MFA challenges or step-up. Password recovery and recovery codes are not implemented. |
| 2. Skill Passport | 6 / 12 | `/`, `/profile`, `/share/[token]` | `passport.py`, `profile.py`; `003`, `008`; `test_skill_extraction.py`, `test_profile_progress.py` | Partial. Deterministic skill matching, learner confirmation and share flows exist. Challenge-test verification and a proven model benchmark are absent. |
| 3. Course picks | 4 / 11 | `/learning` | `courses.py`; `004`; `test_course_recommendations.py` | Partial. Course comparison and explainable, published-version recommendations exist. Each specified ranking, prerequisite, approval and real-catalog rule needs acceptance verification. |
| 4. Enroll and learn | 7 / 11 | `/learning`, `/my-learning`, `/trainer/learning` | `learning.py`; `005`; `test_learning_delivery.py` | Partial. Free/sponsored enrollment, lessons, checkpoints, notes, discussions and submissions have supporting code. No payment processor, refund, real email reminder, file upload or verified escalation service is configured. |
| 5. Adaptive assessment | 5 / 12 | `/assessment`, `/trainer/assessments`, `/admin/assessment-review` | `assessments.py`; `006`; `test_assessments.py` | Partial. Item review, Elo updates, attempts, progress and drills exist. **Question calibration currently occurs at 10 scored responses, below the spec target of 30+.** A proctoring partner, unique generated data sets and answer-similarity service are not established. |
| 6. Verifiable credentials | 3 / 8 | `/credentials`, `/credentials/issued/[credentialId]`, `/verify/[credentialId]`, `/admin/credentials` | `credentials.py`; `007`; `test_credentials.py` | Partial. Issue, PDF/QR, verify, expiry and revoke operations exist; test evidence-tier restrictions and public-field minimization explicitly. |
| 7. Profile and gap update | 2 / 7 | `/profile` | `profile.py`, assessment services; `008`; `test_profile_progress.py` | Partial. Readiness, role gaps, evidence and freshness are implemented; acceptance still needs to confirm every recency/evidence-quality edge case. |
| 8. Next-best path | 3 / 8 | `/roadmap` | `roadmaps.py`; `009`; `test_roadmaps.py` | Partial. Stable prerequisite-aware roadmaps and PDF export exist; verify optimization objectives, change reasons and cadence against the spec. |
| 9. Job gap analysis | 3 / 9 | `/job-gaps` | `job_gaps.py`, `job_gap_analysis.py`; `010`; `test_job_gap_analysis.py` | Partial and release blocking. **Market demand is currently enabled at 10 samples; the specification requires “Not enough data” below 50 postings.** Source license, recency and provenance also need verification. |
| 10. Role matching | 3 / 7 | `/role-matches` | `role_matches.py`, `role_matching.py`; `011`; `test_role_matching.py` | Partial. Transparent, versioned weighted matching exists; no learned model is deployed. Demand inherits the 10-versus-50 threshold defect. |
| 11. Job explorer | 4 / 9 | `/jobs` | `jobs.py`, `job_explorer.py`; `012`; `test_job_explorer.py` | Partial. Active-job discovery, filters, saves and alert preferences exist. An email provider and alert-delivery scheduler do not. |
| 12. One-click apply | 3 / 12 | `/applications`, `/applications/new/[jobId]` | `applications.py`; `013`; `test_application_preparation.py` | Partial. Consent-based previews, submitted snapshots and learner-tracked statuses exist. Verify every line-level approval, allowed field, transition, export and data-minimization requirement. |
| 13. Employer review | 6 / 11 | `/employer`, `/employer/jobs/[jobId]` | `employer_review.py`, `applications.py`; `014`; `test_employer_review.py` | Partial. Verification-gated job/applicant review and deliberately withheld identity/free text exist. There is no complete secure email triage, interview/scorecard workflow or outbound messaging. |
| 14. Interview and decision | 6 / 12 | No dedicated interview or decision page. | Application status includes `interview`; no dedicated scheduler, interview API, scorecard schema or test. | **Gap.** An application status value is not an interview, mock-practice, scorecard, decision or learner-feedback workflow. |
| 15. Offer and onboarding | 4 / 6 | No dedicated offer or onboarding page. | Application status includes `offer`; no offer issue/accept/expiry or status-only onboarding workflow/test. | **Gap.** An application status value is not an offer or onboarding workflow. |
| 16. Placement and model retraining | 3 / 7 | No dedicated placement/outcomes page. | No dedicated placement/check-in/outcome collection or model-release workflow/test. | **Gap.** Do not treat application states or schema vocabulary as 30/90-day outcome collection or model governance. |
| 17. Trainer workspace and approved content upgrades | 10 / 15 | `/trainer/learning`, `/trainer/assessments`, `/admin/assessment-review` | `learning.py`, `courses.py`, `assessments.py`; `004–006`; learning/assessment tests | Partial. Trainer review of learner submissions and assessment-question authoring exist. A complete versioned trainer course builder, risk-based approvals, review escalation and trusted-trainer system are not established. |
| 18. Admin console and capacity dashboard | 9 / 13 | `/admin/assessment-review`, `/admin/credentials` | Admin endpoints in `auth.py`, `assessments.py`, `credentials.py`, `courses.py`, `job_gaps.py` | Partial. Limited review/admin APIs exist. A complete user/permissions/capacity/report/audit-search/settings/data-source/model-release console and end-to-end tests are not established. |

### Verified specification mismatches

- The Stage 5 implementation sets a question to `calibrated` when scored `response_count + 1 >= 10`; the specification requires calibration after **30+ responses**. Assigned to **CC-05** to fix with exact boundary tests.
- The role-matching and market-demand services use `MINIMUM_DEMAND_SAMPLE = 10`; the specification requires **50 postings**, with “Not enough data” below that threshold. Assigned to **CC-06** to fix in both scoring and reports with 0/49/50 boundary tests.
- The existing password policy/documentation specifies 12+ characters whereas the PDF's numbered registration rule states at least 10. The current stricter requirement should not be weakened implicitly; verify UI/API consistency and obtain owner acceptance.
- A schema column, enum or status string such as `mfa_enabled`, `email_verified_at`, `interview`, `offer` or `outcome` does not establish a working delivery, verification, permission, decision or data-retention lifecycle.

## Reproducible validation results

| Gate | Command / method | Result | What is not proven |
|---|---|---|---|
| API dependencies/test runner | Created an isolated Python 3.11 venv; installed `apps/api/requirements-dev.txt`; ran `pip check`. | **Pass**; 0 dependency conflicts. | The initial global interpreter lacked declared `psycopg` and `pypdf`. The missing packages were installed only into the dedicated user venv. |
| API test suite | From the repository root, install with `python -m pip install -r apps/api/requirements-dev.txt`; from `apps/api`, run the isolated interpreter with `-m pytest -q`. | **76 passed** in 12.41 seconds; Python 3.11.6 / pytest 9.1.1; `pip check` reported no broken requirements. | Unit/regression tests are not 182 requirement-acceptance tests or live service tests. |
| Next.js production/type-check build | `npm.cmd run build` from `apps/web`. | **Pass**, Next.js 15.5.28 / React 19; 21 app pages built. | No browser E2E, dedicated frontend unit tests or accessibility checks. The current workspace-root warning for multiple lockfiles remains. |
| Disposable migration smoke test | `.\scripts\verify_migrations.ps1` from the repository root. | **Pass:** all 14 numbered migrations completed in order; all 75 declared tables and `pgvector` exist; `roadmap_milestones` has its UUID `id` primary key and unique `(roadmap_id, step_order)` constraint. | Ran in a network-isolated, disposable PostgreSQL container with migrations mounted read-only; persistent Compose database and volume were not used. |
| UI/browser/accessibility test harness | Inspected `e2e/` and frontend scripts. | **Missing:** zero product E2E test files; no frontend unit/a11y test scripts. | Add and run role-scoped checks in planned implementation workstreams; do not report build success as an accessibility or UX test. |
| Project/sibling license provenance | Inspected root `LICENSE` files for Capacity Connect and seven likely reference repos. | Capacity Connect has no root `LICENSE`; `NextStep.AI` has no root `LICENSE`. Other inspected roots contain MIT/Apache-2.0 license files. | This does not establish permission to distribute models/data or resolve ownership. No sibling code/model is integrated by CC-01. |

The first API test attempt failed during collection because globally installed Python packages were absent. Adding a dev-only dependency declaration and using an isolated project-specific environment resolved that setup issue; **all 76 API tests then passed**.

## License, model and reuse decisions

| Candidate | Root license observed | Current disposition |
|---|---|---|
| `skill-extractor` | MIT | The current deterministic Capacity Connect matcher already uses boundary-aware/symbol-aware skill matching. Review the exact revision and preserve required notices before extending or copying source. |
| `resume-ner` | Apache-2.0 | Evaluate the ONNX/model artifacts only after provenance, weights/data-usage terms, privacy and the labeled 100-resume / 90%-precision benchmark are reviewed. No external resume transfer by default. |
| `AI-Resume-Analyzer` | MIT | Reference only; no code or service integrated or benchmarked in CC-01. |
| `rankscript`, `pykt-toolkit`, `VulnLLM-R` | MIT | Reference only. No dependency, dataset or model import is authorized by this baseline. |
| `NextStep.AI` | No root `LICENSE` located | Do not copy or distribute code until reuse rights and license are confirmed. |
| `Capacity Connect` | No root `LICENSE` located | Obtain an owner-approved product distribution/license decision before public release. Ownership cannot be inferred from the fact the project is present in a workspace. |

Keep transparent recommendation, weighted role-matching and Elo-style assessment as the baseline; no unvalidated ML model is currently serving scores. Any future model must beat a documented held-out baseline on an agreed user outcome and pass privacy, fairness, latency/cost, monitoring, human-approval and rollback gates. Stage 16 outcome-based model release requires at least **500 legitimately collected, consented labeled outcomes and the complete review checklist**; reaching 500 is review eligibility, not automatic release permission.

## CC-01 completion checklist

- [x] Verified all 18 specification stages and exact totals of 92 screens / 182 numbered functions.
- [x] Inventoried frontend pages, API route declarations, migrations, API tests and E2E/frontend-test support.
- [x] Ran the API regression suite (76 passing) and Next.js production/type-check build.
- [x] Declared test-only dependencies separately and reproduced passing tests in an isolated Python 3.11 environment.
- [x] Identified and assigned the exact 10/30 assessment-calibration and 10/50 market-demand defects to CC-05 / CC-06.
- [x] Recorded every specification function with initial route/schema/test evidence and a partial/gap classification in the linked matrix.
- [x] Recorded architecture, cross-cutting storage risk, missing product license, candidate reuse/license evidence and scope of what is not validated.
- [x] Ran a **disposable PostgreSQL migration smoke test** and asserted all migrations 001–014 complete successfully without changing the existing user database.
- [x] Recorded the absent product license and deferred distribution, production deployment, and external model/data use until the owner makes the required decisions; no sibling code or model was integrated.

**Next action:** CC-01's technical gates are complete and the owner accepted the active-time metering limitation; the approved 40-hour cap cannot be certified retrospectively. CC-02 remains paused until its scope, budget, and feasible time-accounting approach are separately approved. Product license, pilot, and production decisions remain pre-release gates; no distribution or external data/model integration is authorized by this baseline.

## Change log

- **2026-10-26 — CC-01 technical baseline and validation complete:** verified **76/76 API tests**, a clean dependency check, the Next.js production build, and all **14/14 migrations**, including **75/75 expected tables**, `pgvector`, and roadmap key constraints, in a disposable network-isolated database. Corrected migration 009's conflicting primary-key definition and fixed the dev requirements include path so the README's root-level install command works. All **182** specification functions remain individually marked as not independently acceptance-tested. No production feature thresholds, external providers, credentials, persistent user database, or sibling-project code/models were changed. Active hours and token usage were not independently metered; the approved 40-hour cap therefore cannot be certified retrospectively.
- **2026-10-26 — Owner accepted the CC-01 time-accounting limitation:** closed the completed technical baseline without claiming the unmetered 40-hour cap was met. CC-02 remains paused pending its own approval and an agreed, feasible time-accounting approach.
