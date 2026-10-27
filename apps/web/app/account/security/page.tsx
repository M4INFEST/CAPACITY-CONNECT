"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type MfaStatus = {
  enabled: boolean;
  recovery_codes_remaining: number;
};

type Account = {
  roles: string[];
};

type MfaSetup = {
  secret: string;
  otpauth_uri: string;
};

type MfaEnrollment = {
  access_token: string;
  recovery_codes: string[];
};

async function request<T extends object>(path: string, token: string, body?: object): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: body ? "POST" : "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  const data = (await response.json().catch(() => null)) as
    | { detail?: string }
    | T
    | null;
  if (!response.ok) {
    throw new Error(
      data && "detail" in data && typeof data.detail === "string"
        ? data.detail
        : `Account security request failed (${response.status}).`,
    );
  }
  return data as T;
}

export default function AccountSecurityPage() {
  const router = useRouter();
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadAccountSecurity = useCallback(async () => {
    const token = window.sessionStorage.getItem("capacity-connect-token");
    if (!token) {
      setError("Sign in to manage account security.");
      return;
    }
    setError("");
    try {
      const [mfaStatus, currentAccount] = await Promise.all([
        request<MfaStatus>("/api/v1/auth/mfa/status", token),
        request<Account>("/api/v1/auth/me", token),
      ]);
      setStatus(mfaStatus);
      setAccount(currentAccount);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load account security.");
    }
  }, []);

  useEffect(() => {
    void loadAccountSecurity();
  }, [loadAccountSecurity]);

  async function beginSetup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const token = window.sessionStorage.getItem("capacity-connect-token");
      if (!token) throw new Error("Sign in to manage account security.");
      setSetup(
        await request<MfaSetup>("/api/v1/auth/mfa/setup", token, { password }),
      );
      setCode("");
    } catch (setupError) {
      setError(setupError instanceof Error ? setupError.message : "Could not start MFA setup.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmSetup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const token = window.sessionStorage.getItem("capacity-connect-token");
      if (!token) throw new Error("Sign in to manage account security.");
      const enrollment = await request<MfaEnrollment>(
        "/api/v1/auth/mfa/confirm",
        token,
        { code },
      );
      window.sessionStorage.setItem("capacity-connect-token", enrollment.access_token);
      setRecoveryCodes(enrollment.recovery_codes);
      setSetup(null);
      setPassword("");
      setCode("");
      setStatus({ enabled: true, recovery_codes_remaining: enrollment.recovery_codes.length });
      setNotice("MFA is enabled. Save each recovery code now; they will not be shown again.");
    } catch (confirmError) {
      setError(confirmError instanceof Error ? confirmError.message : "Could not verify MFA.");
    } finally {
      setBusy(false);
    }
  }

  async function disableMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const token = window.sessionStorage.getItem("capacity-connect-token");
      if (!token) throw new Error("Sign in to manage account security.");
      await request<{ message: string }>("/api/v1/auth/mfa/disable", token, {
        password,
        code,
      });
      window.sessionStorage.removeItem("capacity-connect-token");
      router.replace("/");
    } catch (disableError) {
      setError(disableError instanceof Error ? disableError.message : "Could not disable MFA.");
    } finally {
      setBusy(false);
    }
  }

  const mfaRequired = (account?.roles ?? []).some((role) =>
    ["trainer", "employer", "admin"].includes(role),
  );

  return (
    <main className="mx-auto max-w-3xl px-5 py-10">
      <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <p className="text-sm font-semibold uppercase tracking-wide text-blue-700">Account</p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">Security settings</h1>
        <p className="mt-3 text-slate-600">
          Manage authenticator-based multi-factor authentication and one-time recovery codes.
        </p>

        {error && (
          <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="mt-5 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800" role="status">
            {notice}
          </p>
        )}

        {status && (
          <section className="mt-7 rounded-2xl bg-slate-50 p-5" aria-live="polite">
            <h2 className="font-semibold text-slate-950">
              Authenticator MFA: {status.enabled ? "Enabled" : "Not enabled"}
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              {mfaRequired
                ? "MFA is mandatory for at least one role on this account."
                : "MFA is optional for learner accounts."}
              {status.enabled
                ? ` ${status.recovery_codes_remaining} recovery codes remain.`
                : ""}
            </p>
          </section>
        )}

        {recoveryCodes && (
          <section className="mt-6 rounded-2xl border border-amber-300 bg-amber-50 p-5">
            <h2 className="font-semibold text-amber-950">Save your recovery codes</h2>
            <p className="mt-1 text-sm text-amber-900">
              Store these somewhere private and separate from your authenticator. Each code works once.
            </p>
            <ul className="mt-4 grid gap-2 font-mono text-sm sm:grid-cols-2">
              {recoveryCodes.map((recoveryCode) => (
                <li className="rounded-lg bg-white px-3 py-2" key={recoveryCode}>
                  {recoveryCode}
                </li>
              ))}
            </ul>
            <button
              className="mt-4 rounded-xl bg-amber-900 px-4 py-2 font-semibold text-white hover:bg-amber-800"
              onClick={() => setRecoveryCodes(null)}
              type="button"
            >
              I saved these codes
            </button>
          </section>
        )}

        {status?.enabled && !mfaRequired && (
          <form className="mt-7 space-y-4 border-t border-slate-200 pt-6" onSubmit={disableMfa}>
            <h2 className="text-lg font-semibold text-slate-950">Disable optional MFA</h2>
            <p className="text-sm text-slate-600">
              Verify your password and a fresh authenticator or unused recovery code. Your current session will end.
            </p>
            <label className="block text-sm font-medium text-slate-700">
              Current password
              <input
                autoComplete="current-password"
                className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2"
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Authenticator or recovery code
              <input
                autoComplete="one-time-code"
                className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2"
                onChange={(event) => setCode(event.target.value)}
                required
                value={code}
              />
            </label>
            <button
              className="rounded-xl border border-rose-300 px-4 py-2 font-semibold text-rose-800 hover:bg-rose-50 disabled:opacity-60"
              disabled={busy}
              type="submit"
            >
              {busy ? "Please wait…" : "Disable MFA"}
            </button>
          </form>
        )}

        {status && !status.enabled && (
          <form className="mt-7 space-y-4 border-t border-slate-200 pt-6" onSubmit={beginSetup}>
            <h2 className="text-lg font-semibold text-slate-950">Set up an authenticator</h2>
            <p className="text-sm text-slate-600">
              Use an authenticator app that supports TOTP. MFA is enabled only after you verify a current code.
            </p>
            <label className="block text-sm font-medium text-slate-700">
              Current password
              <input
                autoComplete="current-password"
                className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2"
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </label>
            <button
              className="rounded-xl bg-blue-700 px-4 py-2 font-semibold text-white hover:bg-blue-800 disabled:opacity-60"
              disabled={busy}
              type="submit"
            >
              {busy ? "Please wait…" : "Begin MFA setup"}
            </button>
          </form>
        )}

        {setup && (
          <form className="mt-7 space-y-4 border-t border-slate-200 pt-6" onSubmit={confirmSetup}>
            <h2 className="text-lg font-semibold text-slate-950">Verify authenticator setup</h2>
            <p className="text-sm text-slate-600">
              Add this key manually, or open the authenticator URI in a compatible app:
            </p>
            <p className="break-all rounded-xl bg-slate-100 p-3 font-mono text-sm">{setup.secret}</p>
            <a className="inline-block font-semibold text-blue-700 underline" href={setup.otpauth_uri}>
              Open authenticator URI
            </a>
            <label className="block text-sm font-medium text-slate-700">
              Six-digit authenticator code
              <input
                autoComplete="one-time-code"
                className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2"
                inputMode="numeric"
                onChange={(event) => setCode(event.target.value)}
                required
                value={code}
              />
            </label>
            <button
              className="rounded-xl bg-blue-700 px-4 py-2 font-semibold text-white hover:bg-blue-800 disabled:opacity-60"
              disabled={busy}
              type="submit"
            >
              {busy ? "Please wait…" : "Verify and enable MFA"}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
