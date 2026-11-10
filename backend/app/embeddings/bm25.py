"""BM25 nativo en el servidor local fijado; sin modelos ni servicios externos."""

from qdrant_client import models

from app.contracts import Bm25Config


def bm25_document(text: str, config: Bm25Config) -> models.Document:
    return models.Document(
        text=text,
        model=config.model,
        options={
            "k": config.k,
            "b": config.b,
            "avg_len": config.avg_len,
            "tokenizer": "word",
            "lowercase": True,
            "ascii_folding": False,
            "stemmer": {"type": "none"},
            "stopwords": {"languages": [], "custom": []},
        },
    )


def check_bm25_server(client, config: Bm25Config) -> None:
    if client.info().version != config.server_version:
        raise ValueError(f"BM25 requiere el servidor Qdrant fijado {config.server_version}")


def validate_bm25_collection(client, collection: str) -> None:
    sparse = client.get_collection(collection).config.params.sparse_vectors or {}
    if "bm25" not in sparse or sparse["bm25"].modifier != models.Modifier.IDF:
        raise ValueError("La colección requiere vector bm25 con modificador IDF")
