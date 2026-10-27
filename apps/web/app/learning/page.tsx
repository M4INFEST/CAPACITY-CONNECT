"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Skill = { skill_id: string; skill_name: string };
type Role = { role_id: string; name: string };
type Trainer = { trainer_id: string; trainer: string };
type Preferences = {
  weekly_study_hours: number | null;
  budget_cents: number | null;
  learning_format: "self_paced" | "instructor_led" | "blended";
  prioritize_paid: boolean;
};
type CourseSkill = {
  competency_id: string;
  skill_name: string;
  level_taught: number;
};
type Reason = {
  role_id: string;
  role_name: string;
  competency_id: string;
  skill_name: string;
  levels_closed: number;
  required_gap: number;
  critical: boolean;
  importance: number;
  level_taught: number;
};
type Course = {
  course_version_id: string;
  course_id: string;
  version: number;
  title: string;
  description: string | null;
  duration_hours: number | null;
  price_cents: number;
  price_label: string;
  delivery_format: Preferences["learning_format"];
  rating: number;
  review_count: number;
  trainer_id: string;
  trainer: string;
  updated_at: string;
  skills: CourseSkill[];
  gap_closed_per_hour: number;
  reasons: Reason[];
  reason_summary: string;
  unmet_prerequisites: Array<{
    skill_id: string;
    skill_name: string;
    minimum_level: number;
    current_level: number;
  }>;
  prerequisites?: Array<{
    skill_id: string;
    skill_name: string;
    minimum_level: number;
    current_level: number;
    is_met: boolean;
  }>;
  reviews?: Array<{
    rating: number;
    review_text: string | null;
    created_at: string;
  }>;
  wishlist: boolean;
  syllabus: string[];
  learning_outcomes: string[];
  target_roles?: Role[];
  pretest_available_during_enrollment?: boolean;
};
type Enrollment = {
  enrollment_id: string;
  course_title: string;
  status: string;
  funding_type: "free" | "sponsored";
};
type ExternalCourse = {
  id: string;
  title: string;
  description: string | null;
  provider: string;
  provider_domain: string;
  course_url: string;
  duration_hours: number | null;
  price_cents: number;
  difficulty: number | null;
  language: string;
  skills: CourseSkill[];
  external: true;
  credit_policy: string;
};
type ExternalCompletion = {
  id: string;
  external_course_id: string;
  course_title: string;
  provider: string;
  certificate_id: string;
  status: "pending" | "verified" | "rejected";
  review_reason: string | null;
  submitted_at: string;
  reviewed_at: string | null;
};

async function api<T>(
  path: string,
  token: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...options.headers,
      },
    });
  } catch {
    throw new Error(
      `Could not reach the API at ${API_URL}. Start Docker Desktop, then run "docker compose up --build" from the capacity-connect folder.`,
    );
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: unknown };
    const detail = payload.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "message" in detail
          ? String(detail.message)
          : `Request failed (${response.status})`;
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function formatPrice(cents: number) {
  return cents === 0
    ? "Free"
    : new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        maximumFractionDigits: 2,
      }).format(cents / 100);
}

