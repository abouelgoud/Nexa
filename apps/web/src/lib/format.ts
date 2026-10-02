import { DIALECT_LABELS } from "@nexa/agent-schema";

export function dialectName(code: string | null | undefined): string {
  if (!code) return "-";
  return (DIALECT_LABELS as Record<string, { en: string }>)[code]?.en ?? code;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "-";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}m ${s}s` : `${s}s`;
}

export const OUTCOME_VARIANT: Record<string, "success" | "warning" | "danger" | "secondary"> = {
  task_completed: "success", info_provided: "success", transferred: "warning", failed: "danger",
  completed: "secondary", abandoned: "secondary",
};
