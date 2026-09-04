from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    postgres_db: str = "reconciliation"
    postgres_user: str = "recon"
    postgres_password: str = "recon_secret"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    demo_mode: bool = False
    serverless: bool = False
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_base_url: str = "https://api.razorpay.com"
    razorpay_page_size: int = Field(default=100, ge=1, le=100)
    razorpay_max_pages: int = Field(default=10, ge=1, le=50)
    razorpay_timeout_seconds: float = Field(default=10.0, gt=0, le=60.0)
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    gemini_model: str = "gemma-4-31b-it"
    groq_model: str = "qwen/qwen3.8-27b"
    ai_timeout_seconds: float = Field(default=10.0, gt=0, le=60.0)
    ai_max_tool_rounds: int = Field(default=4, ge=1, le=4)
    ai_max_source_ids: int = Field(default=10, ge=1, le=10)
    ai_max_tool_rows: int = Field(default=100, ge=1, le=1000)
    ai_max_batch_close_prompt_chars: int = Field(default=100_000, ge=1_000, le=1_000_000)
    cors_origins: str = "http://localhost:5173"

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self._async_driver_url(self.database_url_override)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @staticmethod
    def _async_driver_url(url: str) -> str:
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)

        parsed = urlsplit(url)
        query = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key == "channel_binding":
                continue
            if key == "sslmode":
                key = "ssl"
            query.append((key, value))
        return urlunsplit(parsed._replace(query=urlencode(query)))

    model_config = SettingsConfigDict(
        env_file="../../.env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )


settings = Settings()
