/** 正文提取（F2 research R1）：Readability（克隆 DOM）为主，defuddle 兜底，最后 body 文本兜底。 */

import { Readability, isProbablyReaderable } from "@mozilla/readability";

export interface Article {
  title: string;
  text: string;
}

/** 正文长度低于此值视为提取失败（返回空文本 → 视配置决定"仅元信息"或跳过） */
export const MIN_TEXT_LENGTH = 200;

/**
 * 等 DOM 静默（SPA 渲染完成信号）：最后一次变更后安静 quietMs，或达到 maxMs 兜底。
 * 实测（2026-10-02）：Upwork 资料页在触发时仍处渲染中，提取到的是导航骨架 →
 * 先等静默再提取；静态页无变更，~quietMs 即返回（不阻塞用户）。
 */
export function waitForDomQuiet(quietMs = 1500, maxMs = 8000): Promise<void> {
  return new Promise((resolve) => {
    let quietTimer: ReturnType<typeof setTimeout> | undefined;
    let done = false;
    const finish = (): void => {
      if (done) return;
      done = true;
      observer.disconnect();
      if (quietTimer !== undefined) clearTimeout(quietTimer);
      clearTimeout(deadline);
      resolve();
    };
    const observer = new MutationObserver(() => {
      if (quietTimer !== undefined) clearTimeout(quietTimer);
      quietTimer = setTimeout(finish, quietMs);
    });
    const deadline = setTimeout(finish, maxMs);
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
    });
    quietTimer = setTimeout(finish, quietMs);
  });
}

export async function extractArticle(): Promise<Article> {
  const clone = document.cloneNode(true) as Document;

  try {
    if (isProbablyReaderable(clone)) {
      const parsed = new Readability(clone).parse();
      const text = parsed?.textContent?.trim() ?? "";
      if (text.length >= MIN_TEXT_LENGTH) {
        return { title: parsed?.title?.trim() || document.title, text };
      }
    }
  } catch {
    /* 继续走兜底 */
  }

  try {
    const fallback = await defuddleFallback();
    if (fallback.text.length >= MIN_TEXT_LENGTH) return fallback;
  } catch {
    /* 继续走兜底 */
  }

  const bodyText = (document.body?.innerText ?? "").trim();
  return { title: document.title, text: bodyText.length >= MIN_TEXT_LENGTH ? bodyText : "" };
}

async function defuddleFallback(): Promise<Article> {
  const mod: Record<string, unknown> = (await import("defuddle")) as Record<string, unknown>;
  const Defuddle = (mod.Defuddle ?? mod.default) as
    | (new (doc: Document) => { parse(): Promise<{ content?: string; title?: string }> })
    | undefined;
  if (!Defuddle) throw new Error("defuddle 不可用");
  const result = await new Defuddle(document.cloneNode(true) as Document).parse();
  return {
    title: result?.title?.trim() || document.title,
    text: (result?.content ?? "").trim(),
  };
}
