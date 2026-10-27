"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type TargetRole = { role_id: string; role_name: string };
type Settings = {
  role_id: string;
  role_name: string;
  weekly_study_hours: number;
  budget_cents: number | null;
  strategy: "fastest" | "cheapest";
  target_finish_date: string | null;
  ready_threshold: number;
};
type Milestone = {
  id: string;
  step_order: number;
  course_version_id: string;
  course_title: string;
  duration_hours: number;
  price_cents: number;
  planned_start_date: string;
  planned_end_date: string;
  status: "planned" | "in_progress" | "completed";
};
type Roadmap = {
  id: string;
  version: number;
  role_id: string;
  role_name: string;
  strategy: "fastest" | "cheapest";
  target_finish_date: string | null;
  created_at: string;
  change_reason: string;
  weekly_study_hours: number;
  budget_cents: number | null;
  readiness: number;
  job_ready: boolean;
  job_ready_threshold: number;
  milestones: Milestone[];
  total_hours: number;
  total_cost_cents: number;
  estimated_finish_date: string;
  schedule_over_capacity: boolean;
  completed_milestones: number;
  next_best_action: { title: string; href: string } | null;
  remaining_gaps: Array<{
    skill_name: string;
    current_level: number;
    required_level: number;
  }>;
};
type RoadmapVersion = {
  version: number;
  strategy: "fastest" | "cheapest";
  target_finish_date: string | null;
  change_reason: string;
  created_at: string;
};
type RoadmapData = {
  roadmap: Roadmap | null;
  settings: Settings | null;
  versions: RoadmapVersion[];
  comparison?: {
    previous_version: number;
    reason: string;
    added_courses: string[];
    removed_courses: string[];
  } | null;
  suggested_adjustment?: string | null;
  replan_available?: boolean;
};

async function request<T>(
  token: string,
  path: string,
  options: RequestInit = {},
): Promise<T> {
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
    throw new Error(`Could not reach the API at ${API_URL}. Start the stack with docker compose up --build.`);
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : `Request failed (${response.status})`,
    );
  }
  return (await response.json()) as T;
}

