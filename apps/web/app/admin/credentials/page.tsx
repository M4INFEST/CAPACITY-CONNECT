"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Credential = {
  credential_id: string;
  learner_id: string;
  skill: string;
  level: number;
  evidence_tier: string;
  issued_at: string;
  expires_at: string | null;
  status: "valid" | "expired" | "revoked";
  revocation_reason: string | null;
};

async function adminRequest<T>(token: string, path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...options.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function AdminCredentialsPage() {
  const [token, setToken] = useState("");
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [reason, setReason] = useState<Record<string, string>>({});
  const [expiry, setExpiry] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const reload = useCallback(async (accessToken: string) => {
    setCredentials(await adminRequest<Credential[]>(accessToken, "/api/v1/admin/credentials"));
  }, []);

  useEffect(() => {
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with an admin account.");
      return;
    }
    setToken(accessToken);
    void reload(accessToken).catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not load credentials."));
  }, [reload]);

  async function revoke(credentialId: string) {
    setError("");
    setMessage("");
    try {
      await adminRequest(token, `/api/v1/admin/credentials/${credentialId}/revoke`, {
        method: "POST",
        body: JSON.stringify({ reason: reason[credentialId] ?? "" }),
      });
      await reload(token);
      setMessage("Credential revoked and the audit record saved.");
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not revoke credential.");
    }
  }

  async function saveExpiry(credentialId: string) {
    setError("");
    setMessage("");
    try {
      const value = expiry[credentialId];
      await adminRequest(token, `/api/v1/admin/credentials/${credentialId}/expiry`, {
        method: "PATCH",
        body: JSON.stringify({
          expires_at: value ? new Date(`${value}T23:59:59`).toISOString() : null,
          reason: reason[credentialId] ?? "",
        }),
      });
      await reload(token);
      setMessage("Credential expiry updated and the audit record saved.");
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not update expiry.");
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10 sm:px-6">
      <section className="mx-auto max-w-5xl">
        <Link className="text-sm font-semibold text-blue-700 hover:underline" href="/">← Skill passport</Link>
        <p className="mt-8 text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Admin · Stage 6</p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">Credential review</h1>
        <p className="mt-2 text-slate-600">Set optional expiry dates or revoke credentials with a recorded reason.</p>
        {message && <p className="mt-5 rounded-xl bg-emerald-50 p-4 text-emerald-800">{message}</p>}
        {error && <p className="mt-5 rounded-xl bg-rose-50 p-4 text-rose-800">{error}</p>}
        <ul className="mt-6 space-y-4">
          {credentials.map((item) => (
            <li className="rounded-2xl border border-slate-200 bg-white p-5" key={item.credential_id}>
              <div className="flex flex-wrap justify-between gap-2">
                <div><h2 className="font-bold">{item.skill} · Level {item.level}</h2><p className="mt-1 text-sm text-slate-600">Learner {item.learner_id} · {item.evidence_tier} · {item.status}</p></div>
                <Link className="text-sm font-semibold text-blue-700 underline" href={`/verify/${item.credential_id}`}>Public verification</Link>
              </div>
              <label className="mt-4 block text-sm font-semibold">
                Review reason (required)
                <textarea className="mt-1 w-full rounded-lg border border-slate-300 p-2" value={reason[item.credential_id] ?? ""} onChange={(event) => setReason((current) => ({ ...current, [item.credential_id]: event.target.value }))} />
              </label>
              <div className="mt-3 flex flex-wrap items-end gap-3">
                <label className="text-sm font-semibold">
                  Optional expiry
                  <input className="mt-1 block rounded-lg border border-slate-300 p-2" type="date" value={expiry[item.credential_id] ?? (item.expires_at ? item.expires_at.slice(0, 10) : "")} onChange={(event) => setExpiry((current) => ({ ...current, [item.credential_id]: event.target.value }))} />
                </label>
                <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={!reason[item.credential_id]?.trim()} onClick={() => void saveExpiry(item.credential_id)} type="button">Save expiry</button>
                <button className="rounded-lg bg-rose-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={item.status === "revoked" || !reason[item.credential_id]?.trim()} onClick={() => void revoke(item.credential_id)} type="button">Revoke</button>
              </div>
              {item.revocation_reason && <p className="mt-3 text-sm text-rose-800">Revocation reason: {item.revocation_reason}</p>}
            </li>
          ))}
        </ul>
        {credentials.length === 0 && !error && <p className="mt-6 text-slate-600">No issued credentials to review.</p>}
      </section>
    </main>
  );
}
