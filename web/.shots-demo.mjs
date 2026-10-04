// README 演示截图（zh/en 双语；demo / demo-en 账号专用，数据为合成演示集）
// 用法：set -a && . ../server/.env && set +a && DEMO_PASSWORD=… DEMO_EN_PASSWORD=… node .shots-demo.mjs
import { chromium } from "playwright";

const base = "http://127.0.0.1:8000";
const out = "/root/code/second-brain/docs/screenshots";

const LANGS = [
  {
    lang: "zh",
    suffix: "zh",
    user: "demo",
    pass: process.env.DEMO_PASSWORD,
    hero: "HNSW 的 ef_search", // 双来源引用（网页 + 文档）
    mobile: "一致性哈希",
  },
  {
    lang: "en",
    suffix: "en",
    user: "demo-en",
    pass: process.env.DEMO_EN_PASSWORD,
    hero: "How does Raft prevent", // 双来源引用（网页 + 文档）
    mobile: "What problem does consistent",
  },
];

const browser = await chromium.launch();

async function login(ctx, user, pass) {
  const p = await ctx.newPage();
  await p.goto(`${base}/login/`, { waitUntil: "networkidle" });
  await p.locator("input").first().fill(user);
  await p.locator('input[type="password"]').fill(pass);
  await Promise.all([
    p.waitForURL((u) => !u.pathname.includes("login"), { timeout: 15000 }).catch(() => {}),
    p.locator("button.btn-primary").click(),
  ]);
  await p.waitForTimeout(800);
  return p;
}

for (const L of LANGS) {
  const locale = L.lang === "zh" ? "zh-CN" : "en-US";

  // ── 桌面 ──
  const desktop = await browser.newContext({
    viewport: { width: 1280, height: 820 },
    deviceScaleFactor: 2,
    colorScheme: "light",
    locale,
  });
  await desktop.addInitScript((lang) => {
    try {
      localStorage.setItem("sb-lang", lang);
    } catch {}
  }, L.lang);
  const dp = await login(desktop, L.user, L.pass);
  const ids = await dp.evaluate(
    async ([heroPfx, mobilePfx]) => {
      const convs = await (await fetch("/api/conversations")).json();
      // 注意：会话标题在库里截断到 20 字符（英文会切到词中间）→ 前缀匹配只取前 15 字符
      const pick = (pfx) => convs.find((c) => c.title.startsWith(pfx.slice(0, 15)))?.id ?? null;
      return { hero: pick(heroPfx), mobile: pick(mobilePfx) };
    },
    [L.hero, L.mobile],
  );
  console.log(`[${L.suffix}] conv ids:`, JSON.stringify(ids));

  // hero：带引用的回答（展开全部出处）
  await dp.goto(`${base}/chat/?conv=${ids.hero}`, { waitUntil: "networkidle" });
  await dp.waitForTimeout(2000);
  await dp.evaluate(() => document.querySelectorAll(".chat-area details").forEach((d) => (d.open = true)));
  await dp.waitForTimeout(400);
  await dp.screenshot({ path: `${out}/desktop-chat.${L.suffix}.png` });

  // 资料库
  await dp.goto(`${base}/`, { waitUntil: "networkidle" });
  await dp.waitForTimeout(1200);
  await dp.screenshot({ path: `${out}/desktop-library.${L.suffix}.png` });
  await desktop.close();

  // ── 手机 ──
  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    colorScheme: "light",
    locale,
  });
  await mobile.addInitScript((lang) => {
    try {
      localStorage.setItem("sb-lang", lang);
    } catch {}
  }, L.lang);
  const mp = await login(mobile, L.user, L.pass);

  // 手机对话（展开出处）
  await mp.goto(`${base}/chat/?conv=${ids.mobile}`, { waitUntil: "networkidle" });
  await mp.waitForTimeout(2000);
  await mp.evaluate(() => document.querySelectorAll(".chat-area details").forEach((d) => (d.open = true)));
  await mp.waitForTimeout(400);
  await mp.screenshot({ path: `${out}/mobile-chat.${L.suffix}.png` });

  // 会话抽屉
  await mp.locator(".drawer-toggle").click();
  await mp.waitForTimeout(500);
  await mp.screenshot({ path: `${out}/mobile-drawer.${L.suffix}.png` });
  await mp.locator(".drawer-backdrop").click({ position: { x: 370, y: 400 } });
  await mp.waitForTimeout(400);

  // 筛选弹层
  await mp.goto(`${base}/`, { waitUntil: "networkidle" });
  await mp.waitForTimeout(1200);
  await mp.locator(".list-filter-btn").first().click();
  await mp.waitForTimeout(500);
  await mp.screenshot({ path: `${out}/mobile-filter.${L.suffix}.png` });
  await mobile.close();
}

await browser.close();
console.log("done");
