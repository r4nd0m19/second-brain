import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "second-brain",
  description: "你的个人第二大脑 —— 上传、检索、问答",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
