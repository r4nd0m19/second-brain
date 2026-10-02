/**
 * 页面内"采集完成"提示（F2 FR-008 增强）：
 * Shadow DOM 隔离（不污染页面样式）、pointer-events: none（不挡任何交互）、
 * 3 秒自动淡出——满足"可见反馈"且不违背"浏览无可感影响"。
 */

const HOST_ID = "second-brain-toast-host";
const DISPLAY_MS = 3000;

export function showCaptureDoneToast(withSnapshot: boolean): void {
  document.getElementById(HOST_ID)?.remove(); // 连续采集：只保留最新提示

  const host = document.createElement("div");
  host.id = HOST_ID;
  const shadow = host.attachShadow({ mode: "open" });
  const box = document.createElement("div");
  box.textContent = `✓ 已存入第二大脑${withSnapshot ? "（含页面快照）" : "（仅正文）"}`;
  box.style.cssText = [
    "position: fixed",
    "right: 16px",
    "bottom: 16px",
    "z-index: 2147483647",
    "max-width: 320px",
    "background: rgba(30, 41, 59, 0.92)",
    "color: #fff",
    "font: 13px/1.4 system-ui, sans-serif",
    "padding: 10px 14px",
    "border-radius: 8px",
    "box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25)",
    "pointer-events: none",
    "opacity: 1",
    "transition: opacity 0.3s ease",
  ].join(";");
  shadow.appendChild(box);
  document.documentElement.appendChild(host);

  setTimeout(() => {
    box.style.opacity = "0";
    setTimeout(() => host.remove(), 350);
  }, DISPLAY_MS);
}
