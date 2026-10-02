/**
 * 内容脚本（F2 US1）：阅读度量（可见停留 / 滚动深度）→ 达标提取正文 → 消息 SW；
 * 快照在 idle / 页面隐藏时生成，分片（base64 ≤3MB/片）传 SW。
 * 源头不采：服务器未配置 / 暂停 / 黑名单 → 不做任何测量与提取。
 */

import { isBlocked } from "../shared/block";
import type {
  PageReadMessage,
  SnapshotChunkMessage,
  SnapshotCompleteMessage,
  SnapshotFailedMessage,
} from "../shared/messages";
import type { Settings } from "../shared/settings";
import { loadSettings } from "../shared/settings";
import { captureSnapshot } from "../shared/snapshot";
import { ReadingMeter, scrollRatio } from "../shared/trigger";
import { hostOf, isLoopbackHost, normalizeUrl } from "../shared/url";
import { extractArticle, waitForDomQuiet } from "./extract";
import { showCaptureDoneToast } from "./toast";

const TICK_MS = 1000;
const SNAPSHOT_CHUNK_BYTES = 3 * 1024 * 1024;

let meter: ReadingMeter | null = null;
let settings: Settings | null = null;
let currentUrl = "";
let triggered = false;
let snapshotStarted = false;

function resetForNavigation(): void {
  meter?.reset();
  triggered = false;
  snapshotStarted = false;
}

// SPA 路由重置（主路径：SW 的 webNavigation.onHistoryStateUpdated 转发；轮询兜底见 tick）
// 采集完成提示：SW 上传成功后回执（右下角 3s 小提示）
chrome.runtime.onMessage.addListener((message: unknown) => {
  const msg = message as { target?: string; type?: string; withSnapshot?: boolean };
  if (msg?.target !== "content") return undefined;
  if (msg.type === "spa-nav") {
    // 实测（2026-10-02 OI Wiki）：滚动高亮会持续 replaceState 改 #锚点——
    // 纯锚点变化不是换页，不能重置计时（否则"达标→重置→再达标"无限重复采集）
    try {
      const nowUrl = normalizeUrl(location.href);
      if (nowUrl !== currentUrl) {
        currentUrl = nowUrl;
        resetForNavigation();
      }
    } catch {
      /* 非 http(s)：忽略 */
    }
  } else if (msg.type === "capture-done") {
    showCaptureDoneToast(Boolean(msg.withSnapshot));
  }
  return undefined;
});

void init();

async function init(): Promise<void> {
  try {
    settings = await loadSettings();
    currentUrl = normalizeUrl(location.href);
  } catch {
    return; // 非 http(s) 或存储不可用
  }
  console.debug("[second-brain] 内容脚本就绪", currentUrl);
  if (!settings.serverUrl || !settings.token || settings.paused) return;
  if (isLoopbackHost(hostOf(currentUrl))) return; // 本机页面默认不采集（避免采到自身界面）
  if (isBlocked(hostOf(currentUrl), settings.blocklist)) return; // 源头不采（含元信息）

  meter = new ReadingMeter({
    minVisibleSeconds: settings.minVisibleSeconds,
    minScrollRatio: settings.minScrollRatio,
  });

  setInterval(tick, TICK_MS);
}

function tick(): void {
  if (!meter || !settings) return;
  try {
    const nowUrl = normalizeUrl(location.href);
    if (nowUrl !== currentUrl) {
      // 轮询兜底（SW 消息为主路径）
      currentUrl = nowUrl;
      resetForNavigation();
      if (isLoopbackHost(hostOf(currentUrl))) return;
      if (isBlocked(hostOf(currentUrl), settings.blocklist)) return;
    }
  } catch {
    return;
  }

  meter.tick(performance.now(), document.visibilityState === "visible");
  meter.setScrollRatio(
    scrollRatio(window.scrollY, window.innerHeight, document.documentElement.scrollHeight)
  );

  if (!triggered && meter.reached()) {
    triggered = true;
    void onTriggered();
  }
}

