"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Credential = {
  credential_id: string;
  holder: string;
  course: string | null;
  skill: string;
  level: number;
  evidence_tier: string;
  issued_at: string;
  expires_at: string | null;
  status: "valid" | "expired" | "revoked";
  verification_url: string;
};

export default function IssuedCredentialPage() {
  const params = useParams<{ credentialId: string }>();
  const [credential, setCredential] = useState<Credential | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!params.credentialId) return;
    void fetch(`${API_URL}/api/v1/credentials/${params.credentialId}/verify`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Credential lookup failed (${response.status})`);
        setCredential((await response.json()) as Credential);
      })
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not load credential."));
  }, [params.credentialId]);

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 sm:px-6">
      <section className="mx-auto max-w-2xl rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-9">
        <Link className="text-sm font-semibold text-blue-700 hover:underline" href="/credentials">← My credentials</Link>
        <p className="mt-8 text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Credential issued</p>
        {error && <p className="mt-4 rounded-xl bg-rose-50 p-4 text-rose-800">{error}</p>}
        {!credential && !error && <p className="mt-5 text-slate-600">Loading credential…</p>}
        {credential && (
          <>
            <h1 className="mt-2 text-3xl font-bold text-slate-950">Congratulations</h1>
            <p className="mt-2 text-slate-600">Your verified skill credential is ready to share.</p>
            <dl className="mt-7 grid gap-4 rounded-2xl bg-slate-50 p-5 sm:grid-cols-2">
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Skill</dt><dd className="mt-1 font-bold">{credential.skill} · Level {credential.level}</dd></div>
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Evidence tier</dt><dd className="mt-1 font-bold">{credential.evidence_tier.replace("_", " ")}</dd></div>
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Issued</dt><dd className="mt-1 font-semibold">{new Date(credential.issued_at).toLocaleDateString()}</dd></div>
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Status</dt><dd className="mt-1 font-bold">{credential.status}</dd></div>
            </dl>
            <img alt="QR code for public credential verification" className="mt-6 h-40 w-40 rounded-lg border border-slate-200 p-2" src={`${API_URL}/api/v1/credentials/${credential.credential_id}/qr.svg`} />
            <div className="mt-5 flex flex-wrap gap-3">
              <a className="rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white" href={`${API_URL}/api/v1/credentials/${credential.credential_id}/download`}>Download credential PDF</a>
              <Link className="rounded-xl border border-slate-300 px-4 py-2.5 font-semibold" href={`/verify/${credential.credential_id}`}>Open public verification</Link>
              <Link className="rounded-xl border border-slate-300 px-4 py-2.5 font-semibold" href="/">View updated passport</Link>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
