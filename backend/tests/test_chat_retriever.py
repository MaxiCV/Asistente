import hashlib

import pytest
from app.catalog.generations import GenerationUnavailable, pin_generation
from app.chat.retriever import CorpusRetriever
from app.contracts import RetrievalParams
from app.core.config import embedding_config
from app.search.service import ranked_groups, retrieve_passages
from test_search_flow import Encoder, indexed  # noqa: F401


def test_adapter_preserves_winning_passage_and_parent(indexed, monkeypatch):  # noqa: F811
    pinned = pin_generation(indexed.client, indexed.settings.data_dir, embedding_config())
    params = RetrievalParams(q="caída", document_type="all")
    groups = []

    def capture_groups(*args):
        result = ranked_groups(*args)
        groups[:] = result[1]
        return result

    # Synthetic vectors tie. Observe the same query used by the adapter instead
    # of assuming Qdrant breaks passage ties identically across separate queries.
    monkeypatch.setattr("app.search.service.ranked_groups", capture_groups)
    adapter = CorpusRetriever(indexed.client, pinned, Encoder(), params, 2)
    nodes = adapter.retrieve(params.q)
    assert len(nodes) == 2
    assert [n.node.node_id for n in nodes] == [str(g.hits[0].id) for g in groups[:2]]
    for node, item in zip(nodes, adapter.passages, strict=True):
        assert node.node.text == item.passage.text
        assert node.node.metadata["document_id"] == str(item.document.document_id)
        assert hashlib.sha256(node.node.text.encode()).hexdigest() == item.passage.text_sha256
        assert node.node.metadata["index_generation"] == pinned.generation_id
    filtered = retrieve_passages(
        indexed.client, pinned, Encoder(), RetrievalParams(q="fall", publication_type="review"), 5
    )
    assert len(filtered) == 1 and filtered[0].document.content_level == "metadata"


def test_retriever_rejects_corrupt_passage(indexed):  # noqa: F811
    pinned = pin_generation(indexed.client, indexed.settings.data_dir, embedding_config())
    params = RetrievalParams(q="fall", publication_type="review")
    item = retrieve_passages(indexed.client, pinned, Encoder(), params, 1)[0]
    changed = item.passage.model_dump(mode="json") | {"text": "Tampered"}
    indexed.client.set_payload(
        pinned.passages_collection,
        {"passage": changed},
        points=[str(item.passage.passage_id)],
        wait=True,
    )
    with pytest.raises(GenerationUnavailable, match="incoherente"):
        retrieve_passages(indexed.client, pinned, Encoder(), params, 1)
