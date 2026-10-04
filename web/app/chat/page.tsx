"use client";

import { createParser } from "eventsource-parser";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import { api, Citation, Conversation, ConversationSearchHit, UsageInfo } from "@/lib/api";
import { highlight } from "@/lib/highlight";
import { useLang, type MsgKey, type Translate } from "@/lib/i18n";
import ThemeToggle from "../_components/theme-toggle";
import LangToggle from "../_components/lang-toggle";

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
  statusPhase?: string; // 生成阶段（SSE status 事件，2026-10-03）
  elapsedMs?: number; // 生成总耗时（done 时回填）
  thinking?: string; // 思维链增量（SSE thinking 事件；T088 仅当次生成展示、不持久化）
  thinkingStartedAt?: number; // 思考起始时间戳（前端推算思维链用时）
  thinkingMs?: number; // 思维链用时（首个正文 token 到达时定格）
  web_failed?: boolean; // 联网被规划但未取得结果（T083：显式提示，避免"以为在搜却没搜"）
  web_error?: string | null; // 失败原因码（balance/ratelimit/quota/unavailable；no_results=搜索成功但零结果）
};

/** 联网失败原因码 → 文案键（T083 追记：原因对用户可见） */
const WEB_ERR_KEY: Record<string, MsgKey> = {
  balance: "chat.webErrBalance",
  ratelimit: "chat.webErrRate",
  quota: "chat.webErrQuota",
  unavailable: "chat.webErrUnavailable",
};

function webFailedText(msg: ChatMsg, t: Translate): string {
  if (!msg.web_failed) return "";
  // 搜索完成但零结果（T090）：措辞与"故障"区分——不说"失败"（2026-10-04 实测误标驱动）
  if (msg.web_error === "no_results") return t("chat.webNoResults");
  if (msg.web_error && WEB_ERR_KEY[msg.web_error]) {
    return t("chat.webFailedReason", { reason: t(WEB_ERR_KEY[msg.web_error]) });
  }
  return t("chat.webFailed");
}

/** 生成阶段 → 文案键（后端 status 事件的 phase 值） */
const PHASE_KEY: Record<string, MsgKey> = {
  planning: "chat.phasePlanning",
  retrieving: "chat.phaseRetrieving",
  listing: "chat.phaseListing",
  expanding: "chat.phaseExpanding",
  web_search: "chat.phaseWeb",
  generating: "chat.phaseGenerating",
};

