"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const CAPTCHA_SITE_KEY = process.env.NEXT_PUBLIC_CAPTCHA_SITE_KEY ?? "";

declare global {
  interface Window {
    grecaptcha?: {
      render: (
        element: HTMLElement,
        options: { sitekey: string; callback: (value: string) => void; "expired-callback": () => void },
      ) => number;
      reset: (widgetId?: number) => void;
    };
  }
}

function CaptchaWidget({ onToken }: { onToken: (value: string) => void }) {
  const elementRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!CAPTCHA_SITE_KEY || !elementRef.current) return;
    let widgetId: number | undefined;
    const render = () => {
      if (!window.grecaptcha || !elementRef.current || widgetId !== undefined) return;
      widgetId = window.grecaptcha.render(elementRef.current, {
        sitekey: CAPTCHA_SITE_KEY,
        callback: onToken,
        "expired-callback": () => onToken(""),
      });
    };
    if (window.grecaptcha) {
      render();
    } else {
      const existing = document.querySelector<HTMLScriptElement>(
        'script[src^="https://www.google.com/recaptcha/api.js"]',
      );
      if (existing) {
        existing.addEventListener("load", render, { once: true });
      } else {
        const script = document.createElement("script");
        script.src = "https://www.google.com/recaptcha/api.js?render=explicit";
        script.async = true;
        script.defer = true;
        script.addEventListener("load", render, { once: true });
        document.head.appendChild(script);
      }
    }
    return () => {
      if (widgetId !== undefined) window.grecaptcha?.reset(widgetId);
    };
  }, [onToken]);

  if (!CAPTCHA_SITE_KEY) {
    return (
      <p className="text-sm text-rose-700">
        CAPTCHA is required. Configure the matching public and secret CAPTCHA keys, then reload.
      </p>
    );
  }
  return <div ref={elementRef} />;
}

type User = {
  id: string;
  email: string;
  roles: string[];
  employer_verification_level: number | null;
};

type AuthResponse = {
  access_token?: string | null;
  mfa_required?: boolean;
  challenge_token?: string | null;
  mfa_setup_required?: boolean;
  setup_token?: string | null;
};

type TargetRole = { role_id: string; name: string };
type TaxonomySkill = { skill_id: string; skill_name: string };
type Candidate = {
  candidate_id: string;
  skill_id: string;
  skill_name: string;
  matched_alias: string;
  confidence_score: number;
  requires_manual_review: boolean;
  context: string;
};
type PassportSkill = {
  skill_id: string;
  skill_name: string;
  level: number | null;
  status: string;
  freshness: string;
  evidence: Array<{
    source_type: string;
    verification: string;
    created_at: string;
  }>;
};
type ShareLink = {
  id: string;
  sections: ShareSection[];
  expires_at: string;
  revoked_at: string | null;
  view_count: number;
};
type ShareAccess = {
  viewer_id: string | null;
  accessed_at: string;
  outcome: string;
};
type Decision = {
  decision: "accepted" | "edited" | "rejected";
  competency_id?: string;
};
type ShareSection = "skills" | "evidence" | "target_roles" | "credentials";

