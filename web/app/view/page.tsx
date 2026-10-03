"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, Doc, api } from "@/lib/api";
import ThemeToggle from "../_components/theme-toggle";

type ViewState =
  | { kind: "loading" }
  | { kind: "pdf"; id: string }
  | { kind: "text"; content: string }
  | { kind: "epub" }
  | { kind: "unsupported"; reason: string }
  | { kind: "error"; message: string };

const TEXT_FORMATS = new Set(["txt", "md", "markdown"]);

type EpubElement = {
  textContent?: string | null;
  ownerDocument?: Document | null;
};
/** section.load 的请求器：epubjs 用 book.load 才能从内存 archive 读章节 */
type EpubLoader = (url: string) => Promise<{ documentElement?: EpubElement } | undefined>;
type EpubSection = {
  href: string;
  // load() resolve 出根元素（XHTML/XML 模式下没有 .body，直接 textContent）
  load: (request?: EpubLoader) => Promise<EpubElement | undefined>;
  /** Range（位于该章节 DOM）→ 精确 CFI，用于高亮与页内定位 */
  cfiFromRange?: (range: Range) => string;
  unload?: () => void;
};
type EpubRendition = {
  display: (target?: string) => Promise<void>;
  prev: () => Promise<void>;
  next: () => Promise<void>;
  on?: (event: string, cb: (payload: EpubLocation) => void) => void;
  reportLocation?: () => void;
  annotations?: {
    highlight?: (
      cfiRange: string,
      data?: Record<string, unknown>,
      cb?: () => void,
      className?: string,
      styles?: Record<string, string>,
    ) => void;
  };
  /** 章内容钩子：每章 iframe 文档注册（键盘监听等，2026-10-03） */
  hooks?: {
    content?: { register?: (cb: (contents: { document?: Document }) => void) => void };
  };
};
type EpubLocation = { start?: { percentage?: number; cfi?: string } };
/** 目录条目（book.loaded.navigation.toc） */
type EpubTocItem = { label?: string; href?: string; subitems?: EpubTocItem[] };
type EpubBook = {
  ready?: Promise<unknown>;
  spine?: { length: number; get: (index: number) => EpubSection | null };
  load: (url: string) => Promise<{ documentElement?: EpubElement } | undefined>;
  locations?: {
    generate: (chars?: number) => Promise<unknown>;
    length?: () => number;
    locationFromCfi?: (cfi: string) => number;
    cfiFromLocation?: (loc: number) => string;
  };
  loaded?: { navigation?: Promise<{ toc?: EpubTocItem[] }> };
  renderTo: (el: HTMLElement, opts: Record<string, string>) => EpubRendition;
  destroy?: () => void;
};
type EpubFactory = (data: ArrayBuffer) => EpubBook;

/** 单字符级归一化：1:1 替换（智能引号/破折号/不换行空格），长度不变以便 DOM 偏移映射。 */
function normalizeChars(s: string): string {
  return s
    .replace(/[‘’′]/g, "'")
    .replace(/[“”″]/g, '"')
    .replace(/[–—−]/g, "-")
    .replace(/ /g, " ")
    .replace(/\s+/g, " ");
}

/** 引文与原文常存在标点差异 —— 统一并折叠空白后再匹配。 */
function normalizeText(s: string): string {
  return normalizeChars(s).replace(/\s+/g, " ").trim();
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 归一化目标文本 → 正则（大小写不敏感）：空白折叠为 \s+，容忍原文里标签/换行造成的空白差异。 */
function textPattern(target: string): RegExp | null {
  const parts = normalizeText(target).split(" ").filter(Boolean).map(escapeRegExp);
  return parts.length ? new RegExp(parts.join("\\s+"), "i") : null;
}

/**
 * 在已加载章节的 DOM 中定位目标文本，返回 DOM Range（供 cfiFromRange 生成高亮 CFI）。
 * 文本节点扁平化 + 单字符归一化（长度不变，偏移可直接映射回节点）。
 */
function findRangeInSection(root: EpubElement, target: string): Range | null {
  const doc = root.ownerDocument;
  const pattern = textPattern(target);
  if (!doc || !pattern) return null;

  const walker = doc.createTreeWalker(root as unknown as Node, NodeFilter.SHOW_TEXT);
  const spans: { node: Text; start: number }[] = [];
  let flat = "";
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const parentTag = n.parentNode?.nodeName?.toLowerCase();
    if (parentTag === "script" || parentTag === "style") continue;
    spans.push({ node: n as Text, start: flat.length });
    flat += normalizeChars(n.nodeValue ?? "");
  }

  const match = pattern.exec(flat);
  if (!match) return null;
  const posToPoint = (pos: number): [Text, number] | null => {
    for (let i = spans.length - 1; i >= 0; i -= 1) {
      if (pos >= spans[i].start) {
        return [spans[i].node, Math.min(pos - spans[i].start, spans[i].node.data.length)];
      }
    }
    return null;
  };
  const start = posToPoint(match.index);
  const end = posToPoint(match.index + match[0].length);
  if (!start || !end) return null;

  const range = doc.createRange();
  range.setStart(start[0], start[1]);
  range.setEnd(end[0], end[1]);
  return range;
}

