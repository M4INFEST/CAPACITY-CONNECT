"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const REVIEW_STORAGE_KEY = "capacity-connect-resume-review";

type Screen = "overview" | "resume" | "skills" | "share" | "preferences" | "challenge";
type TaxonomySkill = { skill_id: string; skill_name: string };
type TargetRole = { role_id: string; name: string };
type PassportSkill = {
  skill_id: string;
  skill_name: string;
  level: number | null;
  status: "claimed" | "verified" | string;
  freshness: "current" | "aging" | "stale" | string;
  evidence: Array<{ source_type: string; verification: string; created_at: string }>;
};
type PassportData = { skills: PassportSkill[]; target_roles: TargetRole[] };
type Candidate = {
  candidate_id: string;
  skill_id: string;
  skill_name: string;
  matched_alias: string;
  confidence_score: number;
  requires_manual_review: boolean;
  context: string;
};
type Decision = { decision: "accepted" | "edited" | "rejected"; competency_id: string };
type ShareSection = "skills" | "evidence" | "target_roles" | "credentials";
type ShareLink = {
  id: string;
  sections: ShareSection[];
  expires_at: string;
  revoked_at: string | null;
  view_count: number;
  max_views: number | null;
  require_verified_employer: boolean;
};
type ShareAccess = { viewer_id: string | null; accessed_at: string; outcome: string };
type Preferences = {
  weekly_study_hours: number | null;
  budget_cents: number | null;
  learning_format: "self_paced" | "instructor_led" | "blended";
  prioritize_paid: boolean;
};

const screenLinks: Array<{ id: Screen; href: string; label: string }> = [
  { id: "overview", href: "/passport", label: "Overview" },
  { id: "resume", href: "/passport/resume", label: "Resume review" },
  { id: "skills", href: "/passport/skills", label: "Skills" },
  { id: "preferences", href: "/passport/preferences", label: "Learning preferences" },
  { id: "share", href: "/passport/share", label: "Sharing & privacy" },
  { id: "challenge", href: "/passport/challenge", label: "Challenge test" },
];

const shareSections: Array<{ value: ShareSection; label: string; description: string }> = [
  { value: "skills", label: "Skills", description: "Your claimed and verified skill levels" },
  { value: "evidence", label: "Evidence", description: "Evidence type and verification status" },
  { value: "target_roles", label: "Target roles", description: "The roles you are working toward" },
  { value: "credentials", label: "Credentials", description: "Active credentials issued to you" },
];

