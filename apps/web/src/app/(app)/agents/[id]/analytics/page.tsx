"use client";

import { Spinner } from "@nexa/ui";
import { useParams } from "next/navigation";

import { AnalyticsPanels } from "@/components/stats";
import { CallsTable } from "@/components/calls-table";
import { useAnalytics, useCalls } from "@/lib/queries";

export default function AgentAnalyticsPage() {
  const { id } = useParams<{ id: string }>();
  const analytics = useAnalytics(id);
  const calls = useCalls(id);
  return (
    <div className="space-y-6 p-6">
      {analytics.data ? <AnalyticsPanels data={analytics.data} /> : <Spinner />}
      <CallsTable calls={calls.data ?? []} />
    </div>
  );
}
