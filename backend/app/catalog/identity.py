from uuid import NAMESPACE_URL, UUID, uuid5

from app.contracts import canonical_doi


def document_id(openalex_id: str, doi: str | None = None) -> UUID:
    # La ingesta resuelve conflictos antes de asignar esta identidad canónica.
    key = f"doi:{canonical_doi(doi)}" if doi else openalex_id
    return uuid5(NAMESPACE_URL, f"asistente:document:{key}")


def passage_id(document: UUID, text_sha256: str, config_sha256: str, position: int) -> UUID:
    return uuid5(document, f"{text_sha256}:{config_sha256}:{position}")
