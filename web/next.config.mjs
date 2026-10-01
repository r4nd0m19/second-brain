/** @type {import('next').NextConfig} */
const nextConfig = {
  // 静态导出：产物交 FastAPI 托管（单进程部署 —— plan「架构选择」）
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
