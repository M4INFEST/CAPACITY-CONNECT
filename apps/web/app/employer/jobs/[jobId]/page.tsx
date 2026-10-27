"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type ApplicantSkill = { skill_name: string; level: number | null };
type Applicant = {
  application_id: string;
  candidate_code: string;
  status: string;
  applied_at: string;
  fit: {
    match_percentage: number;
    scoring_version: string;
    explanation: string;
    skills: Array<{
      competency_id: string;
      skill_name: string;
      required_level: number;
      current_level: number;
      evidence_status: "verified" | "claimed";
    }>;
  };
  skills: { verified: ApplicantSkill[]; claimed: ApplicantSkill[] };
  verified_credentials: Array<{ skill_name: string; level: number; evidence_tier: string }>;
};
type ApplicantResponse = {
  job: { job_id: string; title: string; active: boolean };
  scoring_explanation: string;
  applicants: Applicant[];
};
type Profile = Applicant & {
  job: { job_id: string; title: string };
  employer_note: { note: string; tags: string[] };
  remaining_profile_views_today: number;
};
type RejectionReason = "position_filled" | "role_changed" | "candidate_withdrew";

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

function label(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function EmployerApplicantsPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params.jobId;
  const [token, setToken] = useState("");
  const [job, setJob] = useState<ApplicantResponse["job"] | null>(null);
  const [applicants, setApplicants] = useState<Applicant[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<Profile | null>(null);
  const [rejectionReason, setRejectionReason] = useState<RejectionReason>("position_filled");
  const [noteText, setNoteText] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [filter, setFilter] = useState("");
  const [comparison, setComparison] = useState<Applicant[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load(accessToken: string, selectedFilter = filter) {
    const result = await request<ApplicantResponse>(
      accessToken,
      `/api/v1/employer/jobs/${jobId}/applicants${selectedFilter ? `?status=${encodeURIComponent(selectedFilter)}` : ""}`,
    );
    setJob(result.job);
    setApplicants(result.applicants);
  }

  useEffect(() => {
    let active = true;
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with a verified employer account to review applicants.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void request<ApplicantResponse>(accessToken, `/api/v1/employer/jobs/${jobId}/applicants`)
      .then((result) => {
        if (!active) return;
        setJob(result.job);
        setApplicants(result.applicants);
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load applicants.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [jobId]);

  async function openProfile(applicationId: string) {
    setBusy(true);
    setError("");
    try {
      const profile = await request<Profile>(token, `/api/v1/employer/applications/${applicationId}`);
      setSelectedProfile(profile);
      setNoteText(profile.employer_note.note);
      setTagsText(profile.employer_note.tags.join(", "));
    } catch (profileError) {
      setError(profileError instanceof Error ? profileError.message : "Could not open applicant profile.");
    } finally {
      setBusy(false);
    }
  }

  async function updateStatus(applicant: Applicant, status: "shortlisted" | "interview" | "offer" | "rejected") {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request(token, `/api/v1/employer/applications/${applicant.application_id}/status`, {
        method: "POST",
        body: JSON.stringify({
          status,
          ...(status === "rejected" ? { rejection_reason: rejectionReason } : {}),
        }),
      });
      await load(token);
      if (selectedProfile?.application_id === applicant.application_id) {
        setSelectedProfile(null);
      }
      setNotice(`${applicant.candidate_code} moved to ${label(status)}.`);
    } catch (statusError) {
      setError(statusError instanceof Error ? statusError.message : "Could not update applicant status.");
    } finally {
      setBusy(false);
    }
  }

  async function saveNote() {
    if (!selectedProfile) return;
    setBusy(true);
    setError("");
    try {
      await request(token, `/api/v1/employer/applications/${selectedProfile.application_id}/note`, {
        method: "PUT",
        body: JSON.stringify({
          note: noteText,
          tags: tagsText.split(",").map((tag) => tag.trim()).filter(Boolean),
        }),
      });
      setNotice("Private employer note saved.");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save note.");
    } finally {
      setBusy(false);
    }
  }

  async function compareSelected() {
    if (selectedIds.length < 2 || selectedIds.length > 3) {
      setError("Select two or three applicants to compare.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await request<{ applicants: Applicant[] }>(
        token,
        `/api/v1/employer/jobs/${jobId}/compare`,
        {
          method: "POST",
          body: JSON.stringify({ application_ids: selectedIds }),
        },
      );
      setComparison(result.applicants);
    } catch (compareError) {
      setError(compareError instanceof Error ? compareError.message : "Could not compare applicants.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <section className="mx-auto max-w-6xl">
        <nav className="flex flex-wrap gap-4 text-sm font-semibold">
          <Link className="text-blue-700 underline" href="/employer">Employer workspace</Link>
          <Link className="text-blue-700 underline" href="/">Capacity Connect</Link>
        </nav>
        <header className="mt-7 rounded-3xl bg-slate-950 p-7 text-white">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-300">Stage 13 · Blind applicant review</p>
          <h1 className="mt-2 text-3xl font-bold">{job?.title ?? "Job applicants"}</h1>
          <p className="mt-2 text-slate-300">Candidates are shown without name, email, institution, photo, or free-text application content.</p>
        </header>
        {error && <p className="mt-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-800" role="alert">{error}</p>}
        {notice && <p className="mt-5 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800" role="status">{notice}</p>}
        {loading && <p className="mt-6 text-slate-600">Loading consented applicants…</p>}
        {!loading && (
          <>
            <section className="mt-6 flex flex-wrap items-end justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-4">
              <label className="text-sm font-semibold">Filter by pipeline status
                <select className="ml-3 rounded-lg border border-slate-300 px-3 py-2 font-normal" onChange={(event) => {
                  const nextFilter = event.target.value;
                  setFilter(nextFilter);
                  void load(token, nextFilter);
                }} value={filter}>
                  <option value="">All statuses</option>
                  {["applied", "shortlisted", "interview", "offer", "rejected"].map((status) => (
                    <option key={status} value={status}>{label(status)}</option>
                  ))}
                </select>
              </label>
              <button className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white disabled:opacity-50" disabled={busy || selectedIds.length < 2 || selectedIds.length > 3} onClick={() => void compareSelected()} type="button">
                Compare selected ({selectedIds.length}/3)
              </button>
            </section>
            {comparison.length > 0 && (
              <section className="mt-5 rounded-2xl border border-blue-200 bg-blue-50 p-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-bold">Side-by-side comparison</h2>
                  <button className="text-sm font-semibold underline" onClick={() => setComparison([])} type="button">Close</button>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  {comparison.map((candidate) => (
                    <article className="rounded-xl bg-white p-4" key={candidate.application_id}>
                      <h3 className="font-bold">{candidate.candidate_code}</h3>
                      <p className="text-2xl font-bold text-blue-800">{candidate.fit.match_percentage}% fit</p>
                      <p className="mt-2 text-sm text-slate-600">{candidate.skills.verified.map((skill) => skill.skill_name).join(", ") || "No verified skills"}</p>
                    </article>
                  ))}
                </div>
              </section>
            )}
            <div className="mt-5 grid gap-5 lg:grid-cols-[1.1fr_.9fr]">
              <section className="space-y-3">
                {applicants.length === 0 && <p className="rounded-2xl border border-slate-200 bg-white p-6 text-slate-600">No consented applicants match this filter.</p>}
                {applicants.map((applicant) => (
                  <article className="rounded-2xl border border-slate-200 bg-white p-5" key={applicant.application_id}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex items-start gap-3">
                        <input aria-label={`Select ${applicant.candidate_code} for comparison`} checked={selectedIds.includes(applicant.application_id)} disabled={!selectedIds.includes(applicant.application_id) && selectedIds.length >= 3} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...current, applicant.application_id] : current.filter((id) => id !== applicant.application_id))} type="checkbox" />
                        <div>
                          <h2 className="font-bold">{applicant.candidate_code}</h2>
                          <p className="mt-1 text-sm text-slate-600">Applied {new Date(applicant.applied_at).toLocaleDateString()} · {label(applicant.status)}</p>
                        </div>
                      </div>
                      <p className="rounded-full bg-blue-50 px-3 py-1 text-lg font-bold text-blue-900">{applicant.fit.match_percentage}% fit</p>
                    </div>
                    <p className="mt-3 text-sm text-slate-600">{applicant.fit.explanation}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {applicant.fit.skills.map((skill) => (
                        <span className={`rounded-full px-3 py-1 text-xs ${skill.evidence_status === "verified" ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-900"}`} key={skill.competency_id}>
                          {skill.skill_name}: {skill.current_level}/{skill.required_level} · {label(skill.evidence_status)}
                        </span>
                      ))}
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold" disabled={busy} onClick={() => void openProfile(applicant.application_id)} type="button">Open blind profile</button>
                      {applicant.status === "applied" && <button className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void updateStatus(applicant, "shortlisted")} type="button">Shortlist</button>}
                      {["applied", "shortlisted", "heard_back"].includes(applicant.status) && <button className="rounded-lg bg-indigo-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void updateStatus(applicant, "interview")} type="button">Move to interview</button>}
                      {applicant.status === "interview" && <button className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void updateStatus(applicant, "offer")} type="button">Record offer</button>}
                      {!["offer", "rejected", "placed"].includes(applicant.status) && (
                        <>
                          <select aria-label="Neutral rejection reason" className="rounded-lg border border-slate-300 px-2 text-sm" onChange={(event) => setRejectionReason(event.target.value as RejectionReason)} value={rejectionReason}>
                            <option value="position_filled">Position filled</option>
                            <option value="role_changed">Role changed</option>
                            <option value="candidate_withdrew">Candidate withdrew</option>
                          </select>
                          <button className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800 disabled:opacity-50" disabled={busy} onClick={() => void updateStatus(applicant, "rejected")} type="button">Reject with reason</button>
                        </>
                      )}
                    </div>
                  </article>
                ))}
              </section>
              <aside className="self-start rounded-2xl border border-slate-200 bg-white p-5">
                {!selectedProfile && <p className="text-sm text-slate-600">Open a blind profile to review consented skills and credentials. Access is logged and limited to 50 profile views per employer in 24 hours.</p>}
                {selectedProfile && (
                  <>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-bold uppercase tracking-wider text-blue-700">{selectedProfile.candidate_code}</p>
                        <h2 className="mt-1 text-xl font-bold">Blind profile</h2>
                      </div>
                      <button className="text-sm underline" onClick={() => setSelectedProfile(null)} type="button">Close</button>
                    </div>
                    <p className="mt-2 text-sm text-slate-600">{selectedProfile.remaining_profile_views_today} profile views remain today for this employer.</p>
                    <div className="mt-4 space-y-4">
                      <div>
                        <h3 className="font-bold">Verified skills</h3>
                        <p className="mt-1 text-sm text-slate-700">{selectedProfile.skills.verified.map((skill) => `${skill.skill_name} (level ${skill.level ?? "—"})`).join(", ") || "None listed"}</p>
                      </div>
                      <div>
                        <h3 className="font-bold">Claimed skills</h3>
                        <p className="mt-1 text-sm text-slate-700">{selectedProfile.skills.claimed.map((skill) => `${skill.skill_name} (level ${skill.level ?? "—"})`).join(", ") || "None listed"}</p>
                      </div>
                      <div>
                        <h3 className="font-bold">Verified credentials</h3>
                        <p className="mt-1 text-sm text-slate-700">{selectedProfile.verified_credentials.map((credential) => `${credential.skill_name} (level ${credential.level})`).join(", ") || "None selected"}</p>
                      </div>
                      <div>
                        <h3 className="font-bold">Match explanation</h3>
                        <ul className="mt-2 space-y-2 text-sm">
                          {selectedProfile.fit.skills.map((skill) => <li key={skill.competency_id}>{skill.skill_name}: {skill.current_level} of {skill.required_level} levels ({label(skill.evidence_status)})</li>)}
                        </ul>
                      </div>
                    </div>
                    <div className="mt-5 border-t border-slate-200 pt-4">
                      <h3 className="font-bold">Private employer notes</h3>
                      <textarea className="mt-2 w-full rounded-lg border border-slate-300 p-3 text-sm" maxLength={4000} onChange={(event) => setNoteText(event.target.value)} placeholder="Private notes for your hiring team" rows={4} value={noteText} />
                      <label className="mt-2 block text-sm font-semibold">Tags
                        <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" onChange={(event) => setTagsText(event.target.value)} placeholder="e.g. strong SQL, follow-up" value={tagsText} />
                      </label>
                      <button className="mt-3 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void saveNote()} type="button">Save private note</button>
                    </div>
                  </>
                )}
              </aside>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
