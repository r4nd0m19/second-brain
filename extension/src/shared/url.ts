/** URL 规范化（与服务端 capture/router.normalize_url 一致）：去 fragment、保留 query、host 小写。 */

export function normalizeUrl(raw: string): string {
  const url = new URL(raw);
  url.hash = "";
  // URL 解析器已折叠默认端口并小写 hostname；toString 即规范化结果
  return url.toString();
}

export function hostOf(raw: string): string {
  return new URL(raw).hostname.toLowerCase();
}

/** 本机地址（localhost / 回环）：默认不采集——避免把 second-brain 自身界面等本地页当成"浏览的网页"。 */
export function isLoopbackHost(host: string): boolean {
  const normalized = host.toLowerCase();
  return (
    normalized === "localhost" ||
    normalized.endsWith(".localhost") ||
    normalized === "127.0.0.1" ||
    normalized === "::1" ||
    normalized === "[::1]"
  );
}
