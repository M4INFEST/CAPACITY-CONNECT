"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type CompetencyMatch = {
  competency_id: string;
  skill_name: string;
  current_level: number;
  required_level: number;
  importance: number;
  gap_levels: number;
  demand: {
    status: "available" | "not_enough_data";
    score: number | null;
    source_name: string | null;
    source_url: string | null;
    observed_at: string | null;
    sample_size: number | null;
  };
};
type AdjacentRole = {
  role_id: string;
  role_name: string;
  shared_skill_similarity: number;
  fit_score: number;
};
type RoleMatch = {
  role_id: string;
  role_name: string;
  description: string | null;
  fit_score: number;
  competencies: CompetencyMatch[];
  explanation: {
    method: string;
    scoring_version: string;
    formula: string;
    market_data_coverage: number;
    average_demand_score: number | null;
    latest_market_observation: string | null;
    demand_sources: Array<{
      source_name: string | null;
      source_url: string | null;
      observed_at: string | null;
      sample_size: number;
      source_type: string | null;
    }>;
    shap_waterfall?: Array<{
      skill_name: string;
      positive_gain: number;
      gap_penalty: number;
      net_impact: number;
    }>;
  };

  top_contributors: CompetencyMatch[];
  largest_gaps: CompetencyMatch[];
  adjacent_roles: AdjacentRole[];
};
type MatchResponse = {
  scoring_version: string;
  matches: RoleMatch[];
  model_status: string;
};

