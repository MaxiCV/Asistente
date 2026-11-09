from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.catalog.identity import document_id, passage_id
from app.contracts import Document, SearchParams, SnapshotManifest
from pydantic import ValidationError


def test_doi_identity_is_independent_of_url_case_and_source():
    a = document_id("https://openalex.org/W1", "HTTPS://DOI.ORG/10.1234/Example")
    b = document_id("https://openalex.org/W2", "10.1234/example")
    assert a == b
    assert passage_id(a, "a" * 64, "b" * 64, 0) != passage_id(a, "a" * 64, "c" * 64, 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"title": " "},
        {"content_level": "abstract"},
        {"abstract": "Available abstract", "content_level": "metadata"},
        {"doi": "not-a-doi"},
        {"unexpected": "field"},
    ],
)
def test_document_rejects_invalid_or_invented_content(changes):
    data = {
        "document_id": uuid4(),
        "title": "Synthetic test fixture",
        "source_url": "https://openalex.org/W1",
        "content_level": "metadata",
        "identities": [
            {
                "openalex_id": "https://openalex.org/W1",
                "snapshot_id": "test_snapshot",
                "retrieved_at": datetime.now(UTC),
            }
        ],
    }
    with pytest.raises(ValidationError):
        Document.model_validate(data | changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"q": " "},
        {"q": "x" * 301},
        {"date_from": "2026-02-01", "date_to": "2026-01-01"},
        {"page": 0},
        {"page_size": 101},
        {"index_generation": "../escape"},
    ],
)
def test_search_rejects_invalid_input(changes):
    with pytest.raises(ValidationError):
        SearchParams.model_validate({"q": "caídas"} | changes)


def test_complete_snapshot_requires_hash_and_finish():
    with pytest.raises(ValidationError):
        SnapshotManifest(
            snapshot_id="test",
            status="complete",
            searches=["fixture"],
            from_date="2020-01-01",
            cutoff_date="2026-01-01",
            started_at=datetime.now(UTC),
            record_count=0,
        )


def test_generation_rejects_mixed_collections_and_counts(generation_manifest):
    data = generation_manifest().model_dump()
    for changes in (
        {"passages_collection": "passages_other"},
        {"abstract_count": 2},
        {"passage_count": 0},
    ):
        with pytest.raises(ValidationError):
            type(generation_manifest()).model_validate(data | changes)
