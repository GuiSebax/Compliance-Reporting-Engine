"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listReports } from "@/lib/api";
import type { ReportSummary } from "@/lib/types";
import { useRequireAuth } from "@/lib/use-require-auth";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-emerald-950 text-emerald-300 border-emerald-800",
  running: "bg-amber-950 text-amber-300 border-amber-800",
  failed: "bg-red-950 text-red-300 border-red-800",
  pending: "bg-slate-800 text-slate-300 border-slate-700",
};

export default function ReportsPage() {
  const { token, isReady } = useRequireAuth();
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isReady || !token) return;
    listReports(token)
      .then(setReports)
      .catch(() => setError("Could not load reports."));
  }, [isReady, token]);

  if (!isReady) return null;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Generated reports</h1>
          <p className="mt-1 text-sm text-slate-400">
            Every run is versioned and auditable — rule set version, input data hash, and
            a full pipeline trace are recorded for each one.
          </p>
        </div>
        <Link
          href="/upload"
          className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-emerald-400"
        >
          Upload &amp; generate
        </Link>
      </div>

      {error && <p className="text-sm text-red-300">{error}</p>}

      <div className="overflow-auto rounded-md border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-900 text-slate-400">
            <tr>
              <th className="px-3 py-2">Period</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Rule set</th>
              <th className="px-3 py-2">Transactions</th>
              <th className="px-3 py-2">Generated</th>
            </tr>
          </thead>
          <tbody>
            {reports?.map((r) => (
              <tr
                key={r.id}
                className="cursor-pointer border-t border-slate-800 hover:bg-slate-900/60"
              >
                <td className="px-3 py-2">
                  <Link href={`/reports/${r.id}`} className="block text-white">
                    {r.period_start} → {r.period_end}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <span
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      STATUS_STYLES[r.status] ?? STATUS_STYLES.pending
                    }`}
                  >
                    {r.status}
                  </span>
                </td>
                <td className="px-3 py-2 text-slate-300">{r.rule_set_version}</td>
                <td className="px-3 py-2 text-slate-300">{r.input_transaction_count}</td>
                <td className="px-3 py-2 text-slate-400">
                  {new Date(r.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
            {reports && reports.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                  No reports yet.{" "}
                  <Link href="/upload" className="text-emerald-400 hover:underline">
                    Upload a batch
                  </Link>{" "}
                  to get started.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
