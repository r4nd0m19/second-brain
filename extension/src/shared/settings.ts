/** 扩展设置（chrome.storage.local；token 仅 SW/options/popup 可读，content script 只经消息拿行为）。 */

export interface Settings {
  serverUrl: string;
  token: string;
  paused: boolean;
  /** 黑名单域名（含子域语义；从源头不采集，含元信息） */
  blocklist: string[];
  minVisibleSeconds: number;
  minScrollRatio: number;
  /** 单页快照大小上限（MB，与服务端 capture_max_snapshot_mb 对齐） */
  snapshotMaxMb: number;
  /** 正文提取失败时是否保留"仅元信息"条目（spec Edge Case，可配置关闭） */
  captureMetadataOnly: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  serverUrl: "",
  token: "",
  paused: false,
  blocklist: [],
  minVisibleSeconds: 10,
  minScrollRatio: 0.5,
  snapshotMaxMb: 20,
  captureMetadataOnly: true,
};

const KEY = "settings";

export async function loadSettings(): Promise<Settings> {
  const stored = (await chrome.storage.local.get(KEY)) as { settings?: Partial<Settings> };
  return { ...DEFAULT_SETTINGS, ...(stored.settings ?? {}) };
}

export async function saveSettings(patch: Partial<Settings>): Promise<Settings> {
  const next = { ...(await loadSettings()), ...patch };
  await chrome.storage.local.set({ [KEY]: next });
  return next;
}

/** 服务端地址校验：仅 https 或本机回环 http（明文公网拒绝）。 */
export function validateServerUrl(raw: string): { ok: true; origin: string } | { ok: false; error: string } {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { ok: false, error: "地址格式不正确" };
  }
  const isLoopback = url.hostname === "localhost" || url.hostname === "127.0.0.1";
  if (url.protocol === "https:" || (url.protocol === "http:" && isLoopback)) {
    return { ok: true, origin: `${url.protocol}//${url.host}/*` };
  }
  return { ok: false, error: "仅支持 https:// 或本机 http://localhost / http://127.0.0.1" };
}
