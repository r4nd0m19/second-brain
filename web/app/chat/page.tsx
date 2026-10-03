"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import { api, Citation, Conversation, ConversationSearchHit, UsageInfo } from "@/lib/api";
import { highlight } from "@/lib/highlight";
import ThemeToggle from "../_components/theme-toggle";

type ChatMsg = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  source_type?: string | null;
  citations?: Citation[];
  related_hints?: Citation[];
  usage?: UsageInfo;
  time_range_label?: string | null;
  error?: string;
  streaming?: boolean;
};

const SOURCE_LABEL: Record<string, string> = {
  kb: "来自你的资料",
  model_knowledge: "来自模型知识",
  prior_conversation: "来自既往对话",
  web: "来自网络",
};

/** 空状态示例问题（点击填入输入框） */
const EMPTY_SUGGESTIONS = [
  "我的资料里是如何定义「架构决策」的？",
  "我最近 3 天看过哪些网页？",
  "上周看过的文章里关于 AI 的内容有哪些？",
];

function patchLast(messages: ChatMsg[], patch: Partial<ChatMsg>): ChatMsg[] {
  if (messages.length === 0) return messages;
  const next = messages.slice();
  next[next.length - 1] = { ...next[next.length - 1], ...patch };
  return next;
}

function lastContent(messages: ChatMsg[]): string {
  return messages.length ? messages[messages.length - 1].content : "";
}

function citationHref(c: Citation): string {
  if (c.web && c.source_url) return c.source_url; // 联网来源（F4）→ 外链直开新标签
  if (c.conversation_id) {
    // 对话回写来源 → 回到原对话（可带消息定位，复用搜索跳转的高亮机制）
    const params = new URLSearchParams({ conv: c.conversation_id });
    if (c.message_id) params.set("msg", c.message_id);
    return `/chat/?${params.toString()}`;
  }
  if (c.source_url) return `/snap/?id=${c.document_id}&from=chat`; // 网页来源 → 快照回放页（返回时回对话）
  const params = new URLSearchParams({ id: c.document_id, from: "chat" });
  if (c.page) params.set("page", String(c.page));
  const snippet = (c.quote ?? "").replace(/\s+/g, " ").trim().slice(0, 200);
  if (snippet) params.set("q", snippet);
  if (c.heading_path) params.set("h", c.heading_path);
  return `/view/?${params.toString()}`;
}

/** 既往对话答案：正文里的 [N] 是旧答案的标记 → 用继承的原始出处映射；无继承则不映射（纯文本，防误指） */
function chipCitations(msg: ChatMsg): Citation[] | undefined {
  if (msg.source_type !== "prior_conversation") return msg.citations;
  return inheritedCitations(msg);
}

/** 从 citations 里取继承的原始出处（2026-10-02 追溯链路） */
function inheritedCitations(msg: ChatMsg): Citation[] {
  const found = msg.citations?.find((c) => c.inherited_citations?.length);
  return found?.inherited_citations ?? [];
}

