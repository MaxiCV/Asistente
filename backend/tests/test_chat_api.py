import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.chat.history import ChatHistoryStore
from app.chat.llm import GeminiAnswerer
from app.contracts import ChatConfig, LlmAnswer
from app.core.config import embedding_config
from app.indexing.publish import publish_generation
from app.main import create_app
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient
from test_hybrid import hybrid_index  # noqa: F401
from test_search_flow import Encoder, indexed  # noqa: F401


class Answers:
    def __init__(self):
        self.calls, self.closed = [], 0
        self.result = LlmAnswer(
            status="answered", answer="El resumen describe detección [1].", cited_sources=[1]
        )
        self.error = None

    def __call__(self, *_):
        return self

    async def answer(self, prompt, evidence):
        self.calls.append(json.loads(evidence))
        if self.error:
            raise self.error
        return self.result

    async def aclose(self):
        self.closed += 1


@pytest.fixture
def chat_env(indexed):  # noqa: F811
    answers = Answers()
    store = ChatHistoryStore(indexed.settings, AsyncQdrantClient(":memory:"))
    app = create_app(
        indexed.settings,
        Encoder,
        llm_factory=answers,
        history_factory=lambda _: store,
        chat_settings=ChatConfig(default_mode="semantic"),
    )
    with TestClient(app) as api:
        yield SimpleNamespace(api=api, app=app, answers=answers, store=store, indexed=indexed)


def ask(api, **kwargs):
    return api.post(
        "/api/v1/chat", json={"request_id": str(uuid4()), "question": "¿Qué se estudió?", **kwargs}
    )


def test_chat_roundtrip_idempotency_and_pagination(chat_env):
    env = chat_env
    key = str(uuid4())
    response = ask(env.api, request_id=key)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["status"] == "answered"
    assert first["citations"][0]["passage_id"] in {p["passage_id"] for p in first["context"]}
    assert first["turn_id"] == key
    assert ask(env.api, request_id=key).json() == first
    conflict = ask(env.api, request_id=key, question="Pregunta diferente")
    assert (
        conflict.status_code == 409 and conflict.json()["detail"]["code"] == "request_id_conflict"
    )
    assert len(env.answers.calls) == 1
    second = ask(env.api, conversation_id=first["conversation_id"]).json()
    assert second["turn_index"] == 2
    assert "[1]" not in env.answers.calls[-1]["history"][0]["answer"]
    page = env.api.get(f"/api/v1/chat/{first['conversation_id']}", params={"limit": 1}).json()
    assert page["turns"][0]["response"] == first and page["next_cursor"] == 1
    later = env.api.get(f"/api/v1/chat/{first['conversation_id']}", params={"after": 1}).json()
    assert later["turns"][0]["response"] == second and later["next_cursor"] is None
    env.app.state.encoder = None
    assert env.api.get(f"/api/v1/chat/{first['conversation_id']}").status_code == 200
    assert env.answers.closed == 2


def test_empty_context_does_not_initialize_provider(chat_env):
    def forbidden(*_):
        pytest.fail("Sin contexto no debe inicializar Gemini")

    chat_env.app.state.chat_service.llm_factory = forbidden
    response = ask(chat_env.api, document_type="patent")
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["model"] is None and not response.json()["context"]
    assert chat_env.api.get("/api/v1/ready").status_code == 200


@pytest.mark.parametrize(
    "change,code,status",
    [
        ({"conversation_id": str(uuid4())}, "conversation_not_found", 404),
        ({"index_generation": "missing"}, "generation_retired", 409),
        ({"mode": "hybrid"}, "search_mode_unavailable", 409),
    ],
)
def test_chat_errors_preserve_codes(chat_env, change, code, status):
    response = ask(chat_env.api, **change)
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def test_conversation_pins_generation_across_publish(chat_env):
    env = chat_env
    first = ask(env.api).json()
    generation = env.indexed.build()
    publish_generation(env.indexed.client, env.indexed.settings, embedding_config(), generation)
    second = ask(env.api, conversation_id=first["conversation_id"]).json()
    assert second["index_generation"] == first["index_generation"]
    conflict = ask(env.api, conversation_id=first["conversation_id"], index_generation=generation)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "conversation_generation_mismatch"
    env.indexed.client.delete_collection(f"passages_{first['index_generation']}")
    retired = ask(env.api, conversation_id=first["conversation_id"])
    assert retired.status_code == 409 and retired.json()["detail"]["code"] == "generation_retired"
    assert len(env.api.get(f"/api/v1/chat/{first['conversation_id']}").json()["turns"]) == 2


def test_llm_errors_no_key_and_no_leaked_messages(chat_env, caplog):
    env = chat_env
    env.app.state.chat_service.llm_factory = GeminiAnswerer
    env.app.state.chat_service.settings.gemini_api_key = None
    response = ask(env.api)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "llm_unavailable"
    env.app.state.chat_service.llm_factory = env.answers
    env.answers.error = RuntimeError("synthetic-secret-must-not-appear")
    response = ask(env.api)
    assert response.status_code == 502 and response.json()["detail"]["code"] == "llm_failed"
    assert "synthetic-secret" not in response.text + caplog.text
    assert env.api.get("/api/v1/ready").status_code == 200
    assert env.api.get("/api/v1/documents", params={"q": "fall"}).status_code == 200


def test_long_questions_and_validation(chat_env):
    env = chat_env
    response = ask(env.api, question="a " * 350)
    assert response.status_code == 200, response.text
    assert ask(env.api, question="x" * 1001).status_code == 422
    assert ask(env.api, date_from="2026-01-02", date_to="2026-01-01").status_code == 422

    def unencodable(_):
        raise ValueError("too many tokens")

    env.app.state.encoder.query_vector = unencodable
    response = ask(env.api)
    assert (
        response.status_code == 422 and response.json()["detail"]["code"] == "query_not_encodable"
    )


def test_history_read_write_failures(chat_env, monkeypatch):
    async def failed(*args, **kwargs):
        raise RuntimeError("sensitive database message")

    monkeypatch.setattr(chat_env.store.client, "upsert", failed)
    response = ask(chat_env.api)
    assert (
        response.status_code == 503
        and response.json()["detail"]["code"] == "chat_history_unavailable"
    )
    monkeypatch.setattr(chat_env.store.client, "collection_exists", failed)
    response = ask(chat_env.api)
    assert response.status_code == 503 and "sensitive" not in response.text


def test_provider_timeout_does_not_save(chat_env):
    env = chat_env
    env.app.state.chat_service.config.timeout_seconds = 0.01

    async def delayed(*_):
        await asyncio.sleep(0.1)
        return env.answers.result

    env.answers.answer = delayed
    response = ask(env.api)
    assert response.status_code == 502
    assert not env.store.client._client.collections


@pytest.mark.integration
def test_real_bm25_chat_history(hybrid_index):  # noqa: F811
    client, pinned, settings = hybrid_index
    settings.chat_collection = f"test_{uuid4().hex}_chat_turns"
    answers = Answers()
    try:
        with TestClient(create_app(settings, Encoder, llm_factory=answers)) as api:
            response = ask(api, question="wearable", mode="hybrid")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["index_generation"] == pinned.generation_id
            assert len(api.get(f"/api/v1/chat/{body['conversation_id']}").json()["turns"]) == 1
            assert client.collection_exists(settings.chat_collection)
            assert all(
                a.collection_name != settings.chat_collection for a in client.get_aliases().aliases
            )
    finally:
        if client.collection_exists(settings.chat_collection):
            client.delete_collection(settings.chat_collection)
