"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  ARABIC_DIALECTS, CAPABILITIES, DAYS, DIALECT_LABELS, TONES, VERBOSITY, agentDefinitionSchema,
  type AgentDefinition, type AgentDefinitionInput,
} from "@nexa/agent-schema";
import type { AgentDetail, WorkflowSummary } from "@nexa/shared-types";
import {
  Alert, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, Select, Spinner,
  Switch, Textarea,
} from "@nexa/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Plus, Trash2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Controller, useFieldArray, useForm, type Control } from "react-hook-form";

import { ErrorBox } from "@/components/error-box";
import { VoiceUpload } from "@/components/voice-upload";
import { get, post } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useAgent, useChecklist, useSaveAgentConfig, useVersions } from "@/lib/queries";

const CAPABILITY_LABELS: Record<string, string> = {
  answer_questions: "Answer questions from your knowledge", book_appointment: "Book appointments",
  cancel_appointment: "Cancel appointments", reschedule_appointment: "Reschedule appointments",
  get_appointment: "Look up appointments", transfer_call: "Transfer to a human", take_order: "Take orders",
  check_order_status: "Check order status", make_reservation: "Make reservations", capture_lead: "Capture leads",
  collect_information: "Collect information",
};

type Form = ReturnType<typeof useForm<AgentDefinitionInput, unknown, AgentDefinition>>;

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle>{description && <CardDescription>{description}</CardDescription>}</CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  );
}

function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function SwitchField({ control, name, label, hint }: { control: Control<AgentDefinitionInput, unknown, AgentDefinition>; name: any; label: string; hint?: string }) {
  return (
    <Controller control={control} name={name} render={({ field }) => (
      <div className="flex items-start justify-between gap-4 rounded-lg border p-3">
        <div><div className="text-sm font-medium">{label}</div>{hint && <div className="text-xs text-muted-foreground">{hint}</div>}</div>
        <Switch checked={!!field.value} onCheckedChange={field.onChange} />
      </div>
    )} />
  );
}

function MultiToggle<T extends string>({ value, options, onChange, label }: {
  value: T[]; options: readonly T[]; onChange: (v: T[]) => void; label: (v: T) => string;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button key={o} type="button" onClick={() => onChange(on ? value.filter((v) => v !== o) : [...value, o])}
            className={`rounded-full border px-3 py-1 text-sm transition ${on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent"}`}>
            {label(o)}
          </button>
        );
      })}
    </div>
  );
}

