"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Enrollment = {
  id: string;
  course_version_id: string;
  course_title: string;
  description: string | null;
  version: number;
  status: "active" | "completed";
  funding_type: "free" | "sponsored";
  lesson_count: number;
  completed_lessons: number;
  progress_percent: number;
  last_activity: string | null;
};
type LessonSummary = {
  id: string;
  title: string;
  sort_order: number;
  duration_seconds: number;
  active_seconds: number;
  last_position_seconds: number;
  checkpoint_count: number;
  answered_checkpoints: number;
  required_answers: number;
  completed: boolean;
};
type LearningCourse = {
  enrollment_id: string;
  course_title: string;
  status: "active" | "completed";
  funding_type: "free" | "sponsored";
  progress_percent: number;
  assessment_unlocked: boolean;
  assessment_message: string;
  lessons: LessonSummary[];
};
type Checkpoint = {
  id: string;
  question: Record<string, unknown>;
  answered: boolean;
  correct: boolean | null;
};
type Lesson = {
  id: string;
  title: string;
  content: string | null;
  content_ref: string | null;
  duration_seconds: number;
  last_position_seconds: number;
  active_seconds: number;
  notes: string;
  completed: boolean;
  required_view_seconds: number;
  checkpoints: Checkpoint[];
};
type Submission = {
  id: string;
  submission_type: "lab" | "project";
  title: string;
  submission_url: string | null;
  status: string;
  trainer_feedback: string | null;
  submitted_at: string;
};
type DiscussionMessage = {
  id: string;
  parent_id: string | null;
  author: string;
  author_role: string;
  body: string;
  created_at: string;
};

async function api<T>(path: string, token: string, options: RequestInit = {}): Promise<T> {
  if (!token) {
    throw new Error("Authentication required.");
  }
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
      `Could not reach the API at ${API_URL}. Start Docker Desktop and run "docker compose up --build" from the capacity-connect folder.`,
    );
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      window.sessionStorage.removeItem("capacity-connect-token");
      throw new Error("Session expired. Please sign in again.");
    }
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

function formatDuration(seconds: number) {
  const minutes = Math.ceil(seconds / 60);
  return `${minutes} min`;
}

function questionText(question: Record<string, unknown>) {
  const prompt = question.prompt ?? question.question ?? question.text;
  return typeof prompt === "string" ? prompt : "Answer this checkpoint";
}

