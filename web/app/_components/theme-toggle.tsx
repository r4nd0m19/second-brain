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
      {theme === "dark" ? (
        // 太阳（切到亮色）：SVG——emoji 在无色彩字体环境渲染为豆腐块（手机端巡检发现）
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M12 3.2v2.2M12 18.6v2.2M3.2 12h2.2M18.6 12h2.2M5.9 5.9l1.5 1.5M16.6 16.6l1.5 1.5M18.1 5.9l-1.5 1.5M7.4 16.6l-1.5 1.5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        // 月亮（切到暗色）
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M20.2 14.6A8.4 8.4 0 0 1 9.4 3.8a8.4 8.4 0 1 0 10.8 10.8Z"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  );
}
