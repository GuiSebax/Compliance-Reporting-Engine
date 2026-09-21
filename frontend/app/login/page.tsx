"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { login, register, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { setToken } = useAuth();
  const router = useRouter();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      if (mode === "register") {
        await register(email, password);
      }
      const tokenResponse = await login(email, password);
      setToken(tokenResponse.access_token);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-sm">
      <h1 className="mb-1 text-xl font-semibold text-white">
        {mode === "login" ? "Sign in" : "Create an account"}
      </h1>
      <p className="mb-6 text-sm text-slate-400">
        {mode === "login"
          ? "Sign in to upload batches and generate compliance reports."
          : "Demo-only self-registration — see the README's Security section."}
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm text-slate-300" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white outline-none focus:border-emerald-400"
            placeholder="you@example.com"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-slate-300" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={mode === "register" ? 8 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white outline-none focus:border-emerald-400"
            placeholder="••••••••"
          />
        </div>

        {error && (
          <p className="rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-md bg-emerald-500 px-3 py-2 text-sm font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-60"
        >
          {isSubmitting ? "Please wait…" : mode === "login" ? "Sign in" : "Create account & sign in"}
        </button>
      </form>

      <button
        onClick={() => {
          setMode(mode === "login" ? "register" : "login");
          setError(null);
        }}
        className="mt-4 text-sm text-slate-400 hover:text-emerald-400"
      >
        {mode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
      </button>
    </div>
  );
}
