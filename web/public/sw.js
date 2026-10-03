// second-brain PWA Service Worker（T029）
// 策略（按资源类型分级，三期 P1 调研对齐 Workbox 惯例）：
//   - /_next/static/*：内容哈希文件名（不可变）→ 缓存优先；
//   - 未哈希静态（图标 / manifest / 字体）：可能原地更新 → stale-while-revalidate（先用缓存、后台刷新）；
//   - /api/* 与页面/HTML：始终走网络（避免旧界面、旧数据）。
// 升级：改动本文件即触发浏览器更新；activate 时清理旧版本缓存。
const STATIC_CACHE = "sb-static-v2";

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

  const isHashed = url.pathname.startsWith("/_next/static/"); // 内容哈希：URL 变则内容变，缓存优先安全

  event.respondWith(
    (async () => {
      const cache = await caches.open(STATIC_CACHE);
      const hit = await cache.match(event.request);

      const network = fetch(event.request)
        .then((res) => {
          if (res.ok) cache.put(event.request, res.clone());
          return res;
        })
        .catch(() => hit); // 离线：有缓存回退

      if (isHashed) return hit ?? network; // 不可变资源：缓存优先
      if (hit) {
        event.waitUntil(network); // SWR：先用缓存，后台拉新（下次生效）
        return hit;
      }
      return network;
    })(),
  );
});
