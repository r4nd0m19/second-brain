/**
 * 采集前跳过滤（纯逻辑，可单测）——2026-10-02 真机实测驱动：
 * ① 反爬验证/拦截页（DDoS-Guard / Cloudflare 等）不是内容：识别并跳过；
 * ② 同 URL 短时内容相同（页面自动刷新循环）不重复采集/计数。
 */

/** chrome.storage.local 键：URL → 最近一次采集的内容指纹 */
export const RECENT_CAPTURES_KEY = "recentCaptures";

/** 挑战页特征（标题或正文开头命中；且正文很短，避免误伤讨论该话题的正常文章） */
const CHALLENGE_PATTERNS: RegExp[] = [
  /ddos[- ]?guard/i,
  /checking your browser/i,
  /just a moment/i,
  /verify you are human/i,
  /enable javascript and cookies/i,
  /cf-browser-verification|cf_chl/i,
  /attention required/i,
];

/** 正文短于该长度（字符）才可能是拦截页（正常文章远超） */
const CHALLENGE_MAX_TEXT = 800;

export function looksLikeChallenge(title: string, text: string): boolean {
  if (text.length >= CHALLENGE_MAX_TEXT) return false;
  const sample = `${title}\n${text.slice(0, 500)}`;
  return CHALLENGE_PATTERNS.some((p) => p.test(sample));
}

/** 32 位 FNV-1a 内容指纹（标题 + 正文）。 */
export function contentHash(title: string, text: string): string {
  const input = `${title}\u0000${text}`;
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16);
}

export interface RecentCapture {
  hash: string;
  at: number;
}

/** 重复采集窗口（同 URL、同内容指纹）：10 分钟内的自动刷新不重复采集。 */
export const REPEAT_WINDOW_MS = 10 * 60 * 1000;

export function shouldSkipRepeat(
  entry: RecentCapture | undefined,
  hash: string,
  nowMs: number,
  windowMs = REPEAT_WINDOW_MS
): boolean {
  return Boolean(entry && entry.hash === hash && nowMs - entry.at < windowMs);
}

/** 维护指纹表：丢弃过期项（默认 7 天）、限制条目数（默认 500，保留最新）。 */
export function pruneRecent(
  map: Record<string, RecentCapture>,
  nowMs: number,
  maxAgeMs = 7 * 24 * 60 * 60 * 1000,
  maxEntries = 500
): Record<string, RecentCapture> {
  const fresh = Object.entries(map)
    .filter(([, value]) => nowMs - value.at < maxAgeMs)
    .sort((a, b) => b[1].at - a[1].at);
  return Object.fromEntries(fresh.slice(0, maxEntries));
}