/** 在文本中定位引文（归一化 + 前 8 个词宽松匹配）。 */
function findHit(content: string, q: string): { start: number; end: number } | null {
  const words = normalizeText(q)
    .split(" ")
    .slice(0, 8)
    .filter(Boolean)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (words.length === 0) return null;
  const match = new RegExp(words.join("[\\s\\S]{0,10}")).exec(content);
  return match ? { start: match.index, end: match.index + match[0].length } : null;
}

/**
 * EPUB 引文定位（FR-016 尽力而为）：逐章扫描，返回章节 href 与引文精确 CFI。
 * 匹配大小写不敏感（Docling 可能改写标题大小写，与原文不一致）；
 * 目录/导览类章节（toc/nav）降权：命中先记住继续找正文，正文找不到才退回目录。
 * 匹配分级（强 → 弱，弱目标仅在强目标全库无果时启用）：
 *   ① 引文长片段（200/120/80/40 字）—— 优先，命中即可高亮对应长度
 *   ② 引文片段（24 字、12 字；不足 12 字的短引文整句兜底）
 *   ③ 章节标题（heading_path 末段）—— 仅定位章节，不用于高亮
 * 高亮范围尽量取引文最长可匹配前缀（避免只高亮开头一小段）。
 * 加载必须经 book.load（内存 archive）；文本取根元素 textContent（XHTML 无 body）。
 * 不依赖 epubjs 的 search 插件（多数构建不含）。
 */
async function findEpubLocation(
  book: EpubBook,
  snippet: string,
  heading: string | null,
): Promise<{ href: string; cfi: string | null } | null> {
  if (!book.spine) return null;

  const normalized = normalizeText(snippet);
  const quotePhases: string[][] = [];
  const longQuote = [200, 120, 80, 40]
    .filter((len) => normalized.length >= len)
    .map((len) => normalized.slice(0, len));
  if (longQuote.length > 0) quotePhases.push(longQuote);
  if (normalized.length >= 24) quotePhases.push([normalized.slice(0, 24)]);
  if (normalized.length >= 12) quotePhases.push([normalized.slice(0, 12)]);
  if (quotePhases.length === 0 && normalized.length >= 4) {
    quotePhases.push([normalized]); // 短引文（<12 字）整句兜底
  }
  const highlightTargets = quotePhases.flat();
  const lastHeading = heading ? normalizeText(heading.split("/").pop() ?? "") : "";
  const headingTargets = lastHeading.length >= 6 ? [lastHeading] : [];
  const phases = [...quotePhases, ...(headingTargets.length > 0 ? [headingTargets] : [])];

  const hit = (text: string, targets: string[]) => {
    const lower = text.toLowerCase();
    const compactLower = lower.replace(/\s+/g, "");
    return targets.some((t) => {
      const lowerTarget = t.toLowerCase();
      return (
        lower.includes(lowerTarget) || compactLower.includes(lowerTarget.replace(/\s+/g, ""))
      );
    });
  };
  /** 目录/导览类章节（toc01.html、nav.xhtml 等） */
  const isTocLike = (href: string) => /(toc|nav)/i.test(href.split("/").pop() ?? href);

  const loader = book.load.bind(book); // 必须经 book.load：从内存 archive 读取；不传则回退 fetch 拿错内容
  let tocFallback: { href: string; cfi: string | null } | null = null;
  for (const targets of phases) {
    for (let i = 0; i < book.spine.length; i += 1) {
      const section = book.spine.get(i);
      if (!section) continue;
      try {
        const contents = await section.load(loader);
        const text = normalizeText(contents?.textContent ?? "");
        if (hit(text, targets)) {
          let cfi: string | null = null;
          if (contents && section.cfiFromRange) {
            // 高亮范围：引文目标按最长优先重试（标题命中章节时也顺便再试）
            for (const t of highlightTargets) {
              const range = findRangeInSection(contents, t);
              if (!range) continue;
              try {
                cfi = section.cfiFromRange(range);
              } catch {
                cfi = null;
              }
              break;
            }
          }
          const jump = { href: section.href, cfi };
          section.unload?.();
          if (isTocLike(section.href)) {
            if (!tocFallback) tocFallback = jump; // 目录命中降权，继续找正文
            continue;
          }
          return jump;
        }
        section.unload?.();
      } catch {
        /* 跳过加载失败的章节 */
      }
    }
  }
  return tocFallback;
}

