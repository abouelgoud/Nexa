"use client";

/** Thin fetch wrapper: adds the JWT and tenant header, and turns API errors into readable messages. */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Detailed, business-language explanation lines (validation problems, checklist items...). */
  get lines(): string[] {
    if (!Array.isArray(this.details)) return [];
    return this.details
      .map((d: any) => (typeof d === "string" ? d : d?.message ?? (d?.ok === false ? `${d.label}: ${d.message}` : null)))
      .filter(Boolean) as string[];
  }
}

const TOKEN_KEY = "nexa.token";
const TENANT_KEY = "nexa.tenant";

export const session = {
  get token() {
    return typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY);
  },
  set token(v: string | null) {
    if (v) localStorage.setItem(TOKEN_KEY, v);
    else localStorage.removeItem(TOKEN_KEY);
  },
  get tenant() {
    return typeof window === "undefined" ? null : localStorage.getItem(TENANT_KEY);
  },
  set tenant(v: string | null) {
    if (v) localStorage.setItem(TENANT_KEY, v);
    else localStorage.removeItem(TENANT_KEY);
  },
};

type Options = Omit<RequestInit, "body"> & { body?: unknown; form?: FormData };

export async function api<T = any>(path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers as Record<string, string>) };
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  if (session.tenant) headers["X-Tenant-ID"] = session.tenant;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...opts, headers, body });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the server. Check that the API is running.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = data?.error ?? {};
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      session.token = null;
      window.location.assign(new URL("/login", window.location.origin));
    }
    throw new ApiError(res.status, err.code ?? "error", err.message ?? `Request failed (${res.status})`, err.details);
  }
  return data as T;
}

export const get = <T = any>(path: string) => api<T>(path);
export const post = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body ?? {} });
export const put = <T = any>(path: string, body: unknown) => api<T>(path, { method: "PUT", body });
export const patch = <T = any>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });
