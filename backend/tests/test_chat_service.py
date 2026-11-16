import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.chat.errors import ChatError
from app.chat.history import ChatHistoryStore
from app.chat.prompt import INSUFFICIENT, SYSTEM, make_prompt
from app.chat.service import ChatService, validated_answer
from app.contracts import ChatConfig, ChatRequest, LlmAnswer
from app.core.config import Settings
from app.indexing.chunking import make_passages
from app.search.service import RetrievedPassage
from qdrant_client import AsyncQdrantClient
from test_chat_api import Answers
from test_search_flow import Encoder, documents


def passages():
    from app.contracts import ChunkingConfig

    return [
        RetrievedPassage(make_passages(d, Encoder(), ChunkingConfig(), "a" * 64)[0], d, 0.5)
        for d in documents()
    ]


@pytest.mark.parametrize(
    "text,declared",
    [
        ("Inventado [99]", [99]),
        ("Texto [1]", [2]),
        ("Texto sin citas", [1]),
        ("Texto [1] y afirmación [99]", [1]),
        ("Texto sin citas", []),
        ("Texto [1] y afirmación [1, 99]", [1]),
        ("Texto [1] y afirmación [1-99]", [1]),
        ("Texto [1] y afirmación [99", [1]),
    ],
)
def test_invalid_citations_discard_claims(text, declared):
    result = validated_answer(
        LlmAnswer(status="answered", answer=text, cited_sources=declared), passages()
    )
    assert result == (INSUFFICIENT, [], "none", "invalid_citations")


@pytest.mark.parametrize(
    "markers,level", [([1], "abstract"), ([2], "metadata_only"), ([1, 2], "mixed")]
)
def test_evidence_level_and_corpus_citations(markers, level):
    answer = "Basado en los datos " + " ".join(f"[{n}]" for n in markers)
    result = validated_answer(
        LlmAnswer(status="answered", answer=answer, cited_sources=markers), passages()
    )
    assert result[2] == level and [c.marker for c in result[1]] == markers
    assert result[1][0].title == passages()[markers[0] - 1].document.title


def test_grouped_citations_are_all_validated_and_normalized():
    result = validated_answer(
        LlmAnswer(status="answered", answer="Fuentes [1, 2].", cited_sources=[1, 2]), passages()
    )
    assert result[0] == "Fuentes [1][2]."
    assert [c.marker for c in result[1]] == [1, 2]
    assert result[2] == "mixed"


def test_prompt_bounds_and_historical_markers():
    history = [
        SimpleNamespace(
            request=SimpleNamespace(question=f"Pregunta {n}"),
            response=SimpleNamespace(answer="Resumen [1]"),
        )
        for n in range(6)
    ]
    prompt, evidence = make_prompt("¿Qué sabemos? {untrusted}", passages(), history, ChatConfig())
    data = json.loads(evidence)
    assert len(data["history"]) == 4 and data["history"][0]["question"] == "Pregunta 2"
    assert all("[1]" not in h["answer"] for h in data["history"])
    assert data["sources"][1]["content_level"] == "metadata"
    assert "métodos, resultados" in SYSTEM and "concesión" in SYSTEM
    assert "{untrusted}" in prompt.format(evidence=evidence)
    with pytest.raises(ValueError, match="presupuesto"):
        make_prompt("Pregunta", passages(), [], ChatConfig(max_prompt_chars=2000))


def test_serialization_retries_and_ambiguous_writes():
    async def scenario():
        settings = Settings(_env_file=None)
        store = ChatHistoryStore(settings, AsyncQdrantClient(":memory:"))
        answers = Answers()
        service = ChatService(
            settings,
            ChatConfig(default_mode="semantic"),
            store,
            lambda *_: (SimpleNamespace(generation_id="fixture"), passages()),
            answers,
        )
        request = ChatRequest(request_id=uuid4(), question="Pregunta")
        try:
            duplicates = await asyncio.gather(*(service.answer(request) for _ in range(3)))
            assert duplicates[0] == duplicates[1] == duplicates[2]
            assert len(answers.calls) == 1
            conversation = duplicates[0].conversation_id
            turns = await asyncio.gather(
                *(
                    service.answer(
                        ChatRequest(
                            request_id=uuid4(),
                            question=f"Seguimiento {n}",
                            conversation_id=conversation,
                        )
                    )
                    for n in range(2)
                )
            )
            assert sorted(t.turn_index for t in turns) == [2, 3]
            assert len(answers.calls[-1]["history"]) == 2
            assert not service.locks.entries
            original = store.client.upsert

            async def ambiguous(*args, **kwargs):
                await original(*args, **kwargs)
                raise TimeoutError("ack lost")

            store.client.upsert = ambiguous
            pending = ChatRequest(
                request_id=uuid4(), question="Persistencia incierta", conversation_id=conversation
            )
            with pytest.raises(ChatError) as failed:
                await service.answer(pending)
            assert failed.value.code == "chat_history_unavailable"
            count = len(answers.calls)
            store.client.upsert = original
            replay = await service.answer(pending)
            assert replay.turn_index == 4 and len(answers.calls) == count
            assert (await store.conversation(conversation)).turns[-1].response == replay
        finally:
            await store.aclose()

    asyncio.run(scenario())


def test_operation_deadline_cancels_without_persistence():
    async def scenario():
        settings = Settings(_env_file=None)
        store = ChatHistoryStore(settings, AsyncQdrantClient(":memory:"))
        answers = Answers()
        config = ChatConfig(operation_timeout_seconds=0.02)
        service = ChatService(
            settings,
            config,
            store,
            lambda *_: (SimpleNamespace(generation_id="fixture"), passages()),
            answers,
        )

        async def slow(*_):
            await asyncio.sleep(1)

        answers.answer = slow
        try:
            with pytest.raises(ChatError) as failed:
                await service.answer(ChatRequest(request_id=uuid4(), question="Pregunta"))
            assert failed.value.code == "llm_failed"
            assert not await store.client.collection_exists(settings.chat_collection)
            assert not service.locks.entries
        finally:
            await store.aclose()

    asyncio.run(scenario())
