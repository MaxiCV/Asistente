"""Real-model pilot and recovery drill. Writes only to the separate recovery Qdrant."""

import json
from contextlib import closing
from datetime import UTC, datetime

import httpx
from app.catalog.generations import pin_generation
from app.core.config import ROOT, Settings, embedding_config
from app.core.files import atomic_json
from app.embeddings.local import LocalEncoder
from app.indexing.build import all_points, build_generation
from app.indexing.publish import publish_generation
from qdrant_client import QdrantClient


def points(client, collection):
    return {
        str(p.id): {"payload": p.payload, "vector": p.vector}
        for p in all_points(client, collection, vectors=True)
    }


def main():
    config = embedding_config()
    settings = Settings(
        _env_file=None,
        ASISTENTE_DATA_DIR=ROOT / "data/recovery/restored/data",
        qdrant_url="http://127.0.0.1:6335",
    )
    with (
        closing(QdrantClient(url="http://127.0.0.1:6333", timeout=60)) as original,
        closing(QdrantClient(url=settings.qdrant_url, timeout=60)) as recovered,
        httpx.Client(base_url="http://127.0.0.1:5174/api/v1", timeout=60) as api,
    ):
        old = pin_generation(recovered, settings.data_dir, config)
        original_aliases = original.get_aliases().model_dump()
        originals = {}
        for collection in (old.documents_collection, old.passages_collection):
            originals[collection] = points(original, collection)
            assert originals[collection] == points(recovered, collection)
        response = api.get("/ready")
        response.raise_for_status()
        encoder = LocalEncoder(settings, config)
        generation = "s14_pilot_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        manifest = build_generation(
            recovered,
            settings,
            config,
            generation,
            settings.data_dir / "snapshots/openalex_20261105_s12",
            ROOT / "corpus/revision_piloto.csv",
            lambda *_: encoder,
        )
        assert manifest["document_count"] == 20 and manifest["abstract_count"] == 18
        try:
            publish_generation(recovered, settings, config, generation)
            corpus = api.get("/corpus").json()
            assert corpus["index_generation"] == generation and corpus["document_count"] == 20
            queries = []
            for query in ("detección de caídas en el hogar", "wearable fall detection at home"):
                response = api.get("/documents", params={"q": query, "page_size": 100})
                response.raise_for_status()
                body = response.json()
                assert body["index_generation"] == generation
                ids = [r["document"]["document_id"] for r in body["results"]]
                assert len(ids) == len(set(ids)) == 20
                queries.append({"query": query, "unique_documents": len(ids)})
        finally:
            publish_generation(recovered, settings, config, old.generation_id, rollback=True)
        assert api.get("/corpus").json()["document_count"] == 100
        assert original.get_aliases().model_dump() == original_aliases
        for collection, expected in originals.items():
            assert points(original, collection) == expected
        evidence = {
            "checked_at": datetime.now(UTC).isoformat(),
            "qdrant_version": recovered.info().version,
            "restored_generation": old.generation_id,
            "all_payloads_and_vectors_equal": True,
            "original_unchanged": True,
            "pilot": manifest,
            "queries": queries,
            "rollback_restores_100_documents": True,
            "quality_evaluated": False,
        }
        atomic_json(ROOT / "docs/evidence/scrum-14-recovery.json", evidence)
        print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
