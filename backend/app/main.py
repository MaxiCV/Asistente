import logging
from contextlib import asynccontextmanager, contextmanager
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from app.catalog.generations import (
    GenerationRetired,
    GenerationUnavailable,
    pin_generation,
    read_generation,
)
from app.contracts import (
    CorpusResponse,
    DocumentResponse,
    ErrorResponse,
    GenerationId,
    SearchParams,
    SearchResponse,
)
from app.core.config import Settings, embedding_config
from app.core.qdrant import qdrant_connection
from app.embeddings.local import LocalEncoder
from app.search.service import QueryNotEncodable, get_document, latest_run, search_documents

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, encoder_factory=LocalEncoder) -> FastAPI:
    settings = settings or Settings()
    config = embedding_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.encoder = None
        started = perf_counter()
        try:
            app.state.encoder = encoder_factory(settings, config)
        except Exception as exc:
            logger.error("No se pudo cargar el modelo local: %s", type(exc).__name__)
        app.state.model_load_seconds = perf_counter() - started
        yield
        app.state.encoder = None

    api = FastAPI(
        title="Buscador de literatura sobre detección de caídas",
        version="0.2.0",
        description="Búsqueda semántica local con filtros y generación fijada. "
        "Calidad en Sprint 3.",
        lifespan=lifespan,
    )

    def error(status, code, message):
        return HTTPException(status_code=status, detail={"code": code, "message": message})

    @contextmanager
    def reader(generation=None, *, needs_model=True):
        if needs_model and api.state.encoder is None:
            raise error(503, "model_unavailable", "El modelo de búsqueda no está disponible.")
        try:
            with qdrant_connection(settings.qdrant_url, timeout=15) as client:
                pinned = pin_generation(client, settings.data_dir, config, generation)
                yield client, pinned
        except HTTPException:
            raise
        except GenerationRetired:
            raise error(
                409,
                "generation_retired",
                "Esta versión de la colección fue retirada. Inicia una nueva búsqueda.",
            ) from None
        except GenerationUnavailable:
            raise error(
                503,
                "corpus_unavailable",
                "La colección no está disponible o no es compatible con el modelo. "
                "Reintenta después del mantenimiento.",
            ) from None
        except Exception as exc:
            logger.warning("Lectura del corpus fallida: %s", type(exc).__name__)
            raise error(
                503,
                "dependency_unavailable",
                "No hay conexión con la colección. Comprueba el servicio local y reintenta.",
            ) from None

    @api.get("/api/v1/health", tags=["Disponibilidad"])
    def health():
        return {"status": "ok", "version": "0.2.0"}

    @api.get("/api/v1/ready", tags=["Disponibilidad"], responses={503: {"description": "No listo"}})
    def ready():
        checks = {"qdrant": False, "model": api.state.encoder is not None, "corpus": False}
        generation = None
        try:
            with qdrant_connection(settings.qdrant_url, timeout=3) as client:
                try:
                    pinned = pin_generation(client, settings.data_dir, config)
                    checks["qdrant"] = checks["corpus"] = True
                    generation = pinned.generation_id
                except GenerationUnavailable:
                    checks["qdrant"] = True
        except Exception:
            pass
        complete = all(checks.values())
        return JSONResponse(
            status_code=200 if complete else 503,
            content={
                "status": "ready" if complete else "not_ready",
                "checks": checks,
                "index_generation": generation,
            },
        )

    unavailable = {
        503: {"model": ErrorResponse, "description": "Dependencia no disponible"},
        409: {"model": ErrorResponse, "description": "Generación retirada"},
    }

    @api.get(
        "/api/v1/documents", response_model=SearchResponse, responses=unavailable, tags=["Corpus"]
    )
    def search(params: Annotated[SearchParams, Query()]):
        with reader(params.index_generation) as (client, pinned):
            try:
                return search_documents(client, pinned, api.state.encoder, params)
            except QueryNotEncodable:
                raise error(
                    422,
                    "query_not_encodable",
                    "Reduce la longitud de la consulta para procesarla con el modelo local.",
                ) from None

    @api.get(
        "/api/v1/documents/{document_id}",
        response_model=DocumentResponse,
        responses={**unavailable, 404: {"model": ErrorResponse}},
        tags=["Corpus"],
    )
    def detail(document_id: UUID, index_generation: GenerationId | None = None):
        with reader(index_generation, needs_model=False) as (client, pinned):
            document = get_document(client, pinned, document_id)
            if document is None:
                raise error(
                    404,
                    "document_not_found",
                    "El documento no existe en esta versión de la colección.",
                )
            return DocumentResponse(index_generation=pinned.generation_id, document=document)

    @api.get(
        "/api/v1/corpus", response_model=CorpusResponse, responses=unavailable, tags=["Corpus"]
    )
    def corpus():
        with reader(needs_model=False) as (_, pinned):
            try:
                record = read_generation(settings.data_dir, config, pinned.generation_id)
            except (OSError, ValueError) as exc:
                raise GenerationUnavailable("Evidencia de publicación inválida") from exc
            manifest = record.manifest
            run, invalid = latest_run(settings.data_dir)
            return CorpusResponse(
                index_generation=pinned.generation_id,
                document_count=manifest.document_count,
                abstract_count=manifest.abstract_count,
                abstract_coverage=manifest.abstract_count / manifest.document_count
                if manifest.document_count
                else 0,
                last_run=run,
                manifest=manifest,
                published_at=record.published_at,
                publication_types=manifest.publication_types,
                maintenance_status_unavailable=invalid,
            )

    return api


app = create_app()
