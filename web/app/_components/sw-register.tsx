"use client";

import { useEffect } from "react";

/** 注册 PWA Service Worker（T029）：仅浏览器环境执行，失败静默（不影响使用）。 */
export default function ServiceWorkerRegister() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);
  return null;
}
