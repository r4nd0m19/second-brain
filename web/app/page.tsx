"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, CaptureToken, Doc, formatSize, StorageStats } from "@/lib/api";
import { highlight } from "@/lib/highlight";
import { useLang, type Lang, type MsgKey } from "@/lib/i18n";
import ThemeToggle from "./_components/theme-toggle";
import LangToggle from "./_components/lang-toggle";
import { ListToolbar, Pager, SortOption } from "./_components/list-controls";
import DateField from "./_components/date-field";

const STATUS_KEY: Record<Doc["status"], MsgKey> = {
  processing: "docs.statusProcessing",
  indexed: "docs.statusIndexed",
  unparseable: "docs.statusUnparseable",
};

type Source = "upload" | "browser";

type ListState = { q: string; sort: string; page: number };

/** 排序字段白名单（与后端 /api/documents sort 参数对应；dir = 该字段的自然默认方向） */
const SORT_OPTIONS: Record<Source, { value: string; labelKey: MsgKey; dir: "asc" | "desc" }[]> = {
  upload: [
    { value: "created_at", labelKey: "docs.sortUploadedAt", dir: "desc" },
    { value: "name", labelKey: "docs.sortName", dir: "asc" },
    { value: "size", labelKey: "docs.sortSize", dir: "desc" },
  ],
  browser: [
    { value: "last_captured_at", labelKey: "docs.sortLastVisited", dir: "desc" },
    { value: "first_captured_at", labelKey: "docs.sortFirstCapture", dir: "desc" },
    { value: "visit_count", labelKey: "docs.sortVisits", dir: "desc" },
    { value: "name", labelKey: "docs.sortTitle", dir: "asc" },
    { value: "size", labelKey: "docs.sortSize", dir: "desc" },
  ],
};

const DEFAULT_SORT: Record<Source, string> = {
  upload: "-created_at",
  browser: "-last_captured_at",
};

