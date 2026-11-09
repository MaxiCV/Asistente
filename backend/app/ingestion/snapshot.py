"""Lectura íntegra del snapshot, compartida por revisión y construcción offline."""

import json
from pathlib import Path

from app.contracts import SnapshotManifest
from app.core.files import sha256_file


def read_snapshot(snapshot_dir: Path) -> tuple[SnapshotManifest, dict[str, dict]]:
    manifest = SnapshotManifest.model_validate_json(
        (snapshot_dir / "manifest.json").read_text("utf-8")
    )
    if manifest.status != "complete" or manifest.snapshot_id != snapshot_dir.name:
        raise ValueError("Se requiere snapshot completo en su directorio identificado")
    for filename, expected in (
        ("works.jsonl", manifest.works_sha256),
        ("requests.jsonl", manifest.requests_sha256),
        ("quarantine.jsonl", manifest.quarantine_sha256),
    ):
        if expected is not None and sha256_file(snapshot_dir / filename) != expected:
            raise ValueError(f"Hash del snapshot incorrecto: {filename}")
    works: dict[str, dict] = {}
    with (snapshot_dir / "works.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            work = json.loads(line)
            if not isinstance(work, dict) or not isinstance(work.get("id"), str):
                raise ValueError("Registro de snapshot sin identificador")
            if work["id"] in works:
                raise ValueError("OpenAlex ID repetido en snapshot")
            works[work["id"]] = work
    if len(works) != manifest.record_count:
        raise ValueError("Conteo del snapshot incorrecto")
    return manifest, works
