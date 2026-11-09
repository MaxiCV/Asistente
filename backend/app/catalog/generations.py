from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from qdrant_client import QdrantClient, models

from app.contracts import EmbeddingConfig, GenerationId, GenerationManifest, PublicationReceipt
from app.core.files import atomic_json, sha256_file


class GenerationUnavailable(Exception):
    """No hay una pareja publicada válida y compatible."""


class GenerationRetired(Exception):
    """La generación solicitada no está publicada o ya no está disponible."""


class _PublicationUnavailable(ValueError):
    """No existe un recibo legible que permita consultar una generación histórica."""


@dataclass(frozen=True)
class GenerationRecord:
    """Manifiesto compatible y evidencia de publicación, sin resolver los alias activos."""

    manifest: GenerationManifest
    receipt: PublicationReceipt | None

    @property
    def published_at(self) -> datetime:
        return self.receipt.published_at if self.receipt else self.manifest.created_at


@dataclass(frozen=True)
class PinnedGeneration:
    generation_id: str
    documents_collection: str
    passages_collection: str
    manifest: GenerationManifest


def collection_names(generation: str) -> tuple[str, str]:
    generation = TypeAdapter(GenerationId).validate_python(generation)
    return f"documents_{generation}", f"passages_{generation}"


def _manifest_path(data_dir: Path, generation: str) -> Path:
    collection_names(generation)  # Validar antes de construir cualquier ruta.
    return data_dir / "generations" / generation / "manifest.json"


def _read_manifest(path: Path, generation: str, embedding: EmbeddingConfig) -> GenerationManifest:
    manifest = GenerationManifest.model_validate_json(path.read_text("utf-8"))
    if manifest.generation_id != generation or manifest.embedding != embedding:
        raise ValueError("Modelo o manifiesto incompatible con la generación")
    # GenerationManifest valida que los nombres físicos correspondan a su generation_id.
    return manifest


def _read_receipt(
    manifest_path: Path, generation: str, *, required: bool
) -> PublicationReceipt | None:
    path = manifest_path.with_name("published.json")
    if not required and not path.exists():
        return None
    try:
        receipt = PublicationReceipt.model_validate_json(path.read_text("utf-8"))
    except (OSError, ValidationError) as exc:
        raise _PublicationUnavailable("Registro de publicación ausente o inválido") from exc
    if receipt.generation_id != generation:
        raise ValueError("Registro de publicación incompatible")
    if sha256_file(manifest_path) != receipt.manifest_sha256:
        raise ValueError("Manifiesto publicado alterado")
    return receipt


def read_generation(
    data_dir: Path,
    embedding: EmbeddingConfig,
    generation: str,
    *,
    require_publication: bool = False,
) -> GenerationRecord:
    """Lee evidencia local sin escribir ni declarar activa una generación.

    Si existe recibo, siempre se valida; recuperación e histórico lo exigen.
    La resolución activa usa solo alias y manifiesto, incluso si falta el recibo.
    """
    path = _manifest_path(data_dir, generation)
    receipt = _read_receipt(path, generation, required=require_publication)
    return GenerationRecord(_read_manifest(path, generation, embedding), receipt)


def record_publication(
    data_dir: Path, embedding: EmbeddingConfig, generation: str
) -> PublicationReceipt:
    """Solo escritor con bloqueo y alias confirmados; conserva la primera publicación."""
    record = read_generation(data_dir, embedding, generation)
    if record.receipt is not None:
        return record.receipt
    path = _manifest_path(data_dir, generation)
    receipt = PublicationReceipt(
        generation_id=generation,
        manifest_sha256=sha256_file(path),
        published_at=datetime.now(UTC),
    )
    atomic_json(path.with_name("published.json"), receipt.model_dump(mode="json"))
    return receipt


