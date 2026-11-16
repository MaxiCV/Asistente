"""Selección explícita de patentes capturadas; nunca aprueba todo un snapshot."""

import re
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import TypeAdapter

from app.contracts import (
    Document,
    GenerationId,
    PatentSelectionFile,
    PatentSnapshotManifest,
    PatentSourceIdentity,
)
from app.core.files import sha256_file
from app.ingestion.epo_ops import parse_page


def select_patents(data_dir: Path, selection_path: Path):
    selection = PatentSelectionFile.model_validate_json(selection_path.read_text("utf-8"))
    snapshots = {}
    selected = []
    seen = set()
    for row in selection.records:
        if row.publication_id in seen:
            raise ValueError("Patente duplicada en selección")
        seen.add(row.publication_id)
        if row.snapshot_id not in snapshots:
            target = data_dir / "patents/snapshots" / row.snapshot_id
            manifest = PatentSnapshotManifest.model_validate_json(
                (target / "manifest.json").read_text("utf-8")
            ).model_dump(mode="json")
            if (
                manifest.get("status") != "complete"
                or manifest.get("source") != "epo_ops"
                or manifest.get("snapshot_id") != row.snapshot_id
            ):
                raise ValueError("Snapshot de patentes incompleto o incompatible")
            TypeAdapter(GenerationId).validate_python(manifest["snapshot_id"])
            records = {}
            for name, digest in manifest["files"].items():
                if not re.fullmatch(r"page_[0-9]+\.xml|patents\.jsonl", name):
                    raise ValueError("Archivo de snapshot no permitido")
                if sha256_file(target / name) != digest:
                    raise ValueError("Hash de snapshot de patentes incorrecto")
                if name.endswith(".xml"):
                    _, docs = parse_page(
                        (target / name).read_bytes(),
                        row.snapshot_id,
                        datetime.fromisoformat(manifest["finished_at"]),
                    )
                    records.update({d.publication_id: d for d in docs})
            if len(records) != manifest["record_count"]:
                raise ValueError("Conteos de patentes incoherentes")
            snapshots[row.snapshot_id] = records
        patent = snapshots[row.snapshot_id].get(row.publication_id)
        if patent is None or not patent.title or patent.language not in ("es", "en"):
            raise ValueError("Patente seleccionada ausente o sin título ES/EN")
        if patent.abstract and patent.abstract_language not in ("es", "en"):
            raise ValueError("Resumen fuera del alcance ES/EN")
        selected.append(
            Document(
                document_id=uuid5(NAMESPACE_URL, f"epo_ops:{patent.publication_id}"),
                document_type="patent",
                publication_type="patent",
                title=patent.title,
                authors=[{"name": name} for name in patent.inventors],
                publication_date=patent.publication_date,
                language=patent.language,
                source_url="https://worldwide.espacenet.com/patent/search?q=pn%3D"
                + patent.publication_id.replace(".", ""),
                abstract=patent.abstract,
                content_level=patent.content_level,
                identities=[
                    PatentSourceIdentity(
                        publication_id=patent.publication_id,
                        snapshot_id=patent.snapshot_id,
                        retrieved_at=patent.retrieved_at,
                        applicants=patent.applicants,
                    )
                ],
            )
        )
    return selected
