"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

/** 实测顶栏（.header）吸顶高度 → CSS 变量 `--hdr-h`。
 *
 * 其下吸顶元素（资料页页签行 / 对话页侧栏 / 阅读页工具栏）以 `top: var(--hdr-h)` 对位停靠；
 * 实测而非写死：移动端顶栏换行、字号变化时自动跟随（ResizeObserver），路由切换重挂。
 */
export default function HeaderOffset() {
  const pathname = usePathname();
  useEffect(() => {
    const header = document.querySelector<HTMLElement>(".header");
    if (!header) return;
    const set = () =>
      document.documentElement.style.setProperty("--hdr-h", `${header.offsetHeight}px`);
    set();
    const observer = new ResizeObserver(set);
    observer.observe(header);
    return () => observer.disconnect();
  }, [pathname]);
  return null;
}