export default function LearningPage() {
  const [token, setToken] = useState("");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [preferences, setPreferences] = useState<Preferences>({
    weekly_study_hours: 5,
    budget_cents: null,
    learning_format: "self_paced",
    prioritize_paid: false,
  });
  const [budgetRupees, setBudgetRupees] = useState("");
  const [courses, setCourses] = useState<Course[]>([]);
  const [trainerOptions, setTrainerOptions] = useState<Trainer[]>([]);
  const [externalCourses, setExternalCourses] = useState<ExternalCourse[]>([]);
  const [externalCompletions, setExternalCompletions] = useState<ExternalCompletion[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingPreferences, setSavingPreferences] = useState(false);
  const [detail, setDetail] = useState<Course | null>(null);
  const [enrollmentCourse, setEnrollmentCourse] = useState<Course | null>(null);
  const [sponsorshipCode, setSponsorshipCode] = useState("");
  const [acknowledgePrerequisites, setAcknowledgePrerequisites] = useState(false);
  const [enrolling, setEnrolling] = useState(false);
  const [completionCourse, setCompletionCourse] = useState<ExternalCourse | null>(null);
  const [certificateId, setCertificateId] = useState("");
  const [certificateUrl, setCertificateUrl] = useState("");
  const [submittingCertificate, setSubmittingCertificate] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Course[]>([]);
  const [wishlist, setWishlist] = useState<Course[]>([]);

  const [filterSkill, setFilterSkill] = useState("");
  const [filterLevel, setFilterLevel] = useState("");
  const [filterMaxPrice, setFilterMaxPrice] = useState("");
  const [filterMinDuration, setFilterMinDuration] = useState("");
  const [filterMaxDuration, setFilterMaxDuration] = useState("");
  const [filterTrainer, setFilterTrainer] = useState("");
  const [filterRating, setFilterRating] = useState("");
  const [search, setSearch] = useState("");
  const [filterKey, setFilterKey] = useState(0);

  const selectedSkillName = useMemo(
    () => skills.find((skill) => skill.skill_id === filterSkill)?.skill_name ?? "",
    [filterSkill, skills],
  );

  const loadData = useCallback(async (accessToken: string) => {
    setLoading(true);
    setError("");
    try {
      const [
        taxonomy,
        roleResponse,
        preferenceResponse,
        recommendationResponse,
        externalResponse,
        wishlistResponse,
        completionResponse,
      ] = await Promise.all([
        api<Skill[]>("/api/v1/passport/taxonomy", accessToken),
        api<Role[]>("/api/v1/passport/roles", accessToken),
        api<Preferences>("/api/v1/learning/preferences", accessToken),
        api<{ recommendations: Course[] }>("/api/v1/courses/recommendations", accessToken),
        api<ExternalCourse[]>("/api/v1/external-courses", accessToken),
        api<Course[]>("/api/v1/courses/wishlist", accessToken),
        api<ExternalCompletion[]>("/api/v1/external-course-completions", accessToken),
      ]);
      setSkills(taxonomy);
      setRoles(roleResponse);
      setPreferences({
        ...preferenceResponse,
        weekly_study_hours: preferenceResponse.weekly_study_hours ?? 5,
      });
      setBudgetRupees(
        preferenceResponse.budget_cents === null
          ? ""
          : String(preferenceResponse.budget_cents / 100),
      );
      setCourses(recommendationResponse.recommendations);
      setTrainerOptions(
        Array.from(
          new Map(
            recommendationResponse.recommendations.map((course) => [
              course.trainer_id,
              { trainer_id: course.trainer_id, trainer: course.trainer },
            ]),
          ).values(),
        ),
      );
      setExternalCourses(externalResponse);
      setWishlist(wishlistResponse);
      setExternalCompletions(completionResponse);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not load course picks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const savedToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!savedToken) {
      setError("Sign in to your trainee account from the Skill Passport first.");
      setLoading(false);
      return;
    }
    setToken(savedToken);
    void loadData(savedToken);
  }, [loadData]);

  useEffect(() => {
    if (!token) return;
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void refreshRecommendations();
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => document.removeEventListener("visibilitychange", refreshWhenVisible);
  }, [token, preferences.budget_cents]);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams();
      if (filterSkill) params.set("skill_id", filterSkill);
      if (filterLevel) params.set("level", filterLevel);
      if (filterMaxPrice) params.set("max_price_cents", String(Math.round(Number(filterMaxPrice) * 100)));
      if (filterMinDuration) params.set("min_duration_hours", filterMinDuration);
      if (filterMaxDuration) params.set("max_duration_hours", filterMaxDuration);
      if (filterTrainer.trim()) params.set("trainer_id", filterTrainer.trim());
      if (filterRating) params.set("min_rating", filterRating);
      if (search.trim()) params.set("search", search.trim());
      const query = params.toString();
      api<{ recommendations: Course[] }>(
        `/api/v1/courses/recommendations${query ? `?${query}` : ""}`,
        token,
        { signal: controller.signal },
      )
        .then((result) => setCourses(result.recommendations))
        .catch((requestError: unknown) => {
          if (requestError instanceof DOMException && requestError.name === "AbortError") return;
          setError(requestError instanceof Error ? requestError.message : "Could not filter courses");
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [
    filterKey,
    filterLevel,
    filterMaxDuration,
    filterMaxPrice,
    filterMinDuration,
    filterRating,
    filterSkill,
    filterTrainer,
    search,
    token,
  ]);

  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSavingPreferences(true);
    setError("");
    setNotice("");
    try {
      const budget = budgetRupees.trim() === "" ? null : Math.round(Number(budgetRupees) * 100);
      if (budget !== null && (!Number.isFinite(budget) || budget < 0)) {
        throw new Error("Enter a valid budget in rupees.");
      }
      const saved = await api<Preferences>("/api/v1/learning/preferences", token, {
        method: "PUT",
        body: JSON.stringify({
          weekly_study_hours: preferences.weekly_study_hours,
          budget_cents: budget,
          learning_format: preferences.learning_format,
          prioritize_paid: preferences.prioritize_paid,
        }),
      });
      setPreferences(saved);
      setNotice("Learning goals saved. Recommendations refreshed.");
      setFilterKey((value) => value + 1);
      await loadData(token);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not save learning goals");
    } finally {
      setSavingPreferences(false);
    }
  }

  async function refreshRecommendations() {
    if (!token) return;
    try {
      const query = new URLSearchParams();
      if (preferences.budget_cents !== null) {
        query.set("max_price_cents", String(preferences.budget_cents));
      }
      const result = await api<{ recommendations: Course[] }>(
        `/api/v1/courses/recommendations${query.size ? `?${query}` : ""}`,
        token,
      );
      setCourses(result.recommendations);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not refresh recommendations");
    }
  }

  async function openCourse(course: Course) {
    setError("");
    try {
      const result = await api<Course>(
        `/api/v1/course-versions/${course.course_version_id}`,
        token,
      );
      setDetail(result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not load course details");
    }
  }

  async function toggleWishlist(course: Course) {
    setError("");
    try {
      if (course.wishlist) {
        await api(`/api/v1/courses/wishlist/${course.course_version_id}`, token, {
          method: "DELETE",
        });
        setNotice("Course removed from wishlist.");
      } else {
        await api("/api/v1/courses/wishlist", token, {
          method: "PUT",
          body: JSON.stringify({ course_version_id: course.course_version_id }),
        });
        setNotice("Course saved to your wishlist.");
      }
      setDetail((current) =>
        current?.course_version_id === course.course_version_id
          ? { ...current, wishlist: !course.wishlist }
          : current,
      );
      await loadData(token);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not update wishlist");
    }
  }

  function toggleCompare(course: Course) {
    setCompareIds((current) => {
      if (current.includes(course.course_version_id)) {
        return current.filter((id) => id !== course.course_version_id);
      }
      if (current.length >= 3) return current;
      return [...current, course.course_version_id];
    });
  }

  async function compareSelected() {
    setError("");
    try {
      const result = await api<{ courses: Course[] }>("/api/v1/courses/compare", token, {
        method: "POST",
        body: JSON.stringify({ course_version_ids: compareIds }),
      });
      setComparison(result.courses);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not compare courses");
    }
  }

  async function submitCertificate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!completionCourse) return;
    setSubmittingCertificate(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ message: string }>(
        `/api/v1/external-courses/${completionCourse.id}/completion`,
        token,
        {
          method: "POST",
          body: JSON.stringify({
            certificate_id: certificateId,
            certificate_url: certificateUrl,
          }),
        },
      );
      setNotice(result.message);
      setExternalCompletions(
        await api<ExternalCompletion[]>("/api/v1/external-course-completions", token),
      );
      setCompletionCourse(null);
      setCertificateId("");
      setCertificateUrl("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not submit certificate");
    } finally {
      setSubmittingCertificate(false);
    }
  }

  async function enrollInCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!enrollmentCourse) return;
    setEnrolling(true);
    setError("");
    try {
      const enrollment = await api<Enrollment>(
        `/api/v1/courses/${enrollmentCourse.course_version_id}/enroll`,
        token,
        {
          method: "POST",
          body: JSON.stringify({
            ...(sponsorshipCode.trim() ? { sponsorship_code: sponsorshipCode.trim() } : {}),
            acknowledge_prerequisites: acknowledgePrerequisites,
          }),
        },
      );
      window.location.assign(`/my-learning?enrollment=${enrollment.enrollment_id}`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not enroll in this course");
      setEnrolling(false);
    }
  }

  async function syncLiveCourses() {
    if (!token) return;
    setLoading(true);
    setError("");
    setNotice("Fetching real live courses from Coursera Open Catalog...");
    try {
      const res = await api<{ status: string; total_processed: number; ingested_count: number; updated_count: number }>(
        "/api/v1/courses/sync-live?limit=15",
        token,
        { method: "POST" },
      );
      setNotice(`Coursera live sync complete: ${res.total_processed} real courses updated in database.`);
      await loadData(token);
    } catch (syncErr) {
      setError(syncErr instanceof Error ? syncErr.message : "Could not sync live courses.");
    } finally {
      setLoading(false);
    }
  }

  function resetFilters() {
    setFilterSkill("");
    setFilterLevel("");
    setFilterMaxPrice("");
    setFilterMinDuration("");
    setFilterMaxDuration("");
    setFilterTrainer("");
    setFilterRating("");
    setSearch("");
    setFilterKey((value) => value + 1);
  }

  function signOut() {
    window.sessionStorage.removeItem("capacity-connect-token");
    window.location.assign("/");
  }

  if (!token && loading) {
    return <main className="min-h-screen p-10 text-slate-600">Loading course picks…</main>;
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-bold uppercase tracking-[0.18em] text-blue-700">
              Capacity Connect · Stages 3–4
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">AI course picks</h1>
            <p className="mt-2 max-w-2xl text-slate-600">
              Transparent recommendations ranked by weighted skill-gap closure per study hour.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="rounded-xl border border-cyan-500/40 bg-cyan-600 px-4 py-2 font-semibold text-white shadow-sm hover:bg-cyan-500 disabled:opacity-50"
              disabled={loading}
              onClick={() => void syncLiveCourses()}
              type="button"
            >
              🔄 Sync Live Coursera Courses
            </button>
            <Link className="rounded-xl bg-blue-700 px-4 py-2 font-semibold text-white" href="/my-learning">
              My learning
            </Link>
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/profile">
              Progress & gaps
            </Link>
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/roadmap">
              Learning roadmap
            </Link>
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/role-matches">
              Role matches
            </Link>
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/jobs">
              Job explorer
            </Link>
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/">
              Skill Passport
            </Link>
            <button className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" onClick={signOut} type="button">
              Sign out
            </button>
          </div>
        </header>

        {(error || notice) && (
          <div
            className={`mt-5 rounded-xl p-3 text-sm ${error ? "bg-rose-50 text-rose-700" : "bg-emerald-50 text-emerald-800"}`}
            role={error ? "alert" : "status"}
          >
            {error || notice}
          </div>
        )}

        {token && (
          <>
            <section className="mt-6 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-xl font-bold">Learning goals</h2>
                  <p className="mt-1 text-sm text-slate-600">
                    Recommendations refresh when goals, target roles, or passport skills change.
                  </p>
                </div>
                <p className="text-xs text-slate-500">
                  Target roles: {roles.length ? roles.map((role) => role.name).join(", ") : "none selected"}
                </p>
              </div>
              <form className="mt-5 grid gap-4 md:grid-cols-4" onSubmit={savePreferences}>
                <label className="text-sm font-medium">
                  Weekly study hours
                  <input
                    className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                    max="80"
                    min="0.5"
                    onChange={(event) =>
                      setPreferences({ ...preferences, weekly_study_hours: Number(event.target.value) })
                    }
                    required
                    step="0.5"
                    type="number"
                    value={preferences.weekly_study_hours ?? 5}
                  />
                </label>
                <label className="text-sm font-medium">
                  Maximum budget (₹)
                  <input
                    className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                    min="0"
                    onChange={(event) => setBudgetRupees(event.target.value)}
                    placeholder="No limit"
                    step="1"
                    type="number"
                    value={budgetRupees}
                  />
                </label>
                <label className="text-sm font-medium">
                  Learning format
                  <select
                    className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                    onChange={(event) =>
                      setPreferences({
                        ...preferences,
                        learning_format: event.target.value as Preferences["learning_format"],
                      })
                    }
                    value={preferences.learning_format}
                  >
                    <option value="self_paced">Self-paced</option>
                    <option value="instructor_led">Instructor-led</option>
                    <option value="blended">Blended</option>
                  </select>
                </label>
                <div className="flex flex-col justify-end gap-3">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      checked={preferences.prioritize_paid}
                      onChange={(event) =>
                        setPreferences({ ...preferences, prioritize_paid: event.target.checked })
                      }
                      type="checkbox"
                    />
                    Prioritize paid courses
                  </label>
                  <button
                    className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white disabled:opacity-50"
                    disabled={savingPreferences}
                    type="submit"
                  >
                    {savingPreferences ? "Saving…" : "Save goals"}
                  </button>
                </div>
              </form>
            </section>

            <div className="mt-6 grid gap-6 lg:grid-cols-[260px_1fr]">
              <aside className="h-fit rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <h2 className="font-bold">Filter courses</h2>
                  <button className="text-xs font-semibold text-blue-700" onClick={resetFilters} type="button">
                    Clear
                  </button>
                </div>
                <div className="mt-4 space-y-3">
                  <label className="block text-sm font-medium">
                    Search
                    <input
                      className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Title, description, skill"
                      value={search}
                    />
                  </label>
                  <label className="block text-sm font-medium">
                    Skill
                    <select
                      className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                      onChange={(event) => setFilterSkill(event.target.value)}
                      value={filterSkill}
                    >
                      <option value="">All skills</option>
                      {skills.map((skill) => (
                        <option key={skill.skill_id} value={skill.skill_id}>{skill.skill_name}</option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-sm font-medium">
                    Course level
                    <select
                      className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                      onChange={(event) => setFilterLevel(event.target.value)}
                      value={filterLevel}
                    >
                      <option value="">All levels</option>
                      {[1, 2, 3, 4, 5].map((level) => (
                        <option key={level} value={level}>Level {level}</option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-sm font-medium">
                    Maximum price (₹)
                    <input
                      className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                      min="0"
                      onChange={(event) => setFilterMaxPrice(event.target.value)}
                      type="number"
                      value={filterMaxPrice}
                    />
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-sm font-medium">
                      Min hours
                      <input
                        className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2"
                        min="0"
                        onChange={(event) => setFilterMinDuration(event.target.value)}
                        type="number"
                        value={filterMinDuration}
                      />
                    </label>
                    <label className="text-sm font-medium">
                      Max hours
                      <input
                        className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2"
                        min="0"
                        onChange={(event) => setFilterMaxDuration(event.target.value)}
                        type="number"
                        value={filterMaxDuration}
                      />
                    </label>
                  </div>
                  <label className="block text-sm font-medium">
                    Minimum rating
                    <select
                      className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                      onChange={(event) => setFilterRating(event.target.value)}
                      value={filterRating}
                    >
                      <option value="">Any rating</option>
                      {[3, 3.5, 4, 4.5].map((rating) => (
                        <option key={rating} value={rating}>{rating}+ stars</option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-sm font-medium">
                    Trainer
                    <select
                      className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
                      onChange={(event) => setFilterTrainer(event.target.value)}
                      value={filterTrainer}
                    >
                      <option value="">All trainers</option>
                      {trainerOptions.map((trainer) => (
                        <option key={trainer.trainer_id} value={trainer.trainer_id}>{trainer.trainer}</option>
                      ))}
                    </select>
                  </label>
                </div>
              </aside>

              <section>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-xl font-bold">Recommended courses</h2>
                    <p className="text-sm text-slate-600">
                      {courses.length} approved published version(s) · free and low-cost first
                    </p>
                  </div>
                  {compareIds.length > 0 && (
                    <button
                      className="rounded-xl border border-blue-700 px-4 py-2 text-sm font-semibold text-blue-800 disabled:opacity-50"
                      disabled={compareIds.length < 2}
                      onClick={compareSelected}
                      type="button"
                    >
                      Compare ({compareIds.length}/3)
                    </button>
                  )}
                </div>

                {loading ? (
                  <p className="mt-5 text-slate-600">Loading approved course picks…</p>
                ) : courses.length === 0 ? (
                  <p className="mt-5 rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-slate-600">
                    No eligible course versions match the current filters. Recommendations include only published,
                    admin-approved courses that address a current target-role gap. Try clearing filters or revisit when
                    more approved courses are available.
                  </p>
                ) : (
                  <div className="mt-4 space-y-4">
                    {courses.map((course) => (
                      <article className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm" key={course.course_version_id}>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <button
                              className="text-left text-lg font-bold text-blue-800 hover:underline"
                              onClick={() => void openCourse(course)}
                              type="button"
                            >
                              {course.title}
                            </button>
                            <p className="mt-1 text-sm text-slate-600">
                              Version {course.version} · {course.delivery_format.replace("_", " ")} · Updated{" "}
                              {new Date(course.updated_at).toLocaleDateString()}
                            </p>
                          </div>
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              checked={compareIds.includes(course.course_version_id)}
                              disabled={
                                compareIds.length >= 3 &&
                                !compareIds.includes(course.course_version_id)
                              }
                              onChange={() => toggleCompare(course)}
                              type="checkbox"
                            />
                            Compare
                          </label>
                        </div>
                        <p className="mt-3 text-sm text-slate-700">{course.description}</p>
                        <p className="mt-3 rounded-xl bg-blue-50 p-3 text-sm font-medium text-blue-950">
                          {course.reason_summary}
                        </p>
                        {course.reasons.length > 0 && (
                          <ul className="mt-3 flex flex-wrap gap-2">
                            {course.reasons.map((reason) => (
                              <li
                                className={`rounded-full px-3 py-1 text-xs ${
                                  reason.critical ? "bg-rose-100 text-rose-900" : "bg-slate-100 text-slate-700"
                                }`}
                                key={`${reason.role_id}-${reason.competency_id}`}
                              >
                                {reason.critical ? "Critical gap: " : "Gap: "}{reason.skill_name} ·{" "}
                                {reason.levels_closed} level(s)
                              </li>
                            ))}
                          </ul>
                        )}
                        {course.unmet_prerequisites.length > 0 && (
                          <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
                            Prerequisites to review:{" "}
                            {course.unmet_prerequisites
                              .map((item) => `${item.skill_name} (need level ${item.minimum_level})`)
                              .join(", ")}
                            . Review these prerequisites before enrolling; a pre-test is not configured yet.
                          </p>
                        )}
                        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
                          <p>
                            {course.duration_hours}h · {course.price_label} · {course.rating.toFixed(1)}★ ({course.review_count}) · Trainer {course.trainer}
                          </p>
                          <div className="flex gap-2">
                            <button
                              className="rounded-lg border border-slate-300 px-3 py-2 font-semibold"
                              onClick={() => void toggleWishlist(course)}
                              type="button"
                            >
                              {course.wishlist ? "Saved" : "Save"}
                            </button>
                            <button
                              className="rounded-lg bg-blue-700 px-3 py-2 font-semibold text-white"
                              onClick={() => void openCourse(course)}
                              type="button"
                            >
                              Details
                            </button>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                )}

                <section className="mt-8 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
                  <h2 className="text-xl font-bold">Saved courses</h2>
                  {wishlist.length === 0 ? (
                    <p className="mt-2 text-sm text-slate-600">Save a course to keep it here.</p>
                  ) : (
                    <ul className="mt-3 space-y-2">
                      {wishlist.map((course) => (
                        <li className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-slate-50 p-3" key={course.course_version_id}>
                          <span className="font-medium">{course.title} · {course.price_label}</span>
                          <button className="text-sm font-semibold text-blue-700" onClick={() => void openCourse(course)} type="button">
                            Details
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </section>
            </div>

            <section className="mt-8 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div>
                <h2 className="text-xl font-bold">Verified external resources</h2>
                <p className="mt-1 text-sm text-slate-600">
                  Optional third-party links. They are not Capacity Connect courses and do not grant completion credit by themselves.
                </p>
              </div>
              {externalCourses.length === 0 ? (
                <p className="mt-4 text-sm text-slate-500">No external courses have been verified by an admin.</p>
              ) : (
                <ul className="mt-4 grid gap-3 md:grid-cols-2">
                  {externalCourses.map((course) => (
                    <li className="rounded-2xl border border-slate-200 p-4" key={course.id}>
                      <div className="flex items-center justify-between gap-2">
                        <h3 className="font-semibold">{course.title}</h3>
                        <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-900">External</span>
                      </div>
                      <p className="mt-1 text-sm text-slate-600">
                        {course.provider} · {formatPrice(course.price_cents)}
                        {course.duration_hours ? ` · ${course.duration_hours}h` : ""}
                      </p>
                      <p className="mt-2 text-sm">{course.description}</p>
                      <a
                        className="mt-3 inline-block text-sm font-semibold text-blue-700 underline"
                        href={course.course_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Open verified provider link
                      </a>
                      <p className="mt-2 text-xs text-slate-500">{course.credit_policy}</p>
                      <button
                        className="mt-3 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold"
                        onClick={() => setCompletionCourse(course)}
                        type="button"
                      >
                        Submit certificate for review
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="mt-5 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="text-xl font-bold">Certificate review status</h2>
              {externalCompletions.length === 0 ? (
                <p className="mt-2 text-sm text-slate-500">You have no external certificate submissions.</p>
              ) : (
                <ul className="mt-4 divide-y divide-slate-200">
                  {externalCompletions.map((completion) => (
                    <li className="flex flex-wrap items-start justify-between gap-3 py-3" key={completion.id}>
                      <div>
                        <p className="font-semibold">{completion.course_title}</p>
                        <p className="text-sm text-slate-600">
                          {completion.provider} · Certificate {completion.certificate_id}
                        </p>
                        {completion.review_reason && (
                          <p className="mt-1 text-sm text-slate-600">{completion.review_reason}</p>
                        )}
                      </div>
                      <span
                        className={`rounded-full px-3 py-1 text-xs font-semibold ${
                          completion.status === "verified"
                            ? "bg-green-100 text-green-800"
                            : completion.status === "rejected"
                              ? "bg-red-100 text-red-800"
                              : "bg-amber-100 text-amber-900"
                        }`}
                      >
                        {completion.status}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>

      {detail && (
        <div
          className="fixed inset-0 z-10 flex items-center justify-center overflow-y-auto bg-slate-950/50 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDetail(null);
          }}
        >
          <section
            aria-labelledby="course-detail-heading"
            aria-modal="true"
            className="my-8 max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-3xl bg-white p-6 shadow-xl"
            role="dialog"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-blue-700">
                  Admin-approved · Version {detail.version}
                </p>
                <h2 className="mt-1 text-2xl font-bold" id="course-detail-heading">{detail.title}</h2>
              </div>
              <button className="rounded-lg px-2 py-1 text-xl text-slate-500" onClick={() => setDetail(null)} type="button" aria-label="Close details">
                ×
              </button>
            </div>
            <p className="mt-3 text-slate-700">{detail.description}</p>
            <div className="mt-4 grid gap-3 rounded-2xl bg-slate-50 p-4 text-sm sm:grid-cols-4">
              <p><strong>Price:</strong> {detail.price_label}</p>
              <p><strong>Duration:</strong> {detail.duration_hours} hours</p>
              <p><strong>Rating:</strong> {detail.rating.toFixed(1)} ({detail.review_count} reviews)</p>
              <p><strong>Trainer:</strong> {detail.trainer}</p>
            </div>
            <section className="mt-5">
              <h3 className="font-bold">Skills and target levels</h3>
              <ul className="mt-2 flex flex-wrap gap-2">
                {detail.skills.map((skill) => (
                  <li className="rounded-full bg-blue-50 px-3 py-1 text-sm" key={skill.competency_id}>
                    {skill.skill_name} · level {skill.level_taught}
                  </li>
                ))}
              </ul>
            </section>
            {detail.syllabus.length > 0 && (
              <section className="mt-5">
                <h3 className="font-bold">Syllabus</h3>
                <ol className="mt-2 list-inside list-decimal space-y-1 text-sm text-slate-700">
                  {detail.syllabus.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
                </ol>
              </section>
            )}
            {detail.learning_outcomes.length > 0 && (
              <section className="mt-5">
                <h3 className="font-bold">Learning outcomes</h3>
                <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-slate-700">
                  {detail.learning_outcomes.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </section>
            )}
            {detail.prerequisites && detail.prerequisites.length > 0 && (
              <section className="mt-5">
                <h3 className="font-bold">Prerequisites</h3>
                <ul className="mt-2 space-y-1 text-sm">
                  {detail.prerequisites.map((item) => (
                    <li className={item.is_met ? "text-emerald-800" : "text-amber-900"} key={item.skill_id}>
                      {item.skill_name} · level {item.current_level}/{item.minimum_level}{" "}
                      {item.is_met ? "(met)" : "(not yet met)"}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {detail.reviews && detail.reviews.length > 0 && (
              <section className="mt-5">
                <h3 className="font-bold">Learner reviews</h3>
                <ul className="mt-2 space-y-2">
                  {detail.reviews.map((review, index) => (
                    <li className="rounded-xl border border-slate-200 p-3 text-sm" key={`${review.created_at}-${index}`}>
                      <span className="font-semibold">{review.rating}/5</span>
                      {review.review_text && <p className="mt-1 text-slate-700">{review.review_text}</p>}
                      <p className="mt-1 text-xs text-slate-500">{new Date(review.created_at).toLocaleDateString()}</p>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {detail.unmet_prerequisites.length > 0 && (
              <p className="mt-5 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
                Prerequisite warning:{" "}
                {detail.unmet_prerequisites
                  .map((item) => `${item.skill_name}: level ${item.current_level}, need ${item.minimum_level}`)
                  .join("; ")}
                . A prerequisite pre-test is not configured yet; you can acknowledge the gap during enrollment.
              </p>
            )}
            <div className="mt-6 flex flex-wrap justify-end gap-2 border-t border-slate-100 pt-4">
              <button
                className="rounded-xl border border-slate-300 px-4 py-2.5 font-semibold"
                onClick={() => void toggleWishlist(detail)}
                type="button"
              >
                {detail.wishlist ? "Remove from wishlist" : "Save to wishlist"}
              </button>
              <button
                className="rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white"
                onClick={() => {
                  setEnrollmentCourse(detail);
                  setSponsorshipCode("");
                  setAcknowledgePrerequisites(detail.unmet_prerequisites.length === 0);
                }}
                type="button"
              >
                Enroll and start learning
              </button>
            </div>
          </section>
        </div>
      )}

      {comparison.length > 0 && (
        <div className="fixed inset-0 z-20 flex items-center justify-center overflow-y-auto bg-slate-950/50 p-4">
          <section className="my-8 max-h-[90vh] w-full max-w-6xl overflow-auto rounded-3xl bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-2xl font-bold">Compare courses</h2>
              <button className="rounded-lg border border-slate-300 px-3 py-2" onClick={() => setComparison([])} type="button">
                Close
              </button>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full border-collapse text-left text-sm">
                <thead>
                  <tr>
                    <th className="border-b p-3">Feature</th>
                    {comparison.map((course) => (
                      <th className="min-w-52 border-b p-3 align-top" key={course.course_version_id}>
                        {course.title}<br />
                        <span className="text-xs font-normal text-slate-500">Version {course.version}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["Price", (course: Course) => course.price_label],
                    ["Duration", (course: Course) => `${course.duration_hours ?? "—"} hours`],
                    ["Rating", (course: Course) => `${course.rating.toFixed(1)} (${course.review_count} reviews)`],
                    ["Trainer", (course: Course) => course.trainer],
                    ["Gap closed/hour", (course: Course) => course.gap_closed_per_hour.toFixed(3)],
                    ["Why it is recommended", (course: Course) => course.reason_summary],
                    ["Skills taught", (course: Course) => course.skills.map((skill) => `${skill.skill_name} (L${skill.level_taught})`).join(", ")],
                    ["Prerequisites", (course: Course) => course.unmet_prerequisites.length
                      ? course.unmet_prerequisites.map((item) => `${item.skill_name} (need ${item.minimum_level})`).join(", ")
                      : "No unmet prerequisites"],
                  ].map(([label, value]) => (
                    <tr key={String(label)}>
                      <th className="border-b p-3 align-top font-semibold">{label as string}</th>
                      {comparison.map((course) => (
                        <td className="border-b p-3 align-top" key={course.course_version_id}>
                          {(value as (course: Course) => string)(course)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}

      {completionCourse && (
        <div
          className="fixed inset-0 z-30 flex items-center justify-center bg-slate-950/50 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setCompletionCourse(null);
          }}
        >
          <section
            aria-labelledby="certificate-heading"
            aria-modal="true"
            className="w-full max-w-lg rounded-3xl bg-white p-6 shadow-xl"
            role="dialog"
          >
            <h2 className="text-xl font-bold" id="certificate-heading">Submit external certificate</h2>
            <p className="mt-2 text-sm text-slate-600">
              {completionCourse.title}. A valid certificate ID and link on {completionCourse.provider_domain} are required.
              The submission earns no credit until an admin checks it.
            </p>
            <form className="mt-5 space-y-4" onSubmit={submitCertificate}>
              <label className="block text-sm font-medium">
                Certificate ID
                <input
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                  onChange={(event) => setCertificateId(event.target.value)}
                  required
                  value={certificateId}
                />
              </label>
              <label className="block text-sm font-medium">
                Certificate URL
                <input
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2"
                  onChange={(event) => setCertificateUrl(event.target.value)}
                  placeholder={`https://${completionCourse.provider_domain}/...`}
                  required
                  type="url"
                  value={certificateUrl}
                />
              </label>
              <div className="flex justify-end gap-2">
                <button
                  className="rounded-lg border border-slate-300 px-4 py-2 font-semibold"
                  onClick={() => setCompletionCourse(null)}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white disabled:opacity-50"
                  disabled={submittingCertificate}
                  type="submit"
                >
                  {submittingCertificate ? "Submitting…" : "Submit for review"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {enrollmentCourse && (
        <div
          className="fixed inset-0 z-30 flex items-center justify-center overflow-y-auto bg-slate-950/50 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setEnrollmentCourse(null);
          }}
        >
          <section
            aria-labelledby="enrollment-heading"
            aria-modal="true"
            className="my-8 w-full max-w-lg rounded-3xl bg-white p-6 shadow-xl"
            role="dialog"
          >
            <h2 className="text-xl font-bold" id="enrollment-heading">Confirm enrollment</h2>
            <p className="mt-2 text-slate-700">{enrollmentCourse.title}</p>
            <div className="mt-4 rounded-2xl bg-slate-50 p-4 text-sm">
              <p><strong>Price:</strong> {enrollmentCourse.price_label}</p>
              <p><strong>Version:</strong> {enrollmentCourse.version} · Admin-approved</p>
              <p className="mt-2 text-slate-600">
                {enrollmentCourse.price_cents === 0
                  ? "This course is free."
                  : "Paid checkout is not connected yet. Use an administrator-issued seat code or choose a free course."}
              </p>
            </div>
            {enrollmentCourse.unmet_prerequisites.length > 0 && (
              <div className="mt-4 rounded-xl bg-amber-50 p-4 text-sm text-amber-950">
                <p className="font-semibold">Prerequisites to review</p>
                <ul className="mt-2 list-inside list-disc">
                  {enrollmentCourse.unmet_prerequisites.map((item) => (
                    <li key={item.skill_id}>
                      {item.skill_name}: your level {item.current_level}, recommended {item.minimum_level}
                    </li>
                  ))}
                </ul>
                <label className="mt-3 flex items-start gap-2">
                  <input
                    checked={acknowledgePrerequisites}
                    className="mt-1"
                    onChange={(event) => setAcknowledgePrerequisites(event.target.checked)}
                    type="checkbox"
                  />
                  <span>I reviewed these gaps and want to continue without the prerequisite pre-test.</span>
                </label>
              </div>
            )}
            <form className="mt-4 space-y-4" onSubmit={enrollInCourse}>
              <label className="block text-sm font-medium">
                Organization seat code <span className="font-normal text-slate-500">(optional)</span>
                <input
                  autoComplete="off"
                  className="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2.5 uppercase"
                  onChange={(event) => setSponsorshipCode(event.target.value)}
                  placeholder="Enter a code from your organization"
                  value={sponsorshipCode}
                />
              </label>
              {error && <p className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700" role="alert">{error}</p>}
              <div className="flex justify-end gap-2">
                <button
                  className="rounded-xl border border-slate-300 px-4 py-2.5 font-semibold"
                  onClick={() => setEnrollmentCourse(null)}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50"
                  disabled={
                    enrolling ||
                    (enrollmentCourse.price_cents > 0 && !sponsorshipCode.trim()) ||
                    (enrollmentCourse.unmet_prerequisites.length > 0 && !acknowledgePrerequisites)
                  }
                  type="submit"
                >
                  {enrolling ? "Enrolling…" : "Confirm and begin"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </main>
  );
}
