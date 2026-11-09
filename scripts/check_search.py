"""Read-only HTTP smoke and latency check against the local demonstration."""

import argparse
import json
import platform
import statistics
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", default="http://127.0.0.1:5173/api/v1")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
queries = [
    "detección de caídas con cámaras en el hogar",
    "wearable fall detection for older adults",
    "sensores ambientales para identificar una caída",
    "deep learning fall detection without cameras",
    "detección de caídas mediante acelerómetros",
    "human fall detection using computer vision",
    "privacidad en sistemas de detección de caídas",
    "multimodal fall detection at home",
    "caídas simuladas y detección en tiempo real",
    "fall detection with radar sensors",
    "clasificación de caídas con redes neuronales",
    "low power wearable fall detector",
    "detección de caídas usando pose humana",
    "fall detection from skeleton sequences",
    "sensores inalámbricos para detectar caídas",
    "home fall detection with machine learning",
    "diferenciar caídas de actividades cotidianas",
    "older adult fall detection laboratory study",
    "redes convolucionales para detectar caídas",
    "real time fall detection with depth cameras",
]


def summary(values):
    return {
        "n": len(values),
        "p50_ms": round(statistics.median(values), 2),
        "p95_ms": round(float(np.percentile(values, 95)), 2),
        "samples_ms": [round(value, 2) for value in values],
    }


with httpx.Client(base_url=args.url.rstrip("/") + "/", timeout=45) as client:
    readiness = client.get("ready")
    readiness.raise_for_status()
    corpus = client.get("corpus").json()
    generation = corpus["index_generation"]

    def search(query, **params):
        started = perf_counter()
        response = client.get(
            "documents",
            params={
                "q": query,
                "page_size": 10,
                "index_generation": generation,
                **params,
            },
        )
        response.raise_for_status()
        result = response.json()
        elapsed = (perf_counter() - started) * 1000
        assert result["index_generation"] == generation
        assert len({hit["document"]["document_id"] for hit in result["results"]}) == len(
            result["results"]
        )
        return result, elapsed

    first, first_ms = search("comprobación inicial de búsqueda local")
    uncached = [search(query)[1] for query in queries]
    cached = [search(query)[1] for query in queries]
    page1, _ = search(queries[0])
    page2, _ = search(queries[0], page=2)
    ids1 = {hit["document"]["document_id"] for hit in page1["results"]}
    assert not ids1.intersection(hit["document"]["document_id"] for hit in page2["results"])
    all_results, _ = search(queries[0], page_size=100)
    assert len(all_results["results"]) == corpus["document_count"]
    metadata = next(
        hit["document"] for hit in all_results["results"] if hit["document"]["abstract"] is None
    )
    detail = client.get(
        f"documents/{metadata['document_id']}", params={"index_generation": generation}
    )
    detail.raise_for_status()
    assert detail.json()["document"]["content_level"] == "metadata"
    empty, _ = search(queries[0], date_from="2099-01-01")
    assert empty["filtered_document_count"] == 0 and empty["results"] == []
    invalid = client.get(
        "documents", params={"q": "fall", "date_from": "2025-01-01", "date_to": "2020-01-01"}
    )
    assert invalid.status_code == 422
    retired = client.get(
        "documents", params={"q": "fall", "index_generation": "nonexistent_s13_check"}
    )
    assert retired.status_code == 409

result = {
    "checked_at": datetime.now(UTC).isoformat(),
    "generation": generation,
    "document_count": corpus["document_count"],
    "abstract_count": corpus["abstract_count"],
    "functional_checks_passed": True,
    "quality_evaluated": False,
    "transport": "HTTP through Vite proxy, response body and JSON decoded; "
    "sequential; model already loaded",
    "first_http_request_ms": round(first_ms, 2),
    "distinct_queries_model_warm": summary(uncached),
    "repeated_queries_embedding_cache_warm": summary(cached),
    "cache": "128 query embeddings per API process. Distinct-query pass assumes a newly "
    "started API; OS file cache not cleared.",
    "client_platform": platform.platform(),
    "client_processor": platform.processor(),
    "queries": queries,
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: value for key, value in result.items() if key != "queries"}, indent=2))
