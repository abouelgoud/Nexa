"use client";

import { Badge, cn } from "@nexa/ui";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { useI18n } from "@/lib/i18n";
import { useAgent } from "@/lib/queries";

export default function AgentLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const { t } = useI18n();
  const { data: agent } = useAgent(id);
  const base = `/agents/${id}`;
  const tabs = [
    [base, t("general")], [`${base}/knowledge`, t("knowledge")], [`${base}/tools`, t("actions")],
    [`${base}/builder`, t("workflow")], [`${base}/integrations`, t("integrations")], [`${base}/phone`, t("phone")],
    [`${base}/test`, t("testing")], [`${base}/analytics`, t("analytics")],
  ];
  return (
    <div className="flex min-h-screen flex-col">
      <div className="border-b bg-card px-6 pt-5">
        <div className="flex items-center gap-3">
          <Link href="/agents" className="text-sm text-muted-foreground hover:underline">Agents</Link>
          <span className="text-muted-foreground">/</span>
          <h1 className="text-lg font-semibold">{agent?.name ?? "…"}</h1>
          {agent && <Badge variant={agent.status === "published" ? "success" : "secondary"}>{agent.status}</Badge>}
        </div>
        <nav className="-mb-px mt-4 flex gap-1 overflow-x-auto">
          {tabs.map(([href, label]) => {
            const active = href === base ? pathname === base : pathname.startsWith(href);
            return (
              <Link key={href} href={href} className={cn("whitespace-nowrap border-b-2 px-3 py-2 text-sm",
                active ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
                {label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex-1">{children}</div>
    </div>
  );
}
