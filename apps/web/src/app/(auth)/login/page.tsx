"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Button, Card, CardContent, Input, Label } from "@nexa/ui";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ErrorBox } from "@/components/error-box";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

const schema = z.object({ email: z.email("Enter a valid email"), password: z.string().min(1, "Enter your password") });

function LoginForm() {
  const { login } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<unknown>(null);
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      await login(values.email, values.password);
      router.replace(params.get("next") || "/dashboard");
    } catch (e) {
      setError(e);
    }
  });

  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email">{t("email")}</Label>
            <Input id="email" type="email" autoComplete="email" {...form.register("email")} />
            <p className="text-xs text-destructive">{form.formState.errors.email?.message}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">{t("password")}</Label>
            <Input id="password" type="password" autoComplete="current-password" {...form.register("password")} />
            <p className="text-xs text-destructive">{form.formState.errors.password?.message}</p>
          </div>
          <ErrorBox error={error} />
          <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>{t("signIn")}</Button>
        </form>
        <p className="text-center text-sm text-muted-foreground">
          {t("noAccount")} <Link href="/register" className="text-primary hover:underline">{t("register")}</Link>
        </p>
      </CardContent>
    </Card>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
