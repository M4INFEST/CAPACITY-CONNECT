"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function VerifyEmailPage() {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const emailToken = params.get("token");
    if (!emailToken) return;
    setToken(emailToken);
    window.history.replaceState(null, "", window.location.pathname);
    setBusy(true);
    fetch(`${API_URL}/api/v1/auth/email/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: emailToken }),
    })
      .then(async (response) => {
        const result = (await response.json()) as { message?: string; detail?: string };
        if (!response.ok) throw new Error(result.detail ?? `Verification failed (${response.status})`);
        setMessage(result.message ?? "Email verified. You can now sign in.");
      })
      .catch((requestError: unknown) => {
        setError(requestError instanceof Error ? requestError.message : "Could not verify email");
      })
      .finally(() => setBusy(false));
  }, []);

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setBusy(true);
    try {
      const response = await fetch(`${API_URL}/api/v1/auth/email/resend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const result = (await response.json()) as { message?: string; detail?: string };
      if (!response.ok) throw new Error(result.detail ?? `Request failed (${response.status})`);
      setMessage(result.message ?? "If the account needs verification, a link will be sent.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not request a link");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-12">
      <section className="mx-auto max-w-lg rounded-3xl border border-slate-200 bg-white p-7 shadow-sm">
        <p className="text-sm font-bold uppercase tracking-wider text-blue-700">Capacity Connect</p>
        <h1 className="mt-3 text-2xl font-bold">Email verification</h1>
        {busy && <p className="mt-4 text-sm text-slate-600" role="status">Verifying your link…</p>}
        {token && !busy && !error && message && <p className="mt-4 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900" role="status">{message}</p>}
        {!token && (
          <form className="mt-5 space-y-4" onSubmit={resend}>
            <p className="text-sm text-slate-600">Enter your account email to request another verification link.</p>
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
              {busy ? "Please wait…" : "Send verification link"}
            </button>
          </form>
        )}
        {(error || message) && !(token && !error && message) && (
          <p className={`mt-4 rounded-xl p-4 text-sm ${error ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-900"}`} role={error ? "alert" : "status"}>
            {error || message}
          </p>
        )}
        <Link className="mt-6 inline-block text-sm font-semibold text-blue-700 hover:underline" href="/">
          Return to sign in
        </Link>
      </section>
    </main>
  );
}
