"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Claim = {
  claim_id: string;
  claim_text: string;
  metric_prompt: string | null;
  user_provided_metric: string | null;
  source_type: string;
  verification: string;
  skill_name: string | null;
};
type Credential = {
  credential_id: string;
  skill_name: string;
  level: number;
  course_title: string | null;
  issued_at: string;
};
type Skill = {
  competency_id: string;
  skill_name: string;
  level: number;
  evidence_status: "claimed" | "provisional" | "verified";
};
type ApplicationQuestion = {
  question_id: string;
  prompt: string;
  answer_type: "text" | "yes_no" | "single_choice";
  options: string[];
  required: boolean;
};
type Preview = {
  job: { job_id: string; title: string; company_name: string };
  claims: Claim[];
  verified_credentials: Credential[];
  skills: Skill[];
  questions: ApplicationQuestion[];
  keyword_check: {
    required_skills: string[];
    job_keywords: string[];
    matched_required_skills: string[];
    missing_required_skills: string[];
    matched_keywords: string[];
    missing_keywords: string[];
  };
  consent_version: string;
};
type ResumeLine = {
  claimId: string | null;
  text: string;
  approved: boolean;
  metric: string;
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
        Authorization: `Bearer ${token}`,
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

export default function ApplicationPreviewPage() {
  const params = useParams<{ jobId: string }>();
  const router = useRouter();
  const jobId = params.jobId;
  const [token, setToken] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [resumeLines, setResumeLines] = useState<ResumeLine[]>([]);
  const [selectedCredentials, setSelectedCredentials] = useState<string[]>([]);
  const [coverLetter, setCoverLetter] = useState("");
  const [answers, setAnswers] = useState<Record<string, string | boolean>>({});
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Sign in with your trainee account to apply.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void request<Preview>(accessToken, `/api/v1/jobs/${jobId}/application-preview`)
      .then((data) => {
        if (!active) return;
        setPreview(data);
        setResumeLines(data.claims.map((claim) => ({
          claimId: claim.claim_id,
          text: claim.claim_text,
          approved: false,
          metric: claim.user_provided_metric ?? "",
        })));
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Could not prepare the application.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [jobId]);

  const approvedLines = useMemo(
    () => resumeLines.filter((line) => line.approved && line.text.trim()),
    [resumeLines],
  );
  const reviewedResumeText = approvedLines
    .map((line) => `${line.text} ${line.metric}`)
    .join(" ")
    .toLocaleLowerCase();
  const containsTerm = (term: string) => {
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?<![\\w+#])${escaped}(?![\\w+#])`, "i").test(reviewedResumeText);
  };
  const matchedRequiredSkills = preview?.keyword_check.required_skills.filter(containsTerm) ?? [];
  const missingRequiredSkills = preview?.keyword_check.required_skills.filter((skill) => !containsTerm(skill)) ?? [];
  const matchedKeywords = preview?.keyword_check.job_keywords.filter(containsTerm) ?? [];

  function updateLine(index: number, update: Partial<ResumeLine>) {
    setResumeLines((current) => current.map((line, lineIndex) =>
      lineIndex === index ? { ...line, ...update } : line,
    ));
  }

  function addCustomLine() {
    setResumeLines((current) => [
      ...current,
      { claimId: null, text: "", approved: false, metric: "" },
    ]);
  }

  function draftCoverLetter() {
    if (!preview) return;
    const statements = approvedLines.map((line) =>
      line.metric.trim() ? `${line.text.trim()} (${line.metric.trim()})` : line.text.trim(),
    );
    const credentials = selectedCredentials
      .map((id) => preview.verified_credentials.find((item) => item.credential_id === id))
      .filter((item): item is Credential => Boolean(item))
      .map((item) => `${item.skill_name} (level ${item.level})`);
    const evidence = [...statements, ...credentials.map((item) => `Verified credential: ${item}`)];
    setCoverLetter(
      [
        `I am applying for ${preview.job.title} at ${preview.job.company_name}.`,
        evidence.length
          ? `My relevant, learner-approved evidence includes:\n${evidence.map((item) => `- ${item}`).join("\n")}`
          : "I am interested in this opportunity. I will add relevant experience that I can personally verify.",
        "Thank you for considering my application.",
      ].join("\n\n"),
    );
  }

  async function downloadPlainResume() {
    setExporting(true);
    setError("");
    try {
      const lines = approvedLines.map((line) =>
        line.metric.trim() ? `${line.text.trim()} (${line.metric.trim()})` : line.text.trim(),
      );
      const skills = preview?.skills ?? [];
      const claimed = skills.filter((skill) => skill.evidence_status !== "verified");
      const verified = skills.filter((skill) => skill.evidence_status === "verified");
      const body = [
        preview?.job.title ?? "Application resume",
        "",
        "Learner-approved experience",
        ...(lines.length ? lines : ["No approved experience statements selected."]),
        "",
        "Verified skills",
        ...(verified.length ? verified.map((skill) => `${skill.skill_name} — level ${skill.level}`) : ["None listed"]),
        "",
        "Claimed skills",
        ...(claimed.length ? claimed.map((skill) => `${skill.skill_name} — level ${skill.level} (claimed, not verified)`) : ["None listed"]),
        "",
        "Verified credentials",
        ...((preview?.verified_credentials ?? [])
          .filter((credential) => selectedCredentials.includes(credential.credential_id))
          .map((credential) => `${credential.skill_name} — level ${credential.level}`)),
      ].join("\n");
      const url = URL.createObjectURL(new Blob([body], { type: "text/plain;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "application-resume.txt";
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Could not export the plain-text resume.");
    } finally {
      setExporting(false);
    }
  }

  async function submitApplication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preview || !consent) {
      setError("Review and accept the profile-sharing consent before submitting.");
      return;
    }
    if (approvedLines.length === 0) {
      setError("Add and approve at least one resume line that you can personally confirm.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const result = await request<{ application_id: string }>(
        token,
        `/api/v1/jobs/${jobId}/applications`,
        {
          method: "POST",
          body: JSON.stringify({
            resume_lines: approvedLines.map((line) => ({
              claim_id: line.claimId,
              text: line.metric.trim() ? `${line.text.trim()} — ${line.metric.trim()}` : line.text.trim(),
              approved_by_learner: true,
            })),
            cover_letter: coverLetter.trim() || null,
            selected_credential_ids: selectedCredentials,
            share_profile_consent: consent,
            extra_answers: answers,
          }),
        },
      );
      router.push(`/applications?submitted=${encodeURIComponent(result.application_id)}`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not submit the application.");
    } finally {
      setSubmitting(false);
    }
  }

  const claimedSkills = preview?.skills.filter((skill) => skill.evidence_status !== "verified") ?? [];
  const verifiedSkills = preview?.skills.filter((skill) => skill.evidence_status === "verified") ?? [];

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
      <section className="mx-auto max-w-4xl">
        <nav className="flex flex-wrap gap-4 text-sm font-semibold">
          <Link className="text-blue-700 underline" href="/jobs">Job explorer</Link>
          <Link className="text-blue-700 underline" href="/applications">My applications</Link>
          <Link className="text-blue-700 underline" href="/">Skill Passport</Link>
        </nav>
        <header className="mt-7">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-700">Capacity Connect · Stage 12</p>
          <h1 className="mt-2 text-3xl font-bold text-slate-950">Review your application</h1>
          <p className="mt-2 text-slate-600">Nothing is submitted until you approve every resume line and confirm the profile-sharing consent.</p>
        </header>
        {error && <p className="mt-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-800" role="alert">{error}</p>}
        {loading && <p className="mt-6 text-slate-600">Preparing your application preview…</p>}
        {preview && (
          <form className="mt-6 space-y-5" onSubmit={(event) => void submitApplication(event)}>
            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <h2 className="text-xl font-bold">{preview.job.title}</h2>
              <p className="mt-1 text-slate-600">{preview.job.company_name}</p>
              <p className="mt-3 text-sm text-slate-600">Keyword check updates from the lines you have approved below. Missing terms are suggestions only; add them only if accurate.</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl bg-emerald-50 p-3 text-sm">
                  <h3 className="font-bold text-emerald-950">Matched required skills</h3>
                  <p className="mt-1 text-emerald-900">{matchedRequiredSkills.join(", ") || "None in approved lines yet"}</p>
                  <p className="mt-2 text-xs text-emerald-800">Job description terms present: {matchedKeywords.join(", ") || "None yet"}</p>
                </div>
                <div className="rounded-xl bg-amber-50 p-3 text-sm">
                  <h3 className="font-bold text-amber-950">Not present in evidence</h3>
                  <p className="mt-1 text-amber-900">{missingRequiredSkills.join(", ") || "All listed job skills appear in the approved lines"}</p>
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-bold">Evidence-first resume</h2>
                  <p className="mt-1 text-sm text-slate-600">Only learner-approved claims are prefilled. No experience or metric is generated.</p>
                </div>
                <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50" disabled={exporting} onClick={() => void downloadPlainResume()} type="button">
                  {exporting ? "Exporting…" : "Export plain-text preview"}
                </button>
              </div>
              <div className="mt-4 space-y-4">
                {resumeLines.map((line, index) => {
                  const claim = preview.claims.find((item) => item.claim_id === line.claimId);
                  return (
                    <div className="rounded-xl border border-slate-200 p-4" key={`${line.claimId ?? "custom"}-${index}`}>
                      <label className="block text-sm font-semibold text-slate-800">
                        Resume line
                        <textarea className="mt-1 w-full rounded-lg border border-slate-300 p-3 font-normal" maxLength={1200} onChange={(event) => updateLine(index, { text: event.target.value })} rows={3} value={line.text} />
                      </label>
                      <label className="mt-3 block text-sm font-semibold text-slate-800">
                        Measurable result (optional; include only a number you can verify)
                        <span className="mt-1 block font-normal text-slate-600">
                          {claim?.metric_prompt ?? "Could you quantify the outcome—for example, users supported, time saved, or percentage improved?"}
                        </span>
                        <input className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" onChange={(event) => updateLine(index, { metric: event.target.value })} placeholder="Your verified result, or leave blank" value={line.metric} />
                      </label>
                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs text-slate-500">
                          {claim ? `Source: ${claim.source_type.replaceAll("_", " ")} · ${claim.verification}` : "Custom line: confirm that every statement is yours and accurate."}
                        </p>
                        <button className="text-sm font-semibold text-rose-700 underline" onClick={() => setResumeLines((current) => current.filter((_, lineIndex) => lineIndex !== index))} type="button">Remove</button>
                      </div>
                      <label className="mt-3 flex items-start gap-2 text-sm text-slate-700">
                        <input checked={line.approved} onChange={(event) => updateLine(index, { approved: event.target.checked })} type="checkbox" />
                        I reviewed this line and confirm it is accurate.
                      </label>
                    </div>
                  );
                })}
              </div>
              <button className="mt-4 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={addCustomLine} type="button">Add my own line</button>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <h2 className="text-xl font-bold">Passport skills and credentials</h2>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div>
                  <h3 className="font-semibold text-slate-900">Verified skills</h3>
                  <ul className="mt-2 space-y-1 text-sm text-slate-700">
                    {verifiedSkills.map((skill) => <li key={skill.competency_id}>{skill.skill_name} · level {skill.level} · verified</li>)}
                    {verifiedSkills.length === 0 && <li className="text-slate-500">None recorded</li>}
                  </ul>
                </div>
                <div>
                  <h3 className="font-semibold text-slate-900">Claimed / provisional skills (not verified)</h3>
                  <ul className="mt-2 space-y-1 text-sm text-slate-700">
                    {claimedSkills.map((skill) => <li key={skill.competency_id}>{skill.skill_name} · level {skill.level} · {skill.evidence_status}</li>)}
                    {claimedSkills.length === 0 && <li className="text-slate-500">None recorded</li>}
                  </ul>
                </div>
              </div>
              <h3 className="mt-5 font-semibold">Attach verified credentials</h3>
              <div className="mt-2 space-y-2">
                {preview.verified_credentials.map((credential) => (
                  <label className="flex items-start gap-2 rounded-lg border border-slate-200 p-3 text-sm" key={credential.credential_id}>
                    <input checked={selectedCredentials.includes(credential.credential_id)} onChange={(event) => setSelectedCredentials((current) => event.target.checked ? [...current, credential.credential_id] : current.filter((id) => id !== credential.credential_id))} type="checkbox" />
                    <span>{credential.skill_name} · level {credential.level} · verified{credential.course_title ? ` · ${credential.course_title}` : ""}</span>
                  </label>
                ))}
                {preview.verified_credentials.length === 0 && <p className="text-sm text-slate-500">No current verified credentials to attach.</p>}
              </div>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-bold">Optional cover letter</h2>
                  <p className="mt-1 text-sm text-slate-600">The template uses only the evidence lines and credentials you selected. Edit or remove it before applying.</p>
                </div>
                <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={draftCoverLetter} type="button">Draft from selected evidence</button>
              </div>
              <textarea className="mt-4 w-full rounded-lg border border-slate-300 p-3" maxLength={8000} onChange={(event) => setCoverLetter(event.target.value)} placeholder="Optional. Write only claims you can support." rows={8} value={coverLetter} />
            </section>

            {preview.questions.length > 0 && (
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <h2 className="text-xl font-bold">Employer questions</h2>
                <div className="mt-4 space-y-4">
                  {preview.questions.map((question) => (
                    <label className="block text-sm font-semibold text-slate-800" key={question.question_id}>
                      {question.prompt}{question.required ? " *" : ""}
                      {question.answer_type === "text" ? (
                        <textarea className="mt-1 w-full rounded-lg border border-slate-300 p-3 font-normal" maxLength={2000} onChange={(event) => setAnswers({ ...answers, [question.question_id]: event.target.value })} required={question.required} rows={3} value={String(answers[question.question_id] ?? "")} />
                      ) : (
                        <select className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" onChange={(event) => setAnswers({ ...answers, [question.question_id]: question.answer_type === "yes_no" ? event.target.value === "true" : event.target.value })} required={question.required} value={answers[question.question_id] === undefined ? "" : String(answers[question.question_id])}>
                          <option value="">Choose an answer</option>
                          {(question.answer_type === "yes_no" ? ["true", "false"] : question.options).map((option) => <option key={option} value={option}>{option === "true" ? "Yes" : option === "false" ? "No" : option}</option>)}
                        </select>
                      )}
                    </label>
                  ))}
                </div>
              </section>
            )}

            <section className="rounded-2xl border border-amber-300 bg-amber-50 p-5">
              <h2 className="text-lg font-bold text-amber-950">Profile-sharing consent</h2>
              <p className="mt-2 text-sm text-amber-950">
                By applying, you consent to share the skills in your Passport, clearly separated as claimed or verified, the verified credentials you selected, and your approved resume and cover-letter text with {preview.job.company_name} for this application. Your login email and unrelated Passport sections are not included in this application snapshot.
              </p>
              <label className="mt-4 flex items-start gap-2 text-sm font-semibold text-amber-950">
                <input checked={consent} onChange={(event) => setConsent(event.target.checked)} type="checkbox" />
                I consent to this application-specific profile sharing and have reviewed the content.
              </label>
            </section>

            <div className="flex flex-wrap gap-3">
              <button className="rounded-xl bg-blue-700 px-5 py-3 font-semibold text-white disabled:opacity-50" disabled={submitting || !consent} type="submit">
                {submitting ? "Submitting…" : "Submit application"}
              </button>
              <Link className="rounded-xl border border-slate-300 bg-white px-5 py-3 font-semibold" href="/jobs">Back to jobs</Link>
            </div>
          </form>
        )}
      </section>
    </main>
  );
}
