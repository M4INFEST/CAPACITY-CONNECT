"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type SkillGap = {
  competency_id: string;
  skill_name: string;
  current_level: number;
  required_level: number;
  gap_levels: number;
  priority: "critical" | "high" | "medium" | "nice_to_have" | "complete";
  employer_feedback_goal: { target_level: number; note: string } | null;
  course_href: string;
  demand: {
    status: "available" | "not_enough_data";
    score: number | null;
    source: string | null;
    source_url: string | null;
    observed_at: string | null;
    sample_size: number | null;
    minimum_sample_size: number;
    source_type: string | null;
  };
};
type RoleReport = {
  role_id: string;
  role_name: string;
  match_percentage: number;
  last_observed_at: string | null;
  market_sample_count: number;
  skills: SkillGap[];
};
type GapReport = { minimum_demand_sample_size: number; roles: RoleReport[] };
type Simulation = {
  before_match_percentage: number;
  after_match_percentage: number;
  change_percentage_points: number;
};

async function apiRequest<T>(token: string, path: string, options?: RequestInit) {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        Authorization: `******`,
        ...(options?.body ? { "Content-Type": "application/json" } : {}),
        ...options?.headers,
      },
    });
  } catch {
    throw new Error(`Could not reach the API at ${API_URL}. Start the stack with docker compose up --build.`);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(
      typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`,
    );
  }
  return (await response.json()) as T;
}

export default function JobGapsPage() {
  const [token, setToken] = useState("");
  const [report, setReport] = useState<GapReport | null>(null);
  const [roleId, setRoleId] = useState("");
  const [skillId, setSkillId] = useState("");
  const [proposedLevel, setProposedLevel] = useState(3);
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with your trainee account to see job gaps.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void apiRequest<GapReport>(accessToken, "/api/v1/jobs/gap-analysis")
      .then((data) => {
        if (!active) return;
        setReport(data);
        setRoleId(data.roles[0]?.role_id ?? "");
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load the report.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const roles = report?.roles ?? [];
  const selectedRole = roles.find((role) => role.role_id === roleId) ?? null;
  const gaps = selectedRole?.skills.filter((skill) => skill.gap_levels > 0) ?? [];

  async function simulate() {
    const selectedSkillId = skillId || gaps[0]?.competency_id;
    if (!roleId || !selectedSkillId) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest<Simulation>(
        token,
        "/api/v1/jobs/gap-analysis/what-if",
        {
          method: "POST",
          body: JSON.stringify({
            role_id: roleId,
            competency_id: selectedSkillId,
            proposed_level: proposedLevel,
          }),
        },
      );
      setSimulation(result);
    } catch (simulationError) {
      setError(simulationError instanceof Error ? simulationError.message : "Could not simulate this change.");
    } finally {
      setBusy(false);
    }
  }

  async function exportReport() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(
        `${API_URL}/api/v1/jobs/gap-analysis/export.pdf?role_id=${encodeURIComponent(roleId)}`,
        { headers: { Authorization: `******` } },
      );
      if (!response.ok) throw new Error(`PDF export failed (${response.status}).`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "capacity-connect-job-gaps.pdf";
      link.click();
      URL.revokeObjectURL(url);
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : "Could not export the report.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#0b0f19] px-4 py-8 sm:px-6 lg:px-8 text-slate-100 antialiased selection:bg-blue-500/30">
      <section className="mx-auto max-w-7xl">
        {/* Career Pathway Stepper */}
        <div className="mb-6 rounded-3xl border border-white/10 bg-slate-900/60 p-5 backdrop-blur-xl shadow-xl">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <span className="text-[11px] font-bold uppercase tracking-wider text-amber-400">Step 2 of Career Journey</span>
              <h1 className="mt-1 text-2xl font-black text-white sm:text-3xl">Role Skill Gap Diagnostic</h1>
              <p className="mt-1 max-w-2xl text-xs text-slate-400 sm:text-sm">
                Empirical comparison of your verified credentials against market requirements, with simulated match gains and course bridges.
              </p>
            </div>
            {selectedRole && (
              <button
                className="rounded-xl bg-gradient-to-r from-amber-600 to-orange-600 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-amber-500/20 transition hover:brightness-110 disabled:opacity-50"
                disabled={busy}
                onClick={() => void exportReport()}
                type="button"
              >
                Export Gap PDF
              </button>
            )}
          </div>

          {/* Stepper Navigation Bar */}
          <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-6 text-center text-xs">
            <Link href="/" className="rounded-xl border border-white/5 bg-slate-800/40 p-2.5 text-slate-400 hover:text-white transition">
              1. Skill Passport
            </Link>
            <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-2.5 font-bold text-amber-300 shadow-sm">
              2. Skill Gaps (Active)
            </div>
            <Link href="/roadmap" className="rounded-xl border border-white/5 bg-slate-800/40 p-2.5 text-slate-400 hover:text-white transition">
              3. Roadmap
            </Link>
            <Link href="/learning" className="rounded-xl border border-white/5 bg-slate-800/40 p-2.5 text-slate-400 hover:text-white transition">
              4. Course Picks
            </Link>
            <Link href="/assessment" className="rounded-xl border border-white/5 bg-slate-800/40 p-2.5 text-slate-400 hover:text-white transition">
              5. Validate (IRT)
            </Link>
            <Link href="/jobs" className="rounded-xl border border-white/5 bg-slate-800/40 p-2.5 text-slate-400 hover:text-white transition">
              6. Jobs & STAR
            </Link>
          </div>
        </div>

        {error && <p className="mb-6 rounded-2xl border border-rose-500/30 bg-rose-950/40 p-4 text-sm font-medium text-rose-300" role="alert">{error}</p>}
        {loading && (
          <div className="mt-8 flex items-center justify-center py-12 text-slate-400">
            <div className="h-7 w-7 animate-spin rounded-full border-2 border-amber-500 border-t-transparent" />
            <span className="ml-3 text-sm font-semibold">Running diagnostic skill gap analysis…</span>
          </div>
        )}
        {!loading && roles.length === 0 && (
          <div className="mt-8 rounded-3xl border border-white/10 bg-slate-900/60 p-6 backdrop-blur-xl">
            <h2 className="text-lg font-bold text-white">Select a target role first</h2>
            <p className="mt-2 text-slate-400 text-sm">Add a target role in your Skill Passport to generate a report.</p>
            <Link className="mt-4 inline-block font-semibold text-blue-400 underline" href="/">Open Skill Passport</Link>
          </div>
        )}

        {selectedRole && (
          <div className="mt-7 space-y-6">
            <section className="flex flex-wrap items-center justify-between gap-4 rounded-3xl border border-white/10 bg-slate-900/60 p-5 backdrop-blur-xl">
              <label className="text-sm font-semibold text-slate-200">
                Target role

                <select
                  className="mt-1 block min-w-64 rounded-lg border border-slate-300 px-3 py-2"
                  onChange={(event) => {
                    setRoleId(event.target.value);
                    setSimulation(null);
                  }}
                  value={roleId}
                >
                  {roles.map((role) => <option key={role.role_id} value={role.role_id}>{role.role_name}</option>)}
                </select>
              </label>
              <div className="text-right">
                <p className="text-sm text-slate-500">Passport match</p>
                <p className="text-3xl font-bold text-slate-950">{selectedRole.match_percentage}%</p>
              </div>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <h2 className="text-xl font-bold">Role gap report</h2>
              <p className="mt-1 text-sm text-slate-600">
                Market demand is weighted only when a source provides at least {report?.minimum_demand_sample_size} observations.
                Each figure includes its source, observation date, and sample size.
              </p>
              <div className="mt-5 space-y-3">
                {selectedRole.skills.map((skill) => (
                  <article className="rounded-xl border border-slate-200 p-4" key={skill.competency_id}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h3 className="font-semibold text-slate-950">{skill.skill_name}</h3>
                        <p className="mt-1 text-sm text-slate-600">
                          Level {skill.current_level} of {skill.required_level} · {skill.priority.replaceAll("_", " ")}
                        </p>
                        {skill.employer_feedback_goal && (
                          <p className="mt-2 rounded-lg bg-amber-50 p-2 text-sm text-amber-900">
                            Employer feedback priority: {skill.employer_feedback_goal.note}
                            {" "}Target level {skill.employer_feedback_goal.target_level}.
                          </p>
                        )}
                        {skill.gap_levels > 0 && (
                          <Link className="mt-2 inline-block text-sm font-semibold text-blue-700 underline" href={skill.course_href}>
                            Find a recommended course
                          </Link>
                        )}
                      </div>
                      <div className="max-w-sm text-right text-xs text-slate-500">
                        {skill.demand.status === "available" ? (
                          <>
                            <p className="font-semibold text-slate-700">Market demand: {(skill.demand.score! * 100).toFixed(0)}%</p>
                            <p>
                              {skill.demand.source}
                              {skill.demand.source_url && <> · <a className="underline" href={skill.demand.source_url} rel="noreferrer" target="_blank">source</a></>}
                            </p>
                            <p>{skill.demand.observed_at ? new Date(skill.demand.observed_at).toLocaleDateString() : "Date unavailable"} · n={skill.demand.sample_size}</p>
                          </>
                        ) : (
                          <>
                            <p className="font-semibold text-slate-600">Not enough data</p>
                            <p>
                              {skill.demand.source ?? "No source observation"}
                              {skill.demand.observed_at && <> · {new Date(skill.demand.observed_at).toLocaleDateString()}</>}
                              {" "}· n={skill.demand.sample_size ?? "unknown"}
                            </p>
                          </>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            {gaps.length > 0 && (
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <h2 className="text-xl font-bold">What-if simulator</h2>
                <p className="mt-1 text-sm text-slate-600">This changes only the preview; it does not update your Passport.</p>
                <div className="mt-4 flex flex-wrap items-end gap-3">
                  <label className="text-sm font-semibold">
                    Skill
                    <select className="mt-1 block rounded-lg border border-slate-300 px-3 py-2" onChange={(event) => setSkillId(event.target.value)} value={skillId || gaps[0].competency_id}>
                      {gaps.map((skill) => <option key={skill.competency_id} value={skill.competency_id}>{skill.skill_name}</option>)}
                    </select>
                  </label>
                  <label className="text-sm font-semibold">
                    Hypothetical level
                    <select className="mt-1 block rounded-lg border border-slate-300 px-3 py-2" onChange={(event) => setProposedLevel(Number(event.target.value))} value={proposedLevel}>
                      {[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>Level {level}</option>)}
                    </select>
                  </label>
                  <button className="rounded-xl bg-slate-900 px-4 py-2 font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void simulate()} type="button">
                    {busy ? "Calculating…" : "Simulate"}
                  </button>
                </div>
                {simulation && (
                  <p className="mt-4 rounded-xl bg-blue-50 p-4 font-semibold text-blue-950" role="status">
                    Match preview: {simulation.before_match_percentage}% → {simulation.after_match_percentage}%
                    {" "}({simulation.change_percentage_points >= 0 ? "+" : ""}{simulation.change_percentage_points} points)
                  </p>
                )}
              </section>
            )}
          </div>
        )}
        <p className="mt-6 text-xs text-slate-500">
          Market data is imported only from open or licensed sources, employer-published feeds, or platform jobs. No prohibited site scraping is used.
          Weekly updates require an authorized administrator to import a fresh, provenance-labeled observation.
        </p>
      </section>
    </main>
  );
}
