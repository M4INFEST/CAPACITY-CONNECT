"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Course = { course_version_id: string; title: string; version: number };
type Assessment = {
  id: string;
  course_version_id: string;
  course_title: string;
  title: string;
  min_questions: number;
  max_questions: number;
  target_level: number;
  time_limit_minutes: number;
  question_count: number;
  approved_question_count: number;
  pending_question_count: number;
};
type Competency = { competency_id: string; skill_name: string };

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

export default function TrainerAssessmentsPage() {
  const [token, setToken] = useState("");
  const [courses, setCourses] = useState<Course[]>([]);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [selectedAssessment, setSelectedAssessment] = useState("");
  const [competencies, setCompetencies] = useState<Competency[]>([]);
  const [courseVersionId, setCourseVersionId] = useState("");
  const [title, setTitle] = useState("");
  const [timeLimit, setTimeLimit] = useState(30);
  const [minQuestions, setMinQuestions] = useState(5);
  const [maxQuestions, setMaxQuestions] = useState(10);
  const [targetLevel, setTargetLevel] = useState(3);
  const [questionType, setQuestionType] = useState<"multiple_choice" | "multi_select" | "short_answer" | "scenario" | "code_task">("multiple_choice");
  const [competencyId, setCompetencyId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [options, setOptions] = useState("");
  const [answerKey, setAnswerKey] = useState("");
  const [explanation, setExplanation] = useState("");
  const [difficulty, setDifficulty] = useState(3);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async (accessToken: string) => {
    const [courseRows, assessmentRows] = await Promise.all([
      api<Course[]>("/api/v1/trainer/assessments/courses", accessToken),
      api<Assessment[]>("/api/v1/trainer/assessments", accessToken),
    ]);
    setCourses(courseRows);
    setAssessments(assessmentRows);
    setCourseVersionId((current) => current || courseRows[0]?.course_version_id || "");
  }, []);

  useEffect(() => {
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in to an approved trainer account before building assessments.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void refresh(accessToken)
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not load trainer courses"))
      .finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    if (!selectedAssessment || !token) {
      setCompetencies([]);
      return;
    }
    void api<Competency[]>(`/api/v1/trainer/assessments/${selectedAssessment}/competencies`, token)
      .then((rows) => {
        setCompetencies(rows);
        setCompetencyId(rows[0]?.competency_id ?? "");
      })
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not load course competencies"));
  }, [selectedAssessment, token]);

  async function createAssessment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const created = await api<{ assessment_id: string }>("/api/v1/trainer/assessments", token, {
        method: "POST",
        body: JSON.stringify({
          course_version_id: courseVersionId,
          title,
          time_limit_minutes: timeLimit,
          min_questions: minQuestions,
          max_questions: maxQuestions,
          target_level: targetLevel,
        }),
      });
      setTitle("");
      setSelectedAssessment(created.assessment_id);
      await refresh(token);
      setNotice("Assessment created. Add questions below; every question needs admin approval before use.");
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Could not create assessment");
    } finally {
      setBusy(false);
    }
  }

  async function createQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedAssessment) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const optionList = ["multiple_choice", "multi_select"].includes(questionType)
        ? options.split(/\r?\n/).map((value) => value.trim()).filter(Boolean)
        : [];
      const key = questionType === "multi_select"
        ? answerKey.split(",").map((value) => value.trim()).filter(Boolean)
        : ["multiple_choice", "short_answer"].includes(questionType)
          ? answerKey.trim()
          : answerKey.trim();
      await api(`/api/v1/trainer/assessments/${selectedAssessment}/questions`, token, {
        method: "POST",
        body: JSON.stringify({
          competency_id: competencyId,
          question_type: questionType,
          prompt,
          options: optionList,
          answer_key: key,
          explanation: explanation.trim() || null,
          difficulty_level: difficulty,
        }),
      });
      setPrompt("");
      setOptions("");
      setAnswerKey("");
      setExplanation("");
      await refresh(token);
      setNotice("Question submitted to the admin approval queue.");
    } catch (questionError) {
      setError(questionError instanceof Error ? questionError.message : "Could not submit question");
    } finally {
      setBusy(false);
    }
  }

  const questionTypeHelp = questionType === "multi_select"
    ? "Enter one option per line. List correct option values separated by commas."
    : questionType === "multiple_choice"
      ? "Enter one option per line, then enter the exact correct option."
      : "Provide an expected answer key for automatic comparison. Verified answers remain provisional pending Stage 6.";

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Stage 5</p>
            <h1 className="mt-1 text-3xl font-bold">Assessment builder</h1>
            <p className="mt-1 text-slate-600">Create course question banks. Admin approval is required before learners can see them.</p>
          </div>
          <Link className="rounded-xl border border-slate-300 bg-white px-4 py-2 font-semibold" href="/trainer/learning">Trainer desk</Link>
        </header>
        {error && <p className="mt-5 rounded-xl bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p>}
        {notice && <p className="mt-5 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800" role="status">{notice}</p>}
        {loading ? <p className="mt-8 text-slate-600">Loading trainer courses…</p> : (
          <div className="mt-7 grid gap-6 lg:grid-cols-2">
            <section className="space-y-5">
              <form className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm" onSubmit={createAssessment}>
                <h2 className="text-xl font-bold">Create course assessment</h2>
                {courses.length === 0 ? (
                  <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">No approved published course versions are assigned to your trainer account.</p>
                ) : (
                  <div className="mt-4 space-y-3">
                    <label className="block text-sm font-medium">Course version
                      <select className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" onChange={(event) => setCourseVersionId(event.target.value)} value={courseVersionId}>
                        {courses.map((course) => <option key={course.course_version_id} value={course.course_version_id}>{course.title} · v{course.version}</option>)}
                      </select>
                    </label>
                    <label className="block text-sm font-medium">Assessment title
                      <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" onChange={(event) => setTitle(event.target.value)} required value={title} />
                    </label>
                    <div className="grid grid-cols-2 gap-3">
                      <label className="block text-sm font-medium">Time limit (minutes)
                        <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" max={180} min={5} onChange={(event) => setTimeLimit(Number(event.target.value))} type="number" value={timeLimit} />
                      </label>
                      <label className="block text-sm font-medium">Target level
                        <select className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" onChange={(event) => setTargetLevel(Number(event.target.value))} value={targetLevel}>
                          {[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>{level}</option>)}
                        </select>
                      </label>
                      <label className="block text-sm font-medium">Minimum questions
                        <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" max={50} min={1} onChange={(event) => setMinQuestions(Number(event.target.value))} type="number" value={minQuestions} />
                      </label>
                      <label className="block text-sm font-medium">Maximum questions
                        <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" max={100} min={1} onChange={(event) => setMaxQuestions(Number(event.target.value))} type="number" value={maxQuestions} />
                      </label>
                    </div>
                    <button className="rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50" disabled={busy || !courseVersionId} type="submit">Create assessment</button>
                  </div>
                )}
              </form>
              <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 className="text-xl font-bold">Your assessments</h2>
                {assessments.length === 0 ? <p className="mt-3 text-sm text-slate-600">No assessments created yet.</p> : (
                  <ul className="mt-3 space-y-2">
                    {assessments.map((item) => (
                      <li key={item.id}>
                        <button className={`w-full rounded-xl border p-3 text-left ${selectedAssessment === item.id ? "border-blue-300 bg-blue-50" : "border-slate-200"}`} onClick={() => setSelectedAssessment(item.id)} type="button">
                          <span className="block font-semibold">{item.title}</span>
                          <span className="mt-1 block text-xs text-slate-600">{item.course_title} · {item.approved_question_count} approved · {item.pending_question_count} pending moderation</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </section>

            <form className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm" onSubmit={createQuestion}>
              <h2 className="text-xl font-bold">Add an assessment question</h2>
              {!selectedAssessment ? <p className="mt-3 text-sm text-slate-600">Create or select an assessment first.</p> : competencies.length === 0 ? (
                <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">This course version has no mapped competencies. Add competency mappings before authoring questions.</p>
              ) : (
                <div className="mt-4 space-y-3">
                  <label className="block text-sm font-medium">Competency
                    <select className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" onChange={(event) => setCompetencyId(event.target.value)} value={competencyId}>
                      {competencies.map((item) => <option key={item.competency_id} value={item.competency_id}>{item.skill_name}</option>)}
                    </select>
                  </label>
                  <label className="block text-sm font-medium">Question type
                    <select className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" onChange={(event) => setQuestionType(event.target.value as typeof questionType)} value={questionType}>
                      <option value="multiple_choice">Multiple choice</option>
                      <option value="multi_select">Multi-select</option>
                      <option value="short_answer">Short answer</option>
                      <option value="scenario">Scenario</option>
                      <option value="code_task">Code task</option>
                    </select>
                  </label>
                  <label className="block text-sm font-medium">Question prompt
                    <textarea className="mt-1 min-h-28 w-full rounded-lg border border-slate-300 p-3" onChange={(event) => setPrompt(event.target.value)} required value={prompt} />
                  </label>
                  {["multiple_choice", "multi_select"].includes(questionType) && (
                    <label className="block text-sm font-medium">Options
                      <textarea className="mt-1 min-h-24 w-full rounded-lg border border-slate-300 p-3" onChange={(event) => setOptions(event.target.value)} placeholder={"One option per line\nOption two\nOption three"} required value={options} />
                    </label>
                  )}
                  <label className="block text-sm font-medium">{questionType === "multi_select" ? "Correct options (comma-separated)" : "Expected answer key"}
                    <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" onChange={(event) => setAnswerKey(event.target.value)} required value={answerKey} />
                  </label>
                  <p className="text-xs text-slate-500">{questionTypeHelp}</p>
                  <label className="block text-sm font-medium">Explanation shown after assessment
                    <textarea className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 p-3" onChange={(event) => setExplanation(event.target.value)} value={explanation} />
                  </label>
                  <label className="block text-sm font-medium">Starting difficulty
                    <select className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2" onChange={(event) => setDifficulty(Number(event.target.value))} value={difficulty}>
                      {[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>Level {level}</option>)}
                    </select>
                  </label>
                  <button className="rounded-xl bg-blue-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50" disabled={busy || !competencyId} type="submit">Submit for admin approval</button>
                </div>
              )}
            </form>
          </div>
        )}
      </div>
    </main>
  );
}
