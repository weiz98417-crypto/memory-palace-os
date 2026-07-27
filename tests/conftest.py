import asyncio

import pytest


@pytest.fixture(scope="session", autouse=True)
def close_global_notification_workers():
    """Ensure imported notification workers never keep pytest alive."""
    yield
    from src.memory_palace.knowledge.db_client import db_client
    from src.memory_palace.knowledge.vector_store import close_vector_client
    from src.memory_palace.tools.sms_client import sms_client

    asyncio.run(db_client.close())
    close_vector_client()
    sms_client.close(wait=True)
