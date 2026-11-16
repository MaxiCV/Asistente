import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path

from pydantic import ValidationError
from qdrant_client import models

from app.catalog.generations import GenerationUnavailable
from app.contracts import Document, Passage, RunRecord, SearchHit, SearchResponse
from app.embeddings.bm25 import bm25_document, validate_bm25_collection


class QueryNotEncodable(ValueError):
    pass


class SearchModeUnavailable(ValueError):
    pass


def make_filter(params):
    conditions = (
        []
        if params.document_type == "all"
        else [
            models.FieldCondition(
                key="document_type",
                match=models.MatchValue(value=params.document_type),
            )
        ]
    )
    if params.publication_type:
        conditions.append(
            models.FieldCondition(
                key="publication_type",
                match=models.MatchValue(value=params.publication_type),
            )
        )
    if params.date_from or params.date_to:
        conditions.append(
            models.FieldCondition(
                key="publication_date",
                range=models.DatetimeRange(
                    gte=datetime.combine(params.date_from, time.min, UTC)
                    if params.date_from
                    else None,
                    lte=datetime.combine(params.date_to, time.max, UTC) if params.date_to else None,
                ),
            )
        )
    return models.Filter(must=conditions)


def read_document(point):
    try:
        document = Document.model_validate((point.payload or {}).get("document"))
    except ValidationError as exc:
        raise GenerationUnavailable("Documento indexado inválido") from exc
    if str(document.document_id) != str(point.id):
        raise GenerationUnavailable("Identidad documental incoherente")
    return document


def get_document(client, pinned, document_id):
    records = client.retrieve(
        pinned.documents_collection, ids=[str(document_id)], with_payload=True
    )
    return read_document(records[0]) if records else None


def ranked_groups(client, pinned, encoder, params):
    if params.mode != "semantic":
        if pinned.manifest.bm25 is None:
            raise SearchModeUnavailable("La generación no contiene BM25")
        try:
            validate_bm25_collection(client, pinned.passages_collection)
        except ValueError as exc:
            raise GenerationUnavailable(str(exc)) from exc
    filters = make_filter(params)
    count = client.count(pinned.documents_collection, count_filter=filters, exact=True).count
    if count > 10000:
        raise GenerationUnavailable("La colección excede el límite de paginación de esta versión")
    ordered = []
    if count:
        query = {}
        if params.mode != "lexical":
            try:
                vector = list(encoder.query_vector(params.q))
            except ValueError as exc:
                raise QueryNotEncodable from exc
            query = {"query": vector, "using": "dense"}
        if params.mode == "lexical":
            query = {"query": bm25_document(params.q, pinned.manifest.bm25), "using": "bm25"}
        elif params.mode == "hybrid":
            # Recuperar todos los fragmentos del lote: no truncar grupos antes de paginar.
            limit = pinned.manifest.passage_count
            if limit > 10000:
                raise GenerationUnavailable("La fusión exacta admite hasta 10000 fragmentos")
            query = {
                "prefetch": [
                    models.Prefetch(
                        query=vector,
                        using="dense",
                        filter=filters,
                        limit=limit,
                        params=models.SearchParams(exact=True),
                    ),
                    models.Prefetch(
                        query=bm25_document(params.q, pinned.manifest.bm25),
                        using="bm25",
                        filter=filters,
                        limit=limit,
                    ),
                ],
                "query": models.FusionQuery(fusion=models.Fusion.RRF),
            }
        groups = client.query_points_groups(
            collection_name=pinned.passages_collection,
            **query,
            query_filter=filters,
            group_by="document_id",
            group_size=1,
            limit=count,
            search_params=models.SearchParams(exact=True),
            with_payload=False,
            with_vectors=False,
        ).groups
        matched_count = len(groups)
        if (
            (params.mode != "lexical" and matched_count != count)
            or matched_count > count
            or len({str(group.id) for group in groups}) != matched_count
        ):
            raise GenerationUnavailable("Grupos documentales incompletos o duplicados")
        if any(not group.hits for group in groups):
            raise GenerationUnavailable("Grupo sin fragmentos")
        ordered = sorted(groups, key=lambda group: (-group.hits[0].score, str(group.id)))
    return count, ordered


def group_documents(client, pinned, selected):
    if not selected:
        return {}
    records = client.retrieve(
        pinned.documents_collection, ids=[str(group.id) for group in selected], with_payload=True
    )
    documents = {str(record.id): read_document(record) for record in records}
    if set(documents) != {str(group.id) for group in selected}:
        raise GenerationUnavailable("Catálogo y fragmentos inconsistentes")
    return documents


def search_documents(client, pinned, encoder, params):
    count, ordered = ranked_groups(client, pinned, encoder, params)
    matched_count = len(ordered)
    first = (params.page - 1) * params.page_size
    selected = ordered[first : first + params.page_size]
    documents = group_documents(client, pinned, selected)
    hits = [
        SearchHit(document=documents[str(group.id)], score=group.hits[0].score)
        for group in selected
    ]
    return SearchResponse(
        mode=params.mode,
        matched_document_count=matched_count,
        index_generation=pinned.generation_id,
        results=hits,
        page=params.page,
        page_size=params.page_size,
        has_more=params.page * params.page_size < matched_count,
        filtered_document_count=count,
    )


@dataclass(frozen=True)
class RetrievedPassage:
    passage: Passage
    document: Document
    score: float


def retrieve_passages(client, pinned, encoder, params, top_k):
    _, ordered = ranked_groups(client, pinned, encoder, params)
    selected = ordered[:top_k]
    documents = group_documents(client, pinned, selected)
    if not selected:
        return []
    records = client.retrieve(
        pinned.passages_collection, ids=[str(g.hits[0].id) for g in selected], with_payload=True
    )
    points = {str(record.id): record for record in records}
    if set(points) != {str(g.hits[0].id) for g in selected}:
        raise GenerationUnavailable("Fragmentos recuperados incompletos")
    result = []
    for group in selected:
        point = points[str(group.hits[0].id)]
        try:
            passage = Passage.model_validate((point.payload or {}).get("passage"))
        except ValidationError as exc:
            raise GenerationUnavailable("Fragmento indexado inválido") from exc
        document = documents[str(group.id)]
        if (
            str(passage.passage_id) != str(point.id)
            or passage.document_id != document.document_id
            or passage.document_type != document.document_type
            or passage.publication_type != document.publication_type
            or passage.publication_date != document.publication_date
            or passage.token_count > pinned.manifest.embedding.max_tokens
            or hashlib.sha256(passage.text.encode()).hexdigest() != passage.text_sha256
        ):
            raise GenerationUnavailable("Identidad o contenido del fragmento incoherente")
        result.append(RetrievedPassage(passage, document, group.hits[0].score))
    return result


def latest_run(data_dir: Path):
    records = []
    invalid = False
    for path in (data_dir / "runs").glob("*.json"):
        try:
            records.append(RunRecord.model_validate_json(path.read_text("utf-8")))
        except (OSError, ValidationError):
            invalid = True
    return max(records, key=lambda run: (run.started_at, run.run_id), default=None), invalid
