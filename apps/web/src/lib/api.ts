"use client";

/**
 * Thin fetch wrapper: adds the JWT and tenant header, and turns API errors into readable messages.
 * By default requests go to /api on this origin and Next.js proxies them to the API (see next.config.ts).
 */
const CONFIGURED_API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";
const LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"];

/** A localhost API address only works when the page is also opened on localhost; otherwise use the proxy. */
function resolveApiUrl(): string {
  if (typeof window === "undefined" || CONFIGURED_API_URL.startsWith("/")) return CONFIGURED_API_URL;
  try {
    const target = new URL(CONFIGURED_API_URL);
    if (LOCAL_HOSTS.includes(target.hostname) && !LOCAL_HOSTS.includes(window.location.hostname)) return "/api";
  } catch {
    return "/api";
  }
  return CONFIGURED_API_URL;
}

export const API_URL = resolveApiUrl();

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
  if (res.status >= 500 && !res.headers.get("content-type")?.includes("application/json")) {
    // The web app's /api proxy answered, but the API behind it did not.
    throw new ApiError(res.status, "network", "The API is not responding. Check that the api service is running.");
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
