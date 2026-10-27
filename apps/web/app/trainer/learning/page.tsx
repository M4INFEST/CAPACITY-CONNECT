"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Submission = {
  id: string;
  enrollment_id: string;
  learner_id: string;
  learner: string;
  course_title: string;
  submission_type: "lab" | "project";
  title: string;
  submission_url: string | null;
  submission_text: string | null;
  submitted_at: string;
};
type Question = {
  id: string;
  enrollment_id: string;
  learner: string;
  course_title: string;
  body: string;
  created_at: string;
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
    throw new Error(`Could not reach ${API_URL}; start the API and database with docker compose up --build.`);
  }
  if (!response.ok) {
    const result = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(result.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function TrainerLearningPage() {
  const [token, setToken] = useState("");
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [replies, setReplies] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async (accessToken: string) => {
    const [submissionRows, questionRows] = await Promise.all([
      api<Submission[]>("/api/v1/trainer/learning/submissions", accessToken),
      api<Question[]>("/api/v1/trainer/learning/discussion", accessToken),
    ]);
    setSubmissions(submissionRows);
    setQuestions(questionRows);
  }, []);

  useEffect(() => {
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in to an approved trainer account to use the trainer desk.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void refresh(accessToken)
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not load trainer work"))
      .finally(() => setLoading(false));
  }, [refresh]);

  async function reviewSubmission(event: { preventDefault: () => void }, submission: Submission, decision: "reviewed" | "changes_requested") {
    event.preventDefault();
    setBusyId(submission.id);
    setError("");
    setNotice("");
    try {
      await api(`/api/v1/trainer/learning/submissions/${submission.id}/decision`, token, {
        method: "POST",
        body: JSON.stringify({
          decision,
          trainer_feedback: feedback[submission.id] ?? "",
        }),
      });
      await refresh(token);
      setNotice(`Updated "${submission.title}".`);
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : "Could not save trainer feedback");
    } finally {
      setBusyId("");
    }
  }

  async function replyToQuestion(question: Question) {
    const body = replies[question.id]?.trim();
    if (!body) return;
    setBusyId(question.id);
    setError("");
    setNotice("");
    try {
      await api(`/api/v1/learning/enrollments/${question.enrollment_id}/discussion`, token, {
        method: "POST",
        body: JSON.stringify({ body, parent_id: question.id }),
      });
      await refresh(token);
      setReplies((current) => ({ ...current, [question.id]: "" }));
      setNotice("Trainer reply sent.");
    } catch (replyError) {
      setError(replyError instanceof Error ? replyError.message : "Could not reply to this question");
    } finally {
      setBusyId("");
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Stage 4</p>
            <h1 className="mt-1 text-3xl font-bold">Trainer desk</h1>
            <p className="mt-1 text-slate-600">Review learner work and answer course questions.</p>
          </div>
          <div className="flex gap-2">
            <Link className="rounded-xl bg-blue-700 px-4 py-2 font-semibold text-white" href="/trainer/assessments">Assessment builder</Link>
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/learning">Course picks</Link>
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/my-learning">My learning</Link>
          </div>
        </header>

        {error && <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p>}
        {notice && <p className="mt-5 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800" role="status">{notice}</p>}
        {loading ? <p className="mt-8 text-slate-600">Loading trainer work…</p> : (
          <div className="mt-7 grid gap-6 lg:grid-cols-2">
            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-xl font-bold">Work to review</h2>
                <span className="rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-900">{submissions.length} pending</span>
              </div>
              {submissions.length === 0 ? (
                <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">No learner submissions are waiting for review.</p>
              ) : (
                <ul className="mt-4 space-y-4">
                  {submissions.map((item) => (
                    <li className="rounded-2xl border border-slate-200 p-4" key={item.id}>
                      <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">{item.course_title} · {item.submission_type}</p>
                      <h3 className="mt-1 font-bold">{item.title}</h3>
                      <p className="mt-1 text-sm text-slate-600">Submitted by {item.learner} · {new Date(item.submitted_at).toLocaleDateString()}</p>
                      {item.submission_url && <a className="mt-2 inline-block text-sm font-semibold text-blue-700 underline" href={item.submission_url} rel="noreferrer" target="_blank">Open submitted work</a>}
                      {item.submission_text && <p className="mt-3 whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-sm">{item.submission_text}</p>}
                      <form className="mt-4 space-y-3" onSubmit={(event) => void reviewSubmission(event, item, "reviewed")}>
                        <label className="block text-sm font-medium">
                          Feedback
                          <textarea
                            className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 p-3"
                            onChange={(event) => setFeedback((current) => ({ ...current, [item.id]: event.target.value }))}
                            required
                            value={feedback[item.id] ?? ""}
                          />
                        </label>
                        <div className="flex flex-wrap gap-2">
                          <button className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={Boolean(busyId)} type="submit">
                            Mark reviewed
                          </button>
                          <button
                            className="rounded-lg border border-amber-300 px-3 py-2 text-sm font-semibold text-amber-900 disabled:opacity-50"
                            disabled={Boolean(busyId) || (feedback[item.id] ?? "").trim().length < 2}
                            onClick={(event) => {
                              event.preventDefault();
                              void reviewSubmission(event, item, "changes_requested");
                            }}
                            type="button"
                          >
                            Request changes
                          </button>
                        </div>
                      </form>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-xl font-bold">Learner questions</h2>
                <span className="rounded-full bg-blue-100 px-3 py-1 text-sm font-semibold text-blue-900">{questions.length} unanswered</span>
              </div>
              {questions.length === 0 ? (
                <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">No learner questions are waiting for a reply.</p>
              ) : (
                <ul className="mt-4 space-y-4">
                  {questions.map((item) => (
                    <li className="rounded-2xl border border-slate-200 p-4" key={item.id}>
                      <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">{item.course_title}</p>
                      <p className="mt-2 whitespace-pre-wrap text-slate-800">{item.body}</p>
                      <p className="mt-2 text-xs text-slate-500">{item.learner} · {new Date(item.created_at).toLocaleString()}</p>
                      <label className="mt-3 block text-sm font-medium">
                        Reply
                        <textarea
                          className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 p-3"
                          onChange={(event) => setReplies((current) => ({ ...current, [item.id]: event.target.value }))}
                          value={replies[item.id] ?? ""}
                        />
                      </label>
                      <button
                        className="mt-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                        disabled={Boolean(busyId) || !(replies[item.id] ?? "").trim()}
                        onClick={() => void replyToQuestion(item)}
                        type="button"
                      >
                        Send reply
                      </button>
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
