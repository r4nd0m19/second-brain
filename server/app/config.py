"""应用配置 —— 全部来自环境变量 / .env（密钥仅存服务端，constitution IV）。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 哨兵默认值：启动时检测到即拒绝（fail-closed，审计二期 B1，见 Settings.assert_secure）
DEFAULT_ADMIN_PASSWORD = "change-me-please"
DEFAULT_SECRET_KEY = "change-me-random-string"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 对话模型
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    # 答案调用思考档（V4 系，T088）：low/high/max（官方默认 high）；小调用（规划/扩检/时间解析）
    # 恒关思考——R42 事故：V4 默认开思考时思维链会把小预算调用打空（T091 起小上限已移除，
    # 关思考保留：小调用要的是短而快的确定性输出）
    llm_answer_effort: str = "high"

    # MCP（T093）：DNS-rebinding 白名单追加项（逗号分隔，含端口的 host，如 "192.168.1.5:8000"）；
    # 默认仅本机（localhost/127.0.0.1）——局域网访问需显式配置（公开仓库不再硬编码作者内网 IP）
    mcp_allowed_hosts: str = ""

    # API 文档端点（/docs、/redoc、/openapi.json，T093）：默认关闭（未认证的信息暴露面）；
    # 本地调试可设 DOCS_ENABLED=true（该开关不走 /api 前缀，生产务必保持关闭）
    docs_enabled: bool = False

    # Embedding
    embedding_provider: str = "siliconflow"
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # 数据库
    database_url: str = "postgresql+asyncpg://secondbrain:secondbrain@localhost:5433/secondbrain"

    # 单用户账号（口令默认值为哨兵值：启动时 fail-closed 拒绝，审计二期 B1）
    admin_username: str = "me"
    admin_password: str = DEFAULT_ADMIN_PASSWORD

    # 会话签名（默认值为哨兵值：启动时 fail-closed 拒绝，审计二期 B1）
    secret_key: str = DEFAULT_SECRET_KEY

    # 认证安全（T034；spec NFR Security）
    login_rate_limit: int = 5  # 登录失败限速：窗口内最大失败次数（单账号口径）
    login_rate_limit_ip: int = 10  # 登录失败限速：窗口内单 IP 最大失败次数（T093，防随机用户名绕过）
    login_rate_window_min: int = 15  # 限速窗口（分钟）
    cookie_secure: bool = False  # HTTPS 部署后置 AUTH_COOKIE_SECURE=true（T035）

    # 存储与限额
    storage_dir: str = "./data/storage"
    max_upload_mb: int = 200

    # 浏览器采集（F2；data-model.md / contracts/capture-api.md）
    capture_max_snapshot_mb: int = 20  # 单页快照体积上限：超出降级为仅正文+元信息（FR-014）
    capture_max_request_mb: int = 100  # 采集请求体天花板（防滥用；超出 413）
    capture_rate_limit: int = 120  # 采集端点按凭据限速（每分钟请求数；超出 429）

    # 解析（PDF 快通道 / 深度解析；2026-10-01 事故复盘后调整，见 research.md R7）
    pdf_fast_parse: bool = True  # PDF 默认走文本层快通道（秒级、内存恒定）
    parse_deep_page_batch: int = 120  # 深度解析每批页数（内存受控）
    parse_deep_do_ocr: bool = False  # 深度解析默认不跑 OCR（扫描版按 FR-014 登记）
    table_hint_ratio: float = 0.08  # 表格页占比 ≥ 此值 → 提示"可深度解析"
    embedding_batch_size: int = 64  # embedding 每请求条数（快通道入库耗时主项）

    # 检索与对话（FR-005/007；阈值语义见 retrieval/search.py）
    retrieval_top_k: int = 6
    retrieval_hit_threshold: float = 0.60
    retrieval_weak_threshold: float = 0.50
    retrieval_keyword_boost: float = 0.12  # 关键词命中的分数加成（仅作用于向量候选，R15；0.05→0.12，2026-10-02 过线实测）
    retrieval_ef_search: int = 200  # HNSW 检索力度（召回余量；索引删改 churn 后退化时兜底，2026-10-02）

    # 联网检索（F4，004-web-search；key 为空 = 能力关闭，零行为变化）
    web_search_api_key: str = ""
    # 联网搜索提供方（R39/T085；T086）：deepseek=官方服务端搜索（默认，token 计费，R40 用户确认）；searxng=自建免费（可切换）；zhipu=付费 API（可切换）
    web_search_provider: str = "deepseek"
    searxng_base_url: str = "http://127.0.0.1:8888"
    searxng_timeout_s: float = 10.0
    # DeepSeek 服务端搜索（T086/R40）：官方 Anthropic 兼容端点 + web_search 服务端工具；
    # 账号/计费复用 llm_*（同一 DeepSeek 账户）；token 计费（无按次费）→ 计入 web 成本与每日护栏
    deepseek_search_base_url: str = ""  # 空 = 由 llm_base_url 推导（+ /anthropic）
    deepseek_search_model: str = "deepseek-flash"
    deepseek_search_timeout_s: float = 30.0  # 模型轮次 + 服务端搜索，比直连搜索源慢（实测 2.7s~15s）
    # 免费加深（全部自建的质量补偿）：结果最好分低于此值 → 改写查询变体二轮检索（零成本、耗时）
    web_search_escalate_below: float = 0.45
    # 付费兜底开关（默认关；开启且智谱 key 有效时，"免费加深仍不达标"才付一次）
    web_search_paid_fallback: bool = False

    web_search_max_results: int = 5
    # 搜索+读页（R38/T082）：对过滤后的前 N 条结果抓取正文、段落级筛选（0 = 关闭读页，仅用摘要）
    web_search_reader_max_pages: int = 4
    web_search_page_timeout_s: float = 8.0
    web_search_page_total_timeout_s: float = 15.0  # 单页抓取总时限（T093：防慢速滴流续命 per-phase 超时）
    chat_url_fetch_max: int = 3  # 聊天内链接直读上限（T097：消息中的 http(s) 链接直接抓正文；0=关闭）
    web_search_page_max_bytes: int = 2_000_000
    web_search_fetch_concurrency: int = 4
    web_search_digest_max_chars: int = 2000  # 单页注入上下文字符上限
    web_search_digest_max_paragraphs: int = 6
    web_search_snippet_max: int = 800
    web_search_timeout_s: float = 5.0
    web_search_freshness: str = "noLimit"
    # 引擎档位（R37 四组查询实测）：sogou 质量显著最优（命中真实数据源）；std/pro 同源、偏中文 SEO 内容农场
    web_search_engine: str = "search_pro_sogou"  # 智谱引擎：search_std(￥0.01)/search_pro(￥0.03)/search_pro_sogou(￥0.05)/search_pro_quark(￥0.05)
    web_search_fallback_engine: str = "search_pro_quark"  # 付费源内部：主引擎零链接时兜底一次（空串=禁用）
    web_search_relevance_floor: float = 0.3  # 结果重排过滤下限（R37 标定：相关 0.4+ / 垃圾 ≤0.2；Reranker 失败 → 不过滤）
    web_search_daily_limit: int = 30  # 每日搜索次数上限（0=不限；进程内计数护栏）
    retrieval_keyword_terms: int = 4  # 查询拆词上限（T033）
    chat_history_limit: int = 10
    timerange_max_years: int = 5  # 时间解析兜底的最大跨度（F2 US3；超出视为解析失败）

    # 模型计价（¥/百万 tokens；deepseek-flash 官方价，2026-10-03 核实：
    # api-docs.deepseek.com/zh-cn/quick_start/pricing）。下列为**空闲时段基准价**；
    # 高峰时段（北京时间周一至五 9:00-12:00 / 14:00-18:00；法定节假日未建模——
    # 节假日按高峰计、费用略高估）为基准 ×2。用于用量估算（FR-017，R22）。
    price_input_hit_per_million: float = 0.02  # 输入·缓存命中（空闲）
    price_input_miss_per_million: float = 1.0  # 输入·缓存未命中（空闲）
    price_output_per_million: float = 4.0  # 输出（空闲）
    price_peak_multiplier: float = 2.0  # 高峰倍率（官方口径：空闲 = 高峰一半）

    # 回写近似查重（审计二期 C1）：新问答与库内最近邻相似度 ≥ 阈值 → 视为重复，跳过回写
    writeback_dup_threshold: float = 0.95

    # 二段式重排（R24/A 方案）：cross-encoder 复评候选池；失败静默降级为余弦+加成
    # 模型换代为 Qwen3-Reranker-4B（R35/T076 评测：分离 −0.30→+0.64、改写抽奖消失、延迟 +0.4s）
    rerank_enabled: bool = True
    rerank_model: str = "Qwen/Qwen3-Reranker-4B"
    rerank_timeout_seconds: float = 15.0

    # 全成本聚合单价（T079 / R36）：联网搜索按次、检索设施按 tokens（用于费用展示）
    price_web_search_std_cny: float = 0.01  # 智谱 search_std（默认引擎）
    price_web_search_pro_cny: float = 0.05  # pro/sogou/quark（保守取上限）
    price_embedding_per_million: float = 0.0  # bge-m3 @ 硅基流动（2026-10 核实免费）
    price_rerank_per_million: float = 0.14  # Qwen3-Reranker-4B @ 硅基流动（R35）

    def assert_secure(self) -> None:
        """fail-closed（审计二期 B1；T093 强化）：默认/空/过弱值 → 拒绝启动。

        原实现只比对哨兵常量——`.env` 里 `SECRET_KEY=`（空值，注释掉值的常见误配）可静默通过。
        """
        if self.secret_key == DEFAULT_SECRET_KEY or len(self.secret_key.strip()) < 32:
            raise RuntimeError(
                "SECRET_KEY 为空/过短（<32 字符）或仍为默认值——请在 .env 设置随机 SECRET_KEY 后重启（fail-closed，T093）"
            )
        if self.admin_password == DEFAULT_ADMIN_PASSWORD or len(self.admin_password.strip()) < 8:
            raise RuntimeError(
                "ADMIN_PASSWORD 为空/过短（<8 字符）或仍为默认值——请在 .env 设置 ADMIN_PASSWORD 后重启（fail-closed，T093）"
            )

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir)


settings = Settings()
