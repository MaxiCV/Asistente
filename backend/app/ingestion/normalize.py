"""Transformación determinista, sin red ni escrituras en Qdrant."""

import csv
import re
from datetime import date
from pathlib import Path
from uuid import UUID

from pydantic import HttpUrl, TypeAdapter, ValidationError

from app.catalog.identity import document_id
from app.contracts import Author, Document, SnapshotManifest, SourceIdentity, canonical_doi
from app.core.files import atomic_json, sha256_file
from app.ingestion.review import CSV_FIELDS, read_review, reconstruct_abstract, validate_review
from app.ingestion.snapshot import read_snapshot


class NormalizationFailure(ValueError):
    """Motivo controlado de cuarentena; los valores opcionales inválidos son avisos."""


def canonical_openalex_id(value: object) -> str:
    if isinstance(value, str) and (
        match := re.fullmatch(r"(?:https?://openalex\.org/)?[wW]([0-9]+)", value.strip())
    ):
        return f"https://openalex.org/W{match[1]}"
    raise NormalizationFailure("INVALID_OPENALEX_ID")


def _text(value: object) -> str | None:
    return " ".join(value.split()) or None if isinstance(value, str) else None


def _url(value: object) -> str | None:
    try:
        return str(TypeAdapter(HttpUrl).validate_python(value))
    except ValidationError:
        return None


def normalize_work(work: dict, manifest: SnapshotManifest) -> tuple[Document, list[str]]:
    origin = canonical_openalex_id(work.get("id"))
    title = _text(work.get("title")) or _text(work.get("display_name"))
    if title is None:
        raise NormalizationFailure("MISSING_TITLE")
    warnings = []
    doi = None
    if work.get("doi"):
        try:
            doi = canonical_doi(work["doi"])
        except (ValueError, AttributeError):
            warnings.append("INVALID_DOI")
    published = None
    if work.get("publication_date"):
        try:
            published = date.fromisoformat(work["publication_date"])
        except (ValueError, TypeError):
            warnings.append("INVALID_DATE")
    if published and not manifest.from_date <= published <= manifest.cutoff_date:
        raise NormalizationFailure("OUTSIDE_DATE_RANGE")
    language = work.get("language")
    if language not in ("es", "en", None):
        raise NormalizationFailure("UNSUPPORTED_LANGUAGE")
    authors = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") if isinstance(authorship, dict) else None
        if not isinstance(author, dict) or not (name := _text(author.get("display_name"))):
            warnings.append("AUTHOR_WITHOUT_NAME")
            continue
        item = Author(name=name, orcid=_url(author.get("orcid")))
        if item not in authors:
            authors.append(item)
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    if work.get("abstract_inverted_index") is not None and abstract is None:
        warnings.append("UNUSABLE_ABSTRACT")
    location = work.get("primary_location") or {}
    source_url = _url(location.get("landing_page_url")) if isinstance(location, dict) else None
    if source_url is None:
        source_url = f"https://doi.org/{doi}" if doi else origin
    return Document(
        document_id=document_id(origin, doi),
        title=title,
        authors=authors,
        publication_date=published,
        language=language,
        doi=doi,
        source_url=source_url,
        publication_type=_text(work.get("type")),
        abstract=abstract,
        content_level="abstract" if abstract else "metadata",
        identities=[
            SourceIdentity(
                openalex_id=origin,
                snapshot_id=manifest.snapshot_id,
                retrieved_at=manifest.started_at,
            )
        ],
    ), warnings


def normalize_snapshot(snapshot_dir: Path) -> tuple[list[Document], dict]:
    manifest, works = read_snapshot(snapshot_dir)
    groups: dict[UUID, list[Document]] = {}
    quarantine = []
    warnings = []
    for key, work in sorted(works.items()):
        try:
            document, notices = normalize_work(work, manifest)
        except NormalizationFailure as exc:
            quarantine.append({"openalex_id": key, "reason": str(exc)})
            continue
        except (ValueError, TypeError, AttributeError):
            quarantine.append({"openalex_id": key, "reason": "INVALID_METADATA"})
            continue
        if notices:
            warnings.append({"openalex_id": key, "codes": notices})
        groups.setdefault(document.document_id, []).append(document)
    documents = []
    for doc_id, versions in sorted(groups.items()):
        # Mayor contenido disponible; empate por ID fuente, independiente del orden de captura.
        versions.sort(key=lambda doc: (-len(doc.abstract or ""), doc.identities[0].openalex_id))
        chosen = versions[0]
        identities = {
            identity.openalex_id: identity for doc in versions for identity in doc.identities
        }
        chosen.identities = [identities[key] for key in sorted(identities)]
        if len(versions) > 1:
            warnings.append({"document_id": str(doc_id), "codes": ["MERGED_SHARED_IDENTITY"]})
        documents.append(chosen)
    return documents, {
        "snapshot_id": manifest.snapshot_id,
        "snapshot_sha256": manifest.works_sha256,
        "raw_records": len(works),
        "normalized_unique": len(documents),
        "merged_records": sum(len(versions) - 1 for versions in groups.values()),
        "quarantine": quarantine,
        "warnings": warnings,
    }


