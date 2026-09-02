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
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    anthropic_api_key: str | None = None
    cors_origins: str = "http://localhost:5173"

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self._async_driver_url(self.database_url_override)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Synchronous DB URL for LangChain (it doesn't support async)."""
        if self.database_url_override:
            url = self.database_url_override
            if url.startswith("postgresql+asyncpg://"):
                return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+psycopg2://", 1)
            if url.startswith("postgres://"):
                return url.replace("postgres://", "postgresql+psycopg2://", 1)
            return url
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @staticmethod
    def _async_driver_url(url: str) -> str:
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    model_config = SettingsConfigDict(
        env_file="../../.env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )


settings = Settings()
