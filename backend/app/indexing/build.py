import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import numpy as np
from qdrant_client import models

from app.catalog.generations import collection_names, create_candidate_collections
from app.contracts import ChunkingConfig, Document, GenerationManifest, Passage, RunRecord
from app.core.files import atomic_json
from app.indexing.chunking import make_passages
from app.ingestion.normalize import select_documents


@contextmanager
def writer_lock(data_dir: Path):
    path = data_dir / "index-writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = path.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("Hay otro escritor o un bloqueo pendiente de mantenimiento") from None
    try:
        with stream:
            stream.write(datetime.now(UTC).isoformat())
            stream.flush()
            yield
    finally:
        path.unlink(missing_ok=True)


def filter_payload(document):
    return {
        "document_id": str(document.document_id),
        "document_type": document.document_type,
        "publication_type": document.publication_type,
        "publication_date": f"{document.publication_date}T00:00:00Z"
        if document.publication_date
        else None,
    }


def all_points(client, collection, *, vectors=False):
    offset = None
    while True:
        records, offset = client.scroll(
            collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=vectors,
        )
        yield from records
        if offset is None:
            return


def validate_collections(client, manifest, documents=None, passages=None):
    doc_points = list(all_points(client, manifest.documents_collection))
    passage_points = list(all_points(client, manifest.passages_collection, vectors=True))
    if len(doc_points) != manifest.document_count or len(passage_points) != manifest.passage_count:
        raise ValueError("Conteos del índice no coinciden con el manifiesto")
    ids = {str(point.id) for point in doc_points}
    catalog = {}
    for point in doc_points:
        payload = point.payload or {}
        document = Document.model_validate(payload.get("document"))
        if str(document.document_id) != str(point.id) or any(
            payload.get(key) != value for key, value in filter_payload(document).items()
        ):
            raise ValueError("Payload documental incoherente")
        catalog[str(point.id)] = document
    if sum(d.abstract is not None for d in catalog.values()) != manifest.abstract_count:
        raise ValueError("Cobertura de resúmenes incoherente")
    linked = set()
    for point in passage_points:
        payload = point.payload or {}
        passage = Passage.model_validate(payload.get("passage"))
        parent = catalog.get(str(passage.document_id))
        if (
            str(passage.passage_id) != str(point.id)
            or parent is None
            or filter_payload(passage) != filter_payload(parent)
            or any(payload.get(key) != value for key, value in filter_payload(passage).items())
            or passage.text_sha256 != hashlib.sha256(passage.text.encode()).hexdigest()
            or passage.token_count > manifest.embedding.max_tokens
        ):
            raise ValueError("Payload de fragmento incoherente")
        linked.add(payload.get("document_id"))
        vector = np.asarray((point.vector or {}).get("dense", []))
        if vector.shape != (manifest.embedding.dimensions,) or not np.isfinite(vector).all():
            raise ValueError("Vector inválido en colección candidata")
        if not np.isclose(np.linalg.norm(vector), 1, atol=1e-4):
            raise ValueError("Vector sin normalizar")
    if linked != ids:
        raise ValueError("Vínculos entre documentos y fragmentos incoherentes")
    if documents is not None:
        expected = {str(doc.document_id): doc.model_dump(mode="json") for doc in documents}
        if {str(p.id): (p.payload or {}).get("document") for p in doc_points} != expected:
            raise ValueError("Contenido documental diferente después de escribir")
    if passages is not None:
        expected = {str(p.passage_id): p.model_dump(mode="json") for p in passages}
        if {str(p.id): (p.payload or {}).get("passage") for p in passage_points} != expected:
            raise ValueError("Fragmentos diferentes después de escribir")


def build_generation(client, settings, embedding, generation, snapshot, csv_path, encoder_factory):
    names = collection_names(generation)
    with writer_lock(settings.data_dir):
        if any(client.collection_exists(name) for name in names):
            raise ValueError("La generación debe ser nueva; no se sobrescriben colecciones")
        target = settings.data_dir / "generations" / generation
        target.mkdir(parents=True, exist_ok=False)
        run = RunRecord(
            run_id=f"build_{uuid4().hex}",
            operation="build",
            status="running",
            started_at=datetime.now(UTC),
            generation_id=generation,
        )
        run_path = settings.data_dir / "runs" / f"{run.run_id}.json"
        atomic_json(run_path, run.model_dump(mode="json"))
        try:
            documents, selection = select_documents(snapshot, csv_path)
            run.snapshot_id = selection["snapshot_id"]
            chunking = ChunkingConfig()
            config = {
                "embedding": embedding.model_dump(mode="json"),
                "chunking": chunking.model_dump(mode="json"),
            }
            config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
            started = perf_counter()
            encoder = encoder_factory(settings, embedding)
            load_seconds = perf_counter() - started
            passages = [
                p for doc in documents for p in make_passages(doc, encoder, chunking, config_hash)
            ]
            create_candidate_collections(client, generation, embedding)
            for first in range(0, len(documents), 64):
                client.upsert(
                    names[0],
                    [
                        models.PointStruct(
                            id=str(doc.document_id),
                            vector={},
                            payload=filter_payload(doc) | {"document": doc.model_dump(mode="json")},
                        )
                        for doc in documents[first : first + 64]
                    ],
                    wait=True,
                )
            started = perf_counter()
            for first in range(0, len(passages), 16):
                batch = passages[first : first + 16]
                vectors = encoder.encode([p.text for p in batch])
                if (
                    vectors.shape != (len(batch), embedding.dimensions)
                    or not np.isfinite(vectors).all()
                ):
                    raise ValueError("Salida de embeddings inválida")
                client.upsert(
                    names[1],
                    [
                        models.PointStruct(
                            id=str(p.passage_id),
                            vector={"dense": vector.tolist()},
                            payload=filter_payload(p) | {"passage": p.model_dump(mode="json")},
                        )
                        for p, vector in zip(batch, vectors, strict=True)
                    ],
                    wait=True,
                )
            encode_seconds = perf_counter() - started
            manifest = GenerationManifest(
                generation_id=generation,
                created_at=datetime.now(UTC),
                documents_collection=names[0],
                passages_collection=names[1],
                snapshot_id=selection["snapshot_id"],
                snapshot_sha256=selection["snapshot_sha256"],
                review_csv_sha256=selection["review_csv_sha256"],
                config_sha256=config_hash,
                embedding=embedding,
                chunking=chunking,
                document_count=len(documents),
                passage_count=len(passages),
                abstract_count=selection["abstract_count"],
                excluded_count=selection["excluded_rows"],
                pending_count=selection["pending_rows"] + selection["unlisted_records"],
                publication_types=sorted(
                    {d.publication_type for d in documents if d.publication_type}
                ),
            )
            validate_collections(client, manifest, documents, passages)
            atomic_json(
                target / "build.json",
                {
                    "load_seconds": load_seconds,
                    "encode_and_write_seconds": encode_seconds,
                    "max_passage_tokens": max((p.token_count for p in passages), default=0),
                    "multi_passage_documents": sum(
                        sum(p.document_id == d.document_id for p in passages) > 1 for d in documents
                    ),
                    "offline_model": True,
                    "quality_evaluated": False,
                },
            )
            atomic_json(target / "manifest.json", manifest.model_dump(mode="json"))
            run.status = "succeeded"
        except BaseException:
            run.status = "failed"
            run.error_code = "build_failed"
            raise
        finally:
            run.finished_at = datetime.now(UTC)
            atomic_json(run_path, run.model_dump(mode="json"))
        return manifest.model_dump(mode="json")
