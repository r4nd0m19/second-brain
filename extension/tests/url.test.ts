import { describe, expect, it } from "vitest";

import { hostOf, isLoopbackHost, normalizeUrl } from "../src/shared/url";

describe("normalizeUrl（与服务端一致：去 fragment、保留 query、host 小写）", () => {
  it("去 fragment", () => {
    expect(normalizeUrl("https://example.com/a?b=1#sec")).toBe("https://example.com/a?b=1");
  });

  it("保留 query；默认端口折叠；host 小写", () => {
    expect(normalizeUrl("https://Example.com:443/x?q=1")).toBe("https://example.com/x?q=1");
  });

  it("空路径补 '/'", () => {
    expect(normalizeUrl("https://example.com")).toBe("https://example.com/");
  });
});

describe("hostOf", () => {
  it("取小写 hostname", () => {
    expect(hostOf("https://Sub.Example.com/path")).toBe("sub.example.com");
  });
});

describe("isLoopbackHost（本机页面默认不采集）", () => {
  it("识别 localhost / 回环", () => {
    expect(isLoopbackHost("localhost")).toBe(true);
    expect(isLoopbackHost("127.0.0.1")).toBe(true);
    expect(isLoopbackHost("[::1]")).toBe(true);
    expect(isLoopbackHost("docs.localhost")).toBe(true);
  });

  it("公网域名不误判", () => {
    expect(isLoopbackHost("example.com")).toBe(false);
    expect(isLoopbackHost("localhost.example.com")).toBe(false);
  });
});
