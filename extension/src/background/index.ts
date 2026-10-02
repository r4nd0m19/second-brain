/**
 * Service Worker（F2）：采集队列（先落盘再发 → capture_id 幂等重试）、alarms 退避、
 * badge 三态、SPA 导航转发、offscreen 上传调度。
 * MV3 硬约束：监听器全部顶层注册；不依赖全局内存态（storage.local = 唯一事实源）。
 */

import {
  countSnapshotParts,
  deleteSnapshotParts,
  getSnapshotParts,
  hasSnapshotParts,
  putSnapshotPart,
} from "../shared/db";
import type {
  CaptureDoneMessage,
  PageReadMessage,
  QueueEntry,
  SnapshotChunkMessage,
  SnapshotCompleteMessage,
  SnapshotFailedMessage,
  UploadResultMessage,
} from "../shared/messages";
import { loadSettings } from "../shared/settings";

const QUEUE_KEY = "queue";
const SCAN_ALARM = "sb-scan";
const MAX_ATTEMPTS = 5;
const BACKOFF_MINUTES = [1, 2, 4, 8, 16];
const SNAPSHOT_WAIT_MS = 30_000; // 等快照分片落盘的最长时间（超时降级仅正文）

// ── 队列读写 ──

async function getQueue(): Promise<QueueEntry[]> {
  const stored = (await chrome.storage.local.get(QUEUE_KEY)) as { queue?: QueueEntry[] };
  return stored.queue ?? [];
}

async function setQueue(queue: QueueEntry[]): Promise<void> {
  await chrome.storage.local.set({ [QUEUE_KEY]: queue });
}

// ── 队列"读-改-写"串行化（2026-10-02 根因修复）──
// 多个消息处理器并发做 getQueue → 改一条 → setQueue 会互相覆盖（丢失更新），
// 表现为条目凭空消失 / 卡死 / 重复上传。所有写入统一走此互斥通道。
let queueLock: Promise<void> = Promise.resolve();

async function mutateQueue(mutator: (queue: QueueEntry[]) => void): Promise<QueueEntry[]> {
  const task = queueLock.then(async () => {
    const queue = await getQueue();
    mutator(queue);
    await setQueue(queue);
    return queue;
  });
  queueLock = task.then(
    () => undefined,
    () => undefined
  );
  return task;
}

