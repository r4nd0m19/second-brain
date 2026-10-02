import { describe, expect, it } from "vitest";

import { DEFAULT_TRIGGER, ReadingMeter, scrollRatio } from "../src/shared/trigger";

describe("ReadingMeter", () => {
  it("只累计可见时间的停留（隐藏暂停）", () => {
    const meter = new ReadingMeter();
    meter.tick(1_000, true); // 建立基线
    meter.tick(4_000, true); // +3s
    meter.tick(20_000, false); // 隐藏：不计
    meter.tick(21_000, true); // +1s
    expect(meter.state.visibleSeconds).toBeCloseTo(4, 5);
  });

  it("达到停留或滚动任一阈值即触发", () => {
    const byTime = new ReadingMeter({ minVisibleSeconds: 10, minScrollRatio: 0.5 });
    byTime.tick(0, true);
    byTime.tick(9_000, true);
    expect(byTime.reached()).toBe(false);
    byTime.tick(10_000, true);
    expect(byTime.reached()).toBe(true);

    const byScroll = new ReadingMeter({ minVisibleSeconds: 10, minScrollRatio: 0.5 });
    byScroll.setScrollRatio(0.4);
    expect(byScroll.reached()).toBe(false);
    byScroll.setScrollRatio(0.5);
    expect(byScroll.reached()).toBe(true);
  });

  it("reset 清零（SPA 路由切换）", () => {
    const meter = new ReadingMeter();
    meter.tick(0, true);
    meter.tick(60_000, true);
    meter.setScrollRatio(1);
    meter.reset();
    expect(meter.reached()).toBe(false);
    expect(meter.state.visibleSeconds).toBe(0);
    expect(meter.state.scrollRatio).toBe(0);
  });

  it("阈值可配置；默认 10s / 50%", () => {
    const meter = new ReadingMeter({ minVisibleSeconds: 1, minScrollRatio: 0.9 });
    meter.tick(0, true);
    meter.tick(1_000, true);
    expect(meter.reached()).toBe(true);
    expect(DEFAULT_TRIGGER.minVisibleSeconds).toBe(10);
    expect(DEFAULT_TRIGGER.minScrollRatio).toBe(0.5);
  });
});

describe("scrollRatio", () => {
  it("无滚动条（一屏读完）视为 100%", () => {
    expect(scrollRatio(0, 800, 800)).toBe(1);
  });

  it("常规滚动比例 = (已滚 + 视口) / 全文", () => {
    expect(scrollRatio(400, 800, 2_000)).toBeCloseTo(0.6, 5);
  });

  it("封顶 1", () => {
    expect(scrollRatio(2_000, 800, 2_000)).toBe(1);
  });
});
