"use client";

import { Alert } from "@nexa/ui";

import { ApiError } from "@/lib/api";

/** Shows API errors in business language, including per-field explanations. */
export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as Error;
  const lines = error instanceof ApiError ? error.lines : [];
  // The technical reason, when the server sent one (e.g. which service failed and how).
  const detail = error instanceof ApiError && typeof error.details === "string" ? error.details : null;
  return (
    <Alert variant="error">
      <p className="font-medium">{e.message}</p>
      {detail && <p className="mt-1 break-words font-mono text-xs opacity-75">{detail}</p>}
      {lines.length > 0 && (
        <ul className="mt-1 list-disc ps-5">
          {lines.map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      )}
    </Alert>
  );
}
