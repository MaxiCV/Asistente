"""Functional retrieval and publication tests; synthetic vectors, no relevance evaluation."""

import json
import os
import re
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np
import pytest
from app.catalog.generations import pin_generation
from app.contracts import ChunkingConfig, Document, RunRecord, SearchParams
from app.core.config import Settings, embedding_config
from app.core.files import atomic_json
from app.indexing.build import all_points, build_generation
from app.indexing.chunking import make_passages
from app.indexing.publish import publish_generation
from app.main import create_app
from app.search.service import search_documents
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient, models


class Tokenizer:
    def encode(self, text, **kwargs):
        return [0] * (len(text.split()) + 2)

    def __call__(self, text, **kwargs):
        return {"offset_mapping": [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]}


class Encoder:
    def __init__(self, *args):
        self.config = embedding_config()
        self.model = SimpleNamespace(tokenizer=Tokenizer())

    def encode(self, texts):
        return np.array(
            [
                ([0.0, 1.0] if text.startswith("Beta") else [1.0, 0.0]) + [0.0] * 382
                for text in texts
            ]
        )

    def query_vector(self, text):
        return [1.0] + [0.0] * 383


def documents():
    return [
        Document(
            document_id=UUID(int=index),
            title=title,
            publication_date=published,
            publication_type=kind,
            source_url=f"https://openalex.org/W{index}",
            identities=[
                dict(
                    openalex_id=f"https://openalex.org/W{index}",
                    snapshot_id="test_snapshot",
                    retrieved_at=datetime.now(UTC),
                )
            ],
            abstract=abstract,
            content_level="abstract" if abstract else "metadata",
        )
        for index, title, published, kind, abstract in [
            (
                1,
                "Alpha caída en casa",
                date(2023, 1, 1),
                "article",
                " ".join(f"término{n}" for n in range(700)),
            ),
            (2, "Beta wearable", date(2024, 1, 1), "review", None),
            (3, "Tie cámara", None, "article", "Resumen corto"),
        ]
    ]


class ScopedClient:
    """Maps only this test's aliases; production aliases can never be changed."""

    def __init__(self, client, prefix):
        self.client, self.prefix = client, prefix

    def __getattr__(self, name):
        return getattr(self.client, name)

    def get_aliases(self):
        return models.CollectionsAliasesResponse(
            aliases=[
                models.AliasDescription(
                    alias_name=a.alias_name.removeprefix(self.prefix),
                    collection_name=a.collection_name,
                )
                for a in self.client.get_aliases().aliases
                if a.alias_name.startswith(self.prefix)
            ]
        )

    def update_collection_aliases(self, change_aliases_operations):
        operations = []
        for operation in change_aliases_operations:
            value = operation.model_dump(exclude_none=True)
            for body in value.values():
                body["alias_name"] = self.prefix + body["alias_name"]
            operations.append(type(operation).model_validate(value))
        return self.client.update_collection_aliases(operations)


@pytest.fixture(params=["memory", pytest.param("server", marks=pytest.mark.integration)])
def indexed(request, tmp_path, monkeypatch):
    if request.param == "server" and not os.getenv("QDRANT_TEST_URL"):
        pytest.skip("QDRANT_TEST_URL no configurado")
    underlying = (
        QdrantClient(url=os.environ["QDRANT_TEST_URL"], timeout=20)
        if (request.param == "server")
        else QdrantClient(":memory:")
    )
    prefix = f"test_s13_{uuid4().hex}_"
    client = ScopedClient(underlying, prefix)
    settings = Settings(_env_file=None, ASISTENTE_DATA_DIR=tmp_path)
    docs = documents()
    monkeypatch.setattr(
        "app.indexing.build.select_documents",
        lambda *_: (
            docs,
            {
                "snapshot_id": "test_snapshot",
                "snapshot_sha256": "a" * 64,
                "review_csv_sha256": "b" * 64,
                "abstract_count": 2,
                "excluded_rows": 0,
                "pending_rows": 0,
                "unlisted_records": 0,
            },
        ),
    )
    generations = []

    def build(encoder=Encoder):
        generation = f"test_s13_{uuid4().hex}"
        generations.append(generation)
        build_generation(client, settings, embedding_config(), generation, None, None, encoder)
        return generation

    generation = build()
    publish_generation(client, settings, embedding_config(), generation)

    @contextmanager
    def connection(*args, **kwargs):
        yield client

    monkeypatch.setattr("app.main.qdrant_connection", connection)
    try:
        with TestClient(create_app(settings, Encoder)) as api:
            yield SimpleNamespace(
                client=client,
                settings=settings,
                generation=generation,
                build=build,
                api=api,
                documents=docs,
            )
    finally:
        operations = [
            models.DeleteAliasOperation(
                delete_alias=models.DeleteAlias(alias_name=prefix + a.alias_name)
            )
            for a in client.get_aliases().aliases
        ]
        if operations:
            underlying.update_collection_aliases(operations)
        for generation in generations:
            for kind in ("documents", "passages"):
                name = f"{kind}_{generation}"
                if underlying.collection_exists(name):
                    underlying.delete_collection(name)
        underlying.close()


