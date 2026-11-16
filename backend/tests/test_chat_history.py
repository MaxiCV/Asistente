import asyncio
from uuid import uuid4

import pytest
from app.chat.errors import ChatError
from app.chat.history import ChatHistoryStore
from app.core.config import Settings
from qdrant_client import AsyncQdrantClient, models


def test_history_reads_do_not_create_and_concurrent_initialization():
    async def scenario():
        client = AsyncQdrantClient(":memory:")
        settings = Settings(_env_file=None)
        first = ChatHistoryStore(settings, client)
        second = ChatHistoryStore(settings, client)
        try:
            assert await first.read(uuid4()) == []
            assert not await client.collection_exists(settings.chat_collection)
            await asyncio.gather(first.ensure(), second.ensure())
            assert (
                await client.get_collection(settings.chat_collection)
            ).config.params.vectors == {}
            assert not (await client.get_aliases()).aliases
        finally:
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["vectors", "alias"])
def test_history_rejects_incompatible_collection(invalid):
    async def scenario():
        client = AsyncQdrantClient(":memory:")
        settings = Settings(_env_file=None)
        store = ChatHistoryStore(settings, client)
        vectors = (
            models.VectorParams(size=2, distance=models.Distance.COSINE)
            if invalid == "vectors"
            else {}
        )
        try:
            await client.create_collection(store.collection, vectors_config=vectors)
            if invalid == "alias":
                await client.update_collection_aliases(
                    [
                        models.CreateAliasOperation(
                            create_alias=models.CreateAlias(
                                collection_name=store.collection, alias_name="test_history_alias"
                            )
                        )
                    ]
                )
            with pytest.raises(ChatError) as failed:
                await store.ensure()
            assert failed.value.code == "chat_history_unavailable"
        finally:
            await client.close()

    asyncio.run(scenario())
