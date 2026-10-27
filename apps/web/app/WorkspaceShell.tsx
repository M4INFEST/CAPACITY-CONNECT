"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Role = "trainee" | "trainer" | "employer" | "admin";
type Account = { email: string; roles: Role[] };
type SessionState =
  | { status: "checking" }
  | { status: "signed-out" }
  | { status: "authenticated"; account: Account }
  | { status: "error"; message: string };

type WorkspaceGroup = {
  role: Role;
  title: string;
  links: Array<{ href: string; label: string }>;
};

const workspaces: WorkspaceGroup[] = [
  {
    role: "trainee",
    title: "Learn and grow",
    links: [
      { href: "/", label: "Skill Passport" },
      { href: "/passport", label: "Passport overview" },
      { href: "/passport/resume", label: "Resume review" },
      { href: "/passport/skills", label: "Manage skills" },
      { href: "/passport/preferences", label: "Learning preferences" },
      { href: "/passport/share", label: "Sharing & privacy" },
      { href: "/passport/challenge", label: "Challenge test" },
      { href: "/profile", label: "Readiness" },
      { href: "/learning", label: "Course picks" },
      { href: "/my-learning", label: "My learning" },
      { href: "/assessment", label: "Assessment" },
      { href: "/credentials", label: "Credentials" },
      { href: "/roadmap", label: "Learning roadmap" },
      { href: "/job-gaps", label: "Skill gaps" },
      { href: "/role-matches", label: "Role matches" },
      { href: "/jobs", label: "Explore jobs" },
      { href: "/applications", label: "Applications" },
      { href: "/trainer/apply", label: "Apply to teach" },
    ],
  },
  {
    role: "trainer",
    title: "Trainer workspace",
    links: [
      { href: "/trainer/learning", label: "Courses and learners" },
      { href: "/trainer/assessments", label: "Assessments" },
    ],
  },
  {
    role: "employer",
    title: "Employer workspace",
    links: [{ href: "/employer", label: "Hiring dashboard" }],
  },
  {
    role: "admin",
    title: "Administration",
    links: [
      { href: "/admin/assessment-review", label: "Assessment review" },
      { href: "/admin/credentials", label: "Credential review" },
      { href: "/admin/access-review", label: "Identity reviews" },
    ],
  },
];

const publicRoutes = ["/", "/share", "/verify"];

function isPublicRoute(pathname: string) {
  return publicRoutes.some(
    (route) => pathname === route || (route !== "/" && pathname.startsWith(`${route}/`)),
  );
}

function isActiveRoute(pathname: string, href: string) {
  return href === "/"
    ? pathname === "/"
    : pathname === href || pathname.startsWith(`${href}/`);
}

