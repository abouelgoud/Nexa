"use client";

import type { Membership, TokenResponse, User } from "@nexa/shared-types";
import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { get, post, session } from "./api";

interface AuthState {
  ready: boolean;
  user: User | null;
  memberships: Membership[];
  tenantId: string | null;
  role: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (data: { email: string; password: string; full_name: string; tenant_name: string }) => Promise<void>;
  logout: () => void;
  selectTenant: (id: string) => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const qc = useQueryClient();

  const apply = useCallback((data: TokenResponse) => {
    if (data.access_token) session.token = data.access_token;
    setUser(data.user);
    setMemberships(data.memberships);
    const current = session.tenant && data.memberships.some((m) => m.tenant_id === session.tenant)
      ? session.tenant : data.memberships[0]?.tenant_id ?? null;
    session.tenant = current;
    setTenantId(current);
  }, []);

  const refresh = useCallback(async () => {
    if (!session.token) {
      setReady(true);
      return;
    }
    try {
      apply(await get<TokenResponse>("/auth/me"));
    } catch {
      session.token = null;
    } finally {
      setReady(true);
    }
  }, [apply]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restore the session from storage on mount
    void refresh();
  }, [refresh]);

  const value = useMemo<AuthState>(() => ({
    ready, user, memberships, tenantId,
    role: memberships.find((m) => m.tenant_id === tenantId)?.role ?? null,
    login: async (email, password) => apply(await post<TokenResponse>("/auth/login", { email, password })),
    register: async (data) => apply(await post<TokenResponse>("/auth/register", data)),
    logout: () => {
      session.token = null;
      session.tenant = null;
      setUser(null);
      qc.clear();
      window.location.assign(new URL("/login", window.location.origin));
    },
    selectTenant: (id) => {
      session.tenant = id;
      setTenantId(id);
      qc.clear();
    },
    refresh,
  }), [ready, user, memberships, tenantId, apply, qc, refresh]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/** Redirects to /login when signed out. */
export function useRequireAuth() {
  const auth = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    if (auth.ready && !auth.user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [auth.ready, auth.user, router, pathname]);
  return auth;
}
