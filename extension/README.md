# 浏览器采集扩展（Chrome / Edge，MV3）

按"阅读行为"（停留/滚动阈值）自动采集你正在读的网页 → 快照 + 正文入库（browser 来源）。

完整安装与配置教程（构建 → 开发者模式加载 → 生成采集凭据 → 填服务器地址并测试）：

- 中文：[../README.ch.md →「浏览器扩展」](../README.ch.md)
- English: [../README.md → "Browser extension"](../README.md)

速览：

```bash
npm install && npm run build   # 产物 dist/ → chrome://extensions 开发者模式「加载已解压的扩展程序」
```

⚠️ 服务器地址仅接受 **https** 或**本机回环 http**（`http://localhost:8000`）——明文公网/局域网 http 会被拒绝（安全设计）。

日常控制：弹窗一键暂停 / 队列与今日计数；设置页维护黑名单与触发阈值；采集凭据在应用「资料页 → 浏览器采集」卡片生成（仅显示一次，可吊销）。

开发：`npm test`（vitest）；`npm run build`（esbuild 打包）。
