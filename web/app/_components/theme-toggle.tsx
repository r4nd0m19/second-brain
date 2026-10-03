"use client";

import { useEffect, useState } from "react";

import { useLang } from "@/lib/i18n";
import { effectiveTheme, toggleTheme, type ThemeMode } from "@/lib/theme";

/** 亮/暗切换按钮：初始跟随系统，点击后手动覆盖（本地记忆）。 */
export default function ThemeToggle() {
  const { t } = useLang();
  const [theme, setTheme] = useState<ThemeMode>("dark");

  useEffect(() => {
    setTheme(effectiveTheme());
  }, []);

  const nextLabel = theme === "dark" ? t("toggle.toLight") : t("toggle.toDark");
  return (
    <button
      className="btn theme-toggle"
      title={nextLabel}
      aria-label={nextLabel}
      onClick={() => setTheme(toggleTheme())}
    >
      {theme === "dark" ? "☀️" : "🌙"}
    </button>
  );
}