function fmtDur(ms: number): string {
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, "0")}s`;
}

/** 费用悬停明细（T079 全成本：模型 / 联网 / 检索） */
function costBreakdownTitle(usage: UsageInfo, t: Translate): string | undefined {
  const b = usage.cost_breakdown;
  if (!b) return undefined;
  const parts: string[] = [];
  if (b.llm) parts.push(`${t("chat.costLlm")} ¥${b.llm.toFixed(4)}`);
  if (b.web) parts.push(`${t("chat.costWeb")} ¥${b.web.toFixed(4)}`);
  if (b.retrieval) parts.push(`${t("chat.costRetrieval")} ¥${b.retrieval.toFixed(4)}`);
  return parts.length ? parts.join(" · ") : undefined;
}

/** 流式静默看门狗（三期 P1）：超过该时长无任何字节 → 主动中止（不设总超时，长回答不被掐断） */
const STREAM_IDLE_TIMEOUT_MS = 60_000;

/** 来源标签 → 文案键（中英文案表见 lib/i18n） */
const SOURCE_LABEL_KEY: Record<string, MsgKey> = {
  kb: "chat.sourceKb",
  model_knowledge: "chat.sourceModel",
  prior_conversation: "chat.sourcePrior",
  web: "chat.sourceWeb",
};

/** 空状态示例问题（点击填入输入框；文案键见 lib/i18n） */
const EMPTY_SUGGESTION_KEYS: MsgKey[] = ["chat.suggest1", "chat.suggest2", "chat.suggest3"];

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

function fmtCitationTime(iso: string | null | undefined, lang: "zh" | "en"): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
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
  onNavigate?: () => void,
  onOpenConversation?: (conversationId: string, messageId?: string) => void,
  onOpenWeb?: (citation: Citation) => void
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
                  // 联网来源（F4）：点 [N] 弹「引文小窗」（2026-10-03 用户反馈），浏览器访问改由窗内显式按钮；
                  // 保留 href 以支持中键/新标签；未接入小窗的场合（如对话预览窗内）退回直开
                  if (onOpenWeb) {
                    return (
                      <a
                        className="citation-chip"
                        href={citationHref(citation)}
                        title={citation.document_name}
                        onClick={(e) => {
                          e.preventDefault();
                          onOpenWeb(citation);
                        }}
                      >
                        {children}
                      </a>
                    );
                  }
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
                if (citation.conversation_id && onOpenConversation) {
                  // 对话回写来源：同路由软导航不重挂载（挂载期深链解析不会重跑）→ 直接切换会话；
                  // 保留 href 以支持中键/新标签（新加载走深链）
                  return (
                    <a
                      className="citation-chip"
                      href={citationHref(citation)}
                      title={citation.document_name}
                      onClick={(e) => {
                        e.preventDefault();
                        onOpenConversation(
                          citation.conversation_id!,
                          citation.message_id ?? undefined
                        );
                      }}
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
  onOpenConversation,
  splitBySource = false,
}: {
  items: Citation[];
  label?: string;
  showJump?: boolean;
  onNavigate?: () => void;
  /** 对话回写来源的「回到原对话」：同路由软导航不重挂载 → 直接切换会话（见 renderAssistant 同注） */
  onOpenConversation?: (conversationId: string, messageId?: string) => void;
  splitBySource?: boolean; // 分「网络来源 / 出处」两组（编号保持与正文 [N] 角标一致）
}) {
  const { t, lang } = useLang();
  if (items.length === 0) return null;
  const numbered = items.map((c, i) => ({ c, n: i + 1 }));
  const groups: { label: string; entries: { c: Citation; n: number }[] }[] = splitBySource
    ? [
        { label: t("chat.citationsWeb"), entries: numbered.filter((e) => e.c.web) },
        { label: t("chat.citationsLocal"), entries: numbered.filter((e) => !e.c.web) },
      ]
    : [{ label: label ?? t("chat.citationsDefault"), entries: numbered }];
  return (
    <div className="citation">
      {/* 按类别分组折叠（2026-10-03）：每组摘要行显示「类别 + 条数」，点开才列条目 */}
      {groups
        .filter((g) => g.entries.length > 0)
        .map((g) => (
          <details key={g.label}>
            <summary>
              {t("chat.citationCount", { label: g.label, count: g.entries.length })}
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
                    ? `${t("chat.inlineWebTag")}${
                        c.last_captured_at
                          ? t("chat.inlineVisitedAt", {
                              time: fmtCitationTime(c.last_captured_at, lang),
                            })
                          : ""
                      }`
                    : ""}
                  {c.heading_path ? ` · ${c.heading_path}` : ""}
                  {c.page ? t("common.page", { page: c.page }) : ""}
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
                        {t("chat.openWeb")}
                      </a>
                    ) : (
                      <>
                        {c.conversation_id && !c.source_url && onOpenConversation ? (
                          <a
                            className="btn"
                            style={{ fontSize: 12, padding: "3px 10px" }}
                            href={citationHref(c)}
                            onClick={(e) => {
                              e.preventDefault();
                              onOpenConversation(
                                c.conversation_id!,
                                c.message_id ?? undefined
                              );
                            }}
                          >
                            {t("chat.backToConv")}
                          </a>
                        ) : (
                          <Link
                            className="btn"
                            style={{ fontSize: 12, padding: "3px 10px" }}
                            href={citationHref(c)}
                            onClick={onNavigate}
                          >
                            {c.source_url
                              ? t("chat.viewSnapshot")
                              : c.conversation_id
                                ? t("chat.backToConv")
                                : t("chat.jumpToSource")}
                          </Link>
                        )}
                        {c.source_url && (
                          <a
                            className="btn"
                            style={{ fontSize: 12, padding: "3px 10px", marginLeft: 8 }}
                            href={c.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {t("chat.openOriginal")}
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

/** 对话引用预览小窗（2026-10-03 用户反馈）：只读消息流 + 定位高亮被引用消息，
 *  不离开当前对话；窗内引用可继续追（对话→重定向本窗，书籍→正常跳阅读器）；
 *  「在对话中打开」再走整页切换。 */
function ConvPreview({
  convId,
  msgId,
  titleFor,
  onClose,
  onOpenFull,
}: {
  convId: string;
  msgId: string | null;
  titleFor: (conversationId: string) => string;
  onClose: () => void;
  onOpenFull: (conversationId: string, messageId?: string) => void;
}) {
  const { t } = useLang();
  const [target, setTarget] = useState<{ convId: string; msgId: string | null }>({
    convId,
    msgId,
  });
  const [msgs, setMsgs] = useState<ChatMsg[] | null>(null);
  const [flashId, setFlashId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMsgs(null);
    api
      .conversationMessages(target.convId)
      .then((stored) => {
        if (cancelled) return;
        setMsgs(
          stored.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            source_type: m.source_type,
            citations: m.citations ?? undefined,
            related_hints: m.related_hints ?? undefined,
          }))
        );
      })
      .catch(() => {
        if (!cancelled) setMsgs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [target.convId]);

  // 消息渲染后：定位目标消息并短暂高亮
  useEffect(() => {
    if (!msgs || !target.msgId) return;
    document.getElementById(`pv-${target.msgId}`)?.scrollIntoView({ block: "center" });
    setFlashId(target.msgId);
  }, [msgs, target.msgId]);

  // Escape 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="conv-preview-backdrop" role="presentation" onClick={onClose}>
      <div
        className="conv-preview"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="conv-preview-head">
          <div className="conv-preview-title">{titleFor(target.convId)}</div>
          <div style={{ display: "flex", gap: 6, flex: "0 0 auto" }}>
            <button
              className="btn"
              onClick={() => onOpenFull(target.convId, target.msgId ?? undefined)}
            >
              {t("chat.previewOpenFull")}
            </button>
            <button className="btn" onClick={onClose} aria-label={t("chat.previewClose")}>
              ✕
            </button>
          </div>
        </div>
        <div className="conv-preview-body">
          {msgs === null ? (
            <p className="muted">{t("docs.loading")}</p>
          ) : (
            msgs.map((m) => (
              <div
                key={m.id}
                id={m.id ? `pv-${m.id}` : undefined}
                className={`bubble ${m.role === "user" ? "bubble-user" : "bubble-assistant"}${
                  m.id && m.id === flashId ? " bubble-flash" : ""
                }`}
                onAnimationEnd={() => {
                  if (m.id && m.id === flashId) setFlashId(null);
                }}
              >
                {m.role === "assistant"
                  ? m.content
                    ? renderAssistant(m.content, chipCitations(m), undefined, (cid, mid) =>
                        setTarget({ convId: cid, msgId: mid ?? null })
                      )
                    : ""
                  : m.content}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

/** 网页引用「引文小窗」（2026-10-03 用户反馈）：点 [N] 先看回答所依据的原文摘录（回答时从页面正文提取，
 *  失败回退搜索摘要），浏览器访问改由窗内「↗ 打开原文」显式触发——业界同款卡片形态
 *  （iframe 直嵌原页会被站点 X-Frame-Options/CSP 拒绝，实测常引来源约半数不可嵌）。 */
function WebCitePreview({
  citation,
  onClose,
}: {
  citation: Citation;
  onClose: () => void;
}) {
  const { t } = useLang();
  // Escape 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  let host = "";
  try {
    host = citation.source_url ? new URL(citation.source_url).hostname : "";
  } catch {
    host = "";
  }
  return (
    <div className="conv-preview-backdrop" role="presentation" onClick={onClose}>
      <div
        className="conv-preview"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="conv-preview-head">
          <div className="conv-preview-title">
            {citation.document_name}
            {host && (
              <span className="muted" style={{ fontWeight: 400, fontSize: 12, marginLeft: 8 }}>
                {t("chat.sourceWeb")} · {host}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 6, flex: "0 0 auto" }}>
            {citation.source_url && (
              <a className="btn" href={citation.source_url} target="_blank" rel="noreferrer">
                {t("chat.openOriginal")}
              </a>
            )}
            <button className="btn" onClick={onClose} aria-label={t("chat.previewClose")}>
              ✕
            </button>
          </div>
        </div>
        <div className="conv-preview-body">
          {citation.quote ? (
            <blockquote className="muted">“{citation.quote}”</blockquote>
          ) : (
            <p className="muted">{t("chat.webNoQuote")}</p>
          )}
          {citation.source_url && (
            <p className="muted" style={{ fontSize: 12, wordBreak: "break-all", marginTop: 8 }}>
              {citation.source_url}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/** 思维链折叠块（T088）：生成时展开实时刷新，答案开始输出后自动折叠；仅当次生成展示（不持久化）。 */
function ThinkingBlock({ text, ms, live }: { text: string; ms?: number; live: boolean }) {
  const { t } = useLang();
  const [open, setOpen] = useState(true);
  const wasLive = useRef(live);
  useEffect(() => {
    if (wasLive.current && !live) setOpen(false); // 正文开始输出 → 自动折叠
    wasLive.current = live;
  }, [live]);
  return (
    <details className="think-block" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="muted">
        {live
          ? t("chat.thinkingLive")
          : t("chat.thinkingDone", { s: ((ms ?? 0) / 1000).toFixed(1) })}
      </summary>
      <div className="think-body muted">{text}</div>
    </details>
  );
}

export default function ChatPage() {
  const { t, lang } = useLang();
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [activeConv, setActiveConv] = useState<string | null>(null);
  const convRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // 滚动策略（2026-10-03 用户要求"生成回答后不要定位到回答底部"）：仅在「发送 / 打开会话」
  // 时定位一次到底部；流式生成期间完全不跟随——页面保持不动。
  const scrollBottomOnceRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null); // 生成中止（停止按钮 / 静默看门狗）
  const stopRequestedRef = useRef(false); // 区分"用户主动停止"与"其他中断"
  const startedAtRef = useRef(0); // 本轮生成开始时间（用时显示/回填）
  const [, setTimerTick] = useState(0); // 每秒重渲染一次，驱动的用时计时

  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setTimerTick((v) => v + 1), 1000);
    return () => clearInterval(id);
  }, [busy]);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null); // 「复制」反馈

  // 侧栏收起（惯例：独立切换按钮 + localStorage 记忆 + Ctrl/Cmd+B；首屏由 layout 内联脚本防闪跳）
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // 手机端会话抽屉（ChatGPT 移动端同款：左上角汉堡 → 左侧滑出会话列表；汉堡钮仅 ≤720px 显示）
  const [drawerOpen, setDrawerOpen] = useState(false);
  // 对话全文搜索（会话级结果）
  const [convQuery, setConvQuery] = useState("");
  const [convHits, setConvHits] = useState<ConversationSearchHit[] | null>(null);
  const [convTotal, setConvTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [flashId, setFlashId] = useState<string | null>(null); // 跳转后的短暂高亮消息
  const [preview, setPreview] = useState<{ convId: string; msgId: string | null } | null>(null); // 对话引用预览小窗
  const [webPreview, setWebPreview] = useState<Citation | null>(null); // 网页引用「引文小窗」
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
      scrollBottomOnceRef.current = false; // 跳转定位优先于"定位到底部"
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
          scrollBottomOnceRef.current = false; // 恢复历史位置优先于"定位到底部"
          scrollRef.current?.scrollTo({ top });
          return;
        }
      } catch {
        /* 忽略 */
      }
    }
    if (scrollBottomOnceRef.current) {
      scrollBottomOnceRef.current = false;
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

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
    setDrawerOpen(false); // 选中会话即收起手机抽屉（点选后立即看到内容）
    const seq = ++convOpenSeq.current;
    try {
      const stored = await api.conversationMessages(id);
      if (seq !== convOpenSeq.current) return; // 竞态：最新打开胜出
      jumpRef.current = jumpMessageId ?? null; // 供渲染后的滚动 effect 消费
      scrollBottomOnceRef.current = true; // 打开会话：定位到最新消息（此后由用户控制）
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

  /** 引用角标（对话类）：弹出预览小窗，不离开当前对话（用户反馈：直接整页跳转太突兀） */
  function openConversationPreview(conversationId: string, messageId?: string) {
    setPreview({ convId: conversationId, msgId: messageId ?? null });
  }

  /** 引用角标（网页类）：弹出「引文小窗」显示回答所依据的原文摘录（用户反馈：不要直接丢去浏览器） */
  function openWebPreview(citation: Citation) {
    setWebPreview(citation);
  }

  /** 「回到原对话」按钮 / 预览窗「在对话中打开」：同路由软导航不重挂载（挂载期深链解析不会重跑）
   *  → 直接切换会话 + 同步 URL（刷新/分享仍可用；href 保留供中键/新标签） */
  function openConversationFromCitation(conversationId: string, messageId?: string) {
    void openConversation(conversationId, messageId);
    const params = new URLSearchParams({ conv: conversationId });
    if (messageId) params.set("msg", messageId);
    router.replace(`/chat/?${params.toString()}`, { scroll: false });
  }

  function newChat() {
    setDrawerOpen(false); // 新建对话同样收起抽屉
    convRef.current = null;
    setActiveConv(null);
    localStorage.removeItem("sb-conv");
    setMessages([]);
  }

  async function deleteConv(id: string, event: React.MouseEvent) {
    event.stopPropagation();
    if (!confirm(t("chat.deleteConvConfirm"))) return;
    try {
      await api.deleteConversation(id);
      if (convRef.current === id) newChat();
      await loadConversations();
    } catch {
      /* 忽略 */
    }
  }

  /** 停止生成（三期 P1）：中止 fetch 流；已生成内容保留 */
  function stopGeneration() {
    stopRequestedRef.current = true;
    abortRef.current?.abort();
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    stopRequestedRef.current = false;
    startedAtRef.current = Date.now(); // 用时计时（2026-10-03）
    scrollBottomOnceRef.current = true; // 发送：定位一次，让新提问可见；之后保持不动
    setMessages((m) => [
      ...m,
      { role: "user", content: text },
      { role: "assistant", content: "", streaming: true },
    ]);

    const ac = new AbortController();
    abortRef.current = ac;
    let idleTimer: ReturnType<typeof setTimeout> | undefined;
    let idleTimedOut = false;
    const armIdle = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        idleTimedOut = true;
        ac.abort();
      }, STREAM_IDLE_TIMEOUT_MS);
    };

    try {
      armIdle(); // 覆盖"连接建立 / 首字节"等待；每收到数据即重置
      const res = await fetch("/api/chat", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: convRef.current }),
        signal: ac.signal,
      });
      if (res.status === 401) {
        window.location.href = "/login/";
        return;
      }
      if (!res.ok || !res.body) throw new Error(t("chat.requestFailed", { status: res.status }));

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let createdNew = false;
      let gotDone = false;
      let sawError = false;

      // SSE 帧解析交 eventsource-parser（规范实现：CRLF / 多行 data / 跨块 UTF-8；手写解析退役，三期 P1）
      const parser = createParser({
        onEvent: (ev) => {
          if (!ev.data) return;
          const payload = JSON.parse(ev.data);
          const event = ev.event ?? "message";

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
                web_failed: payload.web_failed ?? false,
                web_error: payload.web_error ?? null,
              }),
            );
          } else if (event === "status") {
            setMessages((m) => patchLast(m, { statusPhase: payload.phase }));
          } else if (event === "thinking") {
            setMessages((m) => {
              const last = m[m.length - 1];
              return patchLast(m, {
                thinking: (last?.thinking ?? "") + (payload.text ?? ""),
                thinkingStartedAt: last?.thinkingStartedAt ?? Date.now(),
              });
            });
          } else if (event === "token") {
            setMessages((m) => {
              const last = m[m.length - 1];
              const patch: Partial<ChatMsg> = { content: lastContent(m) + payload.text };
              if (last?.thinking && last.thinkingStartedAt && last.thinkingMs === undefined) {
                patch.thinkingMs = Date.now() - last.thinkingStartedAt; // 思维链用时定格（首个正文 token）
              }
              return patchLast(m, patch);
            });
          } else if (event === "error") {
            sawError = true;
            setMessages((m) => patchLast(m, { error: payload.message, streaming: false }));
          } else if (event === "done") {
            gotDone = true;
            setMessages((m) =>
              patchLast(m, {
                streaming: false,
                usage: payload.usage
                  ? { ...payload.usage, cost_cny: payload.cost_cny }
                  : undefined,
                elapsedMs: startedAtRef.current ? Date.now() - startedAtRef.current : undefined,
              }),
            );
          }
        },
      });

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        armIdle();
        parser.feed(decoder.decode(value, { stream: true }));
      }
      parser.feed(decoder.decode());
      if (!gotDone && !sawError && !stopRequestedRef.current && !idleTimedOut) {
        setMessages((m) =>
          patchLast(m, { error: t("chat.streamInterrupted"), streaming: false }),
        );
      }
      if (createdNew) await loadConversations();
    } catch (err) {
      if (stopRequestedRef.current) {
        // 用户主动停止：保留已生成内容，不报错
      } else if (idleTimedOut) {
        setMessages((m) => patchLast(m, { error: t("chat.streamTimeout"), streaming: false }));
      } else {
        setMessages((m) =>
          patchLast(m, {
            error: err instanceof Error ? err.message : t("chat.sendFailed"),
            streaming: false,
          }),
        );
      }
    } finally {
      clearTimeout(idleTimer);
      abortRef.current = null;
      setBusy(false);
      setMessages((m) => patchLast(m, { streaming: false }));
    }
  }

  return (
    <main className="chat-shell">
      <div className="header chat-header">
        <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
          {/* 手机端（≤720px）：左上角汉堡 → 会话抽屉（桌面隐藏，见 globals.css .drawer-toggle） */}
          <button
            className="btn drawer-toggle"
            aria-label={t("chat.toggleExpand")}
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen(true)}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M4 7h16M4 12h16M4 17h16"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
          {!sidebarOpen && (
            <button
              className="btn sidebar-toggle"
              aria-label={t("chat.toggleExpand")}
              aria-expanded={sidebarOpen}
              title={t("chat.toggleTitle")}
              onClick={toggleSidebar}
            >
              ▶
            </button>
          )}
          <h1 style={{ fontSize: 16, color: "var(--muted)" }}>{t("chat.title")}</h1>
        </div>
        <div className="hdr-actions">
          <Link className="btn" href="/">
            {t("chat.navLibrary")}
          </Link>
          <ThemeToggle />
          <LangToggle />
        </div>
      </div>

      <div className="chat-layout">
        {/* 手机端遮罩：点按关闭抽屉（桌面端该元素 display:none，且汉堡不可达） */}
        {drawerOpen && <div className="drawer-backdrop" onClick={() => setDrawerOpen(false)} />}
        {/* 桌面收起由 html[data-sidebar=off]（layout 内联脚本 + toggleSidebar 设置）；
            手机端固定定位 + transform 显隐（.drawer-open），不再用内联 style 双通道 */}
        <aside className={`sidebar${drawerOpen ? " drawer-open" : ""}`}>
          <div className="sidebar-top">
            <button
              className="btn sidebar-toggle"
              aria-label={t("chat.toggleCollapse")}
              aria-expanded={sidebarOpen}
              title={t("chat.toggleTitle")}
              onClick={toggleSidebar}
            >
              ◀
            </button>
            <button className="btn sidebar-new" onClick={newChat}>
              {t("chat.newChat")}
            </button>
          </div>
          <input
            className="sidebar-search"
            type="search"
            placeholder={t("chat.searchPlaceholder")}
            value={convQuery}
            onChange={(e) => setConvQuery(e.target.value)}
          />
          {convQuery.trim() ? (
            <>
              <div className="muted conv-search-status">
                {searching ? t("chat.searching") : convHits ? t("chat.searchHits", { total: convTotal }) : ""}
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
                    {hit.hit_count > 1 ? t("chat.hitCount", { n: hit.hit_count }) : ""}
                    {fmtCitationTime(hit.last_hit_at, lang)}
                  </div>
                </div>
              ))}
              {convHits && convHits.length === 0 && !searching && (
                <p className="muted" style={{ fontSize: 13 }}>
                  {t("chat.noMatch")}
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
                    title={t("chat.deleteConvTitle")}
                    onClick={(e) => void deleteConv(c.id, e)}
                  >
                    ×
                  </button>
                </div>
              ))}
              {convs.length === 0 && (
                <p className="muted" style={{ fontSize: 13 }}>
                  {t("chat.noConversations")}
                </p>
              )}
            </>
          )}
        </aside>

        <div className="chat-main">
        <div className="chat-area" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="chat-empty">
              <h2>{t("chat.emptyTitle")}</h2>
              <p className="muted">{t("chat.emptyHint")}</p>
              <div className="chat-empty-suggestions">
                {EMPTY_SUGGESTION_KEYS.map((key) => {
                  const suggestion = t(key);
                  return (
                    <button
                      key={key}
                      className="btn"
                      onClick={() => {
                        setInput(suggestion);
                        textareaRef.current?.focus();
                      }}
                    >
                      {suggestion}
                    </button>
                  );
                })}
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
                {msg.role === "assistant" && msg.thinking ? (
                  <ThinkingBlock
                    text={msg.thinking}
                    ms={
                      msg.thinkingMs ??
                      (msg.thinkingStartedAt && !msg.streaming
                        ? Date.now() - msg.thinkingStartedAt
                        : undefined)
                    }
                    live={!!msg.streaming && !msg.content}
                  />
                ) : null}
                {msg.content
                  ? msg.role === "assistant"
                    ? renderAssistant(
                      msg.content,
                      chipCitations(msg),
                      rememberScroll,
                      openConversationPreview,
                      openWebPreview
                    )
                    : msg.content
                  : ""}
                {msg.streaming && (
                  <div className="stream-status muted">
                    <span className="stream-dot" aria-hidden="true" />
                    {[
                      t(
                        (msg.statusPhase && PHASE_KEY[msg.statusPhase]) ||
                          "chat.phaseGenerating"
                      ),
                      startedAtRef.current ? fmtDur(Date.now() - startedAtRef.current) : "",
                      msg.content ? t("chat.streamChars", { n: msg.content.length }) : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                )}
                {msg.role === "assistant" && msg.streaming && msg.content ? (
                  <span className="stream-caret" aria-hidden="true" />
                ) : null}
              </div>
              {msg.role === "assistant" && (msg.source_type || msg.error) && (
                <div className="bubble-meta">
                  {msg.error
                    ? `⚠️ ${msg.error}`
                    : t("chat.sourcePrefix", {
                        label:
                          msg.source_type && SOURCE_LABEL_KEY[msg.source_type]
                            ? t(SOURCE_LABEL_KEY[msg.source_type])
                            : (msg.source_type ?? ""),
                      })}
                  {!msg.error ? webFailedText(msg, t) : ""}
                </div>
              )}
              {msg.role === "assistant" && msg.time_range_label && (
                <div className="bubble-meta">
                  {t("chat.timeRange", { label: msg.time_range_label })}
                </div>
              )}
              {msg.role === "assistant" && msg.usage && (
                <div className="bubble-meta">
                  {typeof msg.usage.prompt_tokens === "number" &&
                    `↑${msg.usage.prompt_tokens} ↓${msg.usage.completion_tokens ?? 0} tokens · `}
                  {typeof msg.usage.cost_cny === "number" && (
                    <span title={costBreakdownTitle(msg.usage, t)}>
                      ≈¥{msg.usage.cost_cny.toFixed(4)}
                    </span>
                  )}
                  {typeof msg.elapsedMs === "number" && ` · ⏱ ${fmtDur(msg.elapsedMs)}`}
                  {msg.usage.prompt_cache_hit_tokens
                    ? t("chat.cacheHit", { n: msg.usage.prompt_cache_hit_tokens })
                    : ""}
                </div>
              )}
              {msg.citations && msg.citations.length > 0 && (
                <CitationList
                  items={msg.citations}
                  splitBySource
                  showJump={false}
                  onNavigate={rememberScroll}
                  onOpenConversation={openConversationFromCitation}
                />
              )}
              {msg.related_hints && msg.related_hints.length > 0 && (
                <CitationList
                  items={msg.related_hints}
                  label={t("chat.related")}
                  onNavigate={rememberScroll}
                  onOpenConversation={openConversationFromCitation}
                />
              )}
              {msg.role === "assistant" && (
                <CitationList
                  items={inheritedCitations(msg)}
                  label={t("chat.inherited")}
                  onNavigate={rememberScroll}
                  onOpenConversation={openConversationFromCitation}
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
                    {copiedIdx === i ? t("chat.copied") : t("chat.copy")}
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
              placeholder={t("chat.inputPlaceholder")}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            {busy ? (
              <button
                type="button"
                className="send-btn send-btn-stop"
                onClick={stopGeneration}
                title={t("chat.stop")}
                aria-label={t("chat.stop")}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" />
                </svg>
              </button>
            ) : (
              <button
                type="button"
                className="send-btn"
                onClick={() => void send()}
                disabled={!input.trim()}
                title={t("chat.sendTitle")}
                aria-label={t("chat.send")}
              >
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M12 19V5M5.5 11.5 12 5l6.5 6.5"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            )}
          </div>
          <div className="composer-hint">{t("chat.composerHint")}</div>
        </div>
      </div>
        </div>
      </div>
      {preview && (
        <ConvPreview
          convId={preview.convId}
          msgId={preview.msgId}
          titleFor={(id) => {
            const conv = convs.find((c) => c.id === id);
            return conv ? conv.title : t("docs.navChat");
          }}
          onClose={() => setPreview(null)}
          onOpenFull={(id, mid) => {
            setPreview(null);
            openConversationFromCitation(id, mid);
          }}
        />
      )}
      {webPreview && (
        <WebCitePreview citation={webPreview} onClose={() => setWebPreview(null)} />
      )}
    </main>
  );
}
