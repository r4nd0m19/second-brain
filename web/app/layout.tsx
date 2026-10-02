import type { Metadata, Viewport } from "next";
import "./globals.css";

import ServiceWorkerRegister from "./_components/sw-register";

export const metadata: Metadata = {
  title: "second-brain",
  description: "你的个人第二大脑 —— 上传、检索、问答",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/icon-192.png",
    apple: "/apple-touch-icon-180.png",
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "second-brain",
  },
};

export const viewport: Viewport = {
  themeColor: "#0f1115",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <script
          // 首屏渲染前应用主题（防闪白/闪黑）：手动选择优先，否则跟随系统；
          // 对话页侧栏收起状态同样先行应用（防首屏闪开）
          dangerouslySetInnerHTML={{
            __html:
              'try{var t=localStorage.getItem("sb-theme"),m=t==="light"||t==="dark"?t:(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;var e=document.querySelector(\'meta[name="theme-color"]\');if(e)e.setAttribute("content",m==="dark"?"#0f1115":"#f6f7f9");if(localStorage.getItem("sb-sidebar")==="0")document.documentElement.dataset.sidebar="off"}catch(e){}',
          }}
        />
        <ServiceWorkerRegister />
        {children}
      </body>
    </html>
  );
}
