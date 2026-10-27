"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Credential = {
  credential_id: string;
  skill: string;
  course: string | null;
  level: number;
  evidence_tier: string;
  issued_at: string;
  expires_at: string | null;
  status: "valid" | "expired" | "revoked";
  verification_url: string;
};

async function loadCredentials(token: string): Promise<Credential[]> {
  const response = await fetch(`${API_URL}/api/v1/credentials`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Could not load credentials (${response.status})`);
  }
  return (await response.json()) as Credential[];
}

export default function CredentialsPage() {
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = window.sessionStorage.getItem("capacity-connect-token");
    if (!token) {
      setError("Sign in to view your credentials.");
      setLoading(false);
      return;
    }
    void loadCredentials(token)
      .then(setCredentials)
      .catch((loadError: unknown) => {
        setError(loadError instanceof Error ? loadError.message : "Could not load credentials.");
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 sm:px-6">
      <section className="mx-auto max-w-4xl">
        <nav className="flex gap-4 text-sm font-semibold">
          <Link className="text-blue-700 hover:underline" href="/">← Skill passport</Link>
          <Link className="text-blue-700 hover:underline" href="/profile">Progress & gaps</Link>
        </nav>
        <p className="mt-8 text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Stage 6</p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">My credentials</h1>
        <p className="mt-2 text-slate-600">Credentials show their evidence tier and can be checked without signing in.</p>

        {loading && <p className="mt-8 text-slate-600">Loading credentials…</p>}
        {error && <p className="mt-8 rounded-xl bg-rose-50 p-4 text-rose-800">{error}</p>}
        {!loading && !error && credentials.length === 0 && (
          <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="font-semibold">No credentials yet</h2>
            <p className="mt-2 text-sm text-slate-600">
              Self-check assessments do not issue credentials. A qualifying verified assessment can issue one after it is submitted.
            </p>
            <Link className="mt-4 inline-flex rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white" href="/my-learning">
              Continue learning
            </Link>
          </div>
        )}
        <ul className="mt-6 space-y-4">
          {credentials.map((credential) => (
            <li className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" key={credential.credential_id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-bold text-slate-950">{credential.skill} · Level {credential.level}</h2>
                  <p className="mt-1 text-sm text-slate-600">{credential.course ?? "Assessment"} · {credential.evidence_tier.replace("_", " ")}</p>
                  <p className="mt-1 text-sm text-slate-600">Issued {new Date(credential.issued_at).toLocaleDateString()}</p>
                  {credential.expires_at && <p className="mt-1 text-sm text-slate-600">Expires {new Date(credential.expires_at).toLocaleDateString()}</p>}
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-bold uppercase ${
                  credential.status === "valid" ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"
                }`}>{credential.status}</span>
              </div>
              <div className="mt-4 flex flex-wrap gap-3 text-sm font-semibold">
                <Link className="rounded-lg bg-blue-700 px-3 py-2 text-white" href={`/credentials/issued/${credential.credential_id}`}>View credential</Link>
                <a className="rounded-lg border border-slate-300 px-3 py-2" href={`${API_URL}/api/v1/credentials/${credential.credential_id}/download`}>Download PDF</a>
                <a className="rounded-lg border border-slate-300 px-3 py-2" href={`https://www.linkedin.com/profile/add?startTask=CERTIFICATION_NAME&name=${encodeURIComponent(credential.skill)}&certUrl=${encodeURIComponent(credential.verification_url)}`} rel="noreferrer" target="_blank">Add to LinkedIn</a>
                <a className="rounded-lg border border-slate-300 px-3 py-2" href={`mailto:?subject=${encodeURIComponent(`My ${credential.skill} credential`)}&body=${encodeURIComponent(credential.verification_url)}`}>Share by email</a>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