def test_chunks_preserve_long_unicode_text_and_stable_ids():
    doc = documents()[0]
    config = ChunkingConfig()
    chunks = make_passages(doc, Encoder(), config, "a" * 64)
    assert len(chunks) > 1 and all(p.token_count <= 512 for p in chunks)
    assert all(p.text.startswith(doc.title + "\n\n") for p in chunks)
    words = set(" ".join(p.text for p in chunks).split())
    assert set(doc.abstract.split()) <= words
    assert chunks[-1].text.endswith("término699")
    assert chunks == make_passages(doc, Encoder(), config, "a" * 64)
    with pytest.raises(ValueError, match="Título"):
        make_passages(doc.model_copy(update={"title": "x " * 600}), Encoder(), config, "a" * 64)


def test_grouping_tie_breaking_pagination_filters_and_detail(indexed):
    api = indexed.api
    assert api.get("/api/v1/ready").status_code == 200
    params = {"q": "caídas", "page_size": 1}
    first = api.get("/api/v1/documents", params=params).json()
    assert first["filtered_document_count"] == 3
    assert first["results"][0]["document"]["document_id"] == str(UUID(int=1))
    params.update(page=2, index_generation=first["index_generation"])
    second = api.get("/api/v1/documents", params=params).json()
    assert second["results"][0]["document"]["document_id"] == str(UUID(int=3))
    filtered = api.get(
        "/api/v1/documents",
        params={
            "q": "fall",
            "date_from": "2024-01-01",
            "date_to": "2024-01-01",
            "publication_type": "review",
        },
    ).json()
    assert filtered["filtered_document_count"] == 1
    assert filtered["results"][0]["document"]["content_level"] == "metadata"
    assert (
        api.get(
            f"/api/v1/documents/{UUID(int=2)}",
            params={
                "index_generation": first["index_generation"],
            },
        ).json()["document"]["abstract"]
        is None
    )
    assert api.get(f"/api/v1/documents/{uuid4()}").status_code == 404
    empty = api.get("/api/v1/documents", params={"q": "fall", "date_from": "2025-01-01"})
    assert empty.status_code == 200 and empty.json()["results"] == []


def test_publication_keeps_pinned_readers_and_rollback(indexed):
    cfg = embedding_config()
    old = pin_generation(indexed.client, indexed.settings.data_dir, cfg)
    receipt = indexed.settings.data_dir / "generations" / old.generation_id / "published.json"
    first_receipt = receipt.read_bytes()
    first_published_at = indexed.api.get("/api/v1/corpus").json()["published_at"]
    new = indexed.build()
    for kind in ("documents", "passages"):
        before = {
            str(p.id): p.payload for p in all_points(indexed.client, f"{kind}_{old.generation_id}")
        }
        after = {str(p.id): p.payload for p in all_points(indexed.client, f"{kind}_{new}")}
        assert before == after
    # A candidate cannot be requested before publication.
    assert (
        indexed.api.get(
            "/api/v1/documents",
            params={
                "q": "fall",
                "index_generation": new,
            },
        ).status_code
        == 409
    )
    publish_generation(indexed.client, indexed.settings, cfg, new)
    assert (
        search_documents(indexed.client, old, Encoder(), SearchParams(q="fall")).index_generation
        == old.generation_id
    )
    assert (
        indexed.api.get(
            "/api/v1/documents",
            params={
                "q": "fall",
                "index_generation": old.generation_id,
            },
        ).json()["index_generation"]
        == old.generation_id
    )
    publish_generation(indexed.client, indexed.settings, cfg, old.generation_id, rollback=True)
    assert receipt.read_bytes() == first_receipt
    assert indexed.api.get("/api/v1/corpus").json()["published_at"] == first_published_at
    assert (
        pin_generation(indexed.client, indexed.settings.data_dir, cfg).generation_id
        == old.generation_id
    )
    indexed.client.delete_collection(f"passages_{new}")
    assert (
        indexed.api.get(
            "/api/v1/documents",
            params={
                "q": "fall",
                "index_generation": new,
            },
        ).status_code
        == 409
    )


