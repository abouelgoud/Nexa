export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-50 via-background to-sky-50 p-4 dark:from-slate-950 dark:to-slate-900">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-xl font-bold text-primary-foreground">N</div>
          <h1 className="text-2xl font-semibold">Nexa</h1>
          <p className="text-sm text-muted-foreground">AI phone agents for your business - no code needed.</p>
        </div>
        {children}
      </div>
    </div>
  );
}
