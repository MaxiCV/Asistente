from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    @contextmanager
    def connection(*args, **kwargs):
        yield SimpleNamespace(get_aliases=lambda: SimpleNamespace(aliases=[]))

    monkeypatch.setattr("app.main.qdrant_connection", connection)
    settings = Settings(_env_file=None, ASISTENTE_DATA_DIR=tmp_path)
    app = create_app(settings, encoder_factory=lambda *_: object())
    with TestClient(app) as client:
        yield client


def test_health_is_distinct_from_corpus_readiness(client):
    assert client.get("/api/v1/health").status_code == 200
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"qdrant": True, "model": True, "corpus": False}


@pytest.mark.parametrize(
    "params",
    [
        {"q": " "},
        {"q": "a", "date_from": "2026-02-01", "date_to": "2026-01-01"},
        {"q": "a", "index_generation": "../escape"},
        {"q": "a", "page_size": 101},
    ],
)
def test_invalid_requests_rejected_before_future_search(client, params):
    assert client.get("/api/v1/documents", params=params).status_code == 422


def test_unpublished_corpus_does_not_claim_empty_results(client):
    response = client.get("/api/v1/documents", params={"q": "caídas"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "corpus_unavailable"
    schema = client.get("/openapi.json").json()
    assert "index_generation" in str(schema["components"]["schemas"]["SearchResponse"])


def test_unavailable_qdrant_is_not_ready(tmp_path, monkeypatch):
    class FailingClient:
        def get_aliases(self):
            raise ConnectionError("test outage")

    @contextmanager
    def connection(*args, **kwargs):
        yield FailingClient()

    monkeypatch.setattr("app.main.qdrant_connection", connection)
    app = create_app(
        Settings(_env_file=None, ASISTENTE_DATA_DIR=tmp_path), encoder_factory=lambda *_: object()
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["qdrant"] is False
