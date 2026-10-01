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

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir)


settings = Settings()
