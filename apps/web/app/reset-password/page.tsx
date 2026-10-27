"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function ResetPasswordPage() {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const resetToken = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (resetToken) {
      setToken(resetToken);
      window.history.replaceState(null, "", window.location.pathname);
    } else {
      setError("This reset link is missing its one-time token. Request a new link.");
    }
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setBusy(true);
    try {
      const response = await fetch(`${API_URL}/api/v1/auth/password/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const result = (await response.json()) as { message?: string; detail?: string };
      if (!response.ok) throw new Error(result.detail ?? `Request failed (${response.status})`);
      setMessage(result.message ?? "Password reset. You can now sign in.");
      setPassword("");
      setToken("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not reset password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-12">
      <section className="mx-auto max-w-lg rounded-3xl border border-slate-200 bg-white p-7 shadow-sm">
        <p className="text-sm font-bold uppercase tracking-wider text-blue-700">Capacity Connect</p>
        <h1 className="mt-3 text-2xl font-bold">Choose a new password</h1>
        {token && (
          <form className="mt-5 space-y-4" onSubmit={submit}>
            <label className="block text-sm font-medium">
              New password
              <input
                autoComplete="new-password"
                className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                minLength={12}
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </label>
            <p className="text-xs text-slate-500">At least 12 characters, including uppercase, lowercase, and a number.</p>
            <button className="w-full rounded-xl bg-blue-700 px-4 py-3 font-semibold text-white disabled:opacity-50" disabled={busy} type="submit">
              {busy ? "Please wait…" : "Reset password"}
            </button>
          </form>
        )}
        {(error || message) && <p className={`mt-4 rounded-xl p-4 text-sm ${error ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-900"}`} role={error ? "alert" : "status"}>{error || message}</p>}
        <Link className="mt-6 inline-block text-sm font-semibold text-blue-700 hover:underline" href="/">Return to sign in</Link>
      </section>
    </main>
  );
}
