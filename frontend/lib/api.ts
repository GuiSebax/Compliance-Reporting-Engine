// Thin fetch wrapper around the Compliance Reporting Engine API.
//
// Auth is a bearer JWT kept in memory + localStorage (see auth-context.tsx)
// and attached here. There is no server-side rendering of authenticated
// data in this dashboard on purpose: the token lives in the browser only,
// so every authenticated call happens client-side, which keeps this file
// (and the whole auth story) simple and avoids ever having to forward
// cookies/headers through a Next.js server layer.

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg ?? String(d)).join("; ");
    }
    return JSON.stringify(body);
  } catch {
    return response.statusText || `Request failed with status ${response.status}`;
  }
}

async function request<T>(
  path: string,
  options: RequestInit & { token?: string | null } = {}
): Promise<T> {
  const { token, headers, ...rest } = options;
  const finalHeaders = new Headers(headers);
  if (token) finalHeaders.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
  });

  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorMessage(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function login(email: string, password: string) {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);
  return request<import("./types").TokenResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
}

export async function register(email: string, password: string) {
  return request("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function listBatches(token: string) {
  return request<import("./types").BatchSummary[]>("/batches", { token });
}

export async function uploadBatch(token: string, file: File) {
  const form = new FormData();
  form.set("file", file);
  return request<import("./types").BatchDetail>("/batches/upload", {
    method: "POST",
    token,
    body: form,
  });
}

export async function listReports(token: string) {
  return request<import("./types").ReportSummary[]>("/reports", { token });
}

export async function getReport(token: string, reportId: string) {
  return request<import("./types").ReportDetail>(`/reports/${reportId}`, { token });
}

export async function triggerReport(
  token: string,
  periodStart: string,
  periodEnd: string,
  ruleSetVersion?: string
) {
  return request<import("./types").ReportDetail>("/reports", {
    method: "POST",
    token,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      period_start: periodStart,
      period_end: periodEnd,
      rule_set_version: ruleSetVersion || undefined,
    }),
  });
}

// Exports require the bearer token, so a plain <a href> can't be used
// (the browser won't attach an Authorization header to a navigation).
// This fetches the file as a blob and triggers a client-side download.
export async function downloadExport(
  token: string,
  reportId: string,
  format: "json" | "csv" | "pdf"
) {
  const response = await fetch(
    `${API_BASE_URL}/reports/${reportId}/export?format=${format}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorMessage(response));
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `report-${reportId}.${format}`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
