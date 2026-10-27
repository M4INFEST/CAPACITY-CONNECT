"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setError("");
    setBusy(true);
    try {
      const response = await fetch(`${API_URL}/api/v1/auth/password/forgot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const result = (await response.json()) as { message?: string; detail?: string };
      if (!response.ok) throw new Error(result.detail ?? `Request failed (${response.status})`);
      setMessage(result.message ?? "If the account is eligible, a reset link will be sent.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not request a reset link");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-12">
      <section className="mx-auto max-w-lg rounded-3xl border border-slate-200 bg-white p-7 shadow-sm">
        <p className="text-sm font-bold uppercase tracking-wider text-blue-700">Capacity Connect</p>
        <h1 className="mt-3 text-2xl font-bold">Reset your password</h1>
        <p className="mt-3 text-sm text-slate-600">If an eligible account matches the address, we’ll send a one-time reset link.</p>
        <form className="mt-5 space-y-4" onSubmit={submit}>
          <label className="block text-sm font-medium">
            Email
            <input
              autoComplete="email"
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <button className="w-full rounded-xl bg-blue-700 px-4 py-3 font-semibold text-white disabled:opacity-50" disabled={busy} type="submit">
            {busy ? "Please wait…" : "Send reset link"}
          </button>
        </form>
        {(error || message) && <p className={`mt-4 rounded-xl p-4 text-sm ${error ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-900"}`} role={error ? "alert" : "status"}>{error || message}</p>}
        <Link className="mt-6 inline-block text-sm font-semibold text-blue-700 hover:underline" href="/">Return to sign in</Link>
      </section>
    </main>
  );
}
