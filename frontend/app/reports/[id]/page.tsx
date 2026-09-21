"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { downloadExport, getReport } from "@/lib/api";
import type { ReportDetail } from "@/lib/types";
import { useRequireAuth } from "@/lib/use-require-auth";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-950 text-red-300 border-red-800",
  warning: "bg-amber-950 text-amber-300 border-amber-800",
  info: "bg-slate-800 text-slate-300 border-slate-700",
};

export default function ReportDetailPage() {
  const { token, isReady } = useRequireAuth();
  const params = useParams<{ id: string }>();
  const reportId = params.id;

  const [report, setReport] = useState<ReportDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    if (!isReady || !token || !reportId) return;
    getReport(token, reportId)
      .then(setReport)
      .catch(() => setError("Could not load this report."));
  }, [isReady, token, reportId]);

  if (!isReady) return null;
  if (error) return <p className="text-sm text-red-300">{error}</p>;
  if (!report) return <p className="text-sm text-slate-400">Loading…</p>;

  async function handleDownload(format: "json" | "csv" | "pdf") {
    if (!token) return;
    setDownloading(format);
    try {
      await downloadExport(token, report!.id, format);
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-white">
          Report: {report.period_start} → {report.period_end}
        </h1>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-slate-500">Status</dt>
            <dd className="text-slate-200">{report.status}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Rule set version</dt>
            <dd className="text-slate-200">{report.rule_set_version}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Transactions</dt>
            <dd className="text-slate-200">{report.input_transaction_count}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Input data hash</dt>
            <dd className="truncate font-mono text-xs text-slate-400" title={report.input_data_hash}>
              {report.input_data_hash.slice(0, 16)}…
            </dd>
          </div>
        </dl>

        <div className="mt-4 flex gap-2">
          {(["json", "csv", "pdf"] as const).map((format) => (
            <button
              key={format}
              onClick={() => handleDownload(format)}
              disabled={downloading === format}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:border-emerald-400 hover:text-emerald-400 disabled:opacity-50"
            >
              {downloading === format ? "Downloading…" : `Download ${format.toUpperCase()}`}
            </button>
          ))}
        </div>
      </div>

      <section>
        <h2 className="mb-2 text-lg font-semibold text-white">
          Aggregated line items ({report.line_items.length})
        </h2>
        <div className="overflow-auto rounded-md border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-900 text-slate-400">
              <tr>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2">Currency</th>
                <th className="px-3 py-2">Metric</th>
                <th className="px-3 py-2">Value</th>
                <th className="px-3 py-2">Tx count</th>
              </tr>
            </thead>
            <tbody>
              {report.line_items.map((li, idx) => (
                <tr key={idx} className="border-t border-slate-800">
                  <td className="px-3 py-2 text-white">{li.category}</td>
                  <td className="px-3 py-2 text-slate-300">{li.currency}</td>
                  <td className="px-3 py-2 text-slate-300">{li.metric_name}</td>
                  <td className="px-3 py-2 text-slate-300">{li.metric_value}</td>
                  <td className="px-3 py-2 text-slate-300">{li.transaction_count}</td>
                </tr>
              ))}
              {report.line_items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-center text-slate-500">
                    No transactions fell within this period.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold text-white">
          Violations ({report.violations.length})
        </h2>
        <div className="overflow-auto rounded-md border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-900 text-slate-400">
              <tr>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Rule</th>
                <th className="px-3 py-2">Transaction</th>
                <th className="px-3 py-2">Message</th>
              </tr>
            </thead>
            <tbody>
              {report.violations.map((v, idx) => (
                <tr key={idx} className="border-t border-slate-800">
                  <td className="px-3 py-2">
                    <span
                      className={`rounded-full border px-2 py-0.5 text-xs ${
                        SEVERITY_STYLES[v.severity] ?? SEVERITY_STYLES.info
                      }`}
                    >
                      {v.severity}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-300">{v.rule_id}</td>
                  <td className="px-3 py-2 text-slate-300">{v.transaction_external_id}</td>
                  <td className="px-3 py-2 text-slate-300">{v.message}</td>
                </tr>
              ))}
              {report.violations.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-center text-slate-500">
                    No violations raised.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold text-white">Audit trail</h2>
        <ol className="space-y-2 border-l border-slate-800 pl-4">
          {report.audit_trail.map((event, idx) => (
            <li key={idx} className="relative text-sm">
              <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-emerald-400" />
              <p className="text-slate-200">{event.message}</p>
              <p className="text-xs text-slate-500">
                {event.event_type} · {new Date(event.occurred_at).toLocaleString()}
              </p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