function TextBody({ content, q }: { content: string; q: string | null }) {
  const hitRef = useRef<HTMLElement | null>(null);
  const hit = useMemo(() => (q ? findHit(content, q) : null), [content, q]);

  useEffect(() => {
    if (hit) hitRef.current?.scrollIntoView({ block: "center" });
  }, [hit]);

  if (!hit) {
    return (
      <pre className="card" style={{ whiteSpace: "pre-wrap", maxHeight: "80vh", overflow: "auto" }}>
        {content}
      </pre>
    );
  }
  return (
    <pre className="card" style={{ whiteSpace: "pre-wrap", maxHeight: "80vh", overflow: "auto" }}>
      {content.slice(0, hit.start)}
      <mark ref={hitRef} style={{ background: "var(--warn)", color: "#000" }}>
        {content.slice(hit.start, hit.end)}
      </mark>
      {content.slice(hit.end)}
    </pre>
  );
}

export default function ViewPage() {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [jumpPage, setJumpPage] = useState<string | null>(null);
  const [jumpQuote, setJumpQuote] = useState<string | null>(null);
  const [jumpHeading, setJumpHeading] = useState<string | null>(null);
  const [jumpStatus, setJumpStatus] = useState("");
  const [epubProgress, setEpubProgress] = useState("");
  const [epubPage, setEpubPage] = useState<{ cur: number; total: number } | null>(null); // 页码（按位置索引估算）
  const [epubToc, setEpubToc] = useState<EpubTocItem[] | null>(null);
  const [epubTotal, setEpubTotal] = useState<number | null>(null); // 位置索引总页数（跳页用）
  const [jumpTo, setJumpTo] = useState(""); // 「跳至 N 页」输入
  const [fromChat, setFromChat] = useState(false);
  const epubRef = useRef<HTMLDivElement>(null);
  const epubBookRef = useRef<EpubBook | null>(null);
  const renditionRef = useRef<EpubRendition | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    const page = params.get("page");
    const q = params.get("q");
    const h = params.get("h");
    setFromChat(params.get("from") === "chat"); // 从对话来的出处链接 → 返回时回对话页
    setJumpPage(page);
    setJumpQuote(q);
    setJumpHeading(h);
    if (!id) {
      setState({ kind: "error", message: "缺少文件参数（?id=）" });
      return;
    }
    (async () => {
      try {
        const info = await api.getDoc(id);
        setDoc(info);
        if (info.format === "pdf") {
          setState({ kind: "pdf", id });
        } else if (TEXT_FORMATS.has(info.format)) {
          const res = await fetch(`/api/documents/${id}/original?inline=1`, {
            credentials: "include",
          });
          if (!res.ok) throw new Error(`读取失败（${res.status}）`);
          setState({ kind: "text", content: await res.text() });
        } else if (info.format === "epub") {
          setState({ kind: "epub" });
        } else {
          setState({
            kind: "unsupported",
            reason: `暂不支持在线浏览 .${info.format} 格式`,
          });
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          window.location.href = "/login/";
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setState({ kind: "error", message: "该资料不存在或已被删除（来源已删除）" });
          return;
        }
        setState({ kind: "error", message: err instanceof Error ? err.message : "加载失败" });
      }
    })();
  }, []);

  // EPUB 渲染 + 引文定位（epubjs 动态载入）
  useEffect(() => {
    if (state.kind !== "epub" || !doc || !epubRef.current) return;
    const container = epubRef.current;
    let cancelled = false;
    setEpubPage(null);
    setEpubToc(null);
    setEpubTotal(null);

    (async () => {
      try {
        const res = await fetch(`/api/documents/${doc.id}/original?inline=1`, {
          credentials: "include",
        });
        if (!res.ok) throw new Error(`读取失败（${res.status}）`);
        const data = await res.arrayBuffer();
        const mod = (await import("epubjs")) as unknown as {
          default?: EpubFactory;
        } & EpubFactory;
        const ePub = mod.default ?? mod;
        if (cancelled) return;

        const book = ePub(data);
        epubBookRef.current = book;
        await book.ready;

        // 目录（2026-10-03）：读取导航结构；无目录的书不阻塞
        try {
          const nav = await book.loaded?.navigation;
          if (!cancelled && nav?.toc?.length) setEpubToc(nav.toc);
        } catch {
          /* 无目录 */
        }

        const rendition = book.renderTo(container, { width: "100%", height: "100%" });
        renditionRef.current = rendition;
        rendition.on?.("relocated", (loc) => {
          const pct = loc?.start?.percentage;
          setEpubProgress(typeof pct === "number" ? `${Math.round(pct * 100)}%` : "");
          // 页码：locations 索引（generate 完成前 length 为 0 → 不显示）
          const cfi = loc?.start?.cfi;
          const total = book.locations?.length?.() ?? 0;
          const cur = cfi && total > 0 ? book.locations?.locationFromCfi?.(cfi) : undefined;
          if (typeof cur === "number" && cur >= 0) {
            setEpubPage({ cur: cur + 1, total });
          }
        });
        // 键盘 ←→：章节为独立 iframe，window 监听收不到章内焦点按键（2026-10-03 修复）——
        // 注册到每章 content hooks；窗口级监听保留为焦点在工具栏时的兜底
        rendition.hooks?.content?.register?.((contents) => {
          contents.document?.addEventListener("keydown", (e) => {
            const ke = e as KeyboardEvent;
            if (ke.key === "ArrowLeft") void rendition.prev();
            if (ke.key === "ArrowRight") void rendition.next();
          });
        });

        await rendition.display();

        // 异步生成位置索引：进度百分比依赖它（未生成时 epubjs 恒报 0%）；
        // 完成后主动刷新一次当前位置，让进度显示立即修正。
        void book.locations
          ?.generate(1200)
          .then(() => {
            if (!cancelled) setEpubTotal(book.locations?.length?.() ?? null);
            renditionRef.current?.reportLocation?.();
          });

        if (jumpQuote) {
          const jump = await findEpubLocation(book, jumpQuote, jumpHeading);
          if (!cancelled) {
            if (!jump) {
              setJumpStatus("未在正文中匹配到引文，已打开文档开头");
            } else {
              let cfi: string | null = null;
              if (jump.cfi) {
                try {
                  // 注册高亮（渲染时注入）；CFI 由引文 Range 生成
                  rendition.annotations?.highlight?.(jump.cfi, {}, undefined, "sb-jump-hl", {
                    fill: "#ffd54f",
                    "fill-opacity": "0.45",
                  });
                  cfi = jump.cfi;
                } catch {
                  /* 高亮注册失败不阻塞定位 */
                }
              }
              let displayed = false;
              if (cfi) {
                try {
                  await rendition.display(cfi); // 直接翻到引文所在页
                  displayed = true;
                } catch {
                  /* CFI 显示失败则退回章节定位 */
                }
              }
              if (!displayed) await rendition.display(jump.href);
              setJumpStatus(cfi ? "已定位并高亮引文" : "已定位到引文所在章节");
            }
          }
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : "EPUB 渲染失败",
          });
        }
      }
    })();

    return () => {
      cancelled = true;
      renditionRef.current = null;
      epubBookRef.current?.destroy?.();
      epubBookRef.current = null;
    };
  }, [state.kind, doc, jumpQuote, jumpHeading]);

  // EPUB 阅读快捷键：← →（输入框/文本域聚焦时不触发，避免与光标移动冲突）
  useEffect(() => {
    if (state.kind !== "epub") return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowLeft") void renditionRef.current?.prev();
      if (e.key === "ArrowRight") void renditionRef.current?.next();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.kind]);

  /** 按页跳转（2026-10-03）：页码 = locations 索引 + 1（与工具栏显示口径一致），越界钳制。 */
  function jumpToLocation() {
    const n = Math.floor(Number(jumpTo));
    const book = epubBookRef.current;
    if (!n || !epubTotal || !book?.locations?.cfiFromLocation) return;
    const target = Math.min(Math.max(n, 1), epubTotal);
    const cfi = book.locations.cfiFromLocation(target - 1);
    if (cfi) void renditionRef.current?.display(cfi);
    setJumpTo("");
  }

  const pdfSrc =
    state.kind === "pdf"
      ? `/api/documents/${state.id}/original?inline=1${jumpPage ? `#page=${jumpPage}` : ""}`
      : "";

  return (
    <main className="container" style={{ maxWidth: 1000 }}>
      <div className="header">
        <h1
          style={{
            fontSize: 16,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            maxWidth: "60%",
          }}
        >
          {doc ? doc.name : "浏览"}
        </h1>
        <div className="hdr-actions">
          {doc && (
            <a className="btn" href={api.originalUrl(doc.id)} download={doc.name}>
              下载
            </a>
          )}
          <Link className="btn" href={fromChat ? "/chat/" : "/"}>
            {fromChat ? "返回对话" : "返回"}
          </Link>
          <ThemeToggle />
        </div>
      </div>

      {state.kind === "loading" && <p className="muted">加载中…</p>}
      {state.kind === "error" && <p className="error">{state.message}</p>}
      {state.kind === "unsupported" && (
        <div className="card">
          <p>{state.reason}</p>
          <p className="muted">可用右上角「下载」在本地打开。</p>
        </div>
      )}
      {state.kind === "pdf" && (
        <iframe
          src={pdfSrc}
          title="PDF 预览"
          style={{
            width: "100%",
            height: "80vh",
            border: "1px solid var(--border)",
            borderRadius: 12,
            background: "#fff",
          }}
        />
      )}
      {state.kind === "text" && <TextBody content={state.content} q={jumpQuote} />}
      {state.kind === "epub" && (
        <>
          <div className="view-toolbar">
            <button className="btn" onClick={() => void renditionRef.current?.prev()}>
              ← 上一页
            </button>
            <button className="btn" onClick={() => void renditionRef.current?.next()}>
              下一页 →
            </button>
            <span className="muted">
              {epubPage ? `第 ${epubPage.cur}/${epubPage.total} 页 · ` : ""}
              {epubProgress}
            </span>
            {jumpStatus && <span className="muted">· {jumpStatus}</span>}
            {epubTotal ? (
              <span className="muted page-jump">
                跳至
                <input
                  className="page-jump-input"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={epubTotal}
                  value={jumpTo}
                  placeholder={`1-${epubTotal}`}
                  title="输入页码后回车跳转"
                  onChange={(e) => setJumpTo(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      jumpToLocation();
                    }
                  }}
                />
                页
                <button className="btn page-jump-btn" onClick={jumpToLocation}>
                  跳转
                </button>
              </span>
            ) : null}
            <span className="muted view-kbd-hint" style={{ marginLeft: "auto" }}>
              （也可用键盘 ← →）
            </span>
          </div>
          {epubToc && epubToc.length > 0 && (
            <details className="view-toc">
              <summary>目录</summary>
              <div className="toc-box">
                <TocList
                  items={epubToc}
                  onPick={(href) => void renditionRef.current?.display(href)}
                />
              </div>
            </details>
          )}
          <div
            ref={epubRef}
            style={{
              width: "100%",
              height: "76vh",
              border: "1px solid var(--border)",
              borderRadius: 12,
              background: "#fff",
            }}
          />
        </>
      )}
    </main>
  );
}

/** EPUB 目录树（递归渲染，2026-10-03）：点击条目跳转到对应章节。 */
function TocList({ items, onPick }: { items: EpubTocItem[]; onPick: (href: string) => void }) {
  return (
    <ul className="toc-list">
      {items.map((item, i) => (
        <li key={`${item.href ?? "toc"}-${i}`}>
          <button className="toc-item" onClick={() => item.href && onPick(item.href)}>
            {item.label ?? "（未命名）"}
          </button>
          {item.subitems && item.subitems.length > 0 && (
            <TocList items={item.subitems} onPick={onPick} />
          )}
        </li>
      ))}
    </ul>
  );
}
