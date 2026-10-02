/** 阅读触发判定（F2 FR-002）：可见停留累计 + 最大滚动深度；纯逻辑，可单测。 */

export interface TriggerConfig {
  /** 可见停留阈值（秒） */
  minVisibleSeconds: number;
  /** 滚动深度阈值（0–1） */
  minScrollRatio: number;
}

export const DEFAULT_TRIGGER: TriggerConfig = { minVisibleSeconds: 10, minScrollRatio: 0.5 };

export class ReadingMeter {
  private visibleSeconds = 0;
  private scrollDepth = 0;
  private lastTickMs: number | null = null;

  constructor(private config: TriggerConfig = DEFAULT_TRIGGER) {}

  /** 按时间戳累计"可见"停留；隐藏期间只推进基线、不累计。 */
  tick(nowMs: number, visible: boolean): void {
    if (this.lastTickMs !== null && visible) {
      this.visibleSeconds += Math.max(0, nowMs - this.lastTickMs) / 1000;
    }
    this.lastTickMs = nowMs;
  }

  setScrollRatio(ratio: number): void {
    this.scrollDepth = Math.max(this.scrollDepth, Math.min(1, Math.max(0, ratio)));
  }

  reached(): boolean {
    return (
      this.visibleSeconds >= this.config.minVisibleSeconds ||
      this.scrollDepth >= this.config.minScrollRatio
    );
  }

  reset(): void {
    this.visibleSeconds = 0;
    this.scrollDepth = 0;
    this.lastTickMs = null;
  }

  get state(): { visibleSeconds: number; scrollRatio: number } {
    return { visibleSeconds: this.visibleSeconds, scrollRatio: this.scrollDepth };
  }
}

/** 滚动深度 = (已滚 + 视口) / 全高；无滚动条视为 100%（一屏读完）。 */
export function scrollRatio(scrollTop: number, viewportHeight: number, docHeight: number): number {
  if (docHeight <= viewportHeight) return 1;
  return Math.min(1, (scrollTop + viewportHeight) / docHeight);
}
