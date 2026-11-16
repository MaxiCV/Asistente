"""Contratos compartidos por API, CLI y manifiestos (SCRUM-11)."""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
GenerationId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
OpenAlexId = Annotated[str, StringConstraints(pattern=r"^https://openalex.org/W[0-9]+$")]


def canonical_doi(value: str) -> str:
    value = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
    import re

    if not re.fullmatch(r"10\.\d{4,9}/\S+", value):
        raise ValueError("DOI inválido")
    return value


Doi = Annotated[str, AfterValidator(canonical_doi)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Technology(StrEnum):
    CAMERA = "camara"
    WEARABLE = "vestible"
    AMBIENT = "ambiente"
    MIXED = "mixta"
    UNKNOWN = "ND"


class Evidence(StrEnum):
    LAB = "laboratorio"
    SIMULATED = "simulada"
    HOME = "real_hogar"
    MIXED = "mixta"
    UNKNOWN = "ND"


class ReviewRow(Contract):
    openalex_id: OpenAlexId
    snapshot_id: GenerationId
    decision: Literal["incluir", "excluir", "pendiente"]
    motivo: Text
    tecnologia: Technology
    evidencia: Evidence
    tiene_resumen: Literal["si", "no"]
    fecha_revision: date
    nota_evidencia: Text


class SourceIdentity(Contract):
    openalex_id: OpenAlexId
    snapshot_id: GenerationId
    retrieved_at: AwareDatetime


class Author(Contract):
    name: Text
    orcid: HttpUrl | None = None


class PatentSourceIdentity(Contract):
    source: Literal["epo_ops"] = "epo_ops"
    publication_id: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}\.[A-Z0-9]+\.[A-Z][0-9]?$")]
    snapshot_id: GenerationId
    retrieved_at: AwareDatetime
    applicants: list[Text] = Field(default_factory=list)


class PatentDocument(Contract):
    """Registro OPS seleccionable para el corpus de publicaciones y patentes."""

    schema_version: Literal[1] = 1
    document_type: Literal["patent"] = "patent"
    source: Literal["epo_ops"] = "epo_ops"
    publication_id: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}\.[A-Z0-9]+\.[A-Z][0-9]?$")]
    publication_date: date | None = None
    title: Text | None = None
    language: Text | None = None
    abstract: Text | None = None
    abstract_language: Text | None = None
    content_level: Literal["metadata", "abstract"]
    source_url: HttpUrl
    snapshot_id: GenerationId
    retrieved_at: AwareDatetime
    inventors: list[Text] = Field(default_factory=list)
    applicants: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def content_available(self):
        if (self.content_level == "abstract") != (self.abstract is not None):
            raise ValueError("content_level debe reflejar el resumen disponible")
        return self


class PatentFetchConfig(Contract):
    query: Text
    max_records: int = Field(default=25, ge=1, le=2000)
    page_size: int = Field(default=25, ge=1, le=100)
    max_requests: int = Field(default=100, ge=1, le=1000)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    request_interval_seconds: float = Field(default=6, ge=6, le=60)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_retry_wait_seconds: float = Field(default=60, ge=1, le=60)


