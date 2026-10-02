/** offscreen document（F2）：执行上传 fetch（生命周期不受 SW 30s 终止限制）。 */

import { getSnapshotParts } from "../shared/db";
import type { UploadJob, UploadRequestMessage, UploadResultMessage } from "../shared/messages";

/** 离屏调试（offices 文档平时没有可见控制台）：关键节点写入 storage，弹窗可直接查看。 */
async function dbg(line: string): Promise<void> {
  try {
    const stamp = new Date().toISOString().slice(11, 19);
    await chrome.storage.local.set({ offscreenDebug: `${stamp} ${line}` });
  } catch {
    /* 忽略 */
  }
}

chrome.runtime.onMessage.addListener((message: unknown, _sender, sendResponse) => {
  const msg = message as { target?: string; type?: string };
  if (msg?.target !== "offscreen" || msg.type !== "upload") return undefined;
  void doUpload((message as UploadRequestMessage).job);
  sendResponse({ ok: true }); // 结果经 upload-result 另行回报
  return true;
});

async function doUpload(job: UploadJob): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120_000); // 大页慢链路上限
  try {
    await dbg(`收到任务 ${job.url.slice(0, 60)} 含快照=${job.hasSnapshot}`);
    const form = new FormData();
    form.append("url", job.url);
    if (job.title) form.append("title", job.title);
    form.append("text", job.text ?? ""); // 空串 = 仅元信息（正文提取失败时仍入库标题/URL）
    form.append("captured_at", job.capturedAt);
    form.append("capture_id", job.captureId);
    if (job.hasSnapshot) {
      const parts = await getSnapshotParts(job.captureId);
      await dbg(`快照分片读取：${parts.length} 片 / ${parts.reduce((n, p) => n + p.byteLength, 0)} 字节`);
      if (parts.length) {
        form.append("file", new Blob(parts, { type: "application/gzip" }), "snapshot.html.gz");
      }
    }

    console.debug(
      `[second-brain][offscreen] 开始上传：${job.url} | ${job.hasSnapshot ? "含快照" : "仅正文"}`
    );
    const response = await fetch(`${job.serverUrl.replace(/\/+$/, "")}/api/capture/pages`, {
      method: "POST",
      headers: { Authorization: `Bearer ${job.token}` },
      body: form,
      signal: controller.signal,
    });
    console.debug(`[second-brain][offscreen] 上传返回：HTTP ${response.status}`);
    await dbg(`上传返回 HTTP ${response.status}（快照=${job.hasSnapshot}）`);

    const result: UploadResultMessage = {
      target: "sw",
      type: "upload-result",
      captureId: job.captureId,
      ok: response.ok,
      status: response.status,
      withSnapshot: job.hasSnapshot,
    };
    if (!response.ok) {
      result.permanent = response.status === 400 || response.status === 404;
      const retryAfter = response.headers.get("retry-after");
      if (retryAfter) result.retryAfterSeconds = Number(retryAfter) || undefined;
      result.error = String(response.status);
      try {
        const body = (await response.json()) as { detail?: string; error?: { message?: string } };
        result.error = body?.error?.message ?? body?.detail ?? result.error;
      } catch {
        /* 非 JSON 响应 */
      }
    }
    await chrome.runtime.sendMessage(result);
  } catch (error) {
    console.warn("[second-brain][offscreen] 上传异常：", error);
    await dbg(`上传异常：${String(error).slice(0, 120)}`);
    try {
      await chrome.runtime.sendMessage({
        target: "sw",
        type: "upload-result",
        captureId: job.captureId,
        ok: false,
        error: String(error),
      } satisfies UploadResultMessage);
    } catch {
      /* SW 不可达：由 alarms 下轮补扫 */
    }
  } finally {
    clearTimeout(timer);
  }
}
