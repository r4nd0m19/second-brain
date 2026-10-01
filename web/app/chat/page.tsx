"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, Citation, Conversation, UsageInfo } from "@/lib/api";

type ChatMsg = {
  role: "user" | "assistant";
  content: string;
  source_type?: string | null;
  citations?: Citation[];
  related_hints?: Citation[];
  usage?: UsageInfo;
  error?: string;
  streaming?: boolean;
};

const SOURCE_LABEL: Record<string, string> = {
  kb: "来自你的资料",
  model_knowledge: "来自模型知识",
  prior_conversation: "来自既往对话",
};

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
  const params = new URLSearchParams({ id: c.document_id, from: "chat" });
  if (c.page) params.set("page", String(c.page));
  const snippet = c.quote.replace(/\s+/g, " ").trim().slice(0, 200);
  if (snippet) params.set("q", snippet);
  if (c.heading_path) params.set("h", c.heading_path);
  return `/view/?${params.toString()}`;
}

/** 把回答正文中的 [N] 编号渲染为可点击的跳转按钮（对应 citations[N-1]，无对应则保留原文）。 */
function renderWithCitations(content: string, citations?: Citation[]): React.ReactNode {
  if (!citations || citations.length === 0) return content;
  return content.split(/(\[\d+\])/g).map((part, i) => {
    const m = /^\[(\d+)\]$/.exec(part);
    if (!m) return part;
    const c = citations[Number(m[1]) - 1];
    if (!c) return part;
    return (
      <Link key={i} className="citation-chip" href={citationHref(c)} title={c.document_name}>
        {part}
      </Link>
    );
  });
}

function CitationList({
  items,
  label,
  showJump = true,
}: {
  items: Citation[];
  label: string;
  showJump?: boolean;
}) {
  if (items.length === 0) return null;
  return (
    <div className="citation">
      <div className="muted">{label}</div>
      {items.map((c, i) => (
        <details key={c.chunk_id}>
          <summary>
            【{i + 1}】{c.document_name}
            {c.heading_path ? ` · ${c.heading_path}` : ""}
            {c.page ? `（第 ${c.page} 页）` : ""}
          </summary>
          <blockquote className="muted">“{c.quote}”</blockquote>
          {showJump && (
            <div style={{ marginTop: 4 }}>
              <Link
                className="btn"
                style={{ fontSize: 12, padding: "3px 10px" }}
                href={citationHref(c)}
              >
                ↗ 跳到原文位置
              </Link>
            </div>
          )}
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

  const loadConversations = useCallback(async () => {
    try {
      setConvs(await api.listConversations());
    } catch {
      /* 未登录等场景由 me() 流程兜底 */
    }
  }, []);

  useEffect(() => {
    convRef.current = localStorage.getItem("sb-conv");
    setActiveConv(convRef.current);
    void loadConversations();
    if (convRef.current) {
      void openConversation(convRef.current);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function openConversation(id: string) {
    try {
      const stored = await api.conversationMessages(id);
      setMessages(
        stored.map((m) => ({
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
    <main className="container" style={{ maxWidth: 1100 }}>
      <div className="header">
        <h1>second-brain · 对话</h1>
        <div>
          <Link className="btn" style={{ marginRight: 8 }} href="/">
            资料
          </Link>
        </div>
      </div>

      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        <aside className="sidebar">
          <button
            className="btn btn-primary"
            style={{ width: "100%", marginBottom: 10 }}
            onClick={newChat}
          >
            ＋ 新对话
          </button>
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
        </aside>

        <div className="chat-area" ref={scrollRef} style={{ flex: 1, minWidth: 0 }}>
          {messages.length === 0 && (
            <p className="muted">
              向你的资料提问吧 —— 比如：“这本架构书里是如何定义架构决策的？”
            </p>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`bubble ${msg.role === "user" ? "bubble-user" : "bubble-assistant"}`}
            >
              <div>
                {msg.content ? renderWithCitations(msg.content, msg.citations) : ""}
                {!msg.content && msg.streaming ? "…" : ""}
              </div>
              {msg.role === "assistant" && (msg.source_type || msg.error) && (
                <div className="bubble-meta">
                  {msg.error
                    ? `⚠️ ${msg.error}`
                    : `来源：${SOURCE_LABEL[msg.source_type ?? ""] ?? msg.source_type}`}
                </div>
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
                <CitationList items={msg.citations} label="出处：" showJump={false} />
              )}
              {msg.related_hints && msg.related_hints.length > 0 && (
                <CitationList items={msg.related_hints} label="库中可能相关：" />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="input-row">
        <div className="input-inner">
          <textarea
            className="chat-input"
            placeholder="问点什么…（Enter 发送，Shift+Enter 换行）"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button className="btn btn-primary" onClick={() => void send()} disabled={busy}>
            {busy ? "回答中…" : "发送"}
          </button>
        </div>
      </div>
    </main>
  );
}
