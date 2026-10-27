"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Gap = {
  competency_id: string;
  skill_name: string;
  current_level: number;
  required_level: number;
  importance: number;
  gap_levels: number;
  gap_score: number;
  priority: "critical" | "high" | "medium" | "nice_to_have";
};
type ReadinessSnapshot = {
  created_at: string;
  readiness_before: number;
  readiness_after: number;
  readiness_delta: number;
};
type RoleProgress = {
  role_id: string;
  role_name: string;
  readiness: number;
  readiness_trend: number | null;
  gap_groups: Record<Gap["priority"], Gap[]>;
  history: ReadinessSnapshot[];
};
type Skill = {
  competency_id: string;
  skill_name: string;
  level: number | null;
  status: string;
  freshness: "current" | "aging" | "stale";
  half_life_days: number;
  last_evidence_at: string | null;
  role_required: boolean;
  suggest_refresher: boolean;
};
type ProfileProgress = {
  roles: RoleProgress[];
  skills: Skill[];
  latest_update: {
    attempt_id: string | null;
    readiness_by_role: Array<{
      role_id: string;
      role_name: string;
      readiness_before: number;
      readiness_after: number;
      readiness_delta: number;
    }>;
    skill_changes: Array<{
      competency_id: string;
      skill_name: string;
      previous_level: number | null;
      updated_level: number;
      evidence_quality: string;
      score: number;
      average_question_difficulty: number;
      credential_id: string | null;
    }>;
  };
};

const priorities: Array<{ key: Gap["priority"]; label: string; className: string }> = [
  { key: "critical", label: "Critical", className: "border-rose-200 bg-rose-50 text-rose-900" },
  { key: "high", label: "High", className: "border-amber-200 bg-amber-50 text-amber-950" },
  { key: "medium", label: "Medium", className: "border-blue-200 bg-blue-50 text-blue-950" },
  { key: "nice_to_have", label: "Nice to have", className: "border-slate-200 bg-slate-50 text-slate-800" },
];