def test_active_without_receipt_stays_read_only_until_next_publication(indexed):
    cfg = embedding_config()
    folder = indexed.settings.data_dir / "generations" / indexed.generation
    receipt = folder / "published.json"
    receipt.unlink()
    response = indexed.api.get("/api/v1/corpus")
    assert response.status_code == 200
    assert response.json()["published_at"] == response.json()["manifest"]["created_at"]
    assert indexed.api.get("/api/v1/documents", params={"q": "fall"}).status_code == 200
    assert not receipt.exists()

    new = indexed.build()
    new_receipt = folder.parent / new / "published.json"
    with pytest.raises(ValueError, match="publicación"):
        publish_generation(indexed.client, indexed.settings, cfg, new, rollback=True)
    assert not receipt.exists() and not new_receipt.exists()
    assert indexed.api.get("/api/v1/corpus").json()["index_generation"] == indexed.generation

    publish_generation(indexed.client, indexed.settings, cfg, new)
    assert receipt.is_file() and new_receipt.is_file()
    historical = indexed.api.get(
        "/api/v1/documents", params={"q": "fall", "index_generation": indexed.generation}
    )
    assert historical.status_code == 200
    assert historical.json()["index_generation"] == indexed.generation


@pytest.mark.parametrize("fault", ["generation_id", "manifest_sha256", "malformed"])
def test_invalid_receipt_is_rejected_by_coverage_and_publication(indexed, fault):
    receipt = indexed.settings.data_dir / "generations" / indexed.generation / "published.json"
    if fault == "malformed":
        receipt.write_text("invalid", encoding="utf-8")
    else:
        content = json.loads(receipt.read_text("utf-8"))
        content[fault] = "other" if fault == "generation_id" else "f" * 64
        atomic_json(receipt, content)
    original = receipt.read_bytes()
    aliases = indexed.client.get_aliases()
    # La activa sigue disponible por alias: leer cobertura no repara el recibo.
    assert indexed.api.get("/api/v1/ready").status_code == 200
    assert indexed.api.get("/api/v1/documents", params={"q": "fall"}).status_code == 200
    response = indexed.api.get("/api/v1/corpus")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "corpus_unavailable"
    with pytest.raises(ValueError):
        publish_generation(indexed.client, indexed.settings, embedding_config(), indexed.generation)
    assert indexed.client.get_aliases() == aliases
    assert receipt.read_bytes() == original


def test_failed_build_and_corrupt_candidate_keep_active_collection(indexed):
    class BrokenEncoder(Encoder):
        def encode(self, texts):
            raise RuntimeError("simulated failure")

    with pytest.raises(RuntimeError):
        indexed.build(BrokenEncoder)
    response = indexed.api.get("/api/v1/corpus").json()
    assert response["document_count"] == 3 and response["abstract_count"] == 2
    assert response["last_run"]["status"] == "failed"
    new = indexed.build()
    indexed.client.set_payload(
        f"documents_{new}", {"publication_type": "corrupt"}, [str(UUID(int=1))]
    )
    with pytest.raises(ValueError, match="incoherente"):
        publish_generation(indexed.client, indexed.settings, embedding_config(), new)
    assert indexed.api.get("/api/v1/corpus").json()["index_generation"] == indexed.generation


