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
    login_rate_limit: int = 5  # 登录失败限速：窗口内最大失败次数
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
    web_search_max_results: int = 5
    web_search_snippet_max: int = 800
    web_search_timeout_s: float = 5.0
    web_search_freshness: str = "noLimit"
    web_search_engine: str = "search_std"  # 智谱引擎档位：search_std(￥0.01)/search_pro(￥0.03)/search_pro_sogou(￥0.05)/search_pro_quark(￥0.05)
    web_search_fallback_engine: str = "search_pro_sogou"  # 主引擎零链接时兜底一次（实测 link 按引擎/查询确定性缺失；空串=禁用）
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
    rerank_enabled: bool = True
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_timeout_seconds: float = 15.0

    def assert_secure(self) -> None:
        """fail-closed（审计二期 B1）：默认密钥/口令 → 拒绝启动，要求显式配置。"""
        if self.secret_key == DEFAULT_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY 仍为默认值——请在 .env 设置随机 SECRET_KEY 后重启（fail-closed，审计二期 B1）"
            )
        if self.admin_password == DEFAULT_ADMIN_PASSWORD:
            raise RuntimeError(
                "ADMIN_PASSWORD 仍为默认值——请在 .env 设置 ADMIN_PASSWORD 后重启（fail-closed，审计二期 B1）"
            )

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir)


settings = Settings()
