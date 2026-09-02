from app.config import Settings


def test_neon_url_is_converted_for_asyncpg_and_pgbouncer():
    url = Settings._async_driver_url(
        "postgresql://demo:demo@ep-example-pooler.neon.tech/app"
        "?sslmode=require&channel_binding=require"
    )

    assert url == (
        "postgresql+asyncpg://demo:demo@ep-example-pooler.neon.tech/app?ssl=require"
    )


def test_local_database_url_keeps_compose_defaults():
    settings = Settings(
        postgres_host="postgres",
        postgres_port=5432,
        postgres_db="reconciliation",
        postgres_user="recon",
        postgres_password="local-only",
    )

    assert settings.database_url == (
        "postgresql+asyncpg://recon:local-only@postgres:5432/reconciliation"
    )
