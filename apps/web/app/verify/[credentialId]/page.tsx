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
};

export default function VerifyCredentialPage() {
  const params = useParams<{ credentialId: string }>();
  const [credential, setCredential] = useState<Credential | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!params.credentialId) return;
    void fetch(`${API_URL}/api/v1/credentials/${params.credentialId}/verify`)
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 404 ? "Credential not found." : `Verification failed (${response.status})`);
        setCredential((await response.json()) as Credential);
      })
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not verify this credential."));
  }, [params.credentialId]);

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 sm:px-6">
      <section className="mx-auto max-w-2xl rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-9">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Public verification</p>
        {error && <p className="mt-6 rounded-xl bg-rose-50 p-4 text-rose-800">{error}</p>}
        {!credential && !error && <p className="mt-6 text-slate-600">Checking credential…</p>}
        {credential && (
          <>
            <div className={`mt-6 inline-flex rounded-full px-3 py-1 text-sm font-bold uppercase ${
              credential.status === "valid" ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"
            }`}>{credential.status}</div>
            <h1 className="mt-4 text-3xl font-bold text-slate-950">{credential.skill} · Level {credential.level}</h1>
            <dl className="mt-6 space-y-4 rounded-2xl bg-slate-50 p-5">
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Holder</dt><dd className="mt-1 font-semibold">{credential.holder}</dd></div>
              {credential.course && <div><dt className="text-xs font-semibold uppercase text-slate-500">Course</dt><dd className="mt-1 font-semibold">{credential.course}</dd></div>}
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Evidence tier</dt><dd className="mt-1 font-semibold">{credential.evidence_tier.replace("_", " ")}</dd></div>
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Issued</dt><dd className="mt-1 font-semibold">{new Date(credential.issued_at).toLocaleDateString()}</dd></div>
              {credential.expires_at && <div><dt className="text-xs font-semibold uppercase text-slate-500">Expires</dt><dd className="mt-1 font-semibold">{new Date(credential.expires_at).toLocaleDateString()}</dd></div>}
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Credential ID</dt><dd className="mt-1 break-all font-mono text-sm">{credential.credential_id}</dd></div>
            </dl>
          </>
        )}
        <Link className="mt-6 inline-flex text-sm font-semibold text-blue-700 hover:underline" href="/">Capacity Connect</Link>
      </section>
    </main>
  );
}
