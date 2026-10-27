"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type AssessmentAvailability = {
  available: boolean;
  message?: string;
  assessment_id?: string;
  title?: string;
  min_questions?: number;
  max_questions?: number;
  time_limit_minutes?: number;
  target_level?: number;
  remaining_attempts?: number;
  active_attempt_id?: string | null;
  verified_tier_available?: boolean;
};
type AssessmentOption = string | number | boolean | { value?: unknown; id?: unknown; label?: unknown; text?: unknown };
type AssessmentQuestion = {
  id: string;
  competency_id: string;
  skill_name: string;
  question_type: "multiple_choice" | "multi_select" | "short_answer" | "scenario" | "code_task";
  prompt: string;
  options: AssessmentOption[];
  difficulty_level: number;
  calibration_status: "calibrated" | "uncalibrated";
  estimated_time_seconds: number;
  draft_answer?: unknown;
  draft_confidence?: number;
  draft_dont_know?: boolean;
};
type AttemptState = {
  attempt_id: string;
  assessment_title: string;
  status: "in_progress" | "submitted" | "expired";
  evidence_tier: "self_check" | "verified";
  deadline_at: string | null;
  answered_questions: number;
  min_questions: number;
  max_questions: number;
  can_submit: boolean;
  provisional_estimate: { level_min: number; level_max: number; confidence: string };
  question: AssessmentQuestion | null;
  integrity_notice: string;
  result?: AssessmentResult;
};
type AssessmentResult = {
  attempt_id: string;
  status: string;
  evidence_tier: string;
  provisional: boolean;
  level_min: number;
  level_max: number;
  confidence: "low" | "medium" | "high";
  target_level: number;
  pass: boolean;
  question_count: number;
  calibrated_question_count: number;
  integrity_flag_count: number;
  explanation: string | null;
  profile_update: {
    readiness_by_role: Array<{
      role_id: string;
      role_name: string;
      readiness_before: number;
      readiness_after: number;
      readiness_delta: number;
    }>;
    skill_changes: Array<{
      competency_id: string;
      previous_level: number | null;
      updated_level: number;
      evidence_quality: string;
      score: number;
      average_question_difficulty: number;
      credential_id: string | null;
    }>;
  };
  credentials_issued: Array<{
    credential_id: string;
    skill_name: string;
    level: number;
    evidence_tier: string;
    verification_url: string;
  }>;
  breakdown: Array<{
    competency_id: string;
    skill_name: string;
    level: number;
    level_range: { level_min: number; level_max: number; confidence: string };
    question_count: number;
    correct_count: number;
    missed_count: number;
  }>;
  weak_skills: Array<{ competency_id: string; skill_name: string; missed_count: number }>;
  recommended_courses: Array<{ course_version_id: string; title: string }>;
  practice_questions: Array<{
    id: string;
    skill_name: string;
    question_type: string;
    prompt: string;
    options: unknown[];
    calibration_status: string;
    attempt: { answer: unknown; correct: boolean } | null;
  }>;
  message: string;
};

async function api<T>(path: string, token: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `******`,
        ...options.headers,
      },
    });
  } catch {
    throw new Error(`Could not reach ${API_URL}. Start the API and database with docker compose up --build.`);
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
  return (await response.json()) as T;
}

function encode(value: unknown): string {
  return JSON.stringify(value);
}

function decode(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return value;
  }
}

function displayTime(seconds: number) {
  const safe = Math.max(0, seconds);
  return `${Math.floor(safe / 60).toString().padStart(2, "0")}:${(safe % 60).toString().padStart(2, "0")}`;
}

function optionParts(option: AssessmentOption) {
  if (option && typeof option === "object") {
    const value = option.value ?? option.id ?? option.label ?? option.text ?? option;
    return { value, label: String(option.label ?? option.text ?? value) };
  }
  return { value: option, label: String(option) };
}