class Document(Contract):
    schema_version: Literal[1] = 1
    document_id: UUID
    document_type: Literal["publication", "patent"] = "publication"
    publication_type: Text | None = None
    title: Text
    authors: list[Author] = Field(default_factory=list)
    publication_date: date | None = None
    language: Literal["es", "en"] | None = None
    doi: Doi | None = None
    source_url: HttpUrl
    abstract: Text | None = None
    content_level: Literal["metadata", "abstract"]
    identities: list[SourceIdentity | PatentSourceIdentity] = Field(min_length=1)
    technology: Technology = Technology.UNKNOWN
    evidence: Evidence = Evidence.UNKNOWN

    @model_validator(mode="after")
    def content_and_identity(self):
        if (self.content_level == "abstract") != (self.abstract is not None):
            raise ValueError("content_level debe reflejar el resumen disponible")
        expected = PatentSourceIdentity if self.document_type == "patent" else SourceIdentity
        if any(not isinstance(x, expected) for x in self.identities):
            raise ValueError("Procedencia incompatible con tipo documental")
        keys = [
            (x.snapshot_id, x.openalex_id if isinstance(x, SourceIdentity) else x.publication_id)
            for x in self.identities
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Identidades de origen repetidas")
        return self


class Passage(Contract):
    schema_version: Literal[1] = 1
    passage_id: UUID
    document_id: UUID
    position: int = Field(ge=0)
    text: Text
    token_count: int = Field(gt=0)
    text_sha256: Sha256
    publication_date: date | None = None
    document_type: Literal["publication", "patent"] = "publication"
    publication_type: Text | None = None


class EmbeddingConfig(Contract):
    model_id: Literal["intfloat/multilingual-e5-small"]
    revision: Revision
    dimensions: Literal[384] = 384
    max_tokens: Literal[512] = 512
    query_prefix: Literal["query: "] = "query: "
    passage_prefix: Literal["passage: "] = "passage: "
    normalize: Literal[True] = True
    distance: Literal["Cosine"] = "Cosine"


class ChunkingConfig(Contract):
    method: Literal["token-window-v1"] = "token-window-v1"
    max_tokens: int = Field(default=512, gt=0)
    overlap_tokens: int = Field(default=32, ge=0)
    include_title: Literal[True] = True

    @model_validator(mode="after")
    def valid_overlap(self):
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("El solapamiento debe ser menor que el presupuesto")
        return self


class FetchSearch(Contract):
    query: Text
    has_abstract: bool
    max_records: int = Field(ge=1, le=1000)


class FetchConfig(Contract):
    schema_version: Literal[1] = 1
    from_date: date = date(2020, 1, 1)
    languages: list[Literal["es", "en"]] = Field(default_factory=lambda: ["es", "en"], min_length=1)
    searches: list[FetchSearch] = Field(min_length=1, max_length=20)
    per_page: int = Field(default=50, ge=1, le=100)
    max_requests: int = Field(default=40, ge=1, le=500)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_retries: int = Field(default=3, ge=0, le=5)
    request_interval_seconds: float = Field(default=0.3, ge=0, le=30)
    max_retry_wait_seconds: float = Field(default=30, ge=1, le=60)


class SnapshotManifest(Contract):
    schema_version: Literal[1] = 1
    snapshot_id: GenerationId
    source: Literal["openalex"] = "openalex"
    status: Literal["complete", "incomplete"]
    searches: list[Text] = Field(min_length=1)
    from_date: date
    cutoff_date: date
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    record_count: int = Field(ge=0)
    works_sha256: Sha256 | None = None
    errors: list[Text] = Field(default_factory=list)
    fetch_config: FetchConfig | None = None
    request_count: int = Field(default=0, ge=0)
    duplicate_observations: int = Field(default=0, ge=0)
    quarantined_count: int = Field(default=0, ge=0)
    requests_sha256: Sha256 | None = None
    quarantine_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def valid_completion(self):
        if self.cutoff_date < self.from_date:
            raise ValueError("Intervalo de captura invertido")
        if self.finished_at and self.finished_at < self.started_at:
            raise ValueError("La captura termina antes de comenzar")
        if self.status == "complete" and (
            self.works_sha256 is None or self.finished_at is None or self.errors
        ):
            raise ValueError("Snapshot completo requiere hash, fecha final y ausencia de errores")
        if self.fetch_config:
            if (
                self.from_date != self.fetch_config.from_date
                or self.searches != [search.query for search in self.fetch_config.searches]
                or self.request_count > self.fetch_config.max_requests
            ):
                raise ValueError("Manifiesto incompatible con la configuración de captura")
            if self.status == "complete" and (
                self.requests_sha256 is None or self.quarantine_sha256 is None
            ):
                raise ValueError("Captura completa requiere hashes de solicitudes y cuarentena")
        return self


class Bm25Config(Contract):
    model: Literal["qdrant/bm25"] = "qdrant/bm25"
    server_version: Literal["1.20.0"] = "1.20.0"
    preprocessing: Literal["word-lowercase-no-stemming-v1"] = "word-lowercase-no-stemming-v1"
    k: Literal[1.2] = 1.2
    b: Literal[0.75] = 0.75
    avg_len: Literal[256] = 256


class GenerationManifest(Contract):
    schema_version: Literal[1] = 1
    generation_id: GenerationId
    status: Literal["validated"] = "validated"
    created_at: AwareDatetime
    documents_collection: Text
    passages_collection: Text
    snapshot_id: GenerationId
    snapshot_sha256: Sha256
    review_csv_sha256: Sha256
    config_sha256: Sha256
    embedding: EmbeddingConfig
    chunking: ChunkingConfig
    bm25: Bm25Config | None = None
    patent_selection_sha256: Sha256 | None = None
    document_count: int = Field(ge=0)
    passage_count: int = Field(ge=0)
    abstract_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    publication_types: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_generation(self):
        if self.documents_collection != f"documents_{self.generation_id}":
            raise ValueError("Colección documental ajena a la generación")
        if self.passages_collection != f"passages_{self.generation_id}":
            raise ValueError("Colección de fragmentos ajena a la generación")
        if self.abstract_count > self.document_count or self.passage_count < self.document_count:
            raise ValueError("Conteos de generación incoherentes")
        if self.chunking.max_tokens > self.embedding.max_tokens:
            raise ValueError("Fragmentación excede el presupuesto del modelo")
        if ("patent" in self.publication_types) != (self.patent_selection_sha256 is not None):
            raise ValueError("Patentes y selección de procedencia incoherentes")
        return self


class RetrievalParams(Contract):
    mode: Literal["semantic", "lexical", "hybrid"] = "semantic"
    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    date_from: date | None = None
    date_to: date | None = None
    document_type: Literal["publication", "patent", "all"] = "publication"
    publication_type: Text | None = None
    index_generation: GenerationId | None = None

    @model_validator(mode="after")
    def date_order(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from no puede ser posterior a date_to")
        return self


class SearchParams(RetrievalParams):
    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PublicationReceipt(Contract):
    generation_id: GenerationId
    manifest_sha256: Sha256
    published_at: AwareDatetime


class SearchHit(Contract):
    document: Document
    score: float = Field(allow_inf_nan=False)


class SearchResponse(Contract):
    mode: Literal["semantic", "lexical", "hybrid"] = "semantic"
    matched_document_count: int = Field(default=0, ge=0)
    index_generation: GenerationId
    results: list[SearchHit]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    has_more: bool
    filtered_document_count: int = Field(ge=0)


class DocumentResponse(Contract):
    index_generation: GenerationId
    document: Document


class RunRecord(Contract):
    schema_version: Literal[1] = 1
    run_id: GenerationId
    operation: Literal["fetch", "build", "publish", "rollback"]
    status: Literal["running", "succeeded", "failed"]
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    snapshot_id: GenerationId | None = None
    generation_id: GenerationId | None = None
    error_code: Text | None = None


class CorpusResponse(Contract):
    index_generation: GenerationId | None
    document_count: int = Field(ge=0)
    abstract_count: int = Field(ge=0)
    abstract_coverage: float = Field(ge=0, le=1)
    last_run: RunRecord | None = None
    manifest: GenerationManifest | None = None
    published_at: AwareDatetime | None = None
    publication_types: list[Text] = Field(default_factory=list)
    maintenance_status_unavailable: bool = False


class ErrorDetail(Contract):
    code: Text
    message: Text


class ErrorResponse(Contract):
    detail: ErrorDetail


class RequestValidationResponse(Contract):
    """Errores de validación de entrada emitidos por FastAPI."""

    detail: list[dict]


class PatentSelection(Contract):
    snapshot_id: GenerationId
    publication_id: Text
    reason: Text
    scope: Text


class PatentSelectionFile(Contract):
    records: list[PatentSelection] = Field(min_length=1)


class PatentSnapshotManifest(Contract):
    schema_version: Literal[1] = 1
    source: Literal["epo_ops"] = "epo_ops"
    snapshot_id: GenerationId
    status: Literal["complete", "incomplete"]
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    config: PatentFetchConfig | None = None
    record_count: int = Field(ge=0)
    duplicate_observations: int = Field(default=0, ge=0)
    files: dict[str, Sha256] = Field(default_factory=dict)
    error_code: Text | None = None
    requests: list[dict] = Field(default_factory=list)
    total_results_reported: int | None = Field(default=None, ge=0)
    stop_reason: Literal["exhausted", "record_limit"] | None = None

    @model_validator(mode="after")
    def valid_snapshot(self):
        import re

        if any(not re.fullmatch(r"page_[0-9]+\.xml|patents\.jsonl", name) for name in self.files):
            raise ValueError("Archivo de snapshot no permitido")
        if self.status == "complete" and (
            self.finished_at is None
            or self.error_code is not None
            or "patents.jsonl" not in self.files
            or not any(name.endswith(".xml") for name in self.files)
        ):
            raise ValueError("Snapshot OPS completo requiere archivos y fecha de cierre")
        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            raise ValueError("Intervalo de captura OPS invertido")
        return self


SearchMode = Literal["semantic", "lexical", "hybrid"]


class ChatConfig(Contract):
    provider: Literal["google-genai"] = "google-genai"
    model: Text = "gemini-3.5-flash-lite"
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    top_k: int = Field(default=5, ge=1, le=10)
    max_history_turns: int = Field(default=4, ge=0, le=20)
    max_prompt_chars: int = Field(default=40000, ge=2000, le=200000)
    timeout_seconds: float = Field(default=30, gt=0, le=60)
    operation_timeout_seconds: float = Field(default=60, gt=0, le=65)
    default_mode: SearchMode = "hybrid"


class ChatRequest(Contract):
    request_id: UUID
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    conversation_id: UUID | None = None
    mode: SearchMode | None = None
    document_type: Literal["publication", "patent", "all"] = "all"
    date_from: date | None = None
    date_to: date | None = None
    publication_type: Text | None = None
    index_generation: GenerationId | None = None

    @model_validator(mode="after")
    def valid_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from no puede ser posterior a date_to")
        return self

    def retrieval(self, default_mode):
        values = self.model_dump(exclude={"request_id", "question", "conversation_id", "mode"})
        return RetrievalParams(q=self.question, mode=self.mode or default_mode, **values)


class Citation(Contract):
    marker: int = Field(ge=1, le=10)
    document_id: UUID
    passage_id: UUID
    title: Text
    document_type: Literal["publication", "patent"]
    content_level: Literal["abstract", "metadata"]
    source_url: HttpUrl
    doi: Doi | None = None
    publication_id: Text | None = None
    publication_date: date | None = None


class ContextPassage(Contract):
    rank: int = Field(ge=1, le=10)
    document_id: UUID
    passage_id: UUID
    text_sha256: Sha256
    score: float = Field(allow_inf_nan=False)
    content_level: Literal["abstract", "metadata"]
    cited: bool


class LlmAnswer(Contract):
    status: Literal["answered", "insufficient_evidence"]
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16000)]
    cited_sources: list[int] = Field(max_length=10)


