/** single-file-core 无内置类型且无 package exports 字段——补子路径模块声明。 */

declare module "single-file-core/single-file.js" {
  export function getPageData(
    options?: Record<string, unknown>,
    initOptions?: Record<string, unknown>,
    doc?: Document,
    win?: Window & typeof globalThis
  ): Promise<{ content?: string; title?: string; filename?: string }>;

  export function init(initOptions?: Record<string, unknown>): void;
}
