import pytest

from src.memory_palace.scenic.redis_advice_queue import (
    ADVICE_GROUP_NAME,
    ADVICE_STREAM_KEY,
    RedisAdviceQueue,
)

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self):
        self.eval_calls = []
        self.acks = []
        self.reads = []
        self.claimed = []

    async def eval(self, *args):
        self.eval_calls.append(args)
        return b"1-0"

    async def xautoclaim(self, *args, **kwargs):
        return [b"0-0", self.claimed]

    async def xreadgroup(self, *args, **kwargs):
        return self.reads

    async def xack(self, stream, group, message_id):
        self.acks.append((stream, group, message_id))
        return 1


async def test_advice_queue_uses_an_independent_stream_and_acks_claimed_message():
    client = FakeRedis()
    client.reads = [
        (ADVICE_STREAM_KEY.encode(), [(b"2-0", {b"data": b'{"advice_run_id":"run-1"}'})])
    ]
    queue = RedisAdviceQueue(client=client, consumer_name="test-consumer")

    message = await queue.claim()
    await queue.ack(message)

    assert ADVICE_STREAM_KEY == "memory_palace:advice_runs"
    assert ADVICE_GROUP_NAME == "mp_advice_workers"
    assert message["advice_run_id"] == "run-1"
    assert client.acks == [(ADVICE_STREAM_KEY, ADVICE_GROUP_NAME, "2-0")]


async def test_advice_queue_reclaims_stale_pending_before_new_work():
    client = FakeRedis()
    client.claimed = [(b"1-0", {b"data": b'{"advice_run_id":"run-recovered"}'})]
    queue = RedisAdviceQueue(client=client, consumer_name="recovery-consumer")

    message = await queue.claim()

    assert message["advice_run_id"] == "run-recovered"
    assert message["_recovered"] is True


async def test_advice_enqueue_is_atomically_deduplicated_by_run_id():
    client = FakeRedis()
    queue = RedisAdviceQueue(client=client, consumer_name="test-consumer")

    await queue.enqueue({"advice_run_id": "run-1", "venue_id": "venue-1"})

    call = client.eval_calls[0]
    assert ADVICE_STREAM_KEY in call
    assert "run-1" in call[-2]
    assert call[-1] == "86400000"
