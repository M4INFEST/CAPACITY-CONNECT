"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Job = {
  job_id: string;
  title: string;
  description: string;
  role_id: string | null;
  company: { name: string; website: string | null; industry: string | null };
  location: string | null;
  job_type: string | null;
  experience_min_years: number | null;
  experience_max_years: number | null;
  salary_min_cents: number | null;
  salary_max_cents: number | null;
  salary_currency: string;
  external_apply_url: string | null;
  created_at: string;
  source: { name: string; url: string | null; observed_at: string | null };
  saved: boolean;
  required_skills: Array<{
    competency_id: string;
    skill_name: string;
    required_level: number;
    current_level: number;
    importance: number;
  }>;
  match: {
    match_percentage: number;
    recommendation_group: "apply_now" | "almost_there" | "learn_first";
    covered_skills: Array<{ skill_name: string }>;
    skill_gaps: Array<{
      competency_id: string;
      skill_name: string;
      current_level: number;
      required_level: number;
      gap_levels: number;
    }>;
    explanation: string;
  };
  employer_responsiveness: {
    status: "available" | "not_enough_data";
    median_hours: number | null;
    response_count: number;
    minimum_sample_size: number;
  };
  responsiveness_note: string;
};
type InterviewQuestion = {
  id: number;
  category: string;
  skill: string;
  question: string;
  hints: string;
  ideal_elements: string[];
};

type InterviewEvaluation = {
  relevance_score: number;
  confidence_score: number;
  final_score: number;
  strengths: string[];
  improvements: string[];
  rewritten_answer: {
    star: string;
    concise: string;
  };
};

type JobAlert = {

  id: string;
  role_id: string | null;
  role_name: string | null;
  location: string | null;
  job_type: string | null;
  min_salary_cents: number | null;
  competency_ids: string[];
  enabled: boolean;
  updated_at: string;
};
type JobSkill = { competency_id: string; skill_name: string };
type JobResponse = {
  jobs: Job[];
  counts?: { apply_now: number; almost_there: number; learn_first: number };
};
type AlertResponse = { alerts: JobAlert[]; delivery_configured: boolean };
type FilterState = {
  q: string;
  location: string;
  job_type: string;
  experience_min: string;
  experience_max: string;
  salary_min: string;
  skill_id: string;
};

const emptyFilters: FilterState = {
  q: "",
  location: "",
  job_type: "",
  experience_min: "",
  experience_max: "",
  salary_min: "",
  skill_id: "",
};

async function request<T>(
  token: string,
  path: string,
  options?: RequestInit,
): Promise<T> {
  if (!token) {
    throw new Error("Authentication required.");
  }
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options?.body ? { "Content-Type": "application/json" } : {}),
        ...options?.headers,
      },
    });
  } catch {
    throw new Error(`Could not reach the API at ${API_URL}. Start the stack with docker compose up --build.`);
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      window.sessionStorage.removeItem("capacity-connect-token");
      throw new Error("Session expired. Please sign in again.");
    }
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

function groupLabel(group: Job["match"]["recommendation_group"]) {
  return group === "apply_now" ? "Apply now" : group === "almost_there" ? "Almost there" : "Learn first";
}

function money(cents: number | null, currency: string) {
  if (cents === null) return "Not disclosed";
  return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0 }).format(cents / 100);
}

function salaryRange(job: Job) {
  if (job.salary_min_cents === null && job.salary_max_cents === null) return "Salary not disclosed";
  return `${money(job.salary_min_cents, job.salary_currency)} – ${money(job.salary_max_cents, job.salary_currency)}`;
}