def create_candidate_collections(
    client: QdrantClient,
    generation: str,
    embedding: EmbeddingConfig,
) -> tuple[str, str]:
    """Solo CLI. Repetible para candidatas; nunca altera colecciones con alias."""
    names = collection_names(generation)
    aliases = client.get_aliases().aliases
    if any(alias.collection_name in names for alias in aliases):
        raise ValueError("No se permite modificar una generación publicada")
    for name in names:
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config={}
                if name == names[0]
                else {
                    "dense": models.VectorParams(
                        size=embedding.dimensions,
                        distance=models.Distance.COSINE,
                    ),
                },
            )
        info = client.get_collection(name)
        expected = (
            {}
            if name == names[0]
            else {
                "dense": models.VectorParams(
                    size=embedding.dimensions, distance=models.Distance.COSINE
                ),
            }
        )
        actual = info.config.params.vectors
        if name == names[0]:
            if actual not in ({}, None):
                raise ValueError("documents debe ser una colección sin vectores")
        elif (
            not isinstance(actual, dict)
            or set(actual) != {"dense"}
            or actual["dense"].size != expected["dense"].size
            or actual["dense"].distance != expected["dense"].distance
        ):
            raise ValueError("Configuración vectorial incompatible")
        for field, kind in {
            "document_id": models.PayloadSchemaType.KEYWORD,
            "document_type": models.PayloadSchemaType.KEYWORD,
            "publication_type": models.PayloadSchemaType.KEYWORD,
            "publication_date": models.PayloadSchemaType.DATETIME,
        }.items():
            if field in info.payload_schema:
                if info.payload_schema[field].data_type != kind:
                    raise ValueError("Índice de payload incompatible")
            else:
                client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=kind,
                    wait=True,
                )
    return names


def pin_active_generation(
    client: QdrantClient,
    data_dir: Path,
    embedding: EmbeddingConfig,
) -> PinnedGeneration:
    # Una sola lectura de todos los alias. El consumidor usa los nombres físicos devueltos.
    aliases = {a.alias_name: a.collection_name for a in client.get_aliases().aliases}
    return _pin_aliases(aliases, data_dir, embedding)


def _pin_aliases(aliases, data_dir, embedding):
    documents, passages = aliases.get("documents"), aliases.get("passages")
    if not documents or not passages or not documents.startswith("documents_"):
        raise GenerationUnavailable("No hay corpus publicado")
    generation = documents.removeprefix("documents_")
    try:
        if collection_names(generation) != (documents, passages):
            raise GenerationUnavailable("Los alias no pertenecen a la misma generación")
        manifest = _read_manifest(_manifest_path(data_dir, generation), generation, embedding)
    except (OSError, ValidationError) as exc:
        raise GenerationUnavailable("Manifiesto ausente o inválido") from exc
    except ValueError as exc:
        raise GenerationUnavailable(str(exc)) from exc
    return PinnedGeneration(generation, documents, passages, manifest)


def pin_generation(client, data_dir, embedding, requested=None):
    aliases = {a.alias_name: a.collection_name for a in client.get_aliases().aliases}
    if requested is None:
        pinned = _pin_aliases(aliases, data_dir, embedding)
    else:
        names = collection_names(requested)
        if (aliases.get("documents"), aliases.get("passages")) == names:
            pinned = _pin_aliases(aliases, data_dir, embedding)
        else:
            # No aceptar candidatas simplemente porque tengan manifiesto.
            try:
                record = read_generation(data_dir, embedding, requested, require_publication=True)
            except (_PublicationUnavailable, FileNotFoundError) as exc:
                raise GenerationRetired("La versión solicitada ya no está disponible") from exc
            except (OSError, ValueError) as exc:
                raise GenerationUnavailable(str(exc)) from exc
            pinned = PinnedGeneration(requested, *names, record.manifest)
    for name in (pinned.documents_collection, pinned.passages_collection):
        if not client.collection_exists(name):
            if requested:
                raise GenerationRetired("La versión solicitada fue retirada")
            raise GenerationUnavailable("Colección publicada ausente")
    return pinned
