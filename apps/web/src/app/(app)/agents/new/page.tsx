"use client";

import type { AgentDetail } from "@nexa/shared-types";
import { Badge, Button, Card, CardContent, Input, Label, cn } from "@nexa/ui";
import { useMutation } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { ErrorBox } from "@/components/error-box";
import { post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useTemplates } from "@/lib/queries";

export default function NewAgentPage() {
  const { locale } = useI18n();
  const templates = useTemplates();
  const router = useRouter();
  const [template, setTemplate] = useState("doctor_appointment");
  const [business, setBusiness] = useState("");
  const create = useMutation({
    mutationFn: () => post<AgentDetail>("/agents", { template_key: template, business_name: business || undefined }),
    onSuccess: (agent) => router.push(agent.template_key === "doctor_appointment" ? `/agents/${agent.id}/integrations?setup=1` : `/agents/${agent.id}`),
  });
  return (
    <>
      <PageHeader title="Create an agent" description="Choose a template. You can change everything afterwards - no code required." />
      <div className="mx-auto max-w-4xl space-y-6 p-6">
        <div className="grid gap-3 md:grid-cols-2">
          {templates.data?.map((t) => (
            <button key={t.key} type="button" onClick={() => setTemplate(t.key)}
              className={cn("rounded-xl border bg-card p-4 text-start transition hover:shadow-md",
                template === t.key && "border-primary ring-2 ring-primary/30")}>
              <div className="flex items-center justify-between">
                <span className="font-medium">{locale === "ar" ? t.name_ar : t.name}</span>
                {template === t.key && <Check className="h-4 w-4 text-primary" />}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{t.description}</p>
              <div className="mt-2 flex gap-2">
                <Badge variant="outline">{t.industry}</Badge>
                {t.needs_database && <Badge variant="secondary">connects to your database</Badge>}
              </div>
            </button>
          ))}
        </div>
        <Card>
          <CardContent className="space-y-3 p-5">
            <div className="space-y-1.5">
              <Label htmlFor="business">Business name (used in the greeting)</Label>
              <Input id="business" placeholder="e.g. عيادة الشفاء / ABC Clinic" value={business} onChange={(e) => setBusiness(e.target.value)} />
            </div>
            <ErrorBox error={create.error} />
            <Button onClick={() => create.mutate()} disabled={create.isPending}>Create agent</Button>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
