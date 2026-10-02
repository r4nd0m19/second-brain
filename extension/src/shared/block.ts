/** 黑名单匹配（F2 FR-004）：域名级 + 子域语义；纯逻辑，可单测。 */

export function isBlocked(host: string, blocklist: string[]): boolean {
  const target = host.trim().toLowerCase();
  if (!target) return true; // 拿不到 host 的（如浏览器内部页）一律不采
  return blocklist.some((item) => {
    const domain = item.trim().toLowerCase().replace(/^\.+/, "");
    if (!domain) return false;
    return target === domain || target.endsWith(`.${domain}`);
  });
}