def test_publication_timeout_after_commit_is_reconciled(indexed, monkeypatch):
    new = indexed.build()
    update = indexed.client.update_collection_aliases

    def timeout(change_aliases_operations):
        update(change_aliases_operations)
        raise TimeoutError("response lost after commit")

    monkeypatch.setattr(indexed.client, "update_collection_aliases", timeout)
    result = publish_generation(indexed.client, indexed.settings, embedding_config(), new)
    assert result["published"] == new
    assert indexed.api.get("/api/v1/ready").json()["index_generation"] == new


def test_interrupted_build_releases_lock_and_keeps_search_available(indexed):
    class InterruptedEncoder(Encoder):
        def encode(self, texts):
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        indexed.build(InterruptedEncoder)
    assert not (indexed.settings.data_dir / "index-writer.lock").exists()
    corpus = indexed.api.get("/api/v1/corpus").json()
    assert corpus["last_run"]["status"] == "failed"
    response = indexed.api.get("/api/v1/documents", params={"q": "fall"})
    assert response.status_code == 200
    assert response.json()["index_generation"] == indexed.generation
    indexed.build()  # A subsequent build is not blocked by the interrupted writer.


def test_alias_switch_inside_inflight_search_keeps_physical_generation(indexed, monkeypatch):
    new = indexed.build()
    query = indexed.client.query_points_groups
    observed = []

    def switch_then_query(*args, **kwargs):
        observed.append(kwargs["collection_name"])
        publish_generation(indexed.client, indexed.settings, embedding_config(), new)
        return query(*args, **kwargs)

    monkeypatch.setattr(indexed.client, "query_points_groups", switch_then_query)
    response = indexed.api.get("/api/v1/documents", params={"q": "fall"})
    assert response.status_code == 200
    assert response.json()["index_generation"] == indexed.generation
    assert observed == [f"passages_{indexed.generation}"]
    assert indexed.api.get("/api/v1/corpus").json()["index_generation"] == new
    publish_generation(
        indexed.client, indexed.settings, embedding_config(), indexed.generation, rollback=True
    )


def test_corrupt_documents_are_503_and_maintenance_log_is_separate(indexed):
    atomic_json(
        indexed.settings.data_dir / "runs" / "failed_test.json",
        RunRecord(
            run_id="failed_test",
            operation="fetch",
            status="failed",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            error_code="simulated_failure",
        ).model_dump(mode="json"),
    )
    corpus = indexed.api.get("/api/v1/corpus").json()
    assert corpus["last_run"]["status"] == "failed"
    assert corpus["abstract_coverage"] == 2 / 3 and corpus["manifest"]["document_count"] == 3
    indexed.client.set_payload(
        f"documents_{indexed.generation}", {"document": {}}, [str(UUID(int=1))]
    )
    response = indexed.api.get("/api/v1/documents", params={"q": "fall"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "corpus_unavailable"


def test_failed_publication_before_commit_preserves_aliases(indexed, monkeypatch):
    new = indexed.build()

    def fail(**kwargs):
        raise TimeoutError("request not committed")

    monkeypatch.setattr(indexed.client, "update_collection_aliases", fail)
    with pytest.raises(ValueError, match="no confirmada"):
        publish_generation(indexed.client, indexed.settings, embedding_config(), new)
    corpus = indexed.api.get("/api/v1/corpus").json()
    assert corpus["index_generation"] == indexed.generation
    assert corpus["last_run"]["status"] == "failed"


def test_incompatible_model_and_missing_encoder_are_not_empty_results(indexed, monkeypatch):
    incompatible = embedding_config().model_copy(update={"revision": "f" * 40})
    monkeypatch.setattr("app.main.embedding_config", lambda: incompatible)
    with TestClient(create_app(indexed.settings, Encoder)) as api:
        response = api.get("/api/v1/documents", params={"q": "fall"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "corpus_unavailable"
    monkeypatch.setattr("app.main.embedding_config", embedding_config)

    def unavailable(*args):
        raise OSError("model missing")

    with TestClient(create_app(indexed.settings, unavailable)) as api:
        assert api.get("/api/v1/ready").status_code == 503
        response = api.get("/api/v1/documents", params={"q": "fall"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "model_unavailable"
        assert api.get(f"/api/v1/documents/{UUID(int=2)}").status_code == 200
