"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ApiError, listBatches, triggerReport, uploadBatch } from "@/lib/api";
import type { BatchDetail, BatchSummary } from "@/lib/types";
import { useRequireAuth } from "@/lib/use-require-auth";

export default function UploadPage() {
  const { token, isReady } = useRequireAuth();
  const router = useRouter();

  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [lastBatch, setLastBatch] = useState<BatchDetail | null>(null);

  const [batches, setBatches] = useState<BatchSummary[]>([]);

  const [periodStart, setPeriodStart] = useState("2026-01-01");
  const [periodEnd, setPeriodEnd] = useState("2026-01-31");
  const [isGenerating, setIsGenerating] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const refreshBatches = useCallback(async () => {
    if (!token) return;
    try {
      setBatches(await listBatches(token));
    } catch {
      // Non-critical for this view; the upload form still works.
    }
  }, [token]);

  useEffect(() => {
    // Fetch-on-mount/dependency-change: refreshBatches is async and its
    // setState only runs after the awaited request resolves, not
    // synchronously in this effect body.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (isReady) refreshBatches();
  }, [isReady, refreshBatches]);

  if (!isReady) return null;

  async function handleUpload(e: FormEvent) {
    e.preventDefault();
    if (!file || !token) return;
    setIsUploading(true);
    setUploadError(null);
    setLastBatch(null);
    try {
      const result = await uploadBatch(token, file);
      setLastBatch(result);
      await refreshBatches();
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setIsUploading(false);
    }
  }

  async function handleGenerateReport(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setIsGenerating(true);
    setReportError(null);
    try {
      const report = await triggerReport(token, periodStart, periodEnd);
      router.push(`/reports/${report.id}`);
    } catch (err) {
      setReportError(err instanceof ApiError ? err.message : "Report generation failed.");
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-xl font-semibold text-white">Upload a transaction batch</h1>
        <p className="mt-1 text-sm text-slate-400">
          CSV or JSON. Each row is validated on ingestion; malformed rows are rejected
          individually and reported below — the rest of the batch still gets processed.
        </p>

        <form onSubmit={handleUpload} className="mt-4 flex flex-wrap items-center gap-3">
          <input
            type="file"
            accept=".csv,.json"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm text-slate-300 file:mr-3 file:rounded-md file:border-0 file:bg-slate-700 file:px-3 file:py-2 file:text-sm file:text-white hover:file:bg-slate-600"
          />
          <button
            type="submit"
            disabled={!file || isUploading}
            className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
          >
            {isUploading ? "Uploading…" : "Upload batch"}
          </button>
        </form>

        {uploadError && (
          <p className="mt-3 rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {uploadError}
          </p>
        )}

        {lastBatch && (
          <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/50 p-4">
            <p className="text-sm text-slate-300">
              <span className="font-medium text-white">{lastBatch.original_filename}</span> —{" "}
              {lastBatch.accepted_row_count} accepted, {lastBatch.rejected_row_count} rejected
              of {lastBatch.row_count} rows.
            </p>
            {lastBatch.rejected_rows.length > 0 && (
              <div className="mt-3 max-h-48 overflow-auto rounded-md border border-slate-800">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-900 text-slate-400">
                    <tr>
                      <th className="px-3 py-2">Row</th>
                      <th className="px-3 py-2">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lastBatch.rejected_rows.map((r) => (
                      <tr key={r.row_index} className="border-t border-slate-800">
                        <td className="px-3 py-2 text-slate-400">{r.row_index}</td>
                        <td className="px-3 py-2 text-red-300">{r.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="border-t border-slate-800 pt-8">
        <h2 className="text-lg font-semibold text-white">Generate a report</h2>
        <p className="mt-1 text-sm text-slate-400">
          Runs the versioned rule engine against every transaction whose timestamp falls
          within the period, classifies and validates each one, and produces an
          aggregated, auditable report.
        </p>
        <form onSubmit={handleGenerateReport} className="mt-4 flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-sm text-slate-300" htmlFor="period_start">
              Period start
            </label>
            <input
              id="period_start"
              type="date"
              value={periodStart}
              onChange={(e) => setPeriodStart(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white outline-none focus:border-emerald-400"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-slate-300" htmlFor="period_end">
              Period end
            </label>
            <input
              id="period_end"
              type="date"
              value={periodEnd}
              onChange={(e) => setPeriodEnd(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white outline-none focus:border-emerald-400"
            />
          </div>
          <button
            type="submit"
            disabled={isGenerating}
            className="rounded-md border border-emerald-500 px-4 py-2 text-sm font-medium text-emerald-400 hover:bg-emerald-500 hover:text-slate-950 disabled:opacity-50"
          >
            {isGenerating ? "Generating…" : "Generate report"}
          </button>
        </form>
        {reportError && (
          <p className="mt-3 rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {reportError}
          </p>
        )}
      </section>

      <section className="border-t border-slate-800 pt-8">
        <h2 className="text-lg font-semibold text-white">Recent batches</h2>
        <div className="mt-3 overflow-auto rounded-md border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-900 text-slate-400">
              <tr>
                <th className="px-3 py-2">Filename</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Accepted / Total</th>
                <th className="px-3 py-2">Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.id} className="border-t border-slate-800">
                  <td className="px-3 py-2 text-white">{b.original_filename}</td>
                  <td className="px-3 py-2 text-slate-300">{b.status}</td>
                  <td className="px-3 py-2 text-slate-300">
                    {b.accepted_row_count} / {b.row_count}
                  </td>
                  <td className="px-3 py-2 text-slate-400">
                    {new Date(b.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
              {batches.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-center text-slate-500">
                    No batches uploaded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
