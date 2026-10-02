"use client";

import { Alert } from "@nexa/ui";

import { ApiError } from "@/lib/api";

/** Shows API errors in business language, including per-field explanations. */
export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as Error;
  const lines = error instanceof ApiError ? error.lines : [];
  return (
    <Alert variant="error">
      <p className="font-medium">{e.message}</p>
      {lines.length > 0 && (
        <ul className="mt-1 list-disc ps-5">
          {lines.map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      )}
    </Alert>
  );
}
