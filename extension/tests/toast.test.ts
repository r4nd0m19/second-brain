// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { showCaptureDoneToast } from "../src/content/toast";

const HOST_ID = "second-brain-toast-host";

afterEach(() => {
  vi.useRealTimers();
  document.getElementById(HOST_ID)?.remove();
});

describe("showCaptureDoneToast（采集完成反馈）", () => {
  it("展示含快照标记的提示，并在 3 秒后自动消失", () => {
    vi.useFakeTimers();
    showCaptureDoneToast(true);
    const host = document.getElementById(HOST_ID);
    expect(host).not.toBeNull();
    expect(host?.shadowRoot?.textContent).toContain("已存入第二大脑");
    expect(host?.shadowRoot?.textContent).toContain("含页面快照");

    vi.advanceTimersByTime(3_500);
    expect(document.getElementById(HOST_ID)).toBeNull();
  });

  it("仅正文时文案区分", () => {
    showCaptureDoneToast(false);
    expect(document.getElementById(HOST_ID)?.shadowRoot?.textContent).toContain("仅正文");
  });

  it("连续采集只保留一个提示", () => {
    showCaptureDoneToast(false);
    showCaptureDoneToast(false);
    expect(document.querySelectorAll(`#${HOST_ID}`).length).toBe(1);
  });
});
