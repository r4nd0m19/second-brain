import { describe, expect, it } from "vitest";

import { isBlocked } from "../src/shared/block";

describe("isBlocked（黑名单：域名 + 子域语义）", () => {
  it("精确域名命中", () => {
    expect(isBlocked("example.com", ["example.com"])).toBe(true);
  });

  it("子域命中（含 . 前缀写法）", () => {
    expect(isBlocked("mail.example.com", ["example.com"])).toBe(true);
    expect(isBlocked("mail.example.com", [".example.com"])).toBe(true);
  });

  it("相似后缀不误伤", () => {
    expect(isBlocked("notexample.com", ["example.com"])).toBe(false);
    expect(isBlocked("example.com.evil.net", ["example.com"])).toBe(false);
  });

  it("大小写与空条目容错", () => {
    expect(isBlocked("Example.COM", [" EXAMPLE.com "])).toBe(true);
    expect(isBlocked("a.com", ["", "  "])).toBe(false);
  });

  it("拿不到 host 时保守拦截", () => {
    expect(isBlocked("", [])).toBe(true);
  });
});
