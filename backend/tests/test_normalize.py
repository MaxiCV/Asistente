import csv
import json
from datetime import UTC, date, datetime

import pytest
from app.contracts import SnapshotManifest
from app.core.files import atomic_json, sha256_file
from app.ingestion.normalize import (
    canonical_openalex_id,
    export_documents,
    normalize_snapshot,
    normalize_work,
    prepare_review,
    select_documents,
)
from app.ingestion.review import CSV_FIELDS, reconstruct_abstract


def make_snapshot(tmp_path, works):
    directory = tmp_path / "synthetic"
    directory.mkdir()
    path = directory / "works.jsonl"
    path.write_text("".join(json.dumps(work) + "\n" for work in works), "utf-8")
    manifest = SnapshotManifest(
        snapshot_id="synthetic",
        status="complete",
        searches=["fixture"],
        from_date=date(2020, 1, 1),
        cutoff_date=date(2026, 11, 5),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        record_count=len(works),
        works_sha256=sha256_file(path),
    )
    atomic_json(directory / "manifest.json", manifest.model_dump(mode="json"))
    return directory, manifest


def work(number=1, **extra):
    return {"id": f"https://openalex.org/W{number}", "title": "Synthetic fall detection", **extra}


def review(snapshot, csv_path, decisions):
    prepare_review(snapshot, csv_path, date(2026, 11, 5))
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row, decision in zip(rows, decisions, strict=True):
        row["decision"] = decision
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_reconstruction_preserves_order_and_repeated_words():
    assert reconstruct_abstract({"fall": [2, 0], "a": [1]}) == "fall a fall"
    assert reconstruct_abstract({"bad": [0, 0]}) is None
    assert reconstruct_abstract({"bad": [0, 1000000000]}) is None


def test_nullable_metadata_stable_doi_and_identity(tmp_path):
    _, manifest = make_snapshot(tmp_path, [])
    doc, warnings = normalize_work(
        work(
            doi="HTTPS://doi.org/10.1234/TEST",
            publication_date="not-a-date",
            authorships=[{"author": {"display_name": "  Test   Author ", "orcid": "bad"}}],
        ),
        manifest,
    )
    assert doc.doi == "10.1234/test"
    assert doc.abstract is None and doc.content_level == "metadata"
    assert doc.language is None and doc.publication_date is None
    assert doc.authors[0].name == "Test Author" and doc.authors[0].orcid is None
    assert warnings == ["INVALID_DATE"]
    same, _ = normalize_work(work(2, doi="doi:10.1234/test"), manifest)
    assert same.document_id == doc.document_id
    assert canonical_openalex_id("http://openalex.org/w42") == "https://openalex.org/W42"


def test_dedup_keeps_provenance_not_title_similarity(tmp_path):
    snapshot, _ = make_snapshot(
        tmp_path,
        [
            work(1, doi="10.1234/same"),
            work(2, doi="https://doi.org/10.1234/SAME", abstract_inverted_index={"Test": [0]}),
            work(3),  # Same title does not mean same document.
        ],
    )
    docs, report = normalize_snapshot(snapshot)
    assert len(docs) == 2 and report["merged_records"] == 1
    merged = next(doc for doc in docs if doc.doi)
    assert merged.abstract == "Test"
    assert [i.openalex_id for i in merged.identities] == [work(1)["id"], work(2)["id"]]
    first = tmp_path / "first"
    second = tmp_path / "second"
    export_documents(snapshot, first)
    export_documents(snapshot, second)
    assert (first / "documents.jsonl").read_bytes() == (second / "documents.jsonl").read_bytes()


@pytest.mark.parametrize("decisions", [["incluir", "excluir"], ["incluir", "pendiente"]])
def test_contradictory_decisions_for_shared_doi_block_selection(tmp_path, decisions):
    snapshot, _ = make_snapshot(
        tmp_path,
        [
            work(1, doi="10.1234/shared"),
            work(2, doi="10.1234/shared"),
        ],
    )
    csv_path = tmp_path / "review.csv"
    review(snapshot, csv_path, decisions)
    with pytest.raises(ValueError, match="contradictorias"):
        select_documents(snapshot, csv_path)


def test_invalid_records_not_included_and_pending_never_autoaccepted(tmp_path):
    snapshot, _ = make_snapshot(tmp_path, [work(1, title=" "), work(2)])
    csv_path = tmp_path / "review.csv"
    review(snapshot, csv_path, ["incluir", "pendiente"])
    with pytest.raises(ValueError, match="cuarentena"):
        select_documents(snapshot, csv_path)
    other = tmp_path / "pending.csv"
    review(snapshot, other, ["pendiente", "pendiente"])
    assert select_documents(snapshot, other)[0] == []
    with pytest.raises(ValueError, match="conservar"):
        prepare_review(snapshot, other, date(2026, 11, 5))


def test_selection_filters_other_snapshots_and_exports_counts(tmp_path):
    snapshot, _ = make_snapshot(tmp_path, [work(1), work(2), work(3)])
    csv_path = tmp_path / "review.csv"
    review(snapshot, csv_path, ["incluir", "excluir", "pendiente"])
    with csv_path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writerow(
            dict(
                zip(
                    CSV_FIELDS,
                    [
                        "https://openalex.org/W999",
                        "other_snapshot",
                        "incluir",
                        "Otra captura",
                        "ND",
                        "ND",
                        "no",
                        "2026-11-05",
                        "No participa en esta selección",
                    ],
                    strict=True,
                )
            )
        )
    report = export_documents(snapshot, tmp_path / "selected", csv_path)
    assert report["included"] == report["metadata_only_count"] == 1
    assert report["excluded_rows"] == report["pending_rows"] == 1
    assert report["abstract_count"] == 0
    assert report["review_rows"] == 3


def test_classification_conflict_blocks_shared_doi(tmp_path):
    snapshot, _ = make_snapshot(
        tmp_path,
        [
            work(1, doi="10.1234/shared"),
            work(2, doi="10.1234/shared"),
        ],
    )
    csv_path = tmp_path / "review.csv"
    review(snapshot, csv_path, ["incluir", "incluir"])
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["tecnologia"] = "camara"
    rows[1]["tecnologia"] = "vestible"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="Clasificación contradictoria"):
        select_documents(snapshot, csv_path)


def test_quarantine_reason_and_invalid_optional_doi(tmp_path):
    snapshot, manifest = make_snapshot(
        tmp_path,
        [
            work(1, publication_date="2019-12-31"),
            work(2, language="fr"),
            work(3, title=""),
            work(4, doi="invalid-doi"),
        ],
    )
    docs, report = normalize_snapshot(snapshot)
    assert len(docs) == 1 and docs[0].doi is None
    assert {row["reason"] for row in report["quarantine"]} == {
        "OUTSIDE_DATE_RANGE",
        "UNSUPPORTED_LANGUAGE",
        "MISSING_TITLE",
    }
    assert report["warnings"] == [{"openalex_id": work(4)["id"], "codes": ["INVALID_DOI"]}]
    with pytest.raises(ValueError, match="INVALID_OPENALEX_ID"):
        normalize_work(work(id="https://other.example/W1"), manifest)
