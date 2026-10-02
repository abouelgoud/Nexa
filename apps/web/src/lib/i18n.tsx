"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/** Arabic/English from day one: UI strings + document direction. */
const dict = {
  en: {
    dashboard: "Dashboard", agents: "Agents", voices: "Voices", calls: "Calls", settings: "Settings", logout: "Sign out",
    newAgent: "New agent", general: "General", languages: "Languages", voice: "Voice", personality: "Personality",
    knowledge: "Knowledge", actions: "Actions", workflow: "Workflow", integrations: "Integrations", phone: "Phone",
    testing: "Testing", publish: "Publish", analytics: "Analytics", save: "Save changes", saved: "Saved",
    signIn: "Sign in", register: "Create account", email: "Email", password: "Password", fullName: "Full name",
    businessName: "Business name", noAccount: "No account yet?", haveAccount: "Already have an account?",
    language: "العربية", behaviour: "Behaviour & safety", privacy: "Privacy & recording",
  },
  ar: {
    dashboard: "لوحة التحكم", agents: "الوكلاء", voices: "الأصوات", calls: "المكالمات", settings: "الإعدادات", logout: "تسجيل الخروج",
    newAgent: "وكيل جديد", general: "عام", languages: "اللغات", voice: "الصوت", personality: "الشخصية",
    knowledge: "المعرفة", actions: "الإجراءات", workflow: "سير المحادثة", integrations: "الربط", phone: "الهاتف",
    testing: "التجربة", publish: "النشر", analytics: "التحليلات", save: "حفظ التغييرات", saved: "تم الحفظ",
    signIn: "تسجيل الدخول", register: "إنشاء حساب", email: "البريد الإلكتروني", password: "كلمة المرور",
    fullName: "الاسم الكامل", businessName: "اسم النشاط التجاري", noAccount: "ليس لديك حساب؟",
    haveAccount: "لديك حساب؟", language: "English", behaviour: "السلوك والأمان", privacy: "الخصوصية والتسجيل",
  },
} as const;

export type Locale = keyof typeof dict;
type Key = keyof (typeof dict)["en"];

const I18nContext = createContext<{ locale: Locale; t: (k: Key) => string; toggle: () => void }>({
  locale: "en", t: (k) => dict.en[k], toggle: () => {},
});

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState<Locale>("en");
  useEffect(() => {
    const saved = localStorage.getItem("nexa.locale");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the saved preference once on mount
    if (saved === "ar" || saved === "en") setLocale(saved);
  }, []);
  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
    localStorage.setItem("nexa.locale", locale);
  }, [locale]);
  const t = useCallback((k: Key) => dict[locale][k] ?? dict.en[k], [locale]);
  const value = useMemo(() => ({ locale, t, toggle: () => setLocale((l) => (l === "en" ? "ar" : "en")) }), [locale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export const useI18n = () => useContext(I18nContext);
