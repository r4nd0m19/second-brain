// 同源 API 客户端：会话 Cookie 自动携带（credentials: include）

import { translate } from "@/lib/i18n";

export type DocStatus = "processing" | "indexed" | "unparseable";

export type Doc = {
  id: string;
  name: string;
  format: string;
  size: number;
  status: DocStatus;
  status_reason: string | null;
  progress?: { done: number; total: number; unit: string } | null;
  parse_hint: string | null;
  created_at: string | null;
  // F2 浏览器来源附加字段（source=browser 时存在）
  source_url?: string;
  site_name?: string;
  first_captured_at?: string;
  last_captured_at?: string;
  visit_count?: number;
  snapshot?: { state: "kept" | "skipped_oversize" | "skipped_error" | "none"; bytes: number | null };
  // 搜索命中信息（?q= 时返回）：name/url 命中无片段；content 命中带正文片段
  match?: { type: "name" | "url" | "content"; snippet: string | null };
};

export type DocListResult = {
  items: Doc[];
  total: number;
  page: number;
  page_size: number;
};

export type Citation = {
  document_id: string;
  chunk_id: string | null;
  document_name: string;
  heading_path: string | null;
  page: number | null;
  quote: string | null;
  /** 浏览器来源（F2）：原网页链接与浏览时间 */
  source_url?: string | null;
  last_captured_at?: string | null;
  /** 对话回写来源（2026-10-02）：回到原对话 + 旧引用标记的继承映射 */
  conversation_id?: string | null;
  message_id?: string | null;
  inherited_citations?: Citation[] | null;
  /** 联网来源（F4，2026-10-02）：外链直开新标签，无本地文档 */
  web?: boolean;
};

export type CaptureToken = {
  id: string;
  name: string;
  prefix: string;
  scope: string;
  created_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type StorageStats = {
  database_bytes: number;
  storage_bytes: number;
  snapshot_bytes: number;
  snapshot_files: number;
  storage_files: number;
  documents: Record<string, number>;
};

export type UsageInfo = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  prompt_cache_hit_tokens?: number;
  cost_cny?: number | null;
  /** 全成本明细（T079）：llm=模型调用（含规划/扩检）、web=联网按次、retrieval=embedding+重排 */
  cost_breakdown?: { llm?: number; web?: number; retrieval?: number } | null;
};

export type Conversation = {
  id: string;
  title: string;
  created_at: string | null;
};

export type ConversationSearchHit = {
  id: string;
  title: string;
  hit_count: number;
  last_hit_at: string | null;
  /** 打开会话后的定位目标（该会话最早的命中消息） */
  hit: {
    message_id: string;
    role: "user" | "assistant";
    snippet: string;
    created_at: string | null;
  };
};

export type StoredMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  source_type: string | null;
  citations: Citation[] | null;
  related_hints: Citation[] | null;
  usage: UsageInfo | null;
  created_at: string | null;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "include", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message: string =
      body?.error?.message ??
      body?.detail ??
      translate("common.requestFailed", { status: res.status });
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  me: () => request<{ username: string }>("/api/me"),

  login: (username: string, password: string) =>
    request<void>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),

  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  listDocs: (
    source: "upload" | "browser" = "upload",
    opts: { q?: string; sort?: string; page?: number } = {},
  ) => {
    const params = new URLSearchParams({ source });
    if (opts.q) params.set("q", opts.q);
    if (opts.sort) params.set("sort", opts.sort);
    if (opts.page && opts.page > 1) params.set("page", String(opts.page));
    return request<DocListResult>(`/api/documents?${params.toString()}`);
  },

  cleanupBrowserDocs: (range: { before?: string; after?: string }) => {
    const query = new URLSearchParams({ source: "browser" });
    if (range.before) query.set("before", range.before);
    if (range.after) query.set("after", range.after);
    return request<{ deleted: number }>(`/api/documents?${query.toString()}`, {
      method: "DELETE",
    });
  },

  storageStats: () => request<StorageStats>("/api/stats/storage"),

  listCaptureTokens: () => request<CaptureToken[]>("/api/capture/tokens"),

  createCaptureToken: (name: string, scope: "capture" | "read" | "write" = "capture") =>
    request<{ id: string; name: string; prefix: string; token: string }>("/api/capture/tokens", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, scope }),
    }),

  revokeCaptureToken: (id: string) =>
    request<void>(`/api/capture/tokens/${id}`, { method: "DELETE" }),

  /** 彻底删除（仅限已吊销的凭据；未吊销会 409） */
  purgeCaptureToken: (id: string) =>
    request<void>(`/api/capture/tokens/${id}?purge=1`, { method: "DELETE" }),

  getDoc: (id: string) => request<Doc>(`/api/documents/${id}`),

  upload: (
    file: File,
    onProgress?: (pct: number | null) => void,
  ): Promise<{ id: string; status: string } | { duplicate: true; existing_id: string }> =>
    // fetch 不暴露上传进度 → 专用 XHR
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/documents");
      xhr.withCredentials = true;
      xhr.upload.onprogress = (event) => {
        onProgress?.(
          event.lengthComputable ? Math.round((event.loaded / event.total) * 100) : null,
        );
      };
      xhr.onload = () => {
        if (xhr.status === 200 || xhr.status === 201) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            reject(new ApiError(xhr.status, translate("common.uploadParseFailed")));
          }
        } else if (xhr.status === 401) {
          reject(new ApiError(401, translate("common.unauthorized")));
        } else {
          let message = translate("common.uploadFailed", { status: xhr.status });
          try {
            const body = JSON.parse(xhr.responseText) as { detail?: string };
            if (body.detail) message = body.detail;
          } catch {
            /* 保留默认文案 */
          }
          reject(new ApiError(xhr.status, message));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, translate("common.uploadNetworkError")));
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    }),

  deleteDoc: (id: string) =>
    request<void>(`/api/documents/${id}`, { method: "DELETE" }),

  reprocess: (id: string, mode: "auto" | "deep" = "auto") =>
    request<unknown>(`/api/documents/${id}/reprocess?mode=${mode}`, { method: "POST" }),

  originalUrl: (id: string) => `/api/documents/${id}/original`,

  listConversations: () => request<Conversation[]>("/api/conversations"),

  /** 对话全文搜索（消息正文；会话级结果） */
  searchConversations: (q: string, limit = 20) =>
    request<{ items: ConversationSearchHit[]; total: number }>(
      `/api/conversations/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

  conversationMessages: (id: string) =>
    request<StoredMessage[]>(`/api/conversations/${id}/messages`),

  deleteConversation: (id: string) =>
    request<void>(`/api/conversations/${id}`, { method: "DELETE" }),
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
