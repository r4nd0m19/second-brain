// 构建脚本：esbuild 打包 MV3 各入口 → extension/dist，并拷贝静态文件（manifest/HTML）。
// 用法：npm run build（或 npm run watch）
import { build, context } from "esbuild";
import { cpSync } from "node:fs";

const watch = process.argv.includes("--watch");

// 静态文件原样拷贝（manifest 在扩展根，HTML 在各自目录）
const staticFiles = [
  ["manifest.json", "dist/manifest.json"],
  ["src/options/options.html", "dist/options.html"],
  ["src/popup/popup.html", "dist/popup.html"],
];
for (const [from, to] of staticFiles) cpSync(from, to);

const common = {
  bundle: true,
  outdir: "dist",
  sourcemap: true,
  target: "chrome120",
  logLevel: "info",
  charset: "utf8", // 中文日志/文案保持可读（默认转义为 \uXXXX）
};

// 入口：SW 与页面用 ESM；内容脚本必须 IIFE（内容脚本无 module 语义）
const builds = [
  { entryPoints: [{ in: "src/background/index.ts", out: "background" }], format: "esm" },
  { entryPoints: [{ in: "src/content/index.ts", out: "content" }], format: "iife" },
  { entryPoints: [{ in: "src/options/index.ts", out: "options" }], format: "esm" },
  { entryPoints: [{ in: "src/popup/index.ts", out: "popup" }], format: "esm" },
];

if (watch) {
  for (const b of builds) {
    const ctx = await context({ ...common, ...b });
    await ctx.watch();
  }
  console.log("[build] watching…");
} else {
  await Promise.all(builds.map((b) => build({ ...common, ...b })));
  console.log("[build] dist ready");
}