function formatPrice(cents: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

function formatDate(value: string) {
  return new Date(`${value.slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function RoadmapPage() {
  const [token, setToken] = useState("");
  const [roles, setRoles] = useState<TargetRole[]>([]);
  const [data, setData] = useState<RoadmapData | null>(null);
  const [roleId, setRoleId] = useState("");
  const [weeklyHours, setWeeklyHours] = useState("5");
  const [budget, setBudget] = useState("");
  const [strategy, setStrategy] = useState<"fastest" | "cheapest">("fastest");
  const [finishDate, setFinishDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      const accessToken = window.sessionStorage.getItem("capacity-connect-token");
      if (!accessToken) {
        setError("Sign in with your trainee account to create a roadmap.");
        setLoading(false);
        return;
      }
      setToken(accessToken);
      try {
        const [progress, roadmapData] = await Promise.all([
          request<{ roles: TargetRole[] }>(accessToken, "/api/v1/passport/progress"),
          request<RoadmapData>(accessToken, "/api/v1/learning/roadmap"),
        ]);
        let currentData = roadmapData;
        if (roadmapData.roadmap) {
          currentData = await request<RoadmapData>(
            accessToken,
            "/api/v1/learning/roadmap/refresh",
            { method: "POST" },
          );
        }
        if (!active) return;
        setRoles(progress.roles);
        setData(currentData);
        const savedSettings = currentData.settings;
        const currentRoadmap = currentData.roadmap;
        setRoleId(
          savedSettings?.role_id ??
            currentRoadmap?.role_id ??
            progress.roles[0]?.role_id ??
            "",
        );
        if (savedSettings) {
          setWeeklyHours(String(savedSettings.weekly_study_hours));
          setBudget(
            savedSettings.budget_cents === null
              ? ""
              : String(savedSettings.budget_cents / 100),
          );
          setStrategy(savedSettings.strategy);
          setFinishDate(savedSettings.target_finish_date ?? "");
        }
      } catch (loadError) {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "Could not load your roadmap.");
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  async function saveRoadmap(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const weeklyStudyHours = Number(weeklyHours);
      const budgetCents =
        budget.trim() === "" ? null : Math.round(Number(budget) * 100);
      if (!Number.isFinite(weeklyStudyHours) || weeklyStudyHours < 0.5 || weeklyStudyHours > 80) {
        throw new Error("Weekly study time must be between 0.5 and 80 hours.");
      }
      if (budgetCents !== null && (!Number.isFinite(budgetCents) || budgetCents < 0)) {
        throw new Error("Enter a valid budget or leave it blank for no budget limit.");
      }
      const saved = await request<RoadmapData>(token, "/api/v1/learning/roadmap", {
        method: "PUT",
        body: JSON.stringify({
          role_id: roleId,
          weekly_study_hours: weeklyStudyHours,
          budget_cents: budgetCents,
          strategy,
          target_finish_date: finishDate || null,
        }),
      });
      setData(saved);
      setNotice(
        saved.suggested_adjustment ??
          `Roadmap v${saved.roadmap?.version ?? 1} saved.`,
      );
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save your roadmap.");
    } finally {
      setSaving(false);
    }
  }

  async function refreshRoadmap() {
    setRefreshing(true);
    setError("");
    setNotice("");
    try {
      const refreshed = await request<RoadmapData>(
        token,
        "/api/v1/learning/roadmap/refresh",
        { method: "POST" },
      );
      setData(refreshed);
      setNotice(
        refreshed.roadmap
          ? `Roadmap is current at version ${refreshed.roadmap.version}.`
          : "Create a roadmap to get started.",
      );
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "Could not refresh your roadmap.");
    } finally {
      setRefreshing(false);
    }
  }

  async function downloadRoadmap() {
    setDownloading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/learning/roadmap/export.pdf`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => ({}))) as { detail?: unknown };
        throw new Error(
          typeof payload.detail === "string"
            ? payload.detail
            : `PDF export failed (${response.status})`,
        );
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "capacity-connect-roadmap.pdf";
      link.click();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : "Could not export your roadmap.");
    } finally {
      setDownloading(false);
    }
  }

  const roadmap = data?.roadmap;

  return (
    <main className="min-h-screen bg-[#0b0f19] px-4 py-8 sm:px-6 lg:px-8 text-slate-100 antialiased selection:bg-blue-500/30">
      <section className="mx-auto max-w-7xl">
        {/* Career Pathway Stepper */}
        <div className="mb-6 rounded-3xl border border-white/10 bg-slate-900/60 p-5 backdrop-blur-xl shadow-xl">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <span className="text-[11px] font-bold uppercase tracking-wider text-purple-400">Step 3 of Career Journey</span>
              <h1 className="mt-1 text-2xl font-black text-white sm:text-3xl">Personalized Learning Roadmap</h1>
              <p className="mt-1 max-w-2xl text-xs text-slate-400 sm:text-sm">
                Optimized study sequence targeting your priority competency gaps, modeled around your available hours and budget.
              </p>
            </div>
            {roadmap && (
              <div className="flex flex-wrap gap-2">
                <button
                  className="rounded-xl border border-white/10 bg-slate-800/80 px-4 py-2 text-xs font-semibold text-slate-200 backdrop-blur-md transition hover:bg-slate-700 disabled:opacity-50"
                  disabled={refreshing || !data?.replan_available}
                  onClick={() => void refreshRoadmap()}
                  type="button"
                >
                  {refreshing ? "Checking…" : "Check for updates"}
                </button>
                <button
                  className="rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-blue-500/20 transition hover:brightness-110 disabled:opacity-50"
                  disabled={downloading}
                  onClick={() => void downloadRoadmap()}
                  type="button"
                >
                  {downloading ? "Preparing PDF…" : "Download PDF"}
                </button>
              </div>
            )}
          </div>
          
          {/* Stepper Navigation Bar */}
          <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-6 text-center text-xs">
            <Link href="/" className="rounded-xl border border-white/5 bg-slate-800/40 p-2.5 text-slate-400 hover:text-white transition">
              1. Skill Passport
            </Link>
            <Link href="/profile" className="rounded-xl border border-white/5 bg-slate-800/40 p-2.5 text-slate-400 hover:text-white transition">
              2. Skill Gaps
            </Link>
            <div className="rounded-xl border border-purple-500/40 bg-purple-500/10 p-2.5 font-bold text-purple-300 shadow-sm">
              3. Roadmap (Active)
            </div>
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

        {(error || notice) && (
          <p
            className={`mb-6 rounded-2xl p-4 text-sm font-medium border ${error ? "border-rose-500/30 bg-rose-950/40 text-rose-300" : "border-emerald-500/30 bg-emerald-950/40 text-emerald-300"}`}
            role={error ? "alert" : "status"}
          >
            {error || notice}
          </p>
        )}
        {loading && (
          <div className="mt-8 flex items-center justify-center py-12 text-slate-400">
            <div className="h-7 w-7 animate-spin rounded-full border-2 border-purple-500 border-t-transparent" />
            <span className="ml-3 text-sm font-semibold">Building your optimized career roadmap…</span>
          </div>
        )}

        {!loading && (
          <div className="mt-7 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.9fr)]">
            <section className="rounded-3xl border border-white/10 bg-slate-900/60 p-6 backdrop-blur-xl shadow-xl">
              <h2 className="text-xl font-bold text-white">
                {roadmap ? "Roadmap settings" : "Plan your learning"}
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                Replanning stays stable unless a milestone completes, your role changes, or the finish date moves by more than 15%.
              </p>

              {roles.length === 0 ? (
                <div className="mt-5 rounded-xl bg-amber-50 p-4 text-sm text-amber-950">
                  <p className="font-semibold">Choose a target role in your Skill Passport first.</p>
                  <Link className="mt-2 inline-block font-semibold underline" href="/">Open Skill Passport</Link>
                </div>
              ) : (
                <form className="mt-5 space-y-4" onSubmit={saveRoadmap}>
                  <label className="block text-sm font-semibold text-slate-800">
                    Target role
                    <select
                      className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                      onChange={(event) => setRoleId(event.target.value)}
                      required
                      value={roleId}
                    >
                      {roles.map((role) => (
                        <option key={role.role_id} value={role.role_id}>{role.role_name}</option>
                      ))}
                    </select>
                  </label>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="block text-sm font-semibold text-slate-800">
                      Study hours per week
                      <input
                        className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                        max="80"
                        min="0.5"
                        onChange={(event) => setWeeklyHours(event.target.value)}
                        required
                        step="0.5"
                        type="number"
                        value={weeklyHours}
                      />
                    </label>
                    <label className="block text-sm font-semibold text-slate-800">
                      Optional total budget (INR)
                      <input
                        className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                        min="0"
                        onChange={(event) => setBudget(event.target.value)}
                        placeholder="No limit"
                        step="1"
                        type="number"
                        value={budget}
                      />
                    </label>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="block text-sm font-semibold text-slate-800">
                      Planning strategy
                      <select
                        className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                        onChange={(event) => setStrategy(event.target.value as "fastest" | "cheapest")}
                        value={strategy}
                      >
                        <option value="fastest">Fastest — minimize study time</option>
                        <option value="cheapest">Cheapest — minimize cost</option>
                      </select>
                    </label>
                    <label className="block text-sm font-semibold text-slate-800">
                      Target finish date (optional)
                      <input
                        className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                        min={new Date().toISOString().slice(0, 10)}
                        onChange={(event) => setFinishDate(event.target.value)}
                        type="date"
                        value={finishDate}
                      />
                    </label>
                  </div>
                  <button
                    className="rounded-lg bg-blue-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50"
                    disabled={saving || roles.length === 0}
                    type="submit"
                  >
                    {saving ? "Saving…" : roadmap ? "Save settings" : "Create roadmap"}
                  </button>
                </form>
              )}
            </section>

            {roadmap ? (
              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-blue-700">{roadmap.role_name}</p>
                    <h2 className="mt-1 text-xl font-bold">Version {roadmap.version}</h2>
                  </div>
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold capitalize text-slate-700">
                    {roadmap.strategy}
                  </span>
                </div>
                <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-xl bg-slate-50 p-3">
                    <p className="text-slate-500">Role readiness</p>
                    <p className="mt-1 text-2xl font-bold">{roadmap.readiness.toFixed(1)}%</p>
                  </div>
                  <div className="rounded-xl bg-slate-50 p-3">
                    <p className="text-slate-500">Estimated finish</p>
                    <p className="mt-1 font-bold">{formatDate(roadmap.estimated_finish_date)}</p>
                  </div>
                  <div className="rounded-xl bg-slate-50 p-3">
                    <p className="text-slate-500">Planned study</p>
                    <p className="mt-1 font-bold">{roadmap.total_hours} hours</p>
                  </div>
                  <div className="rounded-xl bg-slate-50 p-3">
                    <p className="text-slate-500">Course total</p>
                    <p className="mt-1 font-bold">{formatPrice(roadmap.total_cost_cents)}</p>
                  </div>
                </div>
                <div className={`mt-4 rounded-xl p-3 text-sm ${roadmap.job_ready ? "bg-emerald-50 text-emerald-900" : "bg-blue-50 text-blue-950"}`}>
                  {roadmap.job_ready
                    ? `You have reached the ${roadmap.job_ready_threshold}% job-ready marker. Job access remains your choice.`
                    : `The ${roadmap.job_ready_threshold}% marker is a progress signal only; it does not block job access.`}
                </div>
                {roadmap.schedule_over_capacity && (
                  <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-950">
                    This target date is earlier than your weekly study schedule can support. Increase weekly hours or move the date.
                  </p>
                )}
                {roadmap.next_best_action && (
                  <Link className="mt-4 inline-flex font-semibold text-blue-700 hover:underline" href={roadmap.next_best_action.href}>
                    {roadmap.next_best_action.title} →
                  </Link>
                )}
              </section>
            ) : (
              <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-6">
                <h2 className="text-lg font-bold">Your plan will appear here</h2>
                <p className="mt-2 text-sm text-slate-600">
                  Select one of your Passport target roles and set a time or budget preference to begin.
                </p>
              </section>
            )}
          </div>
        )}

        {!loading && roadmap && data && (
          <>
            {data.suggested_adjustment && (
              <section className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-5" role="status">
                <h2 className="font-bold text-amber-950">Suggested adjustment</h2>
                <p className="mt-1 text-sm text-amber-900">{data.suggested_adjustment}</p>
              </section>
            )}
            {data.comparison && (
              <section className="mt-6 rounded-2xl border border-blue-200 bg-blue-50 p-5">
                <h2 className="font-bold text-blue-950">
                  What changed from version {data.comparison.previous_version}
                </h2>
                <p className="mt-1 text-sm text-blue-900">{data.comparison.reason}</p>
                <div className="mt-3 grid gap-4 sm:grid-cols-2">
                  <div>
                    <h3 className="text-sm font-bold text-emerald-900">Added</h3>
                    {data.comparison.added_courses.length ? (
                      <ul className="mt-1 list-inside list-disc text-sm">
                        {data.comparison.added_courses.map((course) => <li key={course}>{course}</li>)}
                      </ul>
                    ) : <p className="mt-1 text-sm">No courses added.</p>}
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-700">Removed</h3>
                    {data.comparison.removed_courses.length ? (
                      <ul className="mt-1 list-inside list-disc text-sm">
                        {data.comparison.removed_courses.map((course) => <li key={course}>{course}</li>)}
                      </ul>
                    ) : <p className="mt-1 text-sm">No courses removed.</p>}
                  </div>
                </div>
              </section>
            )}

            <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-xl font-bold">Course milestones</h2>
                  <p className="mt-1 text-sm text-slate-600">
                    {roadmap.completed_milestones} of {roadmap.milestones.length} completed · ordered by prerequisites
                  </p>
                </div>
                <Link className="font-semibold text-blue-700 hover:underline" href="/learning">Browse approved courses</Link>
              </div>
              {roadmap.milestones.length ? (
                <ol className="mt-5 space-y-3">
                  {roadmap.milestones.map((milestone) => (
                    <li className="flex gap-4 rounded-xl border border-slate-200 p-4" key={milestone.id}>
                      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${milestone.status === "completed" ? "bg-emerald-100 text-emerald-900" : milestone.status === "in_progress" ? "bg-blue-100 text-blue-900" : "bg-slate-100 text-slate-700"}`}>
                        {milestone.status === "completed" ? "✓" : milestone.step_order}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <h3 className="font-bold text-slate-950">{milestone.course_title}</h3>
                          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                            {milestone.status.replace("_", " ")}
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-slate-600">
                          {formatDate(milestone.planned_start_date)} – {formatDate(milestone.planned_end_date)}
                          {" · "}{milestone.duration_hours} hours · {formatPrice(milestone.price_cents)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-700">
                  There are no approved courses that currently cover your open role gaps. Your role remains accessible; review your profile or course picks for other options.
                </p>
              )}
            </section>

            <div className="mt-6 grid gap-6 lg:grid-cols-2">
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <h2 className="text-lg font-bold">Open skill gaps</h2>
                {roadmap.remaining_gaps.length ? (
                  <ul className="mt-3 space-y-2 text-sm">
                    {roadmap.remaining_gaps.map((gap) => (
                      <li className="flex justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2" key={gap.skill_name}>
                        <span>{gap.skill_name}</span>
                        <span className="shrink-0 text-slate-600">Level {gap.current_level}/{gap.required_level}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-sm text-emerald-800">No open competency gaps for this role.</p>
                )}
              </section>
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <h2 className="text-lg font-bold">Version history</h2>
                <ol className="mt-3 space-y-3">
                  {data.versions.map((version) => (
                    <li className="border-l-2 border-blue-200 pl-3" key={version.version}>
                      <p className="font-semibold">Version {version.version} · {version.strategy}</p>
                      <p className="text-sm text-slate-600">{version.change_reason} · {formatDate(version.created_at)}</p>
                    </li>
                  ))}
                </ol>
              </section>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
