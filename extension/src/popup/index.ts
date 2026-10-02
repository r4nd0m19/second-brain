/** 弹窗（F2 FR-008）：连接/暂停状态、队列深度、今日计数、最近错误、暂停开关。 */

import type { QueueEntry } from "../shared/messages";
import { loadSettings, saveSettings } from "../shared/settings";

function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T;
}

const statusEl = el<HTMLDivElement>("status");
const statsEl = el<HTMLDivElement>("stats");
const errorEl = el<HTMLDivElement>("error");
const debugEl = el<HTMLDivElement>("debug");
const pausedEl = el<HTMLInputElement>("paused");
const optionsEl = el<HTMLButtonElement>("options");

async function render(): Promise<void> {
  const settings = await loadSettings();
  const stored = (await chrome.storage.local.get([
    "queue",
    "stats",
    "lastError",
    "lastSnapshotError",
    "offscreenDebug",
  ])) as {
    queue?: QueueEntry[];
    stats?: { date: string; count: number };
    lastError?: string | null;
    lastSnapshotError?: string | null;
    offscreenDebug?: string | null;
  };
  const queue = stored.queue ?? [];
  const pending = queue.filter((e) => e.status === "pending").length;
  const dead = queue.filter((e) => e.status === "dead").length;
  const authError = queue.some((e) => e.status === "auth-error");

  pausedEl.checked = settings.paused;

  if (!settings.serverUrl || !settings.token) {
    statusEl.textContent = "未配置";
    statusEl.style.color = "#9a6b00";
  } else if (authError) {
    statusEl.textContent = "凭据无效（需更新设置）";
    statusEl.style.color = "#b3261e";
  } else if (settings.paused) {
    statusEl.textContent = "已暂停";
    statusEl.style.color = "#9a6b00";
  } else {
    statusEl.textContent = "采集中";
    statusEl.style.color = "#1e7d4f";
  }

  const today = new Date().toLocaleDateString("sv-SE");
  const todayCount = stored.stats && stored.stats.date === today ? stored.stats.count : 0;
  statsEl.textContent = `今日采集：${todayCount} 篇｜待传：${pending}${dead ? `｜失败：${dead}` : ""}`;

  const errorLines: string[] = [];
  if (stored.lastError) errorLines.push(`最近错误：${stored.lastError}`);
  if (stored.lastSnapshotError) errorLines.push(`最近快照：${stored.lastSnapshotError}`);
  if (errorLines.length > 0) {
    errorEl.textContent = errorLines.join("\n");
    errorEl.style.display = "block";
  } else {
    errorEl.style.display = "none";
  }

  if (stored.offscreenDebug) {
    debugEl.textContent = `离屏：${stored.offscreenDebug}`;
    debugEl.style.display = "block";
  } else {
    debugEl.style.display = "none";
  }
}

pausedEl.addEventListener("change", () => {
  void (async () => {
    await saveSettings({ paused: pausedEl.checked });
    await render();
  })();
});

optionsEl.addEventListener("click", () => {
  void chrome.runtime.openOptionsPage();
});

void render();
