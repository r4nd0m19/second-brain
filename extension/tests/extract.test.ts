// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { waitForDomQuiet } from "../src/content/extract";

describe("waitForDomQuiet（SPA 渲染稳定信号）", () => {
  it("无变更：约 quietMs 后返回", async () => {
    const t0 = Date.now();
    await waitForDomQuiet(200, 3000);
    const elapsed = Date.now() - t0;
    expect(elapsed).toBeGreaterThanOrEqual(150);
    expect(elapsed).toBeLessThan(900);
  });

  it("持续变更：静默后才返回（不早退）", async () => {
    const t0 = Date.now();
    const timer = setInterval(() => {
      document.body.appendChild(document.createElement("div"));
    }, 80);
    setTimeout(() => clearInterval(timer), 500);
    await waitForDomQuiet(250, 5000);
    const elapsed = Date.now() - t0;
    expect(elapsed).toBeGreaterThanOrEqual(700); // ≈500ms 变更 + 250ms 静默
    expect(elapsed).toBeLessThan(3000);
  });

  it("持续变更到上限：maxMs 兜底返回", async () => {
    const t0 = Date.now();
    const timer = setInterval(() => {
      document.body.appendChild(document.createElement("div"));
    }, 50);
    await waitForDomQuiet(500, 1000);
    clearInterval(timer);
    const elapsed = Date.now() - t0;
    expect(elapsed).toBeGreaterThanOrEqual(900);
    expect(elapsed).toBeLessThan(2500);
  });
});
