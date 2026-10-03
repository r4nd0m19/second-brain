"use client";

/** 中英切换（2026-10-03）：显示将切换到的语言（中文界面显示 EN，英文界面显示 中）。 */

import { useLang } from "@/lib/i18n";

export default function LangToggle() {
  const { lang, setLang, t } = useLang();
  const next = lang === "zh" ? "en" : "zh";
  const label = lang === "zh" ? t("toggle.toEnglish") : t("toggle.toChinese");
  return (
    <button
      className="btn lang-toggle"
      title={label}
      aria-label={label}
      onClick={() => setLang(next)}
    >
      {lang === "zh" ? "EN" : "中"}
    </button>
  );
}
