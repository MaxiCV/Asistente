import csv
import json
from datetime import UTC, datetime

import pytest
from app.core.files import sha256_file
from app.ingestion.review import CSV_FIELDS, read_review, usable_abstract, validate_review


def fixtures(tmp_path):
    snapshot = tmp_path / "fixture_snapshot"
    snapshot.mkdir()
    works = snapshot / "works.jsonl"
    works.write_text(
        json.dumps(
            {
                "id": "https://openalex.org/W1",
                "abstract_inverted_index": {"Synthetic": [0], "fixture": [1]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "snapshot_id": snapshot.name,
        "status": "complete",
        "searches": ["fixture"],
        "from_date": "2020-01-01",
        "cutoff_date": "2026-01-01",
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "record_count": 1,
        "works_sha256": sha256_file(works),
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    row = {
        "openalex_id": "https://openalex.org/W1",
        "snapshot_id": snapshot.name,
        "decision": "incluir",
        "motivo": "Dato sintético, solo para probar el contrato",
        "tecnologia": "ND",
        "evidencia": "ND",
        "tiene_resumen": "si",
        "fecha_revision": "2026-01-01",
        "nota_evidencia": "No constituye evidencia real",
    }
    return snapshot, row


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_review_checks_membership_and_abstract(tmp_path):
    snapshot, row = fixtures(tmp_path)
    path = tmp_path / "review.csv"
    write_csv(path, [row])
    assert len(validate_review(path, snapshot)) == 1
    for change, match in [
        ({"openalex_id": "https://openalex.org/W2"}, "ausente"),
        ({"tiene_resumen": "no"}, "resumen"),
    ]:
        write_csv(path, [row | change])
        with pytest.raises(ValueError, match=match):
            validate_review(path, snapshot)


def test_review_rejects_duplicates_corruption_and_incomplete_snapshot(tmp_path):
    snapshot, row = fixtures(tmp_path)
    path = tmp_path / "review.csv"
    write_csv(path, [row, row])
    with pytest.raises(ValueError, match="repetido"):
        read_review(path)
    write_csv(path, [row])
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest_path.write_text(json.dumps(manifest | {"status": "incomplete"}), "utf-8")
    with pytest.raises(ValueError, match="completo"):
        validate_review(path, snapshot)
    manifest_path.write_text(json.dumps(manifest), "utf-8")
    with (snapshot / "works.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="Hash"):
        validate_review(path, snapshot)


@pytest.mark.parametrize("index", [None, {}, {"x": [1]}, {"x": [0], "y": [0]}, {"x": [True]}])
def test_malformed_abstract_is_not_usable(index):
    assert not usable_abstract(index)
