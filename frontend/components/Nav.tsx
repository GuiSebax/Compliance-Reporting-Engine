"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export function Nav() {
  const { token, logout } = useAuth();
  const router = useRouter();

  return (
    <header className="border-b border-slate-800 bg-slate-950">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link href="/" className="flex items-center gap-2 text-slate-100">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-400" />
          <span className="font-semibold tracking-tight">Compliance Reporting Engine</span>
        </Link>
        {token && (
          <nav className="flex items-center gap-5 text-sm text-slate-300">
            <Link href="/" className="hover:text-emerald-400">
              Reports
            </Link>
            <Link href="/upload" className="hover:text-emerald-400">
              Upload batch
            </Link>
            <button
              onClick={() => {
                logout();
                router.replace("/login");
              }}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 hover:border-slate-500 hover:text-white"
            >
              Sign out
            </button>
          </nav>
        )}
      </div>
    </header>
  );
}
