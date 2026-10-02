"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, CaptureToken, Doc, formatSize, StorageStats } from "@/lib/api";

const STATUS_LABEL: Record<Doc["status"], string> = {
  processing: "处理中",
  indexed: "已入库",
  unparseable: "无法解析",
};

type Source = "upload" | "browser";

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div className="progress" title={`${done}/${total}`}>
      <div className="progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

function IndeterminateBar() {
  return (
    <div className="progress">
      <div className="progress-fill progress-indeterminate" />
    </div>
  );
}

function fmtTime(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function HomePage() {
  const [username, setUsername] = useState<string | null>(null);
  const [source, setSource] = useState<Source>("upload");
  const [docs, setDocs] = useState<Doc[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<{ name: string; pct: number | null } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const sourceRef = useRef<Source>("upload");

  // 采集凭据（F2）
  const [tokens, setTokens] = useState<CaptureToken[]>([]);
  const [tokenName, setTokenName] = useState("");
  const [newToken, setNewToken] = useState<string | null>(null);

  // 按时间清理（F2 FR-007）
  const [cleanupAfter, setCleanupAfter] = useState("");
  const [cleanupBefore, setCleanupBefore] = useState("");

  // 存储占用（试用需求）
  const [storage, setStorage] = useState<StorageStats | null>(null);

  const refresh = useCallback(async (which: Source) => {
    try {
      const list = await api.listDocs(which);
      if (sourceRef.current === which) setDocs(list); // 丢弃过期响应
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        window.location.href = "/login/";
      }
    }
  }, []);

  const loadTokens = useCallback(async () => {
    try {
      setTokens(await api.listCaptureTokens());
    } catch {
      /* 未登录等场景由 me() 流程兜底 */
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
      await Promise.all([
        refresh("upload"),
        loadTokens(),
        api
          .storageStats()
          .then(setStorage)
          .catch(() => undefined),
      ]);
    })();
  }, [refresh, loadTokens]);

  useEffect(() => {
    sourceRef.current = source;
    void refresh(source);
  }, [source, refresh]);

  // 有文档处理中时轮询状态（解析入库是后台异步的）
  const anyProcessing = docs.some((d) => d.status === "processing");
  useEffect(() => {
    if (!anyProcessing) return;
    const id = setInterval(() => void refresh(sourceRef.current), 3000);
    return () => clearInterval(id);
  }, [anyProcessing, refresh]);

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setNotice(null);
    setUploading({ name: file.name, pct: 0 });
    try {
      const result = await api.upload(file, (pct) =>
        setUploading((u) => (u ? { ...u, pct } : u)),
      );
      if ("duplicate" in result) {
        setNotice(`已存在相同文件（${file.name}），未重复入库`);
      } else {
        setNotice(`已上传：${file.name}，正在后台解析入库…`);
      }
      await refresh("upload");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "上传失败");
    } finally {
      setUploading(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function onDelete(doc: Doc) {
    const extra = source === "browser" ? "\n包含网页快照，删除后检索与出处同步消失。" : "\n包含原文件，删除后不可恢复。";
    if (!confirm(`确定删除「${doc.name}」？${extra}`)) return;
    try {
      await api.deleteDoc(doc.id);
      await refresh(sourceRef.current);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  async function onReprocess(doc: Doc, mode: "auto" | "deep" = "auto") {
    try {
      await api.reprocess(doc.id, mode);
      await refresh(sourceRef.current);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "重试失败");
    }
  }

  async function onCreateToken() {
    if (!tokenName.trim()) return;
    try {
      const created = await api.createCaptureToken(tokenName.trim());
      setNewToken(created.token);
      setTokenName("");
      await loadTokens();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "创建凭据失败");
    }
  }

  async function onRevokeToken(token: CaptureToken) {
    if (!confirm(`吊销凭据「${token.name}」（${token.prefix}…）？使用它的扩展将立即失效。`)) return;
    try {
      await api.revokeCaptureToken(token.id);
      await loadTokens();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "吊销失败");
    }
  }

  async function onCleanup() {
    if (!cleanupAfter && !cleanupBefore) {
      setError("请至少选择开始或结束日期");
      return;
    }
    const range = `${cleanupAfter || "最早"} ~ ${cleanupBefore || "现在"}`;
    if (!confirm(`删除该时间范围内浏览过的全部网页（含快照，不可恢复）？\n范围：${range}`)) return;
    try {
      const result = await api.cleanupBrowserDocs({
        after: cleanupAfter ? new Date(cleanupAfter).toISOString() : undefined,
        before: cleanupBefore ? new Date(cleanupBefore).toISOString() : undefined,
      });
      setNotice(`已清理 ${result.deleted} 条浏览记录`);
      await refresh("browser");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "清理失败");
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
          <Link className="btn" style={{ marginRight: 8, textDecoration: "none" }} href="/chat/">
            对话
          </Link>
          <button className="btn" onClick={onLogout}>
            退出
          </button>
        </div>
      </div>

      {storage && (
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          存储占用：数据库 {formatSize(storage.database_bytes)} · 文件 {formatSize(storage.storage_bytes)}
          {storage.snapshot_bytes > 0
            ? `（快照 ${formatSize(storage.snapshot_bytes)} / ${storage.snapshot_files} 个）`
            : ""}
          {" · "}资料 {storage.documents.upload ?? 0} 篇 / 浏览 {storage.documents.browser ?? 0} 条 /
          对话回写 {storage.documents.conversation ?? 0} 条
        </div>
      )}

      <div className="actions" style={{ marginBottom: 12 }}>
        <button
          className={source === "upload" ? "btn btn-primary" : "btn"}
          onClick={() => setSource("upload")}
        >
          上传资料
        </button>
        <button
          className={source === "browser" ? "btn btn-primary" : "btn"}
          onClick={() => setSource("browser")}
        >
          浏览记录
        </button>
      </div>

      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}

      {source === "upload" && (
        <>
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
            {uploading && (
              <div style={{ marginTop: 8 }}>
                <div className="muted">
                  上传中：{uploading.name}
                  {uploading.pct !== null && `（${uploading.pct}%）`}
                </div>
                {uploading.pct !== null ? (
                  <ProgressBar done={uploading.pct} total={100} />
                ) : (
                  <IndeterminateBar />
                )}
              </div>
            )}
          </div>

          <div className="card">
            <div className="table-wrap">
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
                        {doc.status === "processing" && (
                          <div style={{ maxWidth: 220, marginTop: 4 }}>
                            {doc.progress ? (
                              <ProgressBar done={doc.progress.done} total={doc.progress.total} />
                            ) : (
                              <IndeterminateBar />
                            )}
                          </div>
                        )}
                        {doc.status !== "indexed" && doc.status_reason && (
                          <div className="muted">{doc.status_reason}</div>
                        )}
                        {doc.parse_hint && (
                          <div className="muted">
                            {doc.parse_hint}
                            <button
                              className="btn"
                              style={{ marginLeft: 8, fontSize: 12, padding: "2px 10px" }}
                              onClick={() => onReprocess(doc, "deep")}
                            >
                              深度解析
                            </button>
                          </div>
                        )}
                      </td>
                      <td className="muted">{formatSize(doc.size)}</td>
                      <td>
                        <span className={`badge badge-${doc.status}`}>{STATUS_LABEL[doc.status]}</span>
                      </td>
                      <td>
                        <div className="actions">
                          <Link className="btn" href={`/view/?id=${doc.id}`}>
                            浏览
                          </Link>
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
          </div>
        </>
      )}

      {source === "browser" && (
        <>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>浏览器采集</h3>
            <p className="muted" style={{ marginTop: 0 }}>
              在 Chrome / Edge 扩展设置中填入服务器地址与下方凭据，浏览过的网页会
              <b>自动</b>入库（可在扩展弹窗一键暂停、在扩展设置维护黑名单）。凭据仅用于采集写入，可随时吊销。
            </p>
            {newToken && (
              <div className="notice">
                <div>
                  新凭据（<b>只显示这一次</b>，请立即复制到扩展设置）：
                </div>
                <code style={{ wordBreak: "break-all" }}>{newToken}</code>
                <div style={{ marginTop: 6 }}>
                  <button
                    className="btn"
                    onClick={() => void navigator.clipboard.writeText(newToken)}
                  >
                    复制
                  </button>
                  <button className="btn" style={{ marginLeft: 8 }} onClick={() => setNewToken(null)}>
                    我已保存
                  </button>
                </div>
              </div>
            )}
            <div className="actions" style={{ marginTop: 8 }}>
              <input
                className="chat-input"
                style={{ maxWidth: 240, minHeight: 34, padding: "6px 10px" }}
                placeholder="凭据名称（如 Windows Chrome）"
                value={tokenName}
                onChange={(e) => setTokenName(e.target.value)}
              />
              <button className="btn btn-primary" onClick={() => void onCreateToken()}>
                生成凭据
              </button>
            </div>
            {tokens.length > 0 && (
              <div className="table-wrap" style={{ marginTop: 10 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>名称</th>
                      <th>前缀</th>
                      <th>最近使用</th>
                      <th>状态</th>
                      <th style={{ width: 90 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {tokens.map((token) => (
                      <tr key={token.id}>
                        <td>{token.name}</td>
                        <td className="muted">{token.prefix}…</td>
                        <td className="muted">{fmtTime(token.last_used_at)}</td>
                        <td>
                          {token.revoked_at ? (
                            <span className="badge badge-unparseable">已吊销</span>
                          ) : (
                            <span className="badge badge-indexed">有效</span>
                          )}
                        </td>
                        <td>
                          {!token.revoked_at && (
                            <button className="btn btn-danger" onClick={() => void onRevokeToken(token)}>
                              吊销
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <h3 style={{ marginTop: 0 }}>按时间清理浏览记录</h3>
            <div className="actions">
              <label className="muted">
                开始{" "}
                <input type="date" value={cleanupAfter} onChange={(e) => setCleanupAfter(e.target.value)} />
              </label>
              <label className="muted">
                结束{" "}
                <input type="date" value={cleanupBefore} onChange={(e) => setCleanupBefore(e.target.value)} />
              </label>
              <button className="btn btn-danger" onClick={() => void onCleanup()}>
                清理
              </button>
            </div>
            <div className="muted">按「最近浏览时间」过滤；删除包含正文与快照，检索与出处同步消失。</div>
          </div>

          <div className="card">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>网页</th>
                    <th>内容</th>
                    <th>状态</th>
                    <th style={{ width: 220 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {docs.length === 0 && (
                    <tr>
                      <td colSpan={4} className="muted">
                        还没有浏览记录 —— 安装扩展后浏览网页即自动出现
                      </td>
                    </tr>
                  )}
                  {docs.map((doc) => (
                    <tr key={doc.id}>
                      <td>
                        {doc.name}
                        <div className="muted">
                          {doc.site_name} · 浏览于 {fmtTime(doc.last_captured_at)}（共 {doc.visit_count ?? 1} 次）
                        </div>
                        {doc.snapshot?.state === "skipped_oversize" && (
                          <div className="muted">快照未保留（超出体积上限），仅正文可检索</div>
                        )}
                        {doc.snapshot?.state === "skipped_error" && (
                          <div className="muted">快照生成失败，仅正文可检索</div>
                        )}
                        {doc.status === "processing" && (
                          <div style={{ maxWidth: 220, marginTop: 4 }}>
                            {doc.progress ? (
                              <ProgressBar done={doc.progress.done} total={doc.progress.total} />
                            ) : (
                              <IndeterminateBar />
                            )}
                          </div>
                        )}
                        {doc.status !== "indexed" && doc.status_reason && (
                          <div className="muted">{doc.status_reason}</div>
                        )}
                      </td>
                      <td className="muted">
                        {formatSize(doc.size)}
                        {doc.snapshot?.state === "kept" && doc.snapshot.bytes
                          ? ` · 快照 ${formatSize(doc.snapshot.bytes)}`
                          : ""}
                      </td>
                      <td>
                        <span className={`badge badge-${doc.status}`}>{STATUS_LABEL[doc.status]}</span>
                      </td>
                      <td>
                        <div className="actions">
                          {doc.snapshot?.state === "kept" && (
                            <Link className="btn" href={`/snap/?id=${doc.id}`}>
                              查看快照
                            </Link>
                          )}
                          {doc.source_url && (
                            <a className="btn" href={doc.source_url} target="_blank" rel="noreferrer">
                              打开原文
                            </a>
                          )}
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
          </div>
        </>
      )}
    </main>
  );
}
