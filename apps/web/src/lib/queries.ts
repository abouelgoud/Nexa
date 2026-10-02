"use client";

import type {
  AgentDetail, AgentVersion, Analytics, CallDetail, CallSummary, Checklist, Integration, KnowledgeBase,
  PhoneNumber, Template, Tool, WorkflowDetail,
} from "@nexa/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { get, put } from "./api";
import { useAuth } from "./auth";

/** Every query key is scoped by tenant so switching business never shows stale data. */
function useTenantKey() {
  return useAuth().tenantId ?? "none";
}

export function useAgents() {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "agents"], queryFn: () => get<AgentDetail[]>("/agents") });
}

export function useAgent(id: string) {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "agent", id], queryFn: () => get<AgentDetail>(`/agents/${id}`) });
}

export function useSaveAgentConfig(id: string) {
  const t = useTenantKey();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (config: unknown) => put<AgentDetail>(`/agents/${id}/config`, config),
    onSuccess: (data) => {
      qc.setQueryData([t, "agent", id], data);
      void qc.invalidateQueries({ queryKey: [t, "checklist", id] });
      void qc.invalidateQueries({ queryKey: [t, "agents"] });
    },
  });
}

export function useChecklist(id: string) {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "checklist", id], queryFn: () => get<Checklist>(`/agents/${id}/checklist`) });
}

export function useVersions(id: string) {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "versions", id], queryFn: () => get<AgentVersion[]>(`/agents/${id}/versions`) });
}

export function useTemplates() {
  return useQuery({ queryKey: ["templates"], queryFn: () => get<Template[]>("/templates"), staleTime: Infinity });
}

export function useTools() {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "tools"], queryFn: () => get<Tool[]>("/tools") });
}

export function useIntegrations() {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "integrations"], queryFn: () => get<Integration[]>("/integrations") });
}

export function useKnowledgeBases() {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "kbs"], queryFn: () => get<KnowledgeBase[]>("/knowledge") });
}

export function useWorkflow(id: string | null | undefined) {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "workflow", id], queryFn: () => get<WorkflowDetail>(`/workflows/${id}`), enabled: !!id });
}

export function usePhoneNumbers(agentId?: string) {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "phones", agentId], queryFn: () =>
    get<PhoneNumber[]>(`/phone-numbers${agentId ? `?agent_id=${agentId}` : ""}`) });
}

export function useCalls(agentId?: string) {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "calls", agentId], queryFn: () =>
    get<CallSummary[]>(`/calls${agentId ? `?agent_id=${agentId}` : ""}`), refetchInterval: 10_000 });
}

export function useCall(id: string) {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "call", id], queryFn: () => get<CallDetail>(`/calls/${id}`) });
}

export function useAnalytics(agentId?: string, days = 30) {
  const t = useTenantKey();
  return useQuery({ queryKey: [t, "analytics", agentId, days], queryFn: () =>
    get<Analytics>(`/analytics/overview?days=${days}${agentId ? `&agent_id=${agentId}` : ""}`) });
}
