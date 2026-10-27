"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Question = {
  id: string;
  assessment_id: string;
  assessment_title: string;
  competency_id: string;
  skill_name: string;
  question_type: string;
  prompt: string;
  options: unknown[];
  answer_key: unknown;
  difficulty_level: number;
  elo_rating: number;
  calibration_status: string;
  explanation: string | null;
  estimated_time_seconds: number;
};

async function api<T>(path: string, token: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", Authorization: `******`, ...options.headers },
    });
  } catch {
    throw new Error(`Could not reach ${API_URL}. Start the API and database with docker compose up --build.`);
  }
  if (!response.ok) {
    const result = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(result.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function AssessmentReviewPage() {
  const [token, setToken] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [attemptLimit, setAttemptLimit] = useState(3);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function refresh(accessToken: string) {
    const [queue, policy] = await Promise.all([
      api<Question[]>("/api/v1/admin/assessment-questions", accessToken),
      api<{ attempts_per_week: number }>("/api/v1/admin/assessment-policy", accessToken),
    ]);
    setQuestions(queue);
    setAttemptLimit(policy.attempts_per_week);
  }

  useEffect(() => {
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in to an admin account to review question banks.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void refresh(accessToken)
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not load review queue"))
      .finally(() => setLoading(false));
  }, []);

  async function decide(question: Question, decision: "approved" | "rejected") {
    const note = window.prompt(
      decision === "approved" ? "Approval note (content/rubric checked):" : "Reason for rejecting this question:",
      decision === "approved" ? "Reviewed for accuracy and answer-key integrity." : "",
    );
    if (note === null) return;
    if (note.trim().length < 3) {
      setError("Add a review note of at least three characters.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/api/v1/admin/assessment-questions/${question.id}/decision`, token, {
        method: "POST",
        body: JSON.stringify({ decision, moderation_note: note.trim() }),
      });
      await refresh(token);
      setNotice(`Question ${decision}.`);
    } catch (decisionError) {
      setError(decisionError instanceof Error ? decisionError.message : "Could not save review decision");
    } finally {
      setBusy(false);
    }
  }

  async function savePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/api/v1/admin/assessment-policy", token, {
        method: "PUT",
        body: JSON.stringify({ attempts_per_week: attemptLimit }),
      });
      setNotice("Weekly assessment limit saved.");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save assessment policy");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Admin</p>
            <h1 className="mt-1 text-3xl font-bold">Assessment question review</h1>
            <p className="mt-1 text-slate-600">Only approved question-bank content can be served to learners.</p>
          </div>
          <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/">Skill Passport</Link>
        </header>
        {error && <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p>}
        {notice && <p className="mt-5 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800" role="status">{notice}</p>}
        {loading ? <p className="mt-8 text-slate-600">Loading review queue…</p> : (
          <div className="mt-7 grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
            <form className="h-fit rounded-3xl border border-slate-200 bg-white p-5 shadow-sm" onSubmit={savePolicy}>
              <h2 className="text-lg font-bold">Attempt policy</h2>
              <p className="mt-1 text-sm text-slate-600">Applies per learner over a rolling seven-day window.</p>
              <label className="mt-4 block text-sm font-medium">
                Attempts per week
                <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" max={50} min={1} onChange={(event) => setAttemptLimit(Number(event.target.value))} type="number" value={attemptLimit} />
              </label>
              <button className="mt-3 rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white disabled:opacity-50" disabled={busy} type="submit">Save policy</button>
            </form>
            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-xl font-bold">Pending question bank entries</h2>
                <span className="rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-900">{questions.length} pending</span>
              </div>
              {questions.length === 0 ? (
                <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">The queue is clear. Trainer-submitted questions will appear here.</p>
              ) : (
                <ul className="mt-4 space-y-4">
                  {questions.map((question) => (
                    <li className="rounded-2xl border border-slate-200 p-4" key={question.id}>
                      <div className="flex flex-wrap justify-between gap-2">
                        <p className="text-xs font-bold uppercase tracking-wide text-blue-700">{question.assessment_title} · {question.skill_name}</p>
                        <p className="text-xs text-slate-500">{question.question_type} · difficulty {question.difficulty_level} · starting Elo {question.elo_rating}</p>
                      </div>
                      <p className="mt-3 whitespace-pre-wrap font-medium">{question.prompt}</p>
                      {question.options.length > 0 && (
                        <ul className="mt-2 list-inside list-disc text-sm text-slate-600">
                          {question.options.map((option, index) => <li key={index}>{typeof option === "string" ? option : JSON.stringify(option)}</li>)}
                        </ul>
                      )}
                      <p className="mt-3 rounded-xl bg-blue-50 p-3 text-sm text-blue-950">
                        Expected answer key (admin only): {JSON.stringify(question.answer_key)}
                      </p>
                      {question.explanation && <p className="mt-3 rounded-xl bg-slate-50 p-3 text-sm text-slate-600">{question.explanation}</p>}
                      <div className="mt-4 flex gap-2">
                        <button className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void decide(question, "approved")} type="button">Approve</button>
                        <button className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800 disabled:opacity-50" disabled={busy} onClick={() => void decide(question, "rejected")} type="button">Reject</button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