export default function JobsPage() {
  const [token, setToken] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [alerts, setAlerts] = useState<JobAlert[]>([]);
  const [skills, setSkills] = useState<JobSkill[]>([]);
  const [filters, setFilters] = useState<FilterState>(emptyFilters);
  const [filterDraft, setFilterDraft] = useState<FilterState>(emptyFilters);
  const [selected, setSelected] = useState<Job | null>(null);
  const [savedOnly, setSavedOnly] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // AI Interview Simulator state (NextStep.AI integration)
  const [interviewOpen, setInterviewOpen] = useState(false);
  const [interviewQuestions, setInterviewQuestions] = useState<InterviewQuestion[]>([]);
  const [activeQuestionIdx, setActiveQuestionIdx] = useState(0);
  const [userAnswer, setUserAnswer] = useState("");
  const [evaluating, setEvaluating] = useState(false);
  const [evaluation, setEvaluation] = useState<InterviewEvaluation | null>(null);
  const [interviewLoading, setInterviewLoading] = useState(false);


  useEffect(() => {
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with your trainee account to explore jobs.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
  }, []);

  const loadJobs = useCallback(async (accessToken: string, currentFilters: FilterState, onlySaved: boolean) => {
    const params = new URLSearchParams();
    if (currentFilters.q.trim()) params.set("q", currentFilters.q.trim());
    if (currentFilters.location.trim()) params.set("location", currentFilters.location.trim());
    if (currentFilters.job_type) params.set("job_type", currentFilters.job_type);
    if (currentFilters.experience_min) params.set("experience_min", currentFilters.experience_min);
    if (currentFilters.experience_max) params.set("experience_max", currentFilters.experience_max);
    if (currentFilters.salary_min) params.set("salary_min_cents", String(Math.round(Number(currentFilters.salary_min) * 100)));
    if (currentFilters.skill_id) params.append("competency_ids", currentFilters.skill_id);
    if (onlySaved) params.set("saved_only", "true");
    const result = await request<JobResponse>(accessToken, `/api/v1/jobs?${params.toString()}`);
    setJobs(result.jobs);
    setSelected((previous) => previous ? result.jobs.find((job) => job.job_id === previous.job_id) ?? null : null);
  }, []);

  const loadAlerts = useCallback(async (accessToken: string) => {
    const result = await request<AlertResponse>(accessToken, "/api/v1/jobs/alerts");
    setAlerts(result.alerts);
  }, []);

  const loadSkills = useCallback(async (accessToken: string) => {
    const result = await request<{ skills: JobSkill[] }>(accessToken, "/api/v1/jobs/skills");
    setSkills(result.skills);
  }, []);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void Promise.all([loadJobs(token, filters, savedOnly), loadAlerts(token), loadSkills(token)])
      .catch((loadError: unknown) => {
        if (!active) return;
        const msg = loadError instanceof Error ? loadError.message : "Could not load jobs.";
        if (msg.includes("Session expired") || msg.includes("Authentication required")) {
          setToken("");
          setError("Sign in with your trainee account to explore jobs.");
        } else {
          setError(msg);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token, filters, savedOnly, loadJobs, loadAlerts, loadSkills]);

  async function syncLiveJobs() {
    if (!token) return;
    setBusy(true);
    setError("");
    setNotice("Fetching real live jobs from external job boards (Remotive)...");
    try {
      const res = await request<{ status: string; total_processed: number; ingested_count: number; updated_count: number }>(
        token,
        "/api/v1/jobs/sync-live?limit=15",
        { method: "POST" },
      );
      setNotice(`Live sync complete: ${res.total_processed} real jobs fetched and updated in database.`);
      await loadJobs(token, filters, savedOnly);
    } catch (syncErr) {
      setError(syncErr instanceof Error ? syncErr.message : "Could not sync live jobs.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleSaved(job: Job) {
    setBusy(true);
    setError("");
    try {
      await request(token, `/api/v1/jobs/${job.job_id}/saved?saved=${!job.saved}`, { method: "PUT" });
      setJobs((current) => current
        .map((item) => item.job_id === job.job_id ? { ...item, saved: !item.saved } : item)
        .filter((item) => !savedOnly || item.saved));
      if (selected?.job_id === job.job_id) setSelected({ ...job, saved: !job.saved });
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not update saved jobs.");
    } finally {
      setBusy(false);
    }
  }

  async function markExternalApplied(job: Job) {
    if (!job.external_apply_url) return;
    setBusy(true);
    setError("");
    try {
      const report = await request<{ status: string }>(
        token,
        `/api/v1/jobs/${job.job_id}/external-application-report`,
        {
          method: "POST",
          body: JSON.stringify({ applied_externally: true, external_url: job.external_apply_url }),
        },
      );
      setNotice("Application reported. It is now tracked in your Application Pipeline.");
    } catch (reportError) {
      setError(reportError instanceof Error ? reportError.message : "Could not record external application.");
    } finally {
      setBusy(false);
    }
  }

  async function openInterviewSimulator(job: Job) {
    setInterviewLoading(true);
    setInterviewOpen(true);
    setError("");
    setEvaluation(null);
    setUserAnswer("");
    setActiveQuestionIdx(0);
    try {
      const data = await request<{ questions: InterviewQuestion[] }>(
        token,
        `/api/v1/jobs/${job.job_id}/interview-prep`,
      );
      setInterviewQuestions(data.questions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate interview questions.");
    } finally {
      setInterviewLoading(false);
    }
  }

  async function evaluateAnswer() {
    if (!selected || !interviewQuestions[activeQuestionIdx]) return;
    if (!userAnswer.trim()) {
      setError("Please write an answer to receive STAR feedback.");
      return;
    }
    setEvaluating(true);
    setError("");
    try {
      const currentQ = interviewQuestions[activeQuestionIdx];
      const res = await request<{ evaluation: InterviewEvaluation }>(
        token,
        `/api/v1/jobs/${selected.job_id}/interview-evaluate`,
        {
          method: "POST",
          body: JSON.stringify({
            question: currentQ.question,
            user_answer: userAnswer,
            required_skill: currentQ.skill,
          }),
        },
      );
      setEvaluation(res.evaluation);
    } catch (evalErr) {
      setError(evalErr instanceof Error ? evalErr.message : "Failed to evaluate interview answer.");
    } finally {
      setEvaluating(false);
    }
  }


  function openExternalApply(job: Job) {
    if (!job.external_apply_url) return;
    window.open(job.external_apply_url, "_blank", "noopener,noreferrer");
    setNotice("After applying on the employer’s site, return here and choose “I applied externally” to self-report it.");
  }

  async function createAlert() {
    const alert = {
      role_id: selected?.role_id ?? null,
      location: filters.location || null,
      job_type: filters.job_type || null,
      min_salary_cents: filters.salary_min ? Math.round(Number(filters.salary_min) * 100) : null,
      competency_ids: filters.skill_id ? [filters.skill_id] : [],
      enabled: true,
    };
    if (!alert.role_id && !alert.location && !alert.job_type && !alert.competency_ids.length) {
      setError("Set a location, job type, or skill filter before creating an alert.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await request<{ id: string; message: string }>(token, "/api/v1/jobs/alerts", {
        method: "POST",
        body: JSON.stringify(alert),
      });
      setNotice(created.message);
      await loadAlerts(token);
    } catch (alertError) {
      setError(alertError instanceof Error ? alertError.message : "Could not save this job alert.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteAlert(id: string) {
    setBusy(true);
    setError("");
    try {
      await request(token, `/api/v1/jobs/alerts/${id}`, { method: "DELETE" });
      setAlerts((current) => current.filter((alert) => alert.id !== id));
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Could not remove the alert.");
    } finally {
      setBusy(false);
    }
  }

  async function showDetail(job: Job) {
    setSelected(job);
    try {
      const result = await request<{ job: Job }>(token, `/api/v1/jobs/${job.job_id}`);
      setSelected(result.job);
    } catch (detailError) {
      setError(detailError instanceof Error ? detailError.message : "Could not load job details.");
    }
  }

  const counts = {
    apply_now: jobs.filter((job) => job.match.recommendation_group === "apply_now").length,
    almost_there: jobs.filter((job) => job.match.recommendation_group === "almost_there").length,
    learn_first: jobs.filter((job) => job.match.recommendation_group === "learn_first").length,
  };

  return (
    <main className="min-h-screen bg-[#0b0f19] px-4 py-8 sm:px-6 lg:px-8 text-slate-100 antialiased selection:bg-blue-500/30">

      <section className="mx-auto max-w-7xl">
        {/* Career Pathway Stepper */}
        <div className="mb-6 rounded-3xl border border-white/10 bg-slate-900/60 p-5 backdrop-blur-xl shadow-xl">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <span className="text-[11px] font-bold uppercase tracking-wider text-cyan-400">Step 6 of Career Journey</span>
              <h2 className="text-sm font-semibold text-white">Competency-Matched Job Explorer & Placement</h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Link
                className="rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-white/10"
                href="/credentials"
              >
                ← Back to Credentials
              </Link>
              <Link
                className="rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-3.5 py-1.5 text-xs font-bold text-white shadow-lg shadow-blue-600/30 hover:brightness-110"
                href="/applications"
              >
                Next: Track Applications →
              </Link>
            </div>
          </div>
        </div>

        <nav aria-label="Jobs navigation" className="flex flex-wrap gap-2 text-xs font-semibold">
          {[
            { href: "/", label: "1. Skill Passport" },
            { href: "/profile", label: "2. Readiness & Gaps" },
            { href: "/learning", label: "3. Course Picks" },
            { href: "/assessment", label: "4. Assessments" },
            { href: "/credentials", label: "5. Credentials" },
            { href: "/jobs", label: "6. Job Matching" },
            { href: "/applications", label: "7. Applications" },
          ].map((item) => (
            <Link
              key={item.href}
              className={`rounded-xl px-3 py-1.5 transition ${
                item.href === "/jobs"
                  ? "border border-blue-500/40 bg-blue-500/20 text-blue-300 shadow-sm"
                  : "border border-white/5 bg-white/5 text-slate-400 hover:border-white/10 hover:text-white"
              }`}
              href={item.href}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <header className="mt-8 flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-5">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-400">Capacity Connect · Stage 11</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight text-white">Competency Job Explorer</h1>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
              Compare active positions directly against your Skill Passport. See whether to apply immediately or bridge gaps first.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-white/10 hover:text-white"
              onClick={() => setAlertsOpen((open) => !open)}
              type="button"
            >
              🔔 {alertsOpen ? "Hide alerts" : `Job alerts (${alerts.length})`}
            </button>
            <button
              className="rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-4 py-2 text-xs font-semibold text-cyan-300 hover:bg-cyan-500/20 disabled:opacity-50"
              disabled={busy}
              onClick={() => void syncLiveJobs()}
              type="button"
            >
              🔄 Sync Live Postings (Remotive)
            </button>
            <button
              className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-white/10 hover:text-white"
              onClick={() => setSavedOnly((value) => !value)}
              type="button"
            >
              {savedOnly ? "All jobs" : "Saved jobs"}
            </button>
            <Link
              className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white shadow-lg shadow-blue-600/30 hover:bg-blue-500"
              href="/applications"
            >
              📑 My Applications
            </Link>
          </div>
        </header>
        {(error || notice) && (
          <p className={`mt-5 rounded-xl p-4 text-sm ${error ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-800"}`} role={error ? "alert" : "status"}>
            {error || notice}
          </p>
        )}
        {alertsOpen && (
          <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-bold">Job alerts</h2>
            <p className="mt-1 text-sm text-slate-600">
              Save alerts from the current location, job type, salary and skill filters. Email delivery is not configured.
            </p>
            <button className="mt-3 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void createAlert()} type="button">
              Save current filters as alert
            </button>
            {alerts.length > 0 && (
              <ul className="mt-4 divide-y divide-slate-100">
                {alerts.map((alert) => (
                  <li className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm" key={alert.id}>
                    <span>
                      {[alert.role_name, alert.location, alert.job_type?.replaceAll("_", " "), alert.min_salary_cents ? `Min ${money(alert.min_salary_cents, "INR")}` : null]
                        .filter(Boolean).join(" · ") || "Custom skill alert"}
                      {!alert.enabled && <span className="ml-2 text-slate-500">(paused)</span>}
                    </span>
                    <button className="font-semibold text-rose-700 underline disabled:opacity-50" disabled={busy} onClick={() => void deleteAlert(alert.id)} type="button">Remove</button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        <form className="mt-6 grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(event) => {
          event.preventDefault();
          setFilters({ ...filterDraft });
          setSelected(null);
          setError("");
        }}>
          <label className="text-xs font-semibold text-slate-700">Search jobs or companies
            <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" onChange={(event) => setFilterDraft({ ...filterDraft, q: event.target.value })} placeholder="Role, skill, employer" value={filterDraft.q} />
          </label>
          <label className="text-xs font-semibold text-slate-700">Location
            <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" onChange={(event) => setFilterDraft({ ...filterDraft, location: event.target.value })} placeholder="City or remote" value={filterDraft.location} />
          </label>
          <label className="text-xs font-semibold text-slate-700">Job type
            <select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" onChange={(event) => setFilterDraft({ ...filterDraft, job_type: event.target.value })} value={filterDraft.job_type}>
              <option value="">Any type</option><option value="full_time">Full-time</option><option value="part_time">Part-time</option><option value="contract">Contract</option><option value="internship">Internship</option>
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-700">Required skill
            <select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" onChange={(event) => setFilterDraft({ ...filterDraft, skill_id: event.target.value })} value={filterDraft.skill_id}>
              <option value="">Any skill</option>
              {skills.map((skill) => <option key={skill.competency_id} value={skill.competency_id}>{skill.skill_name}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-700">Minimum experience (years)
            <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" min="0" onChange={(event) => setFilterDraft({ ...filterDraft, experience_min: event.target.value })} type="number" value={filterDraft.experience_min} />
          </label>
          <label className="text-xs font-semibold text-slate-700">Maximum experience (years)
            <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" min="0" onChange={(event) => setFilterDraft({ ...filterDraft, experience_max: event.target.value })} type="number" value={filterDraft.experience_max} />
          </label>
          <label className="text-xs font-semibold text-slate-700">Minimum salary (₹)
            <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" min="0" onChange={(event) => setFilterDraft({ ...filterDraft, salary_min: event.target.value })} type="number" value={filterDraft.salary_min} />
          </label>
          <div className="flex items-end gap-2">
            <button className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white" type="submit">Apply filters</button>
            <button className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold" onClick={() => {
              setFilterDraft(emptyFilters);
              setFilters(emptyFilters);
              setSavedOnly(false);
              setSelected(null);
            }} type="button">Clear</button>
          </div>
        </form>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          {([
            ["apply_now", "Apply now · 70%+"],
            ["almost_there", "Almost there · 50–69%"],
            ["learn_first", "Learn first · under 50%"],
          ] as const).map(([group, label]) => (
            <div className="rounded-xl border border-slate-200 bg-white p-4" key={group}>
              <p className="text-sm text-slate-600">{label}</p>
              <p className="mt-1 text-2xl font-bold text-slate-950">{counts[group]}</p>
            </div>
          ))}
        </div>

        {loading && <p className="mt-6 text-slate-600">Loading active jobs…</p>}
        {!loading && jobs.length === 0 && (
          <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="font-bold">{savedOnly ? "No saved jobs yet" : "No active jobs match these filters"}</h2>
            <p className="mt-2 text-sm text-slate-600">
              Jobs appear here after an employer or authorized operator publishes them. The catalog does not contain generated sample listings.
            </p>
            {savedOnly && <button className="mt-3 font-semibold text-blue-700 underline" onClick={() => setSavedOnly(false)} type="button">Browse all jobs</button>}
          </div>
        )}
        {!loading && jobs.length > 0 && (
          <div className="mt-6 grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(350px,0.9fr)]">
            <section aria-label="Job results" className="space-y-3">
              {jobs.map((job) => (
                <article className={`rounded-2xl border bg-white p-4 shadow-sm ${selected?.job_id === job.job_id ? "border-blue-500 ring-2 ring-blue-100" : "border-slate-200"}`} key={job.job_id}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <button className="text-left" onClick={() => void showDetail(job)} type="button">
                      <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">{groupLabel(job.match.recommendation_group)}</p>
                      <h2 className="mt-1 text-lg font-bold text-slate-950">{job.title}</h2>
                      <p className="mt-1 font-medium text-slate-700">{job.company.name}</p>
                    </button>
                    <div className="text-right">
                      <p className="text-2xl font-bold text-slate-950">{job.match.match_percentage}%</p>
                      <p className="text-xs text-slate-500">skill match</p>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600">
                    <span>{job.location ?? "Location not specified"}</span>
                    <span>{job.job_type?.replaceAll("_", " ") ?? "Type not specified"}</span>
                    <span>{salaryRange(job)}</span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                    <p className="text-xs text-slate-500">
                      {job.employer_responsiveness.status === "available"
                        ? `Typical reply: ${job.employer_responsiveness.median_hours} hours (n=${job.employer_responsiveness.response_count})`
                        : job.responsiveness_note}
                    </p>
                    <div className="flex gap-2">
                      <button className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold disabled:opacity-50" disabled={busy} onClick={() => void toggleSaved(job)} type="button">{job.saved ? "Unsave" : "Save"}</button>
                      <button className="rounded-lg bg-blue-700 px-3 py-1.5 text-sm font-semibold text-white" onClick={() => void showDetail(job)} type="button">Details</button>
                    </div>
                  </div>
                </article>
              ))}
            </section>
            {selected && (
              <aside className="sticky top-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <button className="float-right font-semibold text-slate-500" onClick={() => setSelected(null)} type="button">Close</button>
                <p className="text-xs font-bold uppercase tracking-wide text-blue-700">{groupLabel(selected.match.recommendation_group)} · {selected.match.match_percentage}% match</p>
                <h2 className="mt-2 text-2xl font-bold text-slate-950">{selected.title}</h2>
                <p className="mt-1 font-semibold">{selected.company.name}</p>
                {selected.company.website && <a className="mt-1 inline-block text-sm text-blue-700 underline" href={selected.company.website} rel="noreferrer" target="_blank">Company profile</a>}
                {selected.company.industry && <p className="mt-1 text-sm text-slate-600">{selected.company.industry}</p>}
                <p className="mt-4 whitespace-pre-wrap text-sm text-slate-700">{selected.description || "No job description supplied."}</p>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div><dt className="text-slate-500">Location</dt><dd className="font-medium">{selected.location ?? "Not specified"}</dd></div>
                  <div><dt className="text-slate-500">Job type</dt><dd className="font-medium">{selected.job_type?.replaceAll("_", " ") ?? "Not specified"}</dd></div>
                  <div><dt className="text-slate-500">Experience</dt><dd className="font-medium">{selected.experience_min_years ?? 0}–{selected.experience_max_years ?? "unspecified"} years</dd></div>
                  <div><dt className="text-slate-500">Salary</dt><dd className="font-medium">{salaryRange(selected)}</dd></div>
                  <div><dt className="text-slate-500">Employer response</dt><dd className="font-medium">{selected.employer_responsiveness.status === "available" ? `${selected.employer_responsiveness.median_hours} hours median` : "Not enough data"}</dd></div>
                </dl>
                <p className="mt-4 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">{selected.match.explanation}</p>
                <div className="mt-4">
                  <h3 className="font-bold">Skills and gaps</h3>
                  <ul className="mt-2 space-y-2 text-sm">
                    {selected.required_skills.map((skill) => (
                      <li className="flex justify-between gap-3" key={skill.competency_id}>
                        <span>{skill.skill_name}{skill.importance < 1 ? ` · importance ${(skill.importance * 100).toFixed(0)}%` : ""}</span>
                        <span className={skill.current_level >= skill.required_level ? "text-emerald-700" : "text-amber-800"}>Level {skill.current_level}/{skill.required_level}</span>
                      </li>
                    ))}
                    {selected.required_skills.length === 0 && <li className="text-slate-500">No skill requirements were supplied for this listing.</li>}
                  </ul>
                </div>
                {selected.match.skill_gaps.length > 0 && (
                  <div className="mt-4 rounded-xl bg-amber-50 p-3">
                    <h3 className="font-bold text-amber-950">Learn first</h3>
                    <ul className="mt-2 space-y-1 text-sm text-amber-900">
                      {selected.match.skill_gaps.map((gap) => <li key={gap.competency_id}>{gap.skill_name} · need {gap.required_level}, Passport {gap.current_level}</li>)}
                    </ul>
                    <Link className="mt-3 inline-block text-sm font-semibold text-blue-700 underline" href="/learning">Find courses</Link>
                  </div>
                )}
                <div className="mt-5 flex flex-wrap gap-2">
                  <button
                    className="rounded-xl border border-indigo-500/40 bg-gradient-to-r from-indigo-900/60 to-purple-900/60 px-4 py-2 text-sm font-semibold text-indigo-200 shadow-sm transition hover:border-indigo-400 hover:text-white"
                    onClick={() => void openInterviewSimulator(selected)}
                    type="button"
                  >
                    ✨ Practice AI Interview (STAR)
                  </button>
                  {selected.external_apply_url ? (
                    <>
                      <button className="rounded-xl bg-blue-700 px-4 py-2 text-sm font-semibold text-white" onClick={() => openExternalApply(selected)} type="button">Apply externally</button>
                      <button className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50" disabled={busy} onClick={() => void markExternalApplied(selected)} type="button">I applied externally</button>
                    </>
                  ) : (
                    <button className="rounded-xl bg-blue-700 px-4 py-2 text-sm font-semibold text-white" onClick={() => window.location.assign(`/applications/new/${selected.job_id}`)} type="button">
                      Continue to application
                    </button>
                  )}
                  <button className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50" disabled={busy} onClick={() => void toggleSaved(selected)} type="button">{selected.saved ? "Unsave job" : "Save job"}</button>
                </div>

                <p className="mt-3 text-xs text-slate-500">
                  Source: {selected.source.name}
                  {selected.source.observed_at ? ` · observed ${new Date(selected.source.observed_at).toLocaleDateString()}` : ""}
                  {selected.source.url && <> · <a className="underline" href={selected.source.url} rel="noreferrer" target="_blank">listing source</a></>}
                </p>
              </aside>
            )}
          </div>
        )}
      </section>

      {/* AI Interview Prep & Evaluation Modal (Integrated from NextStep.AI) */}
      {interviewOpen && selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-3xl border border-slate-700/60 bg-[#0f172a] p-6 text-white shadow-2xl sm:p-8">
            <button
              className="absolute right-5 top-5 rounded-full p-2 text-slate-400 hover:bg-slate-800 hover:text-white"
              onClick={() => {
                setInterviewOpen(false);
                setEvaluation(null);
              }}
              type="button"
            >
              ✕
            </button>

            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-600 to-purple-600 text-lg font-bold shadow-md">
                🎯
              </span>
              <div>
                <p className="text-xs font-bold uppercase tracking-wider text-indigo-400">
                  NextStep.AI · Simulation Studio
                </p>
                <h2 className="text-xl font-bold text-white sm:text-2xl">
                  Mock Interview: {selected.title}
                </h2>
              </div>
            </div>

            {interviewLoading && (
              <div className="mt-8 flex flex-col items-center justify-center py-12 text-slate-400">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
                <p className="mt-4 text-sm font-medium">Generating questions tailored to this job's competencies…</p>
              </div>
            )}

            {!interviewLoading && interviewQuestions.length > 0 && (
              <div className="mt-6 space-y-6">
                {/* Question Tabs */}
                <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
                  {interviewQuestions.map((q, idx) => (
                    <button
                      className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                        activeQuestionIdx === idx
                          ? "bg-indigo-600 text-white shadow"
                          : "bg-slate-800/80 text-slate-300 hover:bg-slate-700"
                      }`}
                      key={q.id}
                      onClick={() => {
                        setActiveQuestionIdx(idx);
                        setEvaluation(null);
                        setUserAnswer("");
                      }}
                      type="button"
                    >
                      Question {idx + 1}: {q.skill}
                    </button>
                  ))}
                </div>

                {/* Active Question Prompt */}
                {interviewQuestions[activeQuestionIdx] && (
                  <div className="rounded-2xl border border-indigo-900/40 bg-indigo-950/20 p-5">
                    <div className="flex items-center justify-between">
                      <span className="rounded-md bg-indigo-500/20 px-2 py-0.5 text-xs font-semibold text-indigo-300">
                        {interviewQuestions[activeQuestionIdx].category}
                      </span>
                      <span className="text-xs text-slate-400">
                        Focus: {interviewQuestions[activeQuestionIdx].skill}
                      </span>
                    </div>
                    <p className="mt-3 text-base font-semibold leading-relaxed text-slate-100 sm:text-lg">
                      "{interviewQuestions[activeQuestionIdx].question}"
                    </p>
                    <p className="mt-2 text-xs text-indigo-300/80">
                      💡 Tip: {interviewQuestions[activeQuestionIdx].hints}
                    </p>
                  </div>
                )}

                {/* Candidate Answer Box */}
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Your Response (STAR: Situation, Task, Action, Result)
                  </label>
                  <textarea
                    className="mt-2 w-full rounded-2xl border border-slate-700 bg-slate-900/90 p-4 text-sm text-slate-100 placeholder-slate-500 shadow-inner focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    onChange={(e) => setUserAnswer(e.target.value)}
                    placeholder="When I was working on... I was responsible for... To solve this, I designed and deployed... This resulted in a 35% speedup..."
                    rows={6}
                    value={userAnswer}
                  />
                  <div className="mt-3 flex items-center justify-between">
                    <p className="text-xs text-slate-500">
                      Word count: {userAnswer.trim().split(/\s+/).filter(Boolean).length}
                    </p>
                    <button
                      className="rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 px-5 py-2.5 text-sm font-bold text-white shadow-lg transition hover:brightness-110 disabled:opacity-50"
                      disabled={evaluating || !userAnswer.trim()}
                      onClick={() => void evaluateAnswer()}
                      type="button"
                    >
                      {evaluating ? "Evaluating Answer (STAR)…" : "Submit for STAR Evaluation"}
                    </button>
                  </div>
                </div>

                {/* Evaluation Feedback Panel */}
                {evaluation && (
                  <div className="space-y-4 rounded-2xl border border-slate-700/80 bg-slate-900/60 p-6 animate-fadeIn">
                    <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
                      <div>
                        <span className="text-xs uppercase font-bold tracking-wider text-emerald-400">STAR Scoring</span>
                        <h3 className="text-lg font-bold text-white">Evaluation Results</h3>
                      </div>
                      <div className="flex gap-4">
                        <div className="text-center">
                          <p className="text-xs text-slate-400">Relevance</p>
                          <p className="text-xl font-black text-indigo-400">{evaluation.relevance_score}/100</p>
                        </div>
                        <div className="text-center">
                          <p className="text-xs text-slate-400">Confidence</p>
                          <p className="text-xl font-black text-purple-400">{evaluation.confidence_score}/100</p>
                        </div>
                        <div className="text-center">
                          <p className="text-xs text-slate-400">Hiring Score</p>
                          <p className="text-xl font-black text-emerald-400">{evaluation.final_score}/100</p>
                        </div>
                      </div>
                    </div>

                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="rounded-xl border border-emerald-950/60 bg-emerald-950/20 p-4">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-400">Strengths</h4>
                        <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-300">
                          {evaluation.strengths.map((s, idx) => (
                            <li key={idx}>{s}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="rounded-xl border border-amber-950/60 bg-amber-950/20 p-4">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-amber-400">Actionable Improvements</h4>
                        <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-300">
                          {evaluation.improvements.map((imp, idx) => (
                            <li key={idx}>{imp}</li>
                          ))}
                        </ul>
                      </div>
                    </div>

                    {evaluation.rewritten_answer?.concise && (
                      <div className="rounded-xl border border-indigo-950/60 bg-indigo-950/20 p-4">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400">
                          🌟 High-Impact Live Interview Rewrite
                        </h4>
                        <p className="mt-1 text-xs italic text-slate-200">
                          "{evaluation.rewritten_answer.concise}"
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}