export default function MyLearningPage() {
  const [token, setToken] = useState("");
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [course, setCourse] = useState<LearningCourse | null>(null);
  const [selectedEnrollment, setSelectedEnrollment] = useState("");
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [discussion, setDiscussion] = useState<DiscussionMessage[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [question, setQuestion] = useState("");
  const [workTitle, setWorkTitle] = useState("");
  const [workType, setWorkType] = useState<"lab" | "project">("project");
  const [workUrl, setWorkUrl] = useState("");
  const [workText, setWorkText] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const lastInteraction = useRef(Date.now());
  const videoRef = useRef<HTMLVideoElement>(null);

  const loadCourse = useCallback(
    async (enrollmentId: string, accessToken: string) => {
      const [courseResponse, workResponse, discussionResponse] = await Promise.all([
        api<LearningCourse>(`/api/v1/learning/enrollments/${enrollmentId}`, accessToken),
        api<Submission[]>(`/api/v1/learning/enrollments/${enrollmentId}/submissions`, accessToken),
        api<DiscussionMessage[]>(`/api/v1/learning/enrollments/${enrollmentId}/discussion`, accessToken),
      ]);
      setCourse(courseResponse);
      setSubmissions(workResponse);
      setDiscussion(discussionResponse);
      setLesson(null);
    },
    [],
  );

  const loadEnrollments = useCallback(async (accessToken: string) => {
    const response = await api<Enrollment[]>("/api/v1/learning/enrollments", accessToken);
    setEnrollments(response);
    return response;
  }, []);

  useEffect(() => {
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in to your trainee account before opening My Learning.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void (async () => {
      try {
        const rows = await loadEnrollments(accessToken);
        const requestedId = new URLSearchParams(window.location.search).get("enrollment");
        const initial = rows.find((item) => item.id === requestedId) ?? rows[0];
        if (initial) {
          setSelectedEnrollment(initial.id);
          await loadCourse(initial.id, accessToken);
        }
      } catch (loadError) {
        const msg = loadError instanceof Error ? loadError.message : "Could not load your learning dashboard";
        if (msg.includes("Session expired") || msg.includes("Authentication required")) {
          setToken("");
          setError("Sign in to your trainee account before opening My Learning.");
        } else {
          setError(msg);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [loadCourse, loadEnrollments]);

  useEffect(() => {
    if (!token || !selectedEnrollment) return;
    const interval = window.setInterval(() => {
      void api<LearningCourse>(
        `/api/v1/learning/enrollments/${selectedEnrollment}`,
        token,
      ).then(setCourse).catch((loadError: unknown) => {
        setError(loadError instanceof Error ? loadError.message : "Could not refresh course progress");
      });
    }, 30_000);
    return () => window.clearInterval(interval);
  }, [loadCourse, selectedEnrollment, token]);

  useEffect(() => {
    const markActive = () => {
      lastInteraction.current = Date.now();
    };
    window.addEventListener("pointerdown", markActive);
    window.addEventListener("keydown", markActive);
    window.addEventListener("touchstart", markActive);
    return () => {
      window.removeEventListener("pointerdown", markActive);
      window.removeEventListener("keydown", markActive);
      window.removeEventListener("touchstart", markActive);
    };
  }, []);

  useEffect(() => {
    if (!token || !selectedEnrollment || !lesson || lesson.completed) return;
    const isVideo = Boolean(lesson.content_ref?.match(/\.(mp4|webm|ogg)(\?|$)/i));
    const interval = window.setInterval(() => {
      const video = videoRef.current;
      const active = document.visibilityState === "visible"
        && (isVideo
          ? Boolean(video && !video.paused && !video.muted)
          : Date.now() - lastInteraction.current < 60_000);
      if (!active) return;
      const position = isVideo && video
        ? Math.floor(video.currentTime)
        : Math.min(lesson.duration_seconds, lesson.last_position_seconds + 15);
      void api<{ active_seconds: number; last_position_seconds: number; completed: boolean }>(
        `/api/v1/learning/enrollments/${selectedEnrollment}/lessons/${lesson.id}/heartbeat`,
        token,
        {
          method: "POST",
          body: JSON.stringify({ last_position_seconds: position }),
        },
      )
        .then((progress) => {
          setLesson((current) => current
            ? {
                ...current,
                active_seconds: progress.active_seconds,
                last_position_seconds: progress.last_position_seconds,
                completed: progress.completed,
              }
            : current);
          if (progress.completed) setNotice("Lesson completed. Your course progress has been updated.");
        })
        .catch((progressError: unknown) => {
          setError(progressError instanceof Error ? progressError.message : "Could not save lesson progress");
        });
    }, 15_000);
    return () => window.clearInterval(interval);
  }, [lesson, selectedEnrollment, token]);

  async function chooseEnrollment(enrollmentId: string) {
    setError("");
    setNotice("");
    setSelectedEnrollment(enrollmentId);
    try {
      await loadCourse(enrollmentId, token);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not open this course");
    }
  }

  async function openLesson(lessonId: string) {
    if (!selectedEnrollment) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const lessonResponse = await api<Lesson>(
        `/api/v1/learning/enrollments/${selectedEnrollment}/lessons/${lessonId}`,
        token,
      );
      setLesson(lessonResponse);
      setNotes(lessonResponse.notes);
      setAnswers({});
      lastInteraction.current = Date.now();
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not open this lesson");
    } finally {
      setBusy(false);
    }
  }

  async function answerCheckpoint(checkpointId: string) {
    if (!lesson || !selectedEnrollment || answers[checkpointId] === undefined) return;
    setBusy(true);
    setError("");
    try {
      const checkpoint = lesson.checkpoints.find((item) => item.id === checkpointId);
      let answer: string | number | boolean | string[] = answers[checkpointId];
      if (checkpoint && Array.isArray(checkpoint.question.options)) {
        answer = JSON.parse(answers[checkpointId]) as string | number | boolean | string[];
      }
      const result = await api<{ correct: boolean; lesson_completed: boolean }>(
        `/api/v1/learning/enrollments/${selectedEnrollment}/lessons/${lesson.id}/checkpoints/${checkpointId}`,
        token,
        { method: "POST", body: JSON.stringify({ answer }) },
      );
      setNotice(result.correct ? "Correct answer recorded." : "Answer recorded. Review the lesson and try again.");
      const refreshed = await api<Lesson>(
        `/api/v1/learning/enrollments/${selectedEnrollment}/lessons/${lesson.id}`,
        token,
      );
      setLesson(refreshed);
      setNotes(refreshed.notes);
      const courseResponse = await api<LearningCourse>(
        `/api/v1/learning/enrollments/${selectedEnrollment}`,
        token,
      );
      setCourse(courseResponse);
    } catch (answerError) {
      setError(answerError instanceof Error ? answerError.message : "Could not submit this checkpoint");
    } finally {
      setBusy(false);
    }
  }

  async function saveNotes(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!lesson || !selectedEnrollment) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/learning/enrollments/${selectedEnrollment}/lessons/${lesson.id}/notes`, token, {
        method: "PUT",
        body: JSON.stringify({ notes }),
      });
      setNotice("Your private notes were saved.");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save notes");
    } finally {
      setBusy(false);
    }
  }

  async function submitWork(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedEnrollment) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/learning/enrollments/${selectedEnrollment}/submissions`, token, {
        method: "POST",
        body: JSON.stringify({
          submission_type: workType,
          ...(lesson ? { lesson_id: lesson.id } : {}),
          title: workTitle,
          ...(workUrl.trim() ? { submission_url: workUrl.trim() } : {}),
          ...(workText.trim() ? { submission_text: workText.trim() } : {}),
        }),
      });
      const response = await api<Submission[]>(
        `/api/v1/learning/enrollments/${selectedEnrollment}/submissions`,
        token,
      );
      setSubmissions(response);
      setWorkTitle("");
      setWorkUrl("");
      setWorkText("");
      setNotice("Your work was sent to the trainer for review.");
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not submit your work");
    } finally {
      setBusy(false);
    }
  }

  async function postQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedEnrollment || !question.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/learning/enrollments/${selectedEnrollment}/discussion`, token, {
        method: "POST",
        body: JSON.stringify({ body: question }),
      });
      const response = await api<DiscussionMessage[]>(
        `/api/v1/learning/enrollments/${selectedEnrollment}/discussion`,
        token,
      );
      setDiscussion(response);
      setQuestion("");
      setNotice("Your question was sent to the course trainer.");
    } catch (postError) {
      setError(postError instanceof Error ? postError.message : "Could not send your question");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Stage 4</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight">My Learning</h1>
            <p className="mt-1 text-slate-600">Continue courses, track progress, and get help when you need it.</p>
          </div>
          <div className="flex gap-2">
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/learning">
              Course picks
            </Link>
            <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/">
              Skill Passport
            </Link>
          </div>
        </header>

        {error && <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p>}
        {notice && <p className="mt-5 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800" role="status">{notice}</p>}

        {loading ? (
          <p className="mt-8 text-slate-600">Loading your courses…</p>
        ) : enrollments.length === 0 ? (
          <section className="mt-8 rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm">
            <span aria-hidden="true" className="text-4xl">📚</span>
            <h2 className="mt-3 text-2xl font-bold">Your learning journey starts here</h2>
            <p className="mx-auto mt-2 max-w-xl text-slate-600">
              You have no course enrollments yet. Find an approved course matched to your goals and enroll for free or with an organization seat code.
            </p>
            <Link className="mt-5 inline-block rounded-xl bg-blue-700 px-5 py-3 font-semibold text-white" href="/learning">
              Explore course picks
            </Link>
          </section>
        ) : (
          <div className="mt-7 grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
            <aside className="space-y-4">
              <section className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
                <h2 className="px-2 text-sm font-bold uppercase tracking-wide text-slate-500">Your courses</h2>
                <ul className="mt-2 space-y-2">
                  {enrollments.map((item) => (
                    <li key={item.id}>
                      <button
                        aria-current={selectedEnrollment === item.id ? "true" : undefined}
                        className={`w-full rounded-2xl p-3 text-left ${
                          selectedEnrollment === item.id ? "bg-blue-50 ring-1 ring-blue-200" : "hover:bg-slate-50"
                        }`}
                        onClick={() => void chooseEnrollment(item.id)}
                        type="button"
                      >
                        <span className="block font-semibold">{item.course_title}</span>
                        <span className="mt-1 block text-xs text-slate-500">
                          Version {item.version} · {item.funding_type}
                        </span>
                        <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-slate-200">
                          <span className="block h-full rounded-full bg-blue-600" style={{ width: `${item.progress_percent}%` }} />
                        </span>
                        <span className="mt-1 block text-xs text-slate-500">
                          {item.completed_lessons}/{item.lesson_count} lessons · {item.progress_percent}%
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
              {course && (
                <section className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
                  <h2 className="font-bold">Course progress</h2>
                  <p className="mt-1 text-sm text-slate-600">{course.course_title} · {course.funding_type}</p>
                  <div
                    aria-label={`${course.progress_percent}% course progress`}
                    className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200"
                    role="progressbar"
                    aria-valuenow={course.progress_percent}
                    aria-valuemin={0}
                    aria-valuemax={100}
                  >
                    <span className="block h-full rounded-full bg-blue-600" style={{ width: `${course.progress_percent}%` }} />
                  </div>
                  <p className="mt-2 text-sm text-slate-600">{course.progress_percent}% complete</p>
                </section>
              )}
            </aside>

            <div className="space-y-5">
              {course && (
                <>
                  <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Enrolled · {course.funding_type}</p>
                        <h2 className="mt-1 text-2xl font-bold">{course.course_title}</h2>
                        <p className="mt-2 text-sm text-slate-600">
                          Your enrollment stays on its approved course version. Lesson activity pauses when this page is hidden or idle.
                        </p>
                      </div>
                      <span className={`rounded-full px-3 py-1 text-sm font-semibold ${
                        course.status === "completed" ? "bg-emerald-100 text-emerald-800" : "bg-blue-50 text-blue-800"
                      }`}>
                        {course.status}
                      </span>
                    </div>
                    {course.lessons.length === 0 ? (
                      <p className="mt-5 rounded-xl bg-amber-50 p-4 text-sm text-amber-900">
                        The trainer has not published lesson content for this course version yet. Your enrollment is saved; check back when lessons are available.
                      </p>
                    ) : (
                      <ol className="mt-5 space-y-2">
                        {course.lessons.map((item, index) => (
                          <li key={item.id}>
                            <button
                              className={`flex w-full items-center gap-3 rounded-2xl border p-3 text-left ${
                                lesson?.id === item.id ? "border-blue-300 bg-blue-50" : "border-slate-200 hover:bg-slate-50"
                              }`}
                              disabled={busy}
                              onClick={() => void openLesson(item.id)}
                              type="button"
                            >
                              <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full text-sm font-bold ${
                                item.completed ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-700"
                              }`}>
                                {item.completed ? "✓" : index + 1}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block font-semibold">{item.title}</span>
                                <span className="mt-0.5 block text-xs text-slate-500">
                                  {formatDuration(item.duration_seconds)} · {item.answered_checkpoints}/{item.required_answers} checkpoints
                                </span>
                              </span>
                              <span className="text-sm font-semibold text-blue-700">
                                {item.completed ? "Review" : item.last_position_seconds ? "Resume" : "Open"}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ol>
                    )}
                    <p className={`mt-4 rounded-xl p-3 text-sm ${
                      course.assessment_unlocked ? "bg-emerald-50 text-emerald-900" : "bg-slate-50 text-slate-600"
                    }`}>
                      {course.assessment_message}
                    </p>
                    {course.assessment_unlocked && selectedEnrollment && (
                      <Link
                        className="mt-3 inline-flex rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white"
                        href={`/assessment?enrollment=${selectedEnrollment}`}
                      >
                        Check assessment availability
                      </Link>
                    )}
                  </section>

                  {lesson && (
                    <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Lesson player</p>
                          <h2 className="mt-1 text-xl font-bold">{lesson.title}</h2>
                          <p className="mt-1 text-sm text-slate-600">
                            Active study time: {formatDuration(lesson.active_seconds)} / {formatDuration(lesson.required_view_seconds)}
                          </p>
                        </div>
                        {lesson.completed && <span className="rounded-full bg-emerald-100 px-3 py-1 text-sm font-semibold text-emerald-800">Completed</span>}
                      </div>
                      <div className="mt-4 rounded-2xl bg-slate-50 p-4">
                        {lesson.content_ref?.match(/\.(mp4|webm|ogg)(\?|$)/i) ? (
                          <video
                            className="max-h-[28rem] w-full rounded-xl bg-black"
                            controls
                            playsInline
                            ref={videoRef}
                            src={lesson.content_ref}
                          >
                            Your browser does not support video playback.
                          </video>
                        ) : lesson.content ? (
                          <div className="whitespace-pre-wrap leading-7 text-slate-800">{lesson.content}</div>
                        ) : (
                          <p className="text-sm text-slate-600">No reading text was added for this lesson.</p>
                        )}
                        {lesson.content_ref && !lesson.content_ref.match(/\.(mp4|webm|ogg)(\?|$)/i) && (
                          <a
                            className="mt-3 inline-block font-semibold text-blue-700 underline"
                            href={lesson.content_ref}
                            rel="noreferrer"
                            target="_blank"
                          >
                            Open lesson resource
                          </a>
                        )}
                      </div>

                      {lesson.checkpoints.length > 0 && (
                        <section className="mt-6">
                          <h3 className="font-bold">Knowledge checks</h3>
                          <p className="mt-1 text-sm text-slate-600">Answer all required checks to complete this lesson.</p>
                          <ol className="mt-3 space-y-3">
                            {lesson.checkpoints.map((item, index) => {
                              const options = Array.isArray(item.question.options) ? item.question.options : [];
                              return (
                                <li className="rounded-2xl border border-slate-200 p-4" key={item.id}>
                                  <p className="font-medium">{index + 1}. {questionText(item.question)}</p>
                                  {options.length > 0 ? (
                                    <fieldset className="mt-3 space-y-2">
                                      <legend className="sr-only">Answer choice</legend>
                                      {options.map((option, optionIndex) => {
                                        const choice = option && typeof option === "object"
                                          ? option as Record<string, unknown>
                                          : null;
                                        const rawValue = choice?.value ?? choice?.id ?? option;
                                        const value = JSON.stringify(rawValue);
                                        const label = String(choice?.label ?? choice?.text ?? option);
                                        return (
                                          <label className="flex items-start gap-2 text-sm" key={`${item.id}-${optionIndex}`}>
                                            <input
                                              checked={answers[item.id] === value}
                                              disabled={item.answered || busy}
                                              name={`checkpoint-${item.id}`}
                                              onChange={() => setAnswers((current) => ({ ...current, [item.id]: value }))}
                                              type="radio"
                                              value={value}
                                            />
                                            <span>{label}</span>
                                          </label>
                                        );
                                      })}
                                    </fieldset>
                                  ) : (
                                    <input
                                      aria-label={`Answer checkpoint ${index + 1}`}
                                      className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2"
                                      disabled={item.answered || busy}
                                      onChange={(event) => setAnswers((current) => ({ ...current, [item.id]: event.target.value }))}
                                      value={answers[item.id] ?? ""}
                                    />
                                  )}
                                  <div className="mt-3 flex items-center justify-between gap-2">
                                    {item.answered ? (
                                      <span className={`text-sm font-semibold ${item.correct ? "text-emerald-700" : "text-amber-800"}`}>
                                        {item.correct ? "Correct" : "Answered"}
                                      </span>
                                    ) : <span />}
                                    {!item.answered && (
                                      <button
                                        className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                                        disabled={busy || answers[item.id] === undefined}
                                        onClick={() => void answerCheckpoint(item.id)}
                                        type="button"
                                      >
                                        Submit answer
                                      </button>
                                    )}
                                  </div>
                                </li>
                              );
                            })}
                          </ol>
                        </section>
                      )}

                      <form className="mt-6 border-t border-slate-100 pt-5" onSubmit={saveNotes}>
                        <label className="block font-bold" htmlFor="lesson-notes">Private lesson notes</label>
                        <textarea
                          className="mt-2 min-h-28 w-full rounded-xl border border-slate-300 p-3"
                          id="lesson-notes"
                          onChange={(event) => setNotes(event.target.value)}
                          placeholder="Write notes for yourself…"
                          value={notes}
                        />
                        <button className="mt-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold" disabled={busy} type="submit">
                          Save notes
                        </button>
                      </form>
                    </section>
                  )}

                  <section className="grid gap-5 xl:grid-cols-2">
                    <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
                      <h2 className="text-lg font-bold">Labs and projects</h2>
                      <form className="mt-4 space-y-3" onSubmit={submitWork}>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <label className="block text-sm font-medium">
                            Type
                            <select className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" onChange={(event) => setWorkType(event.target.value as "lab" | "project")} value={workType}>
                              <option value="project">Project</option>
                              <option value="lab">Lab</option>
                            </select>
                          </label>
                          <label className="block text-sm font-medium">
                            Title
                            <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" onChange={(event) => setWorkTitle(event.target.value)} required value={workTitle} />
                          </label>
                        </div>
                        <label className="block text-sm font-medium">
                          HTTPS link <span className="font-normal text-slate-500">(optional if submitting text)</span>
                          <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" onChange={(event) => setWorkUrl(event.target.value)} placeholder="https://…" type="url" value={workUrl} />
                        </label>
                        <label className="block text-sm font-medium">
                          Written work <span className="font-normal text-slate-500">(optional if submitting a link)</span>
                          <textarea className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 p-3" onChange={(event) => setWorkText(event.target.value)} value={workText} />
                        </label>
                        <button className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy} type="submit">Send to trainer</button>
                      </form>
                      <ul className="mt-4 space-y-2">
                        {submissions.map((item) => (
                          <li className="rounded-xl bg-slate-50 p-3 text-sm" key={item.id}>
                            <div className="flex justify-between gap-2">
                              <span className="font-semibold">{item.title}</span>
                              <span className="text-slate-600">{item.status.replace("_", " ")}</span>
                            </div>
                            {item.trainer_feedback && <p className="mt-2 text-slate-700">{item.trainer_feedback}</p>}
                          </li>
                        ))}
                      </ul>
                    </section>

                    <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
                      <h2 className="text-lg font-bold">Ask the trainer</h2>
                      <p className="mt-1 text-sm text-slate-600">Ask a question, then check back for a trainer reply.</p>
                      <form className="mt-4 space-y-3" onSubmit={postQuestion}>
                        <label className="sr-only" htmlFor="course-question">Your question</label>
                        <textarea
                          className="min-h-24 w-full rounded-xl border border-slate-300 p-3"
                          id="course-question"
                          onChange={(event) => setQuestion(event.target.value)}
                          placeholder="What are you stuck on?"
                          value={question}
                        />
                        <button className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy || !question.trim()} type="submit">
                          Send question
                        </button>
                      </form>
                      <ul className="mt-4 space-y-2">
                        {discussion.map((item) => (
                          <li className={`rounded-xl p-3 text-sm ${item.parent_id ? "ml-6 bg-blue-50" : "bg-slate-50"}`} key={item.id}>
                            <p className="font-semibold">{item.parent_id ? "Trainer reply" : item.author_role === "you" ? "You" : "Course team"}</p>
                            <p className="mt-1 whitespace-pre-wrap">{item.body}</p>
                          </li>
                        ))}
                      </ul>
                      <details className="mt-4 rounded-xl border border-slate-200 p-3">
                        <summary className="cursor-pointer font-semibold">Stuck? Open the help ladder</summary>
                        <ol className="mt-3 list-inside list-decimal space-y-2 text-sm text-slate-700">
                          <li>Revisit the lesson notes and learning outcomes for a hint.</li>
                          <li>Post a question above to connect with your trainer and course peers.</li>
                          <li>Ask the trainer for an office-hours appointment in the discussion.</li>
                        </ol>
                      </details>
                    </section>
                  </section>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
