"use client";

import { Spinner } from "@nexa/ui";

import { PageHeader } from "@/components/app-shell";
import { CallsTable } from "@/components/calls-table";
import { useCalls } from "@/lib/queries";

export default function CallsPage() {
  const calls = useCalls();
  return (
    <>
      <PageHeader title="Calls" description="Every phone and browser call, with transcript, actions and workflow path." />
      <div className="p-6">{calls.isLoading ? <Spinner /> : <CallsTable calls={calls.data ?? []} />}</div>
    </>
  );
}
