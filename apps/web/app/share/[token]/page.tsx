"use client";

import { use, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ShareData = {
  sections: string[];
  passport: {
    skills?: Array<{ skill_name: string; level: number | null; status: string; freshness: string }>;
    evidence?: Array<{
      skill_name: string | null;
      source_type: string;
      verification: string;
      created_at: string;
    }>;
    target_roles?: string[];
    credentials?: Array<{
      skill_name: string;
      level: number;
      evidence_tier: string;
      issued_at: string;
    }>;
  };
};

export default function SharedPassport({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [data, setData] = useState<ShareData | null>(null);
  const [error, setError] = useState("");
  const [requiresSignIn, setRequiresSignIn] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(`${API_URL}/api/v1/passport/shared/${encodeURIComponent(token)}`)
      .then(async (response) => {
        const result = (await response.json()) as ShareData | { detail?: string };
        if (response.status === 401) {
          if (active) setRequiresSignIn(true);
          return;
        }
        if (!response.ok) {
          throw new Error(
            "detail" in result ? result.detail ?? "This share link is unavailable." : "This share link is unavailable.",
          );
        }
        if (active) setData(result as ShareData);
      })
      .catch((requestError: unknown) => {
        if (active) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "This share link is unavailable.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [token]);

  async function signInAsEmployer(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError("");
    setBusy(true);
    try {
      const loginResponse = await fetch(`${API_URL}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const login = (await loginResponse.json()) as {
        access_token?: string;
        detail?: string;
      };
      if (!loginResponse.ok || !login.access_token) {
        throw new Error(login.detail ?? "Could not sign in");
      }
      const passportResponse = await fetch(
        `${API_URL}/api/v1/passport/shared/${encodeURIComponent(token)}`,
        { headers: { Authorization: `Bearer ${login.access_token}` } },
      );
      const result = (await passportResponse.json()) as ShareData | { detail?: string };
      if (!passportResponse.ok) {
        throw new Error(
          "detail" in result ? result.detail ?? "You cannot view this passport." : "You cannot view this passport.",
        );
      }
      setData(result as ShareData);
      setRequiresSignIn(false);
    } catch (requestError) {
      setAuthError(requestError instanceof Error ? requestError.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-12">
      <article className="mx-auto max-w-3xl rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-bold uppercase tracking-[0.18em] text-blue-700">
          Capacity Connect
        </p>
        <h1 className="mt-3 text-3xl font-bold">Shared Skill Passport</h1>
        <p className="mt-2 text-sm text-slate-600">
          Read-only view of the sections selected by the passport owner.
        </p>

        {!data && !error && (
          <p className="mt-8 text-slate-600" role="status">Loading shared passport…</p>
        )}
        {error && (
          <p className="mt-8 rounded-xl bg-amber-50 p-4 text-amber-900" role="alert">
            {error}
          </p>
        )}
        {requiresSignIn && !data && (
          <form className="mt-8 space-y-4 rounded-2xl bg-slate-50 p-5" onSubmit={signInAsEmployer}>
            <div>
              <h2 className="font-semibold">Verified employer access</h2>
              <p className="mt-1 text-sm text-slate-600">
                Sign in with an employer account verified to Level 2.
              </p>
            </div>
            <label className="block text-sm font-medium">
              Email
              <input
                autoComplete="email"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                onChange={(event) => setEmail(event.target.value)}
                required
                type="email"
                value={email}
              />
            </label>
            <label className="block text-sm font-medium">
              Password
              <input
                autoComplete="current-password"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </label>
            {authError && <p className="text-sm text-rose-700" role="alert">{authError}</p>}
            <button
              className="rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50"
              disabled={busy}
              type="submit"
            >
              {busy ? "Checking…" : "Sign in"}
            </button>
          </form>
        )}
        {data && (
          <div className="mt-8 space-y-8">
            {data.passport.skills && (
              <section>
                <h2 className="text-xl font-bold">Skills</h2>
                {data.passport.skills.length === 0 ? (
                  <p className="mt-3 text-sm text-slate-500">No skills shared.</p>
                ) : (
                  <ul className="mt-3 grid gap-3 sm:grid-cols-2">
                    {data.passport.skills.map((skill) => (
                      <li className="rounded-xl border border-slate-200 p-4" key={skill.skill_name}>
                        <p className="font-semibold">{skill.skill_name}</p>
                        <p className="mt-1 text-sm text-slate-600">
                          {skill.level ? `Level ${skill.level}` : "Level not rated"} ·{" "}
                          {skill.status === "verified" ? "Verified" : skill.status === "provisional" ? "Provisional" : "Claimed"} ·{" "}
                          Freshness: {skill.freshness}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
            {data.passport.target_roles && (
              <section>
                <h2 className="text-xl font-bold">Target roles</h2>
                <ul className="mt-3 flex flex-wrap gap-2">
                  {data.passport.target_roles.map((role) => (
                    <li className="rounded-full bg-blue-50 px-3 py-1.5 text-sm text-blue-900" key={role}>
                      {role}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {data.passport.evidence && (
              <section>
                <h2 className="text-xl font-bold">Evidence</h2>
                <ul className="mt-3 space-y-2">
                  {data.passport.evidence.map((evidence, index) => (
                    <li className="rounded-xl border border-slate-200 p-3 text-sm" key={`${evidence.source_type}-${index}`}>
                      {evidence.skill_name ?? "General"} · {evidence.source_type} · {evidence.verification}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {data.passport.credentials && (
              <section>
                <h2 className="text-xl font-bold">Credentials</h2>
                <ul className="mt-3 space-y-2">
                  {data.passport.credentials.map((credential) => (
                    <li className="rounded-xl border border-slate-200 p-3 text-sm" key={`${credential.skill_name}-${credential.issued_at}`}>
                      {credential.skill_name} · Level {credential.level} · {credential.evidence_tier}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        )}
      </article>
    </main>
  );
}