async function api<T>(
  path: string,
  token?: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        ...(options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new Error(
      `Could not reach the API at ${API_URL}. Start Docker Desktop, then run "docker compose up --build" from the capacity-connect folder.`,
    );
  }

  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(payload.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authStep, setAuthStep] = useState<"credentials" | "mfa" | "mfa_setup" | "role_select" | "recovery">("credentials");
  const [pendingAccount, setPendingAccount] = useState<User | null>(null);
  const [mfaToken, setMfaToken] = useState("");
  const [mfaSecret, setMfaSecret] = useState("");
  const [mfaUri, setMfaUri] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [completedAuthToken, setCompletedAuthToken] = useState("");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [registrationRole, setRegistrationRole] = useState<"trainee" | "employer">("trainee");
  const [companyName, setCompanyName] = useState("");
  const [companyWebsite, setCompanyWebsite] = useState("");
  const [companyIndustry, setCompanyIndustry] = useState("");
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const [captchaToken, setCaptchaToken] = useState("");
  const [step, setStep] = useState(1);
  const [roles, setRoles] = useState<TargetRole[]>([]);
  const [taxonomy, setTaxonomy] = useState<TaxonomySkill[]>([]);
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [runId, setRunId] = useState("");
  const [skills, setSkills] = useState<PassportSkill[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [apiReady, setApiReady] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareDays, setShareDays] = useState(14);
  const [shareSections, setShareSections] = useState<ShareSection[]>(["skills"]);
  const [requireVerifiedEmployer, setRequireVerifiedEmployer] = useState(false);
  const [shareUrl, setShareUrl] = useState("");
  const [shareError, setShareError] = useState("");
  const [shareLinks, setShareLinks] = useState<ShareLink[]>([]);
  const [selectedShareLog, setSelectedShareLog] = useState<string | null>(null);
  const [shareAccessLog, setShareAccessLog] = useState<ShareAccess[]>([]);
  const [manualSkill, setManualSkill] = useState("");
  const [manualLevel, setManualLevel] = useState(1);

  useEffect(() => {
    let active = true;
    const checkApi = async () => {
      try {
        const response = await fetch(`${API_URL}/ready`);
        if (active) setApiReady(response.ok);
      } catch {
        if (active) setApiReady(false);
      }
    };
    void checkApi();

    const storedToken = window.sessionStorage.getItem("capacity-connect-token");
    if (storedToken) {
      setToken(storedToken);
      void finishAuthenticated(storedToken).catch(() => {
        window.sessionStorage.removeItem("capacity-connect-token");
        setToken("");
        setUser(null);
      });
    }

    return () => {
      active = false;
    };
  }, []);


  const selectedSkillCount = useMemo(
    () => Object.values(decisions).filter((item) => item.decision !== "rejected").length,
    [decisions],
  );

  async function loadPassport(accessToken: string) {
    const [roleOptions, skillOptions, passport] = await Promise.all([
      api<TargetRole[]>("/api/v1/passport/roles", accessToken),
      api<TaxonomySkill[]>("/api/v1/passport/taxonomy", accessToken),
      api<{ skills: PassportSkill[]; target_roles: TargetRole[] }>("/api/v1/passport", accessToken),
    ]);
    setRoles(roleOptions);
    setTaxonomy(skillOptions);
    setSkills(passport.skills);
    setSelectedRoles(passport.target_roles.map((role) => role.role_id));
    if (passport.skills.length > 0) setStep(3);
    else if (passport.target_roles.length > 0) setStep(2);
  }

  async function finishAuthenticated(accessToken: string) {
    const account = await api<User>("/api/v1/auth/me", accessToken);
    setToken(accessToken);
    window.sessionStorage.setItem("capacity-connect-token", accessToken);
    setCaptchaRequired(false);
    setCaptchaToken("");
    if (account.roles.length > 1) {
      setPendingAccount(account);
      setAuthStep("role_select");
      return;
    }
    if (account.roles.includes("admin")) {
      window.location.assign("/admin/assessment-review");
      return;
    }
    if (account.roles.includes("trainer")) {
      window.location.assign("/trainer/learning");
      return;
    }
    if (account.roles.includes("employer") && !account.roles.includes("trainee")) {
      window.location.assign("/employer");
      return;
    }
    if (!account.roles.includes("trainee")) {
      throw new Error("The Skill Passport is available to trainee accounts.");
    }
    setUser(account);
    await loadPassport(accessToken);
  }

  async function selectWorkspace(role: string) {
    if (!pendingAccount || !pendingAccount.roles.includes(role)) {
      setError("That workspace is not assigned to this account.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      if (role === "admin") {
        window.location.assign("/admin/assessment-review");
      } else if (role === "trainer") {
        window.location.assign("/trainer/learning");
      } else if (role === "employer") {
        window.location.assign("/employer");
      } else if (role === "trainee") {
        const activeToken = window.sessionStorage.getItem("capacity-connect-token");
        if (!activeToken) throw new Error("Your session expired. Sign in again.");
        setAuthStep("credentials");
        setUser(pendingAccount);
        await loadPassport(activeToken);
      }
    } catch (selectionError) {
      setError(selectionError instanceof Error ? selectionError.message : "Could not open this workspace.");
    } finally {
      setBusy(false);
    }
  }

  function startGoogleSignIn() {
    window.location.assign(`${API_URL}/api/v1/auth/google/start`);
  }

  useEffect(() => {
    const pendingGoogleResponse = window.sessionStorage.getItem(
      "capacity-connect-google-auth",
    );
    if (pendingGoogleResponse) {
      window.sessionStorage.removeItem("capacity-connect-google-auth");
      try {
        const result = JSON.parse(pendingGoogleResponse) as AuthResponse;
        if (result.mfa_required && result.challenge_token) {
          setMfaToken(result.challenge_token);
          setAuthStep("mfa");
          return;
        }
        if (result.mfa_setup_required && result.setup_token) {
          void api<{ secret: string; otpauth_uri: string }>(
            "/api/v1/auth/mfa/setup",
            result.setup_token,
            { method: "POST", body: JSON.stringify({}) },
          )
            .then((setup) => {
              setMfaToken(result.setup_token ?? "");
              setMfaSecret(setup.secret);
              setMfaUri(setup.otpauth_uri);
              setAuthStep("mfa_setup");
            })
            .catch((setupError: unknown) => {
              setError(
                setupError instanceof Error
                  ? setupError.message
                  : "Could not start required MFA setup.",
              );
            });
          return;
        }
        if (!result.access_token) {
          throw new Error("Google sign-in did not complete authentication.");
        }
        void finishAuthenticated(result.access_token).catch((authError: unknown) => {
          setError(authError instanceof Error ? authError.message : "Could not finish Google sign-in.");
        });
      } catch (authError) {
        setError(authError instanceof Error ? authError.message : "Google sign-in response was invalid.");
      }
      return;
    }

    const savedToken = window.sessionStorage.getItem("capacity-connect-token");
    if (!savedToken) return;
    setToken(savedToken);
    api<User>("/api/v1/auth/me", savedToken)
      .then(async (account) => {
        if (account.roles.length > 1) {
          setPendingAccount(account);
          setAuthStep("role_select");
          return;
        }
        if (account.roles.includes("admin")) {
          window.location.replace("/admin/assessment-review");
          return;
        }
        if (account.roles.includes("trainer")) {
          window.location.replace("/trainer/learning");
          return;
        }
        if (account.roles.includes("employer") && !account.roles.includes("trainee")) {
          window.location.replace("/employer");
          return;
        }
        if (!account.roles.includes("trainee")) {
          throw new Error("The Skill Passport is available to trainee accounts.");
        }
        setUser(account);
        await loadPassport(savedToken);
      })
      .catch(() => {
        window.sessionStorage.removeItem("capacity-connect-token");
        setToken("");
      });
  }, []);

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      if (authMode === "register") {
        await api("/api/v1/auth/register", undefined, {
          method: "POST",
          body: JSON.stringify({
            email,
            password,
            role: registrationRole,
            ...(registrationRole === "employer"
              ? {
                  company_name: companyName,
                  website: companyWebsite || null,
                  industry: companyIndustry || null,
                }
              : {}),
          }),
        });
        setAuthMode("login");
        setPassword("");
        setNotice("Account created. Check your email and verify your address before signing in.");
        return;
      }
      const result = await api<AuthResponse>("/api/v1/auth/login", undefined, {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          ...(captchaToken ? { captcha_token: captchaToken } : {}),
        }),
      });
      if (result.mfa_required && result.challenge_token) {
        setMfaToken(result.challenge_token);
        setAuthStep("mfa");
        return;
      }
      if (result.mfa_setup_required && result.setup_token) {
        const setup = await api<{ secret: string; otpauth_uri: string }>(
          "/api/v1/auth/mfa/setup",
          result.setup_token,
          { method: "POST", body: JSON.stringify({ password }) },
        );
        setMfaToken(result.setup_token);
        setMfaSecret(setup.secret);
        setMfaUri(setup.otpauth_uri);
        setAuthStep("mfa_setup");
        return;
      }
      if (!result.access_token) {
        throw new Error("Sign-in did not return a completed authentication token.");
      }
      await finishAuthenticated(result.access_token);
    } catch (authError) {
      const message = authError instanceof Error ? authError.message : "Sign-in failed";
      if (message.toLowerCase().includes("captcha")) {
        setCaptchaRequired(true);
        setCaptchaToken("");
      }
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  async function submitMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (authStep === "mfa") {
        const result = await api<AuthResponse>("/api/v1/auth/mfa/verify", mfaToken, {
          method: "POST",
          body: JSON.stringify({ code: mfaCode }),
        });
        if (!result.access_token) {
          throw new Error("MFA verification did not return an access token.");
        }
        await finishAuthenticated(result.access_token);
        return;
      }
      const result = await api<{ recovery_codes: string[]; access_token?: string | null }>(
        "/api/v1/auth/mfa/confirm",
        mfaToken,
        { method: "POST", body: JSON.stringify({ code: mfaCode }) },
      );
      if (!result.access_token) {
        throw new Error("MFA setup did not return an access token.");
      }
      setCompletedAuthToken(result.access_token);
      setRecoveryCodes(result.recovery_codes);
      setAuthStep("recovery");
      setMfaCode("");
    } catch (authError) {
      setError(authError instanceof Error ? authError.message : "MFA verification failed");
    } finally {
      setBusy(false);
    }
  }

  async function continueAfterRecoveryCodes() {
    setError("");
    setBusy(true);
    try {
      await finishAuthenticated(completedAuthToken);
    } catch (authError) {
      setError(authError instanceof Error ? authError.message : "Could not finish sign-in");
    } finally {
      setBusy(false);
    }
  }

  async function saveRoles() {
    setError("");
    setBusy(true);
    try {
      await api("/api/v1/passport/target-roles", token, {
        method: "PUT",
        body: JSON.stringify({ role_ids: selectedRoles }),
      });
      setStep(2);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not save target roles");
    } finally {
      setBusy(false);
    }
  }

  async function uploadResume(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api<{
        run_id: string;
        candidates: Candidate[];
      }>("/api/v1/passport/extract", token, { method: "POST", body: form });
      setRunId(result.run_id);
      setCandidates(result.candidates);
      setDecisions(
        Object.fromEntries(
          result.candidates.map((candidate) => [
            candidate.candidate_id,
            {
              decision: candidate.requires_manual_review ? "rejected" : "accepted",
              competency_id: candidate.skill_id,
            } satisfies Decision,
          ]),
        ),
      );
      setStep(3);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not process this resume");
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  async function confirmSkills() {
    if (!runId && candidates.length === 0) {
      setError("Upload a resume before confirming extracted skills.");
      return;
    }
    setError("");
    setNotice("");
    setBusy(true);
    try {
      try {
        await api("/api/v1/passport/confirm", token, {
          method: "POST",
          body: JSON.stringify({
            run_id: runId,
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
        // Fallback: directly save accepted or edited skills if run is missing or stale
        const accepted = candidates
          .map((candidate) => {
            const dec = decisions[candidate.candidate_id]?.decision ?? "rejected";
            if (dec === "accepted") return candidate.skill_id;
            if (dec === "edited") return decisions[candidate.candidate_id]?.competency_id;
            return null;
          })
          .filter((id): id is string => Boolean(id));

        for (const cId of accepted) {
          await api("/api/v1/passport/skills", token, {
            method: "POST",
            body: JSON.stringify({ competency_id: cId, level: 1 }),
          }).catch(() => {});
        }
      }
      const passport = await api<{ skills: PassportSkill[] }>("/api/v1/passport", token);
      setSkills(passport.skills);
      setCandidates([]);
      setRunId("");
      setNotice("Your reviewed skills were saved to your passport as claimed, not verified.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not confirm skills");
    } finally {
      setBusy(false);
    }
  }

  async function addManualSkill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!manualSkill) return;
    setError("");
    setBusy(true);
    try {
      await api("/api/v1/passport/skills", token, {
        method: "POST",
        body: JSON.stringify({ competency_id: manualSkill, level: manualLevel }),
      });
      const passport = await api<{ skills: PassportSkill[] }>("/api/v1/passport", token);
      setSkills(passport.skills);
      setManualSkill("");
      setNotice("Skill added as a self-rated claim.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not add skill");
    } finally {
      setBusy(false);
    }
  }

  function toggleRole(roleId: string) {
    setSelectedRoles((current) => {
      if (current.includes(roleId)) return current.filter((id) => id !== roleId);
      if (current.length >= 3) return current;
      return [...current, roleId];
    });
  }

  function setDecision(candidateId: string, value: Decision) {
    setDecisions((current) => ({ ...current, [candidateId]: value }));
  }

  async function createShareLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setShareError("");
    setShareUrl("");
    try {
      const result = await api<{ share_id: string; token: string; expires_at: string }>("/api/v1/passport/share", token, {
        method: "POST",
        body: JSON.stringify({
          expires_in_days: shareDays,
          sections: shareSections,
          require_verified_employer: requireVerifiedEmployer,
        }),
      });
      setShareUrl(`${window.location.origin}/share/${result.token}`);
      await loadShareLinks();
    } catch (requestError) {
      setShareError(requestError instanceof Error ? requestError.message : "Could not create share link");
    }
  }

  async function loadShareLinks() {
    const result = await api<ShareLink[]>("/api/v1/passport/share", token);
    setShareLinks(result);
  }

  async function showShareAccessLog(shareId: string) {
    setShareError("");
    try {
      const result = await api<ShareAccess[]>(
        `/api/v1/passport/share/${shareId}/access-log`,
        token,
      );
      setSelectedShareLog(shareId);
      setShareAccessLog(result);
    } catch (requestError) {
      setShareError(requestError instanceof Error ? requestError.message : "Could not load the access log");
    }
  }

  async function revokeShareLink(shareId: string) {
    setShareError("");
    try {
      await api(`/api/v1/passport/share/${shareId}`, token, { method: "DELETE" });
      await loadShareLinks();
    } catch (requestError) {
      setShareError(requestError instanceof Error ? requestError.message : "Could not revoke this link");
    }
  }

  async function copyShareUrl() {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setNotice("Share link copied.");
    } catch {
      setShareError("Could not copy automatically. Select and copy the link.");
    }
  }

  function toggleShareSection(section: ShareSection) {
    setShareSections((current) =>
      current.includes(section)
        ? current.filter((item) => item !== section)
        : [...current, section],
    );
  }

  if (!user) {
    return (
      <main className="min-h-screen bg-gradient-to-br from-slate-100 via-white to-blue-50 px-5 py-12">
        <div className="mx-auto grid max-w-5xl overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-xl md:grid-cols-[1fr_460px]">
          <aside className="hidden bg-slate-950 p-10 text-white md:flex md:flex-col md:justify-between">
            <div>
              <p className="text-sm font-bold uppercase tracking-[0.18em] text-blue-300">Capacity Connect</p>
              <h1 className="mt-8 text-4xl font-bold leading-tight">Build skills.<br />Show your proof.<br />Move forward.</h1>
              <p className="mt-5 max-w-sm leading-7 text-slate-300">
                A learner-first path from your skills today to the work you want tomorrow.
              </p>
              <ol className="mt-10 space-y-4">
                {[
                  ["01", "Create your Skill Passport"],
                  ["02", "Explore courses matched to your goals"],
                  ["03", "Learn, practice, and track progress"],
                ].map(([number, label]) => (
                  <li className="flex items-center gap-3" key={number}>
                    <span className="grid h-9 w-9 place-items-center rounded-full bg-blue-500/20 text-sm font-bold text-blue-200">{number}</span>
                    <span className="text-sm text-slate-200">{label}</span>
                  </li>
                ))}
              </ol>
            </div>
            <p className="text-xs text-slate-400">Your skills belong to you. Claims and verified evidence are clearly distinguished.</p>
          </aside>
          <section className="p-6 sm:p-9">
          <p className="text-sm font-bold uppercase tracking-[0.18em] text-blue-700">
            Learner workspace · Stage 2
          </p>
          <h1 className="mt-4 text-3xl font-bold tracking-tight">Your Skill Passport</h1>
          <p className="mt-3 text-slate-600">
            Sign in or create an account to build your profile of skills, evidence, and goals.
          </p>
          {apiReady === false && (
            <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950" role="status">
              <p className="font-semibold">The API or database is not ready, so sign-in is unavailable.</p>
              <p className="mt-1">Start Docker Desktop, then run <code className="rounded bg-white px-1">docker compose up --build</code> from the capacity-connect folder. Reload this page after the stack starts.</p>
            </div>
          )}
          {authStep === "credentials" ? (
          <>
          <div className="mt-7 flex rounded-xl bg-slate-100 p-1">
            {(["login", "register"] as const).map((mode) => (
              <button
                key={mode}
                className={`flex-1 rounded-lg px-4 py-2 text-sm font-semibold ${
                  authMode === mode ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
                }`}
                onClick={() => setAuthMode(mode)}
                type="button"
              >
                {mode === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>
          <label className="mt-4 flex items-start gap-2 rounded-xl bg-slate-50 p-3 text-sm">
            <input
              checked={requireVerifiedEmployer}
              className="mt-1"
              onChange={(event) => setRequireVerifiedEmployer(event.target.checked)}
              type="checkbox"
            />
            <span>Require sign-in as a Level 2 verified employer to view this passport.</span>
          </label>
          <form className="mt-6 space-y-4" onSubmit={submitAuth}>
            {authMode === "register" && (
              <label className="block text-sm font-medium">
                Account type
                <select
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                  onChange={(event) => setRegistrationRole(event.target.value as "trainee" | "employer")}
                  value={registrationRole}
                >
                  <option value="trainee">Learner</option>
                  <option value="employer">Employer</option>
                </select>
              </label>
            )}
            {authMode === "register" && registrationRole === "employer" && (
              <>
                <label className="block text-sm font-medium">
                  Company name
                  <input
                    autoComplete="organization"
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                    onChange={(event) => setCompanyName(event.target.value)}
                    required
                    value={companyName}
                  />
                </label>
                <label className="block text-sm font-medium">
                  Company website (optional)
                  <input
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                    onChange={(event) => setCompanyWebsite(event.target.value)}
                    placeholder="https://example.com"
                    type="url"
                    value={companyWebsite}
                  />
                </label>
                <label className="block text-sm font-medium">
                  Industry (optional)
                  <input
                    className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                    onChange={(event) => setCompanyIndustry(event.target.value)}
                    value={companyIndustry}
                  />
                </label>
                <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
                  New employer accounts start unverified and cannot view learner applications until an administrator verifies the business.
                </p>
              </>
            )}
            <label className="block text-sm font-medium">
              Email
              <input
                autoComplete="email"
                className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                onChange={(event) => setEmail(event.target.value)}
                required
                type="email"
                value={email}
              />
            </label>
            <label className="block text-sm font-medium">
              Password
              <input
                autoComplete={authMode === "login" ? "current-password" : "new-password"}
                className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
            </label>
            {authMode === "register" && (
              <p className="text-xs text-slate-500">
                Passwords need at least 12 characters, including upper- and lowercase letters and a number.
              </p>
            )}
            {captchaRequired && (
              <CaptchaWidget
                key={captchaToken ? "verified" : "empty"}
                onToken={setCaptchaToken}
              />
            )}
            {authMode === "login" && (
              <div className="flex flex-wrap justify-between gap-3 text-sm">
                <Link className="font-semibold text-blue-700 hover:underline" href="/forgot-password">
                  Forgot password?
                </Link>
                <Link className="font-semibold text-blue-700 hover:underline" href="/verify-email">
                  Resend verification email
                </Link>
              </div>
            )}
            {error && <p className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
            <button
              className="w-full rounded-xl bg-blue-700 px-4 py-3 font-semibold text-white disabled:opacity-50"
              disabled={busy || apiReady === false}
              type="submit"
            >
              {busy
                ? "Please wait…"
                : authMode === "login"
                  ? "Sign in"
                  : registrationRole === "employer"
                    ? "Create employer account"
                    : "Create learner account"}
            </button>
          </form>
          {(authMode === "login" || registrationRole === "trainee") && (
            <>
              <div className="my-5 flex items-center gap-3 text-xs text-slate-400" aria-hidden="true">
                <span className="h-px flex-1 bg-slate-200" />
                <span>OR</span>
                <span className="h-px flex-1 bg-slate-200" />
              </div>
              <button
                className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-50"
                disabled={busy || apiReady === false}
                onClick={startGoogleSignIn}
                type="button"
              >
                Continue with Google
              </button>
              <p className="mt-2 text-xs text-slate-500">
                Google sign-up creates a learner account. Employers should use the employer registration form.
              </p>
            </>
          )}
          </>
          ) : authStep === "mfa" || authStep === "mfa_setup" ? (
            <form className="mt-7 space-y-4" onSubmit={submitMfa}>
              <h2 className="text-xl font-bold">
                {authStep === "mfa" ? "Verify your sign-in" : "Secure your account with MFA"}
              </h2>
              {authStep === "mfa_setup" && (
                <div className="space-y-3 rounded-xl bg-slate-50 p-4 text-sm">
                  <p>Scan this setup link in an authenticator app, or enter the secret manually:</p>
                  <code className="block break-all rounded bg-white p-3">{mfaSecret}</code>
                  <a className="break-all font-semibold text-blue-700 underline" href={mfaUri}>
                    Open authenticator setup
                  </a>
                  <p className="text-slate-600">MFA is required for trainer, employer, and admin accounts. It is not enabled until you verify a current code.</p>
                </div>
              )}
              <label className="block text-sm font-medium">
                {authStep === "mfa" ? "Authenticator or recovery code" : "Six-digit authenticator code"}
                <input
                  autoComplete="one-time-code"
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2.5"
                  inputMode="numeric"
                  onChange={(event) => setMfaCode(event.target.value)}
                  required
                  value={mfaCode}
                />
              </label>
              {error && <p className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700" role="alert">{error}</p>}
              <button
                className="w-full rounded-xl bg-blue-700 px-4 py-3 font-semibold text-white disabled:opacity-50"
                disabled={busy}
                type="submit"
              >
                {busy ? "Please wait…" : authStep === "mfa" ? "Verify and sign in" : "Enable MFA"}
              </button>
            </form>
          ) : authStep === "role_select" ? (
            <div className="mt-7 space-y-4">
              <h2 className="text-xl font-bold">Choose a workspace</h2>
              <p className="text-sm text-slate-600">Only roles assigned to this account are available.</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {(pendingAccount?.roles ?? []).map((role) => (
                  <button
                    className="rounded-xl border border-slate-300 p-4 text-left font-semibold capitalize hover:border-blue-700 hover:bg-blue-50"
                    key={role}
                    onClick={() => void selectWorkspace(role)}
                    type="button"
                  >
                    {role === "trainee" ? "Learner workspace" : `${role} workspace`}
                  </button>
                ))}
              </div>
              {error && <p className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700" role="alert">{error}</p>}
            </div>
          ) : (
            <div className="mt-7 space-y-4">
              <h2 className="text-xl font-bold">Save your recovery codes</h2>
              <p className="text-sm text-slate-600">
                Each code works once. Store them somewhere safe now; they will not be shown again.
              </p>
              <ul className="grid gap-2 rounded-xl bg-slate-50 p-4 font-mono text-sm sm:grid-cols-2">
                {recoveryCodes.map((code) => <li key={code}>{code}</li>)}
              </ul>
              {error && <p className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700" role="alert">{error}</p>}
              <button
                className="w-full rounded-xl bg-blue-700 px-4 py-3 font-semibold text-white disabled:opacity-50"
                disabled={busy}
                onClick={continueAfterRecoveryCodes}
                type="button"
              >
                I saved these codes — continue
              </button>
            </div>
          )}
        </section>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#0b0f19] text-slate-100 antialiased selection:bg-blue-500/30 selection:text-white">
      {/* Background ambient lighting */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none -z-10">
        <div className="absolute -top-40 -left-40 h-[600px] w-[600px] rounded-full bg-blue-600/10 blur-[130px]" />
        <div className="absolute top-1/3 -right-40 h-[500px] w-[500px] rounded-full bg-indigo-600/10 blur-[140px]" />
        <div className="absolute -bottom-40 left-1/3 h-[500px] w-[500px] rounded-full bg-cyan-600/10 blur-[140px]" />
      </div>

      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Top Navigation Bar */}
        <header className="flex flex-wrap items-center justify-between gap-4 rounded-3xl border border-white/10 bg-slate-900/60 p-5 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center gap-4">
            <div className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-tr from-blue-600 via-indigo-600 to-cyan-400 font-bold text-white shadow-lg shadow-blue-500/25">
              <span className="text-xl">CC</span>
              <span className="absolute -bottom-0.5 -right-0.5 flex h-3.5 w-3.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex h-3.5 w-3.5 rounded-full border-2 border-slate-900 bg-emerald-500"></span>
              </span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-white">Capacity Connect</h1>
                <span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-blue-300">
                  Learner Passport
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Connected as <span className="font-medium text-slate-200">{user.email}</span>
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Link
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:bg-white/10 hover:text-white"
              href="/profile"
            >
              <span>📊</span>
              <span>Readiness & Gaps</span>
            </Link>
            <Link
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:bg-white/10 hover:text-white"
              href="/learning"
            >
              <span>🎯</span>
              <span>Course Recommendations</span>
            </Link>
            <Link
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:bg-white/10 hover:text-white"
              href="/credentials"
            >
              <span>🎖️</span>
              <span>Credentials</span>
            </Link>
            <Link
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:bg-white/10 hover:text-white"
              href="/my-learning"
            >
              <span>📚</span>
              <span>My Courses</span>
            </Link>
            <button
              className="inline-flex items-center gap-1.5 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3.5 py-2 text-xs font-semibold text-rose-300 transition hover:bg-rose-500/20 hover:text-rose-200"
              onClick={() => {
                setToken("");
                window.sessionStorage.removeItem("capacity-connect-token");
                setUser(null);
                setSkills([]);
                setStep(1);
                setAuthStep("credentials");
                setPendingAccount(null);
                setMfaToken("");
                setRecoveryCodes([]);
              }}
              type="button"
            >
              <span>Sign out</span>
            </button>
          </div>
        </header>

        {/* Hero & Quick Stat Banner */}
        <section className="mt-6 grid gap-4 lg:grid-cols-4">
          <div className="relative overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900/90 via-slate-900/60 to-blue-950/40 p-6 shadow-xl backdrop-blur-xl lg:col-span-3">
            <div className="relative z-10 flex flex-col justify-between h-full">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-medium text-cyan-300">
                  <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
                  Verified Evidence-Based Architecture
                </div>
                <h2 className="mt-3 text-2xl font-bold tracking-tight text-white sm:text-3xl">
                  Competency Passport & Skill Growth Center
                </h2>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-300">
                  Manage your claimed skills, upload resumes for automated extraction, test your skills via interactive challenge assessments, and share verified credential proof with employers.
                </p>
              </div>

              <div className="mt-6 flex flex-wrap items-center gap-3 pt-4 border-t border-white/10">
                <Link
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-2.5 text-xs font-bold text-white shadow-lg shadow-blue-600/30 transition hover:brightness-110 active:scale-95"
                  href="/passport"
                >
                  <span>Open Full Passport Suite</span>
                  <span aria-hidden="true">→</span>
                </Link>
                <Link
                  className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white"
                  href="/passport/challenge"
                >
                  <span>⚡ Take Challenge Test</span>
                </Link>
                <Link
                  className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white"
                  href="/passport/preferences"
                >
                  <span>⚙️ Learning Preferences</span>
                </Link>
              </div>
            </div>
          </div>

          {/* Quick Metrics Card */}
          <div className="flex flex-col justify-between rounded-3xl border border-white/10 bg-slate-900/60 p-6 shadow-xl backdrop-blur-xl">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Passport Status</p>
              <div className="mt-4 space-y-3">
                <div className="flex items-center justify-between rounded-2xl border border-white/5 bg-white/5 p-3">
                  <span className="text-xs text-slate-300">Active Skills</span>
                  <span className="text-lg font-bold text-white">{skills.length}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-white/5 bg-white/5 p-3">
                  <span className="text-xs text-slate-300">Target Roles</span>
                  <span className="text-lg font-bold text-cyan-300">{selectedRoles.length}</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl border border-white/5 bg-white/5 p-3">
                  <span className="text-xs text-slate-300">Verified Evidence</span>
                  <span className="text-lg font-bold text-emerald-400">
                    {skills.filter((s) => s.status === "verified").length}
                  </span>
                </div>
              </div>
            </div>

            <button
              className="mt-4 w-full rounded-xl border border-blue-500/30 bg-blue-500/10 py-2.5 text-xs font-bold text-blue-300 transition hover:bg-blue-500/20 active:scale-95"
              onClick={() => {
                setShareOpen(true);
                setShareUrl("");
                setShareError("");
                setSelectedShareLog(null);
                void loadShareLinks().catch((requestError: unknown) => {
                  setShareError(
                    requestError instanceof Error ? requestError.message : "Could not load share links",
                  );
                });
              }}
              type="button"
            >
              🔗 Share Passport Securely
            </button>
          </div>
        </section>

        {/* Global Notifications */}
        {(error || notice) && (
          <div
            className={`mt-6 flex items-center justify-between gap-4 rounded-2xl border p-4 text-sm backdrop-blur-xl ${
              error
                ? "border-rose-500/30 bg-rose-950/40 text-rose-200"
                : "border-emerald-500/30 bg-emerald-950/40 text-emerald-200"
            }`}
            role={error ? "alert" : "status"}
          >
            <div className="flex items-center gap-3">
              <span className="text-base">{error ? "⚠️" : "✨"}</span>
              <span>{error || notice}</span>
            </div>
            <button
              className="text-xs font-semibold underline opacity-80 hover:opacity-100"
              onClick={() => {
                setError("");
                setNotice("");
              }}
              type="button"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Interactive Step Progress Tracker */}
        <nav aria-label="Passport onboarding steps" className="mt-8 grid grid-cols-3 gap-3">
          {[
            { num: 1, label: "Target Roles", desc: "Select target career paths" },
            { num: 2, label: "Resume Extraction", desc: "Upload PDF/DOCX resume" },
            { num: 3, label: "Review & Manage", desc: "Confirm matches & claims" },
          ].map(({ num, label, desc }) => {
            const isActive = step === num;
            const isCompleted = step > num;
            return (
              <button
                key={label}
                onClick={() => setStep(num)}
                type="button"
                className={`group flex flex-col items-start rounded-2xl border p-4 text-left transition ${
                  isActive
                    ? "border-blue-500 bg-blue-500/10 shadow-lg shadow-blue-500/10 ring-1 ring-blue-500/40"
                    : isCompleted
                      ? "border-white/15 bg-white/5 hover:border-white/30"
                      : "border-white/5 bg-white/[0.02] opacity-75 hover:opacity-100"
                }`}
              >
                <div className="flex w-full items-center justify-between">
                  <span
                    className={`flex h-6 w-6 items-center justify-center rounded-lg text-xs font-bold ${
                      isActive
                        ? "bg-blue-600 text-white"
                        : isCompleted
                          ? "bg-emerald-500 text-slate-950"
                          : "bg-white/10 text-slate-400"
                    }`}
                  >
                    {isCompleted ? "✓" : num}
                  </span>
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Step 0{num}
                  </span>
                </div>
                <p className={`mt-2 text-sm font-semibold ${isActive ? "text-blue-300" : "text-white"}`}>
                  {label}
                </p>
                <p className="mt-0.5 text-xs text-slate-400 line-clamp-1">{desc}</p>
              </button>
            );
          })}
        </nav>

        {/* Main Work Area Card */}
        <section className="mt-6 rounded-3xl border border-white/10 bg-slate-900/60 p-6 shadow-2xl backdrop-blur-xl sm:p-8">
          {step === 1 && (
            <div>
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-white/10 pb-5">
                <div>
                  <h2 className="text-xl font-bold text-white">Target Career Roles</h2>
                  <p className="mt-1 text-sm text-slate-400">
                    Select up to three roles you are working toward. The system analyzes skill gaps and course recommendations against these roles.
                  </p>
                </div>
                <span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs font-medium text-blue-300">
                  {selectedRoles.length} of 3 selected
                </span>
              </div>

              {roles.length === 0 ? (
                <div className="mt-6 rounded-2xl border border-amber-500/20 bg-amber-500/10 p-5 text-sm text-amber-200">
                  No roles are currently configured in the role catalog.
                </div>
              ) : (
                <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {roles.map((role) => {
                    const isSelected = selectedRoles.includes(role.role_id);
                    return (
                      <label
                        key={role.role_id}
                        className={`flex cursor-pointer items-center justify-between rounded-2xl border p-4 transition active:scale-[0.99] ${
                          isSelected
                            ? "border-blue-500 bg-blue-500/15 text-white shadow-md shadow-blue-500/10 ring-1 ring-blue-500/40"
                            : "border-white/10 bg-white/5 text-slate-300 hover:border-white/20 hover:bg-white/10 hover:text-white"
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <input
                            checked={isSelected}
                            className="h-4 w-4 rounded border-slate-700 bg-slate-800 text-blue-600 focus:ring-blue-500 focus:ring-offset-slate-900"
                            onChange={() => toggleRole(role.role_id)}
                            type="checkbox"
                          />
                          <span className="text-sm font-semibold">{role.name}</span>
                        </div>
                        {isSelected && (
                          <span className="text-xs font-bold text-blue-400">Selected</span>
                        )}
                      </label>
                    );
                  })}
                </div>
              )}

              <div className="mt-8 flex items-center justify-between border-t border-white/10 pt-5">
                <p className="text-xs text-slate-400">
                  Changes will update readiness calculators across all linked stages.
                </p>
                <button
                  className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-6 py-2.5 text-sm font-bold text-white shadow-lg shadow-blue-600/30 transition hover:bg-blue-500 active:scale-95 disabled:opacity-50"
                  disabled={busy || roles.length === 0}
                  onClick={saveRoles}
                  type="button"
                >
                  {busy ? "Saving..." : "Save & Continue to Step 2"}
                  <span>→</span>
                </button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div>
              <div className="border-b border-white/10 pb-5">
                <h2 className="text-xl font-bold text-white">Upload Resume for Extraction</h2>
                <p className="mt-1 text-sm text-slate-400">
                  Upload a text-based PDF or DOCX (up to 10 MB). The ML parser extracts candidate skills and aliases for your review in-memory.
                </p>
              </div>

              <div className="mt-6">
                <label className="group relative flex cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed border-white/20 bg-white/[0.02] p-10 text-center transition hover:border-blue-500 hover:bg-blue-500/5">
                  <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-600/10 text-3xl text-blue-400 group-hover:scale-110 transition duration-300">
                    📄
                  </div>
                  <span className="mt-4 text-base font-semibold text-white">
                    {busy ? "Parsing resume with AI extractor..." : "Click to select or drop resume file"}
                  </span>
                  <span className="mt-1 text-xs text-slate-400">
                    Accepted formats: PDF or DOCX (Max 10 MB) · Processed securely in-memory
                  </span>
                  <input
                    accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    className="sr-only"
                    disabled={busy}
                    onChange={uploadResume}
                    type="file"
                  />
                </label>
              </div>

              <div className="mt-6 flex items-center justify-between border-t border-white/10 pt-5">
                <button
                  className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold text-slate-300 transition hover:bg-white/10 hover:text-white"
                  onClick={() => setStep(1)}
                  type="button"
                >
                  ← Back to Step 1
                </button>
                <button
                  className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold text-cyan-300 transition hover:bg-cyan-500/10 hover:text-cyan-200"
                  onClick={() => {
                    setCandidates([]);
                    setRunId("");
                    setStep(3);
                  }}
                  type="button"
                >
                  Skip to Manual Entry →
                </button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div>
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-5">
                <div>
                  <h2 className="text-xl font-bold text-white">Review & Confirm Skills</h2>
                  <p className="mt-1 text-sm text-slate-400">
                    Validate extracted competencies or manually add skills from the standardized taxonomy catalog.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {runId && (
                    <span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs font-semibold text-blue-300">
                      {selectedSkillCount} skills ready to confirm
                    </span>
                  )}
                  <button
                    className="rounded-xl border border-white/10 bg-white/5 px-3.5 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-white/10 hover:text-white"
                    onClick={() => setStep(2)}
                    type="button"
                  >
                    Upload Another Resume
                  </button>
                </div>
              </div>

              {candidates.length > 0 ? (
                <div className="mt-6 space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Extracted Matches</p>
                  {candidates.map((candidate) => {
                    const decision = decisions[candidate.candidate_id] ?? {
                      decision: "rejected" as const,
                      competency_id: candidate.skill_id,
                    };
                    const selected = decision.decision !== "rejected";
                    return (
                      <article
                        className={`rounded-2xl border p-4 transition ${
                          selected
                            ? "border-blue-500/50 bg-blue-500/10"
                            : "border-white/5 bg-white/[0.02] opacity-60"
                        }`}
                        key={candidate.candidate_id}
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <label className="flex cursor-pointer items-start gap-3">
                            <input
                              checked={selected}
                              className="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-800 text-blue-600 focus:ring-blue-500"
                              onChange={(event) =>
                                setDecision(candidate.candidate_id, {
                                  decision: event.target.checked ? "accepted" : "rejected",
                                  competency_id: candidate.skill_id,
                                })
                              }
                              type="checkbox"
                            />
                            <div>
                              <span className="text-sm font-semibold text-white">
                                {candidate.skill_name}
                              </span>
                              <span className="mt-0.5 block text-xs text-slate-400">
                                Matched “{candidate.matched_alias}” ·{" "}
                                <span className="font-semibold text-cyan-300">
                                  {Math.round(candidate.confidence_score * 100)}% confidence
                                </span>
                              </span>
                            </div>
                          </label>

                          {candidate.requires_manual_review && (
                            <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-300">
                              Requires Manual Review
                            </span>
                          )}
                        </div>

                        {candidate.requires_manual_review && (
                          <p className="ml-7 mt-2 text-xs italic text-slate-400 bg-white/5 p-2 rounded-xl">
                            "{candidate.context}"
                          </p>
                        )}

                        {selected && (
                          <div className="ml-7 mt-3 flex items-center gap-3">
                            <label className="text-xs text-slate-400">Map to taxonomy:</label>
                            <select
                              className="rounded-lg border border-white/10 bg-slate-800 px-3 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                              onChange={(event) =>
                                setDecision(candidate.candidate_id, {
                                  decision:
                                    event.target.value === candidate.skill_id ? "accepted" : "edited",
                                  competency_id: event.target.value,
                                })
                              }
                              value={decision.competency_id ?? candidate.skill_id}
                            >
                              {taxonomy.map((skill) => (
                                <option key={skill.skill_id} value={skill.skill_id}>
                                  {skill.skill_name}
                                </option>
                              ))}
                            </select>
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div className="mt-6 rounded-2xl border border-white/5 bg-white/[0.02] p-5 text-center text-sm text-slate-400">
                  No extracted skills currently awaiting review. You can add competencies directly from the standardized catalog below.
                </div>
              )}

              {/* Direct Add Skill Form */}
              <form
                className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-5"
                onSubmit={addManualSkill}
              >
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                  Add Skill from Standardized Taxonomy
                </p>
                <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_160px_auto]">
                  <label className="text-xs font-medium text-slate-400">
                    Competency
                    <select
                      className="mt-1 block w-full rounded-xl border border-white/10 bg-slate-800 px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                      onChange={(event) => setManualSkill(event.target.value)}
                      required
                      value={manualSkill}
                    >
                      <option value="">Select competency from taxonomy...</option>
                      {taxonomy.map((skill) => (
                        <option key={skill.skill_id} value={skill.skill_id}>
                          {skill.skill_name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="text-xs font-medium text-slate-400">
                    Self-Rated Level
                    <select
                      className="mt-1 block w-full rounded-xl border border-white/10 bg-slate-800 px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                      onChange={(event) => setManualLevel(Number(event.target.value))}
                      value={manualLevel}
                    >
                      {[1, 2, 3, 4, 5].map((level) => (
                        <option key={level} value={level}>
                          Level {level} {level === 1 ? "(Novice)" : level === 3 ? "(Intermediate)" : level === 5 ? "(Expert)" : ""}
                        </option>
                      ))}
                    </select>
                  </label>

                  <button
                    className="self-end rounded-xl bg-slate-700 px-5 py-2 text-sm font-bold text-white transition hover:bg-slate-600 disabled:opacity-50"
                    disabled={busy || !manualSkill}
                    type="submit"
                  >
                    + Add Skill
                  </button>
                </div>
              </form>

              {runId && (
                <div className="mt-6 flex justify-end">
                  <button
                    className="rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-6 py-3 text-sm font-bold text-white shadow-lg shadow-blue-600/30 transition hover:brightness-110 active:scale-95 disabled:opacity-50"
                    disabled={busy}
                    onClick={confirmSkills}
                    type="button"
                  >
                    {busy ? "Saving to Passport..." : `Confirm ${selectedSkillCount} Skills to Passport`}
                  </button>
                </div>
              )}
            </div>
          )}
        </section>

        {/* Confirmed Passport Skills Inventory */}
        <section className="mt-8 rounded-3xl border border-white/10 bg-slate-900/60 p-6 shadow-2xl backdrop-blur-xl sm:p-8">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-5">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-bold text-white">Your Confirmed Passport</h2>
                <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-300">
                  {skills.length} competencies
                </span>
              </div>
              <p className="mt-1 text-sm text-slate-400">
                Skills confirmed in your passport. Evidence records and verified assessment badges are tracked dynamically.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <Link
                className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white"
                href="/passport/challenge"
              >
                ⚡ Challenge Test
              </Link>
              <button
                className="rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-2 text-xs font-bold text-white shadow-lg shadow-blue-600/25 transition hover:brightness-110"
                onClick={() => {
                  setShareOpen(true);
                  setShareUrl("");
                  setShareError("");
                  setSelectedShareLog(null);
                  void loadShareLinks().catch((requestError: unknown) => {
                    setShareError(
                      requestError instanceof Error ? requestError.message : "Could not load share links",
                    );
                  });
                }}
                type="button"
              >
                Share Passport
              </button>
            </div>
          </div>

          {skills.length === 0 ? (
            <div className="mt-8 rounded-2xl border border-white/5 bg-white/[0.02] p-8 text-center">
              <span className="text-3xl">📭</span>
              <p className="mt-2 text-sm font-semibold text-white">Your Skill Passport is currently empty</p>
              <p className="mt-1 text-xs text-slate-400">
                Upload a resume in Step 2 or add competencies directly using the taxonomy selector.
              </p>
              <button
                className="mt-4 rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-xs font-bold text-blue-300 hover:bg-blue-500/20"
                onClick={() => setStep(2)}
                type="button"
              >
                Upload Resume Now
              </button>
            </div>
          ) : (
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {skills.map((skill) => {
                const isVerified = skill.status === "verified";
                const isFresh = skill.freshness === "current";
                return (
                  <article
                    className="relative flex flex-col justify-between rounded-2xl border border-white/10 bg-white/5 p-5 transition hover:border-white/20 hover:bg-white/[0.08]"
                    key={skill.skill_id}
                  >
                    <div>
                      <div className="flex items-start justify-between gap-2">
                        <h3 className="text-sm font-bold text-white">{skill.skill_name}</h3>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                            isVerified
                              ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                              : "border border-amber-500/30 bg-amber-500/10 text-amber-300"
                          }`}
                        >
                          {isVerified ? "Verified" : "Claimed"}
                        </span>
                      </div>

                      {/* Level Indicator */}
                      <div className="mt-3">
                        <div className="flex items-center justify-between text-xs text-slate-400">
                          <span>Rating</span>
                          <span className="font-semibold text-slate-200">
                            {skill.level ? `Level ${skill.level} / 5` : "Unrated"}
                          </span>
                        </div>
                        <div className="mt-1.5 flex gap-1">
                          {[1, 2, 3, 4, 5].map((lvl) => (
                            <span
                              key={lvl}
                              className={`h-1.5 flex-1 rounded-full ${
                                lvl <= (skill.level ?? 0)
                                  ? isVerified
                                    ? "bg-emerald-400"
                                    : "bg-blue-500"
                                  : "bg-white/10"
                              }`}
                            />
                          ))}
                        </div>
                      </div>

                      {/* Freshness Badge */}
                      <div className="mt-3 flex items-center gap-2 text-[11px] text-slate-400">
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            isFresh ? "bg-emerald-400" : "bg-amber-400"
                          }`}
                        />
                        <span>Freshness: {skill.freshness}</span>
                      </div>
                    </div>

                    <div className="mt-4 border-t border-white/5 pt-3">
                      <p className="text-[11px] text-slate-400">
                        <span className="font-medium text-slate-300">Evidence:</span>{" "}
                        {skill.evidence.length > 0
                          ? skill.evidence.map((item) => `${item.source_type} (${item.verification})`).join(", ")
                          : "Self-declaration"}
                      </p>
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          {/* Target Roles summary tags */}
          {selectedRoles.length > 0 && (
            <div className="mt-6 border-t border-white/10 pt-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Active Target Roles</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {selectedRoles.map((roleId) => {
                  const role = roles.find((item) => item.role_id === roleId);
                  return role ? (
                    <span
                      className="rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-semibold text-cyan-300"
                      key={roleId}
                    >
                      🎯 {role.name}
                    </span>
                  ) : null;
                })}
              </div>
            </div>
          )}
        </section>
      </div>

      {/* Share Passport Modal */}
      {shareOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setShareOpen(false);
          }}
        >
          <section
            aria-labelledby="share-title"
            aria-modal="true"
            className="w-full max-w-lg rounded-3xl border border-white/10 bg-slate-900 p-6 shadow-2xl text-slate-100"
            role="dialog"
          >
            <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-4">
              <div>
                <h2 className="text-lg font-bold text-white" id="share-title">
                  Share Your Competency Passport
                </h2>
                <p className="mt-1 text-xs text-slate-400">
                  Generate secure, time-limited access tokens for employers and recruiters.
                </p>
              </div>
              <button
                aria-label="Close"
                className="rounded-lg p-1 text-slate-400 hover:text-white"
                onClick={() => setShareOpen(false)}
                type="button"
              >
                ✕
              </button>
            </div>

            <form className="mt-5 space-y-4" onSubmit={createShareLink}>
              <label className="block text-xs font-medium text-slate-300">
                Link Expiration
                <select
                  className="mt-1 block w-full rounded-xl border border-white/10 bg-slate-800 px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                  onChange={(event) => setShareDays(Number(event.target.value))}
                  value={shareDays}
                >
                  {[7, 14, 30, 90].map((days) => (
                    <option key={days} value={days}>{days} days</option>
                  ))}
                </select>
              </label>

              <fieldset>
                <legend className="text-xs font-medium text-slate-300">Visible Passport Sections</legend>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {(
                    [
                      ["skills", "Skills & Levels"],
                      ["evidence", "Evidence Proofs"],
                      ["target_roles", "Target Roles"],
                      ["credentials", "Issued Credentials"],
                    ] as const
                  ).map(([section, label]) => (
                    <label
                      className="flex items-center gap-2 rounded-xl border border-white/5 bg-white/5 p-3 text-xs text-slate-300 cursor-pointer hover:bg-white/10"
                      key={section}
                    >
                      <input
                        checked={shareSections.includes(section)}
                        className="rounded border-slate-700 bg-slate-800 text-blue-600 focus:ring-blue-500"
                        onChange={() => toggleShareSection(section)}
                        type="checkbox"
                      />
                      <span>{label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {shareError && (
                <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
                  {shareError}
                </p>
              )}

              {shareUrl && (
                <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4">
                  <p className="text-xs font-semibold text-emerald-300">
                    ✓ Link created successfully. Copy and share it with your employer:
                  </p>
                  <input
                    className="mt-2 w-full rounded-xl border border-emerald-500/30 bg-slate-900 px-3 py-2 text-xs text-white"
                    onFocus={(event) => event.currentTarget.select()}
                    readOnly
                    value={shareUrl}
                  />
                  <button
                    className="mt-2 w-full rounded-xl bg-emerald-600 py-2 text-xs font-bold text-white transition hover:bg-emerald-500 active:scale-95"
                    onClick={copyShareUrl}
                    type="button"
                  >
                    Copy Link to Clipboard
                  </button>
                </div>
              )}

              {shareLinks.length > 0 && (
                <section className="space-y-2 border-t border-white/10 pt-4">
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Active Share Links ({shareLinks.length})
                  </p>
                  <div className="max-h-40 space-y-2 overflow-y-auto pr-1">
                    {shareLinks.map((link) => (
                      <article className="rounded-xl border border-white/5 bg-white/5 p-3 text-xs" key={link.id}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-slate-300">
                            {link.sections.join(", ")} · {link.view_count} views
                            {link.revoked_at ? " (Revoked)" : ""}
                          </p>
                          <div className="flex gap-2">
                            <button
                              className="font-semibold text-blue-400 hover:underline"
                              onClick={() => void showShareAccessLog(link.id)}
                              type="button"
                            >
                              Log
                            </button>
                            {!link.revoked_at && (
                              <button
                                className="font-semibold text-rose-400 hover:underline"
                                onClick={() => void revokeShareLink(link.id)}
                                type="button"
                              >
                                Revoke
                              </button>
                            )}
                          </div>
                        </div>
                        {selectedShareLog === link.id && (
                          <ul className="mt-2 space-y-1 border-t border-white/5 pt-2 text-[11px] text-slate-400">
                            {shareAccessLog.length === 0 ? (
                              <li>No access attempts logged yet.</li>
                            ) : (
                              shareAccessLog.map((entry, index) => (
                                <li key={`${entry.accessed_at}-${index}`}>
                                  {new Date(entry.accessed_at).toLocaleString()} · {entry.outcome}
                                </li>
                              ))
                            )}
                          </ul>
                        )}
                      </article>
                    ))}
                  </div>
                </section>
              )}

              <div className="flex justify-end gap-2 border-t border-white/10 pt-4">
                <button
                  className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-white/10"
                  onClick={() => setShareOpen(false)}
                  type="button"
                >
                  Close
                </button>
                <button
                  className="rounded-xl bg-blue-600 px-5 py-2 text-xs font-bold text-white shadow-lg shadow-blue-600/30 hover:bg-blue-500"
                  type="submit"
                >
                  Generate Share Link
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </main>

  );
}


