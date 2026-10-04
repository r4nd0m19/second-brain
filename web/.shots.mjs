import { chromium } from "playwright";

const base = "http://127.0.0.1:8000";
const user = process.env.ADMIN_USERNAME;
const pass = process.env.ADMIN_PASSWORD;
const out = "/tmp/shots";

const browser = await chromium.launch();

// 登录页（匿名）
const anon = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
const ap = await anon.newPage();
await ap.goto(`${base}/login/`, { waitUntil: "networkidle" });
await ap.screenshot({ path: `${out}/m-login.png` });
await anon.close();

const ctx = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  colorScheme: "light",
  locale: "zh-CN",
});
const page = await ctx.newPage();
await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
await page.locator("input").first().fill(user);
await page.locator('input[type="password"]').fill(pass);
await Promise.all([
  page.waitForURL((u) => !u.pathname.includes("login"), { timeout: 15000 }).catch(() => {}),
  page.locator("button.btn-primary").click(),
]);
await page.waitForTimeout(800);

// 探测：可读的上传文档 / 浏览文档 / 会话
const meta = await page.evaluate(async () => {
  const j = async (u) => (await fetch(u)).json();
  const up = await j("/api/documents?page_size=30");
  const br = await j("/api/documents?source=browser&page_size=10");
  let convs = await j("/api/conversations");
  if (!Array.isArray(convs)) convs = convs.items || convs.conversations || [];
  const readable = (up.items || []).find((d) => d.status === "indexed") || (up.items || [])[0];
  return {
    uploadId: readable?.id ?? null,
    browserId: (br.items || [])[0]?.id ?? null,
    convId: convs[0]?.id ?? null,
  };
});
console.log("meta:", JSON.stringify(meta));

// 资料页（整页：上传来源）
await page.goto(`${base}/`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await page.screenshot({ path: `${out}/m-docs.png`, fullPage: true });

// 浏览来源（含时间筛选行）
await page
  .getByRole("button", { name: /Browsing|浏览/ })
  .first()
  .click()
  .catch(() => {});
await page.waitForTimeout(900);
await page.screenshot({ path: `${out}/m-docs-browser.png`, fullPage: true });

if (meta.convId) {
  await page.goto(`${base}/chat/?conv=${meta.convId}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${out}/m-chat.png` });
}
if (meta.uploadId) {
  await page.goto(`${base}/view/?id=${meta.uploadId}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${out}/m-view.png` });
}
if (meta.browserId) {
  await page.goto(`${base}/snap/?id=${meta.browserId}&from=chat`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${out}/m-snap.png` });
}
await browser.close();
console.log("done");
