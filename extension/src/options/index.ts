/** 设置页（F2）：服务器地址 / 凭据 / 阈值 / 黑名单；保存并测试（/health → /api/capture/ping）。 */

import { DEFAULT_SETTINGS, loadSettings, saveSettings, validateServerUrl } from "../shared/settings";

function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T;
}

const els = {
  serverUrl: el<HTMLInputElement>("serverUrl"),
  token: el<HTMLInputElement>("token"),
  minSeconds: el<HTMLInputElement>("minSeconds"),
  scrollRatio: el<HTMLInputElement>("scrollRatio"),
  snapshotMaxMb: el<HTMLInputElement>("snapshotMaxMb"),
  metadataOnly: el<HTMLInputElement>("metadataOnly"),
  blocklist: el<HTMLTextAreaElement>("blocklist"),
  status: el<HTMLDivElement>("status"),
  save: el<HTMLButtonElement>("save"),
  test: el<HTMLButtonElement>("test"),
  diag: el<HTMLPreElement>("diag"),
  diagRefresh: el<HTMLButtonElement>("diag-refresh"),
};

interface DiagQueueEntry {
  status: string;
  url: string;
  attempts: number;
}

async function renderDiag(): Promise<void> {
  try {
    const stored = (await chrome.storage.local.get([
      "queue",
      "stats",
      "lastError",
      "lastSnapshotError",
      "lastSuccessAt",
    ])) as {
      queue?: DiagQueueEntry[];
      stats?: { date: string; count: number };
      lastError?: string | null;
      lastSnapshotError?: string | null;
      lastSuccessAt?: string | null;
    };
    const queue = stored.queue ?? [];
    const pending = queue.filter((e) => e.status === "pending").length;
    const dead = queue.filter((e) => e.status === "dead").length;
    const lines = [
      `待传 ${pending} ｜ 失败 ${dead} ｜ 队列共 ${queue.length}`,
      `最近成功：${stored.lastSuccessAt ?? "—"}`,
      `最近错误：${stored.lastError ?? "—"}`,
      `最近快照：${stored.lastSnapshotError ?? "—"}`,
      `今日采集：${stored.stats ? `${stored.stats.date} ${stored.stats.count} 篇` : "—"}`,
      ...queue.slice(0, 6).map((e) => `· [${e.status}] ${String(e.url).slice(0, 64)}（尝试 ${e.attempts} 次）`),
    ];
    els.diag.textContent = lines.join("\n");
  } catch (error) {
    els.diag.textContent = `诊断读取失败：${String(error)}`;
  }
}

function setStatus(text: string, kind: "ok" | "warn" | "err" | "" = ""): void {
  els.status.textContent = text;
  els.status.className = kind;
}

function clamp(value: number, min: number, max: number, fallback: number): number {
  if (Number.isNaN(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

async function load(): Promise<void> {
  const settings = await loadSettings();
  els.serverUrl.value = settings.serverUrl;
  els.token.value = settings.token;
  els.minSeconds.value = String(settings.minVisibleSeconds);
  els.scrollRatio.value = String(settings.minScrollRatio);
  els.snapshotMaxMb.value = String(settings.snapshotMaxMb);
  els.metadataOnly.checked = settings.captureMetadataOnly;
  els.blocklist.value = settings.blocklist.join("\n");
  if (!settings.serverUrl || !settings.token) {
    setStatus("尚未配置：填入服务器地址与采集凭据后点「保存并测试」", "warn");
  }
}

async function persist(): Promise<boolean> {
  const serverUrl = els.serverUrl.value.trim().replace(/\/+$/, "");
  if (!serverUrl) {
    setStatus("请填写服务器地址", "err");
    return false;
  }
  const check = validateServerUrl(serverUrl);
  if (!check.ok) {
    setStatus(check.error, "err");
    return false;
  }
  if (!els.token.value.trim()) {
    setStatus("请填写采集凭据（sb_cap_…）", "err");
    return false;
  }

  // MV3：host 权限必须在用户手势内请求（点击保存/测试即手势）
  const granted = await chrome.permissions.request({ origins: [check.origin] });
  if (!granted) {
    setStatus("未授予服务器访问权限，无法上传（可再次点击保存重试）", "err");
    return false;
  }

  await saveSettings({
    serverUrl,
    token: els.token.value.trim(),
    minVisibleSeconds: clamp(Number(els.minSeconds.value), 1, 3600, DEFAULT_SETTINGS.minVisibleSeconds),
    minScrollRatio: clamp(Number(els.scrollRatio.value), 0.05, 1, DEFAULT_SETTINGS.minScrollRatio),
    snapshotMaxMb: clamp(Number(els.snapshotMaxMb.value), 1, 100, DEFAULT_SETTINGS.snapshotMaxMb),
    captureMetadataOnly: els.metadataOnly.checked,
    blocklist: els.blocklist.value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean),
  });
  return true;
}

async function testConnection(
  base: string,
  token: string
): Promise<{ state: "ok" | "unauthorized" | "unreachable"; detail: string }> {
  try {
    const health = await fetch(`${base}/health`, { signal: AbortSignal.timeout(5000) });
    if (!health.ok) return { state: "unreachable", detail: `服务器 /health 返回 ${health.status}` };
  } catch (error) {
    return { state: "unreachable", detail: `无法连接服务器：${String(error)}` };
  }
  try {
    const ping = await fetch(`${base}/api/capture/ping`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(5000),
    });
    if (ping.ok) {
      const body = (await ping.json()) as { server_version?: string };
      return { state: "ok", detail: `已连接（服务器 ${body.server_version ?? "?"}），采集就绪` };
    }
    if (ping.status === 401 || ping.status === 403) {
      return { state: "unauthorized", detail: `凭据无效或权限不足（HTTP ${ping.status}）` };
    }
    return { state: "unreachable", detail: `连接测试返回 HTTP ${ping.status}` };
  } catch (error) {
    return {
      state: "unreachable",
      detail: `连接测试失败：${String(error)}（若权限被撤销请重新保存授权）`,
    };
  }
}

els.save.addEventListener("click", () => {
  void (async () => {
    if (await persist()) setStatus("已保存。新打开的页面按新设置采集。", "ok");
  })();
});

els.test.addEventListener("click", () => {
  void (async () => {
    if (!(await persist())) return;
    setStatus("测试中…", "warn");
    const settings = await loadSettings();
    const result = await testConnection(settings.serverUrl, settings.token);
    setStatus(result.detail, result.state === "ok" ? "ok" : "err");
  })();
});

els.diagRefresh.addEventListener("click", () => {
  void renderDiag();
});

void load().then(() => renderDiag());
