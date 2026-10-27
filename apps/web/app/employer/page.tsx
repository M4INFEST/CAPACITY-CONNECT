"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type User = {
  roles: string[];
  employer_verification_level: number | null;
};
type Role = { role_id: string; name: string };
type Competency = { competency_id: string; skill_name: string };
type EmployerJob = {
  job_id: string;
  title: string;
  active: boolean;
  location: string | null;
  job_type: string | null;
  applicant_count: number;
  new_applicants: number;
};
type EmployerCompany = {
  company_name: string;
  website: string | null;
  industry: string | null;
  verification_level: number;
};
type JobQuestion = {
  prompt: string;
  answer_type: "text" | "yes_no" | "single_choice";
  options: string[];
  required: boolean;
};
type Dashboard = {
  open_jobs: number;
  paused_jobs: number;
  new_applicants: number;
  shortlisted: number;
  interviewing: number;
  offers: number;
  company: { company_name: string; verification_level: number } | null;
};
type SkillRequirement = { competency_id: string; required_level: number; importance: number };

async function request<T>(token: string, path: string, options?: RequestInit): Promise<T> {
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
    throw new Error(`Could not reach the API at ${API_URL}.`);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function EmployerWorkspacePage() {
  const [token, setToken] = useState("");
  const [verificationLevel, setVerificationLevel] = useState<number | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [company, setCompany] = useState<EmployerCompany | null>(null);
  const [jobs, setJobs] = useState<EmployerJob[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [competencies, setCompetencies] = useState<Competency[]>([]);
  const [requirements, setRequirements] = useState<Record<string, number>>({});
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [roleId, setRoleId] = useState("");
  const [location, setLocation] = useState("");
  const [jobType, setJobType] = useState("");
  const [salaryMin, setSalaryMin] = useState("");
  const [salaryMax, setSalaryMax] = useState("");
  const [questionPrompt, setQuestionPrompt] = useState("");
  const [questionRequired, setQuestionRequired] = useState(false);
  const [questions, setQuestions] = useState<JobQuestion[]>([]);
  const [editingJobId, setEditingJobId] = useState("");
  const [companyNameDraft, setCompanyNameDraft] = useState("");
  const [companyWebsiteDraft, setCompanyWebsiteDraft] = useState("");
  const [companyIndustryDraft, setCompanyIndustryDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load(accessToken: string) {
    const [summary, jobRows] = await Promise.all([
      request<Dashboard>(accessToken, "/api/v1/employer/dashboard"),
      request<{ jobs: EmployerJob[] }>(accessToken, "/api/v1/employer/jobs"),
    ]);
    setDashboard(summary);
    setCompanyName(summary.company?.company_name ?? "Employer");
    setJobs(jobRows.jobs);
    const [roleRows, competencyRows, companyProfile] = await Promise.all([
      request<Role[]>(accessToken, "/api/v1/employer/roles"),
      request<Competency[]>(accessToken, "/api/v1/employer/competencies"),
      request<EmployerCompany>(accessToken, "/api/v1/employer/company"),
    ]);
    setRoles(roleRows);
    setCompetencies(competencyRows);
    setCompany(companyProfile);
    setCompanyNameDraft(companyProfile.company_name);
    setCompanyWebsiteDraft(companyProfile.website ?? "");
    setCompanyIndustryDraft(companyProfile.industry ?? "");
  }

  useEffect(() => {
    let active = true;
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with your employer account to open this workspace.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void request<User>(accessToken, "/api/v1/auth/me")
      .then(async (user) => {
        if (!user.roles.includes("employer")) {
          throw new Error("This workspace is only available to employer accounts.");
        }
        if (!active) return;
        setVerificationLevel(user.employer_verification_level);
        if (user.employer_verification_level === 2) await load(accessToken);
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load employer workspace.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function refresh() {
    await load(token);
  }

  async function createJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const wasEditing = Boolean(editingJobId);
    const selectedRequirements: SkillRequirement[] = Object.entries(requirements).map(
      ([competency_id, required_level]) => ({ competency_id, required_level, importance: 1 }),
    );
    if (selectedRequirements.length === 0 && !roleId) {
      setError("Choose at least one required skill or select a platform role.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request<{ job_id: string }>(
        token,
        editingJobId ? `/api/v1/employer/jobs/${editingJobId}` : "/api/v1/employer/jobs",
        {
        method: editingJobId ? "PUT" : "POST",
        body: JSON.stringify({
          title,
          description,
          role_id: roleId || null,
          location: location || null,
          job_type: jobType || null,
          salary_min_cents: salaryMin ? Math.round(Number(salaryMin) * 100) : null,
          salary_max_cents: salaryMax ? Math.round(Number(salaryMax) * 100) : null,
          salary_currency: "INR",
          requirements: selectedRequirements,
          questions: questionPrompt.trim()
            ? [...questions, {
                prompt: questionPrompt.trim(),
                answer_type: "text",
                options: [],
                required: questionRequired,
              }]
            : questions,
          active: true,
        }),
      });
      setTitle("");
      setDescription("");
      setRoleId("");
      setLocation("");
      setJobType("");
      setSalaryMin("");
      setSalaryMax("");
      setRequirements({});
      setQuestionPrompt("");
      setQuestionRequired(false);
      setQuestions([]);
      setEditingJobId("");
      await refresh();
      setNotice(`${wasEditing ? "Job updated" : "Job published"}. Job reference: ${result.job_id}`);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not publish the job.");
    } finally {
      setBusy(false);
    }
  }

  async function editJob(job: EmployerJob) {
    setBusy(true);
    setError("");
    try {
      const detail = await request<{
        job_id: string;
        title: string;
        description: string;
        role_id: string | null;
        location: string | null;
        job_type: string | null;
        salary_min_cents: number | null;
        salary_max_cents: number | null;
        requirements: SkillRequirement[];
        questions: JobQuestion[];
      }>(token, `/api/v1/employer/jobs/${job.job_id}`);
      setEditingJobId(detail.job_id);
      setTitle(detail.title);
      setDescription(detail.description);
      setRoleId(detail.role_id ?? "");
      setLocation(detail.location ?? "");
      setJobType(detail.job_type ?? "");
      setSalaryMin(detail.salary_min_cents === null ? "" : String(detail.salary_min_cents / 100));
      setSalaryMax(detail.salary_max_cents === null ? "" : String(detail.salary_max_cents / 100));
      setRequirements(Object.fromEntries(detail.requirements.map((item) => [item.competency_id, item.required_level])));
      setQuestions(detail.questions);
      setQuestionPrompt("");
      setQuestionRequired(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (editError) {
      setError(editError instanceof Error ? editError.message : "Could not load job details.");
    } finally {
      setBusy(false);
    }
  }

  function cancelJobEdit() {
    setEditingJobId("");
    setTitle("");
    setDescription("");
    setRoleId("");
    setLocation("");
    setJobType("");
    setSalaryMin("");
    setSalaryMax("");
    setRequirements({});
    setQuestions([]);
    setQuestionPrompt("");
    setQuestionRequired(false);
  }

  async function saveCompanyProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await request<EmployerCompany>(token, "/api/v1/employer/company", {
        method: "PUT",
        body: JSON.stringify({
          company_name: companyNameDraft,
          website: companyWebsiteDraft || null,
          industry: companyIndustryDraft || null,
        }),
      });
      setCompany(updated);
      setCompanyName(updated.company_name);
      setVerificationLevel(updated.verification_level);
      setNotice(updated.verification_level === 2
        ? "Company profile updated."
        : "Company identity changed. Administrator re-verification is required before hiring access resumes.");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not update company profile.");
    } finally {
      setBusy(false);
    }
  }

  async function setJobActive(job: EmployerJob) {
    setBusy(true);
    setError("");
    try {
      await request(token, `/api/v1/employer/jobs/${job.job_id}/active`, {
        method: "PATCH",
        body: JSON.stringify({ active: !job.active }),
      });
      await refresh();
      setNotice(job.active ? "Job paused; it is no longer visible to learners." : "Job reopened.");
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : "Could not update job status.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <section className="mx-auto max-w-6xl">
        <nav className="flex flex-wrap gap-4 text-sm font-semibold">
          <Link className="text-blue-700 underline" href="/">Capacity Connect</Link>
          <Link className="text-blue-700 underline" href="/jobs">Learner job explorer</Link>
        </nav>
        <header className="mt-7 rounded-3xl bg-slate-950 p-7 text-white">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-300">Capacity Connect · Stage 13</p>
          <h1 className="mt-2 text-3xl font-bold">Employer workspace</h1>
          <p className="mt-2 text-slate-300">{companyName} · Verified candidate review and job management</p>
        </header>
        {error && <p className="mt-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-800" role="alert">{error}</p>}
        {notice && <p className="mt-5 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800" role="status">{notice}</p>}
        {loading && <p className="mt-6 text-slate-600">Loading employer workspace…</p>}
        {!loading && verificationLevel !== 2 && (
          <section className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-6">
            <h2 className="text-xl font-bold text-amber-950">Business verification required</h2>
            <p className="mt-2 text-amber-900">
              Your account is at verification level {verificationLevel ?? 0}. New employer accounts cannot access candidate data or publish jobs. An administrator must verify your business to Level 2 first.
            </p>
            <p className="mt-2 text-sm text-amber-800">Candidate information is protected; do not send learner profiles or application data outside this workspace.</p>
          </section>
        )}
        {!loading && verificationLevel === 2 && dashboard && (
          <>
            <section aria-label="Hiring pipeline counts" className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
              {[
                ["Open jobs", dashboard.open_jobs],
                ["Paused jobs", dashboard.paused_jobs],
                ["New applicants", dashboard.new_applicants],
                ["Shortlisted", dashboard.shortlisted],
                ["Interviews", dashboard.interviewing],
                ["Offers", dashboard.offers],
              ].map(([label, value]) => (
                <div className="rounded-2xl border border-slate-200 bg-white p-4" key={label}>
                  <p className="text-sm text-slate-500">{label}</p>
                  <p className="mt-1 text-2xl font-bold text-slate-950">{value}</p>
                </div>
              ))}
            </section>
            <section className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.2fr]">
              <form className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5" onSubmit={(event) => void createJob(event)}>
                <div>
                  <h2 className="text-xl font-bold">{editingJobId ? "Edit job" : "Post a job"}</h2>
                  <p className="mt-1 text-sm text-slate-600">Only Level 2 verified employers can publish. Use skills that are necessary for this role.</p>
                </div>
                <label className="block text-sm font-semibold">Job title
                  <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" maxLength={200} onChange={(event) => setTitle(event.target.value)} required value={title} />
                </label>
                <label className="block text-sm font-semibold">Job description
                  <textarea className="mt-1 w-full rounded-lg border border-slate-300 p-3 font-normal" minLength={20} maxLength={20000} onChange={(event) => setDescription(event.target.value)} required rows={5} value={description} />
                </label>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="block text-sm font-semibold">Platform role (optional)
                    <select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" onChange={(event) => setRoleId(event.target.value)} value={roleId}>
                      <option value="">Select role</option>
                      {roles.map((role) => <option key={role.role_id} value={role.role_id}>{role.name}</option>)}
                    </select>
                  </label>
                  <label className="block text-sm font-semibold">Location
                    <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" onChange={(event) => setLocation(event.target.value)} value={location} />
                  </label>
                  <label className="block text-sm font-semibold">Employment type
                    <select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" onChange={(event) => setJobType(event.target.value)} value={jobType}>
                      <option value="">Not specified</option>
                      <option value="full_time">Full time</option>
                      <option value="part_time">Part time</option>
                      <option value="contract">Contract</option>
                      <option value="internship">Internship</option>
                    </select>
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="block text-sm font-semibold">Minimum salary (₹/year)
                      <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" min="0" onChange={(event) => setSalaryMin(event.target.value)} type="number" value={salaryMin} />
                    </label>
                    <label className="block text-sm font-semibold">Maximum (₹/year)
                      <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" min="0" onChange={(event) => setSalaryMax(event.target.value)} type="number" value={salaryMax} />
                    </label>
                  </div>
                </div>
                <fieldset className="rounded-xl border border-slate-200 p-3">
                  <legend className="px-1 text-sm font-bold">Required competencies</legend>
                  <p className="mb-2 text-xs text-slate-500">A weighted skill-level match will explain each applicant ranking.</p>
                  <div className="max-h-56 space-y-2 overflow-y-auto">
                    {competencies.map((skill) => (
                      <div className="flex items-center gap-3" key={skill.competency_id}>
                        <label className="flex flex-1 items-center gap-2 text-sm">
                          <input checked={requirements[skill.competency_id] !== undefined} onChange={(event) => setRequirements((current) => {
                            const next = { ...current };
                            if (event.target.checked) next[skill.competency_id] = 3;
                            else delete next[skill.competency_id];
                            return next;
                          })} type="checkbox" />
                          {skill.skill_name}
                        </label>
                        {requirements[skill.competency_id] !== undefined && (
                          <select aria-label={`Required level for ${skill.skill_name}`} className="rounded border border-slate-300 px-2 py-1 text-sm" onChange={(event) => setRequirements((current) => ({ ...current, [skill.competency_id]: Number(event.target.value) }))} value={requirements[skill.competency_id]}>
                            {[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>Level {level}</option>)}
                          </select>
                        )}
                      </div>
                    ))}
                  </div>
                </fieldset>
                <div className="rounded-xl border border-slate-200 p-3">
                  <label className="block text-sm font-semibold">Optional application question
                    <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" maxLength={1000} onChange={(event) => setQuestionPrompt(event.target.value)} placeholder="e.g. What is your earliest start date?" value={questionPrompt} />
                  </label>
                  <label className="mt-2 flex items-center gap-2 text-sm">
                    <input checked={questionRequired} onChange={(event) => setQuestionRequired(event.target.checked)} type="checkbox" />
                    Require an answer
                  </label>
                  <button className="mt-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={!questionPrompt.trim() || questions.length >= 10} onClick={() => {
                    setQuestions((current) => [...current, {
                      prompt: questionPrompt.trim(),
                      answer_type: "text",
                      options: [],
                      required: questionRequired,
                    }]);
                    setQuestionPrompt("");
                    setQuestionRequired(false);
                  }} type="button">Add question</button>
                  {questions.length > 0 && (
                    <ul className="mt-3 space-y-2 text-sm">
                      {questions.map((question, index) => (
                        <li className="flex items-start justify-between gap-2 rounded-lg bg-slate-50 p-2" key={`${question.prompt}-${index}`}>
                          <span>{question.prompt} {question.required ? "(required)" : "(optional)"}</span>
                          <button aria-label={`Remove question ${index + 1}`} className="text-rose-700 underline" onClick={() => setQuestions((current) => current.filter((_, itemIndex) => itemIndex !== index))} type="button">Remove</button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <button className="w-full rounded-lg bg-blue-700 px-4 py-3 font-semibold text-white disabled:opacity-50" disabled={busy}>
                  {busy ? "Saving…" : editingJobId ? "Save job changes" : "Publish job"}
                </button>
                {editingJobId && <button className="w-full rounded-lg border border-slate-300 px-4 py-3 font-semibold" disabled={busy} onClick={cancelJobEdit} type="button">Cancel edit</button>}
              </form>
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h2 className="text-xl font-bold">Your jobs</h2>
                    <p className="mt-1 text-sm text-slate-600">Applicant lists include only learners who consented to share this application.</p>
                  </div>
                  <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold" disabled={busy} onClick={() => void refresh()} type="button">Refresh</button>
                </div>
                <div className="mt-4 space-y-3">
                  {jobs.length === 0 && <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">No jobs posted yet.</p>}
                  {jobs.map((job) => (
                    <article className="rounded-xl border border-slate-200 p-4" key={job.job_id}>
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h3 className="font-bold">{job.title}</h3>
                          <p className="mt-1 text-sm text-slate-600">{job.location || "Location not specified"} · {job.active ? "Open" : "Paused"}</p>
                          <p className="mt-1 text-sm text-slate-600">{job.applicant_count} consented applicants · {job.new_applicants} new</p>
                        </div>
                        <div className="flex gap-2">
                          <Link className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white" href={`/employer/jobs/${job.job_id}`}>Review</Link>
                          <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold" disabled={busy} onClick={() => void editJob(job)} type="button">Edit</button>
                          <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold" disabled={busy} onClick={() => void setJobActive(job)} type="button">{job.active ? "Pause" : "Reopen"}</button>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            </section>
            {company && (
              <form className="mt-6 grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 sm:grid-cols-2" onSubmit={(event) => void saveCompanyProfile(event)}>
                <div className="sm:col-span-2">
                  <h2 className="text-xl font-bold">Company profile</h2>
                  <p className="mt-1 text-sm text-slate-600">Changing company name or website resets verification for candidate privacy. Industry-only updates retain verification.</p>
                </div>
                <label className="block text-sm font-semibold">Company name
                  <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" maxLength={200} onChange={(event) => setCompanyNameDraft(event.target.value)} required value={companyNameDraft} />
                </label>
                <label className="block text-sm font-semibold">Website
                  <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" onChange={(event) => setCompanyWebsiteDraft(event.target.value)} placeholder="https://example.com" type="url" value={companyWebsiteDraft} />
                </label>
                <label className="block text-sm font-semibold">Industry
                  <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" maxLength={120} onChange={(event) => setCompanyIndustryDraft(event.target.value)} value={companyIndustryDraft} />
                </label>
                <div className="flex items-end">
                  <button className="rounded-lg border border-slate-300 px-4 py-2 font-semibold disabled:opacity-50" disabled={busy} type="submit">Save company profile</button>
                </div>
              </form>
            )}
            <p className="mt-5 text-xs text-slate-500">Blind review hides learner identity and free-text application content. Every profile access is logged and capped at 50 views per employer per rolling 24 hours.</p>
          </>
        )}
      </section>
    </main>
  );
}
