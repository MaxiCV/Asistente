"""Pruebas funcionales; vectores densos sintéticos, BM25 real en servidor fijado."""

import os
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.catalog.generations import pin_generation
from app.contracts import Bm25Config, SearchParams
from app.core.config import Settings, embedding_config
from app.embeddings.bm25 import bm25_document, check_bm25_server
from app.indexing.build import all_points, build_generation, validate_collections
from app.indexing.publish import publish_generation
from app.main import create_app
from app.search.service import SearchModeUnavailable, search_documents
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient, models
from test_search_flow import Encoder, ScopedClient, documents


def test_old_generation_rejects_unsupported_modes():
    pinned = SimpleNamespace(manifest=SimpleNamespace(bm25=None))
    for mode in ("lexical", "hybrid"):
        with pytest.raises(SearchModeUnavailable):
            search_documents(None, pinned, None, SearchParams(q="fall", mode=mode))


def test_version_and_tokenizer_contract():
    with pytest.raises(ValueError, match="1.20.0"):
        check_bm25_server(
            SimpleNamespace(info=lambda: SimpleNamespace(version="1.14.0")), Bm25Config()
        )
    document = bm25_document("CAÍDA fall", Bm25Config())
    assert document.options["stemmer"] == {"type": "none"}
    assert document.options["stopwords"] == {"languages": [], "custom": []}


@pytest.fixture
def hybrid_index(tmp_path, monkeypatch):
    if not os.getenv("QDRANT_TEST_URL"):
        pytest.skip("QDRANT_TEST_URL no configurado")
    underlying = QdrantClient(url=os.environ["QDRANT_TEST_URL"], timeout=30, cloud_inference=True)
    prefix = f"test_s17_{uuid4().hex}_"
    client = ScopedClient(underlying, prefix)
    generation = f"test_s17_{uuid4().hex}"
    settings = Settings(_env_file=None, ASISTENTE_DATA_DIR=tmp_path)
    monkeypatch.setattr(
        "app.indexing.build.select_documents",
        lambda *_: (
            documents(),
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
    try:
        build_generation(
            client, settings, embedding_config(), generation, None, None, Encoder, bm25=Bm25Config()
        )
        publish_generation(client, settings, embedding_config(), generation)
        pinned = pin_generation(client, tmp_path, embedding_config())

        @contextmanager
        def connection(*args, **kwargs):
            yield client

        monkeypatch.setattr("app.main.qdrant_connection", connection)
        yield client, pinned, settings
    finally:
        aliases = client.get_aliases().aliases
        if aliases:
            underlying.update_collection_aliases(
                [
                    models.DeleteAliasOperation(
                        delete_alias=models.DeleteAlias(alias_name=prefix + a.alias_name)
                    )
                    for a in aliases
                ]
            )
        for kind in ("documents", "passages"):
            name = f"{kind}_{generation}"
            if underlying.collection_exists(name):
                underlying.delete_collection(name)
        underlying.close()


@pytest.mark.integration
def test_real_modes_filters_pagination_and_ids(hybrid_index):
    client, pinned, _ = hybrid_index

    def search(mode, q="wearable", **kwargs):
        return search_documents(client, pinned, Encoder(), SearchParams(q=q, mode=mode, **kwargs))

    semantic = search("semantic")
    lexical = search("lexical")
    hybrid = search("hybrid")
    assert semantic.results[0].document.document_id.int == 1
    assert [h.document.document_id.int for h in lexical.results] == [2]
    assert lexical.filtered_document_count == 3 and lexical.matched_document_count == 1
    assert not lexical.has_more
    assert hybrid.results[0].document.document_id.int == 2
    assert len(hybrid.results) == 3
    assert all(r.index_generation == pinned.generation_id for r in (semantic, lexical, hybrid))
    first = search("hybrid", page_size=1)
    second = search("hybrid", page_size=1, page=2, index_generation=pinned.generation_id)
    assert first.has_more and first.results[0] != second.results[0]
    assert search("lexical", "absentxyz").results == []
    assert search("lexical", "CAÍDA").results[0].document.document_id.int == 1
    for mode in ("semantic", "lexical", "hybrid"):
        filtered = search(mode, publication_type="review", date_from="2024-01-01")
        assert [h.document.document_id.int for h in filtered.results] == [2]
        assert search(mode, date_to="2020-01-01").results == []
    assert search("lexical", publication_type="article").results == []
    points = list(all_points(client, pinned.passages_collection, vectors=True))
    assert all(isinstance(p.vector["bm25"], models.SparseVector) for p in points)
    assert len({h.document.document_id for h in hybrid.results}) == 3


@pytest.mark.integration
def test_lexical_api_without_dense_model_and_invalid_mode(hybrid_index):
    _, _, settings = hybrid_index
    with TestClient(create_app(settings, encoder_factory=lambda *_: None)) as api:
        lexical = api.get("/api/v1/documents", params={"q": "wearable", "mode": "lexical"})
        assert lexical.status_code == 200
        assert lexical.json()["matched_document_count"] == 1
        assert (
            api.get("/api/v1/documents", params={"q": "fall", "mode": "hybrid"}).status_code == 503
        )
        assert (
            api.get("/api/v1/documents", params={"q": "fall", "mode": "unknown"}).status_code == 422
        )


@pytest.mark.integration
def test_validation_rejects_missing_sparse_vector(hybrid_index):
    client, pinned, _ = hybrid_index
    point = next(all_points(client, pinned.passages_collection, vectors=True))
    client.delete_vectors(
        pinned.passages_collection, vectors=["bm25"], points=[point.id], wait=True
    )
    with pytest.raises(ValueError, match="BM25"):
        validate_collections(client, pinned.manifest)
