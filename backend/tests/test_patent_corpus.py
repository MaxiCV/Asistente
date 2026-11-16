import json
from datetime import UTC, datetime

import pytest
from app.catalog.generations import pin_generation
from app.contracts import SearchParams
from app.core.config import Settings, embedding_config
from app.core.files import atomic_json, sha256_file
from app.indexing.publish import publish_generation
from app.ingestion.epo_ops import parse_page
from app.ingestion.patent_corpus import select_patents
from app.search.service import search_documents
from test_epo_ops import page
from test_search_flow import Encoder, indexed  # noqa: F401


@pytest.fixture
def selected(tmp_path):
    folder = tmp_path / "patents/snapshots/test_patent"
    folder.mkdir(parents=True)
    (folder / "page_0001.xml").write_bytes(page())
    (folder / "patents.jsonl").write_text("", encoding="utf-8")
    atomic_json(
        folder / "manifest.json",
        {
            "source": "epo_ops",
            "snapshot_id": "test_patent",
            "status": "complete",
            "finished_at": datetime.now(UTC).isoformat(),
            "record_count": 1,
            "files": {f: sha256_file(folder / f) for f in ("page_0001.xml", "patents.jsonl")},
        },
    )
    selection = tmp_path / "selection.json"
    atomic_json(
        selection,
        {
            "records": [
                {
                    "snapshot_id": "test_patent",
                    "publication_id": "EP.100.A1",
                    "reason": "Synthetic fixture",
                    "scope": "test",
                }
            ]
        },
    )
    return tmp_path, folder, selection


def test_selection_stable_ids_and_provenance(selected):
    root, _, selection = selected
    first = select_patents(root, selection)[0]
    assert first.document_type == "patent"
    assert first.identities[0].publication_id == "EP.100.A1"
    assert select_patents(root, selection)[0].document_id == first.document_id


@pytest.mark.parametrize("missing", ["patents.jsonl", "page_0001.xml"])
def test_complete_manifest_requires_both_export_and_raw_xml(selected, missing):
    root, folder, selection = selected
    manifest = json.loads((folder / "manifest.json").read_text())
    del manifest["files"][missing]
    atomic_json(folder / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Snapshot OPS completo"):
        select_patents(root, selection)


@pytest.mark.parametrize("invalid", ["hash", "incomplete", "duplicate", "missing"])
def test_selection_rejects_invalid_sources(selected, invalid):
    root, folder, selection = selected
    if invalid == "hash":
        (folder / "page_0001.xml").write_bytes(b"broken")
    elif invalid == "incomplete":
        m = json.loads((folder / "manifest.json").read_text())
        m["status"] = "incomplete"
        atomic_json(folder / "manifest.json", m)
    else:
        data = json.loads(selection.read_text())
        if invalid == "duplicate":
            data["records"] *= 2
        else:
            data["records"][0]["publication_id"] = "EP.999.A1"
        atomic_json(selection, data)
    with pytest.raises(ValueError):
        select_patents(root, selection)


def test_credential_aliases_are_secret(monkeypatch):
    monkeypatch.setenv("EPO_CONSUMER_KEY", "synthetic-key")
    monkeypatch.setenv("EPO_CONSUMER_SECRET", "synthetic-secret")
    monkeypatch.delenv("EPO_OPS_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("EPO_OPS_CONSUMER_SECRET", raising=False)
    s = Settings(_env_file=None)
    assert s.epo_ops_consumer_key.get_secret_value() == "synthetic-key"
    assert "synthetic-secret" not in repr(s)


def test_inventors_and_applicants_use_original_names():
    parties = b"""<parties><inventors>
    <inventor data-format="epodoc"><inventor-name>
    <name>ROJAS OSCAR [CL]</name></inventor-name></inventor>
    <inventor data-format="original"><inventor-name>
    <name>ROJAS OSCAR</name></inventor-name></inventor>
    </inventors><applicants><applicant data-format="original"><applicant-name>
    <name>TEST UNIVERSITY</name></applicant-name></applicant></applicants></parties>"""
    xml = page().replace(b"</bibliographic-data>", parties + b"</bibliographic-data>")
    document = parse_page(xml, "test", datetime.now(UTC))[1][0]
    assert document.inventors == ["ROJAS OSCAR"]
    assert document.applicants == ["TEST UNIVERSITY"]


def test_mixed_corpus_filters_and_detail(indexed, selected):  # noqa: F811
    root, _, selection = selected
    patent = select_patents(root, selection)[0]
    generation = indexed.build(patent_selection=selection)
    publish_generation(indexed.client, indexed.settings, embedding_config(), generation)
    pinned = pin_generation(indexed.client, indexed.settings.data_dir, embedding_config())
    for kind, expected in [("all", 4), ("publication", 3), ("patent", 1)]:
        result = search_documents(
            indexed.client, pinned, Encoder(), SearchParams(q="WAND", document_type=kind)
        )
        assert result.filtered_document_count == expected
        assert len(result.results) == expected
    response = indexed.api.get(f"/api/v1/documents/{patent.document_id}")
    assert response.status_code == 200
    assert response.json()["document"]["identities"][0]["publication_id"] == "EP.100.A1"