def select_documents(snapshot_dir: Path, csv_path: Path) -> tuple[list[Document], dict]:
    rows = validate_review(csv_path, snapshot_dir)
    documents, report = normalize_snapshot(snapshot_dir)
    by_id = {row.openalex_id: row for row in rows}
    quarantined = {row["openalex_id"] for row in report["quarantine"]}
    if any(row.decision == "incluir" and row.openalex_id in quarantined for row in rows):
        raise ValueError("La revisión incluye registros en cuarentena")
    selected = []
    for document in documents:
        decisions = [by_id.get(identity.openalex_id) for identity in document.identities]
        values = {row.decision if row else "pendiente" for row in decisions}
        if len(values) > 1:
            raise ValueError(
                f"Decisiones contradictorias para identidad/DOI: {document.document_id}"
            )
        if values != {"incluir"}:
            continue
        for column, attribute in (("tecnologia", "technology"), ("evidencia", "evidence")):
            labels = {getattr(row, column) for row in decisions if row is not None}
            labels.discard("ND")
            if len(labels) > 1:
                raise ValueError(f"Clasificación contradictoria: {document.document_id}/{column}")
            if labels:
                setattr(document, attribute, next(iter(labels)))
        selected.append(document)
    report |= {
        "review_csv_sha256": sha256_file(csv_path),
        "review_rows": len(rows),
        "included": len(selected),
        "abstract_count": sum(doc.abstract is not None for doc in selected),
        "metadata_only_count": sum(doc.abstract is None for doc in selected),
        "excluded_rows": sum(row.decision == "excluir" for row in rows),
        "pending_rows": sum(row.decision == "pendiente" for row in rows),
        "unlisted_records": report["raw_records"] - len(rows),
    }
    return selected, report


def prepare_review(snapshot_dir: Path, csv_path: Path, review_date: date) -> dict:
    """Solo inicializa pendientes; nunca sobrescribe decisiones existentes."""
    manifest, works = read_snapshot(snapshot_dir)
    existing = read_review(csv_path) if csv_path.exists() else []
    if any(row.snapshot_id == manifest.snapshot_id for row in existing):
        raise ValueError("Ya hay revisión para este snapshot; conservar sus decisiones")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    # Crear un CSV nuevo obliga a elegir explícitamente cómo consolidar revisiones anteriores.
    with csv_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for key, work in works.items():
            writer.writerow(
                {
                    "openalex_id": key,
                    "snapshot_id": manifest.snapshot_id,
                    "decision": "pendiente",
                    "motivo": "Pendiente de revisión de título y resumen",
                    "tecnologia": "ND",
                    "evidencia": "ND",
                    "tiene_resumen": "si"
                    if reconstruct_abstract(work.get("abstract_inverted_index"))
                    else "no",
                    "fecha_revision": review_date.isoformat(),
                    "nota_evidencia": "Sin clasificación; revisar el contenido disponible",
                }
            )
    return {"rows": len(works), "csv": str(csv_path)}


def export_documents(snapshot_dir: Path, output: Path, csv_path: Path | None = None) -> dict:
    if csv_path:
        documents, report = select_documents(snapshot_dir, csv_path)
    else:
        documents, report = normalize_snapshot(snapshot_dir)
    output.mkdir(parents=True, exist_ok=False)
    path = output / "documents.jsonl"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for document in documents:
            stream.write(document.model_dump_json() + "\n")
    report["documents_sha256"] = sha256_file(path)
    report["selected_by_review"] = csv_path is not None
    atomic_json(output / "report.json", report)
    return report