function GeneralSection({ form }: { form: Form }) {
  const { register, control, formState: { errors } } = form;
  const hours = useFieldArray({ control, name: "general.operating_hours" as const });
  return (
    <Section title="General" description="Who the agent is and when your business is open.">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Agent name" error={errors.name?.message}><Input {...register("name")} /></Field>
        <Field label="Business name"><Input {...register("general.business_name")} /></Field>
        <Field label="Industry"><Input {...register("general.industry")} /></Field>
        <Field label="Timezone" hint="e.g. Asia/Riyadh, Asia/Dubai, Africa/Cairo"><Input {...register("general.timezone")} /></Field>
      </div>
      <Field label="Description"><Textarea rows={2} {...register("description")} /></Field>
      <Field label="Greeting (Arabic)" hint="The first sentence callers hear. You can use {{business_name}}.">
        <Textarea dir="auto" rows={2} {...register("general.greeting")} />
      </Field>
      <Field label="Greeting (English)"><Textarea dir="auto" rows={2} {...register("general.greeting_en")} /></Field>
      <div className="space-y-2">
        <Label>Operating hours</Label>
        {hours.fields.map((f, i) => (
          <div key={f.id} className="flex items-center gap-2">
            <Select className="w-28" {...register(`general.operating_hours.${i}.day` as const)}>
              {DAYS.map((d) => <option key={d} value={d}>{d}</option>)}
            </Select>
            <Input type="time" className="w-32" {...register(`general.operating_hours.${i}.open` as const)} />
            <span>–</span>
            <Input type="time" className="w-32" {...register(`general.operating_hours.${i}.close` as const)} />
            <Button type="button" variant="ghost" size="icon" onClick={() => hours.remove(i)}><Trash2 className="h-4 w-4" /></Button>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => hours.append({ day: "sun", open: "09:00", close: "17:00" })}>
          <Plus className="h-3.5 w-3.5" /> Add hours
        </Button>
      </div>
    </Section>
  );
}

function LanguageSection({ form }: { form: Form }) {
  const { control, register, watch } = form;
  const languages = watch("languages") ?? [];
  return (
    <Section title="Languages" description="Callers can speak Arabic, English or mix both. Dialects are detected automatically - callers never have to choose.">
      <Controller control={control} name="languages" render={({ field }) => (
        <Field label="Languages the agent speaks">
          <MultiToggle value={(field.value ?? []) as ("ar" | "en")[]} options={["ar", "en"] as const}
            label={(l) => (l === "ar" ? "Arabic · العربية" : "English")} onChange={field.onChange} />
        </Field>
      )} />
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Reply language">
          <Select {...register("language_behavior.mode")}>
            <option value="match_caller">Match the caller</option>
            <option value="fixed">Always the primary language</option>
          </Select>
        </Field>
        <Field label="Primary language">
          <Select {...register("language_behavior.primary_language")}>
            <option value="ar">Arabic</option><option value="en">English</option>
          </Select>
        </Field>
        <Field label="Agent's Arabic dialect">
          <Select {...register("language_behavior.response_dialect")}>
            <option value="match_caller">Mirror the caller</option>
            {ARABIC_DIALECTS.map((d) => <option key={d} value={d}>{DIALECT_LABELS[d].en} · {DIALECT_LABELS[d].ar}</option>)}
          </Select>
        </Field>
      </div>
      <Controller control={control} name="language_behavior.vocabulary" render={({ field }) => (
        <Field label="Words callers will say" hint="Names, specialties, products, neighbourhoods - one per line. Greatly improves recognition of names.">
          <LinesInput value={field.value ?? []} onChange={field.onChange} rows={3} placeholder={"د. سارة العتيبي\nالجلدية\nDermatology"} />
        </Field>
      )} />
      <SwitchField control={control} name="language_behavior.code_switching" label="Understand Arabic-English mixing"
        hint={'e.g. "أبغى أحجز appointment" or "ممكن check لي الطلب؟"'} />
      {languages.includes("ar") && (
        <Controller control={control} name="arabic_dialects" render={({ field }) => (
          <Field label="Expected Arabic dialects" hint="Used as a hint for detection only. Leave all selected if unsure.">
            <MultiToggle value={(field.value ?? []) as (typeof ARABIC_DIALECTS[number])[]} options={ARABIC_DIALECTS}
              label={(d) => DIALECT_LABELS[d].en} onChange={field.onChange} />
          </Field>
        )} />
      )}
    </Section>
  );
}

type VoiceProvider = { key: string; label: string; kind: string; cloning: boolean; note: string; configured: boolean;
  voices: { id: string; name: string; dialect?: string | null; gender?: string }[] };

function playBase64(clip: { mime_type: string; audio_base64: string }) {
  void new Audio(`data:${clip.mime_type};base64,${clip.audio_base64}`).play();
}

/** One entry per line. Keeps the typed text (blank lines included) while editing; stores the non-empty lines. */
function LinesInput({ value, onChange, rows, placeholder }: { value: string[]; onChange: (lines: string[]) => void; rows: number; placeholder: string }) {
  const [text, setText] = useState(value.join("\n"));
  const clean = (t: string) => t.split("\n").map((w) => w.trim()).filter(Boolean);
  useEffect(() => {
    if (clean(text).join("\n") !== value.join("\n")) setText(value.join("\n"));
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return <Textarea dir="auto" rows={rows} placeholder={placeholder} value={text}
    onChange={(e) => { setText(e.target.value); onChange(clean(e.target.value)); }} />;
}

function VoiceSection({ form }: { form: Form }) {
  const { register, control, watch, setValue } = form;
  const qc = useQueryClient();
  const catalog = useQuery({ queryKey: ["voice-catalog"], queryFn: () => get<{ providers: VoiceProvider[] }>("/voices/catalog") });
  const providerKey = watch("voice.provider") === "piper" ? "local" : watch("voice.provider") ?? "local";
  const provider = catalog.data?.providers.find((p) => p.key === providerKey);
  const voices = provider?.voices ?? [];
  const arabicVoices = providerKey === "azure" ? voices.filter((v) => v.dialect) : voices;
  const englishVoices = providerKey === "azure" ? voices.filter((v) => !v.dialect) : voices;
  const preview = useMutation({
    mutationFn: (language: "ar" | "en") => post<{ mime_type: string; audio_base64: string }>("/voices/preview", {
      provider: providerKey, language, speed: watch("voice.speed") ?? 1,
      voice_id: (language === "en" && watch("voice.english_voice_id")) || watch("voice.voice_id") }),
    onSuccess: playBase64,
  });
  const choose = (key: string) => {
    setValue("voice.provider", key as never, { shouldDirty: true });
    const first = catalog.data?.providers.find((p) => p.key === key)?.voices;
    if (key === "azure") {
      setValue("voice.voice_id", "ar-SA-HamedNeural", { shouldDirty: true });
      setValue("voice.english_voice_id", "en-US-AndrewMultilingualNeural", { shouldDirty: true });
    } else if (first?.length) {
      setValue("voice.voice_id", first[0].id, { shouldDirty: true });
      setValue("voice.english_voice_id", key === "local" ? first[first.length - 1].id : null, { shouldDirty: true });
    }
  };
  const voiceSelect = (field: "voice.voice_id" | "voice.english_voice_id", list: VoiceProvider["voices"]) =>
    list.length > 0 ? (
      <Select value={watch(field) ?? ""} onChange={(e) => setValue(field, e.target.value, { shouldDirty: true })}>
        {!list.some((v) => v.id === watch(field)) && watch(field) && <option value={watch(field) ?? ""}>{watch(field)}</option>}
        {list.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
      </Select>
    ) : <Input {...register(field)} placeholder="Voice ID" />;

  return (
    <Section title="Voice" description="How your agent sounds. Natural voices sound like a real person; you can also use your own voice.">
      <div className="grid gap-3 md:grid-cols-2">
        {catalog.data?.providers.map((p) => (
          <button key={p.key} type="button" onClick={() => choose(p.key)}
            className={`rounded-lg border p-3 text-start transition ${providerKey === p.key ? "border-primary ring-2 ring-primary/30" : "hover:bg-accent"}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{p.label}</span>
              <Badge variant={p.configured ? "success" : "outline"}>{p.configured ? "available" : "not set up"}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{p.note}</p>
          </button>
        ))}
      </div>
      {provider && !provider.configured && (
        <Alert variant="warning">
          {providerKey === "elevenlabs" ? "Add ELEVENLABS_API_KEY on the server to use ElevenLabs voices."
            : providerKey === "azure" ? "Add AZURE_SPEECH_KEY and AZURE_SPEECH_REGION on the server to use Azure voices."
              : providerKey === "neural" ? "Start the natural voice service (docker compose --profile neural up) to use these voices."
                : "The voice service is not running."}
        </Alert>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Arabic voice">{voiceSelect("voice.voice_id", arabicVoices)}</Field>
        <Field label="English voice" hint={providerKey !== "local" && providerKey !== "azure" ? "Optional - the Arabic voice also speaks English." : undefined}>
          {voiceSelect("voice.english_voice_id", englishVoices)}
        </Field>
        <Field label="Speaking speed"><Input type="number" step="0.05" min="0.5" max="2" {...register("voice.speed", { valueAsNumber: true })} /></Field>
      </div>
      {providerKey === "azure" && (
        <div className="grid gap-3 md:grid-cols-2">
          <SwitchField control={control} name="voice.match_caller_dialect" label="Answer in the caller's dialect"
            hint="Saudi callers hear a Saudi voice, Egyptian callers an Egyptian voice, and so on." />
          <Field label="Voice gender">
            <Select {...register("voice.gender")}><option value="male">Male</option><option value="female">Female</option></Select>
          </Field>
        </div>
      )}
      <Controller control={control} name="voice.pronunciations" render={({ field }) => (
        <Field label="Pronunciation" hint={'How to say your own names and terms, one per line: "word = how to say it". Add vowels to fix an Arabic word, e.g. "أقدر = أَقْدَر". Everyday spoken words are already handled.'}>
          <LinesInput value={field.value ?? []} onChange={field.onChange} rows={3}
            placeholder={"Nexa = نِكْسَا\nد. = دكتورة\nالعتيبي = العُتَيْبِي"} />
        </Field>
      )} />
      <SwitchField control={control} name="voice.thinking_fillers" label="Natural pauses"
        hint={'Says "لحظة من فضلك" / "One moment" when checking information takes a moment, instead of going silent.'} />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" disabled={preview.isPending || !provider?.configured} onClick={() => preview.mutate("ar")}>▶ Preview Arabic</Button>
        <Button type="button" variant="outline" size="sm" disabled={preview.isPending || !provider?.configured} onClick={() => preview.mutate("en")}>▶ Preview English</Button>
        {preview.isPending && <Spinner />}
      </div>
      <ErrorBox error={preview.error} />
      {provider?.cloning && (
        <details className="rounded-lg border border-dashed p-3">
          <summary className="cursor-pointer text-sm font-medium">Use your own voice</summary>
          <div className="mt-3 space-y-2">
            <VoiceUpload engines={[{ key: providerKey as "neural" | "elevenlabs", label: provider.label, available: provider.configured }]}
              defaultEngine={providerKey}
              onCreated={(v) => { void qc.invalidateQueries({ queryKey: ["voice-catalog"] }); setValue("voice.voice_id", v.voice_id, { shouldDirty: true }); }} />
            <p className="text-xs text-muted-foreground">All your voices are managed on the <Link href="/voices" className="text-primary hover:underline">Voices</Link> page.</p>
          </div>
        </details>
      )}
    </Section>
  );
}

function PersonalitySection({ form }: { form: Form }) {
  const { register } = form;
  return (
    <Section title="Personality">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Tone"><Select {...register("personality.tone")}>{TONES.map((t) => <option key={t}>{t}</option>)}</Select></Field>
        <Field label="Answer length"><Select {...register("personality.verbosity")}>{VERBOSITY.map((t) => <option key={t}>{t}</option>)}</Select></Field>
      </div>
      <Field label="Extra instructions" hint="Plain-language guidance, e.g. 'Mention that parking is free.' Never put passwords here.">
        <Textarea dir="auto" rows={3} {...register("personality.custom_instructions")} />
      </Field>
    </Section>
  );
}

function BehaviourSection({ form, agentId }: { form: Form; agentId: string }) {
  const { control, register, watch } = form;
  const targets = useFieldArray({ control, name: "handoff.targets" as const });
  const workflows = useQuery({ queryKey: ["workflows", agentId], queryFn: () => get<WorkflowSummary[]>(`/workflows?agent_id=${agentId}`) });
  const mode = watch("execution_mode");
  return (
    <Section title="Behaviour & safety" description="Exactly what the AI is allowed to do.">
      <Controller control={control} name="capabilities" render={({ field }) => (
        <Field label="What can the agent do?">
          <MultiToggle value={(field.value ?? []) as (typeof CAPABILITIES[number])[]} options={CAPABILITIES}
            label={(c) => CAPABILITY_LABELS[c] ?? c} onChange={field.onChange} />
        </Field>
      )} />
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="How the conversation is driven">
          <Select {...register("execution_mode")}>
            <option value="agent">AI decides (uses your actions and knowledge)</option>
            <option value="workflow">Follow my visual workflow</option>
          </Select>
        </Field>
        <Field label="Workflow" hint={mode === "workflow" ? "Required in workflow mode." : "Optional."}>
          <Controller control={control} name="workflow_id" render={({ field }) => (
            <Select value={field.value ?? ""} onChange={(e) => field.onChange(e.target.value || null)}>
              <option value="">None</option>
              {workflows.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          )} />
        </Field>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <SwitchField control={control} name="policies.require_confirmation_for_booking" label="Confirm before booking"
          hint="The caller must say yes before anything is booked or changed." />
        <SwitchField control={control} name="policies.never_invent_information" label="Never invent information"
          hint="Only answer from your knowledge and systems." />
        <SwitchField control={control} name="policies.human_handoff_enabled" label="Allow human handoff" />
      </div>
      <div className="space-y-2">
        <Label>Transfer destinations</Label>
        {targets.fields.map((f, i) => (
          <div key={f.id} className="grid grid-cols-12 items-center gap-2">
            <Input className="col-span-2" placeholder="key" {...register(`handoff.targets.${i}.key` as const)} />
            <Input className="col-span-4" placeholder="Reception" {...register(`handoff.targets.${i}.label` as const)} />
            <Input className="col-span-4" placeholder="+9661..." {...register(`handoff.targets.${i}.phone_number` as const)} />
            <Button type="button" variant="ghost" size="icon" onClick={() => targets.remove(i)}><Trash2 className="h-4 w-4" /></Button>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm"
          onClick={() => targets.append({ key: "reception", label: "Reception", phone_number: "", only_during_business_hours: false })}>
          <Plus className="h-3.5 w-3.5" /> Add destination
        </Button>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Default destination key"><Input {...register("handoff.default_target", { setValueAs: (v) => v || null })} /></Field>
          <Field label="After-hours message"><Input dir="auto" {...register("handoff.after_hours_message")} /></Field>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <SwitchField control={control} name="handoff.on_explicit_request" label="When the caller asks for a person" />
          <SwitchField control={control} name="handoff.on_low_confidence" label="When the agent is struggling" />
          <SwitchField control={control} name="handoff.on_task_failure" label="When an action fails" />
        </div>
      </div>
    </Section>
  );
}

function PrivacySection({ form }: { form: Form }) {
  const { control, register, watch } = form;
  return (
    <Section title="Privacy & recording" description="Recording rules differ by country. Configure consent and retention to match the law that applies to you.">
      <div className="grid gap-3 md:grid-cols-3">
        <SwitchField control={control} name="privacy.record_calls" label="Record calls" />
        <SwitchField control={control} name="privacy.store_audio" label="Store audio" />
        <SwitchField control={control} name="privacy.store_transcript" label="Store transcripts" />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Keep data for (days)"><Input type="number" min={1} {...register("privacy.retention_days", { valueAsNumber: true })} /></Field>
        <SwitchField control={control} name="privacy.consent_required" label="Play a consent message first" />
      </div>
      {watch("privacy.consent_required") && (
        <Field label="Consent message"><Textarea dir="auto" rows={2} {...register("privacy.consent_message")} /></Field>
      )}
    </Section>
  );
}

function PublishPanel({ agent }: { agent: AgentDetail }) {
  const checklist = useChecklist(agent.id);
  const versions = useVersions(agent.id);
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const publish = useMutation({
    mutationFn: () => post(`/agents/${agent.id}/publish`, { notes }),
    onSuccess: () => { setNotes(""); void qc.invalidateQueries(); },
  });
  const activate = useMutation({
    mutationFn: (vid: string) => post(`/agents/${agent.id}/versions/${vid}/activate`),
    onSuccess: () => void qc.invalidateQueries(),
  });
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Publish</CardTitle><CardDescription>Draft → Validate → Test → Publish. Live calls always use one fixed published version.</CardDescription></CardHeader>
        <CardContent className="space-y-3">
          {checklist.isLoading && <Spinner />}
          <ul className="space-y-2">
            {checklist.data?.items.map((i) => (
              <li key={i.key} className="flex gap-2 text-sm">
                {i.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  : i.severity === "error" ? <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
                    : <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />}
                <div><div>{i.label}</div>{!i.ok && <div className="text-xs text-muted-foreground">{i.message}</div>}</div>
              </li>
            ))}
          </ul>
          <Input placeholder="What changed? (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <ErrorBox error={publish.error} />
          {publish.isSuccess && <Alert variant="success">Published. New calls now use the new version.</Alert>}
          <Button type="button" className="w-full" disabled={!checklist.data?.ready || publish.isPending} onClick={() => publish.mutate()}>
            Publish new version
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm">Versions</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {versions.data?.length === 0 && <p className="text-sm text-muted-foreground">Nothing published yet.</p>}
          {versions.data?.map((v) => (
            <div key={v.id} className="flex items-center justify-between rounded-md border p-2 text-sm">
              <div>
                <span className="font-medium">v{v.version_number}</span>{" "}
                <Badge variant={v.kind === "published" ? "default" : "outline"}>{v.kind}</Badge>
                {agent.published_version_id === v.id && <Badge variant="success" className="ms-1">live</Badge>}
                <div className="text-xs text-muted-foreground">{formatDate(v.created_at)} {v.notes && `· ${v.notes}`}</div>
              </div>
              {v.kind === "published" && agent.published_version_id !== v.id && (
                <Button type="button" size="sm" variant="outline" onClick={() => activate.mutate(v.id)}>Make live</Button>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

export default function AgentSettingsPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const { data: agent } = useAgent(id);
  const save = useSaveAgentConfig(id);
  const form = useForm<AgentDefinitionInput, unknown, AgentDefinition>({ resolver: zodResolver(agentDefinitionSchema) });
  useEffect(() => {
    if (agent) form.reset(agent.draft_config as AgentDefinitionInput);
  }, [agent, form]);
  if (!agent) return <div className="p-6"><Spinner /></div>;
  const formErrors = Object.keys(form.formState.errors).length > 0;
  return (
    <form onSubmit={form.handleSubmit((values) => save.mutate(values))} className="grid gap-6 p-6 xl:grid-cols-3">
      <div className="space-y-6 xl:col-span-2">
        <GeneralSection form={form} />
        <LanguageSection form={form} />
        <VoiceSection form={form} />
        <PersonalitySection form={form} />
        <BehaviourSection form={form} agentId={id} />
        <PrivacySection form={form} />
      </div>
      <div className="space-y-4">
        <Card className="sticky top-4 z-10">
          <CardContent className="space-y-3 p-4">
            {formErrors && <Alert variant="error">Some settings need attention. Check the highlighted fields.</Alert>}
            <ErrorBox error={save.error} />
            {save.isSuccess && !form.formState.isDirty && <Alert variant="success">{t("saved")}</Alert>}
            <Button type="submit" className="w-full" disabled={save.isPending}>{t("save")}</Button>
            <p className="text-xs text-muted-foreground">Saving updates the draft only. Published versions never change.</p>
          </CardContent>
        </Card>
        <PublishPanel agent={agent} />
      </div>
    </form>
  );
}