async function request<T>(
  token: string,
  path: string,
  options?: RequestInit,
): Promise<T> {
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
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function RoleMatchesPage() {
  const [token, setToken] = useState("");
  const [matches, setMatches] = useState<RoleMatch[]>([]);
  const [modelStatus, setModelStatus] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [includeHidden, setIncludeHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadMatches = useCallback(async (accessToken: string, includeNotInterested: boolean) => {
    const result = await request<MatchResponse>(
      accessToken,
      `/api/v1/role-matches?include_not_interested=${includeNotInterested}`,
    );
    setMatches(result.matches);
    setModelStatus(result.model_status);
    setSelectedId((previous) =>
      result.matches.some((match) => match.role_id === previous)
        ? previous
        : result.matches[0]?.role_id ?? "",
    );
  }, []);

  useEffect(() => {
    let active = true;
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with your trainee account to see role matches.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void request<MatchResponse>(accessToken, "/api/v1/role-matches")
      .then((result) => {
        if (!active) return;
        setMatches(result.matches);
        setModelStatus(result.model_status);
        setSelectedId(result.matches[0]?.role_id ?? "");
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not load role matches.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const selected = matches.find((match) => match.role_id === selectedId) ?? null;

  async function refresh() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request<MatchResponse>(
        token,
        `/api/v1/role-matches/refresh?include_not_interested=${includeHidden}`,
        { method: "POST" },
      );
      setMatches(result.matches);
      setModelStatus(result.model_status);
      setSelectedId(result.matches[0]?.role_id ?? "");
      setNotice("Your role matches have been recalculated and recorded.");
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "Could not refresh role matches.");
    } finally {
      setBusy(false);
    }
  }

  async function markTarget(role: RoleMatch) {
    setBusy(true);
    setError("");
    try {
      await request(token, `/api/v1/role-matches/${role.role_id}/target`, { method: "POST" });
      setNotice(`${role.role_name} is now a target role in your Skill Passport.`);
    } catch (targetError) {
      setError(targetError instanceof Error ? targetError.message : "Could not set the target role.");
    } finally {
      setBusy(false);
    }
  }

  async function notInterested(role: RoleMatch) {
    setBusy(true);
    setError("");
    try {
      await request(token, `/api/v1/role-matches/${role.role_id}/feedback`, {
        method: "POST",
        body: JSON.stringify({ feedback: "not_interested" }),
      });
      if (!includeHidden) {
        const remaining = matches.filter((match) => match.role_id !== role.role_id);
        setMatches(remaining);
        if (selectedId === role.role_id) {
          setSelectedId(remaining[0]?.role_id ?? "");
        }
      }
      setNotice(`We’ll exclude ${role.role_name} from future matches. You can bring hidden roles back from the filter.`);
    } catch (feedbackError) {
      setError(feedbackError instanceof Error ? feedbackError.message : "Could not save your feedback.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <section className="mx-auto max-w-6xl">
        <nav aria-label="Role matching navigation" className="flex flex-wrap gap-4 text-sm font-semibold">
          <Link className="text-blue-700 hover:underline" href="/">Skill Passport</Link>
          <Link className="text-blue-700 hover:underline" href="/learning">Course picks</Link>
          <Link className="text-blue-700 hover:underline" href="/job-gaps">Job gap analysis</Link>
          <Link className="text-blue-700 hover:underline" href="/roadmap">Learning roadmap</Link>
          <Link className="text-blue-700 hover:underline" href="/jobs">Job explorer</Link>
        </nav>
        <header className="mt-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Stage 10</p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-950">Role matches</h1>
            <p className="mt-2 max-w-3xl text-slate-600">
              Compare your Passport with role requirements and see which skills raised or lowered each match.
            </p>
          </div>
          <button className="rounded-xl bg-blue-700 px-4 py-2 font-semibold text-white disabled:opacity-50" disabled={busy || loading} onClick={() => void refresh()} type="button">
            {busy ? "Working…" : "Refresh matches"}
          </button>
        </header>
        {(error || notice) && (
          <p className={`mt-5 rounded-xl p-4 text-sm ${error ? "bg-rose-50 text-rose-800" : "bg-emerald-50 text-emerald-800"}`} role={error ? "alert" : "status"}>
            {error || notice}
          </p>
        )}
        <p className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
          {modelStatus || "Role fit uses a transparent, importance-weighted skill-coverage score. No learned role model is currently integrated."}
          {" "}Scores are guidance, not hiring decisions.
        </p>
        <label className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-slate-700">
          <input checked={includeHidden} onChange={(event) => {
            const checked = event.target.checked;
            setIncludeHidden(checked);
            if (token) void loadMatches(token, checked).catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not load matches."));
          }} type="checkbox" />
          Include roles marked “Not interested”
        </label>
        {loading && <p className="mt-6 text-slate-600">Comparing your skills with active roles…</p>}
        {!loading && matches.length === 0 && (
          <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="font-bold">No role matches yet</h2>
            <p className="mt-2 text-sm text-slate-600">Add competency requirements to active roles, then refresh the matches.</p>
            <Link className="mt-3 inline-block font-semibold text-blue-700 underline" href="/">Review your Skill Passport</Link>
          </div>
        )}
        {!loading && matches.length > 0 && (
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.5fr)]">
            <section className="space-y-3" aria-label="Matched roles">
              {matches.map((match, index) => (
                <button aria-pressed={selectedId === match.role_id} className={`w-full rounded-2xl border bg-white p-4 text-left shadow-sm ${selectedId === match.role_id ? "border-blue-500 ring-2 ring-blue-100" : "border-slate-200"}`} key={match.role_id} onClick={() => setSelectedId(match.role_id)} type="button">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-bold uppercase tracking-wide text-slate-500">#{index + 1} match</p>
                      <h2 className="mt-1 font-bold text-slate-950">{match.role_name}</h2>
                    </div>
                    <span className="text-2xl font-bold text-blue-800">{match.fit_score}%</span>
                  </div>
                  <p className="mt-2 line-clamp-2 text-sm text-slate-600">{match.description ?? "Role requirements and skill match."}</p>
                  <p className="mt-3 text-xs text-slate-500">Market data coverage: {match.explanation.market_data_coverage}%</p>
                </button>
              ))}
            </section>
            {selected && (
              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-blue-700">Role detail · Fit {selected.fit_score}%</p>
                    <h2 className="mt-1 text-2xl font-bold text-slate-950">{selected.role_name}</h2>
                    <p className="mt-2 text-slate-600">{selected.description ?? "No role description is available yet."}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button className="rounded-xl bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void markTarget(selected)} type="button">Set as target</button>
                    <button className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={busy} onClick={() => void notInterested(selected)} type="button">Not interested</button>
                  </div>
                </div>
                <div className="mt-5 rounded-2xl border border-white/10 bg-slate-900/60 p-5 backdrop-blur-xl shadow-lg">
                  <div className="flex items-center justify-between border-b border-white/10 pb-3">
                    <div>
                      <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-400">CareerFlow Intelligence Engine</span>
                      <h3 className="text-base font-bold text-white">Why This Role Fits You (SHAP Attribution)</h3>
                    </div>
                    <span className="rounded-lg bg-cyan-500/10 px-2.5 py-1 text-xs font-semibold text-cyan-300">
                      {selected.explanation.scoring_version}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-slate-300 leading-relaxed">{selected.explanation.method}</p>

                  {/* SHAP Waterfall Attribution Bars */}
                  {selected.explanation.shap_waterfall && selected.explanation.shap_waterfall.length > 0 && (
                    <div className="mt-4 space-y-2.5">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                        Marginal Fit Attribution per Competency:
                      </p>
                      {selected.explanation.shap_waterfall.map((item) => (
                        <div className="rounded-xl border border-white/5 bg-slate-950/40 p-2.5 text-xs" key={item.skill_name}>
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-slate-200">{item.skill_name}</span>
                            <span className={item.net_impact >= 0 ? "font-bold text-emerald-400" : "font-bold text-amber-400"}>
                              {item.net_impact >= 0 ? `+${item.net_impact}%` : `${item.net_impact}%`}
                            </span>
                          </div>
                          <div className="mt-1.5 flex h-2 w-full overflow-hidden rounded-full bg-slate-800">
                            <div
                              className="bg-emerald-500 transition-all duration-500"
                              style={{ width: `${Math.min(100, Math.max(0, item.positive_gain))}%` }}
                            />
                            {item.gap_penalty > 0 && (
                              <div
                                className="bg-amber-500/80 transition-all duration-500"
                                style={{ width: `${Math.min(100, Math.max(0, item.gap_penalty))}%` }}
                              />
                            )}
                          </div>
                          <div className="mt-1 flex justify-between text-[10px] text-slate-400">
                            <span>Contribution: +{item.positive_gain}%</span>
                            {item.gap_penalty > 0 && <span>Gap penalty: -{item.gap_penalty}%</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  <p className="mt-3 text-[11px] text-slate-400">
                    Market data coverage: <span className="font-semibold text-white">{selected.explanation.market_data_coverage}%</span> · Bounded demand multiplier: 5%.
                  </p>
                </div>

                <div className="mt-4 rounded-xl border border-slate-200 p-4 text-sm">
                  <h3 className="font-bold text-slate-950">Typical career path</h3>
                  <p className="mt-1 text-slate-600">
                    Career-path data is not configured in this role catalog. Related roles below are based only on shared competency requirements.
                  </p>
                </div>
                {selected.explanation.demand_sources.length > 0 && (
                  <div className="mt-4">
                    <h3 className="font-bold text-slate-950">Market demand provenance</h3>
                    <ul className="mt-2 space-y-1 text-sm text-slate-600">
                      {selected.explanation.demand_sources.map((source, index) => (
                        <li key={`${source.source_name}-${index}`}>
                          {source.source_name ?? "Source"}
                          {source.source_url && <> · <a className="text-blue-700 underline" href={source.source_url} rel="noreferrer" target="_blank">view source</a></>}
                          {" "}· {source.observed_at ? new Date(source.observed_at).toLocaleDateString() : "date unavailable"}
                          {" "}· n={source.sample_size} {source.source_type ? `· ${source.source_type.replaceAll("_", " ")}` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="mt-5 grid gap-4 sm:grid-cols-2">
                  <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                    <h3 className="font-bold text-emerald-950">Skills raising your score</h3>
                    {selected.top_contributors.length ? (
                      <ul className="mt-2 space-y-2 text-sm text-emerald-900">
                        {selected.top_contributors.map((skill) => <li key={skill.competency_id}>{skill.skill_name} · level {skill.current_level}/{skill.required_level}</li>)}
                      </ul>
                    ) : <p className="mt-2 text-sm text-emerald-900">Build evidence for role competencies to raise the match.</p>}
                  </div>
                  <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                    <h3 className="font-bold text-amber-950">Skills lowering your score</h3>
                    {selected.largest_gaps.length ? (
                      <ul className="mt-2 space-y-2 text-sm text-amber-950">
                        {selected.largest_gaps.map((skill) => <li key={skill.competency_id}>{skill.skill_name} · gap {skill.gap_levels} level{skill.gap_levels === 1 ? "" : "s"}</li>)}
                      </ul>
                    ) : <p className="mt-2 text-sm text-amber-950">No gaps against the current role requirements.</p>}
                    <Link className="mt-3 inline-block text-sm font-semibold text-blue-700 underline" href="/job-gaps">Open job gap analysis</Link>
                  </div>
                </div>
                <div className="mt-5">
                  <h3 className="font-bold text-slate-950">Requirement detail and demand</h3>
                  <div className="mt-2 overflow-x-auto">
                    <table className="w-full min-w-[520px] text-left text-sm">
                      <thead><tr className="border-b text-slate-500"><th className="py-2">Skill</th><th>Passport</th><th>Importance</th><th>Demand</th></tr></thead>
                      <tbody>
                        {selected.competencies.map((skill) => (
                          <tr className="border-b border-slate-100" key={skill.competency_id}>
                            <td className="py-2 font-medium">{skill.skill_name}</td>
                            <td>{skill.current_level}/{skill.required_level}</td>
                            <td>{(skill.importance * 100).toFixed(0)}%</td>
                            <td>{skill.demand.status === "available" ? `${(skill.demand.score! * 100).toFixed(0)}% · n=${skill.demand.sample_size}` : "Not enough data"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                {selected.adjacent_roles.length > 0 && (
                  <div className="mt-5">
                    <h3 className="font-bold text-slate-950">Adjacent roles by shared skills</h3>
                    <p className="mt-1 text-xs text-slate-500">Similarity is based on overlap in the catalog competency requirements, not a career-transition prediction.</p>
                    <ul className="mt-2 space-y-1 text-sm text-slate-700">
                      {selected.adjacent_roles.map((role) => <li key={role.role_id}>{role.role_name} · {role.shared_skill_similarity}% shared-skill similarity · {role.fit_score}% fit</li>)}
                    </ul>
                  </div>
                )}
              </section>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
