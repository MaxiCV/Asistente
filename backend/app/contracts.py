"""Contratos compartidos por API, CLI y manifiestos (SCRUM-11)."""

from __future__ import annotations

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


class Document(Contract):
    schema_version: Literal[1] = 1
    document_id: UUID
    document_type: Literal["publication"] = "publication"
    publication_type: Text | None = None
    title: Text
    authors: list[Author] = Field(default_factory=list)
    publication_date: date | None = None
    language: Literal["es", "en"] | None = None
    doi: Doi | None = None
    source_url: HttpUrl
    abstract: Text | None = None
    content_level: Literal["metadata", "abstract"]
    identities: list[SourceIdentity] = Field(min_length=1)
    technology: Technology = Technology.UNKNOWN
    evidence: Evidence = Evidence.UNKNOWN

    @model_validator(mode="after")
    def content_and_identity(self):
        if (self.content_level == "abstract") != (self.abstract is not None):
            raise ValueError("content_level debe reflejar el resumen disponible")
        keys = [(x.snapshot_id, x.openalex_id) for x in self.identities]
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
    document_type: Literal["publication"] = "publication"
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
        return self


class SearchParams(Contract):
    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    date_from: date | None = None
    date_to: date | None = None
    document_type: Literal["publication"] = "publication"
    publication_type: Text | None = None
    index_generation: GenerationId | None = None

    @model_validator(mode="after")
    def date_order(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from no puede ser posterior a date_to")
        return self


class PublicationReceipt(Contract):
    generation_id: GenerationId
    manifest_sha256: Sha256
    published_at: AwareDatetime


class SearchHit(Contract):
    document: Document
    score: float = Field(allow_inf_nan=False)


class SearchResponse(Contract):
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