/** 凭据 scope 展示文案（capture=采集写入；read=只读；write=只读+写入回存） */
const TOKEN_SCOPE_KEY: Record<string, MsgKey> = {
  capture: "docs.scopeCapture",
  read: "docs.scopeRead",
  write: "docs.scopeWrite",
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

function fmtTime(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function HomePage() {
  const { t } = useLang();
  return (
    <Suspense
      fallback={
        <main className="container">
          <p className="muted">{t("docs.loading")}</p>
        </main>
      }
    >
      <HomeInner />
    </Suspense>
  );
}

function HomeInner() {
  const { t, lang } = useLang();
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
        setNotice(t("docs.dupFile", { name: file.name }));
      } else {
        setNotice(t("docs.uploaded", { name: file.name }));
      }
      await load("upload", list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("docs.uploadFailed"));
    } finally {
      setUploading(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function onDelete(doc: Doc) {
    const extra =
      source === "browser" ? t("docs.deleteExtraBrowser") : t("docs.deleteExtraUpload");
    if (!confirm(t("docs.deleteConfirm", { name: doc.name, extra }))) return;
    try {
      await api.deleteDoc(doc.id);
      await load(source, list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("docs.deleteFailed"));
    }
  }

  async function onReprocess(doc: Doc, mode: "auto" | "deep" = "auto") {
    try {
      await api.reprocess(doc.id, mode);
      await load(source, list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("docs.retryFailed"));
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
      setError(err instanceof ApiError ? err.message : t("docs.tokenCreateFailed"));
    }
  }

  async function onRevokeToken(token: CaptureToken) {
    if (!confirm(t("docs.revokeConfirm", { name: token.name, prefix: token.prefix }))) return;
    try {
      await api.revokeCaptureToken(token.id);
      await loadTokens();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("docs.tokenRevokeFailed"));
    }
  }

  async function onPurgeToken(token: CaptureToken) {
    if (!confirm(t("docs.purgeConfirm", { name: token.name, prefix: token.prefix }))) return;
    try {
      await api.purgeCaptureToken(token.id);
      await loadTokens();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("docs.deleteFailed"));
    }
  }

  async function onCleanup() {
    if (!cleanupAfter && !cleanupBefore) {
      setError(t("docs.cleanupNeedDate"));
      return;
    }
    const range = `${cleanupAfter || t("docs.cleanupEarliest")} ~ ${cleanupBefore || t("docs.cleanupNow")}`;
    if (!confirm(t("docs.cleanupConfirm", { range }))) return;
    try {
      const result = await api.cleanupBrowserDocs({
        after: cleanupAfter ? new Date(cleanupAfter).toISOString() : undefined,
        before: cleanupBefore ? new Date(cleanupBefore).toISOString() : undefined,
      });
      setNotice(t("docs.cleanupDone", { n: result.deleted }));
      await load("browser", list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("docs.cleanupFailed"));
    }
  }

  async function onLogout() {
    await api.logout().catch(() => undefined);
    window.location.href = "/login/";
  }

  const revokedCount = tokens.filter((tk) => tk.revoked_at).length;
  const visibleTokens = showRevoked ? tokens : tokens.filter((tk) => !tk.revoked_at);

  const sortOptions = (src: Source): SortOption[] =>
    SORT_OPTIONS[src].map((o) => ({ value: o.value, label: t(o.labelKey), dir: o.dir }));

  return (
    <main className="container">
      <div className="header">
        <h1>second-brain</h1>
        <div className="hdr-actions">
          <span className="muted">{username ?? ""}</span>
          <ThemeToggle />
          <LangToggle />
          <Link className="btn" href="/chat/">
            {t("docs.navChat")}
          </Link>
          <button className="btn" onClick={onLogout}>
            {t("docs.logout")}
          </button>
        </div>
      </div>

      {storage && (
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          {t("docs.storageLine", {
            db: formatSize(storage.database_bytes),
            files: formatSize(storage.storage_bytes),
          })}
          {storage.snapshot_bytes > 0
            ? t("docs.storageSnapshots", {
                size: formatSize(storage.snapshot_bytes),
                count: storage.snapshot_files,
              })
            : ""}
          {t("docs.storageCounts", {
            uploads: storage.documents.upload ?? 0,
            browsing: storage.documents.browser ?? 0,
            conv: storage.documents.conversation ?? 0,
          })}
        </div>
      )}

      <div className="actions actions-sticky" style={{ marginBottom: 12 }}>
        <button
          className={source === "upload" ? "btn btn-primary" : "btn"}
          onClick={() => switchSource("upload")}
        >
          {t("docs.tabUpload")}
        </button>
        <button
          className={source === "browser" ? "btn btn-primary" : "btn"}
          onClick={() => switchSource("browser")}
        >
          {t("docs.tabBrowser")}
        </button>
      </div>

      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}

      {source === "upload" && (
        <>
          <div className="card">
            <p style={{ marginTop: 0 }}>{t("docs.uploadHint")}</p>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.epub,.txt,.md,.markdown,.docx,.html"
              onChange={onUpload}
              style={{ display: "none" }}
              id="file-input"
            />
            <label htmlFor="file-input" className="btn btn-primary" style={{ display: "inline-block" }}>
              {t("docs.chooseFile")}
            </label>
            {uploading && (
              <div style={{ marginTop: 8 }}>
                <div className="muted">
                  {t("docs.uploading", { name: uploading.name })}
                  {uploading.pct !== null && t("docs.uploadPct", { pct: uploading.pct })}
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
              sortOptions={sortOptions("upload")}
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
                    ? t("docs.loading")
                    : list.q
                      ? t("docs.noMatchDocs", { q: list.q })
                      : t("docs.emptyDocs")}
                </p>
              )}
              {docs.map((doc) => (
                <div key={doc.id} className="doc-item">
                  <div className="doc-item-top">
                    <div className="doc-item-main">
                      <div className="doc-item-name">{highlight(doc.name, list.q)}</div>
                      <div className="doc-item-meta">
                        {t("docs.size", { size: formatSize(doc.size) })}
                      </div>
                      {doc.match?.type === "content" && doc.match.snippet && (
                        <div className="doc-item-meta">
                          {t("docs.contentHit", { snippet: doc.match.snippet })}
                        </div>
                      )}
                    </div>
                    <span className={`badge badge-${doc.status}`}>{t(STATUS_KEY[doc.status])}</span>
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
                        {t("docs.deepParse")}
                      </button>
                    </div>
                  )}
                  <div className="doc-item-actions">
                    <Link className="btn" href={`/view/?id=${doc.id}`} onClick={rememberListScroll}>
                      {t("docs.view")}
                    </Link>
                    {doc.status !== "indexed" && (
                      <button className="btn" onClick={() => onReprocess(doc)}>
                        {t("docs.retry")}
                      </button>
                    )}
                    <a className="btn" href={api.originalUrl(doc.id)} download={doc.name}>
                      {t("docs.download")}
                    </a>
                    <button className="btn btn-danger" onClick={() => onDelete(doc)}>
                      {t("docs.delete")}
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
            <h3 style={{ marginTop: 0 }}>{t("docs.collectTitle")}</h3>
            <p className="muted" style={{ marginTop: 0 }}>
              {t("docs.collectHint1")}
              <b>{t("docs.collectHintBold")}</b>
              {t("docs.collectHint2")}
            </p>
            <details
              className="token-details"
              open={tokenOpen}
              onToggle={(e) => setTokenOpen((e.target as HTMLDetailsElement).open)}
            >
              <summary>
                {t("docs.tokensSummary", {
                  state:
                    tokens.length === 0
                      ? t("docs.tokensNone")
                      : `${t("docs.tokensActive", { n: tokens.length - revokedCount })}${
                          revokedCount > 0 ? t("docs.tokensRevoked", { n: revokedCount }) : ""
                        }`,
                })}
              </summary>
              {newToken && (
                <div className="notice">
                  <div>
                    {t("docs.newToken1")}
                    <b>{t("docs.newTokenBold")}</b>
                    {t("docs.newToken2")}
                  </div>
                  <code style={{ wordBreak: "break-all" }}>{newToken}</code>
                  <div style={{ marginTop: 6 }}>
                    <button
                      className="btn"
                      onClick={() => void navigator.clipboard.writeText(newToken)}
                    >
                      {t("docs.copy")}
                    </button>
                    <button className="btn" style={{ marginLeft: 8 }} onClick={() => setNewToken(null)}>
                      {t("docs.saved")}
                    </button>
                  </div>
                </div>
              )}
              <div className="actions" style={{ marginTop: 8 }}>
                <input
                  className="chat-input"
                  style={{ maxWidth: 240, minHeight: 34, padding: "6px 10px" }}
                  placeholder={t("docs.tokenNamePlaceholder")}
                  value={tokenName}
                  onChange={(e) => setTokenName(e.target.value)}
                />
                <select
                  className="list-sort"
                  value={tokenScope}
                  onChange={(e) =>
                    setTokenScope(e.target.value as "capture" | "read" | "write")
                  }
                  title={t("docs.tokenScopeTitle")}
                >
                  <option value="capture">{t("docs.scopeCaptureOpt")}</option>
                  <option value="read">{t("docs.scopeReadOpt")}</option>
                  <option value="write">{t("docs.scopeWriteOpt")}</option>
                </select>
                <button className="btn btn-primary" onClick={() => void onCreateToken()}>
                  {t("docs.createToken")}
                </button>
              </div>
              {visibleTokens.length > 0 && (
                <div className="token-list">
                  {visibleTokens.map((token) => (
                    <div key={token.id} className="token-item">
                      <div className="token-item-main">
                        <div>{token.name}</div>
                        <div className="doc-item-meta">
                          {t("docs.tokenMeta", {
                            scope: TOKEN_SCOPE_KEY[token.scope]
                              ? t(TOKEN_SCOPE_KEY[token.scope])
                              : token.scope,
                            prefix: token.prefix,
                            time: fmtTime(token.last_used_at, lang),
                          })}
                        </div>
                      </div>
                      {token.revoked_at ? (
                        <span className="badge badge-unparseable">{t("docs.revoked")}</span>
                      ) : (
                        <span className="badge badge-indexed">{t("docs.active")}</span>
                      )}
                      {token.revoked_at ? (
                        <button className="btn btn-danger" onClick={() => void onPurgeToken(token)}>
                          {t("docs.delete")}
                        </button>
                      ) : (
                        <button className="btn btn-danger" onClick={() => void onRevokeToken(token)}>
                          {t("docs.revoke")}
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
                  {showRevoked ? t("docs.hideRevoked") : t("docs.showRevoked", { n: revokedCount })}
                </button>
              )}
            </details>
          </div>

          <div className="card">
            <h3 style={{ marginTop: 0 }}>{t("docs.cleanupTitle")}</h3>
            <div className="actions">
              <div className="muted cleanup-date">
                {t("docs.cleanupStart")}
                <DateField value={cleanupAfter} onChange={setCleanupAfter} />
              </div>
              <div className="muted cleanup-date">
                {t("docs.cleanupEnd")}
                <DateField value={cleanupBefore} onChange={setCleanupBefore} />
              </div>
              <button className="btn btn-danger" onClick={() => void onCleanup()}>
                {t("docs.cleanup")}
              </button>
            </div>
            <div className="muted">{t("docs.cleanupHint")}</div>
          </div>

          <div className="card">
            <ListToolbar
              q={qInput}
              onQChange={setQInput}
              sort={list.sort}
              sortOptions={sortOptions("browser")}
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
                    ? t("docs.loading")
                    : list.q
                      ? t("docs.noMatchBrowser", { q: list.q })
                      : t("docs.emptyBrowser")}
                </p>
              )}
              {docs.map((doc) => (
                <div key={doc.id} className="doc-item">
                  <div className="doc-item-top">
                    <div className="doc-item-main">
                      <div className="doc-item-name">{highlight(doc.name, list.q)}</div>
                      <div className="doc-item-meta">
                        {t("docs.browserMeta", {
                          site: doc.site_name ?? "",
                          time: fmtTime(doc.last_captured_at, lang),
                          n: doc.visit_count ?? 1,
                        })}
                      </div>
                      <div className="doc-item-meta">
                        {t("docs.contentSize", { size: formatSize(doc.size) })}
                        {doc.snapshot?.state === "kept" && doc.snapshot.bytes
                          ? t("docs.snapshotSize", { size: formatSize(doc.snapshot.bytes) })
                          : ""}
                      </div>
                      {doc.match?.type === "url" && (
                        <div className="doc-item-meta">{t("docs.urlHit")}</div>
                      )}
                      {doc.match?.type === "content" && doc.match.snippet && (
                        <div className="doc-item-meta">
                          {t("docs.contentHit", { snippet: doc.match.snippet })}
                        </div>
                      )}
                    </div>
                    <span className={`badge badge-${doc.status}`}>{t(STATUS_KEY[doc.status])}</span>
                  </div>
                  {doc.snapshot?.state === "skipped_oversize" && (
                    <div className="doc-item-meta">{t("docs.snapOversize")}</div>
                  )}
                  {doc.snapshot?.state === "skipped_error" && (
                    <div className="doc-item-meta">{t("docs.snapFailed")}</div>
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
                        {t("docs.viewSnapshot")}
                      </Link>
                    )}
                    {doc.source_url && (
                      <a className="btn" href={doc.source_url} target="_blank" rel="noreferrer">
                        {t("docs.openOriginal")}
                      </a>
                    )}
                    <button className="btn btn-danger" onClick={() => onDelete(doc)}>
                      {t("docs.delete")}
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
