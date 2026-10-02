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
    <html lang="zh-CN">
      <body>
        <ServiceWorkerRegister />
        {children}
      </body>
    </html>
  );
}