export default function AssessmentPage() {
  const [token, setToken] = useState("");
  const [enrollmentId, setEnrollmentId] = useState("");
  const [availability, setAvailability] = useState<AssessmentAvailability | null>(null);
  const [attempt, setAttempt] = useState<AttemptState | null>(null);
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [tier, setTier] = useState<"self_check" | "verified">("self_check");
  const [answer, setAnswer] = useState("");
  const [dontKnow, setDontKnow] = useState(false);
  const [confidence, setConfidence] = useState(3);
  const [explanation, setExplanation] = useState("");
  const [practiceAnswers, setPracticeAnswers] = useState<Record<string, string>>({});
  const [practiceFeedback, setPracticeFeedback] = useState<Record<string, { correct: boolean; explanation: string | null }>>({});
  const [secondsRemaining, setSecondsRemaining] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadAttempt = useCallback(async (attemptId: string, accessToken: string) => {
    const response = await api<AttemptState>(`/api/v1/assessment-attempts/${attemptId}`, accessToken);
    setAttempt(response);
    setResult(response.result ?? null);
    setAnswer(
      response.question?.draft_answer === undefined
        ? ""
        : encode(response.question.draft_answer),
    );
    setDontKnow(Boolean(response.question?.draft_dont_know));
    setConfidence(response.question?.draft_confidence ?? 3);
    setSaved(response.question?.draft_answer !== undefined);
    setExplanation(response.result?.explanation ?? "");
    return response;
  }, []);

  const refreshAvailability = useCallback(
    async (id: string, accessToken: string) => {
      const response = await api<AssessmentAvailability>(
        `/api/v1/learning/enrollments/${id}/assessment`,
        accessToken,
      );
      setAvailability(response);
      if (response.active_attempt_id) {
        await loadAttempt(response.active_attempt_id, accessToken);
      }
      return response;
    },
    [loadAttempt],
  );

  useEffect(() => {
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    const id = new URLSearchParams(window.location.search).get("enrollment");
    if (!accessToken) {
      setError("Sign in to your trainee account before taking an assessment.");
      setLoading(false);
      return;
    }
    if (!id) {
      setError("Open an assessment from an enrolled course in My Learning.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    setEnrollmentId(id);
    void refreshAvailability(id, accessToken)
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not load assessment"))
      .finally(() => setLoading(false));
  }, [refreshAvailability]);

  useEffect(() => {
    if (!attempt?.deadline_at || attempt.status !== "in_progress") {
      setSecondsRemaining(null);
      return;
    }
    const update = () => {
      const remaining = Math.max(
        0,
        Math.floor((new Date(attempt.deadline_at as string).getTime() - Date.now()) / 1000),
      );
      setSecondsRemaining(remaining);
      if (remaining === 0) {
        void loadAttempt(attempt.attempt_id, token).catch((loadError: unknown) => {
          setError(loadError instanceof Error ? loadError.message : "Could not refresh the expired attempt");
        });
      }
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [attempt, loadAttempt, token]);

  useEffect(() => {
    if (!attempt || attempt.status !== "in_progress") return;
    const onVisibility = () => {
      const eventType = document.visibilityState === "hidden" ? "tab_hidden" : "tab_visible";
      void api(`/api/v1/assessment-attempts/${attempt.attempt_id}/events`, token, {
        method: "POST",
        body: JSON.stringify({ event_type: eventType }),
      }).catch(() => {
        setNotice("Integrity event could not be recorded while offline; your attempt is not failed.");
      });
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [attempt, token]);

  useEffect(() => {
    if (!attempt?.question || !token || attempt.status !== "in_progress" || dontKnow || !answer) return;
    const timer = window.setTimeout(() => {
      void api(
        `/api/v1/assessment-attempts/${attempt.attempt_id}/responses/${attempt.question?.id}`,
        token,
        {
          method: "PUT",
          body: JSON.stringify({
            answer: decode(answer),
            learner_confidence: confidence,
            dont_know: false,
            finalize: false,
          }),
        },
      )
        .then(() => setSaved(true))
        .catch((saveError: unknown) => {
          setSaved(false);
          setError(saveError instanceof Error ? saveError.message : "Could not auto-save your answer");
        });
    }, 650);
    setSaved(false);
    return () => window.clearTimeout(timer);
  }, [answer, attempt, confidence, dontKnow, token]);

  const answeredLabel = useMemo(
    () => attempt ? `${attempt.answered_questions} / ${attempt.max_questions}` : "",
    [attempt],
  );

  function updateMultiSelect(optionValue: unknown, checked: boolean) {
    const current = answer ? (decode(answer) as unknown[]) : [];
    const key = encode(optionValue);
    const values = new Map(current.map((item) => [encode(item), item]));
    if (checked) values.set(key, optionValue);
    else values.delete(key);
    setAnswer(encode(Array.from(values.values())));
    setDontKnow(false);
  }

  async function startAttempt() {
    if (!enrollmentId) return;
    setBusy(true);
    setError("");
    try {
      const started = await api<{ attempt_id: string }>(
        `/api/v1/learning/enrollments/${enrollmentId}/assessment-attempts`,
        token,
        {
          method: "POST",
          body: JSON.stringify({ evidence_tier: tier }),
        },
      );
      const refreshed = await refreshAvailability(enrollmentId, token);
      if (!refreshed.active_attempt_id) await loadAttempt(started.attempt_id, token);
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : "Could not start the assessment");
    } finally {
      setBusy(false);
    }
  }

  async function saveCurrentAnswer(finalize: boolean) {
    if (!attempt?.question) return;
    setBusy(true);
    setError("");
    try {
      await api(
        `/api/v1/assessment-attempts/${attempt.attempt_id}/responses/${attempt.question.id}`,
        token,
        {
          method: "PUT",
          body: JSON.stringify({
            answer: dontKnow ? null : decode(answer),
            learner_confidence: confidence,
            dont_know: dontKnow,
            finalize,
          }),
        },
      );
      if (finalize) {
        setNotice(dontKnow ? "I don't know recorded without a rating penalty." : "Answer recorded.");
        await loadAttempt(attempt.attempt_id, token);
      } else {
        setSaved(true);
      }
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save your response");
    } finally {
      setBusy(false);
    }
  }

  async function submitAssessment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!attempt) return;
    setBusy(true);
    setError("");
    try {
      const submitted = await api<AssessmentResult>(
        `/api/v1/assessment-attempts/${attempt.attempt_id}/submit`,
        token,
        {
          method: "POST",
          body: JSON.stringify({ explanation }),
        },
      );
      setResult(submitted);
      setAttempt((current) => current ? { ...current, status: submitted.status as AttemptState["status"] } : current);
      setConfirmSubmit(false);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not submit the assessment");
      setConfirmSubmit(false);
    } finally {
      setBusy(false);
    }
  }

  async function submitPractice(questionId: string) {
    const encoded = practiceAnswers[questionId];
    if (!encoded || !result) return;
    setBusy(true);
    setError("");
    try {
      const response = await api<{ correct: boolean; explanation: string | null }>(
        `/api/v1/assessment-attempts/${result.attempt_id}/practice/${questionId}`,
        token,
        { method: "POST", body: JSON.stringify({ answer: decode(encoded) }) },
      );
      setPracticeFeedback((current) => ({ ...current, [questionId]: response }));
    } catch (practiceError) {
      setError(practiceError instanceof Error ? practiceError.message : "Could not save the practice response");
    } finally {
      setBusy(false);
    }
  }

  const question = attempt?.question;
  const currentAnswer = answer ? decode(answer) : null;

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <div className="mx-auto max-w-4xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Stage 5</p>
            <h1 className="mt-1 text-3xl font-bold">Adaptive skill assessment</h1>
            <p className="mt-1 text-slate-600">Estimate your competency level and get focused next steps.</p>
          </div>
          <div className="flex gap-2">
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/my-learning">
              My learning
            </Link>
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/learning">
              Course picks
            </Link>
          </div>
        </header>

        {error && <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p>}
        {notice && <p className="mt-5 rounded-xl bg-blue-50 p-3 text-sm text-blue-900" role="status">{notice}</p>}
        {loading ? (
          <p className="mt-8 text-slate-600">Loading assessment…</p>
        ) : result ? (
          <section className="mt-7 space-y-5">
            <div className={`rounded-3xl border p-6 shadow-sm ${
              result.pass ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"
            }`}>
              <p className="text-sm font-semibold uppercase tracking-wide">{result.pass ? "Target reached" : "Keep building"}</p>
              <h2 className="mt-2 text-3xl font-bold">
                Estimated level {result.level_min}{result.level_max > result.level_min ? `–${result.level_max}` : ""}
              </h2>
              <p className="mt-2">
                {result.confidence} confidence · target level {result.target_level} · {result.question_count} questions
              </p>
              <p className="mt-3 text-sm">{result.message}</p>
              <p className="mt-2 text-xs">
                {result.calibrated_question_count} response(s) came from calibrated questions.
                {result.integrity_flag_count > 0 && ` ${result.integrity_flag_count} focus/tab event(s) were flagged for review; they did not cause an automatic fail.`}
              </p>
            </div>

            <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-xl font-bold">Competency breakdown</h2>
              {result.breakdown.length === 0 ? (
                <p className="mt-3 text-sm text-slate-600">There was not enough scored evidence to estimate a competency range.</p>
              ) : (
                <ul className="mt-4 space-y-3">
                  {result.breakdown.map((item) => (
                    <li className="rounded-2xl bg-slate-50 p-4" key={item.competency_id}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <h3 className="font-semibold">{item.skill_name}</h3>
                        <span className="text-sm font-semibold">
                          Level {item.level_range.level_min}{item.level_range.level_max > item.level_range.level_min ? `–${item.level_range.level_max}` : ""}
                          {" · "}{item.level_range.confidence} confidence
                        </span>
                      </div>
                      <p className="mt-1 text-sm text-slate-600">
                        {item.correct_count} correct · {item.missed_count} missed or unsure · {item.question_count} answered
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {result.weak_skills.length > 0 && (
              <section className="rounded-3xl border border-amber-200 bg-white p-6 shadow-sm">
                <h2 className="text-xl font-bold">Focused practice for weak skills</h2>
                <p className="mt-1 text-sm text-slate-600">Use these targeted recommendations, then retry when ready.</p>
                <ul className="mt-4 space-y-2">
                  {result.weak_skills.map((skill) => (
                    <li className="rounded-xl bg-amber-50 p-3 text-sm" key={skill.competency_id}>
                      {skill.skill_name} · {skill.missed_count} missed/unsure question(s)
                    </li>
                  ))}
                </ul>
                {result.practice_questions.length > 0 && (
                  <div className="mt-4">
                    <h3 className="font-semibold">Quick practice drills</h3>
                    <ol className="mt-2 space-y-3">
                      {result.practice_questions.map((item) => (
                        <li className="rounded-xl bg-slate-50 p-3 text-sm" key={item.id}>
                          <p className="text-xs font-semibold text-blue-700">{item.skill_name} · {item.calibration_status}</p>
                          <p className="mt-1 whitespace-pre-wrap">{item.prompt}</p>
                          {item.options.length > 0 && (
                            <fieldset className="mt-3 space-y-2">
                              <legend className="sr-only">Practice answer</legend>
                              {item.options.map((option, index) => {
                                const parts = optionParts(option as AssessmentOption);
                                const encoded = encode(parts.value);
                                if (item.question_type === "multi_select") {
                                  const selected = practiceAnswers[item.id] ? decode(practiceAnswers[item.id]) as unknown[] : [];
                                  return (
                                    <label className="flex items-start gap-2" key={`${item.id}-${index}`}>
                                      <input
                                        checked={selected.some((value) => encode(value) === encoded)}
                                        disabled={Boolean(item.attempt) || Boolean(practiceFeedback[item.id])}
                                        onChange={(event) => {
                                          const next = new Map(selected.map((value) => [encode(value), value]));
                                          if (event.target.checked) next.set(encoded, parts.value);
                                          else next.delete(encoded);
                                          setPracticeAnswers((current) => ({ ...current, [item.id]: encode(Array.from(next.values())) }));
                                        }}
                                        type="checkbox"
                                      />
                                      <span>{parts.label}</span>
                                    </label>
                                  );
                                }
                                return (
                                  <label className="flex items-start gap-2" key={`${item.id}-${index}`}>
                                    <input
                                      checked={practiceAnswers[item.id] === encoded}
                                      disabled={Boolean(item.attempt) || Boolean(practiceFeedback[item.id])}
                                      name={`practice-${item.id}`}
                                      onChange={() => setPracticeAnswers((current) => ({ ...current, [item.id]: encoded }))}
                                      type="radio"
                                    />
                                    <span>{parts.label}</span>
                                  </label>
                                );
                              })}
                            </fieldset>
                          )}
                          {item.options.length === 0 && (
                            <textarea
                              className="mt-3 min-h-20 w-full rounded-lg border border-slate-300 bg-white p-2"
                              disabled={Boolean(item.attempt) || Boolean(practiceFeedback[item.id])}
                              onChange={(event) => setPracticeAnswers((current) => ({ ...current, [item.id]: encode(event.target.value) }))}
                              value={practiceAnswers[item.id] ? String(decode(practiceAnswers[item.id])) : ""}
                            />
                          )}
                          {item.attempt && (
                            <p className={`mt-2 font-semibold ${item.attempt.correct ? "text-emerald-700" : "text-amber-800"}`}>
                              {item.attempt.correct ? "Previously correct" : "Previously attempted"}
                            </p>
                          )}
                          {practiceFeedback[item.id] && (
                            <p className={`mt-2 font-semibold ${practiceFeedback[item.id].correct ? "text-emerald-700" : "text-amber-800"}`}>
                              {practiceFeedback[item.id].correct ? "Correct." : "Not quite."} {practiceFeedback[item.id].explanation}
                            </p>
                          )}
                          {!item.attempt && !practiceFeedback[item.id] && (
                            <button
                              className="mt-3 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                              disabled={busy || !practiceAnswers[item.id]}
                              onClick={() => void submitPractice(item.id)}
                              type="button"
                            >
                              Check practice answer
                            </button>
                          )}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                {result.recommended_courses.length > 0 && (
                  <div className="mt-4">
                    <h3 className="font-semibold">Related approved course versions</h3>
                    <ul className="mt-2 list-inside list-disc text-sm">
                      {result.recommended_courses.map((course) => (
                        <li key={course.course_version_id}>{course.title}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {result.credentials_issued.length > 0 && (
                  <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                    <h3 className="font-bold text-emerald-950">Verified credentials issued</h3>
                    <ul className="mt-2 space-y-2 text-sm">
                      {result.credentials_issued.map((credential) => (
                        <li key={credential.credential_id}>
                          {credential.skill_name} · Level {credential.level} ·{" "}
                          <Link className="font-semibold underline" href={`/credentials/issued/${credential.credential_id}`}>
                            View credential
                          </Link>
                        </li>
                      ))}
                    </ul>
                    <Link className="mt-3 inline-flex font-semibold text-emerald-900 underline" href="/credentials">
                      View all my credentials
                    </Link>
                  </div>
                )}
                <section className="mt-4 rounded-2xl border border-blue-200 bg-blue-50 p-4">
                  <h3 className="font-bold text-blue-950">Your profile and role gaps were updated</h3>
                  {result.profile_update.readiness_by_role.length > 0 ? (
                    <ul className="mt-2 space-y-1 text-sm text-blue-950">
                      {result.profile_update.readiness_by_role.map((item) => (
                        <li key={item.role_id}>
                          {item.role_name}: {item.readiness_before.toFixed(1)}% → {item.readiness_after.toFixed(1)}%
                          {" "}({item.readiness_delta > 0 ? "+" : ""}{item.readiness_delta.toFixed(1)})
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-sm text-blue-900">Choose a target role in your passport to see readiness and gaps.</p>
                  )}
                  <Link className="mt-3 inline-flex font-semibold text-blue-800 underline" href="/profile">
                    View refreshed gaps and freshness
                  </Link>
                </section>
                <Link className="mt-4 inline-flex rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white" href="/learning">
                  Return to learning picks
                </Link>
              </section>
            )}
            <p className="text-center text-xs text-slate-500">
              Self-checks never issue credentials. A qualifying verified result may issue credentials for supported skills.
            </p>
          </section>
        ) : attempt?.status === "in_progress" ? (
          <section className="mt-7 space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white p-4">
              <div>
                <h2 className="font-bold">{attempt.assessment_title}</h2>
                <p className="text-sm text-slate-600">
                  Question {Math.min(attempt.answered_questions + (question ? 1 : 0), attempt.max_questions)} · {answeredLabel} answered
                </p>
              </div>
              <div aria-label="Time remaining" className={`rounded-xl px-4 py-2 font-mono text-lg font-bold ${
                secondsRemaining !== null && secondsRemaining < 60 ? "bg-rose-100 text-rose-800" : "bg-slate-100"
              }`}>
                {secondsRemaining === null ? "--:--" : displayTime(secondsRemaining)}
              </div>
            </div>

            {question ? (
              <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="rounded-full bg-blue-50 px-3 py-1 text-sm font-semibold text-blue-800">{question.skill_name}</span>
                  <span className="text-xs text-slate-500">
                    Difficulty {question.difficulty_level} · {question.calibration_status}
                  </span>
                </div>
                <h2 className="mt-5 whitespace-pre-wrap text-xl font-bold leading-relaxed">{question.prompt}</h2>
                {question.question_type === "multiple_choice" && (
                  <fieldset className="mt-5 space-y-2">
                    <legend className="sr-only">Select one answer</legend>
                    {question.options.map((option, index) => {
                      const parts = optionParts(option);
                      const value = encode(parts.value);
                      return (
                        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-3 hover:bg-slate-50" key={`${question.id}-${index}`}>
                          <input
                            checked={answer === value}
                            name="assessment-answer"
                            onChange={() => {
                              setAnswer(value);
                              setDontKnow(false);
                            }}
                            type="radio"
                          />
                          <span>{parts.label}</span>
                        </label>
                      );
                    })}
                  </fieldset>
                )}
                {question.question_type === "multi_select" && (
                  <fieldset className="mt-5 space-y-2">
                    <legend className="mb-2 text-sm font-medium">Select all that apply</legend>
                    {question.options.map((option, index) => {
                      const parts = optionParts(option);
                      const selected = Array.isArray(currentAnswer)
                        && currentAnswer.some((item) => encode(item) === encode(parts.value));
                      return (
                        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-3 hover:bg-slate-50" key={`${question.id}-${index}`}>
                          <input checked={selected} onChange={(event) => updateMultiSelect(parts.value, event.target.checked)} type="checkbox" />
                          <span>{parts.label}</span>
                        </label>
                      );
                    })}
                  </fieldset>
                )}
                {["short_answer", "scenario", "code_task"].includes(question.question_type) && (
                  <label className="mt-5 block text-sm font-medium">
                    Your answer
                    <textarea
                      className="mt-2 min-h-32 w-full rounded-xl border border-slate-300 p-3 font-normal"
                      onChange={(event) => {
                        setAnswer(encode(event.target.value));
                        setDontKnow(false);
                      }}
                      placeholder={question.question_type === "code_task" ? "Explain your approach and provide your solution…" : "Write your answer…"}
                      value={typeof currentAnswer === "string" ? currentAnswer : ""}
                    />
                  </label>
                )}
                <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-sm">
                    Confidence
                    <select className="rounded-lg border border-slate-300 bg-white px-2 py-1.5" onChange={(event) => setConfidence(Number(event.target.value))} value={confidence}>
                      <option value={1}>1 · Guessing</option>
                      <option value={2}>2 · Low</option>
                      <option value={3}>3 · Some</option>
                      <option value={4}>4 · High</option>
                      <option value={5}>5 · Certain</option>
                    </select>
                  </label>
                  <span aria-live="polite" className="text-xs text-slate-500">
                    {saved ? "Draft saved" : answer && !dontKnow ? "Saving…" : "Answer is not saved yet"}
                  </span>
                </div>
                <div className="mt-5 flex flex-wrap justify-between gap-3 border-t border-slate-100 pt-4">
                  <button
                    className={`rounded-xl border px-4 py-2.5 font-semibold ${
                      dontKnow ? "border-amber-300 bg-amber-50 text-amber-900" : "border-slate-300"
                    }`}
                    onClick={() => {
                      setDontKnow((current) => !current);
                      setAnswer("");
                    }}
                    type="button"
                  >
                    I don’t know · no rating penalty
                  </button>
                  <button
                    className="rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50"
                    disabled={busy || (!dontKnow && !answer)}
                    onClick={() => void saveCurrentAnswer(true)}
                    type="button"
                  >
                    {busy ? "Saving…" : "Save and continue"}
                  </button>
                </div>
              </section>
            ) : (
              <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
                <h2 className="text-xl font-bold">Question set complete</h2>
                <p className="mt-2 text-slate-600">
                  You have enough responses for an estimate. Submit when you’re ready to review your level range.
                </p>
              </section>
            )}

            <section className="rounded-2xl bg-blue-50 p-4 text-sm text-blue-950">
              <p className="font-semibold">Assessment integrity</p>
              <p className="mt-1">{attempt.integrity_notice} Your answers are auto-saved as drafts and scored only when finalized.</p>
            </section>

            {attempt.can_submit && (
              <div className="flex justify-end">
                <button className="rounded-xl border border-blue-300 bg-white px-4 py-2.5 font-semibold text-blue-800" onClick={() => setConfirmSubmit(true)} type="button">
                  Review and submit assessment
                </button>
              </div>
            )}
          </section>
        ) : attempt?.status === "expired" ? (
          <section className="mt-7 rounded-3xl border border-amber-200 bg-amber-50 p-6">
            <h2 className="text-xl font-bold">Time limit reached</h2>
            <p className="mt-2 text-slate-700">Your saved responses were kept and the result is provisional.</p>
            {attempt.result && <button className="mt-4 rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white" onClick={() => setResult(attempt.result ?? null)} type="button">View saved result</button>}
          </section>
        ) : (
          <section className="mt-7 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
            {availability?.available ? (
              <>
                <p className="text-sm font-bold uppercase tracking-wide text-blue-700">Assessment instructions</p>
                <h2 className="mt-2 text-2xl font-bold">{availability.title}</h2>
                <dl className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl bg-slate-50 p-4"><dt className="text-sm text-slate-500">Time limit</dt><dd className="mt-1 font-semibold">{availability.time_limit_minutes} minutes</dd></div>
                  <div className="rounded-xl bg-slate-50 p-4"><dt className="text-sm text-slate-500">Question range</dt><dd className="mt-1 font-semibold">{availability.min_questions}–{availability.max_questions} adaptive questions</dd></div>
                  <div className="rounded-xl bg-slate-50 p-4"><dt className="text-sm text-slate-500">Pass target</dt><dd className="mt-1 font-semibold">Estimated level {availability.target_level}</dd></div>
                  <div className="rounded-xl bg-slate-50 p-4"><dt className="text-sm text-slate-500">Attempts remaining this week</dt><dd className="mt-1 font-semibold">{availability.remaining_attempts}</dd></div>
                </dl>
                <ul className="mt-5 list-inside list-disc space-y-2 text-sm text-slate-700">
                  <li>Questions adapt to your answers and cover the course’s mapped competencies.</li>
                  <li>Your result is a level range with a confidence label, not just pass or fail.</li>
                  <li>“I don’t know” is allowed and does not change your Elo rating.</li>
                  <li>Switching tabs is logged for review, never an automatic failure.</li>
                  <li>Self-checks never issue credentials. A qualifying verified pass can issue credentials for skills with clear knowledge and practical evidence.</li>
                </ul>
                <fieldset className="mt-6 space-y-3">
                  <legend className="font-bold">Choose an assessment tier</legend>
                  <label className="flex items-start gap-3 rounded-xl border border-slate-200 p-4">
                    <input checked={tier === "self_check"} name="tier" onChange={() => setTier("self_check")} type="radio" />
                    <span><strong>Self-check</strong><span className="mt-1 block text-sm text-slate-600">Practice your level estimate. No credential is issued.</span></span>
                  </label>
                  {availability.verified_tier_available && (
                    <label className="flex items-start gap-3 rounded-xl border border-slate-200 p-4">
                      <input checked={tier === "verified"} name="tier" onChange={() => setTier("verified")} type="radio" />
                      <span><strong>Verified tier</strong><span className="mt-1 block text-sm text-slate-600">Includes an approved practical task and an explain-your-answer review. Credentials are issued only for passing skills with clear evidence and a narrow level range.</span></span>
                    </label>
                  )}
                </fieldset>
                {availability.remaining_attempts === 0 && !availability.active_attempt_id ? (
                  <p className="mt-5 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Weekly attempt limit reached. Ask an administrator if this needs adjustment.</p>
                ) : (
                  <button className="mt-6 rounded-xl bg-blue-700 px-5 py-3 font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void startAttempt()} type="button">
                    {busy ? "Starting…" : availability.active_attempt_id ? "Resume assessment" : "Start assessment"}
                  </button>
                )}
              </>
            ) : (
              <>
                <h2 className="text-xl font-bold">Assessment not available yet</h2>
                <p className="mt-2 text-slate-600">{availability?.message ?? "Loading assessment availability…"}</p>
                <Link className="mt-5 inline-flex rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white" href="/my-learning">Return to My Learning</Link>
              </>
            )}
          </section>
        )}
      </div>

      {confirmSubmit && attempt && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-950/50 p-4">
          <section aria-labelledby="submit-assessment-title" aria-modal="true" className="w-full max-w-lg rounded-3xl bg-white p-6 shadow-xl" role="dialog">
            <h2 className="text-xl font-bold" id="submit-assessment-title">Review before submitting</h2>
            <p className="mt-2 text-sm text-slate-600">{attempt.answered_questions} response(s) will be included. Your current estimate is level {attempt.provisional_estimate.level_min}–{attempt.provisional_estimate.level_max} with {attempt.provisional_estimate.confidence} confidence.</p>
            {attempt.evidence_tier === "verified" && (
              <label className="mt-4 block text-sm font-medium">
                Explain your approach (required for verified review)
                <textarea className="mt-2 min-h-28 w-full rounded-xl border border-slate-300 p-3" onChange={(event) => setExplanation(event.target.value)} value={explanation} />
              </label>
            )}
            <form className="mt-5 flex justify-end gap-2" onSubmit={submitAssessment}>
              <button className="rounded-xl border border-slate-300 px-4 py-2.5 font-semibold" onClick={() => setConfirmSubmit(false)} type="button">Go back</button>
              <button className="rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50" disabled={busy || (attempt.evidence_tier === "verified" && explanation.trim().length < 30)} type="submit">{busy ? "Submitting…" : "Submit and view result"}</button>
            </form>
          </section>
        </div>
      )}
    </main>
  );
}
