// 亮/暗双模式：默认跟随系统；手动切换后写入 localStorage 覆盖系统。

export type ThemeMode = "light" | "dark";

const KEY = "sb-theme";
const COLORS: Record<ThemeMode, string> = { light: "#f6f7f9", dark: "#0f1115" };

export function getStoredTheme(): ThemeMode | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function effectiveTheme(): ThemeMode {
  const stored = getStoredTheme();
  if (stored) return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function syncMeta(mode: ThemeMode): void {
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", COLORS[mode]);
}

/** 应用主题：传 null 表示回到"跟随系统"（清除手动覆盖）。 */
export function applyTheme(mode: ThemeMode | null): void {
  const root = document.documentElement;
  if (mode) {
    root.dataset.theme = mode;
  } else {
    delete root.dataset.theme;
  }
  syncMeta(mode ?? effectiveTheme());
}

export function toggleTheme(): ThemeMode {
  const next: ThemeMode = effectiveTheme() === "dark" ? "light" : "dark";
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* 忽略 */
  }
  applyTheme(next);
  return next;
}