function fmtCitationTime(iso?: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const CITATION_SCHEME = "citation:";

/**
 * react-markdown v9+ 默认 URL 消毒只放行 http/https/irc/mailto/xmpp，
 * 自定义 `citation:` 协议会被清成空串（空 href = 当前页 → 点击等于跳回本页）——
 * 这里放行 citation:，其余交给默认消毒。
 */
function markdownUrlTransform(url: string): string {
  return url.startsWith(CITATION_SCHEME) ? url : defaultUrlTransform(url);
}

/** 回答正文按 Markdown 渲染；[N] 编号映射为可点击引用（对应 citations[N-1]，无对应则保留原文）。 */
function renderAssistant(
  content: string,
  citations?: Citation[],
  onNavigate?: () => void
): React.ReactNode {
  const prepared =
    citations && citations.length > 0
      ? content.replace(/\[(\d+)\]/g, (full, n: string) =>
          citations[Number(n) - 1] ? `[${n}](${CITATION_SCHEME}${n})` : full
        )
      : content;
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={markdownUrlTransform}
        components={{
          a: ({ href, children }) => {
            if (!href) return <>{children}</>; // 被消毒掉的不可信链接：只留文本
            if (href.startsWith(CITATION_SCHEME)) {
              const citation = citations?.[Number(href.slice(CITATION_SCHEME.length)) - 1];
              if (citation) {
                if (citation.web) {
                  // 联网来源（F4）：外部网页链接直接新标签打开（不经本地路由）
                  return (
                    <a
                      className="citation-chip"
                      href={citationHref(citation)}
                      title={citation.document_name}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {children}
                    </a>
                  );
                }
                return (
                  <Link
                    className="citation-chip"
                    href={citationHref(citation)}
                    title={citation.document_name}
                    onClick={onNavigate}
                  >
                    {children}
                  </Link>
                );
              }
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {prepared}
      </ReactMarkdown>
    </div>
  );
}

function CitationList({
  items,
  label,
  showJump = true,
  onNavigate,
  splitBySource = false,
}: {
  items: Citation[];
  label?: string;
  showJump?: boolean;
  onNavigate?: () => void;
  splitBySource?: boolean; // 分「网络来源 / 出处」两组（编号保持与正文 [N] 角标一致）
}) {
  if (items.length === 0) return null;
  const numbered = items.map((c, i) => ({ c, n: i + 1 }));
  const groups: { label: string; entries: { c: Citation; n: number }[] }[] = splitBySource
    ? [
        { label: "网络来源", entries: numbered.filter((e) => e.c.web) },
        { label: "出处", entries: numbered.filter((e) => !e.c.web) },
      ]
    : [{ label: label ?? "来源", entries: numbered }];
  return (
    <div className="citation">
      {/* 按类别分组折叠（2026-10-03）：每组摘要行显示「类别 + 条数」，点开才列条目 */}
      {groups
        .filter((g) => g.entries.length > 0)
        .map((g) => (
          <details key={g.label}>
            <summary>
              {g.label}：{g.entries.length} 条
            </summary>
            {g.entries.map(({ c, n }) => (
              <details key={c.chunk_id ?? `citation-${n}`}>
                <summary>
                  【{n}】{c.web && c.source_url ? (
                    // 联网来源直链（FR-002）：标题可点、新标签打开原文，无需展开详情
                    <a
                      className="citation-link"
                      href={citationHref(c)}
                      title={c.source_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {c.document_name} ↗
                    </a>
                  ) : (
                    c.document_name
                  )}
                  {c.source_url
                    ? ` · 网页${c.last_captured_at ? ` · 浏览于 ${fmtCitationTime(c.last_captured_at)}` : ""}`
                    : ""}
                  {c.heading_path ? ` · ${c.heading_path}` : ""}
                  {c.page ? `（第 ${c.page} 页）` : ""}
                </summary>
                {c.quote ? <blockquote className="muted">“{c.quote}”</blockquote> : null}
                {showJump && (
                  <div style={{ marginTop: 4 }}>
                    {c.web ? (
                      <a
                        className="btn"
                        style={{ fontSize: 12, padding: "3px 10px" }}
                        href={c.source_url ?? "#"}
                        target="_blank"
                        rel="noreferrer"
                      >
                        ↗ 打开网页
                      </a>
                    ) : (
                      <>
                        <Link
                          className="btn"
                          style={{ fontSize: 12, padding: "3px 10px" }}
                          href={citationHref(c)}
                          onClick={onNavigate}
                        >
                          {c.source_url ? "🖼 查看快照" : c.conversation_id ? "↩ 回到原对话" : "↗ 跳到原文位置"}
                        </Link>
                        {c.source_url && (
                          <a
                            className="btn"
                            style={{ fontSize: 12, padding: "3px 10px", marginLeft: 8 }}
                            href={c.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            ↗ 打开原文
                          </a>
                        )}
                      </>
                    )}
                  </div>
                )}
              </details>
            ))}
          </details>
        ))}
    </div>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [activeConv, setActiveConv] = useState<string | null>(null);
  const convRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true); // 是否"贴着底部"（用户上滚阅读时不强制跟随流式输出）
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null); // 「复制」反馈

  // 侧栏收起（惯例：独立切换按钮 + localStorage 记忆 + Ctrl/Cmd+B；首屏由 layout 内联脚本防闪跳）
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // 对话全文搜索（会话级结果）
  const [convQuery, setConvQuery] = useState("");
  const [convHits, setConvHits] = useState<ConversationSearchHit[] | null>(null);
  const [convTotal, setConvTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [flashId, setFlashId] = useState<string | null>(null); // 跳转后的短暂高亮消息
  const jumpRef = useRef<string | null>(null); // 待定位消息（渲染后消费）
  const searchSeq = useRef(0);
  const convOpenSeq = useRef(0);

  const loadConversations = useCallback(async () => {
    try {
      setConvs(await api.listConversations());
    } catch {
      /* 未登录等场景由 me() 流程兜底 */
    }
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const convParam = params.get("conv");
    const msgParam = params.get("msg");
    void loadConversations();
    if (convParam) {
      // 深链「回到原对话」（2026-10-02）：打开指定会话并定位消息（复用搜索跳转的滚动+高亮）
      void openConversation(convParam, msgParam ?? undefined);
      return;
    }
    convRef.current = localStorage.getItem("sb-conv");
    setActiveConv(convRef.current);
    if (convRef.current) {
      void openConversation(convRef.current);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 侧栏收起状态：首屏后从 localStorage 同步（html[data-sidebar] 已由 layout 内联脚本先行应用）
  useEffect(() => {
    try {
      setSidebarOpen(localStorage.getItem("sb-sidebar") !== "0");
    } catch {
      /* 忽略 */
    }
  }, []);

  function toggleSidebar() {
    const next = !sidebarOpen;
    setSidebarOpen(next);
    try {
      localStorage.setItem("sb-sidebar", next ? "1" : "0");
      if (next) delete document.documentElement.dataset.sidebar;
      else document.documentElement.dataset.sidebar = "off";
    } catch {
      /* 忽略 */
    }
  }

  // Ctrl/Cmd+B 切换侧栏（与主流对话应用一致；输入框内不拦截）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "b") return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      e.preventDefault();
      toggleSidebar();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidebarOpen]);

  // 对话搜索：防抖 300ms，命中消息正文（会话级结果）；竞态"最新请求胜出"
  useEffect(() => {
    const q = convQuery.trim();
    const seq = ++searchSeq.current;
    if (!q) {
      setConvHits(null);
      setConvTotal(0);
      setSearching(false);
      return;
    }
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const res = await api.searchConversations(q);
        if (seq !== searchSeq.current) return;
        setConvHits(res.items);
        setConvTotal(res.total);
      } catch {
        if (seq === searchSeq.current) setConvHits([]);
      } finally {
        if (seq === searchSeq.current) setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [convQuery]);

  // 滚动位置记忆（2026-10-02）：跳去原文/快照再返回时恢复离开时的位置；否则自动回到底部。
  // （2026-10-03 ChatGPT 式外壳改造：消息区 .chat-area 为独立滚动容器，记录/恢复其 scrollTop。）
  function rememberScroll() {
    try {
      sessionStorage.setItem(
        "sb-chat-scroll",
        JSON.stringify({ conv: convRef.current, top: scrollRef.current?.scrollTop ?? 0 })
      );
    } catch {
      /* 忽略 */
    }
  }

  useEffect(() => {
    if (messages.length === 0) return;
    // 从搜索结果跳转：定位到目标消息并短暂高亮（不参与回到底部/恢复位置逻辑）
    const jump = jumpRef.current;
    if (jump) {
      jumpRef.current = null;
      document.getElementById(`msg-${jump}`)?.scrollIntoView({ block: "center" });
      setFlashId(jump);
      return;
    }
    const saved = sessionStorage.getItem("sb-chat-scroll");
    if (saved) {
      sessionStorage.removeItem("sb-chat-scroll");
      try {
        const { conv, top } = JSON.parse(saved) as { conv: string | null; top: number };
        if (conv && conv === convRef.current) {
          scrollRef.current?.scrollTo({ top });
          return;
        }
      } catch {
        /* 忽略 */
      }
    }
    if (stickRef.current) {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  // 是否贴底（用户在底部附近才自动跟随流式输出）——监听消息区滚动容器（外壳改造）
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // 输入草稿不丢（跳去原文/快照再返回时还在）
  useEffect(() => {
    try {
      const draft = sessionStorage.getItem("sb-chat-draft");
      if (draft) setInput(draft);
    } catch {
      /* 忽略 */
    }
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem("sb-chat-draft", input);
    } catch {
      /* 忽略 */
    }
  }, [input]);

  async function openConversation(id: string, jumpMessageId?: string) {
    const seq = ++convOpenSeq.current;
    try {
      const stored = await api.conversationMessages(id);
      if (seq !== convOpenSeq.current) return; // 竞态：最新打开胜出
      jumpRef.current = jumpMessageId ?? null; // 供渲染后的滚动 effect 消费
      setMessages(
        stored.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          source_type: m.source_type,
          citations: m.citations ?? undefined,
          related_hints: m.related_hints ?? undefined,
          usage: m.usage ?? undefined,
        })),
      );
      convRef.current = id;
      setActiveConv(id);
      localStorage.setItem("sb-conv", id);
    } catch {
      jumpRef.current = null;
      /* 忽略：列表会被刷新 */
    }
  }

  function newChat() {
    convRef.current = null;
    setActiveConv(null);
    localStorage.removeItem("sb-conv");
    setMessages([]);
  }

  async function deleteConv(id: string, event: React.MouseEvent) {
    event.stopPropagation();
    if (!confirm("删除这个对话？（连同其回写入库的内容，不可恢复）")) return;
    try {
      await api.deleteConversation(id);
      if (convRef.current === id) newChat();
      await loadConversations();
    } catch {
      /* 忽略 */
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [
      ...m,
      { role: "user", content: text },
      { role: "assistant", content: "", streaming: true },
    ]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: convRef.current }),
      });
      if (res.status === 401) {
        window.location.href = "/login/";
        return;
      }
      if (!res.ok || !res.body) throw new Error(`请求失败（${res.status}）`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let createdNew = false;

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let split;
        while ((split = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);

          let event = "message";
          let data = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (!data) continue;
          const payload = JSON.parse(data);

          if (event === "meta") {
            if (payload.conversation_id) {
              createdNew = createdNew || convRef.current !== payload.conversation_id;
              convRef.current = payload.conversation_id;
              setActiveConv(payload.conversation_id);
              localStorage.setItem("sb-conv", payload.conversation_id);
            }
            setMessages((m) =>
              patchLast(m, {
                source_type: payload.source_type,
                citations: payload.citations ?? [],
                related_hints: payload.related_hints ?? [],
                time_range_label: payload.time_range_label ?? null,
              }),
            );
          } else if (event === "token") {
            setMessages((m) => patchLast(m, { content: lastContent(m) + payload.text }));
          } else if (event === "error") {
            setMessages((m) => patchLast(m, { error: payload.message, streaming: false }));
          } else if (event === "done") {
            setMessages((m) =>
              patchLast(m, {
                streaming: false,
                usage: payload.usage
                  ? { ...payload.usage, cost_cny: payload.cost_cny }
                  : undefined,
              }),
            );
          }
        }
      }
      if (createdNew) await loadConversations();
    } catch (err) {
      setMessages((m) =>
        patchLast(m, {
          error: err instanceof Error ? err.message : "发送失败",
          streaming: false,
        }),
      );
    } finally {
      setBusy(false);
      setMessages((m) => patchLast(m, { streaming: false }));
    }
  }

  return (
    <main className="chat-shell">
      <div className="header chat-header">
        <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
          {!sidebarOpen && (
            <button
              className="btn sidebar-toggle"
              aria-label="展开对话列表"
              aria-expanded={sidebarOpen}
              title="展开对话列表（Ctrl+B）"
              onClick={toggleSidebar}
            >
              ▶
            </button>
          )}
          <h1 style={{ fontSize: 16, color: "var(--muted)" }}>second-brain · 对话</h1>
        </div>
        <div className="hdr-actions">
          <Link className="btn" href="/">
            资料
          </Link>
          <ThemeToggle />
        </div>
      </div>

      <div className="chat-layout">
        <aside className="sidebar" style={{ display: sidebarOpen ? undefined : "none" }}>
          <div className="sidebar-top">
            <button
              className="btn sidebar-toggle"
              aria-label="收起对话列表"
              aria-expanded={sidebarOpen}
              title="收起 / 展开对话列表（Ctrl+B）"
              onClick={toggleSidebar}
            >
              ◀
            </button>
            <button className="btn sidebar-new" onClick={newChat}>
              ＋ 新对话
            </button>
          </div>
          <input
            className="sidebar-search"
            type="search"
            placeholder="搜索对话（全文）…"
            value={convQuery}
            onChange={(e) => setConvQuery(e.target.value)}
          />
          {convQuery.trim() ? (
            <>
              <div className="muted conv-search-status">
                {searching ? "搜索中…" : convHits ? `${convTotal} 个会话命中` : ""}
              </div>
              {(convHits ?? []).map((hit) => (
                <div
                  key={hit.id}
                  className={`sidebar-item conv-hit${hit.id === activeConv ? " active" : ""}`}
                  onClick={() => void openConversation(hit.id, hit.hit.message_id)}
                >
                  <div className="conv-hit-title">{highlight(hit.title, convQuery)}</div>
                  <div className="conv-hit-snippet">{highlight(hit.hit.snippet, convQuery)}</div>
                  <div className="conv-hit-meta">
                    {hit.hit_count > 1 ? `${hit.hit_count} 处命中 · ` : ""}
                    {fmtCitationTime(hit.last_hit_at)}
                  </div>
                </div>
              ))}
              {convHits && convHits.length === 0 && !searching && (
                <p className="muted" style={{ fontSize: 13 }}>
                  没有匹配的对话
                </p>
              )}
            </>
          ) : (
            <>
              {convs.map((c) => (
                <div
                  key={c.id}
                  className={`sidebar-item${c.id === activeConv ? " active" : ""}`}
                  onClick={() => void openConversation(c.id)}
                >
                  <span className="sidebar-title">{c.title}</span>
                  <button
                    className="sidebar-del"
                    title="删除对话"
                    onClick={(e) => void deleteConv(c.id, e)}
                  >
                    ×
                  </button>
                </div>
              ))}
              {convs.length === 0 && (
                <p className="muted" style={{ fontSize: 13 }}>
                  暂无历史对话
                </p>
              )}
            </>
          )}
        </aside>

        <div className="chat-main">
        <div className="chat-area" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="chat-empty">
              <h2>向你的第二大脑提问吧</h2>
              <p className="muted">你的资料、浏览过的网页与历史对话都会被检索并引用</p>
              <div className="chat-empty-suggestions">
                {EMPTY_SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    className="btn"
                    onClick={() => {
                      setInput(s);
                      textareaRef.current?.focus();
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              id={msg.id ? `msg-${msg.id}` : undefined}
              className={`bubble ${msg.role === "user" ? "bubble-user" : "bubble-assistant"}${
                msg.id && msg.id === flashId ? " bubble-flash" : ""
              }`}
              onAnimationEnd={() => {
                if (msg.id && msg.id === flashId) setFlashId(null);
              }}
            >
              <div>
                {msg.content
                  ? msg.role === "assistant"
                    ? renderAssistant(msg.content, chipCitations(msg), rememberScroll)
                    : msg.content
                  : ""}
                {!msg.content && msg.streaming ? "…" : ""}
                {msg.role === "assistant" && msg.streaming && msg.content ? (
                  <span className="stream-caret" aria-hidden="true" />
                ) : null}
              </div>
              {msg.role === "assistant" && (msg.source_type || msg.error) && (
                <div className="bubble-meta">
                  {msg.error
                    ? `⚠️ ${msg.error}`
                    : `来源：${SOURCE_LABEL[msg.source_type ?? ""] ?? msg.source_type}`}
                </div>
              )}
              {msg.role === "assistant" && msg.time_range_label && (
                <div className="bubble-meta">🕐 检索时间范围：{msg.time_range_label}</div>
              )}
              {msg.role === "assistant" && msg.usage && (
                <div className="bubble-meta">
                  ↑{msg.usage.prompt_tokens ?? 0} ↓{msg.usage.completion_tokens ?? 0} tokens
                  {typeof msg.usage.cost_cny === "number" &&
                    ` · ≈¥${msg.usage.cost_cny.toFixed(4)}`}
                  {msg.usage.prompt_cache_hit_tokens
                    ? ` · 缓存命中 ${msg.usage.prompt_cache_hit_tokens}`
                    : ""}
                </div>
              )}
              {msg.citations && msg.citations.length > 0 && (
                <CitationList
                  items={msg.citations}
                  splitBySource
                  showJump={false}
                  onNavigate={rememberScroll}
                />
              )}
              {msg.related_hints && msg.related_hints.length > 0 && (
                <CitationList
                  items={msg.related_hints}
                  label="库中可能相关"
                  onNavigate={rememberScroll}
                />
              )}
              {msg.role === "assistant" && (
                <CitationList
                  items={inheritedCitations(msg)}
                  label="原文出处"
                  onNavigate={rememberScroll}
                />
              )}
              {msg.role === "assistant" && msg.content && !msg.streaming && (
                <div className="msg-actions">
                  <button
                    className="msg-action-btn"
                    onClick={() => {
                      void navigator.clipboard.writeText(msg.content);
                      setCopiedIdx(i);
                      window.setTimeout(
                        () => setCopiedIdx((cur) => (cur === i ? null : cur)),
                        1500,
                      );
                    }}
                  >
                    {copiedIdx === i ? "✓ 已复制" : "⧉ 复制"}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>

      <div className="input-row">
        <div className="input-inner">
          <div className="composer">
            <textarea
              ref={textareaRef}
              className="chat-input"
              placeholder="给第二大脑发消息…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <button
              className="send-btn"
              onClick={() => void send()}
              disabled={busy || !input.trim()}
              title={busy ? "回答中…" : "发送（Enter）"}
              aria-label="发送"
            >
              {busy ? "…" : "↑"}
            </button>
          </div>
          <div className="composer-hint">回答可能有误，请以出处为准 · Enter 发送，Shift+Enter 换行</div>
        </div>
      </div>
        </div>
      </div>
    </main>
  );
}
