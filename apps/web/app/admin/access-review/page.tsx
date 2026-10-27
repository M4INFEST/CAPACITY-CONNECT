"use client";

import { FormEvent, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type TrainerApplication = {
  id: string;
  user_id: string;
  email: string;
  expertise: string[];
  status: string;
  submitted_at: string;
};
type EmployerReview = {
  user_id: string;
  email: string;
  company_name: string;
  website: string | null;
  industry: string | null;
  verification_level: number;
};

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
      cache: "no-store",
    });
  } catch {
    throw new Error(`Could not reach the API at ${API_URL}.`);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function AccessReviewPage() {
  const [token, setToken] = useState("");
  const [trainers, setTrainers] = useState<TrainerApplication[]>([]);
  const [employers, setEmployers] = useState<EmployerReview[]>([]);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load(accessToken: string) {
    const account = await request<{ roles: string[] }>(accessToken, "/api/v1/auth/me");
    if (!account.roles.includes("admin")) {
      throw new Error("Administrator access is required to review identity applications.");
    }
    const [trainerRows, employerRows] = await Promise.all([
      request<TrainerApplication[]>(accessToken, "/api/v1/admin/trainer-applications"),
      request<EmployerReview[]>(accessToken, "/api/v1/admin/employers/pending"),
    ]);
    setTrainers(trainerRows);
    setEmployers(employerRows);
  }

  useEffect(() => {
    let active = true;
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with an administrator account to review identity applications.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void load(accessToken)
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load review queues.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function decideTrainer(
    applicationId: string,
    decision: "approved" | "rejected" | "needs_info",
  ) {
    setError("");
    setNotice("");
    setBusyId(applicationId);
    try {
      await request(token, `/api/v1/admin/trainer-applications/${applicationId}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, review_reason: reasons[applicationId] ?? "" }),
      });
      setNotice(`Trainer application ${decision.replace("_", " ")}.`);
      await load(token);
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : "Could not review trainer application.");
    } finally {
      setBusyId("");
    }
  }

  async function advanceEmployer(
    event: FormEvent<HTMLFormElement>,
    employer: EmployerReview,
  ) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusyId(employer.user_id);
    try {
      await request(token, `/api/v1/admin/employers/${employer.user_id}/verification`, {
        method: "POST",
        body: JSON.stringify({
          level: employer.verification_level + 1,
          review_reason: reasons[employer.user_id] ?? "",
        }),
      });
      setNotice(`${employer.company_name} advanced to verification level ${employer.verification_level + 1}.`);
      await load(token);
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : "Could not update employer verification.");
    } finally {
      setBusyId("");
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-10">
      <div className="mx-auto max-w-6xl">
        <header>
          <p className="text-sm font-bold uppercase tracking-wider text-blue-700">Administration · Stage 1</p>
          <h1 className="mt-2 text-3xl font-bold">Identity reviews</h1>
          <p className="mt-2 text-slate-600">Review trainer applications and advance employer verification one level at a time. Every decision requires a recorded reason.</p>
        </header>
        {(error || notice) && (
          <div className={`mt-5 rounded-xl p-4 text-sm ${error ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-900"}`} role={error ? "alert" : "status"}>
            {error || notice}
          </div>
        )}
        {loading ? (
          <p className="mt-8 text-sm text-slate-600" role="status">Loading identity queues…</p>
        ) : !error || trainers.length > 0 || employers.length > 0 ? (
          <div className="mt-8 grid gap-8 xl:grid-cols-2">
            <section aria-labelledby="trainer-queue">
              <div className="flex items-center justify-between">
                <h2 id="trainer-queue" className="text-xl font-bold">Trainer applications</h2>
                <span className="rounded-full bg-slate-200 px-3 py-1 text-sm font-semibold">{trainers.length} pending</span>
              </div>
              {trainers.length === 0 ? (
                <p className="mt-4 rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">No trainer applications are waiting for review.</p>
              ) : (
                <div className="mt-4 space-y-4">
                  {trainers.map((application) => (
                    <form
                      className="rounded-2xl border border-slate-200 bg-white p-5"
                      key={application.id}
                      onSubmit={(event) => {
                        event.preventDefault();
                        void decideTrainer(application.id, "approved");
                      }}
                    >
                      <h3 className="font-bold">{application.email}</h3>
                      <p className="mt-1 text-xs text-slate-500">Submitted {new Date(application.submitted_at).toLocaleString()}</p>
                      <p className="mt-3 text-sm"><span className="font-semibold">Expertise:</span> {application.expertise.join(", ")}</p>
                      <label className="mt-4 block text-sm font-medium">
                        Review reason
                        <textarea
                          className="mt-1 min-h-20 w-full rounded-xl border border-slate-300 p-3"
                          minLength={3}
                          onChange={(event) => setReasons((current) => ({ ...current, [application.id]: event.target.value }))}
                          required
                          value={reasons[application.id] ?? ""}
                        />
                      </label>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busyId === application.id} type="submit">Approve</button>
                        <button className="rounded-lg border border-amber-500 px-3 py-2 text-sm font-semibold text-amber-900 disabled:opacity-50" disabled={busyId === application.id || (reasons[application.id] ?? "").trim().length < 3} onClick={() => void decideTrainer(application.id, "needs_info")} type="button">Request information</button>
                        <button className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800 disabled:opacity-50" disabled={busyId === application.id || (reasons[application.id] ?? "").trim().length < 3} onClick={() => void decideTrainer(application.id, "rejected")} type="button">Reject</button>
                      </div>
                    </form>
                  ))}
                </div>
              )}
            </section>
            <section aria-labelledby="employer-queue">
              <div className="flex items-center justify-between">
                <h2 id="employer-queue" className="text-xl font-bold">Employer verification</h2>
                <span className="rounded-full bg-slate-200 px-3 py-1 text-sm font-semibold">{employers.length} below level 2</span>
              </div>
              {employers.length === 0 ? (
                <p className="mt-4 rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">No employers are waiting for verification.</p>
              ) : (
                <div className="mt-4 space-y-4">
                  {employers.map((employer) => (
                    <form className="rounded-2xl border border-slate-200 bg-white p-5" key={employer.user_id} onSubmit={(event) => advanceEmployer(event, employer)}>
                      <h3 className="font-bold">{employer.company_name}</h3>
                      <p className="mt-1 text-sm text-slate-600">{employer.email}</p>
                      {employer.website && <p className="mt-1 break-all text-sm text-slate-600">{employer.website}</p>}
                      {employer.industry && <p className="mt-1 text-sm text-slate-600">{employer.industry}</p>}
                      <p className="mt-3 rounded-lg bg-blue-50 p-3 text-sm text-blue-900">Current level {employer.verification_level}. Next review advances only to level {employer.verification_level + 1}.</p>
                      <label className="mt-4 block text-sm font-medium">
                        Review reason
                        <textarea
                          className="mt-1 min-h-20 w-full rounded-xl border border-slate-300 p-3"
                          minLength={3}
                          onChange={(event) => setReasons((current) => ({ ...current, [employer.user_id]: event.target.value }))}
                          required
                          value={reasons[employer.user_id] ?? ""}
                        />
                      </label>
                      {employer.verification_level === 0 && <p className="mt-2 text-xs text-slate-500">Level 1 also requires an already verified non-free email matching this company’s website domain.</p>}
                      <button className="mt-4 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busyId === employer.user_id} type="submit">
                        Advance to level {employer.verification_level + 1}
                      </button>
                    </form>
                  ))}
                </div>
              )}
            </section>
          </div>
        ) : null}
      </div>
    </main>
  );
}