export default function WorkspaceShell({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<SessionState>({ status: "checking" });

  useEffect(() => {
    let active = true;
    if (isPublicRoute(pathname)) {
      setSession({ status: "signed-out" });
      return () => {
        active = false;
      };
    }

    const token = window.sessionStorage.getItem("capacity-connect-token");

    if (!token) {
      setSession({ status: "signed-out" });
      return () => {
        active = false;
      };
    }

    void fetch(`${API_URL}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            window.sessionStorage.removeItem("capacity-connect-token");
            if (active) {
              setSession({ status: "signed-out" });
            }
            return;
          }
          const message = `The account service could not verify your session (${response.status}).`;
          throw new Error(message);
        }

        const account = (await response.json()) as Partial<Account>;
        if (
          typeof account.email !== "string" ||
          !Array.isArray(account.roles) ||
          account.roles.length === 0
        ) {
          throw new Error("The account service returned an invalid workspace profile.");
        }

        if (active) {
          setSession({
            status: "authenticated",
            account: { email: account.email, roles: account.roles },
          });
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setSession({
            status: "error",
            message:
              error instanceof Error
                ? error.message
                : "The account service could not verify your session.",
          });
        }
      });

    return () => {
      active = false;
    };
  }, [pathname]);

  function signOut() {
    window.sessionStorage.removeItem("capacity-connect-token");
    setSession({ status: "signed-out" });
    router.replace("/");
  }

  if (isPublicRoute(pathname) || session.status === "checking" || session.status === "signed-out") {
    return children;
  }

  if (session.status === "error") {
    return (
      <>
        <div className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-950" role="alert">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
            <p>{session.message}</p>
            <button
              className="rounded-lg border border-amber-300 bg-white px-3 py-2 font-semibold hover:bg-amber-100"
              onClick={signOut}
              type="button"
            >
              Return to sign in
            </button>
          </div>
        </div>
        {children}
      </>
    );
  }

  const visibleWorkspaces = workspaces.filter((workspace) =>
    session.account.roles.includes(workspace.role),
  );

  return (
    <div className="min-h-screen bg-slate-50 lg:flex">
      <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-200 bg-white lg:sticky lg:top-0 lg:flex lg:h-screen">
        <Link className="flex items-center gap-3 border-b border-slate-100 px-6 py-5" href="/">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-700 text-lg font-bold text-white">
            C
          </span>
          <span>
            <span className="block text-sm font-bold tracking-wide text-slate-950">
              Capacity Connect
            </span>
            <span className="block text-xs text-slate-500">Skills to opportunity</span>
          </span>
        </Link>

        <nav aria-label="Workspace navigation" className="flex-1 space-y-7 overflow-y-auto px-4 py-6">
          {visibleWorkspaces.map((workspace) => (
            <section key={workspace.role}>
              <h2 className="px-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                {workspace.title}
              </h2>
              <ul className="mt-2 space-y-1">
                {workspace.links.map(({ href, label }) => {
                  const active = isActiveRoute(pathname, href);
                  return (
                    <li key={href}>
                      <Link
                        aria-current={active ? "page" : undefined}
                        className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                          active
                            ? "bg-blue-50 text-blue-800"
                            : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"
                        }`}
                        href={href}
                      >
                        <span
                          aria-hidden="true"
                          className={`h-2 w-2 rounded-full ${active ? "bg-blue-700" : "bg-slate-300"}`}
                        />
                        {label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </nav>

        <div className="border-t border-slate-100 p-4">
          <p className="truncate px-2 text-xs text-slate-500" title={session.account.email}>
            {session.account.email}
          </p>
          <Link
            className="mt-2 block rounded-xl px-3 py-2 text-left text-sm font-semibold text-slate-700 hover:bg-slate-100"
            href="/account/security"
          >
            Account security
          </Link>
          <button
            className="mt-2 w-full rounded-xl px-3 py-2 text-left text-sm font-semibold text-slate-700 hover:bg-slate-100"
            onClick={signOut}
            type="button"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="border-b border-slate-200 bg-white px-4 py-4 lg:hidden">
          <div className="flex items-center justify-between gap-3">
            <Link className="font-bold text-slate-950" href="/">
              Capacity Connect
            </Link>
            <button
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700"
              onClick={signOut}
              type="button"
            >
              Sign out
            </button>
          </div>
          <nav aria-label="Workspace navigation" className="mt-4 flex gap-2 overflow-x-auto pb-1">
            {visibleWorkspaces.flatMap((workspace) =>
              workspace.links.map(({ href, label }) => {
                const active = isActiveRoute(pathname, href);
                return (
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={`shrink-0 rounded-full px-3 py-2 text-sm font-medium ${
                      active ? "bg-blue-700 text-white" : "bg-slate-100 text-slate-700"
                    }`}
                    href={href}
                    key={`${workspace.role}-${href}`}
                  >
                    {label}
                  </Link>
                );
              }),
            )}
            <Link
              className={`shrink-0 rounded-full px-3 py-2 text-sm font-medium ${
                isActiveRoute(pathname, "/account/security")
                  ? "bg-blue-700 text-white"
                  : "bg-slate-100 text-slate-700"
              }`}
              href="/account/security"
            >
              Account security
            </Link>
          </nav>
          <p className="mt-3 truncate text-xs text-slate-500">{session.account.email}</p>
        </header>
        {children}
      </div>
    </div>
  );
}
