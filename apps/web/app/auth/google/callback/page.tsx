"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const errorMessages: Record<string, string> = {
  google_not_configured:
    "Google sign-in is not configured. Set the Google OAuth client ID and secret in the private .env file, then restart Docker Compose.",
  google_cancelled: "Google sign-in was cancelled.",
  google_state_invalid: "The Google sign-in session expired or could not be verified. Please try again.",
  google_account_unavailable: "This account is suspended or unavailable. Contact an administrator.",
  google_account_link_conflict:
    "A different Google account is already linked to this email account. Sign in with the linked Google account.",
  google_verification_failed: "Google could not verify this sign-in. Please try again.",
  google_identity_invalid: "Google did not return a valid, verified email address.",
  google_failed: "Google sign-in could not be completed. Please try again.",
};

export default function GoogleCallbackPage() {
  const [message, setMessage] = useState("Completing Google sign-in…");

  useEffect(() => {
    let active = true;
    const callbackUrl = new URL(window.location.href);
    const errorCode = callbackUrl.searchParams.get("error");
    if (errorCode) {
      window.history.replaceState(null, "", callbackUrl.pathname);
      setMessage(errorMessages[errorCode] ?? errorMessages.google_failed);
      return () => {
        active = false;
      };
    }

    const code = new URLSearchParams(callbackUrl.hash.slice(1)).get("code");
    window.history.replaceState(null, "", callbackUrl.pathname);
    if (!code) {
      setMessage("Google sign-in did not return a valid one-time code. Please try again.");
      return () => {
        active = false;
      };
    }

    void fetch(`${API_URL}/api/v1/auth/google/exchange`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
      cache: "no-store",
    })
      .then(async (response) => {
        const result = (await response.json()) as {
          detail?: string;
          access_token?: string | null;
          mfa_required?: boolean;
          challenge_token?: string | null;
          mfa_setup_required?: boolean;
          setup_token?: string | null;
        };
        if (!response.ok) {
          throw new Error(result.detail ?? `Google sign-in failed (${response.status}).`);
        }
        window.sessionStorage.setItem(
          "capacity-connect-google-auth",
          JSON.stringify(result),
        );
        window.location.replace("/");
      })
      .catch((exchangeError: unknown) => {
        if (!active) return;
        setMessage(
          exchangeError instanceof Error
            ? exchangeError.message
            : "Google sign-in could not be completed. Please try again.",
        );
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 px-5 py-12">
      <section className="w-full max-w-lg rounded-3xl border border-slate-200 bg-white p-7 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-wide text-blue-700">
          Capacity Connect
        </p>
        <h1 className="mt-3 text-2xl font-bold text-slate-950">Google sign-in</h1>
        <p className="mt-3 text-slate-700" role="status">{message}</p>
        {message !== "Completing Google sign-in…" && (
          <Link className="mt-6 inline-block font-semibold text-blue-700 underline" href="/">
            Return to sign in
          </Link>
        )}
      </section>
    </main>
  );
}
