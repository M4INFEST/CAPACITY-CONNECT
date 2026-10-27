"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Application = {
  application_id: string;
  expertise: string[];
  status: "pending" | "approved" | "needs_info" | "rejected" | "withdrawn";
  submitted_at: string;
  reviewed_at: string | null;
  review_reason: string | null;
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

export default function TrainerApplicationPage() {
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [application, setApplication] = useState<Application | null>(null);
  const [expertise, setExpertise] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadApplication = useCallback(async (accessToken: string) => {
    const [account, latest] = await Promise.all([
      request<{ email: string; roles: string[] }>(accessToken, "/api/v1/auth/me"),
      request<Application | null>(accessToken, "/api/v1/roles/trainer/applications/me"),
    ]);
    if (account.roles.includes("trainer")) {
      throw new Error("This account already has approved trainer access.");
    }
    setEmail(account.email);
    setApplication(latest);
  }, []);

  useEffect(() => {
    let active = true;
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with a verified account before applying to become a trainer.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void loadApplication(accessToken)
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load your application.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [loadApplication]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const areas = expertise.split(/[\n,]/).map((area) => area.trim()).filter(Boolean);
      if (areas.length === 0) throw new Error("Enter at least one area of expertise.");
      if (areas.length > 30) throw new Error("Enter no more than 30 areas of expertise.");
      await request(token, "/api/v1/roles/trainer/apply", {
        method: "POST",
        body: JSON.stringify({ expertise: areas }),
      });
      await loadApplication(token);
      setNotice("Your trainer application was submitted for administrator review.");
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not submit your application.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-10">
      <section className="mx-auto max-w-3xl rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <p className="text-sm font-bold uppercase tracking-wider text-blue-700">Trainer access</p>
        <h1 className="mt-3 text-3xl font-bold">Apply to teach</h1>
        <p className="mt-3 text-slate-600">
          Trainer access is granted only after an administrator reviews your expertise. Application submission never grants trainer permissions.
        </p>
        {loading ? (
          <p className="mt-6 text-sm text-slate-600" role="status">Loading your application…</p>
        ) : (
          <>
            {email && <p className="mt-4 text-sm text-slate-500">Signed in as {email}</p>}
            {error && <p className="mt-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-800" role="alert">{error}</p>}
            {notice && <p className="mt-5 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900" role="status">{notice}</p>}
            {application?.status === "pending" ? (
              <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-5">
                <h2 className="font-bold text-amber-950">Application pending</h2>
                <p className="mt-2 text-sm text-amber-900">Submitted {new Date(application.submitted_at).toLocaleString()}.</p>
                <p className="mt-2 text-sm text-amber-900">Expertise: {application.expertise.join(", ")}</p>
              </div>
            ) : application && (
              <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50 p-5">
                <h2 className="font-bold capitalize">{application.status.replace("_", " ")}</h2>
                {application.review_reason && <p className="mt-2 text-sm text-slate-700">Review note: {application.review_reason}</p>}
                {application.reviewed_at && <p className="mt-2 text-xs text-slate-500">Reviewed {new Date(application.reviewed_at).toLocaleString()}.</p>}
              </div>
            )}
            {application?.status !== "pending" && !error && (
              <form className="mt-6 space-y-4" onSubmit={submit}>
                <label className="block text-sm font-semibold">
                  Expertise areas
                  <textarea
                    className="mt-2 min-h-32 w-full rounded-xl border border-slate-300 p-3"
                    onChange={(event) => setExpertise(event.target.value)}
                    placeholder={"Python\nData engineering\nCloud platforms"}
                    required
                    value={expertise}
                  />
                </label>
                <p className="text-xs text-slate-500">Enter up to 30 areas, separated by commas or new lines. An administrator must approve the application before trainer permissions are granted.</p>
                <button className="rounded-xl bg-blue-700 px-5 py-3 font-semibold text-white disabled:opacity-50" disabled={busy} type="submit">
                  {busy ? "Submitting…" : "Submit trainer application"}
                </button>
              </form>
            )}
          </>
        )}
        <Link className="mt-7 inline-block text-sm font-semibold text-blue-700 hover:underline" href="/">
          Return to your workspace
        </Link>
      </section>
    </main>
  );
}
