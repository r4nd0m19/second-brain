"use client";

import { useEffect, useState } from "react";

import { effectiveTheme, toggleTheme, type ThemeMode } from "@/lib/theme";

/** 亮/暗切换按钮：初始跟随系统，点击后手动覆盖（本地记忆）。 */
export default function ThemeToggle() {
  const [theme, setTheme] = useState<ThemeMode>("dark");

  useEffect(() => {
    setTheme(effectiveTheme());
  }, []);

  const nextLabel = theme === "dark" ? "切换到白天模式" : "切换到夜间模式";
  return (
    <button
      className="btn"
      style={{ marginLeft: 8 }}
      title={nextLabel}
      aria-label={nextLabel}
      onClick={() => setTheme(toggleTheme())}
    >
      {theme === "dark" ? "☀️" : "🌙"}
    </button>
  );
}