async function onTriggered(): Promise<void> {
  if (!settings) return;
  console.debug("[second-brain] 达到阅读阈值，开始采集");
  // SPA 防护（实测 Upwork 资料页：触发时页面仍在渲染，只提取到导航骨架）：
  // 先等 DOM 静默（静态页约 1.5s，最长 8s），再做提取
  await waitForDomQuiet(1500, 8000);
  console.debug("[second-brain] DOM 已静默，提取正文…");
  const article = await extractArticle();
  console.debug(`[second-brain] 提取完成：${article.text.length} 字 | 标题「${article.title}」`);
  if (!article.text && !settings.captureMetadataOnly) return; // 配置关闭：提取失败不采

  const captureId = crypto.randomUUID();
  const message: PageReadMessage = {
    target: "sw",
    type: "page-read",
    url: currentUrl,
    title: article.title || document.title,
    text: article.text,
    capturedAt: new Date().toISOString(),
    captureId,
  };

  let accepted = false;
  try {
    const response = (await chrome.runtime.sendMessage(message)) as { ok?: boolean } | undefined;
    accepted = response?.ok === true;
  } catch {
    accepted = false;
  }
  console.debug(
    `[second-brain] 入库请求：${accepted ? "已受理" : "被拒（未配置/暂停/扩展后台不可达）"}`
  );
  if (!accepted) return; // 服务未配置 / 暂停 / SW 不可达：不产生快照传输

  scheduleSnapshot(captureId);
}

function scheduleSnapshot(id: string): void {
  const run = (): void => {
    if (snapshotStarted) return;
    snapshotStarted = true;
    void sendSnapshot(id);
  };
  if (document.visibilityState === "hidden") {
    run();
    return;
  }
  // 优先空闲时机（single-file 回放资源 + 去重选项明显占用主线程；R1）
  const idle = (window as unknown as { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => void })
    .requestIdleCallback;
  if (idle) idle(run, { timeout: 8000 });
  else setTimeout(run, 3000);

  document.addEventListener(
    "visibilitychange",
    () => {
      if (document.visibilityState === "hidden") run();
    },
    { once: true }
  );
  window.addEventListener("pagehide", run, { once: true });
}

async function sendSnapshot(id: string): Promise<void> {
  if (!settings) return;
  console.debug("[second-brain] snapshot 开始：", location.href);
  const result = await captureSnapshot();
  if (!result.ok) {
    await send({
      target: "sw",
      type: "snapshot-failed",
      captureId: id,
      reason: result.reason,
    } satisfies SnapshotFailedMessage);
    return;
  }
  const blob = result.blob;
  if (blob.size > settings.snapshotMaxMb * 1024 * 1024) {
    await send({
      target: "sw",
      type: "snapshot-failed",
      captureId: id,
      reason: `快照超限（>${settings.snapshotMaxMb}MB），仅正文入库`,
    } satisfies SnapshotFailedMessage);
    return;
  }

  const bytes = new Uint8Array(await blob.arrayBuffer());
  const total = Math.max(1, Math.ceil(bytes.length / SNAPSHOT_CHUNK_BYTES));
  for (let index = 0; index < total; index += 1) {
    const slice = bytes.subarray(index * SNAPSHOT_CHUNK_BYTES, (index + 1) * SNAPSHOT_CHUNK_BYTES);
    const delivered = await send({
      target: "sw",
      type: "snapshot-chunk",
      captureId: id,
      index,
      total,
      data: bytesToBase64(slice),
    } satisfies SnapshotChunkMessage);
    if (!delivered) {
      console.warn(`[second-brain] snapshot 分片 ${index}/${total} 发送失败`);
      return; // SW 不可达：放弃快照（正文已入库）
    }
  }
  // 全部落盘：通知 SW 快照已就绪（上传队列据此放行 + 完整性校验）
  await send({
    target: "sw",
    type: "snapshot-complete",
    captureId: id,
    total,
  } satisfies SnapshotCompleteMessage);
  console.debug(`[second-brain] 快照分片已全部发送（${total} 片），等待上传完成提示`);
}

async function send(message: unknown): Promise<boolean> {
  try {
    await chrome.runtime.sendMessage(message);
    return true;
  } catch {
    return false;
  }
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const step = 0x8000; // 防 apply 参数上限
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode(...bytes.subarray(i, i + step));
  }
  return btoa(binary);
}
