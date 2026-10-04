"use client";

/**
 * 轻量中英切换（2026-10-03）：文案表 + Context + `useLang()`，零第三方依赖。
 *
 * - 默认跟随浏览器语言（`navigator.language`），手动切换后 localStorage 记忆（键 sb-lang）
 * - 与主题/侧栏同套机制：挂载后同步（静态导出无服务端语言路由，首帧为默认中文）
 * - 范围：界面文案；回答内容（模型按提问语言作答）与后端错误消息不在内
 * - 新增文案：在 `zh` 与 `en` 同时加键（en 与 zh 键不一致会类型报错）
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Lang = "zh" | "en";

const STORAGE_KEY = "sb-lang";

const zh = {
  // ── 通用 ──
  "common.page": "（第 {page} 页）",
  "common.cancel": "取消",
  "common.requestFailed": "请求失败（{status}）",
  "common.unauthorized": "未登录",
  "common.uploadParseFailed": "上传响应解析失败",
  "common.uploadFailed": "上传失败（{status}）",
  "common.uploadNetworkError": "上传网络错误",

  // ── 日期选择 ──
  "date.pick": "选择日期",
  "date.clear": "清除",

  // ── 主题 / 语言切换 ──
  "toggle.toLight": "切换到白天模式",
  "toggle.toDark": "切换到夜间模式",
  "toggle.toEnglish": "切换到英文",
  "toggle.toChinese": "切换到中文",

  // ── 列表工具条 / 分页 ──
  "list.searchPlaceholder": "搜索标题 / 站点 / 正文…",
  "list.sortDescTitle": "当前：降序（点击切升序）",
  "list.sortAscTitle": "当前：升序（点击切降序）",
  "list.toAsc": "切换为升序",
  "list.toDesc": "切换为降序",
  "list.updating": "更新中…",
  "list.count": "共 {total} 条",
  "list.prev": "‹ 上一页",
  "list.next": "下一页 ›",
  "list.pageOf": "第 {page}/{totalPages} 页",
  "list.filter": "筛选",
  "list.filterTitle": "筛选与排序",
  "list.sortSection": "排序方式",
  "list.dirSection": "排序方向",
  "list.asc": "升序",
  "list.desc": "降序",
  "list.done": "完成",

  // ── 快照页 ──
  "snap.backToChat": "返回对话",
  "snap.backToBrowsing": "返回浏览记录",
  "snap.backToLibrary": "返回资料库",
  "snap.missingParam": "缺少条目参数",
  "snap.loadFailed": "加载失败",
  "snap.title": "页面快照",
  "snap.visitedAt": " · 浏览于 {time}",
  "snap.openOriginal": "打开原文 ↗",
  "snap.loading": "加载中…",

  // ── 登录页 ──
  "login.failed": "登录失败",
  "login.hint": "登录你的第二大脑",
  "login.username": "用户名",
  "login.password": "密码",
  "login.submitting": "登录中…",
  "login.submit": "登录",

  // ── 资料库 / 浏览记录页 ──
  "docs.navChat": "对话",
  "docs.logout": "退出",
  "docs.loading": "加载中…",
  "docs.storageLine": "存储占用：数据库 {db} · 文件 {files}",
  "docs.storageSnapshots": "（快照 {size} / {count} 个）",
  "docs.storageCounts": " · 资料 {uploads} 篇 / 浏览 {browsing} 条 / 对话回写 {conv} 条",
  "docs.tabUpload": "上传资料",
  "docs.tabBrowser": "浏览记录",
  "docs.uploadHint": "上传资料（PDF / EPUB / TXT / Markdown / DOCX 等）—— 解析入库后即可检索问答。",
  "docs.chooseFile": "选择文件上传",
  "docs.uploading": "上传中：{name}",
  "docs.uploadPct": "（{pct}%）",
  "docs.dupFile": "已存在相同文件（{name}），未重复入库",
  "docs.uploaded": "已上传：{name}，正在后台解析入库…",
  "docs.uploadFailed": "上传失败",
  "docs.statusProcessing": "处理中",
  "docs.statusIndexed": "已入库",
  "docs.statusUnparseable": "无法解析",
  "docs.sortUploadedAt": "上传时间",
  "docs.sortName": "文件名",
  "docs.sortSize": "大小",
  "docs.sortLastVisited": "最近浏览",
  "docs.sortFirstCapture": "首次采集",
  "docs.sortVisits": "浏览次数",
  "docs.sortTitle": "标题",
  "docs.emptyDocs": "还没有资料 —— 上传第一本书吧",
  "docs.emptyBrowser": "还没有浏览记录 —— 安装扩展后浏览网页即自动出现",
  "docs.noMatchDocs": "没有匹配「{q}」的资料",
  "docs.noMatchBrowser": "没有匹配「{q}」的浏览记录",
  "docs.size": "大小 {size}",
  "docs.contentSize": "正文 {size}",
  "docs.snapshotSize": " · 快照 {size}",
  "docs.contentHit": "正文命中：{snippet}",
  "docs.urlHit": "站点/网址命中",
  "docs.deepParse": "深度解析",
  "docs.view": "浏览",
  "docs.retry": "重试",
  "docs.download": "下载",
  "docs.delete": "删除",
  "docs.revoke": "吊销",
  "docs.viewSnapshot": "查看快照",
  "docs.openOriginal": "打开原文",
  "docs.deleteConfirm": "确定删除「{name}」？{extra}",
  "docs.deleteExtraBrowser": "\n包含网页快照，删除后检索与出处同步消失。",
  "docs.deleteExtraUpload": "\n包含原文件，删除后不可恢复。",
  "docs.deleteFailed": "删除失败",
  "docs.retryFailed": "重试失败",
  "docs.collectTitle": "浏览器采集",
  "docs.collectHint1": "在 Chrome / Edge 扩展设置中填入服务器地址与下方凭据，浏览过的网页会",
  "docs.collectHintBold": "自动",
  "docs.collectHint2": "入库（可在扩展弹窗一键暂停、在扩展设置维护黑名单）。凭据仅用于采集写入，可随时吊销。",
  "docs.tokensSummary": "采集凭据（{state}）",
  "docs.tokensNone": "未创建",
  "docs.tokensActive": "{n} 个有效",
  "docs.tokensRevoked": " · {n} 个已吊销",
  "docs.newToken1": "新凭据（",
  "docs.newTokenBold": "只显示这一次",
  "docs.newToken2": "，请立即复制到扩展设置）：",
  "docs.copy": "复制",
  "docs.saved": "我已保存",
  "docs.tokenNamePlaceholder": "凭据名称（如 Windows Chrome）",
  "docs.tokenScopeTitle": "凭据用途",
  "docs.scopeCapture": "采集",
  "docs.scopeRead": "只读",
  "docs.scopeWrite": "只读+写入",
  "docs.scopeCaptureOpt": "采集写入（浏览器扩展）",
  "docs.scopeReadOpt": "只读（MCP / Claude Code）",
  "docs.scopeWriteOpt": "只读+写入（MCP 可回存笔记）",
  "docs.createToken": "生成凭据",
  "docs.tokenMeta": "{scope} · {prefix}… · 最近使用 {time}",
  "docs.revoked": "已吊销",
  "docs.active": "有效",
  "docs.hideRevoked": "隐藏已吊销",
  "docs.showRevoked": "显示已吊销（{n}）",
  "docs.revokeConfirm": "吊销凭据「{name}」（{prefix}…）？使用它的扩展将立即失效。",
  "docs.purgeConfirm": "彻底删除凭据「{name}」（{prefix}…）？删除后不可恢复。",
  "docs.tokenCreateFailed": "创建凭据失败",
  "docs.tokenRevokeFailed": "吊销失败",
  "docs.cleanupTitle": "按时间清理浏览记录",
  "docs.cleanupStart": "开始",
  "docs.cleanupEnd": "结束",
  "docs.cleanup": "清理",
  "docs.cleanupHint": "按「最近浏览时间」过滤；删除包含正文与快照，检索与出处同步消失。",
  "docs.cleanupNeedDate": "请至少选择开始或结束日期",
  "docs.cleanupEarliest": "最早",
  "docs.cleanupNow": "现在",
  "docs.cleanupConfirm": "删除该时间范围内浏览过的全部网页（含快照，不可恢复）？\n范围：{range}",
  "docs.cleanupDone": "已清理 {n} 条浏览记录",
  "docs.cleanupFailed": "清理失败",
  "docs.browserMeta": "{site} · 浏览于 {time}（共 {n} 次）",
  "docs.snapOversize": "快照未保留（超出体积上限），仅正文可检索",
  "docs.snapFailed": "快照生成失败，仅正文可检索",

  // ── 阅读器页 ──
  "view.title": "浏览",
  "view.back": "返回",
  "view.missingId": "缺少文件参数（?id=）",
  "view.readFailed": "读取失败（{status}）",
  "view.unsupported": "暂不支持在线浏览 .{format} 格式",
  "view.unsupportedHint": "可用右上角「下载」在本地打开。",
  "view.deleted": "该资料不存在或已被删除（来源已删除）",
  "view.loadFailed": "加载失败",
  "view.epubFailed": "EPUB 渲染失败",
  "view.pdfPreview": "PDF 预览",
  "view.prevPage": "← 上一页",
  "view.nextPage": "下一页 →",
  "view.pageOf": "第 {cur}/{total} 页",
  "view.jumpTo": "跳至",
  "view.page": "页",
  "view.jump": "跳转",
  "view.jumpTitle": "输入页码后回车跳转",
  "view.kbdHint": "（也可用键盘 ← →）",
  "view.toc": "目录",
  "view.untitled": "（未命名）",
  "view.quoteNoMatch": "未在正文中匹配到引文，已打开文档开头",
  "view.quoteLocated": "已定位并高亮引文",
  "view.quoteSection": "已定位到引文所在章节",

  // ── 对话页 ──
  "chat.title": "second-brain · 对话",
  "chat.navLibrary": "资料",
  "chat.toggleExpand": "展开对话列表",
  "chat.toggleCollapse": "收起对话列表",
  "chat.toggleTitle": "收起 / 展开对话列表（Ctrl+B）",
  "chat.newChat": "＋ 新对话",
  "chat.searchPlaceholder": "搜索对话（全文）…",
  "chat.searching": "搜索中…",
  "chat.searchHits": "{total} 个会话命中",
  "chat.hitCount": "{n} 处命中 · ",
  "chat.noMatch": "没有匹配的对话",
  "chat.deleteConvTitle": "删除对话",
  "chat.deleteConvConfirm": "删除这个对话？（连同其回写入库的内容，不可恢复）",
  "chat.noConversations": "暂无历史对话",
  "chat.emptyTitle": "向你的第二大脑提问吧",
  "chat.emptyHint": "你的资料、浏览过的网页与历史对话都会被检索并引用",
  "chat.suggest1": "我的资料里是如何定义「架构决策」的？",
  "chat.suggest2": "我最近 3 天看过哪些网页？",
  "chat.suggest3": "上周看过的文章里关于 AI 的内容有哪些？",
  "chat.sourcePrefix": "来源：{label}",
  "chat.sourceKb": "来自你的资料",
  "chat.sourceModel": "来自模型知识",
  "chat.sourcePrior": "来自既往对话",
  "chat.sourceWeb": "来自网络",
  "chat.webFailed": "（联网检索失败，未使用网络来源）",
  "chat.webFailedReason": "（联网检索失败：{reason}，未使用网络来源）",
  "chat.webErrBalance": "供应商账户余额不足",
  "chat.webErrRate": "请求被限流",
  "chat.webErrQuota": "今日联网额度已用尽",
  "chat.webErrUnavailable": "服务不可用",
  "chat.webNoResults": "（联网检索未找到相关结果，未使用网络来源）",
  "chat.timeRange": "🕐 检索时间范围：{label}",
  "chat.cacheHit": " · 缓存命中 {n}",
  "chat.costLlm": "模型",
  "chat.costWeb": "联网",
  "chat.costRetrieval": "检索",
  "chat.citationsWeb": "网络来源",
  "chat.citationsLocal": "出处",
  "chat.citationsDefault": "来源",
  "chat.citationCount": "{label}：{count} 条",
  "chat.related": "库中可能相关",
  "chat.inherited": "原文出处",
  "chat.inlineWebTag": " · 网页",
  "chat.inlineVisitedAt": " · 浏览于 {time}",
  "chat.openWeb": "↗ 打开网页",
  "chat.viewSnapshot": "🖼 查看快照",
  "chat.backToConv": "↩ 回到原对话",
  "chat.previewOpenFull": "↗ 在对话中打开",
  "chat.previewClose": "关闭",
  "chat.jumpToSource": "↗ 跳到原文位置",
  "chat.openOriginal": "↗ 打开原文",
  "chat.webNoQuote": "此来源没有可展示的原文摘录——可点「↗ 打开原文」查看",
  "chat.thinkingLive": "思考中…",
  "chat.thinkingDone": "已思考 {s}s · 点开查看",
  "chat.copied": "✓ 已复制",
  "chat.copy": "⧉ 复制",
  "chat.sendFailed": "发送失败",
  "chat.requestFailed": "请求失败（{status}）",
  "chat.inputPlaceholder": "给第二大脑发消息…",
  "chat.answering": "回答中…",
  "chat.phasePlanning": "正在理解问题、规划检索…",
  "chat.phaseRetrieving": "正在检索资料库…",
  "chat.phaseListing": "正在查询浏览记录…",
  "chat.phaseExpanding": "首次未命中，正在换角度检索…",
  "chat.phaseWeb": "正在联网搜索…",
  "chat.phaseGenerating": "正在生成回答…",
  "chat.streamChars": "已输出 {n} 字",
  "chat.stop": "停止生成",
  "chat.streamInterrupted": "连接中断，回答可能不完整",
  "chat.streamTimeout": "长时间无响应，已停止（回答可能不完整）",
  "chat.sendTitle": "发送（Enter）",
  "chat.send": "发送",
  "chat.composerHint": "回答可能有误，请以出处为准 · Enter 发送，Shift+Enter 换行",
} as const;

const en: Record<keyof typeof zh, string> = {
  // ── Common ──
  "common.page": " (p. {page})",
  "common.cancel": "Cancel",
  "common.requestFailed": "Request failed ({status})",
  "common.unauthorized": "Not signed in",
  "common.uploadParseFailed": "Failed to parse upload response",
  "common.uploadFailed": "Upload failed ({status})",
  "common.uploadNetworkError": "Upload network error",

  // ── Date picker ──
  "date.pick": "Pick a date",
  "date.clear": "Clear",

  // ── Theme / language toggle ──
  "toggle.toLight": "Switch to light mode",
  "toggle.toDark": "Switch to dark mode",
  "toggle.toEnglish": "Switch to English",
  "toggle.toChinese": "Switch to Chinese",

  // ── List toolbar / pagination ──
  "list.searchPlaceholder": "Search title / site / content…",
  "list.sortDescTitle": "Currently descending (click for ascending)",
  "list.sortAscTitle": "Currently ascending (click for descending)",
  "list.toAsc": "Switch to ascending",
  "list.toDesc": "Switch to descending",
  "list.updating": "Updating…",
  "list.count": "{total} items",
  "list.prev": "‹ Prev",
  "list.next": "Next ›",
  "list.pageOf": "Page {page}/{totalPages}",
  "list.filter": "Filter",
  "list.filterTitle": "Filter & sort",
  "list.sortSection": "Sort by",
  "list.dirSection": "Direction",
  "list.asc": "Ascending",
  "list.desc": "Descending",
  "list.done": "Done",

  // ── Snapshot page ──
  "snap.backToChat": "Back to chat",
  "snap.backToBrowsing": "Back to browsing",
  "snap.backToLibrary": "Back to library",
  "snap.missingParam": "Missing item parameter",
  "snap.loadFailed": "Failed to load",
  "snap.title": "Page snapshot",
  "snap.visitedAt": " · visited {time}",
  "snap.openOriginal": "Open original ↗",
  "snap.loading": "Loading…",

  // ── Login page ──
  "login.failed": "Login failed",
  "login.hint": "Sign in to your second brain",
  "login.username": "Username",
  "login.password": "Password",
  "login.submitting": "Signing in…",
  "login.submit": "Sign in",

  // ── Library / browsing ──
  "docs.navChat": "Chat",
  "docs.logout": "Log out",
  "docs.loading": "Loading…",
  "docs.storageLine": "Storage: database {db} · files {files}",
  "docs.storageSnapshots": " (snapshots {size} / {count})",
  "docs.storageCounts": " · {uploads} documents / {browsing} pages / {conv} writebacks",
  "docs.tabUpload": "Uploads",
  "docs.tabBrowser": "Browsing",
  "docs.uploadHint": "Upload documents (PDF / EPUB / TXT / Markdown / DOCX…) — they can be searched once indexed.",
  "docs.chooseFile": "Choose a file to upload",
  "docs.uploading": "Uploading: {name}",
  "docs.uploadPct": " ({pct}%)",
  "docs.dupFile": "An identical file already exists ({name}); skipped",
  "docs.uploaded": "Uploaded: {name}; parsing in the background…",
  "docs.uploadFailed": "Upload failed",
  "docs.statusProcessing": "Processing",
  "docs.statusIndexed": "Indexed",
  "docs.statusUnparseable": "Unparseable",
  "docs.sortUploadedAt": "Uploaded",
  "docs.sortName": "File name",
  "docs.sortSize": "Size",
  "docs.sortLastVisited": "Last visited",
  "docs.sortFirstCapture": "First captured",
  "docs.sortVisits": "Visits",
  "docs.sortTitle": "Title",
  "docs.emptyDocs": "No documents yet — upload your first book",
  "docs.emptyBrowser": "No browsing history yet — browse with the extension installed and pages appear here",
  "docs.noMatchDocs": "No documents match “{q}”",
  "docs.noMatchBrowser": "No pages match “{q}”",
  "docs.size": "Size {size}",
  "docs.contentSize": "Text {size}",
  "docs.snapshotSize": " · snapshot {size}",
  "docs.contentHit": "Content match: {snippet}",
  "docs.urlHit": "Site / URL match",
  "docs.deepParse": "Deep parse",
  "docs.view": "Open",
  "docs.retry": "Retry",
  "docs.download": "Download",
  "docs.delete": "Delete",
  "docs.revoke": "Revoke",
  "docs.viewSnapshot": "View snapshot",
  "docs.openOriginal": "Open original",
  "docs.deleteConfirm": "Delete “{name}”?{extra}",
  "docs.deleteExtraBrowser": "\nIts snapshot will be removed too, and it disappears from search and citations.",
  "docs.deleteExtraUpload": "\nThe original file will be deleted; this cannot be undone.",
  "docs.deleteFailed": "Delete failed",
  "docs.retryFailed": "Retry failed",
  "docs.collectTitle": "Browser capture",
  "docs.collectHint1": "Enter the server address and a credential below in the Chrome / Edge extension settings — pages you browse are captured ",
  "docs.collectHintBold": "automatically",
  "docs.collectHint2": " (pause anytime from the popup; manage the blocklist in settings). Credentials are for capture only and can be revoked at any time.",
  "docs.tokensSummary": "Capture credentials ({state})",
  "docs.tokensNone": "none created",
  "docs.tokensActive": "{n} active",
  "docs.tokensRevoked": " · {n} revoked",
  "docs.newToken1": "New credential (",
  "docs.newTokenBold": "shown only once",
  "docs.newToken2": " — copy it into the extension settings now):",
  "docs.copy": "Copy",
  "docs.saved": "I've saved it",
  "docs.tokenNamePlaceholder": "Credential name (e.g. Windows Chrome)",
  "docs.tokenScopeTitle": "Credential purpose",
  "docs.scopeCapture": "Capture",
  "docs.scopeRead": "Read-only",
  "docs.scopeWrite": "Read + write",
  "docs.scopeCaptureOpt": "Capture (browser extension)",
  "docs.scopeReadOpt": "Read-only (MCP / Claude Code)",
  "docs.scopeWriteOpt": "Read + write (MCP can save notes back)",
  "docs.createToken": "Create credential",
  "docs.tokenMeta": "{scope} · {prefix}… · last used {time}",
  "docs.revoked": "Revoked",
  "docs.active": "Active",
  "docs.hideRevoked": "Hide revoked",
  "docs.showRevoked": "Show revoked ({n})",
  "docs.revokeConfirm": "Revoke credential “{name}” ({prefix}…)? Extensions using it stop working immediately.",
  "docs.purgeConfirm": "Permanently delete credential “{name}” ({prefix}…)? This cannot be undone.",
  "docs.tokenCreateFailed": "Failed to create credential",
  "docs.tokenRevokeFailed": "Failed to revoke",
  "docs.cleanupTitle": "Clean up browsing by date",
  "docs.cleanupStart": "From",
  "docs.cleanupEnd": "To",
  "docs.cleanup": "Clean up",
  "docs.cleanupHint": "Filters by last-visited time; content and snapshots are deleted and disappear from search and citations.",
  "docs.cleanupNeedDate": "Pick a start or end date first",
  "docs.cleanupEarliest": "earliest",
  "docs.cleanupNow": "now",
  "docs.cleanupConfirm": "Delete all pages visited in this range (snapshots included, irreversible)?\nRange: {range}",
  "docs.cleanupDone": "Cleaned up {n} browsing records",
  "docs.cleanupFailed": "Cleanup failed",
  "docs.browserMeta": "{site} · visited {time} ({n} visits)",
  "docs.snapOversize": "Snapshot not kept (over size limit); only text is searchable",
  "docs.snapFailed": "Snapshot generation failed; only text is searchable",

  // ── Reader ──
  "view.title": "Reader",
  "view.back": "Back",
  "view.missingId": "Missing file parameter (?id=)",
  "view.readFailed": "Failed to load ({status})",
  "view.unsupported": "Inline viewing of .{format} is not supported yet",
  "view.unsupportedHint": "Use “Download” in the top right to open it locally.",
  "view.deleted": "This document no longer exists (its source was deleted)",
  "view.loadFailed": "Failed to load",
  "view.epubFailed": "EPUB rendering failed",
  "view.pdfPreview": "PDF preview",
  "view.prevPage": "← Prev",
  "view.nextPage": "Next →",
  "view.pageOf": "Page {cur}/{total}",
  "view.jumpTo": "Go to",
  "view.page": "page",
  "view.jump": "Jump",
  "view.jumpTitle": "Type a page number and press Enter",
  "view.kbdHint": "(arrow keys ← → also work)",
  "view.toc": "Contents",
  "view.untitled": "(Untitled)",
  "view.quoteNoMatch": "Quote not found in the text; opened the beginning of the document",
  "view.quoteLocated": "Jumped to and highlighted the quote",
  "view.quoteSection": "Jumped to the chapter containing the quote",

  // ── Chat ──
  "chat.title": "second-brain · Chat",
  "chat.navLibrary": "Library",
  "chat.toggleExpand": "Expand conversation list",
  "chat.toggleCollapse": "Collapse conversation list",
  "chat.toggleTitle": "Collapse / expand conversation list (Ctrl+B)",
  "chat.newChat": "＋ New chat",
  "chat.searchPlaceholder": "Search conversations (full text)…",
  "chat.searching": "Searching…",
  "chat.searchHits": "{total} conversations matched",
  "chat.hitCount": "{n} matches · ",
  "chat.noMatch": "No matching conversations",
  "chat.deleteConvTitle": "Delete conversation",
  "chat.deleteConvConfirm": "Delete this conversation? Its writeback content will be removed too. This cannot be undone.",
  "chat.noConversations": "No conversations yet",
  "chat.emptyTitle": "Ask your second brain",
  "chat.emptyHint": "Your documents, browsed pages and past conversations are all searched and cited",
  "chat.suggest1": "How does my library define “architecture decision”?",
  "chat.suggest2": "Which pages did I view in the last 3 days?",
  "chat.suggest3": "What AI-related content did I read last week?",
  "chat.sourcePrefix": "Source: {label}",
  "chat.sourceKb": "From your library",
  "chat.sourceModel": "From model knowledge",
  "chat.sourcePrior": "From past conversations",
  "chat.sourceWeb": "From the web",
  "chat.webFailed": " (web search failed — no web sources used)",
  "chat.webFailedReason": " (web search failed: {reason} — no web sources used)",
  "chat.webErrBalance": "provider account balance insufficient",
  "chat.webErrRate": "provider rate limited",
  "chat.webErrQuota": "daily web-search quota used up",
  "chat.webErrUnavailable": "service unavailable",
  "chat.webNoResults": " (web search found no relevant results — no web sources used)",
  "chat.timeRange": "🕐 Time range: {label}",
  "chat.cacheHit": " · cache hit {n}",
  "chat.costLlm": "Model",
  "chat.costWeb": "Web",
  "chat.costRetrieval": "Retrieval",
  "chat.citationsWeb": "Web sources",
  "chat.citationsLocal": "Sources",
  "chat.citationsDefault": "Sources",
  "chat.citationCount": "{label} ({count})",
  "chat.related": "Possibly related",
  "chat.inherited": "Original sources",
  "chat.inlineWebTag": " · web",
  "chat.inlineVisitedAt": " · visited {time}",
  "chat.openWeb": "↗ Open page",
  "chat.viewSnapshot": "🖼 View snapshot",
  "chat.backToConv": "↩ Back to conversation",
  "chat.previewOpenFull": "↗ Open in chat",
  "chat.previewClose": "Close",
  "chat.jumpToSource": "↗ Jump to source",
  "chat.openOriginal": "↗ Open original",
  "chat.webNoQuote": "No excerpt stored for this source — open the original page to view it",
  "chat.thinkingLive": "Thinking…",
  "chat.thinkingDone": "Thought for {s}s · tap to expand",
  "chat.copied": "✓ Copied",
  "chat.copy": "⧉ Copy",
  "chat.sendFailed": "Failed to send",
  "chat.requestFailed": "Request failed ({status})",
  "chat.inputPlaceholder": "Message your second brain…",
  "chat.answering": "Answering…",
  "chat.phasePlanning": "Understanding the question, planning retrieval…",
  "chat.phaseRetrieving": "Searching your library…",
  "chat.phaseListing": "Querying browsing history…",
  "chat.phaseExpanding": "No strong match yet — retrying with variants…",
  "chat.phaseWeb": "Searching the web…",
  "chat.phaseGenerating": "Writing the answer…",
  "chat.streamChars": "{n} chars",
  "chat.stop": "Stop generating",
  "chat.streamInterrupted": "Connection interrupted — the answer may be incomplete",
  "chat.streamTimeout": "No response for a while — stopped (the answer may be incomplete)",
  "chat.sendTitle": "Send (Enter)",
  "chat.send": "Send",
  "chat.composerHint": "Answers may be inaccurate — check the sources · Enter to send, Shift+Enter for a new line",
};

const DICTS: Record<Lang, Record<string, string>> = { zh, en };

export type MsgKey = keyof typeof zh;

export type Translate = (key: MsgKey, vars?: Record<string, string | number>) => string;

interface LangCtx {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: Translate;
}

const defaultT: Translate = (key) => zh[key] ?? key;

const Ctx = createContext<LangCtx>({ lang: "zh", setLang: () => {}, t: defaultT });

/** 当前语言：localStorage 记忆优先，否则跟随浏览器语言。 */
function readLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "zh" || saved === "en") return saved;
    return navigator.language?.toLowerCase().startsWith("zh") ? "zh" : "en";
  } catch {
    return "zh";
  }
}

/** 文案插值（{name} → 值）。 */
function format(
  dict: Record<string, string>,
  key: MsgKey,
  vars?: Record<string, string | number>,
): string {
  let text = dict[key] ?? zh[key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
  }
  return text;
}

/** 非 React 模块（lib/api.ts 等）取当前语言文案；与 Provider 共用同一份记忆。 */
export function translate(key: MsgKey, vars?: Record<string, string | number>): string {
  return format(DICTS[readLang()], key, vars);
}

export function LangProvider({ children }: { children: ReactNode }) {
  // 首帧固定 zh（与静态导出 HTML 一致，避免 hydration 报警）；挂载后按记忆/浏览器语言切
  const [lang, setLangState] = useState<Lang>("zh");

  useEffect(() => {
    setLangState(readLang());
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
      document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    } catch {
      /* 忽略 */
    }
  }, [lang]);

  const setLang = useCallback((next: Lang) => setLangState(next), []);

  const t = useMemo<Translate>(() => {
    const dict = DICTS[lang];
    return (key, vars) => format(dict, key, vars);
  }, [lang]);

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLang(): LangCtx {
  return useContext(Ctx);
}