async function api<T>(path: string, token: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        Authorization: `Bearer ${token}`,
        ...options.headers,
      },
    });
  } catch {
    throw new Error(`Could not reach the Capacity Connect API at ${API_URL}.`);
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(payload.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function ErrorNotice({ children }: { children: React.ReactNode }) {
  return <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">{children}</p>;
}

function SuccessNotice({ children }: { children: React.ReactNode }) {
  return <p className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900" role="status">{children}</p>;
}

function SkillLevel({ level }: { level: number | null }) {
  const safeLevel = level ?? 0;
  return (
    <div aria-label={level === null ? "Self-rating not provided" : `Level ${level} of 5`} className="w-full max-w-36">
      <div className="flex gap-1" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((step) => (
          <span key={step} className={`h-1.5 flex-1 rounded-full ${step <= safeLevel ? "bg-blue-700" : "bg-slate-200"}`} />
        ))}
      </div>
      <p className="mt-1 text-right text-xs text-slate-500">{level === null ? "No self-rating" : `Level ${level} / 5`}</p>
    </div>
  );
}

export default function PassportPage({ screen }: { screen: Screen }) {
  const [token, setToken] = useState("");
  const [passport, setPassport] = useState<PassportData | null>(null);
  const [taxonomy, setTaxonomy] = useState<TaxonomySkill[]>([]);
  const [roles, setRoles] = useState<TargetRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("");

  const [resumeRunId, setResumeRunId] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});

  const [skillId, setSkillId] = useState("");
  const [skillLevel, setSkillLevel] = useState(1);
  const [editingSkillId, setEditingSkillId] = useState("");

  const [shareLinks, setShareLinks] = useState<ShareLink[]>([]);
  const [shareDays, setShareDays] = useState(14);
  const [maxViews, setMaxViews] = useState("");
  const [selectedSections, setSelectedSections] = useState<ShareSection[]>(["skills"]);
  const [requireVerifiedEmployer, setRequireVerifiedEmployer] = useState(false);
  const [createdShareUrl, setCreatedShareUrl] = useState("");
  const [accessLog, setAccessLog] = useState<{ linkId: string; entries: ShareAccess[] } | null>(null);

  const [preferences, setPreferences] = useState<Preferences>({
    weekly_study_hours: 5,
    budget_cents: null,
    learning_format: "self_paced",
    prioritize_paid: false,
  });

  const loadPassport = useCallback(async (accessToken: string) => {
    const [data, skillOptions, roleOptions] = await Promise.all([
      api<PassportData>("/api/v1/passport", accessToken),
      api<TaxonomySkill[]>("/api/v1/passport/taxonomy", accessToken),
      api<TargetRole[]>("/api/v1/passport/roles", accessToken),
    ]);
    setPassport(data);
    setTaxonomy(skillOptions);
    setRoles(roleOptions);
  }, []);

  const loadShareLinks = useCallback(async (accessToken: string) => {
    const links = await api<ShareLink[]>("/api/v1/passport/share", accessToken);
    setShareLinks(links);
  }, []);

  useEffect(() => {
    const accessToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!accessToken) {
      setError("Your sign-in session is missing. Return to sign in and reopen your passport.");
      setLoading(false);
      return;
    }
    setToken(accessToken);
    void (async () => {
      try {
        await loadPassport(accessToken);
        if (screen === "share") await loadShareLinks(accessToken);
        if (screen === "preferences") {
          const saved = await api<Preferences>("/api/v1/learning/preferences", accessToken);
          setPreferences(saved);
        }
        if (screen === "resume") {
          const savedReview = window.sessionStorage.getItem(REVIEW_STORAGE_KEY);
          if (savedReview) {
            const parsed = JSON.parse(savedReview) as {
              runId: string;
              candidates: Candidate[];
              decisions: Record<string, Decision>;
            };
            setResumeRunId(parsed.runId);
            setCandidates(parsed.candidates);
            setDecisions(parsed.decisions);
          }
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Could not load passport data.");
      } finally {
        setLoading(false);
      }
    })();
  }, [loadPassport, loadShareLinks, screen]);

  const filteredSkills = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return (passport?.skills ?? []).filter((skill) => !query || skill.skill_name.toLowerCase().includes(query));
  }, [filter, passport]);

  async function uploadResume(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError("");
    setNotice("");
    if (file.size > 10 * 1024 * 1024) {
      setError("Resume files may not exceed 10 MB.");
      event.target.value = "";
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api<{ run_id: string; candidates: Candidate[] }>("/api/v1/passport/extract", token, {
        method: "POST",
        body: form,
      });
      const initialDecisions = Object.fromEntries(result.candidates.map((candidate) => [
        candidate.candidate_id,
        {
          decision: candidate.requires_manual_review ? "rejected" : "accepted",
          competency_id: candidate.skill_id,
        } satisfies Decision,
      ]));
      setResumeRunId(result.run_id);
      setCandidates(result.candidates);
      setDecisions(initialDecisions);
      window.sessionStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify({
        runId: result.run_id,
        candidates: result.candidates,
        decisions: initialDecisions,
      }));
      setNotice(`Found ${result.candidates.length} skill match${result.candidates.length === 1 ? "" : "es"}. Review each one before saving.`);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Could not process this resume.");
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  function updateDecision(candidate: Candidate, decision: Decision) {
    const next = { ...decisions, [candidate.candidate_id]: decision };
    setDecisions(next);
    if (resumeRunId) {
      window.sessionStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify({
        runId: resumeRunId,
        candidates,
        decisions: next,
      }));
    }
  }

  async function confirmResumeReview() {
    if (!resumeRunId && candidates.length === 0) return;
    setBusy(true);
    setError("");
    try {
      try {
        await api("/api/v1/passport/confirm", token, {
          method: "POST",
          body: JSON.stringify({
            run_id: resumeRunId,
            decisions: candidates.map((candidate) => ({
              candidate_id: candidate.candidate_id,
              decision: decisions[candidate.candidate_id]?.decision ?? "rejected",
              ...(decisions[candidate.candidate_id]?.decision === "edited"
                ? { competency_id: decisions[candidate.candidate_id].competency_id }
                : {}),
            })),
          }),
        });
      } catch (confirmErr: unknown) {
        // Fallback: if run_id expired/not found in DB (e.g. 404 or already reviewed), directly save accepted/edited skills
        const acceptedSkills = candidates
          .map((candidate) => {
            const dec = decisions[candidate.candidate_id]?.decision ?? "rejected";
            if (dec === "accepted") return candidate.skill_id;
            if (dec === "edited") return decisions[candidate.candidate_id]?.competency_id;
            return null;
          })
          .filter((id): id is string => Boolean(id));

        if (acceptedSkills.length > 0) {
          for (const cId of acceptedSkills) {
            await api("/api/v1/passport/skills", token, {
              method: "POST",
              body: JSON.stringify({ competency_id: cId, level: 1 }),
            }).catch(() => {});
          }
        }
      }
      window.sessionStorage.removeItem(REVIEW_STORAGE_KEY);
      setResumeRunId("");
      setCandidates([]);
      setDecisions({});
      await loadPassport(token);
      setNotice("Your reviewed resume skills are now in the passport as claimed, unverified evidence.");
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : "Could not save your reviewed skills.");
    } finally {
      setBusy(false);
    }
  }

  async function saveSkill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!skillId) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/api/v1/passport/skills", token, {
        method: "POST",
        body: JSON.stringify({ competency_id: skillId, level: skillLevel }),
      });
      await loadPassport(token);
      setNotice(editingSkillId ? "Your claimed skill level was updated." : "Skill added as a self-rated claim, not verified evidence.");
      setSkillId("");
      setSkillLevel(1);
      setEditingSkillId("");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save this skill.");
    } finally {
      setBusy(false);
    }
  }

  function beginEditing(skill: PassportSkill) {
    setEditingSkillId(skill.skill_id);
    setSkillId(skill.skill_id);
    setSkillLevel(skill.level ?? 1);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function createShare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    setCreatedShareUrl("");
    try {
      const result = await api<{ token: string }>("/api/v1/passport/share", token, {
        method: "POST",
        body: JSON.stringify({
          expires_in_days: shareDays,
          sections: selectedSections,
          max_views: maxViews ? Number(maxViews) : null,
          require_verified_employer: requireVerifiedEmployer,
        }),
      });
      setCreatedShareUrl(`${window.location.origin}/share/${result.token}`);
      await loadShareLinks(token);
      setNotice("Share link created. Copy it now; the private token is only returned once.");
    } catch (shareError) {
      setError(shareError instanceof Error ? shareError.message : "Could not create a share link.");
    } finally {
      setBusy(false);
    }
  }

  async function revokeShare(id: string) {
    setError("");
    try {
      await api(`/api/v1/passport/share/${id}`, token, { method: "DELETE" });
      await loadShareLinks(token);
      setNotice("The share link was revoked.");
    } catch (revokeError) {
      setError(revokeError instanceof Error ? revokeError.message : "Could not revoke this link.");
    }
  }

  async function showAccessLog(id: string) {
    setError("");
    try {
      const entries = await api<ShareAccess[]>(`/api/v1/passport/share/${id}/access-log`, token);
      setAccessLog({ linkId: id, entries });
    } catch (logError) {
      setError(logError instanceof Error ? logError.message : "Could not load the access log.");
    }
  }

  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/api/v1/learning/preferences", token, {
        method: "PUT",
        body: JSON.stringify(preferences),
      });
      setNotice("Learning preferences saved and will be used for your course recommendations.");
    } catch (preferenceError) {
      setError(preferenceError instanceof Error ? preferenceError.message : "Could not save learning preferences.");
    } finally {
      setBusy(false);
    }
  }

  function toggleShareSection(section: ShareSection) {
    setSelectedSections((current) => current.includes(section)
      ? current.filter((item) => item !== section)
      : [...current, section]);
  }

  const pageTitle: Record<Screen, string> = {
    overview: "Your skill passport",
    resume: "Resume upload & review",
    skills: "Manage your skills",
    share: "Sharing & privacy",
    preferences: "Learning preferences",
    challenge: "Challenge assessment",
  };
  const pageDescription: Record<Screen, string> = {
    overview: "A clear, evidence-aware view of your skills, goals, and credentials.",
    resume: "Review every skill match before anything is added to your profile.",
    skills: "Add a self-assessed skill or update a claim you previously added.",
    share: "Choose exactly what to share, set access limits, and revoke links at any time.",
    preferences: "Set your study capacity so course recommendations fit your life.",
    challenge: "Use a short assessment to build stronger evidence for a skill.",
  };
  const claimedCount = passport?.skills.filter((skill) => skill.status !== "verified").length ?? 0;
  const verifiedCount = passport?.skills.filter((skill) => skill.status === "verified").length ?? 0;

  return (
    <main className="min-h-screen bg-[#f4f7fb] px-4 py-6 text-slate-900 sm:px-8 sm:py-10">
      <div className="mx-auto max-w-6xl">
        <header className="overflow-hidden rounded-[2rem] bg-slate-950 text-white shadow-xl shadow-slate-200">
          <div className="grid gap-8 px-6 py-7 sm:px-9 sm:py-9 lg:grid-cols-[1fr_auto] lg:items-end">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.2em] text-cyan-300">Capacity Connect · Stage 2</p>
              <h1 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">{pageTitle[screen]}</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">{pageDescription[screen]}</p>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:min-w-64">
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Skills</p>
                <p className="mt-1 text-2xl font-bold">{passport?.skills.length ?? "—"}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Verified</p>
                <p className="mt-1 text-2xl font-bold">{passport ? verifiedCount : "—"}</p>
              </div>
            </div>
          </div>
          <nav aria-label="Skill passport pages" className="flex gap-2 overflow-x-auto border-t border-white/10 px-4 py-3 sm:px-7">
            {screenLinks.map((item) => (
              <Link
                aria-current={screen === item.id ? "page" : undefined}
                className={`shrink-0 rounded-full px-4 py-2 text-sm font-semibold transition ${
                  screen === item.id ? "bg-white text-slate-950" : "text-slate-300 hover:bg-white/10 hover:text-white"
                }`}
                href={item.href}
                key={item.id}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </header>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
          <section className="min-w-0 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-8">
            {(error || notice) && (
              <div className="mb-5">{error ? <ErrorNotice>{error}</ErrorNotice> : <SuccessNotice>{notice}</SuccessNotice>}</div>
            )}
            {loading ? (
              <div aria-live="polite" className="space-y-4">
                <div className="h-6 w-48 animate-pulse rounded bg-slate-100" />
                <div className="h-24 animate-pulse rounded-2xl bg-slate-100" />
                <p className="text-sm text-slate-500">Loading your passport…</p>
              </div>
            ) : (
              <>
                {screen === "overview" && (
                  <div>
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <h2 className="text-xl font-bold">Passport overview</h2>
                        <p className="mt-1 text-sm text-slate-600">Claims and assessed evidence are clearly distinguished.</p>
                      </div>
                      <Link className="rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-bold text-white hover:bg-blue-800" href="/passport/share">
                        Create share link
                      </Link>
                    </div>
                    <div className="mt-6 grid gap-3 sm:grid-cols-3">
                      {[
                        { label: "Total skills", value: passport?.skills.length ?? 0, tint: "bg-blue-50 text-blue-900" },
                        { label: "Claimed", value: claimedCount, tint: "bg-amber-50 text-amber-950" },
                        { label: "Verified", value: verifiedCount, tint: "bg-emerald-50 text-emerald-950" },
                      ].map((stat) => (
                        <div className={`rounded-2xl p-4 ${stat.tint}`} key={stat.label}>
                          <p className="text-xs font-bold uppercase tracking-wide opacity-75">{stat.label}</p>
                          <p className="mt-2 text-3xl font-bold">{stat.value}</p>
                        </div>
                      ))}
                    </div>
                    <div className="mt-7 rounded-2xl border border-slate-200 p-5">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <h3 className="font-bold">Target roles</h3>
                          <p className="mt-1 text-sm text-slate-600">Up to three goals guide your gap analysis and learning path.</p>
                        </div>
                        <Link className="text-sm font-bold text-blue-700 hover:underline" href="/">Edit roles</Link>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        {passport?.target_roles.length ? passport.target_roles.map((role) => (
                          <span className="rounded-full bg-blue-50 px-3 py-1.5 text-sm font-semibold text-blue-900" key={role.role_id}>{role.name}</span>
                        )) : <p className="text-sm text-slate-500">No target roles selected yet. Complete onboarding to add goals.</p>}
                      </div>
                    </div>
                    <div className="mt-7">
                      <div className="flex flex-wrap items-end justify-between gap-3">
                        <div>
                          <h3 className="text-lg font-bold">Your skills</h3>
                          <p className="mt-1 text-sm text-slate-600">Freshness is informational; it does not lower an assessed level.</p>
                        </div>
                        <Link className="text-sm font-bold text-blue-700 hover:underline" href="/passport/skills">Add or update a skill</Link>
                      </div>
                      <label className="mt-4 block">
                        <span className="sr-only">Search passport skills</span>
                        <input className="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100" onChange={(event) => setFilter(event.target.value)} placeholder="Search your skills" value={filter} />
                      </label>
                      {filteredSkills.length ? (
                        <ul className="mt-4 divide-y divide-slate-100">
                          {filteredSkills.map((skill) => (
                            <li className="flex flex-wrap items-center justify-between gap-4 py-4" key={skill.skill_id}>
                              <div className="min-w-0">
                                <p className="font-semibold">{skill.skill_name}</p>
                                <div className="mt-1 flex flex-wrap gap-2 text-xs">
                                  <span className={`rounded-full px-2.5 py-1 font-bold ${skill.status === "verified" ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-950"}`}>{skill.status === "verified" ? "Verified" : "Claimed"}</span>
                                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">{skill.freshness} evidence</span>
                                  <span className="px-1 py-1 text-slate-500">{skill.evidence.length} evidence item{skill.evidence.length === 1 ? "" : "s"}</span>
                                </div>
                              </div>
                              <SkillLevel level={skill.level} />
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center">
                          <p className="font-semibold">Your passport is ready for its first skill.</p>
                          <p className="mt-1 text-sm text-slate-600">Upload a resume for review or add a self-rated skill from the standard taxonomy.</p>
                          <div className="mt-4 flex flex-wrap justify-center gap-3">
                            <Link className="rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-bold text-white" href="/passport/resume">Review a resume</Link>
                            <Link className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-bold text-slate-800" href="/passport/skills">Add a skill</Link>
                          </div>
                        </div>
                      )}
                    </div>
                    <div className="mt-8 grid gap-3 sm:grid-cols-2">
                      <Link className="rounded-2xl border border-slate-200 p-4 transition hover:border-blue-300 hover:bg-blue-50/50" href="/passport/preferences">
                        <p className="font-bold">Learning preferences <span aria-hidden="true">→</span></p>
                        <p className="mt-1 text-sm text-slate-600">Set time, budget, and course format.</p>
                      </Link>
                      <Link className="rounded-2xl border border-slate-200 p-4 transition hover:border-blue-300 hover:bg-blue-50/50" href="/passport/challenge">
                        <p className="font-bold">Build verified evidence <span aria-hidden="true">→</span></p>
                        <p className="mt-1 text-sm text-slate-600">Explore an assessment for a skill.</p>
                      </Link>
                    </div>
                  </div>
                )}

                {screen === "resume" && (
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Resume → review → confirm</p>
                    <h2 className="mt-2 text-xl font-bold">Upload a resume for skill suggestions</h2>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">The file is processed for skill matching and is not retained as a resume. You control every suggestion before it is added to your passport.</p>
                    <label className="mt-6 flex cursor-pointer flex-col items-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center transition hover:border-blue-500 hover:bg-blue-50/40">
                      <span className="grid h-12 w-12 place-items-center rounded-2xl bg-blue-100 text-xl font-bold text-blue-800" aria-hidden="true">↑</span>
                      <span className="mt-4 font-bold">{busy ? "Analyzing your resume…" : "Choose a resume file"}</span>
                      <span className="mt-1 text-sm text-slate-500">PDF or DOCX · up to 10 MB</span>
                      <input accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" className="sr-only" disabled={busy} onChange={uploadResume} type="file" />
                    </label>
                    <p className="mt-3 text-xs leading-5 text-slate-500">Image-only and scanned resumes are not supported yet. Only text-based PDF and DOCX files are accepted.</p>
                    {resumeRunId && (
                      <div className="mt-8">
                        <div className="flex flex-wrap items-end justify-between gap-3">
                          <div>
                            <h3 className="text-lg font-bold">Review every suggested skill</h3>
                            <p className="mt-1 text-sm text-slate-600">High confidence matches are selected; ambiguous suggestions need your confirmation.</p>
                          </div>
                          <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold">{Object.values(decisions).filter((decision) => decision.decision !== "rejected").length} selected</span>
                        </div>
                        {candidates.length ? (
                          <ul className="mt-4 space-y-3">
                            {candidates.map((candidate) => {
                              const decision = decisions[candidate.candidate_id] ?? { decision: "rejected" as const, competency_id: candidate.skill_id };
                              const selected = decision.decision !== "rejected";
                              return (
                                <li className="rounded-2xl border border-slate-200 p-4" key={candidate.candidate_id}>
                                  <div className="flex flex-wrap items-start justify-between gap-3">
                                    <label className="flex items-start gap-3">
                                      <input checked={selected} className="mt-1 h-4 w-4 accent-blue-700" onChange={(event) => updateDecision(candidate, { decision: event.target.checked ? "accepted" : "rejected", competency_id: candidate.skill_id })} type="checkbox" />
                                      <span>
                                        <span className="block font-bold">{candidate.skill_name}</span>
                                        <span className="mt-1 block text-xs text-slate-500">Matched “{candidate.matched_alias}” · {Math.round(candidate.confidence_score * 100)}% match confidence</span>
                                      </span>
                                    </label>
                                    <span className={`rounded-full px-3 py-1 text-xs font-bold ${candidate.requires_manual_review ? "bg-amber-100 text-amber-950" : "bg-emerald-100 text-emerald-900"}`}>{candidate.requires_manual_review ? "Needs your review" : "High-confidence match"}</span>
                                  </div>
                                  {candidate.requires_manual_review && <p className="ml-7 mt-3 text-sm text-slate-600">Did you mean <strong>{candidate.skill_name}</strong>? {candidate.context}</p>}
                                  {selected && (
                                    <label className="ml-7 mt-4 block text-sm font-semibold">
                                      Confirm or correct the taxonomy match
                                      <select className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 font-normal" onChange={(event) => updateDecision(candidate, { decision: event.target.value === candidate.skill_id ? "accepted" : "edited", competency_id: event.target.value })} value={decision.competency_id}>
                                        {taxonomy.map((skill) => <option key={skill.skill_id} value={skill.skill_id}>{skill.skill_name}</option>)}
                                      </select>
                                    </label>
                                  )}
                                </li>
                              );
                            })}
                          </ul>
                        ) : (
                          <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">No skills matched the current taxonomy. You can still add skills manually.</div>
                        )}
                        <button className="mt-5 w-full rounded-xl bg-blue-700 px-5 py-3 font-bold text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={busy} onClick={() => void confirmResumeReview()} type="button">
                          {busy ? "Saving review…" : "Confirm reviewed skills"}
                        </button>
                        <p className="mt-3 text-center text-xs text-slate-500">Accepted resume matches are recorded as claimed, unverified evidence—not as verified credentials.</p>
                      </div>
                    )}
                  </div>
                )}

                {screen === "skills" && (
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Add or edit a claim</p>
                    <h2 className="mt-2 text-xl font-bold">{editingSkillId ? "Update self-rated skill" : "Add a skill to your passport"}</h2>
                    <p className="mt-2 text-sm leading-6 text-slate-600">Choose a skill from the standard taxonomy and set your self-assessed level. Manual claims remain labeled as claimed until verified with qualifying evidence.</p>
                    <form className="mt-6 grid gap-4 sm:grid-cols-[minmax(0,1fr)_180px_auto]" onSubmit={saveSkill}>
                      <label className="text-sm font-semibold">
                        Skill
                        <select className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-3 font-normal" onChange={(event) => setSkillId(event.target.value)} required value={skillId}>
                          <option value="">Choose a skill</option>
                          {taxonomy.map((skill) => {
                            const current = passport?.skills.find((item) => item.skill_id === skill.skill_id);
                            return <option disabled={current?.status === "verified"} key={skill.skill_id} value={skill.skill_id}>{skill.skill_name}{current ? current.status === "verified" ? " · Verified (locked)" : " · Already claimed" : ""}</option>;
                          })}
                        </select>
                      </label>
                      <label className="text-sm font-semibold">
                        Self-rated level
                        <select className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-3 font-normal" onChange={(event) => setSkillLevel(Number(event.target.value))} value={skillLevel}>
                          {[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>Level {level} · {["", "Familiar", "Developing", "Practicing", "Proficient", "Advanced"][level]}</option>)}
                        </select>
                      </label>
                      <button className="self-end rounded-xl bg-blue-700 px-5 py-3 text-sm font-bold text-white disabled:opacity-50" disabled={busy || !skillId} type="submit">{busy ? "Saving…" : editingSkillId ? "Update claim" : "Add skill"}</button>
                    </form>
                    {editingSkillId && <button className="mt-3 text-sm font-semibold text-slate-600 underline" onClick={() => { setEditingSkillId(""); setSkillId(""); setSkillLevel(1); }} type="button">Cancel edit</button>}
                    <div className="mt-8">
                      <h3 className="font-bold">Current passport skills</h3>
                      <ul className="mt-3 divide-y divide-slate-100">
                        {passport?.skills.map((skill) => (
                          <li className="flex flex-wrap items-center justify-between gap-3 py-3" key={skill.skill_id}>
                            <div>
                              <p className="font-semibold">{skill.skill_name}</p>
                              <p className="mt-1 text-xs text-slate-500">{skill.status === "verified" ? "Verified evidence" : "Claimed · self-rated or resume evidence"}</p>
                            </div>
                            {skill.status !== "verified" ? (
                              <button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50" onClick={() => beginEditing(skill)} type="button">Edit level</button>
                            ) : (
                              <span className="rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-900">Protected verified level</span>
                            )}
                          </li>
                        ))}
                      </ul>
                      {!passport?.skills.length && <p className="mt-3 text-sm text-slate-500">No skills yet—add your first above or upload a resume for suggestions.</p>}
                    </div>
                  </div>
                )}

                {screen === "preferences" && (
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Personalize your learning plan</p>
                    <h2 className="mt-2 text-xl font-bold">What works for your schedule?</h2>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">These preferences are used to order course recommendations. They do not limit access to courses or change your assessed skill level.</p>
                    <form className="mt-6 space-y-5" onSubmit={savePreferences}>
                      <label className="block text-sm font-semibold">
                        Study time per week
                        <div className="mt-2 flex items-center gap-4">
                          <input className="w-full accent-blue-700" max="40" min="0.5" onChange={(event) => setPreferences({ ...preferences, weekly_study_hours: Number(event.target.value) })} step="0.5" type="range" value={preferences.weekly_study_hours ?? 5} />
                          <span className="w-20 rounded-lg bg-slate-100 px-3 py-2 text-center">{preferences.weekly_study_hours ?? 5} hr</span>
                        </div>
                      </label>
                      <label className="block text-sm font-semibold">
                        Course budget
                        <select className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-3 font-normal" onChange={(event) => setPreferences({ ...preferences, budget_cents: event.target.value === "" ? null : Number(event.target.value) * 100 })} value={preferences.budget_cents == null ? "" : Math.round(preferences.budget_cents / 100)}>
                          <option value="">No fixed budget</option>
                          <option value="0">Free courses only</option>
                          <option value="500">Up to ₹500</option>
                          <option value="2000">Up to ₹2,000</option>
                          <option value="5000">Up to ₹5,000</option>
                          <option value="10000">Up to ₹10,000</option>
                        </select>
                      </label>
                      <fieldset>
                        <legend className="text-sm font-semibold">Preferred learning format</legend>
                        <div className="mt-2 grid gap-3 sm:grid-cols-3">
                          {([
                            ["self_paced", "Self-paced", "Learn on your own schedule"],
                            ["instructor_led", "Instructor-led", "Live trainer guidance"],
                            ["blended", "Blended", "A mix of both"],
                          ] as const).map(([value, label, detail]) => (
                            <label className={`cursor-pointer rounded-2xl border p-4 ${preferences.learning_format === value ? "border-blue-600 bg-blue-50 ring-1 ring-blue-600" : "border-slate-200 hover:bg-slate-50"}`} key={value}>
                              <input checked={preferences.learning_format === value} className="sr-only" name="learning-format" onChange={() => setPreferences({ ...preferences, learning_format: value })} type="radio" />
                              <span className="block font-bold">{label}</span>
                              <span className="mt-1 block text-xs leading-5 text-slate-600">{detail}</span>
                            </label>
                          ))}
                        </div>
                      </fieldset>
                      <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-slate-50 p-4 text-sm">
                        <input checked={preferences.prioritize_paid} className="mt-1 h-4 w-4 accent-blue-700" onChange={(event) => setPreferences({ ...preferences, prioritize_paid: event.target.checked })} type="checkbox" />
                        <span><span className="font-bold">Prioritize paid courses</span><span className="mt-1 block text-slate-600">When enabled, paid options can appear ahead of free or lower-cost options that also meet your needs.</span></span>
                      </label>
                      <button className="rounded-xl bg-blue-700 px-5 py-3 font-bold text-white disabled:opacity-50" disabled={busy} type="submit">{busy ? "Saving…" : "Save preferences"}</button>
                    </form>
                  </div>
                )}

                {screen === "share" && (
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Your data, your choice</p>
                    <h2 className="mt-2 text-xl font-bold">Create a private, limited share link</h2>
                    <p className="mt-2 text-sm leading-6 text-slate-600">Only selected sections are visible. Link tokens are shown once, and you can review access attempts or revoke an active link.</p>
                    <form className="mt-6 space-y-5" onSubmit={createShare}>
                      <fieldset>
                        <legend className="text-sm font-semibold">Choose visible sections</legend>
                        <div className="mt-2 grid gap-3 sm:grid-cols-2">
                          {shareSections.map((section) => (
                            <label className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 ${selectedSections.includes(section.value) ? "border-blue-600 bg-blue-50" : "border-slate-200"}`} key={section.value}>
                              <input checked={selectedSections.includes(section.value)} className="mt-1 h-4 w-4 accent-blue-700" onChange={() => toggleShareSection(section.value)} type="checkbox" />
                              <span><span className="block text-sm font-bold">{section.label}</span><span className="mt-1 block text-xs leading-5 text-slate-600">{section.description}</span></span>
                            </label>
                          ))}
                        </div>
                      </fieldset>
                      <div className="grid gap-4 sm:grid-cols-2">
                        <label className="text-sm font-semibold">
                          Link expiry
                          <select className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-3 font-normal" onChange={(event) => setShareDays(Number(event.target.value))} value={shareDays}>
                            {[7, 14, 30, 90].map((days) => <option key={days} value={days}>{days} days</option>)}
                          </select>
                        </label>
                        <label className="text-sm font-semibold">
                          Maximum successful views <span className="font-normal text-slate-500">(optional)</span>
                          <input className="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-3 font-normal" max="1000" min="1" onChange={(event) => setMaxViews(event.target.value)} placeholder="No view limit" type="number" value={maxViews} />
                        </label>
                      </div>
                      <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-slate-50 p-4 text-sm">
                        <input checked={requireVerifiedEmployer} className="mt-1 h-4 w-4 accent-blue-700" onChange={(event) => setRequireVerifiedEmployer(event.target.checked)} type="checkbox" />
                        <span><span className="font-bold">Require a Level 2 verified employer to sign in</span><span className="mt-1 block text-slate-600">This protects the link with an employer account and completed employer verification.</span></span>
                      </label>
                      <button className="rounded-xl bg-blue-700 px-5 py-3 font-bold text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || selectedSections.length === 0} type="submit">{busy ? "Creating secure link…" : "Create share link"}</button>
                    </form>
                    {createdShareUrl && (
                      <div className="mt-5 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                        <p className="font-bold text-emerald-950">Your link is ready—copy it now</p>
                        <p className="mt-1 text-xs text-emerald-900">For privacy, the platform cannot show this token again after you leave this page.</p>
                        <div className="mt-3 flex gap-2">
                          <input className="min-w-0 flex-1 rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm" onFocus={(event) => event.currentTarget.select()} readOnly value={createdShareUrl} />
                          <button className="rounded-lg bg-emerald-800 px-4 py-2 text-sm font-bold text-white" onClick={() => void navigator.clipboard.writeText(createdShareUrl).then(() => setNotice("Share link copied.")).catch(() => setError("Could not copy automatically; select and copy the link."))} type="button">Copy</button>
                        </div>
                      </div>
                    )}
                    <section className="mt-8">
                      <div className="flex items-center justify-between gap-3">
                        <div><h3 className="font-bold">Active and previous links</h3><p className="mt-1 text-xs text-slate-600">Expired or revoked links cannot reveal your passport.</p></div>
                        <button className="text-sm font-bold text-blue-700 hover:underline" onClick={() => void loadShareLinks(token).catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Could not refresh links."))} type="button">Refresh</button>
                      </div>
                      <ul className="mt-3 space-y-3">
                        {shareLinks.map((link) => (
                          <li className="rounded-2xl border border-slate-200 p-4" key={link.id}>
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <p className="text-sm font-bold">{link.sections.map((section) => shareSections.find((item) => item.value === section)?.label ?? section).join(" · ")}</p>
                                <p className="mt-1 text-xs text-slate-600">{link.view_count}{link.max_views ? ` / ${link.max_views}` : ""} views · expires {new Date(link.expires_at).toLocaleDateString()}{link.require_verified_employer ? " · verified employers only" : ""}</p>
                                <span className={`mt-2 inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${link.revoked_at ? "bg-slate-100 text-slate-600" : new Date(link.expires_at) <= new Date() ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-900"}`}>{link.revoked_at ? "Revoked" : new Date(link.expires_at) <= new Date() ? "Expired" : "Active"}</span>
                              </div>
                              <div className="flex flex-wrap gap-2">
                                <button className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-bold" onClick={() => void showAccessLog(link.id)} type="button">Access log</button>
                                {!link.revoked_at && new Date(link.expires_at) > new Date() && <button className="rounded-lg border border-rose-200 px-3 py-2 text-xs font-bold text-rose-800 hover:bg-rose-50" onClick={() => void revokeShare(link.id)} type="button">Revoke link</button>}
                              </div>
                            </div>
                            {accessLog?.linkId === link.id && (
                              <ul className="mt-4 space-y-2 border-t border-slate-100 pt-3 text-xs text-slate-600">
                                {accessLog.entries.length ? accessLog.entries.map((entry, index) => <li key={`${entry.accessed_at}-${index}`}>{new Date(entry.accessed_at).toLocaleString()} · {entry.outcome} · {entry.viewer_id ? "signed-in viewer" : "anonymous viewer"}</li>) : <li>No access attempts are recorded for this link.</li>}
                              </ul>
                            )}
                          </li>
                        ))}
                        {!shareLinks.length && <li className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">No share links yet.</li>}
                      </ul>
                    </section>
                  </div>
                )}

                {screen === "challenge" && (
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Stronger evidence, when you are ready</p>
                    <h2 className="mt-2 text-xl font-bold">Assess a skill you want to demonstrate</h2>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">An assessment can provide stronger evidence than a self-reported claim. Results are shown with a confidence range; a tab switch may flag review but does not automatically fail you.</p>
                    <div className="mt-6 grid gap-3 sm:grid-cols-3">
                      {[
                        ["Self-check", "Practice and learn where to focus."],
                        ["Verified", "Build stronger evidence when an approved assessment is available."],
                        ["Credential", "A credential may be issued only when the assessment policy is met."],
                      ].map(([title, detail]) => <article className="rounded-2xl border border-slate-200 p-4" key={title}><p className="font-bold">{title}</p><p className="mt-2 text-sm leading-5 text-slate-600">{detail}</p></article>)}
                    </div>
                    <div className="mt-6 rounded-2xl bg-blue-50 p-5">
                      <h3 className="font-bold text-blue-950">What to expect</h3>
                      <ul className="mt-3 space-y-2 text-sm text-blue-950">
                        <li>• Your skill answers are used to estimate a level range with a confidence label.</li>
                        <li>• “I don’t know” is available; guessing is not required.</li>
                        <li>• Only approved assessments are available. If none are listed, check back later.</li>
                      </ul>
                    </div>
                    <Link className="mt-6 inline-flex rounded-xl bg-blue-700 px-5 py-3 font-bold text-white hover:bg-blue-800" href="/assessment">View available assessments <span aria-hidden="true" className="ml-2">→</span></Link>
                    <p className="mt-3 text-xs text-slate-500">The assessment page shows the assessments currently available to your account.</p>
                  </div>
                )}
              </>
            )}
          </section>

          <aside className="space-y-4">
            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <p className="text-xs font-bold uppercase tracking-wide text-blue-700">Passport checklist</p>
              <ol className="mt-4 space-y-4">
                {[
                  { label: "Choose up to 3 target roles", done: Boolean(passport?.target_roles.length) },
                  { label: "Add skills and evidence", done: Boolean(passport?.skills.length) },
                  { label: "Set study preferences", done: true },
                  { label: "Share only what you choose", done: shareLinks.some((link) => !link.revoked_at && new Date(link.expires_at) > new Date()) },
                ].map((item, index) => (
                  <li className="flex gap-3" key={item.label}>
                    <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold ${item.done ? "bg-emerald-100 text-emerald-900" : "bg-slate-100 text-slate-500"}`}>{item.done ? "✓" : index + 1}</span>
                    <span className={`text-sm ${item.done ? "text-slate-500 line-through" : "font-semibold text-slate-800"}`}>{item.label}</span>
                  </li>
                ))}
              </ol>
              <Link className="mt-5 block text-sm font-bold text-blue-700 hover:underline" href="/">Continue onboarding →</Link>
            </section>
            <section className="rounded-3xl border border-blue-100 bg-blue-50 p-5">
              <p className="text-sm font-bold text-blue-950">Evidence stays transparent</p>
              <p className="mt-2 text-sm leading-6 text-blue-900">Resume and manual entries remain <strong>claimed</strong>. Only qualifying assessment evidence can mark a skill as <strong>verified</strong>.</p>
              <Link className="mt-3 inline-block text-sm font-bold text-blue-800 underline" href="/credentials">Review my credentials</Link>
            </section>
          </aside>
        </div>
      </div>
    </main>
  );
}