function base64ToBytes(data: string): Uint8Array {
  const binary = atob(data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

// ── 消息处理（顶层注册）──

interface SwMessage {
  target?: string;
  type?: string;
}

chrome.runtime.onMessage.addListener((message: unknown, sender, sendResponse) => {
  const msg = message as SwMessage;
  if (msg?.target !== "sw") return undefined;
  void handleMessage(msg, sender.tab?.id ?? null).then(sendResponse, (error) =>
    sendResponse({ ok: false, error: String(error) })
  );
  return true; // 异步响应
});

async function handleMessage(
  msg: SwMessage,
  tabId: number | null
): Promise<{ ok: boolean; reason?: string }> {
  switch (msg.type) {
    case "page-read":
      return handlePageRead(msg as unknown as PageReadMessage, tabId);
    case "snapshot-chunk": {
      const chunk = msg as unknown as SnapshotChunkMessage;
      await putSnapshotPart(
        chunk.captureId,
        chunk.index,
        base64ToBytes(chunk.data).buffer as ArrayBuffer
      );
      // 记录声明的总分片数（完整性校验 / 超时判定用）
      await mutateQueue((queue) => {
        const entry = queue.find((e) => e.captureId === chunk.captureId);
        if (entry && entry.snapshotTotal == null) entry.snapshotTotal = chunk.total;
      });
      return { ok: true };
    }
    case "snapshot-complete": {
      const done = msg as unknown as SnapshotCompleteMessage;
      const parts = await countSnapshotParts(done.captureId);
      await mutateQueue((queue) => {
        const entry = queue.find((e) => e.captureId === done.captureId);
        if (!entry) return;
        entry.snapshotPending = false;
        entry.snapshotTotal = parts >= done.total ? done.total : null;
      });
      if (parts < done.total) {
        await deleteSnapshotParts(done.captureId); // 传输不完整：降级仅正文
        await chrome.storage.local.set({
          lastSnapshotError: `快照传输不完整（${parts}/${done.total}），已降级为仅正文`,
        });
      }
      void processQueue();
      return { ok: true };
    }
    case "snapshot-failed": {
      const failed = msg as unknown as SnapshotFailedMessage;
      await chrome.storage.local.set({ lastSnapshotError: failed.reason });
      await deleteSnapshotParts(failed.captureId);
      await mutateQueue((queue) => {
        const entry = queue.find((e) => e.captureId === failed.captureId);
        if (entry) {
          entry.snapshotPending = false;
          entry.snapshotTotal = null;
        }
      });
      void processQueue(); // 不再等快照，立即走正文上传
      return { ok: true };
    }
    case "upload-result": {
      const result = msg as unknown as UploadResultMessage;
      console.debug(
        "[second-brain][SW] 收到上传结果：",
        result.ok ? "成功" : "失败",
        result.status ?? "",
        result.error ?? ""
      );
      await handleUploadResult(result);
      return { ok: true };
    }
    default:
      return { ok: false, reason: "unknown" };
  }
}

async function handlePageRead(
  msg: PageReadMessage,
  tabId: number | null
): Promise<{ ok: boolean; reason?: string }> {
  const settings = await loadSettings();
  if (!settings.serverUrl || !settings.token) return { ok: false, reason: "unconfigured" };
  if (settings.paused) return { ok: false, reason: "paused" };

  const entry: QueueEntry = {
    captureId: msg.captureId,
    url: msg.url,
    title: msg.title,
    text: msg.text,
    capturedAt: msg.capturedAt,
    attempts: 0,
    nextRetryAt: 0,
    status: "pending",
    snapshotDropped: false,
    queuedAt: Date.now(),
    tabId,
    snapshotPending: true,
    snapshotTotal: null,
  };
  await mutateQueue((queue) => {
    queue.push(entry);
  }); // 先落盘：SW 随后被杀也不丢
  console.debug("[second-brain][SW] 已入队，等待快照落定后上传：", msg.url);
  await refreshBadge();
  void processQueue();
  return { ok: true };
}

// ── 上传调度 ──

let processing = false;

async function processQueue(): Promise<void> {
  if (processing) return;
  processing = true;
  try {
    const settings = await loadSettings();
    if (!settings.serverUrl || !settings.token) return;
    const queue = await getQueue();
    const now = Date.now();
    const due = queue.filter(
      (e) =>
        e.status === "pending" &&
        e.nextRetryAt <= now &&
        // 等快照分片落盘再上传（防"正文先传、快照迟到变孤儿"竞态）；
        // 30s 超时兜底降级仅正文（旧版本遗留条目无 snapshotPending 字段 → 直接放行）
        (!e.snapshotPending || now - (e.queuedAt || 0) > SNAPSHOT_WAIT_MS)
    );
    console.debug(`[second-brain][SW] 队列扫描：待传 ${queue.length}，本轮派发 ${due.length}`);
    if (due.length === 0) return;
    for (const entry of due) {
      // 等超时但分片不完整 → 丢弃残片，降级仅正文
      if (entry.snapshotPending && entry.snapshotTotal != null) {
        const total = entry.snapshotTotal;
        const parts = await countSnapshotParts(entry.captureId);
        if (parts < total) {
          await deleteSnapshotParts(entry.captureId);
          await mutateQueue((queue) => {
            const e = queue.find((x) => x.captureId === entry.captureId);
            if (e) e.snapshotTotal = null;
          });
          await chrome.storage.local.set({
            lastSnapshotError: `快照传输超时（${parts}/${total}），已降级为仅正文`,
          });
          entry.snapshotTotal = null;
        }
      }
      // 后台直传（2026-10-02 架构简化）：不再经"离屏上传器"跨上下文握手——
      // 该握手在实际运行中不稳定（回执丢失 → 无限重试）。同进程内 fetch，结果即时处理。
      await dispatchUpload(entry, settings);
    }
  } finally {
    processing = false;
  }
}

async function handleUploadResult(msg: UploadResultMessage): Promise<void> {
  let successEntry: QueueEntry | null = null;
  let errorMessage: string | null = null;
  let warnText = "";

  await mutateQueue((queue) => {
    const index = queue.findIndex((e) => e.captureId === msg.captureId);
    if (index < 0) return;
    const entry = queue[index];

    if (msg.ok) {
      queue.splice(index, 1);
      successEntry = entry;
      return;
    }
    if (msg.status === 401 || msg.status === 403) {
      entry.status = "auth-error"; // 停发直到设置更新（badge 变红）
      errorMessage = "采集凭据无效或已吊销（请在设置中更新）";
      warnText = `上传被拒（凭据无效/吊销）：${msg.status}`;
    } else if (msg.status === 413 && !entry.snapshotDropped) {
      entry.snapshotDropped = true;
      entry.nextRetryAt = 0;
      errorMessage = "快照超出服务器上限，已降级为仅正文重试";
      warnText = `快照超限（413），降级仅正文重试：${entry.url}`;
    } else if (msg.permanent) {
      entry.status = "dead";
      errorMessage = `服务器拒绝该条目（${msg.error ?? msg.status}），已停止重试`;
      warnText = `永久失败：${msg.status} ${msg.error} ${entry.url}`;
    } else {
      entry.attempts += 1;
      if (entry.attempts >= MAX_ATTEMPTS) {
        entry.status = "dead";
        errorMessage = `重试 ${MAX_ATTEMPTS} 次仍失败：${msg.error ?? msg.status}`;
        warnText = `重试耗尽，放弃：${msg.error ?? msg.status} ${entry.url}`;
      } else {
        const minutes = msg.retryAfterSeconds
          ? msg.retryAfterSeconds / 60
          : BACKOFF_MINUTES[Math.min(entry.attempts - 1, BACKOFF_MINUTES.length - 1)];
        entry.nextRetryAt = Date.now() + minutes * 60_000;
        errorMessage = `上传失败（第 ${entry.attempts} 次）：${msg.error ?? msg.status}`;
        warnText = `上传失败（第 ${entry.attempts} 次，${Math.round(minutes)} 分钟后重试）：${msg.error ?? msg.status} ${entry.url}`;
      }
    }
  });

  if (successEntry) {
    const entry = successEntry as QueueEntry;
    await deleteSnapshotParts(entry.captureId);
    await bumpTodayCount();
    console.debug("[second-brain][SW] 上传成功：", entry.url, `快照=${msg.withSnapshot ? "有" : "无"}`);
    await chrome.storage.local.set({ lastError: null, lastSuccessAt: new Date().toISOString() });
    // 当前页面采集完成的反馈：标签页徽标 ✓ + 页面右下角提示
    if (entry.tabId != null) {
      void flashTabBadge(entry.tabId);
      chrome.tabs
        .sendMessage(entry.tabId, {
          target: "content",
          type: "capture-done",
          withSnapshot: msg.withSnapshot ?? false,
        } satisfies CaptureDoneMessage)
        .catch(() => {
          /* 标签页已关闭/已跳转 */
        });
    }
  } else if (errorMessage) {
    console.warn("[second-brain][SW]", warnText);
    await chrome.storage.local.set({ lastError: errorMessage });
  }

  await refreshBadge();
  if (msg.status === 413) void processQueue(); // 降级后立即重试
}

// ── 完成反馈：该标签页徽标短暂 ✓（4s 后还原为全局状态）──

async function flashTabBadge(tabId: number): Promise<void> {
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#1e7d4f" });
    await chrome.action.setBadgeText({ tabId, text: "✓" });
    setTimeout(() => {
      void chrome.action.setBadgeText({ tabId, text: "" }).catch(() => {});
    }, 4_000);
  } catch {
    /* 标签页已关闭 */
  }
}

// ── 今日计数与 badge ──

async function bumpTodayCount(): Promise<void> {
  const today = new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD（本地时区）
  const stored = (await chrome.storage.local.get("stats")) as {
    stats?: { date: string; count: number };
  };
  const stats =
    stored.stats && stored.stats.date === today ? stored.stats : { date: today, count: 0 };
  stats.count += 1;
  await chrome.storage.local.set({ stats });
}

async function refreshBadge(): Promise<void> {
  const queue = await getQueue();
  const pending = queue.filter((e) => e.status === "pending").length;
  const authError = queue.some((e) => e.status === "auth-error");
  if (authError) {
    await chrome.action.setBadgeBackgroundColor({ color: "#c0392b" });
    await chrome.action.setBadgeText({ text: "!" });
  } else if (pending > 0) {
    await chrome.action.setBadgeBackgroundColor({ color: "#d68910" });
    await chrome.action.setBadgeText({ text: String(pending) });
  } else {
    await chrome.action.setBadgeText({ text: "" });
  }
}

// ── 上传（SW 内直传；离屏文档已弃用，2026-10-02）──

async function dispatchUpload(entry: QueueEntry, settings: { serverUrl: string; token: string }): Promise<void> {
  try {
    const form = new FormData();
    form.append("url", entry.url);
    if (entry.title) form.append("title", entry.title);
    form.append("text", entry.text ?? "");
    form.append("captured_at", entry.capturedAt);
    form.append("capture_id", entry.captureId);
    let withSnapshot = false;
    if (!entry.snapshotDropped) {
      const parts = await getSnapshotParts(entry.captureId);
      if (parts.length) {
        form.append("file", new Blob(parts, { type: "application/gzip" }), "snapshot.html.gz");
        withSnapshot = true;
      }
    }

    const controller = new AbortController();
    // 后台进程硬约束：fetch 超过 30s 会被终止 → 25s 主动超时，快速失败后重试
    const timer = setTimeout(() => controller.abort(), 25_000);
    let response: Response;
    try {
      response = await fetch(`${settings.serverUrl.replace(/\/+$/, "")}/api/capture/pages`, {
        method: "POST",
        headers: { Authorization: `Bearer ${settings.token}` },
        body: form,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }

    console.debug(
      `[second-brain][SW] 上传返回 HTTP ${response.status}（快照=${withSnapshot}）：`,
      entry.url
    );
    let error: string | undefined;
    let retryAfterSeconds: number | undefined;
    let permanent = false;
    if (!response.ok) {
      permanent = response.status === 400 || response.status === 404;
      error = String(response.status);
      const retryAfter = response.headers.get("retry-after");
      if (retryAfter) retryAfterSeconds = Number(retryAfter) || undefined;
      try {
        const body = (await response.json()) as { detail?: string };
        error = body?.detail ?? error;
      } catch {
        /* 非 JSON 响应 */
      }
    }
    await handleUploadResult({
      target: "sw",
      type: "upload-result",
      captureId: entry.captureId,
      ok: response.ok,
      status: response.status,
      error,
      retryAfterSeconds,
      permanent,
      withSnapshot,
    });
  } catch (err) {
    console.warn("[second-brain][SW] 上传异常：", err, entry.url);
    await handleUploadResult({
      target: "sw",
      type: "upload-result",
      captureId: entry.captureId,
      ok: false,
      error: String(err),
    });
  }
}

// ── alarms / 生命周期 / SPA 导航（全部顶层注册）──

async function ensureAlarm(): Promise<void> {
  if (!(await chrome.alarms.get(SCAN_ALARM))) {
    await chrome.alarms.create(SCAN_ALARM, { periodInMinutes: 1 });
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === SCAN_ALARM) void processQueue();
});

chrome.runtime.onInstalled.addListener((details) => {
  void ensureAlarm();
  // 仅首次安装时打开设置页引导配置（开发重载也会触发 onInstalled，不打扰）
  if (details.reason === "install") void chrome.runtime.openOptionsPage();
});

chrome.runtime.onStartup.addListener(() => {
  void ensureAlarm();
});

void ensureAlarm(); // SW 每次启动检查/重建（扩展更新会清 alarm）

chrome.webNavigation.onHistoryStateUpdated.addListener((details) => {
  if (details.frameId !== 0) return; // 只处理主框架
  chrome.tabs.sendMessage(details.tabId, { target: "content", type: "spa-nav" }).catch(() => {});
});

void refreshBadge();
