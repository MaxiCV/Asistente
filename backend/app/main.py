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
from app.chat.errors import ChatError
from app.chat.history import ChatHistoryStore
from app.chat.llm import GeminiAnswerer
from app.chat.service import ChatService
from app.contracts import (
    ChatConfig,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    CorpusResponse,
    DocumentResponse,
    ErrorResponse,
    GenerationId,
    RequestValidationResponse,
    SearchParams,
    SearchResponse,
)
from app.core.config import Settings, chat_config, embedding_config
from app.core.qdrant import qdrant_connection
from app.embeddings.local import LocalEncoder
from app.search.service import (
    QueryNotEncodable,
    SearchModeUnavailable,
    get_document,
    latest_run,
    search_documents,
)

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    encoder_factory=LocalEncoder,
    *,
    llm_factory=GeminiAnswerer,
    history_factory=ChatHistoryStore,
    chat_settings: ChatConfig | None = None,
) -> FastAPI:
    settings = settings or Settings()
    config = embedding_config()
    chat_options = chat_settings or chat_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.encoder = None
        started = perf_counter()
        try:
            app.state.encoder = encoder_factory(settings, config)
        except Exception as exc:
            logger.error("No se pudo cargar el modelo local: %s", type(exc).__name__)
        app.state.model_load_seconds = perf_counter() - started
        app.state.chat_history = history_factory(settings)
        app.state.chat_service = ChatService(
            settings, chat_options, app.state.chat_history, retrieve_chat, llm_factory
        )
        try:
            yield
        finally:
            app.state.encoder = None
            await app.state.chat_history.aclose()

    api = FastAPI(
        title="Buscador de literatura sobre detección de caídas",
        version="0.3.0",
        description="Búsqueda semántica, BM25 e híbrida de publicaciones y patentes. "
        "Chat RAG con LlamaIndex, Gemini, referencias y generación fijada. Calidad en Sprint 3.",
        lifespan=lifespan,
    )

    def error(status, code, message):
        return HTTPException(status_code=status, detail={"code": code, "message": message})

    @api.exception_handler(ChatError)
    async def chat_error_handler(_, exc):
        return JSONResponse(
            status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}}
        )

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
        return {"status": "ok", "version": "0.3.0"}

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
                "chat": bool(settings.gemini_api_key),
            },
        )

    unavailable = {
        503: {"model": ErrorResponse, "description": "Dependencia no disponible"},
        409: {
            "model": ErrorResponse,
            "description": "generation_retired o search_mode_unavailable",
        },
        422: {
            "model": ErrorResponse | RequestValidationResponse,
            "description": "Validación de entrada o query_not_encodable",
        },
    }

    @api.get(
        "/api/v1/documents", response_model=SearchResponse, responses=unavailable, tags=["Corpus"]
    )
    def search(params: Annotated[SearchParams, Query()]):
        with reader(params.index_generation, needs_model=params.mode != "lexical") as (
            client,
            pinned,
        ):
            try:
                return search_documents(client, pinned, api.state.encoder, params)
            except SearchModeUnavailable:
                raise error(
                    409,
                    "search_mode_unavailable",
                    "Esta versión admite solo búsqueda semántica. Selecciona ese modo "
                    "o publica una generación con BM25.",
                ) from None
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

    def retrieve_chat(params, top_k):
        from app.chat.retriever import CorpusRetriever

        with reader(params.index_generation, needs_model=params.mode != "lexical") as (
            client,
            pinned,
        ):
            try:
                retriever = CorpusRetriever(client, pinned, api.state.encoder, params, top_k)
                retriever.retrieve(params.q)
                return pinned, retriever.passages
            except SearchModeUnavailable:
                raise error(
                    409,
                    "search_mode_unavailable",
                    "Esta generación admite solo búsqueda semántica.",
                ) from None
            except QueryNotEncodable:
                raise error(
                    422,
                    "query_not_encodable",
                    "Reduce la longitud de la pregunta para procesarla con el modelo local.",
                ) from None

    @api.post(
        "/api/v1/chat",
        response_model=ChatResponse,
        tags=["Conversación"],
        responses={
            **unavailable,
            404: {"model": ErrorResponse, "description": "conversation_not_found"},
            409: {
                "model": ErrorResponse,
                "description": "generation_retired, search_mode_unavailable, "
                "conversation_generation_mismatch o request_id_conflict",
            },
            502: {
                "model": ErrorResponse,
                "description": "llm_failed: proveedor, salida estructurada o plazo total",
            },
            503: {
                "model": ErrorResponse,
                "description": "llm_unavailable, chat_history_unavailable, model_unavailable, "
                "corpus_unavailable o dependency_unavailable",
            },
        },
    )
    async def chat(request: ChatRequest):
        return await api.state.chat_service.answer(request)

    @api.get(
        "/api/v1/chat/{conversation_id}",
        response_model=ConversationResponse,
        tags=["Conversación"],
        responses={
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse, "description": "chat_history_unavailable"},
        },
    )
    async def conversation(
        conversation_id: UUID,
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ):
        return await api.state.chat_history.conversation(conversation_id, after, limit)

    return api


app = create_app()