async function request<T>(token: string, path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        Authorization: `Bearer ${token}`,
        ...options.headers,
      },
    });
  } catch {
    throw new Error(`Could not reach the API at ${API_URL}. Start the API and database with docker compose up --build.`);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

function readinessLabel(delta: number | null) {
  if (delta === null) return "No assessment trend yet";
  if (delta > 0) return `Up ${delta.toFixed(1)} points after the latest assessment`;
  if (delta < 0) return `Down ${Math.abs(delta).toFixed(1)} points after the latest assessment`;
  return "No readiness change after the latest assessment";
}

export default function ProfileProgressPage() {
  const [token, setToken] = useState("");
  const [data, setData] = useState<ProfileProgress | null>(null);
  const [loading, setLoading] = useState(true);
  const [busySkill, setBusySkill] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const reload = useCallback(async (accessToken: string) => {
    setData(await request<ProfileProgress>(accessToken, "/api/v1/passport/progress"));
  }, []);

  useEffect(() => {
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with your trainee account to view profile progress.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void reload(accessToken)
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not load profile progress."))
      .finally(() => setLoading(false));
  }, [reload]);

  async function acknowledge(skill: Skill) {
    setBusySkill(skill.competency_id);
    setError("");
    setNotice("");
    try {
      await request(token, `/api/v1/passport/skills/${skill.competency_id}/freshness-acknowledgement`, {
        method: "POST",
      });
      await reload(token);
      setNotice(`Refresher suggestion dismissed for ${skill.skill_name}. Freshness remains visible; your level and evidence date were not changed.`);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not dismiss refresher suggestion.");
    } finally {
      setBusySkill("");
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <section className="mx-auto max-w-6xl">
        <nav aria-label="Profile navigation" className="flex flex-wrap gap-3 text-sm font-semibold">
          <Link className="text-blue-700 hover:underline" href="/">Skill Passport</Link>
          <Link className="text-blue-700 hover:underline" href="/learning">Course picks</Link>
          <Link className="text-blue-700 hover:underline" href="/roadmap">Learning roadmap</Link>
          <Link className="text-blue-700 hover:underline" href="/job-gaps">Job gap analysis</Link>
          <Link className="text-blue-700 hover:underline" href="/role-matches">Role matches</Link>
          <Link className="text-blue-700 hover:underline" href="/jobs">Job explorer</Link>
          <Link className="text-blue-700 hover:underline" href="/credentials">My credentials</Link>
        </nav>
        <p className="mt-8 text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Stage 7</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-950">Profile and gap update</h1>
        <p className="mt-2 max-w-3xl text-slate-600">
          Assessment evidence updates skill levels and recalculates readiness for each target role. Freshness is displayed separately and never reduces a proven level.
        </p>

        {(error || notice) && (
          <p className={`mt-5 rounded-xl p-4 text-sm ${error ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-800"}`} role="status">
            {error || notice}
          </p>
        )}
        {loading && <p className="mt-8 text-slate-600">Recalculating your profile…</p>}

        {!loading && data && (
          <>
            {data.latest_update.attempt_id && (
              <section className="mt-7 rounded-2xl border border-emerald-200 bg-emerald-50 p-5" aria-live="polite">
                <h2 className="text-lg font-bold text-emerald-950">Your profile was updated after your latest assessment</h2>
                <p className="mt-1 text-sm text-emerald-900">Readiness, role gaps, and evidence were recalculated from this result.</p>
                {data.latest_update.readiness_by_role.length > 0 && (
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    {data.latest_update.readiness_by_role.map((item) => (
                      <div className="rounded-xl bg-white/80 p-3" key={item.role_id}>
                        <p className="font-semibold">{item.role_name}</p>
                        <p className="mt-1 text-sm text-slate-700">
                          {item.readiness_before.toFixed(1)}% → {item.readiness_after.toFixed(1)}%
                          <span className="ml-2 font-semibold">
                            ({item.readiness_delta > 0 ? "+" : ""}{item.readiness_delta.toFixed(1)})
                          </span>
                        </p>
                      </div>
                    ))}
                  </div>
                )}
                {data.latest_update.skill_changes.length > 0 && (
                  <ul className="mt-4 space-y-2 text-sm text-slate-800">
                    {data.latest_update.skill_changes.map((change) => (
                      <li key={change.competency_id}>
                        <strong>{change.skill_name}</strong>: {change.previous_level ?? "—"} → {change.updated_level}
                        {" · "}{change.evidence_quality} evidence
                        {" · "}score {(change.score * 100).toFixed(0)}%
                        {" · "}difficulty {change.average_question_difficulty.toFixed(1)}/5
                        {change.credential_id && (
                          <> · <Link className="font-semibold underline" href={`/credentials/issued/${change.credential_id}`}>View credential</Link></>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            <section className="mt-8">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-2xl font-bold text-slate-950">Readiness by target role</h2>
                  <p className="mt-1 text-sm text-slate-600">Weighted readiness uses each required skill’s importance and caps credit at its required level.</p>
                </div>
                <Link className="rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white" href="/learning">Find courses for gaps</Link>
              </div>
              {data.roles.length === 0 && (
                <div className="mt-4 rounded-xl border border-slate-200 bg-white p-5 text-slate-700">
                  Choose target roles in your <Link className="font-semibold text-blue-700 underline" href="/">Skill Passport</Link> to see role gaps and readiness.
                </div>
              )}
              <div className="mt-4 space-y-5">
                {data.roles.map((role) => (
                  <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" key={role.role_id}>
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <h3 className="text-xl font-bold">{role.role_name}</h3>
                        <p className={`mt-1 text-sm font-semibold ${
                          role.readiness_trend === null ? "text-slate-600" : role.readiness_trend >= 0 ? "text-emerald-700" : "text-rose-700"
                        }`}>{readinessLabel(role.readiness_trend)}</p>
                      </div>
                      <div className="min-w-40">
                        <p className="text-right text-2xl font-bold">{role.readiness.toFixed(1)}%</p>
                        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                          <div className="h-full rounded-full bg-blue-600" style={{ width: `${role.readiness}%` }} />
                        </div>
                      </div>
                    </div>
                    {role.history.length > 0 && (
                      <details className="mt-4 text-sm">
                        <summary className="cursor-pointer font-semibold text-slate-700">Readiness trend history</summary>
                        <ul className="mt-2 space-y-1 text-slate-600">
                          {role.history.map((point) => (
                            <li key={point.created_at}>
                              {new Date(point.created_at).toLocaleDateString()}: {point.readiness_before.toFixed(1)}% → {point.readiness_after.toFixed(1)}%
                              {" "}({point.readiness_delta > 0 ? "+" : ""}{point.readiness_delta.toFixed(1)})
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                    <div className="mt-5 grid gap-3 lg:grid-cols-2">
                      {priorities.map((priority) => {
                        const gaps = role.gap_groups[priority.key] ?? [];
                        if (!gaps.length) return null;
                        return (
                          <section className={`rounded-xl border p-4 ${priority.className}`} key={priority.key}>
                            <h4 className="font-bold">{priority.label}</h4>
                            <ul className="mt-2 space-y-2 text-sm">
                              {gaps.map((gap) => (
                                <li className="flex flex-wrap justify-between gap-x-3 gap-y-1" key={gap.competency_id}>
                                  <span>{gap.skill_name} · Level {gap.current_level}/{gap.required_level}</span>
                                  <span className="font-semibold">
                                    {gap.gap_levels ? `${gap.gap_levels} level${gap.gap_levels === 1 ? "" : "s"} · gap ${gap.gap_score.toFixed(2)}` : "Requirement met"}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </section>
                        );
                      })}
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="mt-9">
              <h2 className="text-2xl font-bold text-slate-950">Skill freshness</h2>
              <p className="mt-1 text-sm text-slate-600">Freshness uses each skill’s half-life and does not change its level.</p>
              <ul className="mt-4 grid gap-3 md:grid-cols-2">
                {data.skills.map((skill) => (
                  <li className="rounded-xl border border-slate-200 bg-white p-4" key={skill.competency_id}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <h3 className="font-bold">{skill.skill_name}{skill.level ? ` · Level ${skill.level}` : ""}</h3>
                        <p className="mt-1 text-sm text-slate-600">{skill.status} · {skill.half_life_days}-day half-life{skill.role_required ? " · Required by a target role" : ""}</p>
                      </div>
                      <span className={`rounded-full px-3 py-1 text-xs font-bold uppercase ${
                        skill.freshness === "current" ? "bg-emerald-100 text-emerald-800" : skill.freshness === "aging" ? "bg-amber-100 text-amber-900" : "bg-slate-200 text-slate-800"
                      }`}>{skill.freshness}</span>
                    </div>
                    {skill.suggest_refresher && (
                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 p-3 text-sm">
                        <span>Consider refreshing this role-required skill.</span>
                        <button className="font-semibold text-blue-800 underline disabled:opacity-50" disabled={busySkill === skill.competency_id} onClick={() => void acknowledge(skill)} type="button">
                          I use this regularly
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              {data.skills.length === 0 && <p className="mt-4 rounded-xl bg-white p-5 text-slate-600">Add or confirm skills in your passport to track freshness.</p>}
            </section>
          </>
        )}
      </section>
    </main>
  );
}
