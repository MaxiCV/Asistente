import json
import os
from functools import lru_cache
from pathlib import Path
from threading import Lock
from time import perf_counter

from app.contracts import EmbeddingConfig
from app.core.config import Settings
from app.core.files import atomic_json, sha256_file

MODEL_FILES = [
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "tokenizer.model",
    "sentencepiece.bpe.model",
    "vocab.txt",
    "model.safetensors",
    "1_Pooling/config.json",
]


def model_path(settings: Settings, config: EmbeddingConfig) -> Path:
    return settings.data_dir / "models" / "multilingual-e5-small" / config.revision


def download_model(settings: Settings, config: EmbeddingConfig) -> dict:
    # Este es el único comando que permite acceso al Hub; la API carga solo rutas locales.
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["TRANSFORMERS_OFFLINE"] = "0"
    os.environ["HF_HOME"] = str(settings.data_dir / "cache/huggingface")
    from huggingface_hub import snapshot_download

    target = model_path(settings, config)
    snapshot_download(
        repo_id=config.model_id,
        revision=config.revision,
        local_dir=target,
        allow_patterns=MODEL_FILES,
        token=False,
    )
    hashes = {name: sha256_file(target / name) for name in MODEL_FILES if (target / name).is_file()}
    required = {
        "model.safetensors",
        "config.json",
        "tokenizer.json",
        "modules.json",
        "1_Pooling/config.json",
    }
    if not required.issubset(hashes):
        raise ValueError("Descarga incompleta del modelo")
    receipt = {"model_id": config.model_id, "revision": config.revision, "files": hashes}
    atomic_json(target / "download.json", receipt)
    return {"model_id": config.model_id, "revision": config.revision, "files": len(hashes)}


def verify_model_files(settings: Settings, config: EmbeddingConfig) -> Path:
    target = model_path(settings, config)
    receipt = json.loads((target / "download.json").read_text("utf-8"))
    if receipt.get("model_id") != config.model_id or receipt.get("revision") != config.revision:
        raise ValueError("Revisión local del modelo incompatible")
    hashes = receipt.get("files", {})
    required = {
        "model.safetensors",
        "config.json",
        "tokenizer.json",
        "modules.json",
        "1_Pooling/config.json",
    }
    if not required.issubset(hashes) or not set(hashes).issubset(MODEL_FILES):
        raise ValueError("Manifiesto local de pesos inválido")
    for name, expected in hashes.items():
        if sha256_file(target / name) != expected:
            raise ValueError(f"Archivo de modelo alterado: {name}")
    return target


class LocalEncoder:
    def __init__(self, settings: Settings, config: EmbeddingConfig):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HOME"] = str(settings.data_dir / "cache/huggingface")
        target = verify_model_files(settings, config)
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(settings.embedding_threads)
        self.lock = Lock()
        self.query_vector = lru_cache(maxsize=128)(self._query_vector)
        self.config = config
        self.model = SentenceTransformer(
            str(target),
            device=settings.embedding_device,
            local_files_only=True,
            trust_remote_code=False,
        )
        self.model.max_seq_length = config.max_tokens
        if self.model.get_embedding_dimension() != config.dimensions:
            raise ValueError("Dimensiones de modelo incompatibles")

    def encode(self, texts: list[str], *, query: bool = False):
        prefix = self.config.query_prefix if query else self.config.passage_prefix
        prepared = [prefix + text for text in texts]
        lengths = [len(self.model.tokenizer.encode(text, truncation=False)) for text in prepared]
        if any(length > self.config.max_tokens for length in lengths):
            raise ValueError("Texto excede el presupuesto; fragmentar antes de vectorizar")
        with self.lock:
            return self.model.encode(
                prepared,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

    def _query_vector(self, text: str) -> tuple[float, ...]:
        return tuple(float(x) for x in self.encode([text], query=True)[0])


def check_model(settings: Settings, config: EmbeddingConfig) -> dict:
    import numpy as np

    started = perf_counter()
    encoder = LocalEncoder(settings, config)
    load_seconds = perf_counter() - started
    started = perf_counter()
    vectors = encoder.encode(
        ["detección de caídas en el hogar", "fall detection at home"], query=True
    )
    if vectors.shape != (2, config.dimensions) or not np.isfinite(vectors).all():
        raise ValueError("Salida de embeddings inválida")
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5):
        raise ValueError("Embeddings sin normalización")
    return {
        "offline": True,
        "model_id": config.model_id,
        "revision": config.revision,
        "dimensions": config.dimensions,
        "functional_samples": 2,
        "load_seconds": round(load_seconds, 3),
        "encode_seconds": round(perf_counter() - started, 3),
        "quality_evaluated": False,
    }
