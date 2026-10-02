// second-brain PWA Service Worker（T029）
// 策略：静态资源（_next/static、图标、字体）缓存优先；API 与页面导航始终走网络（避免旧界面）。
// 升级：改动本文件即触发浏览器更新；activate 时清理旧版本缓存。
const STATIC_CACHE = "sb-static-v1";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      await self.clients.claim();
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => k.startsWith("sb-static-") && k !== STATIC_CACHE)
          .map((k) => caches.delete(k)),
      );
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // API 永不缓存（含 SSE）
  const isStatic =
    url.pathname.startsWith("/_next/static/") ||
    /\.(png|svg|ico|webmanifest|woff2?|ttf)$/.test(url.pathname);
  if (!isStatic) return; // 页面/HTML 走网络（保证拿到最新界面）

  event.respondWith(
    (async () => {
      const cache = await caches.open(STATIC_CACHE);
      const hit = await cache.match(event.request);
      if (hit) return hit;
      const res = await fetch(event.request);
      if (res.ok) cache.put(event.request, res.clone());
      return res;
    })(),
  );
});
