/**
 * 页面快照（F2 research R1）：单一接口封装 single-file-core（引擎可替换——若拒绝 AGPL 或效果不满，
 * 仅替换本模块）。调用方在 idle / 页面隐藏时调用（回放资源 + 去重选项会明显占用主线程）。
 * 返回结果对象：失败携带**可上报的原因**（进弹窗"最近快照"，便于定位）。
 */

type GetPageData = (
  options?: Record<string, unknown>,
  initOptions?: Record<string, unknown>
) => Promise<{ content?: string; title?: string; filename?: string }>;

export type SnapshotResult = { ok: true; blob: Blob } | { ok: false; reason: string };

let apiPromise: Promise<GetPageData | null> | null = null;

function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

function loadApi(): Promise<GetPageData | null> {
  if (!apiPromise) {
    apiPromise = import("single-file-core/single-file.js")
      .then((mod) =>
        typeof mod?.getPageData === "function" ? (mod.getPageData as GetPageData) : null
      )
      .catch(() => null);
  }
  return apiPromise;
}

export async function captureSnapshot(): Promise<SnapshotResult> {
  try {
    const getPageData = await withTimeout(loadApi(), 15_000, "single-file-core 加载超时");
    if (!getPageData) return { ok: false, reason: "single-file-core 未加载（import 失败）" };

    const result = await withTimeout(
      getPageData({
        // 体积治理 / 安全默认（R1；未知选项被引擎忽略，选项名以实现时核对为准）
        blockScripts: true,
        removeHiddenElements: true,
        removeUnusedStyles: true,
        removeUnusedFonts: true,
        compressHTML: true,
        groupDuplicateImages: true,
        removeFrames: true, // 仅主框架（内容脚本运行在主框架）
        removeVideoSources: true,
        removeAudioSources: true,
      }),
      30_000,
      "快照生成超时（30s）"
    );
    const html = result?.content ?? "";
    if (!html) return { ok: false, reason: "快照内容为空" };

    const stream = new Blob([html]).stream().pipeThrough(new CompressionStream("gzip"));
    const gz = await new Response(stream).arrayBuffer();
    console.debug(`[second-brain] snapshot 生成成功：raw=${html.length}B gz=${gz.byteLength}B`);
    return { ok: true, blob: new Blob([gz], { type: "application/gzip" }) };
  } catch (error) {
    console.warn("[second-brain] snapshot 生成失败：", error);
    return { ok: false, reason: String(error).slice(0, 160) };
  }
}