CITATION_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def citation_markers(text: str) -> set[int]:
    # Validate every numeric reference, including grouped references. Unsupported
    # ranges or malformed brackets must not bypass membership checks.
    for candidate in re.findall(r"\[\s*\d[^\]\n]*(?:\]|$)", text):
        if not CITATION_MARKER.fullmatch(candidate):
            raise ValueError("Formato de cita no admitido")
    return {int(n) for group in CITATION_MARKER.findall(text) for n in group.split(",")}


class ChatResponse(Contract):
    conversation_id: UUID
    turn_id: UUID
    turn_index: int = Field(ge=1)
    index_generation: GenerationId
    mode: SearchMode
    status: Literal["answered", "insufficient_evidence"]
    evidence_level: Literal["abstract", "metadata_only", "mixed", "none"]
    answer: Text
    citations: list[Citation]
    context: list[ContextPassage]
    model: Text | None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def valid_citations(self):
        context = {c.rank: c for c in self.context}
        markers = {c.marker for c in self.citations}
        if citation_markers(self.answer) != markers:
            raise ValueError("Los marcadores del texto no coinciden con las citas")
        if len(context) != len(self.context) or len(markers) != len(self.citations):
            raise ValueError("Contexto o citas duplicadas")
        for citation in self.citations:
            passage = context.get(citation.marker)
            if (
                passage is None
                or not passage.cited
                or (passage.document_id, passage.passage_id, passage.content_level)
                != (citation.document_id, citation.passage_id, citation.content_level)
            ):
                raise ValueError("Cita ajena al contexto")
        if {c.rank for c in self.context if c.cited} != markers:
            raise ValueError("Marcadores incoherentes")
        if self.status == "answered" and (not self.citations or self.evidence_level == "none"):
            raise ValueError("Respuesta sin evidencia citada")
        if self.citations:
            levels = {c.content_level for c in self.citations}
            expected = (
                "mixed"
                if len(levels) > 1
                else ("abstract" if "abstract" in levels else "metadata_only")
            )
            if self.evidence_level != expected:
                raise ValueError("Nivel de evidencia incoherente")
        if self.status == "insufficient_evidence" and (
            self.citations or self.evidence_level != "none"
        ):
            raise ValueError("Evidencia insuficiente no debe presentarse como respuesta respaldada")
        return self


class ChatTurn(Contract):
    schema_version: Literal[1] = 1
    request: ChatRequest
    request_sha256: Sha256
    response: ChatResponse
    rejection_reason: Text | None = None

    @model_validator(mode="after")
    def valid_identity(self):
        if self.request.request_id != self.response.turn_id:
            raise ValueError("Identidad del turno incoherente")
        if (
            self.request.conversation_id
            and self.request.conversation_id != self.response.conversation_id
        ):
            raise ValueError("Conversación incoherente")
        return self


class ConversationResponse(Contract):
    conversation_id: UUID
    index_generation: GenerationId
    turns: list[ChatTurn]
    next_cursor: int | None = Field(default=None, ge=1)
