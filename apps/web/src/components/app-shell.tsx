"use client";

import { Button, Select, Spinner, cn } from "@nexa/ui";
import { AudioLines, Bot, Languages, LayoutDashboard, LogOut, PhoneCall, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export function AppShell({ children }: { children: React.ReactNode }) {
  const auth = useRequireAuth();
  const { t, toggle } = useI18n();
  const pathname = usePathname();
  if (!auth.ready || !auth.user) {
    return <div className="flex h-screen items-center justify-center"><Spinner /></div>;
  }
  const nav = [
    { href: "/dashboard", label: t("dashboard"), icon: LayoutDashboard },
    { href: "/agents", label: t("agents"), icon: Bot },
    { href: "/voices", label: t("voices"), icon: AudioLines },
    { href: "/calls", label: t("calls"), icon: PhoneCall },
    { href: "/settings", label: t("settings"), icon: Settings },
  ];
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col border-e bg-card md:flex">
        <Link href="/dashboard" className="flex items-center gap-2 px-5 py-5 text-lg font-semibold">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">N</span>
          Nexa
        </Link>
        <nav className="flex flex-1 flex-col gap-1 px-3">
          {nav.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href}
              className={cn("flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent",
                pathname.startsWith(href) && "bg-accent font-medium")}>
              <Icon className="h-4 w-4" /> {label}
            </Link>
          ))}
        </nav>
        <div className="space-y-2 border-t p-3">
          {auth.memberships.length > 1 && (
            <Select value={auth.tenantId ?? ""} onChange={(e) => auth.selectTenant(e.target.value)} aria-label="Business">
              {auth.memberships.map((m) => <option key={m.tenant_id} value={m.tenant_id}>{m.tenant_name}</option>)}
            </Select>
          )}
          <div className="px-1 text-xs text-muted-foreground">
            <div className="truncate font-medium text-foreground">
              {auth.memberships.find((m) => m.tenant_id === auth.tenantId)?.tenant_name}
            </div>
            <div className="truncate">{auth.user.email} · {auth.role}</div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" className="flex-1" onClick={toggle}>
              <Languages className="h-3.5 w-3.5" /> {t("language")}
            </Button>
            <Button variant="ghost" size="sm" onClick={auth.logout} title={t("logout")}><LogOut className="h-3.5 w-3.5" /></Button>
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <div className="flex items-center justify-between border-b bg-card px-4 py-3 md:hidden">
          <span className="font-semibold">Nexa</span>
          <div className="flex gap-3 text-sm">{nav.map((n) => <Link key={n.href} href={n.href}>{n.label}</Link>)}</div>
        </div>
        {auth.tenantId ? children : (
          <div className="p-8 text-sm text-muted-foreground">Create a business in Settings to get started.</div>
        )}
      </main>
    </div>
  );
}

export function PageHeader({ title, description, actions }: {
  title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 border-b bg-card px-6 py-5">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
