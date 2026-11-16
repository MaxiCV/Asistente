import asyncio
import hashlib
import json
from contextlib import asynccontextmanager

from qdrant_client import AsyncQdrantClient, models

from app.chat.errors import ChatError, history_unavailable
from app.contracts import ChatTurn, ConversationResponse


def request_hash(request):
    text = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


class TurnLocks:
    """Per-process locks, released with their last waiter. Deploy one API worker."""

    def __init__(self):
        self.entries = {}

    @asynccontextmanager
    async def hold(self, key):
        entry = self.entries.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                del self.entries[key]


class ChatHistoryStore:
    def __init__(self, settings, client=None):
        self.client = client or AsyncQdrantClient(
            url=settings.qdrant_url, timeout=5, check_compatibility=False
        )
        self.collection = settings.chat_collection
        self.creation_lock = asyncio.Lock()

    @asynccontextmanager
    async def checked(self):
        try:
            yield
        except ChatError:
            raise
        except Exception:
            raise history_unavailable() from None

    async def ensure(self):
        async with self.creation_lock, self.checked():
            if not await self.client.collection_exists(self.collection):
                try:
                    await self.client.create_collection(self.collection, vectors_config={})
                except Exception:
                    if not await self.client.collection_exists(self.collection):
                        raise
            info = await self.client.get_collection(self.collection)
            if info.config.params.vectors != {} or info.config.params.sparse_vectors:
                raise ValueError("La colección de historial debe carecer de vectores")
            aliases = await self.client.get_aliases()
            if any(a.collection_name == self.collection for a in aliases.aliases):
                raise ValueError("El historial no admite alias")
            for name, kind in (
                ("conversation_id", models.PayloadSchemaType.KEYWORD),
                ("turn_index", models.PayloadSchemaType.INTEGER),
            ):
                existing = info.payload_schema.get(name)
                if existing and existing.data_type != kind:
                    raise ValueError("Índice de historial incompatible")
                if not existing:
                    await self.client.create_payload_index(self.collection, name, kind, wait=True)

    def decode(self, point):
        payload = point.payload or {}
        turn = ChatTurn.model_validate(payload.get("turn"))
        if (
            str(point.id) != str(turn.request.request_id)
            or payload.get("conversation_id") != str(turn.response.conversation_id)
            or payload.get("turn_index") != turn.response.turn_index
            or request_hash(turn.request) != turn.request_sha256
        ):
            raise ValueError("Turno persistido incoherente")
        return turn

    async def lookup(self, request):
        async with self.checked():
            if not await self.client.collection_exists(self.collection):
                return None
            points = await self.client.retrieve(
                self.collection, [str(request.request_id)], with_payload=True
            )
            if not points:
                return None
            turn = self.decode(points[0])
            if turn.request_sha256 != request_hash(request):
                raise ChatError(
                    409,
                    "request_id_conflict",
                    "Este envío ya se utilizó con otra pregunta o filtros.",
                )
            return turn

    async def read(self, conversation_id, *, limit=20, after=0, descending=False):
        async with self.checked():
            if not await self.client.collection_exists(self.collection):
                return []
            points, _ = await self.client.scroll(
                self.collection,
                limit=limit,
                with_payload=True,
                with_vectors=False,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="conversation_id",
                            match=models.MatchValue(value=str(conversation_id)),
                        ),
                        models.FieldCondition(key="turn_index", range=models.Range(gt=after)),
                    ]
                ),
                order_by=models.OrderBy(
                    key="turn_index", direction="desc" if descending else "asc"
                ),
            )
            turns = [self.decode(p) for p in points]
            if (
                any(t.response.conversation_id != conversation_id for t in turns)
                or len({t.response.turn_index for t in turns}) != len(turns)
                or len({t.response.index_generation for t in turns}) > 1
            ):
                raise ValueError("Historial inconsistente")
            return turns

    async def conversation(self, conversation_id, after=0, limit=20):
        first = await self.read(conversation_id, limit=1)
        if not first:
            raise ChatError(
                404, "conversation_not_found", "La conversación no existe. Inicia una nueva."
            )
        turns = await self.read(conversation_id, after=after, limit=limit + 1)
        if any(t.response.index_generation != first[0].response.index_generation for t in turns):
            raise history_unavailable()
        return ConversationResponse(
            conversation_id=conversation_id,
            index_generation=first[0].response.index_generation,
            turns=turns[:limit],
            next_cursor=turns[limit - 1].response.turn_index if len(turns) > limit else None,
        )

    async def save(self, turn):
        await self.ensure()
        async with self.checked():
            await self.client.upsert(
                self.collection,
                [
                    models.PointStruct(
                        id=str(turn.request.request_id),
                        vector={},
                        payload={
                            "conversation_id": str(turn.response.conversation_id),
                            "turn_index": turn.response.turn_index,
                            "turn": turn.model_dump(mode="json"),
                        },
                    )
                ],
                wait=True,
            )

    async def aclose(self):
        await self.client.close()
