import pytest

from src.memory_palace.core.watcher_runtime import _ensure_event_watcher_policy


@pytest.mark.asyncio
async def test_event_watcher_policy_binds_postgres_boolean_value():
    class RecordingDB:
        def __init__(self):
            self.statement = ""
            self.params = ()

        async def execute(self, statement, params=()):
            self.statement = statement
            self.params = params

    database = RecordingDB()

    policy_id = await _ensure_event_watcher_policy(
        database,
        venue_id="venue-alpha",
        created_by="manager-alpha",
    )

    assert policy_id
    assert database.params[2] is False
    assert "'0 0 1 1 *', ?," in database.statement

