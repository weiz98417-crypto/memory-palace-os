import pytest

from src.memory_palace.knowledge import postgres_client
from src.memory_palace.knowledge.postgres_client import PostgresDBClient


class _Connection:
    def __init__(self, execute_result="UPDATE 1"):
        self.execute_result = execute_result
        self.executed = None
        self.transaction_context = None
        self.transaction_options = None

    async def execute(self, sql, *params):
        self.executed = (sql, params)
        return self.execute_result

    async def fetchrow(self, sql, *params):
        return {"ok": 1}

    async def fetch(self, sql, *params):
        return [{"ok": 1}, {"ok": 2}]

    def transaction(self, **options):
        self.transaction_options = options
        self.transaction_context = _TransactionContext()
        return self.transaction_context


class _TransactionContext:
    def __init__(self):
        self.entered = False
        self.exited_with = None

    async def __aenter__(self):
        self.entered = True

    async def __aexit__(self, exc_type, exc, traceback):
        self.exited_with = exc_type
        return False


class _AcquireContext:
    def __init__(self, connection=None):
        self.connection = connection or _Connection()

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Pool:
    def __init__(self, connection=None):
        self.connection = connection

    def acquire(self):
        return _AcquireContext(self.connection)


@pytest.mark.asyncio
async def test_postgres_password_with_url_reserved_characters_stays_out_of_dsn(monkeypatch):
    captured = {}

    async def create_pool(dsn, **kwargs):
        captured["dsn"] = dsn
        captured.update(kwargs)
        return _Pool()

    password = "db@pass:/?#[]"
    monkeypatch.setenv("PGPASSWORD", password)
    monkeypatch.setattr(postgres_client.asyncpg, "create_pool", create_pool)

    client = PostgresDBClient("postgresql://mp_user@postgres:5432/memory_palace")
    row = await client.fetch_one("SELECT 1 AS ok")

    assert row == {"ok": 1}
    assert client.backend_name == "postgresql"
    assert captured["dsn"] == "postgresql://mp_user@postgres:5432/memory_palace"
    assert captured["password"] == password


@pytest.mark.asyncio
async def test_postgres_execute_reports_conditional_update_rowcount():
    connection = _Connection("UPDATE 1")
    client = PostgresDBClient("postgresql://localhost/memory_palace")
    client._pool = _Pool(connection)

    affected = await client.execute(
        "UPDATE refresh_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (123.0, "refresh-id"),
    )

    assert affected == 1
    assert connection.executed == (
        "UPDATE refresh_tokens SET revoked_at = $1 WHERE id = $2 AND revoked_at IS NULL",
        (123.0, "refresh-id"),
    )

    connection.execute_result = "UPDATE 0"
    assert await client.execute(
        "UPDATE refresh_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (124.0, "refresh-id"),
    ) == 0


@pytest.mark.asyncio
async def test_postgres_transaction_reuses_one_connection_with_database_interface():
    connection = _Connection("INSERT 0 1")
    client = PostgresDBClient("postgresql://localhost/memory_palace")
    client._pool = _Pool(connection)

    async with client.transaction() as transaction:
        affected = await transaction.execute(
            "INSERT INTO audit_logs (trace_id) VALUES (?)",
            ("trace-1",),
        )
        row = await transaction.fetch_one("SELECT ? AS ok", (1,))
        rows = await transaction.fetch_all("SELECT ? AS ok", (1,))

    assert affected == 1
    assert row == {"ok": 1}
    assert rows == [{"ok": 1}, {"ok": 2}]
    assert connection.transaction_context.entered is True
    assert connection.transaction_context.exited_with is None


@pytest.mark.asyncio
async def test_postgres_read_snapshot_is_repeatable_and_read_only():
    connection = _Connection()
    client = PostgresDBClient("postgresql://localhost/memory_palace")
    client._pool = _Pool(connection)

    async with client.read_snapshot() as snapshot:
        assert await snapshot.fetch_one("SELECT 1 AS ok") == {"ok": 1}

    assert connection.transaction_options == {
        "isolation": "repeatable_read",
        "readonly": True,
    }
