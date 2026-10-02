import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node", // DOM 相关用例在文件头用 @vitest-environment jsdom 声明
  },
});
