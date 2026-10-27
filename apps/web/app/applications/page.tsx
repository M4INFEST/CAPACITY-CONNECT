"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type StatusEvent = {
  status: string;
  actor_role: string;
  note: string | null;
  created_at: string;
};
type Application = {
  application_id: string;
  job_id: string;
  status: "applied" | "heard_back" | "interview" | "offer" | "no_reply" | "likely_closed" | "rejected" | "withdrawn";
  applied_at: string;
  last_employer_activity_at: string | null;
  likely_closed_at: string | null;
  withdrawn_at: string | null;
  job_title: string;
  company_name: string | null;
  location: string | null;
  job_type: string | null;
  status_history: StatusEvent[];
};

async function request<T>(token: string, path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        Authorization: `******`,
        ...(options?.body ? { "Content-Type": "application/json" } : {}),
        ...options?.headers,
      },
    });
  } catch {
    throw new Error(`Could not reach the API at ${API_URL}. Start the stack with docker compose up --build.`);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

function label(status: string) {
  return status.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function MyApplicationsPage() {
  const [token, setToken] = useState("");
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load(accessToken: string) {
    const result = await request<{ applications: Application[] }>(accessToken, "/api/v1/applications");
    setApplications(result.applications);
  }

  useEffect(() => {
    let active = true;
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with your trainee account to track applications.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void load(accessToken)
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load applications.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function updateStatus(application: Application, status: "heard_back" | "interview" | "offer" | "no_reply") {
    setBusyId(application.application_id);
    setError("");
    setNotice("");
    try {
      await request(token, `/api/v1/applications/${application.application_id}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      await load(token);
      setNotice(`Your update for ${application.job_title} was recorded. This is learner-reported status, not employer verification.`);
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : "Could not update the status.");
    } finally {
      setBusyId("");
    }
  }

  async function withdraw(application: Application) {
    if (!window.confirm(`Withdraw your application for ${application.job_title}?`)) return;
    setBusyId(application.application_id);
    setError("");
    try {
      await request(token, `/api/v1/applications/${application.application_id}/withdraw`, { method: "POST" });
      await load(token);
      setNotice("Application withdrawn.");
    } catch (withdrawError) {
      setError(withdrawError instanceof Error ? withdrawError.message : "Could not withdraw the application.");
    } finally {
      setBusyId("");
    }
  }

  async function downloadResume(application: Application) {
    setBusyId(application.application_id);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/applications/${application.application_id}/resume.txt`, {
        headers: { Authorization: `******` },
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
        throw new Error(typeof body.detail === "string" ? body.detail : `Resume download failed (${response.status})`);
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "application-resume.txt";
      link.click();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : "Could not download resume.");
    } finally {
      setBusyId("");
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <section className="mx-auto max-w-5xl">
        <nav className="flex flex-wrap gap-4 text-sm font-semibold">
          <Link className="text-blue-700 underline" href="/jobs">Job explorer</Link>
          <Link className="text-blue-700 underline" href="/learning">Course picks</Link>
          <Link className="text-blue-700 underline" href="/profile">Progress & gaps</Link>
        </nav>
        <header className="mt-7">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Stage 12</p>
          <h1 className="mt-2 text-3xl font-bold text-slate-950">My applications</h1>
          <p className="mt-2 text-slate-600">Track applications and report status updates. Learner-reported updates are labeled separately from employer activity.</p>
        </header>
        {error && <p className="mt-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-800" role="alert">{error}</p>}
        {notice && <p className="mt-5 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800" role="status">{notice}</p>}
        {loading && <p className="mt-6 text-slate-600">Loading applications…</p>}
        {!loading && applications.length === 0 && (
          <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="font-bold">No applications yet</h2>
            <p className="mt-2 text-sm text-slate-600">Choose an active role in the job explorer and review an application before submitting.</p>
            <Link className="mt-3 inline-block font-semibold text-blue-700 underline" href="/jobs">Explore jobs</Link>
          </div>
        )}
        <div className="mt-6 space-y-4">
          {applications.map((application) => {
            const busy = busyId === application.application_id;
            const canUpdate = !["offer", "rejected", "withdrawn", "likely_closed"].includes(application.status);
            const canWithdraw = !["offer", "rejected", "withdrawn"].includes(application.status);
            return (
              <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" key={application.application_id}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-xl font-bold text-slate-950">{application.job_title}</h2>
                    <p className="mt-1 text-slate-700">{application.company_name ?? "Platform employer"}</p>
                    <p className="mt-1 text-sm text-slate-500">
                      {[application.location, application.job_type?.replaceAll("_", " ")].filter(Boolean).join(" · ") || "Job details not available"}
                    </p>
                  </div>
                  <span className="rounded-full bg-blue-50 px-3 py-1 text-sm font-bold text-blue-900">{label(application.status)}</span>
                </div>
                <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                  <div><dt className="text-slate-500">Applied</dt><dd>{new Date(application.applied_at).toLocaleString()}</dd></div>
                  <div><dt className="text-slate-500">Last employer activity</dt><dd>{application.last_employer_activity_at ? new Date(application.last_employer_activity_at).toLocaleString() : "No employer response recorded"}</dd></div>
                </dl>
                {application.status_history.length > 0 && (
                  <details className="mt-4">
                    <summary className="cursor-pointer text-sm font-semibold text-slate-700">Status history</summary>
                    <ol className="mt-2 space-y-2 border-l border-slate-200 pl-4 text-sm">
                      {application.status_history.map((event, index) => (
                        <li key={`${event.created_at}-${index}`}>
                          <span className="font-semibold">{label(event.status)}</span>
                          {" "}· {event.actor_role === "trainee" ? "Reported by you" : label(event.actor_role)}
                          {" "}· {new Date(event.created_at).toLocaleString()}
                          {event.note && <p className="text-slate-600">{event.note}</p>}
                        </li>
                      ))}
                    </ol>
                  </details>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={busy} onClick={() => void downloadResume(application)} type="button">Download resume</button>
                  {canUpdate && (
                    <>
                      <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={busy} onClick={() => void updateStatus(application, "heard_back")} type="button">Heard back</button>
                      <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={busy} onClick={() => void updateStatus(application, "interview")} type="button">Interview</button>
                      <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={busy} onClick={() => void updateStatus(application, "offer")} type="button">Offer</button>
                      <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={busy} onClick={() => void updateStatus(application, "no_reply")} type="button">No reply</button>
                    </>
                  )}
                  {canWithdraw && (
                    <button className="rounded-lg border border-rose-200 px-3 py-2 text-sm font-semibold text-rose-700 disabled:opacity-50" disabled={busy} onClick={() => void withdraw(application)} type="button">Withdraw</button>
                  )}
                </div>
                {application.status === "likely_closed" && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">No employer response was recorded for 14 days. Consider exploring other active jobs.</p>}
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}
