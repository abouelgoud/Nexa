"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Button, Card, CardContent, Input, Label } from "@nexa/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ErrorBox } from "@/components/error-box";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

const schema = z.object({
  full_name: z.string().min(1, "Enter your name"),
  tenant_name: z.string().min(1, "Enter your business name"),
  email: z.email("Enter a valid email"),
  password: z.string().min(8, "Use at least 8 characters"),
});
type Values = z.infer<typeof schema>;

export default function RegisterPage() {
  const { register: signUp } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const [error, setError] = useState<unknown>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const field = (name: keyof Values, label: string, type = "text") => (
    <div className="space-y-1.5">
      <Label htmlFor={name}>{label}</Label>
      <Input id={name} type={type} {...form.register(name)} />
      <p className="text-xs text-destructive">{form.formState.errors[name]?.message}</p>
    </div>
  );
  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      await signUp(values);
      router.replace("/agents/new");
    } catch (e) {
      setError(e);
    }
  });
  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <form onSubmit={onSubmit} className="space-y-3">
          {field("full_name", t("fullName"))}
          {field("tenant_name", t("businessName"))}
          {field("email", t("email"), "email")}
          {field("password", t("password"), "password")}
          <ErrorBox error={error} />
          <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>{t("register")}</Button>
        </form>
        <p className="text-center text-sm text-muted-foreground">
          {t("haveAccount")} <Link href="/login" className="text-primary hover:underline">{t("signIn")}</Link>
        </p>
      </CardContent>
    </Card>
  );
}
