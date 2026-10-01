// 同源 API 客户端：会话 Cookie 自动携带（credentials: include）

export type DocStatus = "processing" | "indexed" | "unparseable";

export type Doc = {
  id: string;
  name: string;
  format: string;
  size: number;
  status: DocStatus;
  status_reason: string | null;
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

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ id: string; status: string } | { duplicate: true; existing_id: string }>(
      "/api/documents",
      { method: "POST", body: form },
    );
  },

  deleteDoc: (id: string) =>
    request<void>(`/api/documents/${id}`, { method: "DELETE" }),

  reprocess: (id: string) =>
    request<unknown>(`/api/documents/${id}/reprocess`, { method: "POST" }),

  originalUrl: (id: string) => `/api/documents/${id}/original`,
};

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
