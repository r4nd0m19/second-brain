import { describe, expect, it } from "vitest";

import {
  contentHash,
  looksLikeChallenge,
  pruneRecent,
  shouldSkipRepeat,
} from "../src/shared/skip";

describe("looksLikeChallenge（反爬验证/拦截页识别）", () => {
  it("识别 DDoS-Guard 验证页（短正文 + 特征）", () => {
    expect(
      looksLikeChallenge(
        "DDoS-Guard",
        "Checking your browser before accessing annas-archive.gd\n\nPlease wait a few seconds."
      )
    ).toBe(true);
  });

  it("识别 Cloudflare 拦截页", () => {
    expect(looksLikeChallenge("Just a moment...", "Enable JavaScript and cookies to continue")).toBe(
      true
    );
  });

  it("长正文中提到这些词不误伤（正常文章远超长度阈值）", () => {
    const long = "本文讨论 Cloudflare 与 DDoS-Guard 的挑战页机制与应对。".repeat(60);
    expect(looksLikeChallenge("反爬机制综述", long)).toBe(false);
  });

  it("正常短页不误伤", () => {
    expect(looksLikeChallenge("今日天气", "晴转多云，26℃")).toBe(false);
  });

  it("标题命中但正文很长也不误伤", () => {
    const long = "正常内容。".repeat(300);
    expect(looksLikeChallenge("Checking your browser — 我的博客", long)).toBe(false);
  });
});

describe("contentHash / shouldSkipRepeat（同 URL 重复采集窗口）", () => {
  const now = 1_000_000_000;

  it("指纹确定性：同内容一致，异内容不同", () => {
    expect(contentHash("t", "abc")).toBe(contentHash("t", "abc"));
    expect(contentHash("t", "abc")).not.toBe(contentHash("t", "abd"));
    expect(contentHash("t1", "abc")).not.toBe(contentHash("t2", "abc"));
  });

  it("同内容且在 10 分钟窗口内 → 跳过", () => {
    const h = contentHash("标题", "正文");
    expect(shouldSkipRepeat({ hash: h, at: now - 60_000 }, h, now)).toBe(true);
  });

  it("窗口外（>10 分钟）→ 不跳过（真实回访重新计数）", () => {
    const h = contentHash("标题", "正文");
    expect(shouldSkipRepeat({ hash: h, at: now - 11 * 60_000 }, h, now)).toBe(false);
  });

  it("内容变化 / 无记录 → 不跳过", () => {
    expect(shouldSkipRepeat({ hash: "other", at: now }, "abc", now)).toBe(false);
    expect(shouldSkipRepeat(undefined, "abc", now)).toBe(false);
  });
});

describe("pruneRecent（指纹表维护）", () => {
  const now = 1_000_000_000;

  it("丢弃过期项（默认 7 天）", () => {
    const map = {
      old: { hash: "1", at: now - 8 * 24 * 60 * 60 * 1000 },
      fresh: { hash: "2", at: now - 1000 },
    };
    expect(Object.keys(pruneRecent(map, now))).toEqual(["fresh"]);
  });

  it("限制条目数（保留最新）", () => {
    const many = Object.fromEntries(
      Array.from({ length: 10 }, (_, i) => [`u${i}`, { hash: `${i}`, at: now - i }])
    );
    const pruned = pruneRecent(many, now, 7 * 24 * 60 * 60 * 1000, 5);
    expect(Object.keys(pruned)).toEqual(["u0", "u1", "u2", "u3", "u4"]);
  });
});
