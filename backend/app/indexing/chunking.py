"""Ventanas por tokens que conservan el texto original, con título en cada fragmento."""

import hashlib

from app.catalog.identity import passage_id
from app.contracts import ChunkingConfig, Document, Passage


def make_passages(document: Document, encoder, config: ChunkingConfig, config_hash: str):
    prefix = encoder.config.passage_prefix
    tokenizer = encoder.model.tokenizer

    def count(text):
        return len(tokenizer.encode(prefix + text, truncation=False))

    def passage(text, position):
        text = text.strip()
        digest = hashlib.sha256(text.encode()).hexdigest()
        return Passage(
            passage_id=passage_id(document.document_id, digest, config_hash, position),
            document_id=document.document_id,
            position=position,
            text=text,
            token_count=count(text),
            text_sha256=digest,
            publication_date=document.publication_date,
            publication_type=document.publication_type,
        )

    full = document.title + ("\n\n" + document.abstract if document.abstract else "")
    if count(full) <= config.max_tokens:
        return [passage(full, 0)]
    heading = document.title + "\n\n"
    budget = config.max_tokens - count(heading) - 2
    if not document.abstract or budget <= config.overlap_tokens:
        raise ValueError("Título demasiado largo para fragmentar sin perder contenido")
    offsets = tokenizer(
        document.abstract,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
    )["offset_mapping"]
    chunks = []
    start = 0
    while start < len(offsets):
        end = min(start + budget, len(offsets))
        left = 0 if start == 0 else offsets[start][0]
        while end > start:
            right = len(document.abstract) if end == len(offsets) else offsets[end][0]
            text = heading + document.abstract[left:right]
            if count(text) <= config.max_tokens:
                break
            end -= 1
        if end <= start or (end < len(offsets) and end - start <= config.overlap_tokens):
            raise ValueError("No se puede fragmentar con el solapamiento configurado")
        chunks.append(passage(text, len(chunks)))
        if end == len(offsets):
            break
        start = end - config.overlap_tokens
    if not chunks:
        raise ValueError("Texto no fragmentable")
    return chunks
