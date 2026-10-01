"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, Doc, formatSize } from "@/lib/api";

const STATUS_LABEL: Record<Doc["status"], string> = {
  processing: "处理中",
  indexed: "已入库",
  unparseable: "无法解析",
};

export default function HomePage() {
  const [username, setUsername] = useState<string | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocs());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        window.location.href = "/login/";
      }
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setUsername((await api.me()).username);
      } catch {
        window.location.href = "/login/";
        return;
      }
      await refresh();
    })();
  }, [refresh]);

  // 有文档处理中时轮询状态（解析入库是后台异步的）
  const anyProcessing = docs.some((d) => d.status === "processing");
  useEffect(() => {
    if (!anyProcessing) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [anyProcessing, refresh]);

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setNotice(null);
    try {
      const result = await api.upload(file);
      if ("duplicate" in result) {
        setNotice(`已存在相同文件（${file.name}），未重复入库`);
      } else {
        setNotice(`已上传：${file.name}，正在后台解析入库…`);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "上传失败");
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function onDelete(doc: Doc) {
    if (!confirm(`确定删除「${doc.name}」？\n包含原文件，删除后不可恢复。`)) return;
    try {
      await api.deleteDoc(doc.id);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  async function onReprocess(doc: Doc) {
    try {
      await api.reprocess(doc.id);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "重试失败");
    }
  }

  async function onLogout() {
    await api.logout().catch(() => undefined);
    window.location.href = "/login/";
  }

  return (
    <main className="container">
      <div className="header">
        <h1>second-brain</h1>
        <div>
          <span className="muted" style={{ marginRight: 12 }}>
            {username ?? ""}
          </span>
          <button className="btn" onClick={onLogout}>
            退出
          </button>
        </div>
      </div>

      <div className="card">
        <p style={{ marginTop: 0 }}>
          上传资料（PDF / EPUB / TXT / Markdown / DOCX 等）—— 解析入库后即可检索问答。
        </p>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.epub,.txt,.md,.markdown,.docx,.html"
          onChange={onUpload}
          style={{ display: "none" }}
          id="file-input"
        />
        <label htmlFor="file-input" className="btn btn-primary" style={{ display: "inline-block" }}>
          选择文件上传
        </label>
        {notice && <p className="notice">{notice}</p>}
        {error && <p className="error">{error}</p>}
      </div>

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>资料</th>
              <th>大小</th>
              <th>状态</th>
              <th style={{ width: 180 }}></th>
            </tr>
          </thead>
          <tbody>
            {docs.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  还没有资料 —— 上传第一本书吧
                </td>
              </tr>
            )}
            {docs.map((doc) => (
              <tr key={doc.id}>
                <td>
                  {doc.name}
                  {doc.status === "unparseable" && doc.status_reason && (
                    <div className="muted">{doc.status_reason}</div>
                  )}
                </td>
                <td className="muted">{formatSize(doc.size)}</td>
                <td>
                  <span className={`badge badge-${doc.status}`}>{STATUS_LABEL[doc.status]}</span>
                </td>
                <td>
                  <div className="actions">
                    {doc.status !== "indexed" && (
                      <button className="btn" onClick={() => onReprocess(doc)}>
                        重试
                      </button>
                    )}
                    <a className="btn" href={api.originalUrl(doc.id)} download={doc.name}>
                      下载
                    </a>
                    <button className="btn btn-danger" onClick={() => onDelete(doc)}>
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
