from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_database_initialization_is_explicit(monkeypatch):
    from app import database_init
    from app.common.base import Base

    sync_operations = []
    statements = []

    class Connection:
        async def run_sync(self, operation):
            sync_operations.append(operation)

        async def execute(self, statement):
            statements.append(str(statement))
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    class Begin:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    class Engine:
        def begin(self):
            return Begin()

    monkeypatch.setattr(database_init, "engine", Engine())

    await database_init.initialize_database()

    assert sync_operations == [Base.metadata.create_all]
    assert any("ALTER TYPE auditeventtype" in statement for statement in statements)
    assert any("ALTER TABLE" in statement for statement in statements)
    assert any("CREATE UNIQUE INDEX" in statement for statement in statements)


@pytest.mark.asyncio
async def test_api_lifespan_does_not_initialize_database(monkeypatch):
    from app import database_init, main

    initialize = AsyncMock(side_effect=AssertionError("startup initialization"))
    dispose = AsyncMock()
    monkeypatch.setattr(database_init, "initialize_database", initialize)
    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=dispose))

    async with main.lifespan(main.app):
        pass

    initialize.assert_not_awaited()
    dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_serverless_request_does_not_initialize_database(monkeypatch):
    from app import database_init, main
    from app.database import get_session

    initialize = AsyncMock(side_effect=AssertionError("request initialization"))
    dispose = AsyncMock()
    monkeypatch.setattr(database_init, "initialize_database", initialize)
    ddl_engine = SimpleNamespace(
        begin=MagicMock(side_effect=AssertionError("request DDL"))
    )
    monkeypatch.setattr(database_init, "engine", ddl_engine)
    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=dispose))
    monkeypatch.setattr(main.app_settings, "serverless", True)

    count_result = MagicMock(scalar=lambda: 0)
    rows_result = MagicMock(scalars=lambda: MagicMock(all=lambda: []))
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[count_result, rows_result])
    main.app.dependency_overrides[get_session] = lambda: session

    try:
        async with main.lifespan(main.app):
            async with AsyncClient(
                transport=ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                response = await client.get("/batches?page=1&page_size=10")
    finally:
        main.app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    initialize.assert_not_awaited()
    dispose.assert_awaited_once()
