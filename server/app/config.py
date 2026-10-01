"""应用配置 —— 全部来自环境变量 / .env（密钥仅存服务端，constitution IV）。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # 单用户账号
    admin_username: str = "me"
    admin_password: str = "change-me-please"

    # 会话签名
    secret_key: str = "change-me-random-string"

    # 存储与限额
    storage_dir: str = "./data/storage"
    max_upload_mb: int = 200

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
    chat_history_limit: int = 10

    # 模型计价（¥/百万 tokens；默认 deepseek-chat 空闲时段价，用于用量估算 FR-017）
    price_input_per_million: float = 1.1
    price_output_per_million: float = 4.4

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir)


settings = Settings()
