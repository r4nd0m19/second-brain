// 同源 API 客户端：会话 Cookie 自动携带（credentials: include）

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
};

export type Citation = {
  document_id: string;
  chunk_id: string;
  document_name: string;
  heading_path: string | null;
  page: number | null;
  quote: string;
};

export type UsageInfo = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  prompt_cache_hit_tokens?: number;
  cost_cny?: number | null;
};

export type Conversation = {
  id: string;
  title: string;
  created_at: string | null;
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
      body?.error?.message ?? body?.detail ?? `请求失败（${res.status}）`;
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

  listDocs: () => request<Doc[]>("/api/documents"),

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
            reject(new ApiError(xhr.status, "上传响应解析失败"));
          }
        } else if (xhr.status === 401) {
          reject(new ApiError(401, "未登录"));
        } else {
          let message = `上传失败（${xhr.status}）`;
          try {
            const body = JSON.parse(xhr.responseText) as { detail?: string };
            if (body.detail) message = body.detail;
          } catch {
            /* 保留默认文案 */
          }
          reject(new ApiError(xhr.status, message));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "上传网络错误"));
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
