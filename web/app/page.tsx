"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, CaptureToken, Doc, formatSize, StorageStats } from "@/lib/api";
import { highlight } from "@/lib/highlight";
import ThemeToggle from "./_components/theme-toggle";
import { ListToolbar, Pager, SortOption } from "./_components/list-controls";

const STATUS_LABEL: Record<Doc["status"], string> = {
  processing: "处理中",
  indexed: "已入库",
  unparseable: "无法解析",
};

type Source = "upload" | "browser";

type ListState = { q: string; sort: string; page: number };

/** 排序字段白名单（与后端 /api/documents sort 参数对应；dir = 该字段的自然默认方向） */
const SORT_OPTIONS: Record<Source, SortOption[]> = {
  upload: [
    { value: "created_at", label: "上传时间", dir: "desc" },
    { value: "name", label: "文件名", dir: "asc" },
    { value: "size", label: "大小", dir: "desc" },
  ],
  browser: [
    { value: "last_captured_at", label: "最近浏览", dir: "desc" },
    { value: "first_captured_at", label: "首次采集", dir: "desc" },
    { value: "visit_count", label: "浏览次数", dir: "desc" },
    { value: "name", label: "标题", dir: "asc" },
    { value: "size", label: "大小", dir: "desc" },
  ],
};

const DEFAULT_SORT: Record<Source, string> = {
  upload: "-created_at",
  browser: "-last_captured_at",
};

/** 凭据 scope 展示文案（capture=采集写入；read=只读；write=只读+写入回存） */
const TOKEN_SCOPE_LABEL: Record<string, string> = {
  capture: "采集",
  read: "只读",
  write: "只读+写入",
};

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
  return (
    <Suspense
      fallback={
        <main className="container">
          <p className="muted">加载中…</p>
        </main>
      }
    >
      <HomeInner />
    </Suspense>
  );
}

function HomeInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState<string | null>(null);
  const [source, setSource] = useState<Source>(
    searchParams.get("source") === "browser" ? "browser" : "upload"
  );
  const [docs, setDocs] = useState<Doc[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<{ name: string; pct: number | null } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // 列表查询（分页/搜索/排序）：状态进 URL（?q=&sort=&page=），刷新/后退/从详情页返回都不丢
  const [qInput, setQInput] = useState(searchParams.get("q") ?? "");
  const [list, setList] = useState<ListState>(() => ({
    q: searchParams.get("q") ?? "",
    sort: searchParams.get("sort") ?? DEFAULT_SORT[source],
    page: Math.max(1, Number.parseInt(searchParams.get("page") ?? "1", 10) || 1),
  }));
  const [pager, setPager] = useState({ total: 0, pageSize: 20 });
  const [listLoading, setListLoading] = useState(false);
  const reqSeq = useRef(0);

  // 采集凭据（F2）
  const [tokens, setTokens] = useState<CaptureToken[]>([]);
  const [tokenName, setTokenName] = useState("");
  const [newToken, setNewToken] = useState<string | null>(null);
  const [tokenOpen, setTokenOpen] = useState(false); // 凭据区折叠（日常不占版面；创建时自动展开）
  const [showRevoked, setShowRevoked] = useState(false); // 已吊销默认隐藏
  const [tokenScope, setTokenScope] = useState<"capture" | "read" | "write">("capture"); // 新凭据用途

  // 按时间清理（F2 FR-007）
  const [cleanupAfter, setCleanupAfter] = useState("");
  const [cleanupBefore, setCleanupBefore] = useState("");

  // 存储占用（试用需求）
  const [storage, setStorage] = useState<StorageStats | null>(null);

  // 标签状态跟 URL 走（?source=）：切换时重置查询（各来源独立默认排序）
  function switchSource(next: Source) {
    if (next === source) return;
    try {
      sessionStorage.removeItem("sb-lib-scroll"); // 手动切页签不恢复旧列表状态
    } catch {
      /* 忽略 */
    }
    setSource(next);
    setQInput("");
    setList({ q: "", sort: DEFAULT_SORT[next], page: 1 });
    setDocs([]);
  }

  function changeSort(value: string) {
    setList((s) => ({ ...s, sort: value, page: 1 }));
  }

  function goPage(p: number) {
    setList((s) => ({ ...s, page: p }));
    window.scrollTo({ top: 0 });
  }

  // 列表状态记忆：跳去快照/阅读器再返回时恢复（搜索/排序/页码 + 滚动位置）
  function rememberListScroll() {
    try {
      sessionStorage.setItem(
        "sb-lib-scroll",
        JSON.stringify({ source, top: window.scrollY, q: list.q, sort: list.sort, page: list.page }),
      );
    } catch {
      /* 忽略 */
    }
  }

  // 从快照/阅读器返回：URL 未显式带查询参数时，恢复离开前的列表状态
  useEffect(() => {
    if (searchParams.get("q") || searchParams.get("sort") || searchParams.get("page")) return;
    try {
      const saved = sessionStorage.getItem("sb-lib-scroll");
      if (!saved) return;
      const rec = JSON.parse(saved) as { source?: Source; q?: string; sort?: string; page?: number };
      if (rec.source !== source) return;
      setQInput(rec.q ?? "");
      setList({ q: rec.q ?? "", sort: rec.sort ?? DEFAULT_SORT[source], page: rec.page ?? 1 });
    } catch {
      /* 忽略 */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 列表状态 → URL（replace：不产生历史条目；刷新/返回都还原）
  useEffect(() => {
    const params = new URLSearchParams();
    if (source === "browser") params.set("source", "browser");
    if (list.q) params.set("q", list.q);
    if (list.sort !== DEFAULT_SORT[source]) params.set("sort", list.sort);
    if (list.page > 1) params.set("page", String(list.page));
    const qs = params.toString();
    router.replace(qs ? `/?${qs}` : "/", { scroll: false });
  }, [source, list, router]);

  const load = useCallback(async (which: Source, state: ListState, silent = false) => {
    const seq = ++reqSeq.current;
    if (!silent) setListLoading(true);
    try {
      const res = await api.listDocs(which, { q: state.q, sort: state.sort, page: state.page });
      if (seq !== reqSeq.current) return; // 竞态：最新请求胜出
      setDocs(res.items);
      setPager({ total: res.total, pageSize: res.page_size });
      if (res.page !== state.page) setList((s) => ({ ...s, page: res.page })); // 服务端钳制（如删空末页）
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        window.location.href = "/login/";
      }
    } finally {
      // 最新请求才能清 loading：静默轮询若成为最新（打断了更早的可见加载），也负责收尾
      if (seq === reqSeq.current) setListLoading(false);
    }
  }, []);

  // 查询变化（切换来源/搜索/排序/翻页）即加载
  useEffect(() => {
    void load(source, list);
  }, [source, list, load]);

  // 搜索防抖 300ms：输入停止后提交，并回到第 1 页
  useEffect(() => {
    const timer = setTimeout(() => {
      const q = qInput.trim();
      setList((s) => (s.q === q ? s : { ...s, q, page: 1 }));
    }, 300);
    return () => clearTimeout(timer);
  }, [qInput]);

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
        loadTokens(),
        api
          .storageStats()
          .then(setStorage)
          .catch(() => undefined),
      ]);
    })();
  }, [loadTokens]);

  // 滚动位置记忆消费：数据到位后回到离开时的位置
  useEffect(() => {
    if (docs.length === 0) return;
    const saved = sessionStorage.getItem("sb-lib-scroll");
    if (!saved) return;
    try {
      const rec = JSON.parse(saved) as { source: Source; top: number };
      if (rec.source !== source) return;
      sessionStorage.removeItem("sb-lib-scroll");
      window.scrollTo({ top: rec.top });
    } catch {
      /* 忽略 */
    }
  }, [docs, source]);

  // 有文档处理中时轮询状态（解析入库是后台异步的）；静默刷新不打断浏览
  const anyProcessing = docs.some((d) => d.status === "processing");
  useEffect(() => {
    if (!anyProcessing) return;
    const id = setInterval(() => void load(source, list, true), 3000);
    return () => clearInterval(id);
  }, [anyProcessing, source, list, load]);

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
      await load("upload", list);
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
      await load(source, list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  async function onReprocess(doc: Doc, mode: "auto" | "deep" = "auto") {
    try {
      await api.reprocess(doc.id, mode);
      await load(source, list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "重试失败");
    }
  }

  async function onCreateToken() {
    if (!tokenName.trim()) return;
    setTokenOpen(true);
    try {
      const created = await api.createCaptureToken(tokenName.trim(), tokenScope);
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

  async function onPurgeToken(token: CaptureToken) {
    if (!confirm(`彻底删除凭据「${token.name}」（${token.prefix}…）？删除后不可恢复。`)) return;
    try {
      await api.purgeCaptureToken(token.id);
      await loadTokens();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
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
      await load("browser", list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "清理失败");
    }
  }

  async function onLogout() {
    await api.logout().catch(() => undefined);
    window.location.href = "/login/";
  }

  const revokedCount = tokens.filter((t) => t.revoked_at).length;
  const visibleTokens = showRevoked ? tokens : tokens.filter((t) => !t.revoked_at);

  return (
    <main className="container">
      <div className="header">
        <h1>second-brain</h1>
        <div className="hdr-actions">
          <span className="muted">{username ?? ""}</span>
          <ThemeToggle />
          <Link className="btn" href="/chat/">
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

      <div className="actions actions-sticky" style={{ marginBottom: 12 }}>
        <button
          className={source === "upload" ? "btn btn-primary" : "btn"}
          onClick={() => switchSource("upload")}
        >
          上传资料
        </button>
        <button
          className={source === "browser" ? "btn btn-primary" : "btn"}
          onClick={() => switchSource("browser")}
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
            <ListToolbar
              q={qInput}
              onQChange={setQInput}
              sort={list.sort}
              sortOptions={SORT_OPTIONS.upload}
              onSortChange={changeSort}
              total={pager.total}
              loading={listLoading}
            />
            <div
              className="doc-list"
              style={{ opacity: listLoading && docs.length > 0 ? 0.6 : 1 }}
            >
              {docs.length === 0 && (
                <p className="muted" style={{ margin: 0 }}>
                  {listLoading
                    ? "加载中…"
                    : list.q
                      ? `没有匹配「${list.q}」的资料`
                      : "还没有资料 —— 上传第一本书吧"}
                </p>
              )}
              {docs.map((doc) => (
                <div key={doc.id} className="doc-item">
                  <div className="doc-item-top">
                    <div className="doc-item-main">
                      <div className="doc-item-name">{highlight(doc.name, list.q)}</div>
                      <div className="doc-item-meta">大小 {formatSize(doc.size)}</div>
                      {doc.match?.type === "content" && doc.match.snippet && (
                        <div className="doc-item-meta">正文命中：{doc.match.snippet}</div>
                      )}
                    </div>
                    <span className={`badge badge-${doc.status}`}>{STATUS_LABEL[doc.status]}</span>
                  </div>
                  {doc.status === "processing" && (
                    <div style={{ maxWidth: 260, marginTop: 6 }}>
                      {doc.progress ? (
                        <ProgressBar done={doc.progress.done} total={doc.progress.total} />
                      ) : (
                        <IndeterminateBar />
                      )}
                    </div>
                  )}
                  {doc.status !== "indexed" && doc.status_reason && (
                    <div className="doc-item-meta">{doc.status_reason}</div>
                  )}
                  {doc.parse_hint && (
                    <div className="doc-item-meta">
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
                  <div className="doc-item-actions">
                    <Link className="btn" href={`/view/?id=${doc.id}`} onClick={rememberListScroll}>
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
                </div>
              ))}
            </div>
            <Pager
              page={list.page}
              totalPages={Math.max(1, Math.ceil(pager.total / pager.pageSize))}
              onPage={goPage}
            />
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
            <details
              className="token-details"
              open={tokenOpen}
              onToggle={(e) => setTokenOpen((e.target as HTMLDetailsElement).open)}
            >
              <summary>
                采集凭据（
                {tokens.length === 0
                  ? "未创建"
                  : `${tokens.length - revokedCount} 个有效${
                      revokedCount > 0 ? ` · ${revokedCount} 个已吊销` : ""
                    }`}
                ）
              </summary>
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
                <select
                  className="list-sort"
                  value={tokenScope}
                  onChange={(e) =>
                    setTokenScope(e.target.value as "capture" | "read" | "write")
                  }
                  title="凭据用途"
                >
                  <option value="capture">采集写入（浏览器扩展）</option>
                  <option value="read">只读（MCP / Claude Code）</option>
                  <option value="write">只读+写入（MCP 可回存笔记）</option>
                </select>
                <button className="btn btn-primary" onClick={() => void onCreateToken()}>
                  生成凭据
                </button>
              </div>
              {visibleTokens.length > 0 && (
                <div className="token-list">
                  {visibleTokens.map((token) => (
                    <div key={token.id} className="token-item">
                      <div className="token-item-main">
                        <div>{token.name}</div>
                        <div className="doc-item-meta">
                          {TOKEN_SCOPE_LABEL[token.scope] ?? token.scope} · {token.prefix}… ·
                          最近使用 {fmtTime(token.last_used_at)}
                        </div>
                      </div>
                      {token.revoked_at ? (
                        <span className="badge badge-unparseable">已吊销</span>
                      ) : (
                        <span className="badge badge-indexed">有效</span>
                      )}
                      {token.revoked_at ? (
                        <button className="btn btn-danger" onClick={() => void onPurgeToken(token)}>
                          删除
                        </button>
                      ) : (
                        <button className="btn btn-danger" onClick={() => void onRevokeToken(token)}>
                          吊销
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {revokedCount > 0 && (
                <button
                  className="btn token-toggle-revoked"
                  onClick={() => setShowRevoked((v) => !v)}
                >
                  {showRevoked ? "隐藏已吊销" : `显示已吊销（${revokedCount}）`}
                </button>
              )}
            </details>
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
            <ListToolbar
              q={qInput}
              onQChange={setQInput}
              sort={list.sort}
              sortOptions={SORT_OPTIONS.browser}
              onSortChange={changeSort}
              total={pager.total}
              loading={listLoading}
            />
            <div
              className="doc-list"
              style={{ opacity: listLoading && docs.length > 0 ? 0.6 : 1 }}
            >
              {docs.length === 0 && (
                <p className="muted" style={{ margin: 0 }}>
                  {listLoading
                    ? "加载中…"
                    : list.q
                      ? `没有匹配「${list.q}」的浏览记录`
                      : "还没有浏览记录 —— 安装扩展后浏览网页即自动出现"}
                </p>
              )}
              {docs.map((doc) => (
                <div key={doc.id} className="doc-item">
                  <div className="doc-item-top">
                    <div className="doc-item-main">
                      <div className="doc-item-name">{highlight(doc.name, list.q)}</div>
                      <div className="doc-item-meta">
                        {doc.site_name} · 浏览于 {fmtTime(doc.last_captured_at)}（共 {doc.visit_count ?? 1} 次）
                      </div>
                      <div className="doc-item-meta">
                        正文 {formatSize(doc.size)}
                        {doc.snapshot?.state === "kept" && doc.snapshot.bytes
                          ? ` · 快照 ${formatSize(doc.snapshot.bytes)}`
                          : ""}
                      </div>
                      {doc.match?.type === "url" && (
                        <div className="doc-item-meta">站点/网址命中</div>
                      )}
                      {doc.match?.type === "content" && doc.match.snippet && (
                        <div className="doc-item-meta">正文命中：{doc.match.snippet}</div>
                      )}
                    </div>
                    <span className={`badge badge-${doc.status}`}>{STATUS_LABEL[doc.status]}</span>
                  </div>
                  {doc.snapshot?.state === "skipped_oversize" && (
                    <div className="doc-item-meta">快照未保留（超出体积上限），仅正文可检索</div>
                  )}
                  {doc.snapshot?.state === "skipped_error" && (
                    <div className="doc-item-meta">快照生成失败，仅正文可检索</div>
                  )}
                  {doc.status === "processing" && (
                    <div style={{ maxWidth: 260, marginTop: 6 }}>
                      {doc.progress ? (
                        <ProgressBar done={doc.progress.done} total={doc.progress.total} />
                      ) : (
                        <IndeterminateBar />
                      )}
                    </div>
                  )}
                  {doc.status !== "indexed" && doc.status_reason && (
                    <div className="doc-item-meta">{doc.status_reason}</div>
                  )}
                  <div className="doc-item-actions">
                    {doc.snapshot?.state === "kept" && (
                      <Link
                        className="btn"
                        href={`/snap/?id=${doc.id}&from=browser`}
                        onClick={rememberListScroll}
                      >
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
                </div>
              ))}
            </div>
            <Pager
              page={list.page}
              totalPages={Math.max(1, Math.ceil(pager.total / pager.pageSize))}
              onPage={goPage}
            />
          </div>
        </>
      )}
    </main>
  );
}
