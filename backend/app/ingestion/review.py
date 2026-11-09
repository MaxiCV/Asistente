import csv
from pathlib import Path

from app.contracts import ReviewRow
from app.ingestion.snapshot import read_snapshot

CSV_FIELDS = list(ReviewRow.model_fields)


def usable_abstract(inverted_index: object) -> bool:
    return reconstruct_abstract(inverted_index) is not None


def reconstruct_abstract(inverted_index: object) -> str | None:
    if not isinstance(inverted_index, dict) or not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, offsets in inverted_index.items():
        if not isinstance(word, str) or not word.strip() or not isinstance(offsets, list):
            return None
        for offset in offsets:
            if type(offset) is not int or offset < 0 or offset in positions:
                return None
            positions[offset] = word
    if not positions or set(positions) != set(range(len(positions))):
        return None
    return " ".join(positions[index] for index in range(len(positions))).strip()


def read_review(path: Path) -> list[ReviewRow]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError("Encabezado CSV distinto del contrato")
        rows = [ReviewRow.model_validate(row) for row in reader]
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.snapshot_id, row.openalex_id)
        if key in seen:
            raise ValueError("Par snapshot_id/openalex_id repetido")
        seen.add(key)
    return rows


def validate_review(csv_path: Path, snapshot_dir: Path) -> list[ReviewRow]:
    manifest, works = read_snapshot(snapshot_dir)
    rows = [row for row in read_review(csv_path) if row.snapshot_id == manifest.snapshot_id]
    for row in rows:
        if row.openalex_id not in works:
            raise ValueError("La revisión referencia un ID ausente del snapshot")
        has_abstract = usable_abstract(works[row.openalex_id].get("abstract_inverted_index"))
        if (row.tiene_resumen == "si") != has_abstract:
            raise ValueError("tiene_resumen no coincide con el contenido reconstruible")
    return rows
